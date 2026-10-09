# 真实 STM32 工程分类修复与验收

## 扫描对象和边界

本次按当前 `config/semantics.yaml` 扫描 `H:/stm32_RAG/code/serial - opencode`。它是 STM32F103、20 个 C Translation Unit 的构建变体，**不是请求中描述的 220 TU 变体**。在可读取的 `H:/stm32_RAG` 编译数据库中，发现的最大规模为 62 TU（SmartFarm），未找到 220 TU 数据库。原有结果在清缓存前保存到 `docs/real_project_classification_before.json`；复扫样本和逐变量证据保存在 `docs/real_project_classification_after.json`、`docs/real_project_classification_audit.json`。这份报告只声称当前配置实际覆盖的工程。

扫描前删除了工程内的 `.ecra` 和专用 `build/manual`，随后用真实 CMake 配置、编译和 `compile_commands.json` 对所有 20 TU 重新执行 Clang 提取、points-to、上下文、阶段分析和分类。使用 `--no-review`，遵守当前禁用 OpenCode/Claude Code 委派的指示；它生成完整静态报告并保留人工复核队列。

## 根因与算法修复

| 根因 | 旧行为及失真 | 修复后的证据规则 |
| --- | --- | --- |
| RC-1 GCC 构建参数混入 Clang | 链接、汇编、依赖和输出参数可触发不相关诊断 | `compilation.py` 按参数类别和成对操作数移除 `-Wl/-Wa/-Xlinker/-Xassembler/--specs/-M*/-o` 等；保留宏、头文件、语言标准及 ARM ABI/布局参数；`remove_args` 继续作为项目补充。 |
| RC-2 diagnostic 等同失败 | 可遍历 AST 的 TU 被整单元标 `FAILED` | `extract.py` 将完整提取且无错误的 TU 标 `PARSED`，可恢复错误标 `PARTIAL`，fatal 诊断或提取异常标 `FAILED`。`PARTIAL_PARSE_REGION` 只绑定错误所在函数实际引用的变量；CLI、多核聚合和补充解析均单独统计 `PARTIAL`，真正 `FAILED` 才进入缺失 TU 传播。 |
| RC-3 `PrintingPolicy` 崩溃 | 属性辅助提取中断整个 TU | section 属性使用 attribute cursor token、声明 token 和有限的宏参数映射提取；缺失辅助元数据不会使 `main` 或整个 TU 失败。 |
| RC-4 前台调用链断裂 | `main` 的 CFG 将 `if (Cli_Start(&cli) != HAL_OK)` 误报未定序，弱 HAL 实现又覆盖了用户强定义 | `controlflow.py` 区分调用自身实参与调用之外的操作；`extract.py` 识别 STM32 `__weak` 定义，让现有链接解析先选强实现。现有 call graph/physical propagation 因此恢复 `Reset_Handler → main → helper/CLI` 的 `FOREGROUND`。 |
| RC-5 函数地址误作异步入口 | 同步命令表可能引入未知执行者 | `evidence.py` 与 `context_points.py` 仅在 `actual_escape` 被证明时把 `FUNCTION_ADDRESS` 作为入口缺口；有限 points-to 间接调用继续继承调用者物理上下文。已配置的注册 API 仍创建异步上下文。 |
| RC-6 多 IRQ 共用 callback 的访问复制 | 同源码写点跨 context 产生候选笛卡尔积 | `pointer_extract.py` 把稳定 handle 参数的 `handle->Instance` 指针比较序列化为条件；现有 context points-to 按调用者对象证明分支不可达后删除该 IRQ 的访问实例。两个真正可到达同一写点的 IRQ 仍形成冲突，不按 `access_id` 一刀切跳过。 |
| RC-7 初始化证明过严 | 无显式 disable、多层 helper、任何取地址或无关 CFG 缺口均令证明失败 | `initialization.py` 从已验证 Reset 向 `main` 建立状态，按 CFG/callsite 传播写、enable 和单调 runtime 位；动态数组、真正不确定 store/call 仍可阻断。识别常见 HAL/NVIC 启动 API 和 `async_enable` 配置；链接 map 限定 `__libc_init_array` 在 main 前的构造函数。 |
| RC-8 UNKNOWN 扇出过大 | 一个 opaque 消费者或诊断污染无关变量 | `evidence.py` 只让变量直接绑定的 alias/存储缺口，或在注册点可达且能沿调用边到达其访问的入口缺口进入 `VariableEvidenceSlice`；若初始化证明覆盖全部写点，且所有回调发布点只在已验证使能后的 IRQ 中执行、回调路径无法到达写点，则此入口不会造成该变量的读写冲突。`fanout_diagnostics` 统计所有分类的 blocker 扇出。格式化输出 API 的读写且不逃逸语义消除了 CLI `vsnprintf` 的虚假地址逃逸。 |

