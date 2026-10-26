# Git 分支差异并发扫描：实现与验收记录

## 开发基线和架构审查

2026-10-25 开发前执行 `git status --short`、`git branch --show-current`、`git log -1 --format=fuller`：工作区干净，分支 `optimize_ccc`，提交 `bafe1ee911c38960beae668cd5ced340a1bdb6f1`。执行 `git fetch origin optimize_ccc` 后，`git rev-list --left-right --count HEAD...origin/optimize_ccc` 为 `0 0`。没有从旧优化分支覆盖源码。

现有真实流程：`load_config → compilation.prepare → InputSnapshot.discover/seal → 独立 Clang Worker → FactParts → merge/resolve_linkage → points_to.enrich → 存储成员/数组规范化 → 完整入口及调用图 → NVIC/保护/覆盖证据 → 静态分类 → report.generate → workflow.save_scan → review_all → 最终快照检查`。本版在同一流程增加基准分析、TU 缓存和独立影响集合。

* 外部链接变量/函数采用 Clang USR；内部链接对象增加 `tu::<源码相对路径>::`；函数 static 使用所属函数、名字和同名 ordinal。成员/数组沿用现有 canonical storage ID。行号不是存储身份。
* `context_call_graph` 保存完整上下文入口和边；`calls` 保存调用点；`call_graph_slices` 保存访问者的完整上游切片。HTML 的最短见证和有限路径列表只是展示。
* `facts.json` 保存完整事实；`facts.db` 的事实表和 findings 表按 symbol_id/function_id/finding_id 关联。`report.findings` 仍是完整静态候选及盲区集合，不按差异删除。
* `review_targets()` 生成本轮队列，`review_integrity()`/归档校验使用同一入口。新增 `report.git_diff.selected_symbol_ids`，不改变静态归账。
* 原 HTML 由变量、finding、源码访问视图和变量决策统计构成。差异模式在 `write_html` 校验完整事实后建立浅层展示视图；完整构建覆盖统计明确标识其分母。
* 输入有效性继续依赖实际命令、Clang 预处理签名及消费内容、源码读取、闭包重放、引擎摘要和发布后验证。复用原子写入、失败归档、流式事实和应急内存处理。

瓶颈主要是多次预处理、AST 提取、全局指针分析和大型证据输出。本版减少重复 AST 提取和复核任务，不声称已将全局求解改为局部增量计算。

## 配置和 Git 比较规则

唯一项目配置 `analysis.git_diff`：

```yaml
enabled: false
target_ref: origin/master
compare_mode: merge_base
include_uncommitted: false
cache_enabled: true
verify_against_full: false
uncertain_impact_policy: expand_or_full_scan
```

引用属于 `project.root` 的固件仓库。默认关闭。`--scan-mode full|diff` 仅改变本次内存配置；恢复沿用检查点模式。配置严格检查类型、允许值和未知键；构建前检查 Git 与引用。

固定目标 SHA、HEAD SHA、merge-base（适用时）、实际基准、仓库根、项目子目录、工作区内容摘要和文件增删改/重命名。`direct` 使用目标 SHA，`merge_base` 使用共同祖先。路径采用 NUL 分隔，不通过 shell 拼接执行 Git。

未包含工作区时，未提交文件导致明确失败，不将工作区冒充 HEAD。启用后同时绑定暂存、未暂存、未跟踪文件；构建和报告输出须由固件 `.gitignore` 排除。忽略的生成头文件仍受 InputSnapshot 校验。发布前后和恢复时重查引用及内容。用户固件工作区不执行 checkout/reset/clean。

## 双版本事实和变量匹配

基准在输出目录 `git_diff/base-<SHA>` 的 detached worktree 使用相同引擎独立扫描。CMake 使用旧源码重新配置/构建，不复制 HEAD 构建产物。非 CMake 工程须有基准提交内可重定位的真实编译数据库；缺失则明确失败。版本内数据库只重定位项目根路径，外部工具/头文件继续受原快照约束。

基准完整检查点有效时复用，失败则重新扫描。基准部分解析/失败不能当作无变化。worktree、原始事实及 SHA 保留供审计。两版顺序执行，基准完整 facts 释放后，仅把规范化变量摘要交给当前分析。

变量按语义身份匹配，Git 重命名映射修复 TU 与文件 static USR。不同 TU 和函数 static 不按名字合并。无法可靠确认变量/函数改名时，保留旧对象删除证据和新对象的 `MATCH_UNCERTAIN`，不宣称已修复或新增风险。现有 symbol_id 不改写。

## 语义传播与完整图比较

