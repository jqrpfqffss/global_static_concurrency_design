# UNKNOWN 传播根因（重构前）

本次审查覆盖 `analysis.py` 的合并、上下文、canonical member、冲突、分类和归账路径，以及 `extract.py`、`pointer_extract.py`、`points_to.py`、`protection.py`、`interrupts.py`、编译数据库与补充盘点入口。

1. **调用图双向污染**：`analyze` 将 callee 的 `INDIRECT_CALL / EXTERNAL_CALLEE / INLINE_ASSEMBLY / UNRESOLVED_POINTEE` 反向传到 caller，再将 caller 的全部 taint 沿所有 callee 正向传播。主循环的一个未知调用可以污染另一个完全无关的任务及其变量。丢失原始 gap 身份后只剩 kind，无法回答“此变量为什么相关”。
2. **覆盖与结论混用**：旧分类分支首先检查 `coverage_status == PARTIAL`，直接设置 UNKNOWN。已知 MAIN/ISR 或 ISR/ISR 冲突会被 `PROTECTION_UNRESOLVED / IRQ_PREEMPTION_UNRESOLVED` 覆盖。
3. **取址不等于逃逸**：`ADDRESS_TAKEN` 和任何 `via_alias` 都被当成逃逸。即便 points-to 已恢复所有访问，仍无法筛除。
4. **求解成功未消除旧缺口**：函数指针、指针下标、function address 的提取阶段诊断与后续求解结果没有严格对应。已经恢复的同步回调仍会保留未知入口。
5. **逻辑任务不等于物理并发者**：配置入口和注册入口按 ID 独立建上下文。裸机 dispatcher 中串行调用的多个 TASK/CALLBACK 可能被错误当成多个执行域；同一个 IRQ 的多个入口也缺少统一物理身份。
6. **构建范围错误进入并发分类**：数据库之外的仓库源码既触发 lexical missing caller，又产生 supplemental UNKNOWN 复核项。未编进当前 firmware 的其他 board/feature 因而参与风险归账。
7. **weak 覆盖依赖遍历顺序**：同一 function USR 在 merge 时最后覆盖，但另一实现的 accesses/calls 保留，不能代表 ELF strong-over-weak 语义。
8. **数组抽象过宽**：全部下标合并；无法对已知常量元素给出独立存储证明。结构体成员已有基础区分，但 whole-object 和重叠存储必须继续传播真实影响。

重构原则：先构造带原始位置和相关性解释的 VariableEvidenceSlice；用 PhysicalExecutionContext 比较实际执行者；先判已知未受有效保护的冲突为 SUSPECT，再判可能隐藏额外冲突的变量级缺口为 UNKNOWN，最后以明确 proof code 判 SAFE。覆盖状态独立保存。未进入当前目标构建的声明保留为盘点资料，不进入当前 firmware 的分类和复核分母。

## SUSPECT 数量不能代替误报分析

冲突优先使原先被覆盖缺口压成 UNKNOWN 的已知冲突归入 SUSPECT，这是分类纠正，不代表新发现了同样数量的真实缺陷。另一方面，减少 UNKNOWN 不能成为将剩余候选全部交给人工的终点。应继续分别审计访问事实、物理入口、存储重叠与有效保护，修复可确定排除的候选。

当前 serial 源码抽查同时发现两类情况：`pending_events` 快照后清零、`tx_frame` 启动 DMA 后立即覆写等有具体成立的交错；`command_image.sequence` 和 `reply_bank` 的单一 USART2 路径却被共享 HAL 回调的其他 IRQ 污染，属于需要通用参数/条件路径分析消除的候选。`guarded_total` 的完整 PRIMASK 保护，还受到同一函数其他 `for` 循环使整个 CFG 不完整的影响。逐项源码依据见 [serial_static_classification_audit.md](serial_static_classification_audit.md)。这些结论没有写入任何变量名排除表。

初始化也必须区分“代码看起来在启动时执行”与“已经证明异步源不能访问”。当前严格证明要求真实 NVIC Disable 支配全部写点、全部写点支配相关 Enable。serial 的 `huart2.Init.*` 写入在 `MX_USART2_UART_Init`，但唯一 USART2 Disable 位于未调用的 DeInit 路径；仅扩展跨函数调用图仍缺启动时禁用证据。不能为了消除这类 SUSPECT 猜测 main 之前的 NVIC 状态。后续应恢复明确 reset/bootloader 契约与跨 helper 初始化控制流，或在证据不足时保留候选。

`SAFE_DISJOINT_STORAGE` 作为附加静态证明记录到 `safe_reason_codes` 和 `safe_evidence.disjoint_storage`：依据 Clang 布局和常量下标保存同一容器下互不重叠的半开 bit 区间及另一执行域的访问。它只附加到已由独立规则证明 SAFE 的变量，不删除现有冲突或相关缺口。动态下标、union 重叠和 bitfield 共用存储不能使用这个证明。
