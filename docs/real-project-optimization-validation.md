# 真实工程扫描优化与验证（2026-10-26）

## 开发与实测范围

开发前工作区干净，分支 `optimize_ccc`，起点提交 `a1ea2076df76cc906383f4b04c5ebe10eaa88f98`。在该实现上继续优化，没有切换旧分支。全部扫描关闭 `review.enabled`、`review.prepare_packets`，命令显式使用 `--no-review`；保留静态 UNKNOWN 和待复核候选，不执行 OpenCode。

使用真实 STM32F103/FreeRTOS SmartFarm 的隔离源码副本 `H:/ecra_stm32_validation/git-diff-smartfarm-62tu`，61 个 C TU、1 个汇编输入及实际 ARM GCC/CMake/Ninja 构建。原工程 `H:/stm32_RAG/code/SmartFarm` 不参与修改。副本基准提交为 `ca90b75`，基准分支 `base`。这不是大型 H7 或目标板时序测试。

旧引擎、完整 Worker 响应、facts、报告和输入清单已独立归档，供同一源码快照的对照。采样诊断与原生完整扫描分开记录，诊断停止不计为完整扫描通过。

## 定位与修改

旧版真实全量扫描耗时 2103.937 秒，进程树 RSS 采样峰值 4081975296 B。其中跨 TU 指针求解 430.172 秒，上下文指针/调用图 1348.969 秒。旧版指针事实含 709459 个位置—目标关系，上下文解含 735695 个关系，均收敛。

对完整 Worker 事实的诊断采样及原生扫描的低开销采样显示，旧版逃逸闭包对具体数组元素重复扫描同形数组的所有兄弟元素，再通过 `overlaps` 排除不相交对象。30 秒热点采样共 1495 个样本，没有采样错误；这解释了大型数组下的重复匹配成本。

`Solver.overlapping_slots()` 对具体下标直接查找自身及通配替换位置；对通配、多维复杂查询继续完整匹配。不限制调用深度、变量数、下标范围或闭包传播。原有子对象、指针返回值、未知目标、逃逸缺口和缓存失效机制保持参与计算。`reachable_pointer_values()` 与 `copied_pointer_values()` 共用该精确候选索引。

差异调用链见证的 BFS 改为保存前驱/后继，每个顶点不再复制整条前缀和后缀。只为实际变化边还原展示路径，保留全部调用边，递归仍去重。12,000 层调用链与循环/断连图有独立回归。

开发中尝试了表达式值缓存及传递失效。试验版共 912 项，910 通过、2 项真实模型测试跳过；SmartFarm 完整访问/图/分类/保护/覆盖语义与优化前一致，不一致 0。但原生全量耗时 2174.078 秒，高于旧版 2103.937 秒；其中上下文阶段 1744.875 秒。该试验未显示整体收益，**已撤回，不包含在最终实现和最终验收中**。试验引擎摘要为 `6456875ada5725a0ed7487139031821ecff1e88a4fa6f5b154c26fa6bcdf2ce8`。原始记录保留于 `optimization-20261026/full-final`，这里的历史目录名不表示最终采用。

压缩指针集合的比较须按真实目标身份归一化，不能把数值 atom 分配、位图 ID 或显式/压缩格式当作语义变化。对应回归先在原实现复现失败，再修复；同一目标集合与真实 pointee 变化分别验证。

基准摘要缓存的 key 绑定 schema 2、静态引擎、完整 facts 哈希、清理复核字段后的静态报告哈希及 Git 重命名映射。每次仍先执行 `checked_scan(with_facts=False)`，验证原始 facts/报告、源码内容及预处理输入闭包。命中后省去完整 facts 的反序列化与再次规范化，摘要另有内容哈希并纳入 `assert_pin` 的发布/恢复检查。缓存损坏时重建摘要，基准源码被污染则阻止发布。

真实 Portable CMake 中文路径实测额外暴露了构建签名伪差异：同一逻辑源码在两版使用不同的 `TEMP/ECRA-paths/<hash>` NTFS 目录别名，旧比较仅替换真实 `project.root`，因而错误扩大到无关变量。现在仅对能解析到本版工程根内的路径参数按逻辑相对路径比较，保留编译驱动名，宏等非路径参数沿用原有比较规则；外部或指向其他目录的别名不当作项目内路径。原始命令、源码快照和 TU 缓存键未被改写。新增真实目录别名、宏/驱动变化及外部路径反例回归。

最终包内实际运行两轮：中文空格工程中 3 行完整盘点、仅 `g_mfcInterface.msgSp` 进入差异范围；第二轮 TU 与基准摘要均命中。两轮独立全量对照通过，完整 TIM4 访问仍保留，未生成 `diff_index.html`。首次夹具把日志写进 Git 目录而被输入校验拒绝，随后将日志及验收收据置于仓库外，没有放宽校验。此前未完成的长扫描因修复这一比较缺陷被停止，单独保留 operator-stop 收据，不计入最终通过数。

## 可复现入口

