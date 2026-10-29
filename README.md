# STM32 全局变量与 static 变量并发排查工具（ECRA）

大型 STM32H743 飞控工程的目标构建、问题修正与实测状态见 [INAV H743 验收记录](docs/inav-h743-git-diff-validation.md)。多目标 CMake 工程可配置可选的 `analysis.cmake.target`，由 Ninja 实际依赖图选择完整固件闭包。

大型事实与报告使用自包含的无损共享存储，Python 可通过 `ecra.workflow.read_saved_json(path)` 还原完整原结构；小结果保持原 JSON 格式。编码、SQLite 单元还原和完整性规则见[设计说明](docs/concurrency-tool-design.md#完整大型证据的无损存储)。页面继续使用 `.ecra/index.html`，完整图和长源码搜索按需加载。

新增可选 [Git 分支差异扫描](docs/git-diff-concurrency-validation.md)：在同一 `config/semantics.yaml` 配置 `analysis.git_diff`，比较 `project.root` 固件仓库，使用 `py -3.10 run_ecra.py --scan-mode diff`。仍在原 `.ecra/index.html` 展示受影响变量，完整后台并发证据和静态归账保留。默认 `enabled: false`；`--scan-mode full` 临时恢复全量。旧版事实无法可靠建立会明确失败，未知影响会说明保守扩大范围。

变量详情对照基准与当前版本的访问类型、布局、执行上下文、保护屏蔽观测、调用子图及覆盖变化，并链接代码差异。未变化的完整证据默认收起，继续参与并发分析。标量与结构体/数组容器转换时保留匹配不确定性，不能把根对象的容器汇总类别当作“风险新增”或“风险消除”的依据。

缓存还会核对预定义宏的语义影响。`__DATE__`、`__TIME__`、`__TIMESTAMP__` 仅在已证明不消费字符串值的不可变构建元数据场景中允许复用，字符串内容仍记录为未知；参与运行逻辑、存储布局或同 TU 派生常量时明确停止提取。这类用途目前不支持，可由工程提供纳入快照的确定生成输入后重扫；真实预处理构建输入导入仍待实现。不能关闭检查后宣称结果完整。

真实工程的后续性能优化、无复核实测及完整事实对照见 [2026-10-26 优化记录](docs/real-project-optimization-validation.md)。可用 `scripts/benchmark_project_scan.py` 对自己的工程记录全量/差异耗时、内存和语义一致性；该脚本要求关闭自动复核与证据包。

大型 INAV STM32H743（388 C 翻译单元）的实际结果与未完成项见 [大型工程验收记录](docs/inav-h743-git-diff-validation.md)。测量脚本支持 `--audit-saved` 严格恢复同一已保存扫描的未完成审计，保留原始 CLI 测量；输入或引擎变化会拒绝恢复。已有原生全量结果不等于大型差异矩阵通过。

先盘点变量，再追踪“谁在什么任务/中断里读写”，生成本地报告；可选启用 OpenCode 逐项复核。用户不需要手工填写变量列表，默认无需模型账户。源码不会被工具修改。

第一次使用请看 [详细操作教程：简单配置后，一条命令完成并发排查](docs/one-command-tutorial.md)。以 `serial - continue` 裸机工程为例，包含多个排查/排除目录、自动 CMake 构建、报告阅读与故障处理。工具整体架构、风险判定与 STM32 分层中断/回调适配见[设计文档](docs/concurrency-tool-design.md)。详细源码排查另见 [变量案例](docs/variable-investigation-guide.md)。

适用于 CMake STM32 裸机工程（自动生成真实 `compile_commands.json`），也兼容已有编译数据库的工程，也能盘点 C++ 命名空间变量和静态成员；C++ 复杂运行语义会单独标记盲区。第一版采用 Python + libclang，不需要自行构建 C++ 提取器，也不要求虚拟环境。

## Windows Full Portable 离线打包

`build_portable.ps1` **不会联网**。它从项目根目录的 `.tools-cache/` 读取工具和 Python 依赖，生成 `dist/ECRA-Portable/` 与 `dist/ECRA-Portable.zip`。默认版本记录在 `config/portable_sources.psd1`，目前内置 Python 为 **3.12.10（64 位）**、Arm GCC 为 **10.3.1**。若缓存中仍是旧版 Arm GCC，需重新准备缓存，或通过 `-ArmGccSource` 指定本地 10.3.1 完整目录。

### 把源码和已有缓存迁移到新电脑打包

1. 在旧电脑上复制**整个项目源码和完整的 `.tools-cache/` 目录**到新电脑，保持两者相邻。例如：

   ```text
   D:\ECRA\
   ├─ build_portable.ps1
   ├─ prepare_portable_cache.ps1
   ├─ requirements.txt
   ├─ config\portable_sources.psd1
   └─ .tools-cache\
      ├─ python\
      ├─ cmake\
      ├─ ninja\
      ├─ arm-gcc\
      ├─ downloads\
      └─ wheels\
   ```

   `.tools-cache/` 被 `.gitignore` 忽略，单独克隆 Git 仓库不会得到它。必须复制完整目录，不能只复制 `downloads/`：缓存中的某些工具可能只有完整解压目录，没有对应的原始 ZIP。项目可以放在其他盘符；脚本会以自身所在目录定位默认缓存。新电脑需要 64 位 Windows，建议预留约 5–6 GB 空间用于缓存、打包产物和 ZIP 自检时的临时解压。

2. 在新电脑打开 PowerShell，进入项目根目录，离线检查缓存：

   ```powershell
   Set-Location 'D:\ECRA'
   powershell -NoProfile -ExecutionPolicy Bypass -File .\prepare_portable_cache.ps1 -OfflineCheck
   ```

   出现“本地 Portable 缓存已备齐”后继续。`-OfflineCheck` 不下载文件；若提示缺少工具或 wheel，从旧电脑补复制相应缓存，或在可联网的新电脑运行不带 `-OfflineCheck` 的准备脚本。

3. 离线打包并检查产物：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1
   .\dist\ECRA-Portable\runtime\python.exe --version
   .\dist\ECRA-Portable\ecra.cmd --help
   ```

   内置 Python 应显示 `Python 3.12.10`。打包脚本会自检内置 Python、依赖、CMake、Ninja 和 ARM 工具链，还会解压生成的 ZIP 再检查一次。最终交付文件为 `dist\ECRA-Portable.zip`。

**新电脑已安装 Python 3.10 也不影响上述打包。** 准备脚本使用缓存中的嵌入式 Python 检查 wheel；打包脚本使用缓存中的 Python 3.12.10 和对应的依赖 wheel，不调用系统 PATH 中的 Python 3.10。不要因为新电脑的 Python 版本是 3.10 就把 `config/portable_sources.psd1` 改为 3.10；如果确实要改用 3.10 打包，需要同时更换匹配的嵌入式 Python 和依赖 wheel，重新准备缓存并通过自检。

### 新电脑只有源码、没有缓存

先在可联网的新电脑运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\prepare_portable_cache.ps1`，下载 Python、CMake、Ninja、ARM GNU Toolchain、pip wheel 和 `requirements.txt` 的依赖 wheel 到 `.tools-cache/`，再按上面的步骤执行 `-OfflineCheck` 和离线打包。若需要保留四个工具的原始 ZIP，在准备时加 `-ForceArchives`；默认也可复用完整解压缓存。已有其他本地工具目录或 ZIP 时，可向打包脚本传入 `-PythonSource`、`-CMakeSource`、`-NinjaSource`、`-ArmGccSource`，pip wheel 可用 `-PipWheelSource` 指定。

将便携包解压到目标电脑后，按实际固件位置修改包内 `config/semantics.yaml` 的 `project.root` 和相关 CMake 设置。AI review 仍需目标电脑有可用的 OpenCode；只做静态扫描可使用 `--no-review`。

## 完整变量清单与覆盖检查

`index.html` 默认打开“全部全局 / static 变量清单”。常量和未使用变量也保留；全局变量、文件 static、函数 static（含头文件实例和 C++ 静态成员）均可查询。同名 static 按编译单元区分。结构体成员和已知数组元素按独立存储分析；父对象仅汇总，不重复计入分类分母。普通自动局部变量和函数参数用于恢复别名，不作为独立共享对象盘点。

默认 `analysis.build_closure_only: true`，只分析当前固件编译数据库中的 TU；可通过 `analysis.build_closure.linked_sources / linked_objects` 进一步限定实际链接输入。其他板卡、未启用功能和未编入目标的源码不参与并发分类。`include_dirs / exclude_dirs` 限定要排查的变量范围，范围外但实际参与构建的函数仍用于恢复调用与访问。

需要额外查看仓库声明时可设 `build_closure_only: false`。补充声明和关闭分支标记 `OUT_OF_BUILD`，保留在盘点中，不计为 SAFE、不进入当前固件的复核队列。

## OpenCode 前的确定性分类

每个 canonical 变量或成员建立自己的 `VariableEvidenceSlice`。分类按以下顺序执行：

1. 已恢复同一存储的跨物理上下文访问，至少一方修改，可能交错且未证明完整保护：`SUSPECT`。IRQ 优先级或保护细节未恢复时仍保留这个冲突结论。
2. 没有上述冲突，但存在可能隐藏额外冲突的变量相关缺口：`UNKNOWN`。报告列出变量、位置、缺失事实和相关性。
3. 证据足以证明不存在冲突：`SAFE`，必须保存 `safe_reason_code` 和 `safe_evidence`。

覆盖状态 `COMPLETE / PARTIAL` 独立保存，因此 `SUSPECT + PARTIAL` 是有效状态。其他函数的未知调用、未逃逸私有变量之外的失败 TU，不会仅凭“项目不完整”改变本变量的分类。SAFE 不进入 OpenCode；其余变量各提交一次，聚合全部相关访问和冲突。

裸机物理执行域为 `FOREGROUND`、`IRQ:<vector>`、`DMA:<id>`、`EXTERNAL_ASYNC` 和 `UNKNOWN_CONTEXT`。主循环同步调用的任务和 callback 继承执行者；同一 IRQ 不因多条调用路径而与自己并发。参数和自动局部别名按物理上下文传播，全局/static 存储仍保持共享。

安全证明包括无运行访问、只读、单一 foreground、单一 IRQ、已证明不能交错、完整有效保护、严格初始化阶段写入，以及附加的不重叠成员/元素证据。`volatile`、字长、单 writer、出现 Lock/disable API 本身均不是安全证明。初始化证明要求异步源启用顺序的实际证据，不默认 main 入口就是所有 IRQ 尚未启用。

`coverage.blocker_fanout` 记录单个缺口影响的变量和相关性；`analysis.max_unknown_fanout_debug` 控制诊断阈值。UNKNOWN 超过 10% 时输出根因分布用于继续定位，不把比例用作 SAFE 判定条件。完整调用图保存全部入口和边；路径数量过大时报告明确区分图证据和最短见证，避免枚举指数数量的调用链。

“过滤与覆盖校验”逐文件显示变量数量、解析状态和诊断，包括零变量文件。解析错误、无法恢复的类型/宏/条件组合及未编译文件会明确保留覆盖缺口；部分 AST 仍可显示已恢复声明。分支变体不穷举不同文件间所有宏配置组合，因此存在覆盖缺口时不得声称所有声明已完整恢复或已排除全部风险。应修正诊断，必要时分别扫描真实构建变体。

修改提取实现后需要重新运行完整扫描；旧报告不能只刷新后作为新盘点结果。JSON、Markdown、HTML 使用同一变量集合。可复现验收结果见 `output/variable-inventory-fix/verification.md`。


## 裸机 CMake 工程：配置一次，日常一条命令

工具只使用一份 [`config/semantics.yaml`](config/semantics.yaml)。该文件的 `project.root` 指向当前要排查的固件，切换项目时直接修改这一项及该项目的排查/CMake 参数；固件 `.ecra/` 只保存运行产物。在工具根目录执行：

可在 [`config/review_context.md`](config/review_context.md) 填写当前工程补充背景及源码依据。每次正常变量复核读取它，作为待源码核实的用户声明。修改后运行 `review`，会重新复核全部静态疑似/未知变量。使用 `--config` 时，将同名 Markdown 放在实际 semantics.yaml 旁边；切换工程时同步更新。

### 如何维护 OpenCode 深层并发风险案例库

在 [`config/concurrency_cases.md`](config/concurrency_cases.md) 文件末尾按文末模板追加新案例，后续执行 `review` 时会自动生效，无需修改程序、YAML 或手动重建索引。使用 `--config` 或独立配置目录时，编辑实际 `semantics.yaml` 旁的同名文件。

也可以把[案例生成提示词模板](docs/concurrency_case_prompt_template.md)和案例描述、相关代码一起交给 OpenCode，生成符合格式的条目。模板要求保留来源名称和可信状态、不输出链接、区分已确认事实与待核实条件；核对后将生成条目追加到案例库末尾即可。

完整运行、`review`、`review-failed` 都自动读取最新案例库。每轮提供简短案例索引，在复核产物目录保存正文只读快照，让 OpenCode 按行号读取相关案例；大索引自动保存为可分段读取的文件。正文更新也会使正常运行的旧复核缓存失效；`review-failed` 仍只处理技术失败项，要让已完成变量采用新增案例请执行 `review`。缺失字段或异常格式会警告并保留原文阅读路径，不中止复核，也不覆盖用户原文件。

OpenCode 内部遵循八步方法，核查间接访问、真实抢占、跨函数旧值写回、多变量一致性、DMA、外设和完整保护窗口，继续返回现有变量级 JSON。案例相似不能直接确认风险，没有匹配案例也不能证明安全。案例中的代码和命令仅作参考，不会授予执行权限。来源、覆盖缺口及验证记录见[实施报告](docs/opencode_deep_concurrency_review.md)。

### 日常复核

```powershell
py -3.10 run_ecra.py
```

自动刷新 CMake 编译数据库、增量构建、排查自有目录、输出 `.ecra/index.html` 和 `.ecra/opencode_review.html`。新工程默认本地静态排查；当前工程及复核开关以 config/semantics.yaml 为准。只做本地扫描时加 `--no-review`。`analysis.open_report: true` 可自动打开浏览器。

OpenCode 页面顶部直接显示总体结论：有问题、当前覆盖范围内未确认问题、或尚不能确定。确认存在一个变量缺陷即可回答“有问题”，但剩余疑似项、失败项和覆盖盲区仍保留，不能宣称全工程排查完成。`LIKELY` 不算最终定论，下次 `review` 会重新复核。

所有工程使用[简单变量级输出格式](docs/opencode-review-format.md)：`finding_id/status/summary/reason/interleaving/protection/impact/evidence/fix/verification/missing_context`。`summary` 为独立中文一句话结论，`reason` 保留完整分析。一个变量一个最终状态和结论，不要求逐 pair、investigation、参与者或结构化步骤。页面保留中文栏目，按模型原文展示；旧归档仍可读取。

源码证据仅要求 `file/line/claim`；程序核对工程内文件及有效行号，保存邻近源码、完整文件 SHA-256、执行时间、模型、实际提示词、Packet 和原始 stdout/stderr。归档完整性独立于模型输出协议；日志与源码一致不代表模型推理已由硬件实验验证。

`review.workers` 为 1–8（默认 1），控制同时复核的变量数。任何一项结束，空闲会话立即处理下一项，无需等待其他复核结束；三个复核入口均自动处理完全部目标。Packet 保留全部访问、完整调用链、上下文、保护、初始化、别名与未知事实，重复调用链只做无损去重；不再默认附带 1600 行函数正文。OpenCode 按声明、访问点、调用链、入口、保护和 unknowns 导航读取必要源码，避免无关全仓扫描。

只执行一次正常语义复核。输出结构异常时最多两次 `FORMAT_FIX`，只发送原始分析文字、具体错误、简单格式和 finding_id；格式会话无工具权限，不发送 Packet、不重读源码。旧的 `audit_verdicts` 设置不再参与流程，可从项目配置删除。

一句话结论默认启用。在 `config/semantics.yaml` 的 `review` 下配置 `summary: {enabled: true, max_chars: 120, fix_retries: 2}`；缺省使用这些默认值。`max_chars` 为 1–10000 的整数，`fix_retries` 为 0–10 的整数，类型或范围错误会直接报错。长度按 Python `len(str)` 统计 Unicode 码点，包含变量名、空格和标点；它不同于模型 token 数，也不同于组合字形数。程序不通过切片缩短摘要。摘要缺失、超长或出现可检测的残缺/矛盾时，独立调用无工具权限的 `SUMMARY_FIX`，仅允许修改顶层 `summary`，其余字段须完全一致；耗尽次数记 `TECH_FAILED`。关闭 `summary.enabled` 后无需摘要，完整 reason 和证据仍保留。规则只检查可确定的问题，不能证明所有语义都准确；完整配置、日志字段、历史 v2 兼容和根因清单见[摘要修复说明](docs/review-summary.md)。

`timeout_seconds` 是每次 OpenCode 调用的最长时间，`retries` 只用于有限技术重试；格式修正单独限制为两次。真正执行失败或最终格式仍无效记为 `TECH_FAILED`，始终可用 `review-failed` 再试。`--no-review` 覆盖 enabled，保留完整 `PENDING` 队列。所有合法语义状态（包括 `LIKELY` 和 `NEED_MORE_CONTEXT`）均记 `DONE`，证据不足不是执行失败。

默认逐项调用 OpenCode 的对象是候选项；静态判安全的变量留在变量清单。若要让范围内这些变量也逐项调用 OpenCode，完整运行时加入 `--review-safe-sample 9999 --review-shared-sample 9999`；这两个参数会将现有两类静态筛除变量全部加入独立复核队列，具体数量取决于当次扫描结果。

若所有复核项几秒内失败，先查看 `review/*.attempt*.stderr.txt` 并在固件目录运行 `opencode agent list` 检查项目配置。OpenCode 会加载 `.opencode/agent/` 中的 agent 文件；其 YAML 头部的 `model` 只能是单个模型字符串，列表会使整个 OpenCode 命令启动失败。工具发现 `Configuration is invalid at ...` 后会保存该项技术失败，继续处理其余变量；修复配置后运行 `review-failed`（分析实现或扫描输入变化时需重新运行 `run`）。

判定时分开报告存储一致性与业务影响：没有额外业务消费者，不能据此否认 `++` 或位域/union 的非原子读改写会丢失更新；反过来，原子字节 store/store 的最后写者生效，也不能凭空推导出不存在的业务协议被破坏。变量结论绑定自己的 `symbol_id`，指针指向对象的问题不能重复算成指针本身的问题。

新工程先安装依赖，再生成一次**工具侧**配置：

```powershell
py -3.10 -m pip install -r requirements.txt
py -3.10 H:/global_static_concurrency_design/run_ecra.py init --project "D:/MyFirmware"
```

把示例固件路径换成自己的。检测到 `CMakeLists.txt` 时，初始化会创建唯一的 `config/semantics.yaml` CMake 模板；主要编辑 `project.root`、包含/排除目录和 CMake 参数。以后只需执行一条完整排查命令；`doctor`、`review`、`report`、`status` 保留用于分步定位问题。

默认运行/分步命令均从 `project.root` 读取固件目录；`--project <目录>` 可仅用于临时覆盖。已安装工具目录不可写时，可在启动前设置 `$env:ECRA_CONFIG_HOME='D:/ecra-config'`，把唯一的 `semantics.yaml` 放到独立可写位置。跨工程验证及已知边界见[移植验收记录](docs/portability-validation.md)。

初始化默认包含整个工程 `include_dirs: [.]`，排除常见第三方和产物目录，避免只识别 `Core` 导致遗漏 `BSP/User/Modules`。请按实际目录归属检查排除规则；第三方源码中的调用链仍作为依赖分析。CMake 初始化会识别根目录或 `cmake/` 下唯一的 Arm GCC 工具链文件；非标准位置可用 `init --toolchain-file <路径>` 指定。

```yaml
analysis:
  include_dirs: [Core/Src, Core/Inc]  # 多目录取并集，递归包含
  exclude_dirs: [Drivers, Middlewares, ThirdParty]  # 排除优先
  exclude_files: [Core/Src/system_stm32f1xx.c, Core/Src/syscalls.c, Core/Src/sysmem.c]
  cmake:
    build_dir: build/manual
    generator: Ninja
    build_type: Debug
    toolchain_file: cmake/arm-none-eabi.cmake
    args: []
    clean_before_configure: true  # 清理 ECRA 专用目录，然后重新配置/构建
    build: true
  auto_system_includes: true
  output_dir: .ecra
```

目录相对固件根目录，也可使用绝对路径。包含目录必须存在；空包含列表表示不限制范围。根据变量定义文件归属范围；头文件 static 保留不同编译单元的身份，extern 以实际定义归属。排除目录里的变量不进入清单、候选或模型任务。

开启清理时，若 `build/manual` 已存在且没有当前工程的 ECRA 所有权标记，工具会保留原目录，自动使用 `build/manual-ecra`；若同名目录也被占用，则依次选择 `build/manual-ecra-2` 等。后续运行复用该专用目录，`doctor` 也使用同一目录；无需修改固件源码或现有配置。

**第三方文件可能混在业务目录中**：ST 的 `SystemCoreClock` 等变量定义在 `Core/Src/system_stm32f1xx.c`，只排除 `Drivers` 不会排除它们。用 `exclude_files` 列出这些文件，无需移动源码；最终输出会再次校验排除范围。

**依赖仍可被解析**：HAL 调用用户回调、库函数通过指针写用户变量的证据不能因排除第三方自有变量而消失。无关第三方盲区不进入队列；影响目标调用链的缺口和依赖解析失败仍保留并说明原因。旧 `analysis.exclude` 跳过匹配的编译单元，并过滤匹配头文件的变量；需要保留依赖分析时使用 `exclude_dirs` / `exclude_files`。

HTML 首页按变量给出“已确认风险 / 疑似并发风险 / 无法判断 / 已复核安全 / 已排查不存在并发风险”的数量，点击数字即可筛选；每行直接展示风险标签、关键读写和处理动作。最后一类是满足完整证据约束的本地静态筛除，与模型复核安全不同；仅仅未发现静态线索不代表已证明安全。

### 大型项目：完整盘点、明确安全、逐项复核

当前版本对当前构建中的 canonical 存储执行归账检查：**SAFE + SUSPECT + UNKNOWN = 分类变量总数**，且 **SAFE + 去重复核队列 = 分类变量总数**。父容器和 `OUT_OF_BUILD` 声明另计盘点行数。缺少实际定义或存在相关证据缺口的变量保留复核项。每个文件的覆盖记录含 `symbol_ids`，方便核对头文件 static 实例和同名变量。

无相关覆盖缺口、地址逃逸或硬件不确定性时，以下情况明确标记“已排查：不存在并发风险”：只有读取；没有运行期访问；全部访问函数被证明入口不可达；所有读写只属于一个不可重入上下文。不可达判断检查完整调用图（包括递归环）、函数地址、注册入口、函数属性、汇编引用及外部调用；原始访问证据仍保留。一个写入点被多个任务/中断共用，或任务可重入，仍不能据此筛除。

无关库调用、未编译文件不会一概阻塞所有未逃逸 static；可能访问导出全局变量的外部代码、解析失败、DMA 和未恢复入口仍明确保留阻塞原因。指针本体与 DMA 指向缓冲区分开判定。

OpenCode 每项 Packet 包含全部访问和完整调用链，保护、初始化、覆盖缺口与未解析调用继续保留。程序不要求模型逐访问 ID 复述，也不要求逐组合证明。完整静态冲突证据保留在 facts.json/report 中，Packet 只提供上下文导航摘要。单项准备失败会独立归档，不中止后续项。

更新后必须重新运行完整扫描，旧报告不能只刷新：

```powershell
python run_ecra.py --profile <你的项目ID> --no-review
python run_ecra.py review --profile <你的项目ID>
```

大型回归的范围与证据边界见 [大型项目验收说明](docs/large-project-validation.md)。逐项校验保证核对记录不漏项，不能替代对模型推理和真实固件配置的验证。

JSON 的 `risk_summary` 与 HTML、Markdown 共用变量风险分类；`review_summary` 单独统计模型复核进度。具备源码证据的快照候选可展开三步交错示例；打印会保留当前筛选并包含全部匹配分页。过期或失败的旧回答不进入当前结论和修复清单。

两个 HTML 均可离线打开，支持搜索、筛选、分页。变量页顶部展示排查范围；展开变量可查看读写、实际上下文、调用链和保护证据。未启用模型时，第二页仍生成并明确保留待复核状态；不能把静态候选或被排除目录当成安全结论。

## 日常使用：不必每次重扫固件

在固件目录执行以下命令，或加 `--project D:/firmware`：

| 命令 | 作用 |
|---|---|
| `python H:/global_static_concurrency_design/run_ecra.py` | 重新盘点源码并执行完整复核流程 |
| `py -3.10 run_ecra.py review` | 重新复核当前全部静态 SUSPECT/UNKNOWN，包含已有 DONE |
| `py -3.10 run_ecra.py review-failed` | 仅重试 TECH_FAILED，DONE（包括证据不足）不重复调用 |
| `python H:/global_static_concurrency_design/run_ecra.py report` | 校验已有扫描，仅刷新两个 HTML 及配套报告，不调用模型 |
| `python H:/global_static_concurrency_design/run_ecra.py status` | 显示已保存进度、未完成数量、能否恢复及下一步建议；加 `--json` 输出结构化信息 |
| `python H:/global_static_concurrency_design/run_ecra.py doctor` | 检查源码分析环境与 OpenCode 命令可用性，保留上轮运行记录和报告 |

恢复会验证源码、实际包含的外部头文件、嵌套 `@response` 文件、编译数据库、分析配置、分析实现和事实完整性。新增/删除源码、修改芯片宏或损坏事实会要求重新执行 `run`。修改复核设置无需重新解析；显式 review 总是重新复核全部疑似/未知；复核设置可修改，无需重扫静态事实。`review` 命令表示明确启用复核，即使配置中先前写了 `enabled: false`。

旧版本扫描没有 `scan_state.json`，需要先重新运行一次。`Ctrl+C` 中断保留待办；并行复核会取消尚未开始的任务，已运行的会话可能需要等到本次调用完成或超时，单项收据可在恢复时复用。若静态扫描尚未完成，应重跑 `run`。因强制结束进程或断电遗留的 `scan.lock` 仍需先确认进程已经退出，再移除过期锁。

也可以安装命令入口：`python -m pip install .`，然后在固件目录执行 `ecra`。

## 先运行自带示例

```powershell
cd H:/global_static_concurrency_design
python examples/stm32_demo/setup_demo.py
python run_ecra.py --project examples/stm32_demo --no-review
```

示例使用 Cortex-M7 参数解析真实 C 文件，包括同名 static、头文件 static、函数级 static 重入、旧快照写回、宏/普通读改写、DMA buffer 和未知回调。它只生成分析报告，不调用模型。返回码 **2** 是预期结果：示例特意保留了未解决的上下文和指针问题。

## 编译数据库与首次适配

必须保留固件真实的 include 路径、芯片宏、架构、语言标准和条件编译参数。不要拿空编译命令或测试夹具代替实际项目。

- 已有数据库：设置 `analysis.compile_database` 为明确路径。
- CMake 工程：推荐 `analysis.cmake`，每次完整运行都刷新数据库，默认增量构建；`build: false` 仅配置。不会烧录。旧的 `auto_configure_cmake: true` 和 `cmake_*` 字段仍保留“数据库缺失时才配置”的行为，不可与新模式混用。
- STM32CubeIDE、Make、Keil、IAR 工程：先从实际构建流程导出数据库。第一版没有 `.uvprojx`/`.ewp` 自动转换器；不把 IDE 专用选项猜成正确的 Clang 参数。
- 自动查找遇到多个数据库时直接报出路径，要求配置选用哪个，避免选错 Debug/Release/CM4/CM7。
- 支持 `arguments`、`command`、常见 `ccache`/`sccache` 前缀和递归 `@response` 文件。推荐 `arguments` 数组，尤其是带空格的 Windows 路径。响应文件按编译工作目录解释；不执行数据库中的整条编译命令或 shell 字符串。启用 `auto_system_includes` 时，仅向实际 Arm GCC 发出预处理头文件路径探测。
- 自动去除输出文件、依赖生成和 `-c` 等非解析参数；`arm-none-eabi-*` 命令会补充 `--target=arm-none-eabi`。所有原始参数、移除项和推断都保留在事实库。
- GCC 专用参数或工具链头文件无法解析时，使用 `analysis.remove_args` 精确去除不影响语义的选项，使用 `extra_args` 补充所需路径。不要删除影响 ABI、宏和布局的参数来“刷绿”报告。

可先检查环境：

```powershell
python H:/global_static_concurrency_design/run_ecra.py doctor --project D:/firmware
```

`doctor` 通过只表示依赖、数据库及启用复核时的 OpenCode 命令可用，不代表模型提供商已连接或固件已完整解析。启用复核但缺少 OpenCode 命令时返回 2，并给出修正提示；普通 `run` 仍先完成变量盘点。

## 已有编译数据库的兼容配置

```yaml
version: 1
project:
  chip: STM32H747
  core: CM7
  concurrency_model: single_core_preemptive
  native_word_bits: 32
analysis:
  compile_database: build/compile_commands.json
  expected_defines: [STM32H747xx, USE_HAL_DRIVER, CORE_CM7]
  auto_contexts: true
  extra_args: []
  remove_args: []
  include_dirs: [Core/Src, Core/Inc]
  exclude_dirs: [Drivers, Middlewares, ThirdParty]
  exclude_files: []  # 混在业务目录中的第三方文件
  exclude: ['CM4/*', 'build/*']  # 旧选项：仅跳过确定不属于本次固件的编译单元
  output_dir: .ecra
  parse_timeout_seconds: 180
contexts:
  - id: main
    kind: MAIN
    functions: [main]
  - id: control
    kind: TASK
    functions: [ControlTask]
  - id: timer_irq
    kind: ISR
    functions: [TIM4_IRQHandler]
    priority: 1
preemption:
  - higher: timer_irq
    lower: control
concurrency: []
call_edges: []
review:
  enabled: true
  command: [opencode]
  # model: provider/model
  timeout_seconds: 300
  retries: 1
  workers: 1  # 同时复核的变量数；完成一项后立即补入下一项
```

上下文支持 `functions` 精确名称/符号 ID/`文件::函数`、`patterns` 通配符和 `regex` 列表。多个规则匹配同一个函数会保留全部上下文。`priority` 和显式抢占关系作为复核证据，第一版不会仅根据数字或 `preemptive: false` 排除风险。

自动入口包括无参数的 `*IRQHandler`、常见 Cortex-M 异常入口、`main`，以及 FreeRTOS/CMSIS v2 任务、FreeRTOS 定时器和延后回调注册。带 handle 参数的 `HAL_*_IRQHandler` 分发函数沿真实调用图继承上下文，不单独制造 ISR 根。跨函数指针传播可恢复部分注册包装和函数指针目标，重复任务注册保守考虑重入；FreeRTOS 软件定时器和延后函数归入同一个串行 daemon，不因重复注册假定并发重入。显式配置的上下文仍按用户声明保留。无法恢复的动态入口和 CMSIS v1 `osThreadCreate` 仍需配置补充。注册不等价于同步调用任务。

**HAL 回调优先从调用图继承真正的任务/中断上下文。** 无法恢复的回调调用可用 `call_edges: [{caller: TIM4_IRQHandler, callee: HAL_TIM_PeriodElapsedCallback}]` 补充。必须引用唯一的真实函数；这表示你声明了一条运行边，不是 Clang 证明了它。

两个不同任务使用同一个入口函数时，配置两个不同的 TASK id；不要合并为一个不可重入任务。裸机主循环里直接调用的函数不必额外配置为 TASK。

## 输出与状态

| 输出 | 用途 |
|---|---|
| `.ecra/index.html` | HTML 1：全量变量、读写/调用链、独立风险变量表及覆盖盲区 |
| `.ecra/opencode_review.html` | HTML 2：OpenCode 分类结论、源码证据、交错过程、修复与验证 |
| `inventory/global_static_inventory.md/json` | 排查范围内的变量，包括常量、未使用项、头文件实例 |
| `reports/global_static_concurrency.md/json` | 候选规则、证据、覆盖率、增量变化 |
| `reports/unknown_contexts.md` | 未知上下文、间接调用、指针、DMA、解析失败等 |
| `reports/opencode_global_static_review.md` | 逐项复核状态及结论 |
| `reports/opencode_patch_plan.md` | CONFIRMED/LIKELY 项的修复和验证建议 |
| `facts.json` / `facts.db` | 变量、函数、调用、访问、上下文、保护事件和候选 |
| `review/*.input.json` / `*.prompt.txt` | 每项的输入证据与提示词，可独立复核 |
| `review/*.attempt*.jsonl` / `*.result.json` / `queue.json` | 原始模型事件、验证后的结果、队列 |
| `doctor.json` / `run.json` / `run.log` | 环境、运行状态和错误 |
| `input_manifest.json` | 输入文件内容指纹 |
| `scan_state.json` | 可恢复扫描的分析配置、实现和事实校验信息 |
| `resume.json` | 最近一次继续复核/刷新报告的状态 |
| `snapshots/` | 上轮证据与报告归档 |

SQLite 中的列与 JSON 字段同名；数组和对象列使用 JSON 文本。示例：

```sql
SELECT v.name, v.kind, a.file, a.line, a.access_kind, a.contexts
FROM variables v JOIN accesses a ON v.symbol_id = a.symbol_id
ORDER BY v.symbol_id, a.file, a.line;
```

报告区分 `INCOMPLETE`（存在盲区/未完成复核）与 `MODELED_SCOPE_COMPLETE`（当前建模范围的覆盖门槛通过）。后者也不代表固件无竞态。

| 返回码 | 含义 |
|---|---|
| 0 | `init`/`doctor` 成功，或扫描覆盖门槛通过且无候选 |
| 1 | 覆盖和复核流程完成，但仍有候选记录，应查看结论 |
| 2 | 解析/上下文/别名等不完整、复核仍待完成，或 doctor 发现 OpenCode 命令缺失 |
| 3 | 配置、依赖、数据库或运行致命失败 |
| 130 | 用户中断；根据扫描检查点继续 review 或重新 run |

只做静态扫描可加 `--no-review`。有候选时仍返回 2，不把“没有调用模型”显示成复核通过。

## OpenCode 复核与持续使用

每个变量的相关风险合并为一个复核包；无法归属于变量的覆盖盲区仍独立保留，不减少候选。日常完整运行：`py -3.10 run_ecra.py`；全部重评：`py -3.10 run_ecra.py review`；仅技术失败重试：`py -3.10 run_ecra.py review-failed`。后两者使用经一致性检查的静态扫描，不重新运行 Clang。

修改复核提示词、`concurrency_cases.md`、案例库读取逻辑或报告页面后，可直接执行 `review`，无需重扫。固件源码、编译数据库、静态提取/分类实现或分析配置变化时，须先执行 `py -3.10 run_ecra.py --no-review` 刷新静态事实，再执行 `review`。升级前的旧检查点使用全程序指纹，也需要这样刷新一次；旧报告与模型记录会归档到 `.ecra/snapshots/`，不通过替换指纹强行复用旧事实。

`review-failed` 已通过[真实子进程故障注入与真实 OpenCode 恢复测试](docs/review_failed_validation.md)：只重试 TECH_FAILED，成功项退出失败集合，没有失败项时不启动复核进程。

同一文件中的同类盲区合并成复核项，所有具体位置仍保存在原始事实和该项证据中。队列从开始就列出全部项，处理中断也能看到尚未处理的项目。`--no-review` 默认保存两个 HTML、静态报告与完整待办清单，证据包在实际复核时生成；需要提前导出全部包时可设置 `review.prepare_packets: true`。

通过 `opencode run --format json` 获取事件，Parser 兼容纯 JSON、前后解释、fenced JSON 和最后一个匹配 finding_id 的完整对象。最小 Validator 只硬校验 finding_id、五种 status、非空 reason、evidence 列表及源码位置；CONFIRMED/REVIEWED_SAFE/FALSE_POSITIVE 至少一处证据，LIKELY/NEED_MORE_CONTEXT 至少一个明确 missing_context。文字长度及可选展示字段不导致技术失败。

复核使用独立 `ecra-review` 只读 agent 权限，禁止修改文件和执行 shell。实际源码及证据会交给你配置的 OpenCode 提供商处理。工具不会自动登录、选择付费提供商、设置自动分享或修改固件。

正常完整运行可复用当前指纹下的有效 DONE（包括 LIKELY/NEED_MORE_CONTEXT）；显式 `review` 必须重新调用全部当前静态 SUSPECT/UNKNOWN，不受上次 AI 结论影响。`review-failed` 仅重试 TECH_FAILED，成功后自动退出失败集合；没有永久放弃次数。源码、头文件、编译输入、分析实现或事实变化仍要求重新扫描，旧结论移入历史并标记技术失效，不能用于当前安全判断。

每次运行归档上一轮，`baseline.no_longer_observed` 仅表示本次不再观察到，不自动视为已修复。`known_safe` 注释会保留供复核参考，不隐藏候选。意外中止后若遗留 `scan.lock`，确认对应进程已结束再删除锁。归档会持续增长，可按团队保留策略清理 `snapshots`。

## 准确性边界

- 清单针对**配置排查目录内、实际解析到的当前编译配置**；范围外变量不作安全判断。数据库未列出的源文件和未包含的头文件单独报告；被 `#if` 关闭的声明、其他固件/核配置，不能声称已经完整提取。不同构建变体应分别扫描。
- 文件级 static 包含翻译单元身份，因此头文件里每个独立实例不会错误合并。函数级 static 区分函数和同名局部作用域。`extern` 按 Clang USR 合并。
- 展示每个上下文到访问函数的全部已解析无环函数路径，以及各调用点、边来源、递归边和 unresolved_call_edge；最短链仅作为旧 JSON 字段兼容保留。不枚举递归的无限路径。`analysis.max_call_paths: 0` 默认不限制，显式上限超出时扫描失败，不输出截断的安全结论。
- 指针采用不区分控制流的保守目标集合，支持跨 TU 参数/返回、初始化地址、结构成员指针、数组衰减、内存函数包装及部分函数指针。数组下标合并，目标仍可能过近似；未解析目标继续保留盲区。旧快照规则也是候选，未证明真实延迟。
- 数组/结构体字段保留容器和访问路径。撕裂风险按容器大小/对齐保守提示，不代表每一次字段访问都发生撕裂。位域和多字段协议需复核。
- 每个变量都有 `SAFE` / `SUSPECT` / `UNKNOWN` 静态分类，以及 `COMPLETE` / `PARTIAL` 访问覆盖率和具体缺口原因；报告强校验 `TOTAL = SAFE + SUSPECT + UNKNOWN`。只有完整证据才会进入 `SAFE`。
- CMSIS 和配置的临界区先记录直接事实，再由 CFG 数据流检查整个访问窗口。PRIMASK 是一个状态位，不是嵌套计数器；分支汇合、循环、提前返回、保存/恢复值及被调函数都参与分析。只有完整证据才能判 `EFFECTIVE`。BASEPRI 还要求 `project.nvic_priority_bits`、无条件初始化的唯一 NVIC 分组/优先级，以及所有竞争 IRQ 均被阈值屏蔽。DMB/DSB/ISB 不提供互斥；不支持的控制流和不明硬件配置保留未知，不判安全。
- DMA/Cache、动态回调、RTOS 时序、双核共享内存和复杂 C++ 语义尚不能静态证明。真实中断优先级分组、复杂 BASEPRI、非直线临界区、调度时序与硬件复现仍属于最终工程验证。
- 一键运行会产生最终的本轮报告；如信息不足，最终结果明确是“哪些项仍未完成”，不会承诺“所有变量无风险”。

原设计中的 Codex 复核已改为 OpenCode；`variable_scan` 的过滤选项不再隐藏常量和头文件变量；`native_extractor`/`auto_build_native` 等旧字段不适用于本版 Python/libclang 实现。

## 验证与代码结构

ST 官方 STM32CubeF4 USB CDC 裸机工程的 ARM 构建、20 项深层并发预埋矩阵、真实 OpenCode 复核与误报校准见 [实工程验证报告](docs/stm32_cube_cdc_validation.md)。可重复执行的源码、独立预期和入口见 [场景说明](tests/fixtures/stm32_cdc/README.md)；包含风险、安全对照与二进制实现缺失场景，未进行目标板烧录。

```powershell
python -m unittest discover -s tests -v
python scripts/verify_design.py --all
```

测试覆盖真实 Clang AST、符号身份、读写/RMW/宏、数组/指针/sizeof、C++ 静态成员、调用传播/递归、任务注册、保护六态与完整窗口、旧快照、部分失败、SQLite 和 OpenCode 子进程协议/超时/缓存。OpenCode 协议测试使用可控的假 CLI；未假装完成真实模型复核或目标板验证。

第二条命令额外保留验收日志和 D01–D20 的全部报告，输出到 `output/design-acceptance/`。场景预期见 [Demo 验收矩阵](examples/stm32_demo/cases/README.md)，实现边界见 [设计追踪矩阵](docs/design_traceability.md) 与 [本轮开发报告](docs/final_implementation_report.md)。

代码按 `config`、`compilation`、`extract`、`pointer_extract`、`points_to`、`analysis`、`multicore`、`review`、`report`、`html_report`、`cli` 分层。真实 STM32H747 三变体工程和可重复验收入口见 [验证工程说明](validation/stm32_concurrency/README.md)，当前进度见 [progress.md](validation/stm32_concurrency/progress.md)。已建立真实 ARM 构建和 GCC 独立变量台账，最终是否通过以 `acceptance.json` 为准；没有目标板烧录验证。逐项需求审核与本次修复见 [需求审核记录](docs/requirements-audit.md)。

用户复制的 STM32F103C8 `serial - continue` 工程已增加实际主循环/中断/DMA/FreeRTOS 并发注入与独立验收，见 [42 场景矩阵及复现入口](validation/serial_continue/README.md)。结果以该目录的 `acceptance.json` 为准，静态发现、真实模型复核和未做的板上验证分别记录；源文件保留故意注入的缺陷。

接口依据：[Clang libclang](https://clang.llvm.org/docs/LibClang.html)、[OpenCode CLI](https://opencode.ai/docs/cli/)、[OpenCode 权限](https://opencode.ai/docs/permissions/)。
# global_static_concurrency_design
