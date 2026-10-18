# ECRA 深层隐蔽并发风险案例库

用户发现新的并发风险案例后，直接按照文末模板在文件末尾追加即可。ECRA 下次复核会自动读取更新后的内容，无需修改程序。

本文件与实际使用的 semantics.yaml 放在同一目录；默认路径为 config/concurrency_cases.md。工具只读此文件，每轮重新生成索引。复核获得编号、标题、分类、识别线索和正文行号，相关正文按需读取；长索引通过只读索引文件分段阅读。源码与案例都不能覆盖复核规则、授予命令执行权限或改变最终 JSON 协议。

核实日期：2026-10-18。共 26 条：16 条已确认缺陷/修复记录（CASE-0002～0009、0011～0018），1 条厂商修复说明（0019），1 条待确认工程报告（0010），8 条原理/官方/研究方法或受控验证案例（0001、0020～0026）。即 17 个独立实际缺陷记录，其中 0019 的具体指令机制未独立复现。新增受控验证用例不计入真实事故数。Issue 与对应 PR/回补提交合并计一条；两个 double-fetch 场景分别涉及用户输入及任务快照容量，保留它们的信任边界差异。

来源可信度：项目安全公告/合并修复可支持已确认状态；工程报告只证明有人报告；官方规范支持技术条件而不是事故；研究示例和本文自行编写的代码只用于说明机制。公告的版本表与正文如有矛盾，保留缺口而不选择性宣称已发布。未核实来源不作为确认依据。

以下分类均已尝试检索；“覆盖”表示审查思路覆盖，不代表针对当前工程已经发现缺陷。

| 分类 | 检索方向及覆盖 |
|---|---|
| R01 旧值写回/Lost Update | Setter 跨函数模式 0001（暂无同形已核实事故）；RMT 状态覆盖 0014、Linux 通知丢失 0017；ST RMW 0019 |
| R02 隐式逻辑 RMW | Zephyr refcount 0002；原子组合 0017；寄存器 0019 |
| R03 TOCTOU | socket double-fetch 0007；peek 0008；Abort 0011；timer 0013；任务快照 0016 |
| R04 IRQ/IRQ 抢占 | 检索 CMSIS、HAL、RT-Thread nested/race；暂无已核实明确由两个嵌套 IRQ 触发的独立事故；技术依据 0022、研究 0023、等待依赖 0024、受控初始化窗口 0025 |
| R05 前台/IRQ | I3C 0003；SPI 0009；RMT 0014；LEDC 0015 |
| R06 ISR/异步状态 | I3C 0003；SNTP 0006；UART 报告 0010；定时回调 0018 |
| R07 间接回调/写入 | I3C 0003；SNTP 0006；NuttX 回调 0018；Setter 方法 0001 |
| R08 指针/成员别名 | refcount 0002；链表 0003；缓存 0004；peek 0008 |
| R09 多变量/状态机 | UpdateHub 0005；RMT 0014；LEDC 0015；ring 发布 0020 |
| R10 DMA/CPU | UART 报告 0010；AES 修复 0012；AN4839 0021 |
| R11 完成/中止/重启 | UART 报告 0010；STM32U5 修复 0011；AES 0012 |
| R12 缓冲区/所有权 | I3C 0003；peek 0008；AES 0012；官方 ring 0020 |
| R13 保护范围/粒度 | TLS 全局锁 0004；timer 0013；RMT 0014；LEDC 0015 |
| R14 释放/在途使用 | refcount 0002；TLS 0004；SNTP 0006；peek 0008；NuttX 0018 |
| R15 外设事务 | STM32 SPI 0009；UART 报告 0010；U5 Abort 0011；HAL 0019 |
| R16 寄存器瞬态 | SPI 0009；U5 SUSPF 0011；HAL 寄存器方法 0019 |
| R17 屏蔽/生命周期 | SNTP 0006；RMT 0014；LEDC 0015；NuttX 0018；CMSIS 0022 |
| R18 发布/内存顺序 | 已检索 Linux/Zephyr ring、DMA 文档；暂无已核实独立弱内存发布事故；官方依据 0020、0021 |
| R19 Cache/DMA | 已检索 ST、NXP、TI、Infineon；暂无已核实真实案例；官方 AN4839 0021 |
| R20 其他模式 | timer 重复入链形成环 0013；研究验证边界 0023；IRQ推进依赖 0024；旧快照反证 0026 |

检索还覆盖 FreeRTOS 官方发布说明、Apache NuttX、ESP-IDF、ST HAL、CMSIS、RT-Thread ChangeLog、Microchip 中断共享数据指导、NXP AN3544、TI DMA 所有权指导、Infineon DMA/Cache 指导，以及 IEEE/大学公开研究。未充分核实的材料不进入真实缺陷计数。所有示意代码均重新编写，非产品原代码；危险交错中标明的泛化推演必须回到当前工程验证。

## CASE-0001｜跨函数旧值经 Setter 写回：逻辑事务窗口

**分类：** R01、R02、R04、R05、R07、R13  
**来源类型：** 原理归纳 / 研究方法  
**确认状态：** 已核实技术依据；暂无已核实的同形多级 Setter 真实事故  
**来源：** MITRE CWE-367；SDRacer（研究）  
**适用环境：** 裸机 / IRQ / 通用；非特定产品版本  
**关键共享对象：** shared 及保存旧值的参数/局部变量  
**执行上下文：** 前台或低优先级 IRQ；可介入的高优先级 IRQ  
**识别线索：** Setter(shared)、temp、FunctionA、FunctionB、stale write-back、lost update  
**检索关键词：** Setter(shared)、temp、FunctionA、FunctionB、stale write-back、lost update

### 1. 风险机制

单次 load/store 原子不等于读旧值到写回的逻辑 RMW 原子。本条是自行归纳的审查模式，不声称上述资料记录了此 Setter 事故。

### 2. 典型代码模式

```c
unsigned shared;
void Setter(unsigned v) { shared = v; }
void B(unsigned v) { Setter(v); }
void A(unsigned v) { B(v); }
void foreground(void) { A(shared); }
void irq(void) { Setter(200); }
```

### 3. 危险交错

前台读取 100 并保存为实参 → IRQ 写 200 → 前台经 A/B/Setter 写回 100；仅在该 IRQ 确能介入时成立。

### 4. 隐蔽原因

搜索最终赋值只见一个 Setter；旧值在多个栈帧流动，看似独立的 READ/WRITE 实为一个事务。

### 5. OpenCode排查方法

从实参求值位置开始，逐层追踪值而非只追踪变量名；列出每层调用、实际写回及可介入者，并核对 READ 是否也在保护内。

### 6. 常见错误判断

“32 位原子”“只有同一 Setter”“last-writer-wins”“最终 WRITE 已关中断”。

### 7. 可证明安全的条件

证明同一不可重入上下文，或完整保护覆盖读值、传参到写回，并排除未受保护的 DMA/其他核写者；不同实际存储不能硬凑写回。

### 8. 适用性和边界

STM32 可直接采用此排查方法；IRQ 优先级未知时保留 NEED_MORE_CONTEXT。普通盲写最后顺序不确定本身不是事务缺陷。

## CASE-0002｜Zephyr net_buf 非原子引用递减与最后引用释放

**分类：** R02、R08、R14  
**来源类型：** 真实缺陷 / 项目安全公告  
**确认状态：** 已确认并修复（按公告）  
**来源：** Zephyr GHSA-284j-5jm9-55hh  
**适用环境：** Zephyr lib/net_buf/buf.c；具体分支以公告回补表为准  
**关键共享对象：** 缓冲区头部及数据区引用计数  
**执行上下文：** 共享同一缓冲区的多个释放调用者  
**识别线索：** net_buf_unref、--ref、最后引用、double-free  
**检索关键词：** net_buf_unref、--ref、最后引用、double-free