分类器没有放宽 SAFE 门槛。`SUSPECT` 优先于证据缺口时，`unknown_reason_codes`、`analysis_coverage=PARTIAL` 与 `blocking_evidence` 仍保留在事实和 HTML/Markdown 报告中。

## 修改文件

| 文件 | 改动原因 |
| --- | --- |
| `ecra/compilation.py` | 按编译阶段规范化 GCC 参数及操作数。 |
| `ecra/extract.py` | TU 三态、属性降级、弱定义识别、局部 PARTIAL gap、异步启动事件。 |
| `ecra/async_semantics.py`、`ecra/config.py` | 常见异步启动 API 与可配置 `async_enable`。 |
| `ecra/controlflow.py` | 修复条件中单个调用的假未定序 CFG 缺口。 |
| `ecra/common.py`、`ecra/points_to.py` | `vsnprintf` 等标准格式化 API 的精确读写和无逃逸合同。 |
| `ecra/pointer_extract.py` | HAL handle `Instance` 对象条件提取。 |
| `ecra/context_points.py` | 同步函数表地址不再抑制 caller-sensitive guard 收敛。 |
| `ecra/evidence.py` | 同步函数地址判别、不可达注册点过滤、已证明初始化写与后续 IRQ 回调读的阶段关联、PARTIAL 局部 gap、SUSPECT 保留 coverage。 |
| `ecra/analysis.py` | 在变量证据切片前生成初始化证明，供入口缺口相关性判断使用。 |
| `ecra/initialization.py` | 跨 helper 阶段解释、reset/map 启动检查、变量相关 opaque 判断。 |
| `ecra/cli.py`、`ecra/multicore.py`、`ecra/supplemental.py` | 端到端保留 `PARSED/PARTIAL/FAILED` 三态，避免部分解析被重新解释为缺失 TU。 |
| `ecra/report.py`、`ecra/html_report.py` | 分别显示完整、部分、失败 TU 数目及诊断。 |
| `tests/test_real_classification_repair.py`、`tests/test_precision_diagnostics.py`、`tests/test_complete_inventory.py` | 根因回归、不可达注册点反例及补充解析三态断言。 |
| `scripts/clean_configured_scan.ps1`、`scripts/real_project_metrics.py`、`scripts/real_project_audit.py` | 安全清缓存、可复核的全量统计和逐变量审计。 |

现有 `ecra/physical.py` 的 context/access 分层和真实跨物理上下文冲突保留。仓库原有的 `config/semantics.yaml`、`docs/classifier_progress.md`、`ecra/points_to.py`、`ecra/target_set.py`、`tests/test_pointer_worklist.py` 未提交改动均予保留；上述表格只陈述本次新增的修改。

## 自动测试

新增回归覆盖：GCC 参数、nonfatal diagnostic 与局部 PARTIAL、CLI 端到端 PARTIAL 归账、fatal 缺头、缺失 `PrintingPolicy`、单前台动态 CLI 表、真实异步注册、跨层初始化、enable 后再次写、未知 pre-main 构造函数、HAL `Instance` 分支、真实双 IRQ 写点、强定义覆盖 `__weak` HAL 默认实现、不可达 callback 注册点，以及仅在初始化写之后的已验证 IRQ 中发布回调的阶段证据。反例包括回调可达写点、IRQ 不匹配、混入来源不明的发布点、发布函数另有未知入口，均必须保留 UNKNOWN。现有 `test_init_phase`、`test_vector_contexts`、`test_portability`、`test_multicore` 等保留对缺失 TU、DMA、ISR/main、ISR/ISR、RMW、未知调用及上下文传播的反例验证。最终完整 `python -m unittest discover -s tests -p 'test_*.py' -q`：574 项，通过，1 项按原条件跳过；日志为 `output/repair-test-final-proof.log`。

