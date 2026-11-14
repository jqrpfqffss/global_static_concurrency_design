# ECRA 分支一致性回归

本轮比较 `optimize_cc` 的 `ac96abc39ffc66de53e57df82ca0ee791907bce6`（A）、`optimize_ccc` 的 `f7a4f32a7d2257dff955bfcab3e613c52586ebc0`（B）以及基于 B 的修复工作区（C）。A/B 使用分离 HEAD 工作树。C 的代码身份同时使用基础提交、静态引擎摘要和工作区补丁摘要。

固定编译输入后，本机 `serial - opencode` 的全量重扫三版均为 58 行，其中 49 个独立分类对象。找到了不同固件版本、不同 TU 集与不同扫描模式造成的历史统计差异。另用真实 ARM 构建和 Clang 反例复现了 C++ TU 静默漏收、多个 RTOS 任务实例误判安全和发布失败收据仍标记有效，三项均有修复和回归。

INAV 的固定 STM32H743 固件已实际构建。A/B/首轮 C 均完整解析 388 个 C 翻译单元，逐变量核验了全部 4,044 个实际定义根。B 与首轮 C 的 16,566 行清单和 12,172 个独立分类对象的静态结果相同。大型工程最终验收仍为 **BLOCKED**。A 第 3 轮在分类期间耗尽内存，独占重试已排队。B 正在发布。C 第 3 轮检测到源码更新并拒绝发布，第 4 轮用新引擎在隔离工作区冷扫。现有历史记录尚无法唯一定位用户报告的两次原始扫描。

后续影响核查复现并补修了 RTOS 任务归属和任务数量的兼容性问题，以及新增 C++ 用例污染后续 MinGW 用例工作目录的问题。后续补修的引擎身份、专项回归、真实扫描结果和未完成项记录在 `acceptance.json` 的 `impact_verification` 中。

## 复现

隔离证据目录为 `I:/ecra-parity-20261114`。其中保留下载、构建、输入核验、版本适配前后语义、扫描命令、诊断、结果库和历史报告的只读副本。每次扫描的 `execution.json` 记录实际调用及退出码，`engine.json` 记录版本和配置摘要。等价性检查使用 CMake 原始数据库、Ninja 目标图、链接 map 和 ARM GCC 实际头搜索路径。

1. 使用 `scripts/prepare_inav_h743.py` 从官方仓库准备固定 INAV 和 `MATEKH743.elf`。证据目录的 `inav-preparation/preparation.json` 保留完整命令。
2. 使用证据目录的 `prepare_parity.py` 从真实 CMake 数据库按 Ninja 对象身份选出完整目标。`crosscheck_inputs.py` 单独复查命令、链接对象和有效 Clang 参数。适配只将传入 Clang 的 GCC LTO 并行度选项 `-flto=1` 映射为 `-flto`。
3. 使用证据目录的 `run_parity.py` 执行带 Windows Job 资源计量的新扫。也可用 `scripts/run_branch_parity_scan.py --engine <版本工作树> --config <版本配置> --evidence <新证据目录>` 直接记录各阶段。A 加 `--legacy-cli`，内部执行 `run --config <A.yaml> --no-review`。B/C 走 `run --config <版本.yaml> --scan-mode full --no-review`。观察器调用实际 CLI，记录准备、合并、范围、投影和分类边界。
4. 用 `scripts/audit_github_stm32_inventory.py <固件根> <配置> --units <核对过的有效参数.json> --expected-only --output <AST 收据.json>` 独立枚举。使用 `--expected <AST 收据.json> --stage <观察目录/L6-L7-analyzed.json>` 对照扫描根对象，也可传 `--scan-dir <扫描目录>` 核对已发布结果。
5. 用 `scripts/compare_regression_branches.py --evidence I:/ecra-parity-20261114 --project <工程> --left A:<轮次> --right B:<轮次> --fixed C1:<轮次> --output <新对照目录> --compare-accesses` 序列化对象身份、实例、解析诊断、逐阶段归账、原始静态分类、实际展示决策和证据差异。调用图比较覆盖所有已解析的入向边，访问比较另保留最短路径见证。完整控制流、未解析边、NVIC、DMA 和保护证据在相应权威事实中复核。

本目录的 CSV 覆盖已完成的串口项目与 ARM 夹具。`missing_variables.csv` 中 3 个变量是独立 AST 证明 A/B 都漏收的对象，A/B 两次已完成全量之间的缺失数为 0。大型工程的独立枚举、逐阶段输出、进程日志和完整数据库保留在隔离验证目录。`final-continuation.json` 记录后续各轮及审计步骤的当前状态，`acceptance-current.json` 更新运行进展，最终结论仍需逐项验证原始收据。

[根因与修复](root_cause.md) · [归账口径与实测](scan_comparison.md) · [机器可读验收](acceptance.json)