### 1. 风险机制

公告确认引用计数递减与最后引用判断未作为原子操作完成，竞争释放可破坏所有权并重复释放；修复采用原子计数并使用返回的旧值判断。

### 2. 典型代码模式

```c
/* 机制示意，不复制产品实现 */
void release(struct Obj *p) {
    if (--p->refs == 0) free_payload(p);
}
```

### 3. 危险交错

两个 unref 的 load/dec/store/test 交错 → 最后引用判定失去唯一性 → 可能重复释放；具体指令交错须按目标编译结果核实。

### 4. 隐蔽原因

每个调用者都合法持有引用；问题在组合递减与判断，不在单个 free 或字段宽度。

### 5. OpenCode排查方法

追踪所有 ref/unref 包装、浅克隆、共享数据块及最终释放；核对最后引用决定是否唯一，并检查递减后的字段读取生命周期。

### 6. 常见错误判断

“每个线程只释放一次”“计数是一个字节”“用了引用计数就安全”。

### 7. 可证明安全的条件

所有拥有者遵守同一原子引用协议，唯一最后引用者负责回收，且引用建立早于发布；仅替换某个调用点不足。

### 8. 适用性和边界

STM32 ISR 与前台共享包池同样适用；不能把可能 double-free 扩大为必然可利用的代码执行。

## CASE-0003｜Zephyr I3C ISR 与工作队列空闲链表竞争

**分类：** R05、R06、R07、R08、R09、R12  
**来源类型：** 真实缺陷 / 项目安全公告  
**确认状态：** 已确认并修复（按公告）  
**来源：** Zephyr GHSA-gfj5-gcxv-9jqm  
**适用环境：** Zephyr drivers/i3c/i3c_ibi_workq.c  
**关键共享对象：** i3c_ibi_work_nodes_free 的 head/tail/节点链接  
**执行上下文：** I3C ISR 分配；工作队列归还；SMP 可真正并行  
**识别线索：** sys_slist、IBI、workqueue、memcpy、free-list  
**检索关键词：** sys_slist、IBI、workqueue、memcpy、free-list

### 1. 风险机制

无内部同步的链表被 ISR 取节点和工作线程归还同时操作；链表不一致可重复分配节点或丢失节点，间接 memcpy 放大后果。

### 2. 典型代码模式

```c
node = freelist_take(&pool); /* ISR */
/* 工作线程，多个字段组成插入 */
pool.tail->next = returned;
pool.tail = returned;
```

### 3. 危险交错

工作线程更新链接尚未更新尾指针 → IBI ISR 取节点 → 恢复后链表头尾或节点所有权不一致。

### 4. 隐蔽原因

不同辅助函数各只写一部分字段，节点数据写入还隐藏在 memcpy 中。

### 5. OpenCode排查方法

恢复 callback 的实际入口，展开链表辅助函数和结构体指针别名；核对取出与归还是否使用同一 ISR 可用保护。

### 6. 常见错误判断

“静态节点不用 free”“只有一个工作线程”“链表 API 名称意味着线程安全”。

### 7. 可证明安全的条件

同一有效锁覆盖所有分配/归还，且中断/SMP 语义适用；或证明归还期间对应 IRQ 永不可介入。

### 8. 适用性和边界

可映射为 STM32 IRQ/主循环的静态包池；锁种类须按裸机环境选择，不能建议 ISR 阻塞等待普通互斥量。

## CASE-0004｜Zephyr TLS 每 socket 锁未覆盖全局会话缓存

**分类：** R08、R13、R14  
**来源类型：** 真实缺陷 / 项目安全公告  
**确认状态：** 已确认并修复（按公告）  
**来源：** Zephyr GHSA-wcgm-pq6x-v2gf  
**适用环境：** Zephyr subsys/net/lib/sockets/sockets_tls.c；启用客户端会话缓存  
**关键共享对象：** 全局 client_cache 与 entry->session  
**执行上下文：** 不同 socket 的并发客户端线程  
**识别线索：** ctx->lock、client_cache、session_cache、每实例锁、全局资源  
**检索关键词：** ctx->lock、client_cache、session_cache、每实例锁、全局资源

### 1. 风险机制

不同 socket 分别持有自己的锁，却读写相同全局缓存；读取 session 时另一个 socket 可以淘汰并释放它。

### 2. 典型代码模式

```c
lock(socket_a.lock); read_session(global_cache[0]);
/* 另一调用者持有不同的锁 */
lock(socket_b.lock); replace_session(global_cache[0]);
```

### 3. 危险交错

A 在自己的锁内取得缓存指针 → B 在另一把锁内释放/替换同槽 → A 继续解码已释放会话。

### 4. 隐蔽原因

每个函数看起来都有 mutex；遗漏的是锁身份与共享资源粒度。

### 5. OpenCode排查方法

由对象字段追到实际全局数组；比较所有 get/save/reset/restore 路径使用的锁身份和生命周期。

### 6. 常见错误判断

“所有 API 都有锁”“不同 socket 是不同实例所以不会冲突”。

### 7. 可证明安全的条件

同一缓存锁覆盖全部访问和释放，或每实例真正使用互不重叠缓存；持锁时间覆盖指针解引用。

### 8. 适用性和边界

裸机多个外设 handle 共用全局缓存/临时数组时同样适用；无并发客户端不能照搬缺陷结论。

## CASE-0005｜Zephyr UpdateHub 多入口破坏共享上下文与数组边界

**分类：** R08、R09、R13  
**来源类型：** 真实缺陷 / 项目安全公告  
**确认状态：** 已确认并修复（按公告）  
**来源：** Zephyr GHSA-vprh-rff6-46xp  
**适用环境：** Zephyr subsys/mgmt/updatehub/updatehub.c  
**关键共享对象：** 全局 ctx、fds[1]、nfds、sock、payload  
**执行上下文：** 后台 autohandler；shell/API/syscall 触发的用户操作  
**识别线索：** ctx.nfds、共享状态机、索引与数组、prepare_fds  
**检索关键词：** ctx.nfds、共享状态机、索引与数组、prepare_fds

### 1. 风险机制

多个更新流程重入同一上下文；nfds 与单元素 fds 的约束破坏后写越界，连接建立/清理也可互相干扰。

### 2. 典型代码模式

```c
void prepare(void) {
    ctx.fds[ctx.nfds] = ctx.sock;
    ctx.nfds++;
}
```

### 3. 危险交错

流程 A 已占用槽 0 → 流程 B 进入共享 ctx 的 prepare → 按已变化 nfds 写槽 1。

### 4. 隐蔽原因

ctx 各成员单次写入合法；缺陷由多入口状态关系和数组容量共同决定。

### 5. OpenCode排查方法

枚举 shell、定时工作及直接 API 入口，核对全局上下文串行化与 nfds 边界，读取相邻成员及清理路径。

### 6. 常见错误判断

“只有一个定义 ctx 的 C 文件”“状态字段是 int”“更新动作很少触发”。

### 7. 可证明安全的条件

全局事务互斥覆盖所有入口及错误恢复，并独立验证索引边界；或每个事务有独立上下文。

### 8. 适用性和边界

STM32 通信/升级状态与缓冲区索引可复用此方法；不把公告的结构体内破坏推断为任意代码执行。

## CASE-0006｜Zephyr SNTP 注销服务后立即关闭仍在 poll 的 socket

