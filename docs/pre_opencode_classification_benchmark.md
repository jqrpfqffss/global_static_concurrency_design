# Pre-OpenCode 静态分类真实工程基准

本报告记录截至 2026-09-30 的实现与验证进展，尚未完成最终验收。三个真实构建闭包已有固件产物；Klipper 已完成 36 项 SAFE 源码审计，但仍须在最终统一引擎上复核。Betaflight / Blackmagic 的完整分类和各 30 项 SAFE 审计未完成。未运行 OpenCode。

## 根因与分类模型

原模型把诊断存在性与变量并发结论混用。`FUNCTION_ADDRESS`、间接调用、指针下标和外部调用在大型工程中的数量很大；缺少对象、调用者和物理入口的关联性约束，会把局部缺口放大为整个工程的筛选障碍。优先级和保护未解析又会把已有的冲突降为 UNKNOWN，掩盖可直接复核的风险。

新模型先建立 canonical storage，再为每个对象建立 `VariableEvidenceSlice`：定义和链接可见性、直接/alias 访问、whole-object 影响、地址逃逸、完整相关调用图、物理执行域及访问窗口保护。项目诊断本身不产生变量 UNKNOWN。

分类顺序固定为：

1. 存储重叠、至少一方修改、不同物理执行者可能交错，而且未证明完整保护：**SUSPECT**。IRQ priority unknown 或保护有效性未确认不改变此结论。
2. 没有已知冲突，但 slice 内存在可能隐藏冲突的关键缺口：**UNKNOWN**。
3. 没有冲突且相关证据覆盖足以完成具体静态证明：**SAFE**。

classification 与 coverage 独立保存，允许 `SUSPECT + PARTIAL`。file-static / function-static 的链接可见性隔离无关缺失 TU。所有串行主循环任务归入 FOREGROUND，callback 继承实际调用者，同一物理 IRQ 不产生自我并发。函数指针赋值、表、结构体 initializer、注册、weak override 和可恢复 linker section 使用同一套通用规则。

## SAFE / UNKNOWN 证明契约

SAFE 必须同时保存 `safe_reason_code` 和 `safe_evidence`，已实现：

| proof code | 证明依据 |
|---|---|
| SAFE_NO_RUNTIME_ACCESS | 无可达运行访问，且没有相关遗漏访问证据 |
| SAFE_READ_ONLY / SAFE_MULTI_CONTEXT_READ_ONLY | 所有可能运行访问只读，无未知写者或整对象写 |
| SAFE_SINGLE_FOREGROUND | 全部访问属于同一串行 foreground |
| SAFE_SINGLE_IRQ | 全部访问属于同一物理 IRQ |
| SAFE_NON_INTERLEAVING | 所有修改相关 context pair 均已证明不可交错 |
| SAFE_EFFECTIVE_PROTECTION | 全部冲突窗口有已证明有效的保护 |
| SAFE_INIT_ONLY_WRITE | 写点位于已证明的 Disable→写入→Enable 初始化边界内 |
| SAFE_DISJOINT_STORAGE | 字段/常量数组元素不重叠；作为可审计的补充证明 |

初始化证明目前仅覆盖保守的显式 CFG 条件，不能把函数名带 Init、main 中调用、volatile、32 位访问或检测到 Lock 当作安全理由。

UNKNOWN 使用变量相关 reason code：`UNKNOWN_RELEVANT_ALIAS`、`UNKNOWN_RELEVANT_INDIRECT_CALL`、`UNKNOWN_ADDRESS_ESCAPE`、`UNKNOWN_RELEVANT_MISSING_TU`、`UNKNOWN_EXECUTION_CONTEXT`、`UNKNOWN_DMA_LIFETIME`、`UNKNOWN_INLINE_ASM`。每个 blocker 保留代码位置、目标存储和 relevance，报告唯一变量 fanout；不使用 UNKNOWN_GENERAL。复核队列只收 SUSPECT / UNKNOWN，按 canonical variable 去重，不按 context pair 重复提交。

## 本轮额外发现的通用缺陷

