# OpenCode 深层并发复核与真实案例库实施报告

实施日期：2026-10-18。实现由 Codex 直接完成；OpenCode 仅作为 ECRA 的只读复核模型被调用。

## 1. 真实调用链与原有局限

当前实现是变量级复核：

```text
Clang 提取 / 静态扫描（未修改）
  → SUSPECT / UNKNOWN 候选变量
  → build_variable_review_packet：全部访问、无损去重调用路径、上下文、保护、unknowns
  → REVIEW_PROMPT + 工程背景 + 案例索引/路径 + 原有 CONTRACT_PROMPT
  → opencode run --agent ecra-review --format json --file <变量Packet> -- <prompt>
  → OpenCode 按 Packet 中 file/line/end_line 只读源码和相关案例正文
  → 原有 parse_answer / Validator
  → 原有 PENDING / DONE / TECH_FAILED、归档与 HTML
```

完整运行入口为 `ecra/cli.py::run`；恢复入口为 `ecra/workflow.py::saved_run`，根据原有参数选择 `review` 或 `review-failed`。二者均把真实配置文件同目录的案例库路径传入 `review_all`。实际进程在 `ecra/review.py::review_all.process.invoke` 调用，工作目录仍为被扫描固件目录。

原 Prompt 已要求核查执行关系和保护，并已有 READ_THEN_WRITEBACK 的专项检查及单次语义 challenge。本次没有重新设计它。原有局限是检查要求分散，跨函数传播主要依赖已生成提示，关联资源/状态、异步生命周期及硬件瞬态缺少固定排查顺序，也没有自动加载的外部案例经验。

## 2. 固定八步方法

`ecra/review.py::REVIEW_PROMPT` 内部固定要求：

1. 确认真实存储、全部访问来源及遗漏的指针/回调/宏/间接内存访问。
2. 恢复前台、IRQ 嵌套、DMA、回调等执行域和实际抢占、阶段与屏蔽关系。
3. 主动追踪 READ → 参数/局部变量 → 多级调用 → WRITEBACK，识别隐式逻辑 RMW。
4. 构造符合平台条件的危险交错，覆盖旧值覆盖、TOCTOU、生命周期及硬件等待。
5. 检查标志/数据、长度/缓冲区、状态/所有权等有源码依据的关联约束。
6. 验证保护覆盖整个事务及所有路径，检查锁身份、阈值、提前退出和恢复。
7. 阅读案例索引和相关正文，将机制用于当前源码，同时考虑库外模式。
8. 反向审查安全结论，主动寻找反证；未知保留为合法 LIKELY / NEED_MORE_CONTEXT。

明确禁止把原子 load/store、同一 Setter、单个赋值位置或 last-writer-wins 单独作为安全证明；也要求接受完整保护、同一不可重入上下文等真正安全的对照。不要求输出八步过程，不新增逐 pair、Conflict Class、investigation 或安全状态机。

## 3. 案例库设计及来源

新增 UTF-8 中文 Markdown 文件 `config/concurrency_cases.md`，23 条案例使用统一元数据和八个正文小节，包含来源、可信状态、平台/模块、共享对象、执行上下文、机制、重写示意代码、危险交错、漏判原因、针对性排查、错误安全理由、安全排除条件、裸机适用边界和检索关键词。

按用户后续要求，案例库及追加模板不再放置链接；保留来源名称、公告/Issue/提交编号和确认状态，来源链接保留在本报告的追溯记录中。

共 **17 个独立实际缺陷/修复记录**：16 条项目安全公告或已核实合并修复，1 条厂商正式修复说明。另有 1 条尚未确认最终根因的工程报告，5 条官方技术依据、原理归纳或研究方法。Issue、对应 PR 及回补仅计一条；未将 CWE 或厂商示例当事故。