**分类：** R06、R07、R14、R17  
**来源类型：** 真实缺陷 / 项目安全公告  
**确认状态：** 已确认并合并修复（按公告；不承诺预测发布版本）  
**来源：** Zephyr GHSA-34wr-cg29-c4mw  
**适用环境：** Zephyr 异步 SNTP、socket service、net_context 固定对象池  
**关键共享对象：** socket 对应 net_context 和 poll 节点  
**执行上下文：** 系统工作队列超时关闭；socket service poll 线程  
**识别线索：** close_async、unregister、poll、对象池复用、注销不等于退出  
**检索关键词：** close_async、unregister、poll、对象池复用、注销不等于退出

### 1. 风险机制

注销只防止后续分发，未同步等待已在 poll 的使用者；调用线程关闭后底层对象可被复用。修复把关闭交给实际 poll 的服务线程。

### 2. 典型代码模式

```c
service_unregister(fd);
close(fd); /* 服务线程可能仍持有内部 poll 指针 */
```

### 3. 危险交错

服务线程建立 poll 引用并等待 → 超时线程注销/close → 对象池复用 → poll 继续访问旧对象。

### 4. 隐蔽原因

没有显式共享全局变量赋值；生命周期由跨层 API 和内部队列联结。

### 5. OpenCode排查方法

沿注册、poll、timeout、注销和 close 追踪所有权；区分“请求停止”与“所有在途使用已结束”。

### 6. 常见错误判断

“回调已取消”“已从列表移除”“固定池没有真正 free”。

### 7. 可证明安全的条件

在所有使用者退出后回收，或由单一 owner 在线程内关闭；等待同步不得引入互等死锁。

### 8. 适用性和边界

STM32 Stop/DeInit 后 DMA/ISR/回调仍在途的场景可类比；纯同步路径没有此窗口。

## CASE-0007｜Zephyr socket double-fetch：分配与循环读取不同参数

**分类：** R03、R08、R09  
**来源类型：** 真实缺陷 / 项目安全公告  
**确认状态：** 已确认并修复（按公告）  
**来源：** Zephyr GHSA-fcp3-vrr2-xfjv；CWE-367  
**适用环境：** Zephyr zsock_sendmsg/zsock_recvmsg 用户态参数校验  
**关键共享对象：** 用户共享 msghdr、msg_iovlen 与内核分配容量  
**执行上下文：** 系统调用处理；可修改用户内存的线程/核  
**识别线索：** double-fetch、msg_copy、分配大小、循环边界、TOCTOU  
**检索关键词：** double-fetch、msg_copy、分配大小、循环边界、TOCTOU

### 1. 风险机制

虽已建立副本，后续仍重复解引用原用户指针；分配容量与循环界限可能来自不同时间的值。

### 2. 典型代码模式

```c
size_t n = user->count;
Item *p = allocate(n);
for (size_t i = 0; i < user->count; ++i) copy_item(p+i);
```

### 3. 危险交错

按小 count 分配 → 竞争者增大 count → 循环按新 count 写超过容量。

### 4. 隐蔽原因

每次参数读取都有效，问题在多次读取之间不一致；只看到 memcpy 前做过检查容易漏掉。

### 5. OpenCode排查方法

沿分配大小、校验条件和实际复制次数追踪是否使用同一可信快照，检查深层指针是否仍引用可变内存。

### 6. 常见错误判断

“已经 memcpy 参数”“每次读取都在合法地址”“volatile 保证最新”。

### 7. 可证明安全的条件

验证、分配、循环使用同一已验证快照，包含必要的嵌套数据；或完整互斥阻止修改。

### 8. 适用性和边界

裸机 IRQ 修改通信长度、CPU 按旧长度分配再按新长度复制同样适用；不要求 STM32 存在用户态。

## CASE-0008｜Zephyr queue peek 获取节点后在解引用前被释放

**分类：** R03、R08、R12、R14  
**来源类型：** 真实缺陷 / 项目安全公告  
**确认状态：** 已确认并合并修复（按公告；版本表与正文不一致，本文不指定修复版本）  
**来源：** Zephyr GHSA-8xm3-4w69-29mm  
**适用环境：** Zephyr kernel/queue.c；含 FIFO/LIFO 包装  
**关键共享对象：** data_q 节点、alloc_node 标志及数据指针  
**执行上下文：** peek 调用者；get/unlink/free 调用者  
**识别线索：** peek_head、peek_tail、只读路径、alloc_node、悬空指针  
**检索关键词：** peek_head、peek_tail、只读路径、alloc_node、悬空指针

### 1. 风险机制

peek 未用队列锁，读取节点指针后到读取节点内容前，其他 get 可以摘链并释放内部包装节点；修复覆盖 peek 内部读取窗口。

### 2. 典型代码模式

```c
Node *n = queue.head;
/* 竞争者可能 remove_and_free(n) */
return n->data;
```

### 3. 危险交错

A 读取 head → B 在队列锁内摘链并释放 n → A 无锁解引用 n。

### 4. 隐蔽原因

peek 被当作只读查询；真正竞争对象是它依赖的内部节点生命周期。

### 5. OpenCode排查方法

查看 API 内部和包装层，而非只检查返回指针的赋值；分别核对内部节点读取和返回业务对象的后续生命周期。

### 6. 常见错误判断

“读操作不需要锁”“get 已经加锁”“返回的指针是原子的”。

### 7. 可证明安全的条件

peek 的取指针及解引用受同一队列锁保护；返回后使用业务对象还需独立的引用/所有权协议。

### 8. 适用性和边界

STM32 IRQ 与前台共享队列、静态池复用也可发生对象混淆；不把内部修复当作返回对象无限期有效。

## CASE-0009｜STM32 SPI 半双工等待错过 CSTART 瞬态

**分类：** R05、R15、R16  
**来源类型：** 真实缺陷 / Issue 与合并 PR（同一事故）  
**确认状态：** 已确认并修复  
**来源：** Zephyr #94265 → #98558  
**适用环境：** STM32H745；Zephyr spi_stm32_half_duplex_switch_to_receive；报告基于 4.1.0  
**关键共享对象：** SPI CR1.CSTART、EOT 与事务进度  
**执行上下文：** CPU 发起并轮询；SPI 硬件独立推进；其他 IRQ 可延迟 CPU  
**识别线索：** half-duplex、StartMasterTransfer、CSTART、EOT、无限等待  
**检索关键词：** half-duplex、StartMasterTransfer、CSTART、EOT、无限等待

### 1. 风险机制

启动后 CPU 被抢占，硬件可能完成并清除启动位；CPU 恢复后只等待启动位出现，将永远错过它。修复增加已完成条件。

### 2. 典型代码模式

```c
start_transfer();
while (!transfer_active()) {
    /* 缺少 completed/error/timeout 出口 */
}
```

### 3. 危险交错

启动 SPI → CPU 被延迟 → SPI 完成且清除 CSTART → CPU 恢复等待 CSTART 再次为 1。

### 4. 隐蔽原因

即使只有一个软件调用者也会与硬件竞速，变量扫描可能只看见寄存器读取。

### 5. OpenCode排查方法

查瞬态位与持久完成位的硬件语义；在启动到首次轮询间尝试插入可行延迟，并检查完成、错误、超时出口。

### 6. 常见错误判断

“没有第二个软件写者”“硬件肯定先 busy 再 done，所以一定看得见 busy”。

### 7. 可证明安全的条件

等待条件同时接受已完成状态并正确处理错误/超时，或硬件协议保证所等状态持续到确认；须核对具体 SPI 代际。

### 8. 适用性和边界

直接适用于相应 STM32 SPI 外设；不能把所有型号的标志位行为视为相同。

## CASE-0010｜ESP32 UART DMA 完成早于软件接收计数更新