提取器新增完整函数/变量 token 摘要，排除注释，不按行号认定修改。变量证据比较声明、访问、上下文、完整图、保护、冲突、安全证明、覆盖及分类，所有原因按存储对象聚合。

变量完整定义会覆盖先前 extern 声明的摘要，初始化器超出原展示字段 500 字符的部分仍参与比较。TU 元数据另存活动源码/头文件宏定义的完整语义摘要，包含函数式宏标志；因此 `.c` 内仅修改宏值而调用图/访问模式不变，也会触发构建语义扩大。自动局部指针 slot 的 Clang 字节位置仅在比较摘要中归一化，原始访问、points-to 和全局/static symbol_id 不被改写；实际函数编辑仍由完整 token 摘要独立检出。

带类型工作队列求不动点：修改函数传播到全部调用者（返回/控制副作用）与被调用者（参数/执行副作用）；受影响写者经共享存储传播到读者；存储修改传播到读者；无法证明不重叠的存储扩大范围，已知不重叠字段保持精度。递归去重，不用固定深度、变量数量或任务数截断。未解析边界、全局入口/保护/NVIC/DMA/别名变化、重要头文件和构建变化保守扩大到完整构建集合，记录 L1 与原因。

这是保守函数级数据/控制闭包，不是精确表达式切片。公共函数可能将连通调用区域全部纳入；纳入不等于新增风险。原全量分析中的 UNKNOWN 不会因影响扩大而变成 SAFE。

比较完整调用边和上下文边，不以最短路径代替图。每条变化边生成最短代表证据供展示，不枚举递归的全部路径。未变化计数明确标为“边数”，不冒称全部路径数量。

风险变化与影响原因独立：新增疑似风险、已有风险受修改影响、风险证据变化、风险可能消除、无法判断。SUSPECT→SUSPECT 仍比较具体冲突和访问证据。

## index.html 与后台完整证据

只使用 `.ecra/index.html`，保留 CSS、栏目、筛选、搜索、分页、延迟详情与分类交互。顶部增加分支/SHA、比较方式、变更文件/函数、影响变量及其分类。主要表只列影响集合；旧对象删除证据另列，不计当前风险。空集合明确说明没有识别到本次差异变量，不表示整个工程安全。

详情先显示影响原因、风险变化和基准/当前变化路径代表证据；完整当前访问、未修改路径及其他证据放在默认收起的详情。facts 和 Packet 不应用展示层裁剪。分类质量统计保留完整构建范围，变量链接仅指向当前差异范围的有效锚点。

## 缓存、输入校验和回退

TU 缓存绑定源码/有效头文件内容、最新 Clang 预处理签名、实际命令及响应文件展开、编译器、libclang、环境、语义配置、引擎与 Schema。每次先重新发现依赖，搜索路径中新增的头文件、生成头文件和负向包含探测不会靠旧依赖列表误命中。

缓存保存原始 Worker 响应和校验元数据，只接受 PARSED、快照完整且匹配当前 sealed snapshot 的响应。损坏/缺失重新提取；继续执行原始最终发现、发布前后快照及源码读取校验。Worker、内存、比较或输入失败沿用失败归档并阻止有效发布，不截断证据。

禁用缓存不关闭任何安全检查。L0 表示有效缓存/完整比较；L1 表示有说明的保守扩大；L2 是缓存失效后的重新提取及完整全局分析；L3 是 Git、基准、输入、Worker 或对照失败。全量回退不能消除分析器原有盲区。

`verify_against_full` 独立重新提取全部 TU，完整分析后比较规范化证据、图、分类、冲突、覆盖和安全证明。不一致阻止发布并保存诊断。目前该对照要求 `build_closure_only: true`；补充分支模式启用该选项会明确失败。对照额外消耗时间与内存。

## OpenCode、恢复和归档

`review_targets` 只为选中的疑似/未知变量生成普通任务，独立全局覆盖缺口仍保留；安全抽样也受本轮范围约束。一变量一条原有聚合任务。Packet 保留完整当前访问、真实上游/调用边、保护/上下文和未解析证据，另附 impact、基准事实路径/SHA、代码 patch 路径。模型结果不修改静态事实。

检查点保存模式和 Git 比较身份，扫描指纹绑定整个差异比较。`review`/`review-failed` 不重新筛选范围。引用、输入、差异集合、基准事实或 patch 变化使旧复核失效。基准源码受污染会被拒绝。

## Portable 和磁盘生命周期