## 真实工程 Before / After

这里的 TOTAL 包含 58 个 inventory 行；49 个可分类的叶子/存储单元构成 SAFE、SHARED、SUSPECT、UNKNOWN 的分母。容器和数组根记录不参与四类计数。

| 指标 | Before | After |
| --- | ---: | ---: |
| Translation Units | 20 | 20 |
| PARSED / PARTIAL / FAILED | 20 / 0 / 0 | 20 / 0 / 0 |
| TOTAL inventory variables | 58 | 58 |
| Classifiable variables | 49 | 49 |
| SAFE_PROVEN | 19 | 29 |
| SHARED_NO_REVIEW | 0 | 0 |
| SUSPECT | 23 | 20 |
| UNKNOWN | 7 | 0 |
| UNKNOWN_EXECUTION_CONTEXT blockers | 89 | 9 |
| UNKNOWN_RELEVANT_MISSING_TU blockers | 0 | 0 |
| INDIRECT_CALL blockers | 0 | 0 |
| ADDRESS_ESCAPE blockers | 17 | 0 |
| Initialization proofs | 0 | 3 |
| Conflict pair records | 414 | 426 |
| Same source access pair records | 8 | 8 |

本次配置原先已经是 20/20 `PARSED`、SAFE 19，故不能把它写成“220/220 FAILED → PARSED”或“SAFE 0 → 29”。冲突记录上升是强 HAL 回调恢复后可见执行路径增加，不能作为误判增加的直接证据。

## 逐类审计

对 29 个 SAFE、20 个 SUSPECT 全量审计；SHARED 与 UNKNOWN 类均为 0，已检查全部。逐行记录（访问数、物理上下文、来源、冲突见证、blocker 调用链）见 `docs/real_project_classification_audit.json`。自动一致性审计要求 SAFE 无关键 blocker/未归属运行访问，理由与读写/物理域相符，INIT 证明覆盖所有 writer；SUSPECT 有可交错写冲突见证；UNKNOWN 有 source、relation 和可达调用链。审计不替代源码逐项核对，下面给出源码证据。

### SAFE

29 个 SAFE 的理由分布为：`SAFE_SINGLE_FOREGROUND` 19、`SAFE_INIT_ONLY_WRITE` 3、`SAFE_READ_ONLY` 5、`SAFE_SINGLE_IRQ` 1、`SAFE_NO_RUNTIME_ACCESS` 1。单前台样本 `DebugCliStats.cmd_ok/cmd_err/last_cmd` 与 `cli.command_count/commands/line_buffer/line_length/line_overflow` 的运行访问均落在 `FOREGROUND`，且无关键 blocker。`cli.command_count` 的证据链包括 `main → Cli_Process → Cli_ProcessByte → Cli_ExecuteLine → AppCli_Help → Cli_GetCommandCount`，命令表的间接目标不创建新物理执行者。静态命令表成员 `app_cli_commands[*].handler/name/summary/usage` 只有运行期读。`huart2.pTxBuffPtr` 只在 `USART2` 物理 IRQ 域读写；`huart2.hdmatx` 无运行访问；`huart2.hdmarx` 只有读。