**分类：** R06、R09、R10、R11、R12、R15  
**来源类型：** 真实工程问题报告 / GitHub Issue  
**确认状态：** 已核实报告与日志；未核实最终根因及修复  
**来源：** Zephyr #100955  
**适用环境：** ESP32；Zephyr v4.3.0；async_uart + async_rx_helper（报告环境）  
**关键共享对象：** rx_counter、rx_len、rx_buf 与 DMA 重装地址  
**执行上下文：** UART ISR；DMA 完成回调；接收超时工作  
**识别线索：** uart_esp32_dma_rx_done、rx_counter、dma_reload、边界覆盖  
**检索关键词：** uart_esp32_dma_rx_done、rx_counter、dma_reload、边界覆盖

### 1. 风险机制

报告指出 DMA 完成回调在 UART 更新计数前发生，可能据旧计数重新装载并覆盖尾部；这里只记录待验证机制。

### 2. 典型代码模式

```c
/* 对报告机制重新编写的示意 */
void dma_done(void) { reload(buf + rx_count); }
void uart_irq(void) { rx_count++; }
```

### 3. 危险交错

DMA 填满 → 完成回调先用旧 rx_count 重装 → 后到 UART ISR 才更新计数 → 后续字节覆盖旧位置（待工程验证）。

### 4. 隐蔽原因

两个事件分别正确，但事件顺序和缓冲区所有权不一致；只看完成回调中的锁会遗漏。

### 5. OpenCode排查方法

核对真实硬件完成顺序、IRQ 优先级、计数来源、回调重入及边界长度；用日志与寄存器确认，不将报告猜测当已证事实。

### 6. 常见错误判断

“完成回调一定意味着所有软件状态都更新了”“另一个板卡正常所以协议安全”。

### 7. 可证明安全的条件

重装依据权威已完成字节数，事件顺序及所有权已证明，且重复/延迟事件不会复用在途缓冲区。

### 8. 适用性和边界

可启发 STM32 UART IDLE/TC/HT 与 DMA 回调审查；ESP32 细节不可直接移植为 STM32 结论。

## CASE-0011｜STM32U5 DMA Abort 对已空闲通道等待 SUSPF 卡死

**分类：** R03、R11、R15、R16  
**来源类型：** 真实缺陷 / Issue 与合并 PR（同一事故）  
**确认状态：** 已确认并修复；不采信早期 AI 猜测作为证据  
**来源：** Zephyr #103042 → #103367（2026-02-05 合并）  
**适用环境：** STM32U585；Zephyr 4.3 报告；dma_stm32_suspend  
**关键共享对象：** DMA stream busy 状态、挂起请求、SUSPF  
**执行上下文：** 调用 uart_tx_abort 的任务；DMA 硬件完成及中断  
**识别线索：** uart_tx_abort、dma_suspend、SUSPF、busy、完成与中止  
**检索关键词：** uart_tx_abort、dma_suspend、SUSPF、busy、完成与中止

### 1. 风险机制

挂起一个已经空闲的 stream 时，等待挂起确认可永久无结果；合并修复在 DMA 等待循环检查实际忙状态，不能只在 UART 层提前检查一次。

### 2. 典型代码模式

```c
request_suspend();
while (!suspended()) {
    if (!stream_busy()) break; /* 必须按真实驱动语义核对 */
}
```

### 3. 危险交错

调用者决定中止 → DMA 同时完成变空闲 → 发挂起请求后 SUSPF 不再出现 → 旧实现无限等。

### 4. 隐蔽原因

软件状态检查到硬件请求之间仍有窗口；“窄到几条指令”不能排除。

### 5. OpenCode排查方法

沿 Abort→DMA suspend→寄存器等待链追踪；确认空闲、完成、错误和中止完成出口，不只重复 busy 检查。

### 6. 常见错误判断

“关 IRQ 会停硬件”“再检查一次 busy 就构成原子事务”“Issue 标题带问号所以永无后续证据”。

### 7. 可证明安全的条件

驱动根据硬件实际状态允许空闲退出并处理完成/错误，且资源只有在真正停止后复用；需要芯片手册和实现共同支持。

### 8. 适用性和边界

直接针对 STM32U5 对应驱动，其他系列须重查状态寄存器。早期删掉 suspend 的试验不等同通用正确修复。

## CASE-0012｜ESP-IDF AES DMA 等待首描述符误作全链完成

**分类：** R10、R11、R12、R14  
**来源类型：** 真实缺陷 / 官方仓库修复提交  
**确认状态：** 已确认并修复  
**来源：** ESP-IDF 536d6eea61（release/v4.2）  
**适用环境：** ESP32-S2 mbedTLS AES DMA；release/v4.2 修复  
**关键共享对象：** 输入/输出描述符链、尾块和输出缓冲区  
**执行上下文：** CPU 等待/读取/清理；AES DMA  
**识别线索：** out_desc_head、out_desc_tail、owner、链表尾、尾块未完成  
**检索关键词：** out_desc_head、out_desc_tail、owner、链表尾、尾块未完成

### 1. 风险机制

修复将完成等待参数从输出链首换成真正尾描述符（含零头块）。机制上首块完成不能证明后续输出完成。

### 2. 典型代码模式

```c
start_dma(chain);
wait_owner_clear(chain.head); /* 不能推出 tail 已完成 */
consume_output();
```

### 3. 危险交错

首输出块完成 → CPU 误认全链结束 → 尾块仍由 DMA 写 → CPU 读取或复用输出。

### 4. 隐蔽原因

完成标志本身真实，只是归属的工作范围比调用者假定的小；CPU 关中断不改变 DMA。

### 5. OpenCode排查方法

追踪完成事件对应哪个 descriptor，含追加尾块路径；读取输出、释放描述符、重启前是否等待最后硬件访问。

### 6. 常见错误判断

“收过一次 DMA 完成通知”“第一个 owner 已归还”“只剩几个字节”。

### 7. 可证明安全的条件

证明等待覆盖本次事务所有描述符及尾块，完成后再交接所有权；同步与 Cache 可见性分别验证。

### 8. 适用性和边界

STM32 链表 DMA、双缓冲尾块可以复用审查方法；不能把 ESP 描述符字段直接套用 STM32。

## CASE-0013｜ESP-IDF esp_timer 先检查后加锁导致重复入链

**分类：** R03、R09、R13、R20  
**来源类型：** 真实缺陷 / 合并 PR  
**确认状态：** 已确认并修复  
**来源：** ESP-IDF #11215；500b5b2  
**适用环境：** esp_timer；2023-05-08 合并  
**关键共享对象：** timer armed 状态及 s_timers 链表  
**执行上下文：** 两个可调用启动定时器 API 的任务  
**识别线索：** timer_armed、s_timers、先检查后加锁、重复插入、链表环  
**检索关键词：** timer_armed、s_timers、先检查后加锁、重复插入、链表环

### 1. 风险机制

armed 检查在锁外，另一任务可在获取锁前先插入；后续虽在锁内插入，已依据失效结果，形成链表环。

### 2. 典型代码模式

```c
if (!timer_armed(t)) {
    lock(list_lock);
    insert_timer(t);
    unlock(list_lock);
}
```

### 3. 危险交错

A 检查未 armed → B 完整启动并入链 → A 取得锁后重复插入 → 遍历无限循环。

### 4. 隐蔽原因

破坏发生时确实持锁；遗漏的是锁外检查决定了锁内动作。

### 5. OpenCode排查方法

从状态检查开始界定整个逻辑窗口；核对 start/stop/restart 的所有状态判断与入链是否在同一锁内。

### 6. 常见错误判断

“链表写操作全部在锁内”“检查只读不需要锁”。

### 7. 可证明安全的条件

检查及更新受同一锁保护，或有具有相同效果的原子状态转移且失败者不会操作链表。

### 8. 适用性和边界

裸机软定时器、IRQ 与主循环共享任务表同样适用；不能只给 insert 加锁就结束复核。

## CASE-0014｜ESP-IDF RMT 解锁后发布 RUN 覆盖完成 ISR 状态