- GNU statement expression、va_arg、cleanup 和赋值表达式的指针值缺失会漏访问；已恢复并加入防 false-safe 回归。
- 编译期恒假分支中的 opaque call 曾制造地址逃逸；现在仅按可证明的常量条件移除不可达 body，并保留条件求值副作用及原始证据。
- 启动汇编的注释、已解析向量与 `.weak` 声明曾禁用 callback 参数条件证明；现在逐处消歧。向量之外真实未知汇编调用仍保留缺口。
- 宏展开的 section 属性可能没有 Clang token；改读 Clang 展开后的声明，且排除 initializer 字符串。跨 TU 合并必须保留实际定义上的 section、数组尺寸和布局，不能由先到的 extern 声明决定。
- 全局结构体嵌套数组路径与 pointer slot 路径格式不一致，造成正常字段被误合并为 whole-object overlap。新布局保留每一维数组边界和字段，未知维度使用有限通配摘要。
- 大型 points-to 集合采用无损位集合，依赖失效缓存减少重复求值；证据不再为每个成员递归复制整份调用图。求解失败不输出 SAFE，也不冒充 UNKNOWN 分类。

## 固定源码与真实固件目标

| 工程 | 固定 commit | 选择的固件目标 | 实际链接编译项 |
|---|---|---|---:|
| Betaflight 4.5.2 | `024f8e13d4e642eb6a380308685b9ea3aa3ef1a2` | 官方 `STM32F405`，Cortex-M4F，默认固件功能 | 418（416 C TU + 2 汇编） |
| Klipper v0.13.0 | `61c0c8d2ef40340781835dd53fb04cc7a454e37a` | STM32F103xE、Cortex-M3、8 KiB bootloader、8 MHz 晶振、USB PA11/PA12 | 50 |
| Black Magic Debug | `07184d19e64db602251bf8dcf41bac76808e6a83` | 官方 `cross-file/native.ini`，STM32F1 native probe、BMD bootloader | 104 |

三个目标均实际编译、链接成功，验证了 ELF magic 与 `e_machine=40`（ARM）。数据库没有从仓库源码列表拼造：Betaflight/Klipper 由透明编译包装器记录成功的真实 GCC 调用，再与成功链接命令中的对象交集；Blackmagic 使用 Meson 数据库、Ninja native ELF 依赖图及真实 link map 中选中的 libopencm3 thin-archive 成员。宿主 BMDA、独立 bootloader、生成 flashstub 的其它 MCU 编译项均不进入 native 固件并发分析。