已有真实工程可使用 `scripts/benchmark_project_scan.py`。它不修改固件源码或配置，拒绝启用复核/证据包的配置，执行实际 CLI 并记录日志、输入有效性、阶段耗时、进程树 RSS 峰值、完整语义摘要和 SHA-256。退出 2 可表示保留静态未知/待复核，是否成功建模以 `analysis_valid` 和具体覆盖证据为准。

```powershell
py -3.10 scripts/benchmark_project_scan.py `
  --project H:/ecra_stm32_validation/git-diff-smartfarm-62tu `
  --config H:/ecra_stm32_validation/git-diff-smartfarm-62tu-semantics.yaml `
  --scan-mode diff `
  --evidence H:/ecra_stm32_validation/optimization-20261026/repeat-diff
```

同一当前源码的全量对照增加 `--reference <前一轮证据目录>/summary.json`。该对照检查完整变量证据维度、函数、完整调用边、指针/执行语义、覆盖缺口和构建输入摘要，不只比较风险标签。证据目录必须不存在，防止覆盖之前的测量记录。内存采样依赖 `psutil`，该依赖仅用于测量脚本。

重放时为 `--work` / `--evidence` 选择不存在的新目录，保护已有证据。完整数值、各阶段耗时、峰值内存及指纹见[机器可读结果](real-project-optimization-results.json)。

## 路径生成的独立内存测量

对同一条 4096 节点调用链和一条变化边，使用标准库 `tracemalloc` 分别测量旧、新 `representative_paths`，返回见证完全相等。旧实现峰值 137105848 B（约 130.8 MiB），新实现 2435648 B（约 2.32 MiB）；启用跟踪时分别耗时 0.190 秒和 0.039 秒。这是展示路径算法的微基准，**不是固件全扫描峰值或硬件测试**。实际 12,000 层回归另行通过。变化边很多时，保存相应见证本身仍有输出成本，未用数量限制截断证据。

Portable 的 Python 3.10.9 显式加载当前工作区模块，18 项重叠索引、指针编码、位图、路径及真实目录别名回归通过。另重新生成包内全部文件哈希并执行目录包隔离验收，22 条接口检查及 419 个 PE 的依赖检查通过，实际模型复核未测试；没有生成或验收 ZIP。

## 最终自动化结果

最终静态引擎摘要：`ce31da1f921864b82a7fc1331a9b5bfcfcae976f5cee6eda1dafbfc5eab5d8ad`。

```powershell
py -3.10 -m unittest discover -s tests -q
py -3.10 -m unittest tests.test_emergency_memory -q
```

最终全套 **共 912 项，910 通过、2 跳过、0 失败，耗时 751.499 秒**；跳过的是需要显式启用真实 OpenCode 的测试。完整日志 `git_diff_optimization_release_regression_retry.log`。定向内存回归 4 项通过、44.200 秒；包内运行时回归 18 项通过、6.621 秒。后两组与全套存在重叠，不累加成独立用例总数。`git diff --check` 和相关 Python 编译检查通过。

开发期曾复现压缩/显式指针集合比较失败、基准摘要首轮复用失败和 Portable 路径别名伪差异，均已修复。前一次最终回归 912 项中有 1 项故障注入夹具准备超时：其 30 秒时限包括两轮真实 Clang 扫描。增加独立、受限的准备时限后重新执行全套通过；实际 CLI 内存注入仍为 **192 MiB**，保留旧报告失效、检查点移除及锁清理断言，没有扩大注入后的内存额度。

## 真实 SmartFarm 全量对照

实际命令：

```powershell
py -3.10 scripts/benchmark_project_scan.py `
  --project H:/ecra_stm32_validation/git-diff-smartfarm-62tu `
  --config H:/ecra_stm32_validation/git-diff-smartfarm-62tu-semantics.yaml `
  --scan-mode full `
  --evidence H:/ecra_stm32_validation/optimization-20261026/full-release `
  --reference H:/ecra_stm32_validation/optimization-20261026/before-summary-pathfix.json
```

参照摘要从独立保留的优化前原始 facts 重新规范化生成，没有改写原始证据。61 个 C TU、3935 个函数、327 行清单；其中 277 个实际归账对象为 SAFE_PROVEN 168、SUSPECT 106、UNKNOWN 3，待复核 109。其余为容器/汇总行。missing=0、duplicate_ids=0；完整访问、图、冲突、保护、覆盖与分类的语义不一致 0。

本轮耗时 **2362.032 秒**，进程树 RSS 采样峰值 4079824896 B（约 3.80 GiB）。初始指针阶段 182.282 秒，上下文阶段 1758.938 秒。**本轮没有证明 SmartFarm 总时间下降**，不能用初始阶段改善代替总体提速结论。历史全量 2103.937 秒与本轮存在调度、并行验证和主机负载差异；完整全局求解仍是后续主要优化对象。输入 VERIFIED、analysis_valid=true，静态仍 INCOMPLETE，退出 2，保留原有未知和待复核。

## 真实 STM32CubeF4 CDC 差异矩阵

使用已有、固定 ST STM32CubeF4 v1.28.3 的 CDC 接入副本 `validation/stm32_cube_cdc_20261018/projects/p00`；上游提交 `94cae6e83f00e276a11957e7833c01ac3d0bd7af`。保留原 CDC/USART/DMA 应用、HAL、USB 中间件及既有的无操作 Lab 挂接。新测试只在独立复制目录修改真实业务源码，不改原工程，不注入几十行替代背景工程。

```powershell
py -3.10 scripts/validate_cdc_git_diff.py `
  --source H:/global_static_concurrency_design/validation/stm32_cube_cdc_20261018/projects/p00 `
  --work H:/ecra_stm32_validation/optimization-20261026/st-cdc-release