**分类：** R01、R02、R05、R09、R13、R17  
**来源类型：** 真实缺陷 / 官方仓库修复提交  
**确认状态：** 已确认并修复  
**来源：** ESP-IDF da503640；关联 #15842（同一事故）  
**适用环境：** components/esp_driver_rmt/src/rmt_rx.c  
**关键共享对象：** channel->fsm 与 RX 硬件使能状态  
**执行上下文：** rmt_receive 调用者；接收完成 ISR  
**识别线索：** atomic_store、RMT_FSM_RUN、enable、完成ISR、解锁后写状态  
**检索关键词：** atomic_store、RMT_FSM_RUN、enable、完成ISR、解锁后写状态

### 1. 风险机制

硬件已启动但 RUN 在退出临界区后发布；完成 ISR 可以先恢复 ENABLE，随后调用者原子写 RUN，覆盖真实完成状态。修复把 RUN 写入移回临界区。

### 2. 典型代码模式

```c
lock(); enable_rx(); unlock();
atomic_store(&fsm, RUN); /* ISR 可能刚写回 ENABLE */
```

### 3. 危险交错

启动 RX 并解锁 → 快速完成 ISR 写 ENABLE → 前台写 RUN → 状态与已完成硬件不符。

### 4. 隐蔽原因

使用了 atomic_store，且主要硬件配置在临界区内，但发布顺序和保护边界错误。

### 5. OpenCode排查方法

沿使能→状态发布→完成 ISR 核对事件可能发生的最早时刻；追踪所有状态写者及最后一次解锁后的写回。

### 6. 常见错误判断

“fsm 是原子类型”“启动函数只有一处赋值”“完成 ISR 自己持锁”。

### 7. 可证明安全的条件

状态发布和使能顺序与竞争者同锁协调，完成者永不会被过期启动状态覆盖；还须核对多核锁语义。

### 8. 适用性和边界

STM32 DMA/UART 启动后才写 BUSY 的模式可直接类比；此源的具体寄存器为 ESP32 RMT。

## CASE-0015｜ESP-IDF LEDC Stop 在锁外保存状态导致 ISR 竞争

**分类：** R03、R05、R09、R13、R17  
**来源类型：** 真实缺陷 / 官方仓库修复提交  
**确认状态：** 已确认并修复  
**来源：** ESP-IDF 95f8eb12  
**适用环境：** components/esp_driver_ledc/src/ledc.c；ledc_fade_stop  
**关键共享对象：** fade->fsm、通道中断使能与完成信号量  
**执行上下文：** 停止调用者；fade ISR  
**识别线索：** fade_stop、fsm、锁外READ、提前return、停止中断、assert  
**检索关键词：** fade_stop、fsm、锁外READ、提前return、停止中断、assert

### 1. 风险机制

旧实现锁外读取状态，之后 ISR 可改变状态；修复将首次读取纳入临界区并统一退出，协调等待 ISR 完成与信号量释放。

### 2. 典型代码模式

```c
State saved = fade.state;
lock(); disable_channel_irq();
stop_using(saved); unlock();
```

### 3. 危险交错

Stop 读取运行状态 → ISR 完成并变 IDLE → Stop 按旧状态处理或遇到原本不该出现的断言分支。

### 4. 隐蔽原因

锁内再次读或单独关闭中断，不能自动修正锁外决策；早退还关联资源释放。

### 5. OpenCode排查方法

从首次 fsm 读取追踪全部 return/goto、屏蔽和信号量操作，区分禁新中断与已在执行 ISR 的退出。

### 6. 常见错误判断

“Stop 内关了通道 IRQ”“最终状态读写都原子”“assert 会保证安全”。

### 7. 可证明安全的条件

读取、判断及状态变更在有效临界区中，退出恢复及完成等待覆盖所有分支，不对未占用资源重复释放。

### 8. 适用性和边界

STM32 PWM/DMA Stop/Abort 可借鉴；信号量方案在裸机中需换成真正可验证的完成握手。

## CASE-0016｜FreeRTOS 任务快照容量与分配大小重复读取失配

**分类：** R03、R09  
**来源类型：** 真实缺陷 / 官方仓库修复提交  
**确认状态：** 已确认并修复  
**来源：** FreeRTOS-Kernel e146d644  
**适用环境：** tasks.c；vTaskListTasks 及运行统计相关路径  
**关键共享对象：** uxCurrentNumberOfTasks、uxArraySize、任务状态数组  
**执行上下文：** 生成任务快照的任务；创建/删除任务的竞争路径  
**识别线索：** volatile task count、uxArraySize、pvPortMalloc、uxTaskGetSystemState  
**检索关键词：** volatile task count、uxArraySize、pvPortMalloc、uxTaskGetSystemState

### 1. 风险机制

已保存的数组容量和实际 malloc 又读取的任务数可能不一致；修复让分配复用同一局部 uxArraySize。本条关注容量失配，不假定计数只会增加。

### 2. 典型代码模式

```c
size_t capacity = task_count;
Status *p = allocate(task_count * sizeof(*p));
fill_snapshot(p, capacity);
```

### 3. 危险交错

保存容量 N → 其他路径改变任务计数为 M → 按 M 分配却按 N 的容量传给填充函数；N>M 时可能分配不足。

### 4. 隐蔽原因

局部快照看似已解决问题，但分配仍读原 volatile；风险跨越调用参数、分配与下游容量校验。

### 5. OpenCode排查方法

逐个比较检查/分配/实际写入的容量来源，查创建及删除路径；查看下游是否根据真实传入容量阻止溢出。

### 6. 常见错误判断

“volatile 总是最新所以更安全”“之前已经复制过计数”“被调用 API 有边界检查”。

### 7. 可证明安全的条件

同一可信容量控制分配和所有写入，实时任务数增长时下游拒绝超限；不能要求本地快照永远等于实时数量。

### 8. 适用性和边界

裸机 IRQ 改变采样数、设备数或报文数时同样适用；FreeRTOS 调度细节不代表裸机入口。

## CASE-0017｜Linux NFS 原子 bit 操作组合仍丢失通知

**分类：** R01、R02、R09  
**来源类型：** 真实缺陷 / 官方仓库修复提交  
**确认状态：** 已确认并修复  
**来源：** Linux 7f101efd  
**适用环境：** fs/nfsd/nfs4state.c；clients_still_reclaiming  
**关键共享对象：** NFSD_NET_SOMEBODY_RECLAIMED 与宽限期推进状态  
**执行上下文：** 回收 OPEN/LOCK 路径；周期性 laundromat 检查  
**识别线索：** test_bit、clear_bit、set_bit、test_and_clear_bit、通知丢失  
**检索关键词：** test_bit、clear_bit、set_bit、test_and_clear_bit、通知丢失

### 1. 风险机制

单独 test 后 clear 允许中间的 set 被清掉；真实协议依靠该通知延续宽限期。修复改为原子 test-and-clear。

### 2. 典型代码模式

```c
if (test_bit(flag)) {
    clear_bit(flag);
    continue_grace();
}
```

### 3. 危险交错

周期路径看到旧通知 → 回收路径再次 set → 周期路径 clear 掩盖新通知 → 下次检查提前结束宽限期。

### 4. 隐蔽原因

单项 bit API 具有原子性也无法保证组合原子；业务状态决定重复通知能否合并。

### 5. OpenCode排查方法

追踪通知消费到下一次动作的完整周期，查清零后的处理是否已覆盖新事件，再判断有无真实丢失。

### 6. 常见错误判断

“用了原子 bit 函数”“布尔通知总能合并”“任何重复置位被清除都一定丢工作”。

### 7. 可证明安全的条件

消费采用正确原子交换或锁，并证明消费范围覆盖被合并事件；若当前处理确已覆盖新事件，不应照搬此缺陷。

