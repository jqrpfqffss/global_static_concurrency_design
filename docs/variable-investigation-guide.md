# 真实变量排查案例：从报告读写证据到修复思路

先按[一条命令教程](one-command-tutorial.md)生成 `serial - continue/.ecra/index.html`，再照本页练习。本示例的已登记配置只排查 Core/Src、Core/Inc，排除第三方自有变量（新工程初始化默认包含整个工程，再排除常见第三方目录）；调用链上下文 ID 由当前配置自动生成，名称可能与历史示例不同。下面的源码行号以原始注入样例为参考，修改源码后按函数名和表达式查找。

## 1. 跟着排查第一个问题：`pending_events` 为什么丢事件

### 1.1 在报告里找到变量

1. 点击“全部目标变量”。
2. 在页面顶部标着“搜索”的输入框中输入 `pending_events`，用页面自己的搜索框，不是浏览器的地址栏。
3. “筛选”保持“全部变量”，“文件”保持“全部文件”。
4. 在“全部全局变量与 static 变量”表里，找到定义位于 `Core/Src/serial_service.c:6` 的记录。
5. 点击该行“变量属性、全部访问与调用链”。

这个变量的真实定义是：

```c
static volatile uint32_t pending_events;
```

`static` 表示这个变量属于当前 C 文件；并不意味着只有一个执行环境能访问它。该文件里的函数仍然可以分别被主循环和中断调用。

