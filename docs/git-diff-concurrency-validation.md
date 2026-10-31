# Git 分支差异并发扫描：实现与验收记录

2026-10-31 工作区改造与最终验收见[工作区交付记录](workspace-validation.md)。固定提交扫描还检查输入归属：若绝对 include、编译数据库或 CMake 输入仍指向原固件仓库，而不是所选隔离版本，会明确拒绝发布并列出路径。仓库内引用应使用相对路径或所选版本新生成的数据库，工具链放在仓库外；不通过忽略依赖、缩小 AST 或读取原工作区兜底来消除错误。完整配置与恢复方法见[迁移说明](workspace-migration.md)。

2026-10-30 已修复默认清单被扩大至近乎全量的问题，最新实测见[差异清单收敛验收](git-diff-focused-validation.md)。下方早期执行记录保留当时的全量扩大数量，不代表当前默认展示规则。

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
base_ref: origin/master
current_ref: HEAD
```

引用属于 `project.root` 的固件仓库。默认关闭。`--scan-mode full|diff` 仅改变本次内存配置；恢复沿用检查点模式。配置严格检查类型、允许值和未知键；构建前检查 Git 与引用。

固定 `base_ref` 与 `current_ref` 的 SHA、仓库根、项目子目录，以及文件增删改/重命名。直接比较两个引用的提交内容，不自动计算 merge-base。支持本地分支、远端跟踪分支、标签和提交 SHA，不自动 fetch。路径采用 NUL 分隔，不通过 shell 拼接执行 Git。

`current_ref: HEAD` 默认固定 HEAD SHA，并与基准一起使用独立 detached worktree。原工作区未提交内容不阻断比较，也不纳入结果；终端与 HTML 明确说明这一边界。仅 `include_uncommitted: true` 使用真实工作区，同时绑定暂存、未暂存、未跟踪内容。非 HEAD 引用不能启用该选项。默认结果、工作树、构建及缓存集中到工具侧项目 workspace；不要求修改固件忽略规则。旧数据按归属验证和哈希清单迁移，不按 .ecra/build 目录名排除真实输入。详细兼容、迁移与恢复步骤见[工作区说明](workspace-migration.md)。发布前后和恢复时继续验证引用、隔离源码及实际编译输入，不执行用户工作区 checkout/reset/clean。

### 参数取舍与迁移

日常配置从八个字段缩减为三个。这里的精简针对 `analysis.git_diff`，其它分析、构建和复核配置不变。

| 参数 | 是否需要用户配置 | 处理与理由 |
|---|---|---|
| `enabled` | 日常展示，默认 false | 决定一键运行采用全量还是差异扫描；命令行 `--scan-mode` 可临时覆盖。仅用命令行切换时也可以省略。 |
| `base_ref` | 比较基准，默认 origin/master | 指定变化之前的版本，是比较方向的一部分。应按实际仓库填写。 |
| `current_ref` | 待检查版本，默认 HEAD | 指定变化之后的版本；可填写任意分支，无需手动 checkout。 |
| 原 `compare_mode` | 删除 | 当前固定直接比较两个版本，与“任意两个分支比较”一致，避免用户再选择比较语义。 |
| `include_uncommitted` | 可选，默认 false | 是否把本地开发修改加入 HEAD 扫描是用户意图，不能自动猜测；仅在需要时添加。 |
| `cache_enabled` | 高级可选，默认 true | 有效性由内容、构建、引擎和输入闭包校验决定，用户无需管理；故障定位或性能验收可设 false，不影响完整性检查。 |
| `verify_against_full` | 高级可选，默认 false | 独立重新提取全量事实并核对结果，额外耗时、占用内存；用于引擎升级验收与排查，不是日常扫描前提，也不关闭已有完整性检查。 |
| 原 `uncertain_impact_policy` | 删除 | 不忽略未知影响：保留完整后台分析，并在覆盖说明记录未排除的潜在影响；不再将这些变量自动填入默认差异清单。 |

两个可选高级字段继续受严格类型检查，但不再出现在日常 YAML 中。默认缓存复用失败时重新提取，不需要用户手动更改参数。

旧配置会给出迁移错误，不会悄悄改变扫描范围：原 `target_ref` 改成 `base_ref`，添加 `current_ref: HEAD`，删除 `compare_mode` 与 `uncertain_impact_policy`。原 `direct` 行为保持。原 `merge_base` 若要保留同样的比较基准，先在固件仓库执行 `git merge-base <原target_ref> <current_ref>`，将输出 SHA 填入 `base_ref`；改为分支名直接比较意味着采用新语义。

例如任意双分支比较：

```yaml
analysis:
  git_diff:
    enabled: true
    base_ref: release/v1
    current_ref: feature/control