### 8. 适用性和边界

STM32 ISR 事件标志/前台清零可类比，但必须用本项目的事件处理关系证明错误结果。

## CASE-0018｜NuttX 异步取消 TCP 定时工作未等待在途回调

**分类：** R06、R07、R08、R14、R17  
**来源类型：** 真实缺陷 / Issue 与合并 PR（同一事故）  
**确认状态：** 已确认并修复  
**来源：** Apache NuttX #19849 → #20641（2026-10-15 合并）  
**适用环境：** net/tcp/tcp_timer.c；报告为单核 ESP32-P4、NuttX 13.0.0 提交  
**关键共享对象：** conn、conn->dev、LPWORK 工作节点与连接池  
**执行上下文：** 关闭连接路径；已从队列取出的 TCP 定时回调  
**识别线索：** work_cancel、work_cancel_sync、memset、定时器、断线重连  
**检索关键词：** work_cancel、work_cancel_sync、memset、定时器、断线重连

### 1. 风险机制

异步取消不等待已经开始的回调；连接随后被清零/归还对象池，在途回调仍使用旧 conn。修复同时处理同步取消及缺失 NULL 检查等根因。

### 2. 典型代码模式

```c
cancel_work_async(&conn->work);
zero_and_recycle(conn); /* callback 可能已出队 */
```

### 3. 危险交错

工作回调已出队执行 → 关闭取消排队工作但不等待 → conn 清零复用 → 回调继续访问 conn->dev。

### 4. 隐蔽原因

没有多核也会发生；工作项已不在队列，取消返回值容易被当成完成保证。

### 5. OpenCode排查方法

读取 cancel 的真实契约，追踪回调出队后所有路径及锁依赖；同步等待是否与网络锁互相等待也要核实。

### 6. 常见错误判断

“单核”“取消函数已经返回”“对象池没有堆释放”“加 NULL 判断就消除所有生命周期问题”。

### 7. 可证明安全的条件

回调完全退出后再清理，或持有有效引用；等待顺序必须避开回调需要的锁，且新定时请求不能重入回收窗口。

### 8. 适用性和边界

STM32 软件定时器、异步回调取消及 DMA DeInit 后复用对象可类比；本条不声称在 STM32 上复现原问题。

## CASE-0019｜STM32 HAL UART Tx/Rx 并发寄存器访问修复记录

**分类：** R01、R02、R04、R05、R15、R16  
**来源类型：** 真实缺陷 / 厂商正式修复说明  
**确认状态：** 已核实厂商修复记录；未逐指令复现原事故  
**来源：** ST stm32f1xx-hal-driver Release_Notes：UART/USART concurrent register access  
**适用环境：** STM32F1 HAL/LL UART 与 USART；确切修复版本以发布说明对应章节为准  
**关键共享对象：** 同一 UART/USART 的共享控制寄存器  
**执行上下文：** Tx 与 Rx 的可交错调用/中断路径，具体优先级取决于工程  
**识别线索：** concurrent register access、Tx、Rx、CR1、SET_BIT、CLEAR_BIT、隐式RMW  
**检索关键词：** concurrent register access、Tx、Rx、CR1、SET_BIT、CLEAR_BIT、隐式RMW

### 1. 风险机制

厂商明确记录处理 Tx/Rx 并发寄存器竞争；下面用不同位 RMW 丢更新说明应检查的机制，非原事故指令级复现。

### 2. 典型代码模式

```c
/* 通用寄存器 RMW 示例 */
unsigned old = UART_CTRL;
UART_CTRL = old | TX_ENABLE;
/* 竞争路径也可能改变 RX_ENABLE */
```

### 3. 危险交错

A 读整个控制字 → B 改另一控制位 → A 按旧字写回，可能覆盖 B；成立条件需检查具体寄存器及实现。

### 4. 隐蔽原因

Tx/Rx 看似不同业务，实际可能共享寄存器存储；两个位不代表独立机器访问。

### 5. OpenCode排查方法

查看所用 HAL 版本、宏展开及寄存器手册，区分普通 RMW、专用 set/clear、独占访问和 W1C；核实 IRQ 真实关系。

### 6. 常见错误判断

“Tx 与 Rx 不同字段”“寄存器 32 位原子”“HAL API 已自动处理一切并发”。

### 7. 可证明安全的条件

所用实现已提供对竞争位有效的原子更新/完整保护，所有相关路径遵守同一协议，且硬件写副作用已核查。

### 8. 适用性和边界

直接相关 STM32；不能因发行说明一句话推断所有具体机型/版本仍有缺陷，R04 嵌套 IRQ 的具体事故仍未核实。

## CASE-0020｜环形缓冲区的发布顺序与生产者数量约束

**分类：** R09、R12、R18  
**来源类型：** 官方技术依据  
**确认状态：** 已核实文档；非真实事故  
**来源：** Linux Circular Buffers；Zephyr Ring Buffers  
**适用环境：** Linux/Zephyr 环形缓冲区；裸机适用需核实内存模型  
**关键共享对象：** ring 数据、head/tail、claim/finish 保留区域  
**执行上下文：** 生产者；消费者；潜在额外 ISR/核  
**识别线索：** SPSC、ring_buf、head、tail、release/acquire、claim/finish  
**检索关键词：** SPSC、ring_buf、head、tail、release/acquire、claim/finish

### 1. 风险机制

无锁方案通常依赖单生产者/单消费者和数据先于索引的可见性；Zephyr API 不提供普遍内部并发控制。索引原子不足以保证载荷已发布。

### 2. 典型代码模式

```c
ring[next] = payload;
store_release(&head, next); /* 示意，不可直接替换任意平台宏 */
```

### 3. 危险交错

若先发布 head 或重排可见性 → 消费者见新 head 却读旧数据；或两个生产者认领同一槽。

### 4. 隐蔽原因

扫描可能只看到生产者写 head、消费者写 tail，看不见跨变量协议和弱内存可见性。

### 5. OpenCode排查方法

数实际物理生产/消费上下文，检查 claim 到 finish 生命周期、重入、发布与消费顺序及平台屏障。

### 6. 常见错误判断

“两个索引分别只有一个写函数”“索引 volatile”“SPSC 允许任意数量回调生产者”。

### 7. 可证明安全的条件

真实 SPSC、槽位所有权正确且发布/回收顺序符合目标内存模型；多生产者/消费者另有完整同步。

### 8. 适用性和边界

适用于 STM32 UART ring/DMA 双缓冲的协议审查；屏障不能解决 DMA 正在覆写或 Cache 未维护。

## CASE-0021｜STM32F7/H7 CPU Cache 与 DMA 可见性

**分类：** R10、R12、R18、R19  
**来源类型：** 官方技术依据 / 厂商应用笔记  
**确认状态：** 已核实 AN4839；非真实事故  
**来源：** ST AN4839 Rev 2，第 5–8 页；Linux DMA API guide 补充所有权方法；Arm AN321 第4.18节补充无Cache型号的屏障边界  
**适用环境：** STM32F7/H7 Cortex-M7、可缓存 DMA 缓冲区  
**关键共享对象：** DMA buffer、SRAM、D-cache 行及描述符所有权  
**执行上下文：** CPU 通过 Cache 访问；DMA 独立访问物理内存  
**识别线索：** SCB_CleanDCache、Invalidate、write-back、cache-line、DMA owner  
**检索关键词：** SCB_CleanDCache、Invalidate、write-back、cache-line、DMA owner

### 1. 风险机制

CPU 脏 Cache 尚未写回时 DMA 读旧 SRAM；DMA 更新 SRAM 后 CPU 又可能读旧 Cache。中断屏蔽和 volatile 都不建立一致性。

### 2. 典型代码模式

