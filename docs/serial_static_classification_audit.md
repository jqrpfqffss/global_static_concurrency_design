# serial 静态分类源码审计

审计日期：2026-09-28。目标目录：`H:/stm32_RAG/test/serial - continue`，仅检查当前裸机分支。`SERIAL_CONCURRENCY_RTOS` 分支不作为本次执行证据。候选索引取自 `output/preopencode-benchmark/serial-current/after/facts.json`；判断逐项回到下列当前源码，没有调用 OpenCode，也没有把静态交错当作板上复现。该 facts 仍在重扫，表格是源码审计记录，不能作为最终 benchmark 数量。

## 真实执行入口

- `Core/Src/main.c:131–137` 的裸机主循环顺序调用 `Cli_Process`、`Service_Poll` 和 `Transport_Poll`，三者属于同一 FOREGROUND。
- `Core/Src/stm32f1xx_it.c:289–294`：USART2 IRQ 进入 `HAL_UART_IRQHandler(&huart2)`；`Core/Src/main.c:62–66` 回调明确限制 `huart == &huart2` 才调用 `Service_Rx`。
- `Core/Src/stm32f1xx_it.c:301–320`：TIM2 调用 `Service_Sample`，TIM3 调用 `Service_Urgent`。`serial_service.c:158–161` 设置 TIM2 抢占优先级 6、TIM3 优先级 2 并启用，二者不是串行 foreground task。
- `Core/Src/stm32f1xx_it.c:321–323`：DMA1 Channel4/5 与 USART1 IRQ 进入 transport；`serial_transport.c:65–72` 再依据句柄筛选 TX/RX 完成回调。
- `serial_transport.c:51` 启动循环 DMA 接收，`:57` 启动 DMA 发送。DMA 硬件与完成通知 IRQ 是不同执行者。

## 至少十个 SUSPECT 的独立源码核对

以下每项都有具体访问和成立的冲突模式，不能为了降低 SUSPECT 比例改成 SAFE。`serial_service.c` 下文简称 service，`serial_transport.c` 简称 transport。

| 变量 / canonical storage | 已核对源码 | 执行者与成立的交错 | 审计结论 |
|---|---|---|---|
| `pending_events` | service:55、85、110、118 | USART2/TIM2 发布位；MAIN 读取快照后，ISR 再发布事件，MAIN 随后的清零抹去新事件。 | 保留 SUSPECT；有真实丢事件路径。 |
| `retry_budget` | service:56、120 | USART2 自增与 MAIN 检查后自减交错，两个 RMW 可基于旧值回写。 | 保留 SUSPECT；volatile 不证明复合操作原子。 |
| `line_flags` | service:35、57、121 | MAIN 与 USART2 通过宏分别 `|=1`、`|=2`；读取同一旧值后相互覆盖位。 | 保留 SUSPECT；不同 bit 掩码仍共用存储。 |
| `lifetime_bytes` | service:58、106–107 | USART2 更新 64 位计数，MAIN 逐字节读取；ISR 可插在读取字节之间。 | 保留 SUSPECT；实际快照可撕裂。 |
| `last_sample.value` | service:60、108–109 | USART2 修改 packed 成员；MAIN 经字节 alias 分多次读取。 | 保留 SUSPECT；成员 alias 与写点指向同一存储。 |
| `maintenance_total` | service:63、101、125 | MAIN 保存旧值；USART2 自增；MAIN 回写 `previous+1` 覆盖中断增量。 | 保留 SUSPECT；旧快照窗口未保护。 |
| `restore_count` | service:47、65、128–131 | MAIN 关中断后立即经 `Service_EnableLine` 重新开中断，再执行自增；USART2 可在自增窗口进入。 | 保留 SUSPECT；扫描到 disable 不等于有效保护。 |
| `priority_total` | service:84、91、132–135、158–159 | TIM2/TIM3 均自增；TIM3 的优先级 2 高于 MAIN 设置的 BASEPRI 阈值 5，至少还有可交错竞争者。 | 保留 SUSPECT；不可因 BASEPRI 被检测到而筛除。 |
| `gated_total` | service:66、136–138 | MAIN 只禁 DMA1 Channel4 IRQ，真正另一写点来自 USART2 的 `Service_Rx`。 | 保留 SUSPECT；屏蔽对象不覆盖竞争 IRQ。 |
| `rx_watermark` | service:24、37、64、127 | `channel.counter` 静态指向此变量；MAIN 和 USART2 经 `Service_Adjust` 对同一 pointee RMW。 | 保留 SUSPECT；指针槽本身只读不改变 pointee 冲突。 |
| `Service_Record::last_token` | service:41–44、52、83、113 | 同一 function-static 由 MAIN、USART2 和 TIM2 间接调用更新；函数局部 static 不是每次调用私有存储。 | 保留 SUSPECT；已存在多个真实执行入口。 |
| `completed_frames` | transport:56、62、67 | MAIN 先保存计数，TX 完成 IRQ 自增，MAIN 用旧 `n+1` 回写。 | 保留 SUSPECT；可覆盖完成计数。 |
| `rx_ready` | transport:59、61、71 | MAIN 读取 ready 后处理数据；RX IRQ 再置位；MAIN 的清零可能抹去新通知。 | 保留 SUSPECT；单次 32 位写也不消除协议窗口。 |
| `tx_frame[*]` | transport:57–58 | HAL 发送启动成功后，MAIN 立即 memset 同一 buffer；DMA 硬件仍在读取。 | 保留 SUSPECT；独立于共享 HAL 回调产生的伪 IRQ 路径。 |
| `rx_frame[*]` | transport:39、51、60 | RX 配置为循环 DMA，MAIN 遍历同一 buffer 计算 checksum；没有停 DMA 或已恢复的双缓冲 ownership 协议。 | 保留 SUSPECT；CPU/DMA 生命周期需要处理。 |
| `wire_status.word` / `bytes[1]` | service:25、68、144 | MAIN 对 union word RMW，USART2 写 union 的第二个 byte；两成员物理重叠。 | 保留 SUSPECT；不可用 field-sensitive 名称分离排除。 |