`volatile` 也没有把“读出、计算、写回”变成一个不可打断的事务。例如 `pending_events |= 1U` 仍需要读取旧值并写入新值；它不是锁。关于 volatile 的限制可参见 [GCC 官方说明](https://gcc.gnu.org/onlinedocs/gcc/Volatiles.html)。

### 1.2 把读写位置对应到源码

在展开的访问表中，先找下面四条。行号以本次源码为准，后续编辑后可以按函数名和表达式定位：

| 文件内位置 | 函数 | 代码 | 报告标记 | 实际作用 |
|---|---|---|---|---|
| 第 55 行 | `Service_Rx` | `pending_events \|= 1U;` | 读改写（`RMW`） | 记下“收到串口数据”事件 |
| 第 85 行 | `Service_Sample` | `pending_events \|= 2U;` | 读改写（`RMW`） | 记下“定时采样”事件 |
| 第 110 行 | `Service_Poll` | `uint32_t snapshot = pending_events;` | 读取（`READ`） | 主循环把事件位图读到局部快照 |
| 第 118 行 | `Service_Poll` | `pending_events = 0;` | 写入（`WRITE`） | 主循环处理后清空共享位图 |

`READ` 是读，`WRITE` 是写，`RMW` 是先读旧值、修改、再写回。`|=` 和 `++` 都属于读改写操作。如果看到 `ADDRESS_TAKEN`，它只是取地址，不等于已经读写了该地址指向的数据。

在 VS Code 按 `Ctrl+P`，输入 `serial - continue/Core/Src/serial_service.c` 并打开；按 `Ctrl+G` 输入 `110` 可以直接跳到当前读取位置。浏览器显示的源码位置是定位依据，不必假设点击它一定能自动打开 IDE。

### 1.3 确定谁会打断谁

查看访问表“上下文 → 最短证据调用链”一列，点击主循环或中断名称后的“→ 调用链”展开具体函数和源码位置。每条入口分别折叠，便于先对比全部读写语句。先核对这三条真实路径：

```text
主循环：
main → Service_Poll → 读取 pending_events / 清零 pending_events

USART2 接收中断：
USART2_IRQHandler → HAL_UART_IRQHandler → UART_Receive_IT
→ HAL_UART_RxCpltCallback → Service_Rx → pending_events |= 1U

TIM2 定时器中断：
TIM2_IRQHandler → Service_Sample → pending_events |= 2U
```

可以分别打开三个文件交叉检查：

- `Core/Src/main.c`：裸机 `while (1)` 中调用 `Service_Poll()`；接收回调里有 `if (huart == &huart2) Service_Rx(cli.rx_byte);`。
- `Core/Src/stm32f1xx_it.c`：`USART2_IRQHandler()` 调用 HAL；`TIM2_IRQHandler()` 调用 `Service_Sample()`。
- `Core/Src/serial_service.c`：`Service_Init()` 配置并启用 TIM2/TIM3；`Service_Poll()` 读取和清空事件位图。

报告还可能给 `Service_Rx` 列出 USART1、DMA1 Channel4/5 等保守传播路径。**不能据此说这些入口实际上都会执行 `Service_Rx`。** 必须结合回调中的 `huart == &huart2` 条件和实际句柄核对。工具对 HAL 分发和指针的保守分析会多列候选路径。

下一个交错例子只需要已经明确的 `main` 和 `TIM2` 两条路径成立，不依赖那些待排除的路径。

如果想看某次访问的更多来路，可在变量详情里继续展开“展开所有相关调用边（含多路径、递归及边的来源）”。每个上下文显示的一条最短链不是全部运行路径的穷举。

### 1.4 用一张时间表看懂错误

假设串口事件已经到达，初始 `pending_events = 1`。二进制 `01` 表示串口事件，`10` 表示采样事件，`11` 表示两个事件都在等待处理。

| 顺序 | 正在运行的代码 | 操作 | 共享 `pending_events` | 主循环的 `snapshot` |
|---|---|---|---|---|
| 1 | 主循环 `Service_Poll` | 读取 `snapshot = pending_events` | `01` | `01` |
| 2 | TIM2 中断抢占主循环 | 执行 `pending_events \|= 2U` | `11` | 仍为 `01` |
| 3 | 中断返回，主循环继续 | 根据旧快照处理串口事件 | `11` | `01` |
| 4 | 主循环 | 执行 `pending_events = 0` | `00` | `01` |
| 5 | 下一轮主循环 | 再读事件位图 | `00` | `00` |

**结果：TIM2 新加入的采样事件被主循环清掉了，但主循环从未按这个事件执行处理。** 第 2 步发生在快照读取之后，因此旧 `snapshot` 看不到它；第 4 步却把共享变量中的新位也清掉了。

此处中断并不需要与主循环在两个 CPU 上同时执行。单核上的“读完后被打断，回来后继续写”就足以造成错误。

### 1.5 回到风险表核对规则

点击“变量风险结论”，找到同一个 `pending_events`，先看“疑似并发风险”标签和直接展示的关键读写，再展开“展开排查证据与处理步骤”。这里先显示每条规则的中文含义和核对动作；继续展开“风险依据、并发关系与保护证据”，可以核对入口组合和保护字段。本次命中的规则包括：

| 规则 | 在本例中的意思 |
|---|---|
| `GS-FILE-STATIC-SHARED` | 文件内 static 被多个上下文访问 |
| `GS-MULTI-CONTEXT` | 主循环和中断等多个上下文参与访问 |
| `GS-MULTI-WRITER` | 不止一处执行环境写这个变量 |
| `GS-RMW-INTERLEAVE` | 读改写之间可能发生交错 |
| `GS-STALE-SNAPSHOT` | 读取快照后的处理与后续共享状态修改需要核对 |

规则用来指出排查方向；上面的源码、可达路径和交错过程才构成具体问题的解释。查找时优先使用变量名和定义文件，风险 ID 以当前报告为准。

### 1.6 写下第一条排查记录

可以在候选详情底部点击“复制排查记录模板”，再参考下面这段补全你自己的问题记录：

```text
变量：serial_service.c::pending_events，文件级 static，volatile uint32_t。
范围：serial - continue 裸机 Debug 配置。
读写：Service_Poll 读后清零；Service_Rx 设置串口位；Service_Sample 设置采样位。
路径：main → Service_Poll；TIM2_IRQHandler → Service_Sample；另有 USART2 接收路径。
问题：主循环取快照后、清零前发生 TIM2 更新，会清除尚未消费的采样事件。
保护：该读快照/清零事务没有共同临界区。
结论依据：当前源码和上述交错推演；还没有做目标板复现。
后续：统一保护事件发布和取走操作；重扫、复核，并验证事件不再丢失。
```

到这里，第一项排查已经有了明确结果。下一步把模型结论和这份人工证据对照，而不是只看一个红色标签。

## 2. 用同样的方法检查 DMA、保护范围和同名 static

这一节继续使用裸机 `index.html`。每换一个变量，先点“清除筛选”，再输入新的变量名，展开“变量属性、全部访问与调用链”。

### 2.1 `tx_frame`：DMA 还在读取，CPU 就修改缓冲区

搜索 `tx_frame`，确认定义位于 `Core/Src/serial_transport.c:6`。打开这个源文件，找到 `Transport_Poll()`：

```c
uint32_t n = completed_frames;
if (HAL_UART_Transmit_DMA(&telemetry_uart, tx_frame, sizeof(tx_frame)) == HAL_OK)
    memset(tx_frame, (int)n, sizeof(tx_frame));
```

先不急着读所有 HAL 代码，按下面顺序核对：

1. `tx_frame` 被传给 `HAL_UART_Transmit_DMA`，作为发送数据的来源。
2. `HAL_OK` 表示该调用成功启动发送，不是“整个数组已经传输完毕”。工程后面还有 `Transport_TxComplete()` 完成回调，可沿调用链继续检查。
3. CPU 紧接着执行 `memset`，改写的正是刚交给 DMA 的数组。
4. 在报告“任务、中断与硬件上下文”中核对 `dma_tx`，再看变量访问里的 CPU 写入和 DMA 读取证据。

| 顺序 | CPU | DMA |
|---|---|---|
| 1 | 启动发送 `tx_frame` | 开始读取数组 |
| 2 | `memset` 改写同一个数组 | 传输可能还没读到后面的字节 |
| 3 | 继续执行主循环 | 后面的字节可能来自改写后的内容 |

**排查结论：存在发送缓冲区所有权冲突，需要保证 DMA 使用期间 CPU 不复用它。** 实际哪一字节受影响要结合 DMA 传输时序验证，静态报告不能给出每次传输的具体损坏位置。

修复时通常先填好缓冲区，再启动 DMA，直到确认完成才允许重用；若要双缓冲，就要明确每块缓冲区何时属于 CPU、何时属于 DMA。仅给数组加 `volatile`，或仅屏蔽完成中断，都没有让正在工作的 DMA 停止读取。

### 2.2 `rx_frame`：通知到了，不代表 DMA 停止覆盖

搜索 `rx_frame`，找到同一文件第 7 行的数组。在 `Transport_Init()` 中看这两点：

```c
telemetry_rx_dma.Init.Mode = DMA_CIRCULAR;
/* 中间还有其他初始化代码 */
if (HAL_UART_Receive_DMA(&telemetry_uart, rx_frame, sizeof(rx_frame)) != HAL_OK) Error_Handler();
```

在 `Transport_Poll()` 中又有：

```c
if (rx_ready) {
    for (unsigned i = 0; i < sizeof(rx_frame); ++i) consumed_checksum += rx_frame[i];
    rx_ready = 0;
    completed_frames = n + 1U;
}
```

`rx_ready` 只是软件通知位。循环 DMA 仍可能进入下一轮，覆盖 CPU 正在校验的数组。报告中 `dma_rx` 与 CPU 读取共同出现后，应进一步检查稳定数据区、半满/全满位置、读写游标或复制快照的协议。

记录时把两个问题分开：`rx_ready` 的读后清零可能丢通知；`rx_frame` 的生命周期可能导致校验混入不同轮的数据。修好一个不代表另一个也修好了。

### 2.3 `guarded_total` 与 `restore_count`：同样有“关中断”，保护效果不同

在 `serial_service.c` 中，`guarded_total` 的主循环更新为：

```c
saved_mask = __get_PRIMASK();
__disable_irq();
guarded_total++;
__set_PRIMASK(saved_mask);
```

而 `restore_count` 是：

```c
__disable_irq();
Service_EnableLine();
restore_count++;
__set_PRIMASK(saved_mask);
```

继续进入 `Service_EnableLine()`，能看到它调用了 `__enable_irq()`。也就是说，`restore_count++` 执行前，中断已经又被打开了。

对这两项分别核对所有写入者、受保护的具体访问、保护区中调用的辅助函数。`guarded_total` 是工程里用于对照的保护场景；静态工具仍可能保守列出候选，不能因为候选没有消失就断言保护无效。

报告中的 `PARTIAL` 只表示发现了相关保护 API 证据，尚未证明所有路径都在正确保护范围内；`DECLARED_ONLY` 表示来自配置声明。它们都不是“已验证安全”。

CMSIS 中 `__disable_irq` 通过 PRIMASK 屏蔽可配置优先级的异常；恢复先前 PRIMASK 能保留进入前的中断状态。它不停止 DMA，也不屏蔽 NMI/HardFault。具体语义见 [CMSIS 内核寄存器接口](https://arm-software.github.io/CMSIS_6/main/Core/group__Core__Register__gr.html)。

### 2.4 两个 `status` 不是一个变量

搜索 `status` 时会出现其他名字含 status 的记录，重点对照这两个定义：

- `Core/Src/serial_service.c:21` 的 `static volatile uint32_t status`。
- `Core/Src/service_accounting.c:3` 的 `static volatile uint32_t status`。

它们名字相同，但属于不同 C 文件，应分别记录定义文件和唯一变量 ID。不能把第一个的写入者拼到第二个上。

再搜索 `service_epoch`：它定义在头文件 `Core/Inc/service_inline.h`，被不同 C 文件包含后形成独立 static 实例。此时连“定义文件 + 行号”都可能一样，还必须看变量详情中的“所属编译单元”和唯一 ID。

### 2.5 安全对照也要看实际证据

搜索 `private_poll_count` 和 `frame_limits`。在当前裸机业务里，前者在 `Service_Poll()` 使用，后者是只读表。报告保留这些变量，便于检查全量清单。

本次 `private_poll_count` 仍被保守筛为 `REVIEW_REQUIRED`；这不等于发现了一个真实的多任务写入错误。应打开具体候选原因，确认它是否只是未知路径、保守指针或其他待补证据。`frame_limits` 的盘点标签是 `CONST_INVENTORY`。

这一节练习的重点是：**既能用证据解释真正的风险，也能说明候选为什么需要进一步排除。**

## 3. 找到问题后，怎样修复并复查

### 3.1 先形成完整的修改方案

以下用 `pending_events` 示范修复思路。**本教程没有把这些修改写进原固件；原工程继续保留注入缺陷。** 如果要动手练习，请先用自己的版本管理或完整备份保留原文件，再应用修改。历史验收矩阵检查的是原先注入的缺陷，改完源码后其哈希及预期检查可能失效，不能据此认定新代码错误。

本例需要解决两类交错：

1. 主循环“取走事件”和中断“加入事件”交错，导致第 1 节的新事件被清除。
2. 串口与定时器两个发布者都用 `|=`，发布者之间的读改写也需要统一保护。

只给最后一条 `pending_events = 0` 加保护不够，保护必须覆盖完整事务。

针对本例单核、普通可屏蔽中断访问的前提，可以在 `serial_service.c` 中、`Service_Rx()` 之前加入下面两个辅助函数：

```c
static void Service_PostEvents(uint32_t bits)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    pending_events |= bits;
    __set_PRIMASK(mask);
}

static uint32_t Service_TakeEvents(void)
{
    uint32_t mask = __get_PRIMASK();
    uint32_t events;
    __disable_irq();
    events = pending_events;
    pending_events = 0;
    __set_PRIMASK(mask);
    return events;
}
```

然后完成**所有三处调用点的调整**：

| 原位置 | 要做的修改 |
|---|---|
| `Service_Rx()` 中的 `pending_events \|= 1U;` | 替换为 `Service_PostEvents(1U);` |
| `Service_Sample()` 中的 `pending_events \|= 2U;` | 替换为 `Service_PostEvents(2U);` |
| `Service_Poll()` 读取快照以及随后清零的位置 | 读快照替换为 `uint32_t snapshot = Service_TakeEvents();`，删除原 `if (snapshot)` 内的 `pending_events = 0;`，保留按 `snapshot` 处理 LED 的代码 |

取走事件和清空共享位图在同一个短临界区中完成；取走之后到来的事件会留在共享位图中，等下一轮处理。LED 等业务处理在恢复中断后执行，避免把不必要的工作塞进关中断区间。

恢复原来的 PRIMASK，而不是结尾无条件 `__enable_irq()`，才能保留调用前已经关闭中断的状态。这个方案不适用于未经分析的多核、DMA 写入或 NMI 写入场景。

还有一个业务前提：位图表示“至少发生过一次”。同一种事件发生十次也可能合并为一个位。如果业务要求每一次事件都必须计数或携带数据，应改为具有正确同步的计数器或队列，并定义容量满时的处理方式。

修改并保存后，重新运行新版教程中的同一条命令，即可自动构建、重扫和生成新报告。修复仍需验证原来的错误交错不再发生；本工具保守保留保护证据，不保证候选自动消失。

## 4. 对照案例：为什么另一些变量可以直接标为已排查无风险

在本轮 F103 裸机报告顶部点击“已排查：不存在并发风险”，可看到 `ring_tail` 和 `consumed_checksum` 两行：

- `ring_tail` 的全部已恢复读写均位于同一个不可重入 TIM3 中断上下文；即使有多个访问位置，也没有第二个并发执行者，且当前证据没有阻断项。
- `consumed_checksum` 的唯一读改写位置仅在 main 中执行，没有其它已恢复入口、重入或覆盖阻断项，因此可以静态筛除。

这里没有根据 `volatile` 或变量名判断安全。相反，若把某个 `Write()` 同时放到 TIM2 和 TIM3 的调用链中，即使变量只有一行写入语句，也会保留多写者风险。某条主循环路径已知但上游回调入口仍不明时，同样不能标为安全。

安全标记依赖当前构建、配置和完整证据；增加新 ISR、注册入口、DMA 路径或源文件后必须重新扫描。具体判定字段与覆盖限制见[设计文档](concurrency-tool-design.md)，本轮回归和真实项目统计见[验收记录](portability-validation.md)。