```c
fill(tx_buffer);
/* 缺少必要的 clean / 所有权交接 */
start_dma(tx_buffer);
/* RX 必须在完成后按平台要求维护 Cache 再消费 */
```

### 3. 危险交错

CPU 写脏行 → DMA 读旧 SRAM；或 DMA 写新 SRAM → CPU 命中旧 Cache；不需要第二个 CPU 写者。

### 4. 隐蔽原因

硬件写入不出现在普通 C 赋值中，程序逻辑顺序正确也可能看不到新数据。

### 5. OpenCode排查方法

核实芯片、MPU 属性、DMA 可达内存、缓存行对齐/范围及相邻对象共行；区分 DMA 运行中所有权与完成后可见性。

### 6. 常见错误判断

“关中断”“加 volatile”“任意时刻 invalidate”“只维护 buffer 的字节长度就总能安全”。

### 7. 可证明安全的条件

不可缓存且 DMA 可达区域，或正确的 clean/invalidate、屏障、行级独占及完成握手；未完成传输不能靠 Cache 操作修复。

### 8. 适用性和边界

直接适用于带 D-cache 的 STM32 型号；无该 Cache 的 F1/F407 等不能照搬缓存风险。R19 暂无已核实真实事故，只有官方示例依据。另据 Arm AN321 第4.18节，普通共享RAM的数据store与DMA使能store之间可用DMB建立观察顺序；DSB可替代它但不能因“DMB不等全部指令完成”就认定该发布顺序失效。此结论不替代在途DMA完成/所有权握手，也不免除有Cache型号的维护要求。

## CASE-0022｜IRQ 嵌套与屏蔽阈值：临界区实际覆盖边界

**分类：** R04、R05、R13、R17  
**来源类型：** 官方技术依据  
**确认状态：** 已核实 CMSIS 文档；R04 具体嵌套 IRQ 事故暂无已核实真实案例  
**来源：** Arm CMSIS-Core NVIC / Core Register Access；Microchip 共享内存指导  
**适用环境：** 具体 Cortex-M 内核和优先级分组；不同内核寄存器支持不同  
**关键共享对象：** 共享事务与 PRIMASK/BASEPRI、NVIC priority/grouping  
**执行上下文：** 前台；低/高抢占优先级 IRQ；不可屏蔽异常  
**识别线索：** BASEPRI、PRIMASK、NVIC_SetPriorityGrouping、同级IRQ、restore  
**检索关键词：** BASEPRI、PRIMASK、NVIC_SetPriorityGrouping、同级IRQ、restore

### 1. 风险机制

屏蔽阈值只阻止其覆盖的异常；子优先级不等于抢占优先级。恢复为固定 enable 也可能破坏外层临界区。

### 2. 典型代码模式

```c
unsigned saved = read_mask();
mask_competitors();
whole_transaction();
restore_mask(saved);
```

### 3. 危险交错

低 IRQ 进入未屏蔽高 IRQ 的保护 → 高 IRQ 介入改状态 → 低 IRQ 写回旧值；同抢占级 IRQ 则不能这样互抢。

### 4. 隐蔽原因

函数名 Disable/Lock 不说明实际寄存器、阈值、内核和作用范围。

### 5. OpenCode排查方法

检查真实分组、实现优先级位数、寄存器设置与所有返回路径；逐个竞争者验证被屏蔽，DMA 另查。

### 6. 常见错误判断

“两个不同 IRQ 必然互抢”“数值相同子优先级就等同抢占关系”“enable 恢复总正确”。

### 7. 可证明安全的条件

按实际内核证明所有竞争者不能介入且嵌套恢复正确；DMA/其他核须独立同步。

### 8. 适用性和边界

直接指导 STM32；缺 NVIC 配置就说明缺口，不能从注释推定优先级，亦不能凭资料确认工程缺陷。还须核对配置的生效顺序：可见的早期优先级设置若随后经过实现不可见的板级策略调用，不能直接作为调用后最终配置的证明。源码证据缺失时保留 LIKELY/NEED_MORE_CONTEXT，并指出需补充的实现或配置；若主张调用前的短暂窗口，则另行证明当时的 IRQ 触发和具体错误，不能混用两个阶段。

## CASE-0023｜SDRacer：以可行中断注入验证危险交错

**分类：** R01、R04、R05、R20  
**来源类型：** 研究案例 / 方法依据  
**确认状态：** 已核实论文摘要；未独立复现论文各工程，非新增独立事故计数  
**来源：** Wang 等，Automatic Detection, Validation and Repair of Race Conditions in Interrupt-Driven Embedded Software  
**适用环境：** 研究覆盖多个 C 嵌入式工程；本文不导入其静态分析框架  
**关键共享对象：** 访问相关共享内存和中断控制状态  
**执行上下文：** 应用入口与一个或多个中断处理器  
**识别线索：** interrupt-driven、atomicity violation、可行交错、中断注入  
**检索关键词：** interrupt-driven、atomicity violation、可行交错、中断注入

### 1. 风险机制

研究强调静态潜在冲突还需验证触发输入和可行中断点。作为复核方法依据，不能把任意 syntactic READ/WRITE 组合当真实事故。

### 2. 典型代码模式

```c
read_shared();
/* 仅当此点 IRQ 已使能且优先级允许时注入 */
write_using_saved_value();
```

### 3. 危险交错

找到候选窗口 → 核实可达输入及中断使能 → 在可行点插入竞争 ISR → 验证结果差异（验证建议，不代表已执行）。

### 4. 隐蔽原因

调用图可达不等于该运行阶段可抢占；普通线程模型容易生成不合法 IRQ 交错。

### 5. OpenCode排查方法

构造最短真实时序，同时主动寻找优先级/阶段/保护反证；对缺失运行条件明确列出所需证据。

### 6. 常见错误判断

“静态有冲突就已复现”“论文能检出所以当前源码必有缺陷”。

### 7. 可证明安全的条件

在当前工程证据下所有候选介入点均不可行或完整受保护；有限测试未复现不能单独证明普遍安全。

### 8. 适用性和边界

适用于 STM32 复核与验证建议；不新增中断模拟器，不承诺自动证明所有未知并发缺陷。

## CASE-0024｜ISR 等待无法抢占自己的 SysTick：推进依赖死锁

**分类：** R04、R06、R17、R20  
**来源类型：** 官方技术依据 / 本项目受控验证  
**确认状态：** 已核实 ST 官方注意事项；本项目完成 ARM 构建和有界宿主机调度回放，未板上复现  
**来源：** STM32CubeF4 v1.28.3，STM324xG_EVAL USB_Device/CDC_Standalone readme；本项目 stm32_cdc/p11  
**适用环境：** 单核 Cortex-M 裸机，依赖 SysTick 或其他 IRQ 的轮询等待  
**关键共享对象：** tick、完成标志、超时计数  
**执行上下文：** 外设 ISR 与低抢占优先级 SysTick/完成 IRQ  
**识别线索：** HAL_Delay、HAL_GetTick、while、唯一推进者、SysTick、等待依赖  
**检索关键词：** priority dependency、ISR busy wait、tick timeout deadlock

### 1. 风险机制

轮询者占据 CPU，唯一能改变退出条件的 IRQ 却无法抢占它。ST 官方明确提醒：在外设 ISR 内使用 HAL_Delay 时，SysTick 必须具有更高抢占优先级。本条不是 ST 项目已发生事故的公告。

### 2. 典型代码模式

```c
volatile uint32_t tick;
void SysTick_Handler(void) { tick++; } /* priority 15 */
void Peripheral_IRQHandler(void) {    /* priority 2 */
    uint32_t start = tick;
    while (tick == start) { /* 等待者永不让出当前 ISR */ }
}
```

### 3. 危险交错