```

### 2026-10-29 双分支配置精简验证

`py -3.10 -m unittest tests.test_git_diff tests.test_git_diff_patch tests.test_relative_worktree_gitdir tests.test_benchmark_project_scan -q`：57 项全部通过，205.763 秒，日志 `output/two-branch-targeted-tests.log`。

`py -3.10 -m unittest discover -s tests -q`：1015 项，1013 通过、2 项真实模型测试默认跳过、0 失败/错误，773.747 秒，日志 `output/two-branch-full-tests.log`。专项包含于全套，不累加为独立测试数。Python 编译检查和 `git diff --check` 通过。全套日志保留一条 subprocess ResourceWarning；对应 PID 25768 已核对退出。

新增场景覆盖：未检出目标分支且原工作区有未提交修改、分叉但内容相同的提交、分支指向变化、隔离当前源码污染、中文工程子目录、标签引用和 CLI 临时模式的保存恢复。真实 ARM GCC + CMake/Ninja 场景分别构建两个隔离版本，在原输出目录发布报告并通过独立全量事实对照；原检出版本没有 CMake 工程也不会被误用为当前分支。未运行实际模型复核或目标板验证。

## 双版本事实和变量匹配

基准在输出目录 `<project_workspace>/trees/base-<SHA前16位>` 的 detached worktree 使用相同引擎独立扫描。CMake 使用旧源码重新配置/构建，不复制 HEAD 构建产物。非 CMake 工程须有基准提交内可重定位的真实编译数据库；缺失则明确失败。版本内数据库只重定位项目根路径，外部工具/头文件继续受原快照约束。

基准完整检查点有效时复用，失败则重新扫描。基准部分解析/失败不能当作无变化。worktree、原始事实及 SHA 保留供审计。两版顺序执行，基准完整 facts 释放后，仅把规范化变量摘要交给当前分析。

变量按语义身份匹配，Git 重命名映射修复 TU 与文件 static USR。不同 TU 和函数 static 不按名字合并。无法可靠确认变量/函数改名时，保留旧对象删除证据和新对象的 `MATCH_UNCERTAIN`，不宣称已修复或新增风险。现有 symbol_id 不改写。

## 语义传播与完整图比较

提取器新增完整函数/变量 token 摘要，排除注释，不按行号认定修改。变量证据比较声明、访问、上下文、完整图、保护、冲突、安全证明、覆盖及分类，所有原因按存储对象聚合。

变量完整定义会覆盖先前 extern 声明的摘要，初始化器超出原展示字段 500 字符的部分仍参与比较。TU 元数据保存活动宏定义的完整摘要；函数另保存实际消费宏及其传递定义、命令行宏、有效预定义宏值的摘要。宏变化按真实消费者关联变量，未使用的公共头文件定义不会改变所有函数。自动局部指针 slot 的 Clang 字节位置仅在比较摘要中归一化，原始访问、points-to 和全局/static symbol_id 不被改写；实际函数编辑仍由完整 token 摘要独立检出。

带方向的类型工作队列求不动点：修改函数向被调用者传播参数/执行影响；只有返回值被实际消费时，才向调用者传播返回/控制影响。到达一个未修改的 callee，不会再反向走入它的全部调用者及其无关分支。受影响写者经共享存储传播到读者；存储修改传播到读者；无法证明不重叠的存储仍按已恢复的重叠关系关联，已知不重叠字段保持精度。递归去重，不用固定深度、变量数量或任务数截断。

未解析边界、全局语义或构建变化仍记录 L1 与原因，但不再把全量变量自动加入 `selected_symbol_ids`。只有未排除潜在影响的变量记录在 `conservative_symbol_ids`，集中显示于覆盖说明。完整后台 findings、事实和静态归账不删除；它们不自动成为默认差异变量或本轮复核对象。有未排除影响时仍返回尚不能确定，不能据空差异清单宣称无影响或安全。

当前依赖分析仍采用函数和已恢复存储关系的粒度，不是逐语句最小切片。因此一个变更函数内的安全访问也可能进入差异清单；这些条目必须有源码或依赖依据，不能仅因共享 `main` 或存在全局缺口而入选。原全量分析中的 UNKNOWN 不会变成 SAFE。

比较完整调用边和上下文边，不以最短路径代替图。每条变化边生成最短代表证据供展示，不枚举递归的全部路径。未变化计数明确标为“边数”，不冒称全部路径数量。

风险变化与影响原因独立：新增疑似风险、已有风险受修改影响、风险证据变化、风险可能消除、无法判断。SUSPECT→SUSPECT 仍比较具体冲突和访问证据。

## index.html 与后台完整证据

只使用项目 `results/index.html`，保留 CSS、栏目、筛选、搜索、分页、延迟详情与分类交互。顶部增加分支/SHA、比较方式、变更文件/函数、影响变量及其分类。主要表只列影响集合；旧对象删除证据另列，不计当前风险。空集合明确说明没有识别到本次差异变量，不表示整个工程安全。

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

## 2026-10-26 后续优化

在用户提交 `a1ea2076` 后继续开发，新增精确数组重叠候选索引、内容绑定的基准规范化摘要缓存及前驱式调用路径见证。修复压缩指针集合因 atom 编号/编码格式而产生的伪语义差异；摘要消费哈希也加入发布与恢复校验。原有全局求解调度、完整事实、静态分类和 index.html 框架保留。

本轮关闭实际 OpenCode 复核，重新执行真实 SmartFarm、ST 官方 CDC 应用的隔离副本及 129 TU H7 集成验证。试验中无性能收益的表达式缓存已经撤回，不计入最终实现。各轮引擎身份、实际命令、故障/撤回记录、测试和性能结果见 [后续实测记录](real-project-optimization-validation.md)；本节以上为上一轮历史记录，不能代替新引擎的有效性检查。

## 大型生产固件验证补充

真实 INAV STM32H743 工程使用 388 个 C 单元及 2 个汇编单元，完整接入多目标构建图。新增目标闭包校验及完整调用子图共享索引，继续保留完整当前证据、静态分类和原 index.html。该轮实际结果、问题修正和验收边界集中在 [INAV H743 实测报告](inav-h743-git-diff-validation.md)；历史小型工程或生成夹具的通过不等于本工程通过。

2026-10-27 的原生全量轮次已经发布快照验证通过的结果，但 4.11 小时、约 54.98 GiB 进程树 RSS、66.2 GB facts.json 暴露了新的大型持久化瓶颈，尚未通过大型差异矩阵。新增共享存储、初始化索引和不可变产物归档优化正在用新的冻结引擎复测。共享存储只改变表示，完整值与类型、访问、来源、图和证明均保留；读取 API 与 SQLite 还原方法见[设计说明](concurrency-tool-design.md#完整大型证据的无损存储)。不把原生静态 INCOMPLETE、主动停止的后处理或受控 IR 回放记作完整差异验收通过。

## 2026-10-28 当前冻结版本门禁

本节记录上一冻结版本的门禁；旧版本的“最终”记录只对当时引擎有效。该引擎摘要为 `47308f60467ce5b4134778e4fe43314dd5f8140dc90bf9ed53ec290616672aa2`，工具分支仍为 `optimize_ccc`，起点提交 `3496939a984062f6557f90294b1e9e41ab9370c5`，本轮修改尚未提交。所有实际扫描均关闭 OpenCode；两项实时模型测试明确跳过。后续审查复现未跟踪文件的补丁遗漏，修复后的 `2ce940a3…` 正在重新执行门禁，下表不冒充其验收结果。

| 要求 | 已获得的证据 | 当前边界 |
|---|---|---|
| 全量行为、完整归账、差异集合分离 | `py -3.10 -B -m unittest discover -s tests -q`：987 项执行，985 通过、2 跳过，0 失败，694.087 秒 | 不用单元测试代替大型原生矩阵 |
| 完整事实、分类和未变化路径保留 | 包内真实 ARM 差异案例及独立全量对照通过，分类与规范化语义差异均为 0 | 案例为小型工程；大型 UART 场景另设门禁 |
| 只用原 index.html，保持搜索、分页和详情 | 大型已保存报告的浏览器自动门禁通过；20,106 行索引、UART 唯一检索、25/100 行分页、筛选、懒加载及 main/IRQ 图均核对 | 属于展示层重放；不是原生分析通过，也不是 file:// 协议验证 |
| 大型输出不丢值、不改类型 | 生产编码的完整数据库校验通过：132,225,391 个单元格、20,085,639 个嵌套 JSON 值 | 来源为完整受控回放语料，不能替代最新原生扫描 |
| Portable 离线环境 | 当前引擎目录包 22 项、ZIP 解压包 22 项隔离验收通过；中文空格路径、真实响应文件扫描和热缓存通过 | 实际包内 Python 为显式指定的 3.10.9；未运行模型 |
| 动态时间宏的缓存有效性 | 新增四组回归及实际 INAV version.c 提取通过；只允许已证明不消费字符串值的不可变元数据，保留 STRING_CONTENT_UNKNOWN | 参与逻辑、布局或派生常量的时间宏会明确失败，不能宣称已支持这些语义 |
| 大型工程增量/全量等价、性能和回退 | 388 C TU、2 汇编输入的实际 MATEKH743.elf 九轮矩阵 v18 已主动停止并保留收据；发现未跟踪文件补丁遗漏后先修复 | 未通过，需重新冻结；不得提前声称全部符合或获得大型提速 |

完整回归日志为 `.tools-cache/inav-dynamic-987-regression.log`。Portable ZIP SHA-256 为 `1635df95e898fabb6c6f6f452a0c78d6aad55f403c7d48cd7d90e339afd17a72`。小型包内全量、首次差异、热差异分别耗时 4.688、10.500、6.015 秒，热缓存命中 1/1 TU；这些数字不是大型工程性能。

v18 原生矩阵证据目录为 `I:/ecra_stm32_validation/inav-h743-20261028-evidence-v18`，其 `acceptance.json` 保留 `complete=false`，停止于 320/388 TU，未执行后续测试变更。计划的矩阵包含 UART 写回逻辑、公共 UART 头文件和 NVIC 优先级三处工作区变更；HEAD 固定以隔离 INAV `__REVISION__` 宏变化，不能将其描述为多个业务提交的实测。每轮差异还必须同时保留 txBufferTail 的 main 与 IRQ 完整执行入口。原生运行未设置人工内存上限；受控存储实验的 48 GiB 上限不能混入原生峰值统计。

新增补丁写入器保留真实暂存区，将标准差异与所有未跟踪新增文件的 Git no-index 补丁流式归档，并在完整成功后原子发布。中文、空格、前导连字符、空文件和二进制由 Git 表示；仓库子目录仍使用仓库相对位置。读取失败或只有错误输出的返回 1 不能视为差异成功。新增回归同时核对独立副本应用补丁后的文件内容、暂存区不变和失败时旧归档不被覆盖。

生产存储继续使用已经核对完整值的实现。跨产物复用计划的试验虽然缩短了写入阶段，但增大文件并拖慢完整审计，已经明确不采用。详细失败、修复、撤回、浏览器和原生执行记录见 [INAV H743 实测报告](inav-h743-git-diff-validation.md)。

### 当前用户提交的重新绑定

用户已将改动提交为 `db52f3231235336fb39c9e5795a78d30f95b643b`，分支保持 `optimize_ccc`。补丁修复后的 `2ce940a3…` 已通过 991 项完整回归（989 通过、2 项实际模型测试跳过、728.330 秒）及目录/ZIP 各 22 项 Portable 验收。新增文件补丁还在包内 MinGit 2.56.0.windows.3 中实际生成，并在独立副本应用核对，包含中文空格、前导连字符、二进制、空文件与符号链接；索引保持不变。

提交后 108 个文件的原始换行发生变化，逐文件规范化比对确认逻辑内容一致，引擎原始摘要变为 `6e3b665ef28b0b2ef894220629b4ac0029ed3963b5a8ff5d2410fb4e839b21ae`。为保留内容绑定，重新执行该身份的完整回归：991 项执行、989 通过、2 项实际模型测试跳过、0 失败，805.520 秒；目录及 ZIP 解压版 Portable 各 22 项通过。包内 ARM 响应文件小案例的独立全量分类/语义差异均为 0，热轮命中 1/1 TU；不将旧身份的通过直接改名。

v19 启动因过期扫描锁退出，未进入分析。锁内 PID 已被系统搜索进程复用，核对创建时间及 v18 归属后只移除锁，没有操作系统进程。v20 于 2026-10-28 21:31:34 +0800 正常启动，证据目录 `I:/ecra_stm32_validation/inav-h743-20261028-evidence-v20`；当前大型九轮矩阵未完成。包内 Git 新增文件归档的可重复脚本为 `scripts/validate_portable_untracked_patch.py`，已实际核对中文空格、前导连字符、二进制、空文件、符号链接和索引不变，调用方式见 INAV 实测文档。

## 2026-10-29 真实全量结果与继续优化

v20 的独立全量子任务已完成并通过产物审计：388 个 C TU 全部解析，CLI 13,153.203 秒、进程树 RSS 峰值约 27.47 GiB；12,172 个实际存储对象，8,632 个 SAFE_PROVEN、1,318 个 SUSPECT、2,222 个 UNKNOWN，归账遗漏和重复均为 0。输入 VERIFIED、analysis_valid=true；退出 2、静态 INCOMPLETE，没有安全放行或模型执行。JSON/SQLite 数量、引用池、指针不动点、HTML 覆盖和资源审计通过。顶层九轮矩阵仍 complete=false。

采样定位到分类阶段对 491,011 条函数及 1,007,369 条保护窗口的重复遍历。已新增单次分析内的 ProtectionIndex，保留原行、顺序、重复窗口及全部判定。四项专项通过，包含 5,000 组固定种子旧算法对照和完整 Clang 事实/报告对照；995 项完整回归已通过（993 通过、2 项实际模型测试跳过、0 失败，830.369 秒）。新 Portable 目录及 ZIP 解压各 22 项通过，包内实际 ARM 响应文件案例的两轮独立全量分类/语义差异均为 0；不是大型性能结果。

原生九轮 v21 已于 2026-10-29 08:34:31 +0800 启动，增加同基准 `--baseline-reference` 对照，当前尚未完成，不能复用旧引擎的测试身份。v20 原生页面的实际浏览器交互检查通过，没有先迁移页面；完整 main/IRQ 图及证据懒加载均保留。报告生成仍占上一轮 CLI 约 59%，保护索引的局部收益不能当作大型端到端收益。完整数据及限制见 [INAV 实测报告](inav-h743-git-diff-validation.md#2026-10-29-原生全量结果及保护索引优化)。

后续真实 Clang 复现了“标量 SUSPECT → 容器 CONTAINER、成员仍 SUSPECT，却把根对象标为风险可能消除”的问题。当时暂停 v21 父控制器进入下一轮，全量子任务保持 0f3f；先在独立候选副本修复，保留完整开发、失败及后续复查记录，见 INAV 文档对应缺陷记录。

上述修复现已合入，当前引擎为 `45d3ba477c5547c42c8b884689d93a7c123426da3c537be57ef9874e609a55ef`，仍在 optimize_ccc、未提交。新增独立风险可比性状态、Schema 4 新旧变化摘要、按需详情补丁链接修正，以及不依赖忽略目录的公开验收辅助模块。完整冻结源码回归 1010 项：1008 通过、2 个实际模型测试跳过、0 失败（741.574 秒）；20 项定向复查通过；合入前验证 232 个冻结文件以及包内核心模块字节一致。开发中失败的 1000/1007 项轮次均保留，没有改记为通过。

最新逐项结果及尚未通过的边界见[结果 JSON](inav-h743-latest-validation-results.json)，包括完整命令、引擎身份、原生时间/内存、包内独立全量对照及后台矩阵状态。

Portable v7 目录与 ZIP 解压各 22 项通过；真实 ARM 响应文件、中文空格路径的小型差异案例中，只选择 g、保留未修改 TIM4 访问，两轮独立全量对照的分类及语义差异均为 0；新增文件、二进制、空文件、真实符号链接补丁也通过。大型 0f3f 全量 CLI 已结束（12,050.609 秒、进程树 RSS 约 27.48 GiB、388/388 C TU），完整规范化摘要与优化前逐字节一致，15 项产物审计通过，1793.578 秒，静态状态仍为 INCOMPLETE。

一次性补跑辅助脚本在完成审计记录落盘后的最后打印遗漏 peak，造成 v22 启动门禁停止；保留其错误和 FAILED 记录，并核对源代码顺序、完整摘要、归账、指纹和产物审计后单独保存处理收据，没有改写扫描成功状态。公开审计恢复功能的实际回归不受此辅助脚本问题影响。v21 全部原始输出按同盘目录重命名保存，最新 45d3 的 v23 大型差异矩阵已于 2026-10-29 15:28:21 +0800 启动，当前 diff-first，尚未通过整体验收。所有实际扫描关闭 OpenCode。详细日志、失败原因、回退限制与未完成项见 [INAV 实测记录](inav-h743-git-diff-validation.md)。