| 案例 | 原始证据 / 核实状态 |
|---|---|
| 0002～0008 | Zephyr 的 [net_buf 引用计数](https://github.com/zephyrproject-rtos/zephyr/security/advisories/GHSA-284j-5jm9-55hh)、[I3C 空闲链表](https://github.com/zephyrproject-rtos/zephyr/security/advisories/GHSA-gfj5-gcxv-9jqm)、[TLS 缓存锁粒度](https://github.com/zephyrproject-rtos/zephyr/security/advisories/GHSA-wcgm-pq6x-v2gf)、[UpdateHub](https://github.com/zephyrproject-rtos/zephyr/security/advisories/GHSA-vprh-rff6-46xp)、[SNTP 生命周期](https://github.com/zephyrproject-rtos/zephyr/security/advisories/GHSA-34wr-cg29-c4mw)、[socket double-fetch](https://github.com/zephyrproject-rtos/zephyr/security/advisories/GHSA-fcp3-vrr2-xfjv)、[queue peek](https://github.com/zephyrproject-rtos/zephyr/security/advisories/GHSA-8xm3-4w69-29mm) 安全公告；核实公开描述和修复说明。 |
| 0009 | STM32 SPI [#94265](https://github.com/zephyrproject-rtos/zephyr/issues/94265) 与已合并 [#98558](https://github.com/zephyrproject-rtos/zephyr/pull/98558)，核实错过 CSTART 后等待卡死及 EOT 出口修复。 |
| 0010 | ESP32 UART [#100955](https://github.com/zephyrproject-rtos/zephyr/issues/100955)，核实报告与日志；不宣称最终根因或修复已确认。 |
| 0011 | STM32U5 Abort [#103042](https://github.com/zephyrproject-rtos/zephyr/issues/103042) 与已合并 [#103367](https://github.com/zephyrproject-rtos/zephyr/pull/103367)，核实在 DMA 等待处检查 busy 的修复；未把早期 AI 推测当根因证据。 |
| 0012 | ESP-IDF [AES DMA 536d6ee](https://github.com/espressif/esp-idf/commit/536d6eea61faf5f9343a4bca9864230ce3121641)，核实完成等待从首描述符改为尾描述符的实际 diff。 |
| 0013 | ESP-IDF [esp_timer #11215](https://github.com/espressif/esp-idf/pull/11215)，核实检查移入锁内，避免定时器重复插入成环。 |
| 0014 | ESP-IDF [RMT da503640](https://github.com/espressif/esp-idf/commit/da503640a23b3c225160e459eb48adc7f8d4f9e2)，核实原子 RUN 发布移入临界区。 |
| 0015 | ESP-IDF [LEDC 95f8eb12](https://github.com/espressif/esp-idf/commit/95f8eb12d37aea88500084d5db4cad9ecf4b7af1)，核实首次状态读取及退出路径纳入保护。 |
| 0016 | FreeRTOS [e146d644](https://github.com/FreeRTOS/FreeRTOS-Kernel/commit/e146d6444c3d80b60dc75735438dc6c21d533747)，核实 malloc 使用同一局部容量快照。 |
| 0017 | Linux [7f101efd](https://github.com/torvalds/linux/commit/7f101efd236e14915bf35d5c2b62d10350a63b1c)，核实 test/clear 改为 test-and-clear 及真实通知协议后果。 |
| 0018 | Apache NuttX [#19849](https://github.com/apache/nuttx/issues/19849) 与合并 [#20641](https://github.com/apache/nuttx/pull/20641)，核实异步取消后仍在执行回调的生命周期问题。 |
| 0019 | [ST HAL F1 发布说明](https://github.com/STMicroelectronics/stm32f1xx-hal-driver/blob/master/Release_Notes.html)，确认厂商记录 UART/USART Tx/Rx 并发寄存器修复；未逐指令复现，RMW 示例明确是泛化方法。 |

此外直接访问了用户给出的全部 14 个初始来源，以及 [CWE-367](https://cwe.mitre.org/data/definitions/367.html)、[Linux ring](https://docs.kernel.org/core-api/circular-buffers.html)、[Zephyr ring](https://docs.zephyrproject.org/latest/kernel/data_structures/ring_buffers.html)、[AN4839](https://www.st.com/resource/en/application_note/an4839-level-1-cache-on-stm32f7-series-and-stm32h7-series-stmicroelectronics.pdf)、[CMSIS NVIC](https://arm-software.github.io/CMSIS_6/main/Core/group__NVIC__gr.html)、[CMSIS 寄存器](https://arm-software.github.io/CMSIS_6/main/Core/group__Core__Register__gr.html)、[Linux DMA](https://docs.kernel.org/core-api/dma-api-howto.html)、[SDRacer](https://arxiv.org/abs/2305.17869)。还检索了 RT-Thread、Microchip、NXP、TI、Infineon 及大学/IEEE 研究。未充分核实的检索结果没有转为已确认事故。

## 4. R01～R20 覆盖与缺口

| 分类 | 主要案例 | 证据边界 |
|---|---|---|
| R01 | 0001、0014、0017、0019 | 有 Lost Update/状态覆盖；同形多级 Setter 实际事故尚无已核实记录，0001 是原理示例。 |
| R02 | 0002、0014、0017、0019 | 引用递减、原子操作组合、寄存器 RMW。 |
| R03 | 0007、0008、0011、0013、0016 | 多类检查与使用窗口，硬件也会改变条件。 |
| R04 | 0019、0022、0023 | 已检索但暂无明确双 IRQ 嵌套触发的已核实独立事故；保留官方优先级依据。 |
| R05 | 0003、0009、0014、0015 | ISR/前台及抢占延迟。 |
| R06 | 0003、0006、0010、0018 | 工作队列/异步回调；0010 仍待确认。 |
| R07 | 0003、0006、0018 | 包装、callback、间接访问。 |
| R08 | 0002～0008、0018 | 结构体、列表、指针与对象池。 |
| R09 | 0005、0014～0017、0020 | 状态/容量/数据发布关系。 |
| R10 | 0010、0012、0021 | AES 实际修复及官方 DMA/Cache 技术依据。 |
| R11 | 0010～0012 | UART 完成/Abort、DMA 描述符全链完成。 |
| R12 | 0003、0008、0012、0020 | 所有权、节点复用及 SPSC 前提。 |
| R13 | 0004、0013～0015、0022 | 锁身份、范围、屏蔽阈值。 |
| R14 | 0002、0004、0006、0008、0018 | refcount、peek、异步释放和复用。 |
| R15 | 0009～0011、0019 | SPI/UART 及共享控制资源。 |
| R16 | 0009、0011、0019 | 瞬态与挂起状态。 |
| R17 | 0006、0014、0015、0018、0022 | 注册/取消/使能与在途使用。 |
| R18 | 0020、0021 | 官方技术依据；暂无已核实独立弱内存发布事故。 |
| R19 | 0021 | AN4839 官方示例；暂无已核实真实事故。 |
| R20 | 0013、0023 | 重复插入成环；研究验证方法不计独立事故。 |

## 5. 自动读取、追加生效与权限

`ecra/case_library.py` 每次 `review_all` 调用读取源文件，宽容提取标题、分类、识别线索与正文行范围。可选环境/关键词/URL 不要求完整。缺分类、线索、重复编号、未识别二级标题及坏 UTF-8 会警告；未索引内容仍可从完整快照读取。代码围栏内的模板和 HTML 注释不生成伪案例。

源路径从实际 `config_file.parent` 定位，不依赖 cwd。UTF-8/BOM、中文/空格路径使用 pathlib 和参数数组处理。正文原字节保存到 `<output>/review/case-library/<sha256>.md`，默认位于固件工程中，避免 OpenCode 无法跨目录读工具配置。源文件绝不覆盖。写快照失败时保留源绝对路径和受限外部目录读取方式；缺文件则警告，继续八步源码复核。

OpenCode 分析会话只获得读取所需文件的权限，命令/修改工具仍拒绝；格式修复会话保持所有工具拒绝。外部目录许可仅用于案例参考文件所在目录的读工具前置检查，文件读取本身仍由原有 read 白名单限制。案例库不能覆盖复核指令或决定判定。

正文 SHA-256 进入提示词，沿用已有 cache_key 计算：仅修改正文也会使正常运行的旧复核缓存失效。每轮重新生成索引，无后台服务和持久索引缓存。一次调用内所有变量使用同一快照，运行中追加的内容在下一轮生效。

日常只需追加 Markdown 后运行原命令：

```powershell
py -3.10 run_ecra.py
py -3.10 run_ecra.py review
py -3.10 run_ecra.py review-failed
```

`review-failed` 保持原语义，仅选择 TECH_FAILED；让已经完成的变量采用新案例应使用 `review`。

## 6. 输入长度控制

正文不全文注入。每个索引只保留编号、标题、分类、线索、正文行范围，较长元数据有显式省略标记。索引超过 12,000 字符时，保存完整 `<sha>.index.md`，提示模型先分段读取完整索引，不按关键词丢弃案例。已有超过 12,000 字符走 stdin 的 Windows 传输逻辑保持原样。

实施时测量（字符，不声称等于 token）：旧方法 Prompt 1,967 字符；新方法及证据边界要求 2,888；原合同 1,195；23 条索引/路径/哈希约 3,118；组合约 7,201，另加原有工程背景与 finding_id。当时正文文件 53,012 字节（后续按用户要求重命名并移除链接），要求按索引使用 read 的 offset/limit 读取相关行。实际调用路径长度导致少量差异。大正文测试使用约 1 MB 文本，提示词不随正文膨胀；千案例长索引转为完整索引文件。

## 7. 修改边界与文件

生产改动为：`ecra/review.py`（八步 Prompt、案例段及参考读取权限）、`ecra/case_library.py`（动态索引/快照）、`ecra/cli.py` 和 `ecra/workflow.py`（传入配置旁路径）。便携分发只在 `build_portable.ps1` 的配置复制清单和 ZIP 必需资产清单各添加一个案例库文件名，确保重新打包后仍自动携带案例库，没有修改构建流程。

新增 `config/concurrency_cases.md`、`tests/test_case_library.py`、`tests/test_deep_review.py`、`tests/fixtures/deep_review/{chain,coherence,dma}.c`，复用原有 direct/safe/unknown fixture；补充 README 及本报告。

未修改 Clang 提取、变量扫描、分类、Conflict Pair、最终 JSON 合同、Validator、状态机、报告页面代码或 dist 构建产物。原本已有的 `stale_writeback_assessment` 及一次 challenge 保持原样，没有新增模型输出字段。

## 8. 自动化测试

基线相关单测：57 项运行，56 项通过，1 项原有 opt-in live 测试跳过。

新增测试实际拦截 `ecra.review.execute`，检查 Packet 附件、原样保留的全部访问/调用链、八步提示、案例正文权限和最终 JSON 兼容。覆盖：

- 追加 CASE-TEST-999 / TEST_UNIQUE_CONCURRENCY_PATTERN，无需改 Python/YAML。
- 正文单独修改失效缓存、同内容复用、旧快照保留。
- 中文/空格配置与固件路径、cwd 分离、BOM/CRLF、可选字段、坏编码、重复/未识别标题及快照失败回退。
- 大正文不注入、千案例完整索引可读、长 Prompt 沿用 stdin。
- run/review/review-failed 三入口从真实配置旁加载最新库，重试只处理技术失败，静态 facts 不变。
- 格式修复不携带案例输入且无工具权限。
- 在 PowerShell 中单独执行打包脚本实际的配置复制循环，验证中文案例库被原字节带入便携配置目录；完整 ZIP 检查清单也含该文件。未重建或覆盖当前 dist 大型工具包。
- 六类真实 Clang fixture：直接旧值写回、多级参数链、两字段一致性、DMA 缓冲区、完整保护安全、未知优先级。DMA 外部寄存器实现缺失被保留为证据边界，不能凭注释伪称已证实硬件路径。

Mock 答案只验证传输、解析、归档兼容，不证明模型能识别风险。真实模型检查单独 opt-in，保存原始日志和源文件供审查。

全量运行 `py -3.10 -m unittest discover -s tests`：**656 项，654 通过、2 个 opt-in live 测试跳过，161.027 秒，无失败**。日志：`output/deep-review-final-tests.log`。其中包括原有解析、复核契约/归档、review/review-failed 入口、状态映射、HTML/报告兼容，以及扫描/分类回归。

之后根据真实模型观察补充两句提示词（限制案例读取范围、禁止用缺失 DMA 实现的注释直接确诊），相关回归命令：

```powershell
py -3.10 -m unittest tests.test_case_library tests.test_deep_review tests.test_review_integrity tests.test_review_contract tests.test_review_risk tests.test_stale_writeback tests.test_review_real_format tests.test_html_report tests.test_review_presentation
```

随后补充了“大索引写入失败时，已经成功建立的正文快照仍可读”的容错回归；上述相关命令最终结果：**77 项，75 通过、2 个 opt-in live 测试跳过，10.637 秒，无失败**。复核合同、Validator、状态机、HTML、AST 提取及分类模块在 Git diff 中均未修改，CLI 集成还核对复核前后 facts 完全相同。

## 9. 实际 OpenCode 验证与已知限制

本机有 Python 3.10、libclang、OpenCode 1.18.35 及模型配置。已对六个 fixture 通过 ECRA 原调用链尝试真实复核，首个端点 `kimi-open-platform/kimi-k2.6` 返回 HTTP 401 Invalid Authentication，六项均 TECH_FAILED，没有模型结论，不能视为功能通过。失败原始日志保存在 `output/deep-review-live/`，包含供应商错误，未复制到案例库。

使用另一已配置端点 `kimi/kimi-k2.7-code` 完成六例真实分析。每例只有一次 ANALYZE；没有 FORMAT_FIX、challenge、重试或超时，均被现有解析器接受。逐条检查工具事件，六例都实际成功 read 了 `app.c` 和案例库正文；并重新从导出的源码验证了六份归档 receipt。

| 场景 | 初次真实结果 | 调用耗时 | 判断 |
|---|---|---:|---|
| 直接 Setter 旧值写回 | CONFIRMED | 56.27 s | 明确 READ→实参→WRITEBACK 和 HIGH 抢占，未用原子 store 排除。 |
| FunctionA→FunctionB→Setter | CONFIRMED | 77.31 s | 按调用链追踪旧局部值。 |
| 状态 A/长度 B 一致性 | CONFIRMED | 124.87 s | 从代码中的相等检查识别混合快照。 |
| DMA/CPU 缓冲区 | CONFIRMED | 94.94 s | 未错误判安全，但依赖注释确认外部板级 DMA 行为，过度确认，需要收紧。 |
| 完整 IRQ 保护 | FALSE_POSITIVE | 115.63 s | 用完整 PRIMASK 窗口阻塞证明排除静态疑点，未把所有变量都报风险。 |
| IRQ 优先级缺失 | LIKELY | 65.77 s | 保留具体缺失优先级/抢占条件，未猜安全。 |

初次六例存档：`output/deep-review-live-cn/observations.json`、`verified-summary.json` 和各场景 `review/` 中的提示词、Packet、stdout/stderr、receipt。总测试运行 536.372 秒；初次每项提示词约 7,107～7,125 字符。表中 DMA 的 CONFIRMED 不是证据边界验收通过，Mock 也不用于掩盖此问题。

另一个观察是，多变量一例曾无范围读取整份案例库，而其他场景读取了对应 CASE 行段。为此实际 Prompt 增加了必须使用索引行范围的要求；对 DMA 注释证据不足的问题，增加“决定性实现/寄存器配置无法获取时列入 missing_context，不得仅凭假设 CONFIRMED”的要求，并把 DMA fixture 可接受状态收紧为 LIKELY / NEED_MORE_CONTEXT。

**最终 Prompt 的两例真实复测通过**（192.698 秒）：

| 场景 | 最终结果 | 耗时 / Prompt 字符数 | 实际读取与证据边界 |
|---|---|---|---|
| 多变量一致性 | CONFIRMED | 85.74 s / 7,260 | 成功读取源码；案例正文仅 offset=1076、limit=60，无全库读取。 |
| DMA/CPU 缓冲区 | LIKELY | 106.42 s / 7,254 | 成功读取源码；四次案例 read 均带 offset/limit。missing_context 明确列出 board_start_rx 实现/寄存器、IRQ 使能、DMA 与 CPU 实际重叠、Cache/MPU 和 busy 协议等缺口。 |

最终两例均只有一次 ANALYZE，无修复、challenge 或超时，现有解析器接受，并从导出源码再次通过 receipt 校验。存档：`output/deep-review-live-final/observations.json`、`verified-summary.json` 和各场景 `review/`。初次四个其他场景与最终两例共同覆盖六类 fixture；不把早期 DMA 过度确诊列为通过，也不声称每个模型都会给出相同答案。

局限：

- Prompt 是分析指导，不能形式化证明所有程序安全，也不能保证模型每次遵循全部步骤。
- 案例不是匹配规则；安全/缺陷结论必须来自本工程源码、调用、真实执行条件及保护证据。
- 外部板级 DMA、编译宏/IRQ 配置缺失时仍需补充；关 CPU 中断不能当作 DMA 停止证据。
- 原有 SAFE 变量仍不自动进入候选队列，没有借本功能扩大静态扫描范围。
- 记录中的泛化代码与时序明确标为示意；未对 17 个上游事故逐个硬件复现，版本声明不替代目标版本核查。
- 索引文件模式仍需模型先读取完整索引；语法警告时须查看未索引正文，不能把索引完整性当成安全证明。
- 未运行同一模型旧 Prompt 的性能 A/B；只能报告当前输入规模、实际调用耗时与是否超时，不能声称速度提升或零性能回归。
- 本机 `kimi-open-platform` 端点仍存在认证限制；成功实测使用另一已配置端点，没有修改用户的模型配置、凭据或 semantics.yaml。