这些变量在源码中实际包含成组的丢更新、撕裂、DMA 生命周期和无效保护场景。仓库已有 `docs/opencode-review-validation.md` 记载其中风险与安全对照，但本表不依赖既有模型结论；“是否由工程作者故意植入”不是本次静态审计可以证明的事实。

## 应继续消除的工具候选

| 当前 SUSPECT | 源码检查 | 通用解析缺口 |
|---|---|---|
| `command_image.sequence` | service:69 是唯一运行访问，只在 `Service_Rx`；main:64 的句柄条件把该调用限定到 huart2/USART2。 | 当前共享 HAL callback 的调用图把 DMA1 Channel4/5、USART1 的其他句柄路径也传播进来。需要调用点参数与相等条件分支过滤；不应产生多个真实 IRQ。 |
| `reply_bank` | service:73–74 是运行读写，只由同一个 `Service_Rx` 执行。 | 同上。恢复实际句柄路径后应能使用 SINGLE_IRQ；不能按变量名特批。 |
| `guarded_total` | service:139–142 保存 PRIMASK、disable、完整 `++`、restore；另一写点 service:76 只由 USART2 进入。 | 一是上述伪多 IRQ；二是 Service_Poll 较早的两个 `for` 循环令整个 CFG complete=False，使后面的局部确定性临界区也无法证明。需要通用 CFG 控制流支持或局部可证明窗口，不能简单忽略未知控制流。 |
| `channel.counter` / `telemetry_uart.Instance` 等指针成员 | 必须区分指针槽读写与指向 peripheral/buffer 的读写。 | 内联 member 重复 whole-object 访问、pointee 效果错误落在 pointer storage 是正在修复的提取缺陷。只删除重复错误事实，真实 pointee 冲突仍应保留。 |

`command_image.text`、`published_reply`、`reply_banks` 不能随 `command_image.sequence`、`reply_bank` 一起整体筛除：前者还有 MAIN buffer 写、地址发布或跨上下文存储重叠。按同一父对象“一项误报就整组 SAFE”会制造 false-safe。

## huart2.Init 初始化证明为什么还不成立

`main.c:110` 调用 `MX_USART2_UART_Init`；`:197–203` 给 `huart2.Init.*` 写入，然后调用 `HAL_UART_Init(&huart2)`。`stm32f1xx_hal_msp.c:118` 的 Enable USART2 在这条 helper 路径更后面。从普通 CubeMX 启动流程看，这很像初始化后只读配置，但当前工具尚无完整证明。

1. 唯一显式 `HAL_NVIC_DisableIRQ(USART2_IRQn)` 在 `stm32f1xx_hal_msp.c:150` 的 DeInit 路径。检查 Core/Src 未发现调用 `HAL_UART_DeInit`；这个 Disable 不支配 Init 写点。
2. 严格初始化证明目前只支持 main 内的 write/disable/enable CFG；这些写点在 helper，Enable 又在带 `if(huart->Instance==USART2)` 的更深 helper。
3. `main.c:95` 先调用 HAL_Init，已涉及 SysTick。不能把“main 中出现的初始化代码”泛化为“所有异步源尚未启动”。对特定成员应只分析确实可访问它的 IRQ；SysTick 的存在也不能全局污染其它变量。
4. 仅支持 helper 不会弥补第 1 项。合法的后续增强应恢复 reset 到 main 的实际中断启用状态/bootloader 契约，或证明显式 Disable→全部写入→Enable 的跨函数支配关系。不得假定 main 入口时 NVIC 尚未使能。

因此本轮保留这些字段候选并记录具体边界；没有手工添加变量 SAFE 规则，也没有把“初始化路径很常见”当成证明。

## 本次读取的源码指纹

| 文件 | SHA-256 |
|---|---|
| `Core/Src/serial_service.c` | `274b92fc5a71b2b92c66e5838439643d04b3d72f48e928b1e2e7695bb8bfcee3` |
| `Core/Src/serial_transport.c` | `c973b448297526e7d3829c4eee4efb2fcea13c0c960666762eb48bb6a93b5fe4` |
| `Core/Src/main.c` | `a963d9b082987d975180826e3a94c9fae4582137db70dbf40a8ab4cb06d86f1a` |
| `Core/Src/stm32f1xx_it.c` | `775ad767a93de95cb048c8d407f35e57ae5c117c4286f2e8f5d7f907d24c30c3` |
| `Core/Src/stm32f1xx_hal_msp.c` | `ad1b193f26ff3a47830e7e3b8816d90c784511620452a3a33b79211b9905fbda` |
