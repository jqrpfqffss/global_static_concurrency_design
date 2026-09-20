# 设计需求追踪矩阵

依据：`stm32_baremetal_concurrency_tool_design_final.md`。本次增量保留现有 CLI → libclang → facts → analysis → reports/review 架构，不调用外部编码代理。
状态：Implemented 表示已实现并测试所列能力；Partial 表示存在明确、保守处理的设计缺口，不代表完整证明。

| ID | 设计要求 | 当前实现 | 缺口 / 边界 | 修改模块 | 测试方法 | 状态 |
|---|---|---|---|---|---|---|
| R001 | global/file/function static 全量归账与唯一 ID | 原有 AST、TU 身份、补充盘点保留 | 未编译分支仅盘点，不伪装访问已分析 | extract/supplemental | inventory + D01–03/D07 | Implemented |
| R002 | TOTAL=SAFE+SUSPECT+UNKNOWN | 分类枚举、唯一 ID、安全/队列互斥与并集强校验 | 缺分类直接报错，不以 UNKNOWN 隐式兜底 | analysis | 全部 D01–20 | Implemented |
| R003 | 全部 READ/WRITE/RMW/ADDRESS_TAKEN | facts/SQLite/HTML/Packet 全部保存 | 未解析别名保留未知 | extract/points_to/html_report | D20 的 32 个访问逐项验证 | Implemented |
| R004 | COMPLETE/PARTIAL 局部覆盖 | coverage_reasons、unknown_reason、required_context | 不代表整个固件或所有运行配置完整 | analysis | D11–15 | Implemented |
| R005 | 全部解析调用链 | all_call_chains + 所有调用点；递归边单列 | 无限递归不展开；显式资源上限超出则扫描失败 | analysis/report/review | diamond 路径 + D20 | Implemented |
| R006 | unresolved_call_edge | 每访问关联未知调用、缺失源码入口，HTML 明示 | 动态调用目标不猜测 | analysis/html_report | D12/调用图回归 | Implemented |
| R007 | MAIN/ISR/Callback 上下文传播 | 调用图、注册语义、多上下文、DMA 独立上下文 | 无法恢复的注册入口仍未知 | analysis/points_to | context/HAL/D07/D15 | Implemented |
| R008 | IRQ priority / 抢占关系 | 分组、位数、抢占/子优先级；CAN_PREEMPT/SERIAL/UNKNOWN | 仅证明 MAIN 访问前无条件且唯一配置；动态重配、复杂初始化路径不证明 | interrupts/extract | 优先级回归及 D10–11 | Partial |
| R009 | PRIMASK CFG 状态 | 分支汇合、while/do、break/continue、return、保存值、嵌套、跨函数与完整窗口 | for/switch/goto/异常/asm/无序复杂表达式阻断保护证明；不是完整 C CFG | controlflow/protection | 20 个 CFG 对抗测试 + D08–09 | Partial |
| R010 | BASEPRI 与 IRQ 阈值 | 常量宏求值、阈值/位数/分组边界检查，覆盖全部竞争 IRQ | 动态寄存器表达式和复杂初始化未知；被调函数的 BASEPRI 窗口保守处理 | interrupts/protection | D10–11、过高 IRQ/条件/未调用初始化反例 | Partial |
| R011 | 配置 Critical / 未配置 Lock | enter/exit/save/restore 契约；名字本身不是锁 | 任意自定义锁算法不自动证明 | config/extract/protection | D16–17 + 保存恢复回归 | Implemented |
| R012 | 六种保护状态 | NOT_FOUND/DETECTED/EFFECTIVE/PARTIAL/INEFFECTIVE/UNRESOLVED | 状态不是规则名或模型推测 | protection | D08–11/D16–18 | Implemented |
| R013 | Ownership 与保护分离 | Single Writer/Context、逃逸、owner 注解分开呈现 | 不证明任意 Single Owner 生命周期/所有权转移 | analysis/html_report | D19 | Partial |
| R014 | SAFE 必须证明 | safe_reason/safe_evidence/完整覆盖强校验 | 只针对当前构建和已声明执行模型 | analysis | D01–03/D08/D10/D16 | Implemented |
| R015 | UNKNOWN 局部传播 | 符号/调用/入口关联；缺失源码的词法引用仅作候选 | 词法候选可能过报，绝不冒充 AST READ/WRITE；复杂别名仍未知 | analysis | 无关 parse 回归、missing TU、D12–14 | Implemented |
| R016 | DMA 独立并发主体 | HAL 契约抽取硬件访问和独立上下文 | 未证明 DMA 生命周期/Cache/owner，保留 UNKNOWN | points_to/analysis | D15/HAL 回归 | Partial |
| R017 | 屏障不等于互斥 | DMB/DSB/ISB 直接事实；单独存在时 INEFFECTIVE | 无 | extract/protection | D18 | Implemented |
| R018 | index.html 完整变量详情 | 分类/覆盖/源码/全链/抢占/保护/Ownership/缺口 | 复杂语义依赖展开的原始事实，不伪造简化结论 | html_report | HTML 回归 + D01–20 | Implemented |
| R019 | 默认 SUSPECT+UNKNOWN，SAFE 可抽样 | 独立队列、Packet、SQLite 表、HTML 栏及计数 | 样本不改变风险队列或静态分类 | cli/review/report | SafeSampleIntegration | Implemented |
| R020 | 单变量 Evidence Packet | 全访问/全链/上下文/抢占/事件/CFG/窗口/缺口/真实源码 | 函数源码 1600 行附件预算显式 manifest，模型须继续读取 | review | packet/合约/D01–20 | Implemented |
| R021 | OpenCode 可保留 NEED_MORE_CONTEXT | 五种状态、日志收据、源码引用、逐项检查合约 | 本轮无真实模型执行，只有离线及可控协议测试 | review_contract/review | review 全套回归 | Implemented |
| R022 | 参与者/抢占/逐步时序 | v2 模型输出协议及源码绑定展示；旧快照静态候选示例有条件提示 | 无真实模型答案时不编造逐步运行轨迹；未覆盖所有风险的自动静态时序 | review_presentation/html_report | explanation 回归/D06 | Partial |
| R023 | D01–D20 独立 Demo | 20 独立固件，逐层断言与可持久化报告 | 不等于板上重现 | cases/test_design_acceptance | verify_design.py | Implemented |
| R024 | 阶段回归与 facts/HTML 一致性 | 历史回归 + 设计矩阵 + 对抗测试；日志/JSON | ARM 真实构建测试取决于外部工具链 | scripts/verify_design.py | --all | Implemented |
| R025 | facts.db 与两个可排查 HTML | 每场景保留源码/编译库/数据库/两报告/离线 Packet | 仅静态工程验证，未做目标板实验 | report/tests | SQLite 与 HTML 跨层验证 | Implemented |

## 架构与阶段记录

原有 `run_ecra.py`/`cli.py` 管理构建参数、扫描和复核；`extract.py` 提取直接事实，`points_to.py` 处理别名及 HAL 语义；`analysis.py` 汇总和分类；`report.py`/`html_report.py` 生成产物；`review*.py` 保留模型协议及收据审计。

1. 事实层：保留全部变量/访问/无环路径与调用点，分类和归账强校验。
2. 并发模型：新增 `interrupts.py`，优先级证据不足不猜测。
3. 保护：新增 `controlflow.py` 直接 CFG 事实和 `protection.py` 状态推导。PRIMASK 不是计数锁；保护端点不足以证明整个窗口。
4. 局部 UNKNOWN：修复缺失源码变量引用漏阻塞，同时不污染无关对象；扫描期间源码变化仍是整个结果完整性阻塞。
5. 复核：扩充 Packet，安全抽样独立呈现，不执行或伪造真实模型复核。

执行结果及 P0 对照见 [开发报告](final_implementation_report.md)，场景和重放命令见 [Demo 说明](../examples/stm32_demo/cases/README.md)。