构建依据：[Betaflight 固定版 Makefile](https://github.com/betaflight/betaflight/blob/024f8e13d4e642eb6a380308685b9ea3aa3ef1a2/Makefile)、[Klipper 固定版 STM32F103 配置](https://github.com/Klipper3d/klipper/blob/61c0c8d2ef40340781835dd53fb04cc7a454e37a/test/configs/stm32f103.config)、[Blackmagic 固定版 native 配置](https://github.com/blackmagic-debug/blackmagic/blob/07184d19e64db602251bf8dcf41bac76808e6a83/cross-file/native.ini)。

机器可读构建证据：`output/preopencode-benchmark/{project}/build-closure.json`、`compile_commands.json`、`firmware.map`、根目录的 `*-build.log` 与 `build-closure-verification.json`。三项目所有记录的 source/object 均存在，ELF SHA-256 与记录一致。

## 环境与比较方法

固件构建使用 GNU Arm Embedded 10.3-2021.10、官方 Make/Meson 构建系统。Windows 宿主的兼容处理只涉及工具 `--version` 输出 CRLF 和 GCC 自动 LTO 并行度：Klipper 链接明确使用 `-flto=4`；固件源码未修改。包装器保存的是实际执行的编译参数。

Clang 解析统一保留真实架构、宏、include 与 ABI 参数；移除不影响 C 语义的 GCC 专用优化/链接开关，并追加 `-Wno-error`，避免将 GCC 与 Clang 不同的警告政策混同于 AST 解析失败。所有 warning 仍保存在诊断中，真正 Clang error 仍计入解析失败。该配置对 baseline 与 after 完全相同。

baseline 在本次修改开始时冻结于 `output/preopencode-benchmark/baseline/ecra/`，仓库 HEAD 为 `6e998c788b8651fcff3cdebe1c3c1c40c3b1a9c3`。使用同一实际构建闭包，只比较生产提取器、points-to、调用图与分类器的差异；不把 off-target 补充盘点计入任何一侧的运行变量。canonical member/array 拆分可能改变分类项分母，因此另报告相同根 storage 的汇总比较。

旧 Betaflight 首轮 416 个 C TU 全部因 warning-as-error 失败，其结果无效，不计入基准。调整 warning 策略后的 `before-verified` 在冻结引擎 `context_graph()` 中枚举所有无环路径时发生 `MemoryError`，没有产生有效分类；不修改 baseline 或将失败误报为 100% UNKNOWN，UNKNOWN/队列降幅不能量化。

Betaflight 的 upstream `atomic.h` 显式提供 `__clang__` 分支，使用 Blocks 实现 cleanup memory barrier，而 GCC 分支使用 nested function；最终解析 profile 追加 `-fblocks` 以解析该上游兼容分支，没有替换宏或修改源码。两者都是编译器 memory barrier，不是 IRQ 屏蔽证明；Blocks/cleanup 的控制流覆盖需独立核对，解析成功不等于有效保护。

当前统一重跑快照为 `engine-after-d769cb5860fc`；完整 SHA-256 与逐文件 hash 保存在 `output/preopencode-benchmark/active-after-engine.json` 和该快照的 `manifest.json`。每次修复都新建冻结快照并全新提取。此前 `99b3d6121a2c` 等中间结果已暴露提取缺口，不作为最终验收基准；重分类旧 raw-facts 的运行只用于诊断。

## 已确认的 baseline 现象

| 工程 | 分类项 | Global | File static | Function static | Struct member | SAFE | SUSPECT | UNKNOWN | UNKNOWN % | 逐变量复核队列 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Klipper | 686 | 21 | 221 | 93 | 351 | 341 | 0 | 345 | 50.29% | 345 |
| Blackmagic native | 682 | 107 | 86 | 13 | 476 | 8 | 0 | 674 | 98.83% | 674 |
| Betaflight | baseline 调用路径枚举 OOM，无有效统计 | — | — | — | — | — | — | — | — | — |

Klipper baseline SAFE 为 `NO_RUNTIME_ACCESSES` 340、`ONLY_READS` 1；Blackmagic 为 `NO_RUNTIME_ACCESSES` 1、`ONLY_READS` 7。它们是旧引擎输出，不等同于完成 SAFE 源码审计。基准只以有明确证据的最终新规则判断 false-safe。

Blackmagic 中 `FUNCTION_ADDRESS` 影响 481 项、`INDIRECT_CALL` 469 项、`POINTER_SUBSCRIPT` 460 项，展示了需要变量相关性切片检查的高 fanout。一个变量可同时有多个 blocker，原因计数不可相加作为变量总数。更详细根因聚类见 [unknown_root_causes.md](unknown_root_causes.md)。

## 最终结果与独立审计

最终统一快照的分类结果、前后 UNKNOWN/队列变化及 proof 分布待扫描完成后更新。最近一个完成的中间 Klipper 运行 `after-assembly-entry` 有 733 分类项、SAFE 494、SUSPECT 18、UNKNOWN 221、队列 239，50/50 TU 解析成功；它仍受 extern 合并丢失 section 的缺陷影响，不能作为最终降幅或 false-safe 结论。

[Klipper 36 项源码审计](benchmark_safe_audit_klipper.md)覆盖四类存储和两种已出现的主 proof。样本在 `after-exact-sets`、`after-branch-context`、`after-vector-guards` 的分类与主 proof 均未变化；这只验证样本对应关系，不替代对新增 SAFE 的源码审计。

Betaflight 最新失败发生在大规模别名传播；Blackmagic 曾完成求解后在递归复制 evidence slice 时内存耗尽。失败运行不计入分类百分比，不报告虚构的队列降幅。抽样脚本只生成候选，初始状态一律为 `PENDING_INDEPENDENT_SOURCE_REVIEW`。

## 大型调用图的有限存储

旧算法显式枚举所有无环路径，30 层 diamond 图即有超过十亿条 root-to-leaf 路径。新算法保存完整 context roots、reachability、调用边和递归边；小图继续列出全部路径，大图以明确标记的最短见证作展示。`facts.context_call_graph` 与 `facts.call_graph_slices` 是完整证据，`all_call_chains` 在图模式下是见证视图，见证计数不冒充全部路径数量。

保护证明仍遍历完整 CFG/被调函数，相关保护事件从完整逆向调用图切片取得。回归已验证：最短调用链受 PRIMASK 保护但更长路径未保护时仍为 SUSPECT；两条路径都完整屏蔽时才可 SAFE。另覆盖 30 层 diamond 全边保留、显式 `max_call_paths` 超限仍失败、递归边保留、`allowed_contexts` 约束以及两个 IRQ 的不同 pointee 不混入对方 mask window。

当前尚不能宣称：三个工程已满足最终验收、UNKNOWN 已主要来自真正静态边界、SAFE 没有错误扩大，或 OpenCode 队列已经显著缩减。