`huart2.Instance`、`huart2.Init.WordLength`、`huart2.Init.Parity` 的唯一写点分别在 `Core/Src/main.c:178/180/182`：`Reset_Handler → main → MX_USART2_UART_Init`。前台及 `USART2_IRQHandler → HAL_UART_IRQHandler → UART_Receive_IT/UART_Transmit_IT` 的后续访问均为读。`HAL_NVIC_EnableIRQ(USART2_IRQn)` 在 `Core/Src/stm32f1xx_hal_msp.c:118`，证据链给出全部写先于使能。Reset 启动源码与 linker map 限定 main 前仅有 `SystemInit` 和 GCC `crtbegin` 的 4 字节 init-array 入口。`HAL_UART_IRQHandler` 中的 `UART_DMAAbortOnError` 回调槽赋值位于该 IRQ 内；即使回调日后由异步来源执行，静态调用图也显示它对这三个变量只读且不能到达初始化写点。因此三者均为 `SAFE_INIT_ONLY_WRITE`。任何未覆盖的发布点、错误 IRQ 屏障或回调可达写点都会保留 blocker，回归测试逐项验证。

### SUSPECT 与同源码访问

20 个 SUSPECT 均有 `vector:slot:1` 前台与 `vector:slot:54` USART2 IRQ 的 `CAN_PREEMPT` 读写/RMW 见证。例如 `cli.rx_head/rx_tail/rx_queue`、`DebugCliStats.rx_bytes` 和 `huart2.RxState/RxXferCount`；这些并非单纯函数数量造成的冲突。8 个相同 `access_id` pair 都是不同物理执行实例（前台与 USART2 IRQ），其源点在 HAL UART 接收路径，真实可能被两个调用域重入。没有同一个串行执行实例与自身构成并发冲突。双独立 IRQ 访问同一 callback 的回归仍判 SUSPECT；单 `handle->Instance` 分支回归被收敛到一个 IRQ。

### UNKNOWN 与 blocker 扇出

最终没有 UNKNOWN 变量。之前的 HAL UART DMA 函数中 `stm32f1xx_hal_uart.c:1408/3282` 两个回调赋值点，其发布函数在当前链接入口下已证明不可达，因此不能产生执行者。`HAL_UART_IRQHandler` 中 `:2428` 的发布点可达；对 `huart2.Init.Parity` 和 `huart2.Instance`，完整初始化证明和回调只读调用图排除了相关读写冲突，故不再阻止 SAFE。对另外 9 个存在真实前台/IRQ 冲突的变量，`:2428` 仍以 `UNKNOWN_EXECUTION_CONTEXT` 附加 blocker 保留，主分类继续是 SUSPECT，`analysis_coverage=PARTIAL`。最大单 blocker 扇出为 9，且每条均可沿 `UART_DMAAbortOnError → HAL_UART_ErrorCallback → Cli_*` 到达该变量；没有项目级或 TU 级无条件污染。原始 facts 中保留的 `INDIRECT_CALL` 等诊断没有进入无关变量的关键 blocker。

## 性能和交付物

真实工程最后一次扫描 CMake configure/build 成功，20/20 TU 全新提取。根据 `run.json` 时间戳，完整扫描耗时 152.2 秒；`facts.json` 38.30 MB、SQLite 24.87 MB、HTML 4.99 MB、JSON 报告 3.30 MB、Markdown 报告 0.91 MB（十进制）。峰值内存未采样，不填推测值。报告包括 `.ecra/index.html`、`.ecra/facts.json`、`.ecra/facts.db`、`.ecra/reports/global_static_concurrency.json`、`.ecra/reports/global_static_concurrency.md`。`--no-review` 下 CLI 的 `INCOMPLETE`/退出码 2 表示 20 条 SUSPECT 人工复核队列未处理，并非 configure、build、Clang 或静态分类失败。

## 遗留证明边界

当前工程没有满足 `SHARED_SINGLE_WRITER_READERS` 严格模型的变量，`SHARED_NO_REVIEW=0` 没有通过放宽门槛制造数量。20 个 SUSPECT 仍需人工判断业务协议是否容许交错；9 个附加 DMA 回调入口 blocker 也不能仅凭静态调用边证明具体硬件会否触发。若需复现请求中的 220 TU 故障，应将 `project.root` 指向那个构建变体并提供其真实 `compile_commands.json`；本报告不把 20 TU 工程的结果外推至未扫描的变体。