外设 IRQ 进入并保存 tick → SysTick pending → 其数值优先级更大，不能抢占 → tick 不变 → 外设 IRQ 不返回。用同一个 tick 实现超时也不能解除依赖。

### 4. 隐蔽原因

每条 load/store 可以原子，两个 IRQ 甚至不能互相交错；问题是等待依赖而不是数据撕裂。

### 5. OpenCode排查方法

沿 while/HAL_Delay/超时循环追踪所有推进写者，核实实际优先级分组、屏蔽状态和硬件是否可独立完成。区分自主 DMA 完成位与只能由软件 IRQ 更新的标志。

### 6. 常见错误判断

“加 volatile 就能更新”“有超时就不会卡死”“同级 IRQ 不互抢所以安全”。

### 7. 可证明安全的条件

等待移到前台或采用异步状态机；或证明推进者确能在整个等待期间运行且不会被屏蔽。独立硬件退出条件需核实寄存器行为，不能凭名称假定。

### 8. 适用性和边界

本项目 p11 回放只对给定优先级和调度模型进行有界验证；未模拟完整芯片或证明所有等待均安全。

## CASE-0025｜先使能 IRQ 再初始化回调对象：启动窗口

**分类：** R04、R06、R09、R14、R17  
**来源类型：** 本项目自行构造的验证案例  
**确认状态：** 已完成 STM32F407 ARM 编译链接；交错按 Cortex-M 优先级及源码可达性分析，未板上复现  
**来源：** 本项目 tests/fixtures/stm32_cdc/p20.c 与 board.c  
**适用环境：** STM32 裸机初始化、Start/Reset/重新注册回调  
**关键共享对象：** buffer、capacity 及 IRQ 可访问的接收对象  
**执行上下文：** main 初始化与已使能的 TIM7 IRQ  
**识别线索：** EnableIRQ、SetPendingIRQ、回调注册、零初始化、capacity-1  
**检索关键词：** initialization window、publish before init、IRQ enable lifecycle

### 1. 风险机制

对象静态清零并不代表业务已就绪。使能 IRQ 或发布回调后，处理器可在初始化完成前进入访问路径；无符号容量减一还可能把空对象错误判为可用。

### 2. 典型代码模式

```c
struct Receiver { unsigned char *buffer; unsigned capacity; } rx;
void start(void) {
    enable_and_pend_irq();
    rx.buffer = storage; rx.capacity = sizeof(storage);
}
void irq(void) {
    if (0U < rx.capacity - 1U) rx.buffer[0] = 0x55;
}
```

### 3. 危险交错

main 使能并 pending IRQ → IRQ 抢占，capacity 仍为零 → capacity-1 回绕为最大无符号值 → 使用空 buffer。也需检查仅 buffer 写完而 capacity 未写完的中间状态。

### 4. 隐蔽原因

日常业务路径可能保护正确，错误只发生在启动、重启或错误恢复阶段；“初始化函数”并不自动排除并发。

### 5. OpenCode排查方法

核对实际使能位置、pending 来源、回调可达性、对象首次赋值及所有重置路径。将使能后到对象就绪视为真实事务窗口。

### 6. 常见错误判断

“main 的初始化不会与 IRQ 并发”“BSS 清零就是合法空状态”“已设置 buffer 就等于整个对象已发布”。

### 7. 可证明安全的条件

先初始化完整对象并建立所需可见性，再使能生产源和 IRQ；或证明所有处理路径在未就绪状态均安全返回，并核实重启流程。

### 8. 适用性和边界

这是预埋验证案例，不是 ST 上游缺陷记录；不能将其计入真实公开事故数。

## CASE-0026｜消费者旧快照可以合法：发布索引的误报排除

**分类：** R01、R09、R12、R18、R20  
**来源类型：** 审查方法 / 本项目反向验证  
**确认状态：** 已核对所选固件反汇编中的单次取值；不代表整个环形缓冲区已证明安全  
**来源：** STM32CubeF4 v1.28.3 CDC_Standalone 本地 GNU ARM -Og 构建；本项目验证记录  
**适用环境：** 单生产者发布索引、消费者分批取走数据的协议  
**关键共享对象：** 发布索引、消费索引、在途数据  
**执行上下文：** 生产者 IRQ 与较低优先级消费者  
**识别线索：** 单生产者、发布索引、旧但自洽快照、单字命令邮箱、GPIO、传播延迟  
**检索关键词：** SPSC、consistent snapshot、false positive、publication index、blind store mailbox

### 1. 风险机制

生产者在消费者保存索引后追加数据，不一定使已保存的批次失效；新数据可以留给下一轮。必须证明具体数据丢失、越界、二次取值矛盾或存储被提前复用，才能确认缺陷。相同原则适用于单字盲写命令邮箱：IRQ 各写一个完整常量、前台单次读取驱动 GPIO 时，不能仅因输出存在一轮传播延迟，就发明“任意时刻必须等于最新共享值”的业务约束；写另一个外设不等于向原共享对象回写旧值。

### 2. 典型代码模式

```c
unsigned end = published; /* 保存一次发布边界 */
consume_range(out, end);  /* 必须另查范围有效、所有权、发布顺序 */
out = end;
```

### 3. 危险交错

读旧边界 → 生产者发布新边界 → 消费者仅处理旧批次，本身可能合法。若生产者在消费完成前覆盖旧批次，或消费者检查旧边界后重新取不同边界计算长度，才有需要另行证明的风险。

### 4. 隐蔽原因

“无锁且有抢占”容易被误当成充分条件；C 源码多次出现同一非 volatile 表达式，也不保证当前机器代码进行了多次 load。

### 5. OpenCode排查方法

恢复生产、发布、消费和复用协议；指出错误结果所需的最短时序。没有反汇编证据时不宣称已验证实际 load 序列，必要时列为待验证条件。

### 6. 常见错误判断

“消费者可能读旧值，所以已确认丢数据”“生产者用了 ++，即使没有其他写者也必丢更新”。

### 7. 可证明安全的条件

完整证明单生产者、稳定消费批次、容量与复用约束、发布可见性及生命周期。单次取值只能反驳特定 double-fetch 交错，不能证明整个系统安全。

### 8. 适用性和边界

本条用于降低无证据的 CONFIRMED；不得据此忽略过载、DMA/USB 在途数据复用、生命周期或不同构建产生的真实风险。

### 后续追加模板

复制以下模板到本文件末尾，替换编号和内容；编号可使用 CASE-0027 或 CASE-USER-001。可选元数据缺失不阻断复核，缺少分类/识别线索会警告并保留正文路径。不要将模板的代码围栏一起复制，否则它仍被视为示例。

```markdown
## CASE-0027｜新发现的问题名称

**分类：** R20  
**来源类型：** 用户确认 / 真实缺陷 / 官方技术依据 / 研究案例  
**确认状态：** 已核实 / 待核实（写明依据）  
**来源：** 现场记录或公开项目  
**适用环境：** 芯片、模块、版本、裸机/IRQ/DMA/RTOS  
**关键共享对象：** 对象及相关状态  
**执行上下文：** 真实入口  
**识别线索：** 函数名、资源名、风险模式  
**检索关键词：** 可检索术语

### 1. 风险机制
说明来源确认了什么，什么只是推测。
### 2. 典型代码模式
给出自行编写的最小示意。
### 3. 危险交错
写清谁先执行、何处介入、结果是什么。
### 4. 隐蔽原因
普通 READ/WRITE 检查为何会遗漏。
### 5. OpenCode排查方法
沿哪些调用、数据和保护窗口核查。
### 6. 常见错误判断
哪些理由不能单独证明安全。
### 7. 可证明安全的条件
需要哪些可验证证据排除该交错。
### 8. 适用性和边界
对当前 STM32 工程成立的条件和剩余未知。
```