原全量模式不增加 Git 依赖。离线打包可传 `build_portable.ps1 -GitSource <MinGit目录>`，复制完整运行时/许可证，记录实际版本并沿用交付文件哈希。差异扫描和 doctor 先检查包内 `tools/git/cmd/git.exe`；缺失会中文报错，不回落开发机 Git，也不静默跳过。

worktree、基准原始证据、缓存、patch 暂不自动回收，防止删除仍被报告/复核引用的数据。释放空间前应归档整个输出目录及其引用。移动 Portable 后须重新扫描，历史绝对路径检查点不能作为当前有效输入。

正式打包保留完整 Git 核心及许可证，移除独立可选的 GCM/.NET/Avalonia 认证与界面组件，逐文件记录 SHA-256 和原因；同时去掉对该组件及其他 Git 安装目录的系统配置引用。未把 .NET 运行时当成 Windows 必有组件。PE 校验增加 Git 包内的原生 DLL 搜索目录；`BCryptPrimitives.dll` 按 [Microsoft ProcessPrng 契约](https://learn.microsoft.com/en-us/windows/win32/seccng/processprng) 识别为 Windows 8 起已有的操作系统组件，仍必须实际存在于相应系统目录。其他缺失依赖继续失败，没有通配放行。

## 回归和规模验证方法

新增 `tests/test_git_diff.py` 使用真实 Clang、临时 Git 和原报告/恢复流程，覆盖 T01–T31、T33、T35–T36 的相关场景；T34 由完整既有测试回归，T32 由规模夹具和原图/内存回归补充。组合编号不表示所有硬件机制已穷尽验证。

```powershell
py -3.10 -m unittest tests.test_git_diff -q
py -3.10 -m unittest discover -s tests -q
py -3.10 scripts/validate_git_diff_stm32.py --work <不存在的新目录> --vendor <INAV/lib/main> --compiler <ARM-GCC/bin/arm-none-eabi-gcc.exe>
```

规模脚本生成 129 TU Cortex-M7 工程，使用本机已有 STM32H743/CMSIS 头文件，以 ARM GCC、CMake、Ninja 实际构建 ELF。含跨文件多层调用、全局/文件与函数 static、结构体字段、指针参数、函数指针、多 IRQ、DMA 寄存器、NVIC 与临界区。依次执行基准全量、首次差异、缓存差异、当前全量、头文件差异和 NVIC 差异，保存逐轮日志、完整语义摘要、进程树 RSS 峰值和 JSON 收据。

规模监测脚本需要测试用可选依赖 `psutil`（可执行 `py -3.10 -m pip install psutil`），不增加扫描器运行时依赖。实测供应商头文件来自本机 INAV 提交 `ed7fb3bb3216f8215150b42b52cb7b724e1dfae8` 的 `lib/main`，具体消费内容仍以各轮 InputSnapshot 为准。

该夹具是规模集成验证，**不是生产固件或硬件时序验证**。没有执行收据的测试不能视为通过；静态 INCOMPLETE/UNKNOWN 和未启用模型复核不伪装为风险已清零。最终实际结果另记于本文末尾。

### 浏览器与证据包实测

在 `H:/ecra_stm32_validation/git-diff-ui-final` 建立真实 Git 双提交的 ECAT/TIM4 案例。底层清单共 3 行，差异选中且主表仅显示 `g_mfcInterface.msgSp` 1 行；无保守全量扩大。当前版独立无缓存全量校验 `PASSED`，分类/语义不一致均为 0。

Playwright 实际打开原 index 页面，展开变量详情后显示 `ECAT_IRQHandler → Old → INF_SetPointFP` 的删除代表证据及 `ECAT_IRQHandler → INF_SetPointFP` 的新增代表证据。完整证据默认收起时，浏览器可见正文不含 TIM4 路径；展开后可见 TIM4 的 RMW。实际 `review/*.input.json` 同时包含 TIM4 与 ECAT。主表 DOM 行数为 1，搜索 unrelated 为 0 行；浏览器错误/警告均为 0。截图位于仓库本地 `output/playwright/git-diff-details.png`，页面快照保留于 `.playwright-cli/`。文件协议受浏览器测试工具限制，验证通过绑定 127.0.0.1 的只读 HTTP 服务完成；交付仍是原本地 HTML。

### 开发过程中的失败记录

直接执行未限定目录的 `pytest -q` 收集了仓库外部验证夹具，并因这些工程的导入路径而收集失败；不能算测试通过。随后使用 README 规定的 `unittest discover -s tests`。首轮 884 项中 1 失败、1 错误、2 跳过，发生于开发期间引擎变化窗口；两个失败项独立重跑通过，仍需以冻结引擎后的整轮记录作为最终验收。

规模脚本初版链接脚本语法错误已修正；重复包含 CMSIS 的旧夹具被主动停止。开发中的旧夹具因源码变化被停止或被一致性门禁拒绝，均不计入最终成功轮次，也不冒称 OOM。v6/v7 的完成记录属于相应旧引擎，不冒充最终版本。最终规模记录使用 v8。`git_diff_tests_delivery.log` 曾记录 32 项通过、151.999 秒；后续又补充局部指针注释、宏、长初始化器和恢复范围测试，以本文最终记录为准。

Portable 首次实验使用完整桌面 Git，交付 PE 校验检出了可选凭据组件依赖 mscoree.dll，明确失败。正式实验改用官方 [MinGit 2.56.0.3](https://github.com/git-for-windows/git/releases/tag/v2.56.0.windows.3)，下载包 SHA-256 为 `2e5619966e588fde5f8122c5557cad50c0fbafcaed736689f40ec1dfb1d78ea7`，与发布页一致。准备期可下载运行时，最终打包命令只读取本地资产；没有降低 DLL 完整性校验。

## 已知限制及优化方向

改名不猜测性合并；返回/控制依赖采用保守函数级闭包。重要头文件、全局语义或未知边界可使影响范围扩大到完整构建。旧版构建依赖缺失时明确失败。双版本全局分析与独立全量对照成本显著，TU 缓存不能加速全部阶段。硬件真实优先级/时序、DMA 副作用及原分析器未建模行为仍须按 UNKNOWN 和限制核对。后续可优化依赖切片、共享摘要存储和有引用计数的磁盘回收，但不得降低完整性门禁。

## 最终冻结版本执行记录

静态引擎摘要：`85a25f66304d886f1820dea2f97d4320c0b72622d73aa5a087d2eeaed72b0568`。完整机器记录见 [git-diff-concurrency-validation-results.json](git-diff-concurrency-validation-results.json)。分支仍为 `optimize_ccc`，工作区改动未提交；不能把起点提交 SHA 当成本次实现的已提交版本。

* `py -3.10 -m unittest discover -s tests -q`：896 项执行，0 失败、0 错误、2 跳过，1228.920 秒。跳过项为两项须显式启用的实时 OpenCode 测试，不冒充已连接真实模型。
* 修改 Portable 运行时查找后，`PYTHONPATH=tests` 下执行 `py -3.10 -m unittest test_portable_build test_portability -q`：44 项通过，29.961 秒。
* 新增差异专项共 37 个测试方法；其中 36 项包含在上述整轮回归，后续补充了复核补丁读取权限测试。最终差异、HTML、复核归档及合同专项合计 69 项通过，111.658 秒；额外权限/合同组 27 项通过，20.929 秒，包内 Python 运行权限专项 1 项通过，10.563 秒。这些重复执行不叠加宣称为不同的测试总数。
* `git diff --check`、Python 编译检查和 PowerShell 语法检查通过。

### 129 TU STM32H743 集成夹具

最终目录 `H:/ecra_stm32_validation/git-diff-h743-129tu-v8`，七轮 complete=true，实际 ARM GCC 10.3、CMake/Ninja ELF 构建。完整盘点 653 行，其中 130 行是容器汇总，实际分析对象 523；当前静态分类为 SAFE_PROVEN 394、SUSPECT 128、UNKNOWN 1，复核候选 129。未解析依赖触发有记录的 L1 保守扩大，差异清单包含全部 653 行，**不能以此声称在该夹具上精确缩小了范围**。精确排除无关变量的独立 ECAT/TIM4 案例选中 1 行。

| 轮次 | 总耗时（秒） | 当前 TU 重提取 / 命中 | 进程树 RSS 峰值（MiB） |
|---|---:|---:|---:|
| 基准全量 | 80.453 | 129 / 0（未用缓存） | 412.8 |
| 首次差异（含独立基准） | 257.563 | 129 / 0 | 452.2 |
| 热缓存差异 | 115.797 | 0 / 129 | 366.5 |
| 当前版全量 | 82.156 | 129 / 0（未用缓存） | 442.0 |
| 头文件变更差异 | 123.641 | 129 / 0 | 443.6 |
| NVIC 变更差异 | 117.312 | 1 / 128 | 369.3 |
| 独立无缓存全量对照 | 222.750 | 129 / 0，另做 129 TU 对照 | 463.1 |

首次差异还独立建立了 129 TU 基准事实；表中提取数为当前版主事实流，对照提取单列。热缓存命中率 100%，NVIC 修改后命中率 99.22%，公共头文件修改后全部失效。每阶段耗时和输入验证、回退原因保留在机器记录的 `stage_timings` 与 `fallback` 中。五轮差异均有说明地扩大范围，最终七轮没有 L3 发布失败或 MemoryError；开发期间被停止/失败的旧轮次没有混入。

该共享主机实测中，热差异仍慢于单版全量，**总耗时优化目标尚未在该夹具上达到**。已实现的是原始 TU 提取复用，而基准闭包重放、完整全局分析及输出成本仍然存在。主机同时执行其他验证，不能将这些耗时用于承诺固定提速比例。

独立全量对照重新提取全部 129 TU：分类不一致 0、规范化语义事实不一致 0。头文件及 NVIC 变更都重新执行完整全局分析；UNKNOWN 保留，没有转成安全放行。退出码 2 对应该夹具的风险待复核/覆盖不足，不表示输入验证失败。所有轮次输入快照 VERIFIED；没有把完整性未知标成完整安全证明。

### Windows Full Portable

实际命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build_portable.ps1 `
  -OutputDir H:/ecra_stm32_validation/portable-git-diff-final `
  -GitSource H:/global_static_concurrency_design/.tools-cache/git-diff-runtime/MinGit-2.56.0.3 `
  -SkipZip
```

目录包隔离验收通过，419 个 PE 文件的依赖闭包通过，未生成/验收 ZIP。用包内 Python 3.10.9、MinGit、libclang 和 ARM 工具，在 `portable-evidence/分支差异 中文 空格` 真实执行两次差异扫描：3 行完整清单、仅 1 个目标字段展示，队列 1 条，重复扫描命中 1/1 TU；独立全量对照 PASSED，分类/语义不一致均 0。Packet 同时含 TIM4/ECAT，无 diff_index.html。退出码 2 是静态风险等待复核；输入有效性为 true/VERIFIED。实际离线运行不依赖桌面 Git/GCM。

最终页面又在浏览器打开并截图 `output/playwright/git-diff-final.png`，控制台 0 错误、0 警告。报告明确区分分析对象数与含容器的清单行数。

补丁和基准事实通过每个 Packet 的精确路径加入 OpenCode 只读白名单；没有开放通用 `.patch` 或执行权限。差异提示明确要求读取变化证据并结合全部未修改路径；格式/语言/摘要修复阶段仍不允许读取源码。更新最终复核/报告模块后，目录包重新生成完整文件哈希并完成 `final-all-changes` 隔离验收，记录见机器结果。

### 真实 SmartFarm 固件全量回归

从本机 `H:/stm32_RAG/code/SmartFarm` 的实际源码建立独立副本 `H:/ecra_stm32_validation/git-diff-smartfarm-62tu`，没有改动原工程。复制实际 Core、Drivers、FreeRTOS Middlewares、CMake/链接和启动文件，在副本创建 Git 基准并使用其原有 STM32F103/FreeRTOS 构建配置。该项目不是大型 H7，**本轮只验证其完整全量流程**，不冒充真实生产 H7 的双版本或缓存性能验收。

最终命令等价于：

```powershell
py -3.10 run_ecra.py --project H:/ecra_stm32_validation/git-diff-smartfarm-62tu `
  --config H:/ecra_stm32_validation/git-diff-smartfarm-62tu-semantics.yaml `
  --scan-mode full --no-review
```

真实构建成功，61 个 C TU 全部提取并分析，另有汇编输入；完整调用分析含 3935 个函数，盘点 327 行。277 个实际归账对象中，SAFE_PROVEN 168、SUSPECT 106、UNKNOWN 3，复核候选 109；容器汇总另列，不重复统计。最终归账 missing=0、duplicate_ids=0。耗时 2103.937 秒，进程树 RSS 采样峰值 4081975296 B（约 3.80 GiB），Windows 主进程峰值工作集 4103630848 B、峰值提交 4182204416 B。输入 VERIFIED，analysis_valid=true，没有 MemoryError。

跨 TU 指针阶段 430.172 秒，执行上下文指针/调用图阶段 1348.969 秒，是实测主要瓶颈；单纯减少 AST 提取无法解决这一成本。静态结果仍 INCOMPLETE，并保留 3 个 UNKNOWN 和待复核项，退出 2，不解释为安全放行。先前因实现继续变化而主动停止的两次副本运行有独立 operator-stop 收据，未计入本次成功记录。

生产级大型 STM32H7 工程的完整差异矩阵、实际模型服务复核，以及 ZIP 分发验收仍未覆盖。本次可交付范围为上述实现、自动化回归、129 TU H7 集成夹具、真实 F1 全量回归和离线目录包验证。