```

副本基准 `17f408d1ac8097f6aca8286e2a44b3e203e073c4`，最终 HEAD `b86b41b12eb43bdb0e459b8afede32cb29feb4b7`。依次修改实际 `UserTxBufPtrIn` 的步长、UART DMA 通道宏和 USART IRQ 优先级。每轮 39 个 C TU，244 行清单、210 个实际归账对象；最终 SAFE_PROVEN 5、SUSPECT 135、UNKNOWN 70，待复核 205，归账缺失/重复均 0。

| 轮次 | 秒 | 当前版重新提取 | 当前版缓存命中 | 进程树峰值 MiB |
|---|---:|---:|---:|---:|
| 基准全量 | 397.485 | 39 | — | 920.2 |
| 首次差异 | 785.875 | 39 | 0/39 | 1222.1 |
| 热差异 | 219.453 | 0 | 39/39 | 806.7 |
| 当前版独立全量 | 279.953 | 39 | — | 920.7 |
| 头文件宏差异 | 178.500 | 4 | 35/39 | 813.5 |
| IRQ 配置差异 | 161.265 | 1 | 38/39 | 802.6 |
| IRQ 版本独立全量 | 263.750 | 39 | — | 918.2 |

首次差异另独立建立了基准事实，表中提取数仅指当前版主流。索引修改版本及最终 IRQ 版本均与独立全量完整语义相等，分类/语义不一致为 0；中间头文件提交执行了失效验证，没有冒充单独做过该提交的全量对照。

本工程存在未解析依赖、全局别名及执行语义影响，四轮差异均 **L1 保守扩大到 244 行目标清单**，不能宣称已精确收窄此工程，也不将全部入选解释为新增风险。缓存复用没有丢掉其他 IRQ、HAL 回调和 DMA 证据。全部输入 VERIFIED，静态保持 INCOMPLETE，没有实际模型任务。

## 129 TU H7 集成矩阵与串行性能对照

实际执行 `scripts/validate_git_diff_stm32.py --work H:/ecra_stm32_validation/git-diff-h743-129tu-v11 --vendor H:/ecra_stm32_validation/inav/lib/main --compiler D:/gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc.exe --units 128`。

七轮全量、首次/热差异、头文件、NVIC 与独立全量验证均完成。129 TU、653 行清单；523 个实际归账对象为 SAFE_PROVEN 394、SUSPECT 128、UNKNOWN 1，候选 129。常规热差异命中 129/129 TU，公共头文件改变后重新提取 129 个，NVIC 仅重提取 1 个、命中 128 个。最终独立全量额外提取 129 个 TU，653 行完整证据比较通过，分类/语义不一致 0。详细主矩阵时间见机器记录，部分计时有其他验证任务并行，不能据此作隔离性能推断。

其他 ECRA 验证结束后，在同一提交设 `verify_against_full: false`、固定 `PYTHONHASHSEED=0`，先预热，再连续扫描；不关闭任何输入/依赖验证。机器并非独占。

| 轮次 | 秒 | 当前 TU 提取/命中 | 基准摘要缓存 | 峰值 MiB |
|---|---:|---|---|---:|
| 恢复常规配置并预热 | 99.484 | 0 / 129 | 重建 | 400.1 |
| 热差异一 | 85.438 | 0 / 129 | 命中 | 366.7 |
| 独立全量 | 62.672 | 129 / 0 | — | 429.1 |
| 热差异二 | 79.937 | 0 / 129 | 命中 | 354.8 |

四轮完整语义相等；热差异仍慢于同轮全量，说明基准闭包复查、全局分析和比较开销不能忽略。确认了 AST 与摘要复用、较小的本轮热扫描内存，没有将它描述为所有工程都获得总耗时收益。

## 交付边界

源码在 `optimize_ccc`，本轮未提交或推送；以引擎摘要及文件哈希识别实际实现。只复用现有 index.html，未新建差异页面。源码/事实/分类/复核范围仍分开，未修改原始 symbol_id、静态分类或输入快照规则。

真实 F1/F4 工程和生成的 H7 集成夹具分别记账；没有生产级大型 H7 应用完整矩阵、目标板烧录、实际 OpenCode 模型复核或 ZIP 验收。未知依赖仍可扩大到完整目标范围；进一步降低全局求解和重复预处理成本仍需专项优化。这些对照只覆盖已建模、已解析的证据，不能当作所有实际硬件行为零漏报的证明。
