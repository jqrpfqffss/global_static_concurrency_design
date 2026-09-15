# STM32 全局变量与 static 变量并发排查工具（ECRA）

先盘点变量，再追踪“谁在什么任务/中断里读写”，生成本地报告；可选启用 OpenCode 逐项复核。用户不需要手工填写变量列表，默认无需模型账户。源码不会被工具修改。

第一次使用请看 [详细操作教程：简单配置后，一条命令完成并发排查](docs/one-command-tutorial.md)。以 `serial - continue` 裸机工程为例，包含多个排查/排除目录、自动 CMake 构建、报告阅读与故障处理。工具整体架构、风险判定与 STM32 分层中断/回调适配见[设计文档](docs/concurrency-tool-design.md)。详细源码排查另见 [变量案例](docs/variable-investigation-guide.md)。

适用于 CMake STM32 裸机工程（自动生成真实 `compile_commands.json`），也兼容已有编译数据库的工程，也能盘点 C++ 命名空间变量和静态成员；C++ 复杂运行语义会单独标记盲区。第一版采用 Python + libclang，不需要自行构建 C++ 提取器，也不要求虚拟环境。

## 完整变量清单与覆盖检查

`index.html` 默认打开“全部全局 / static 变量清单”。无风险候选、常量、未使用变量也保留；全局变量、文件 static、函数 static（含头文件实例和 C++ 静态成员）均可查询。同名 static 按编译单元区分。文件筛选同时匹配定义和声明所在文件。普通自动局部变量、函数参数和结构体/联合体字段不作为共享对象盘点。

配置包含范围内未进入编译数据库的 C/C++ 源文件、未被包含的头文件也会补充盘点。关闭的条件分支在原文件上下文中按分支变体解析，包括嵌套和 elif/else；有真实包含关系的头文件使用原编译单元、工作目录及参数。显式排除规则仍优先，依赖自身变量不会进入目标清单。

“补充声明（未分析访问）”只表示找到了声明。它不向当前固件注入调用链、任务或中断访问，也不表示安全。清单只覆盖全局/static 对象；自动局部变量、参数和字段仍会作为指针/别名分析的对象参与共享访问建模，但不单独列为清单行。

“过滤与覆盖校验”逐文件显示变量数量、解析状态和诊断，包括零变量文件。解析错误、无法恢复的类型/宏/条件组合及未编译文件会明确保留覆盖缺口；部分 AST 仍可显示已恢复声明。分支变体不穷举不同文件间所有宏配置组合，因此存在覆盖缺口时不得声称所有声明已完整恢复或已排除全部风险。应修正诊断，必要时分别扫描真实构建变体。

修改提取实现后需要重新运行完整扫描；旧报告不能只刷新后作为新盘点结果。JSON、Markdown、HTML 使用同一变量集合。可复现验收结果见 `output/variable-inventory-fix/verification.md`。


## 裸机 CMake 工程：配置一次，日常一条命令

当前工程已配置好工具侧的 `config/projects/serial-continue/semantics.yaml`，并由 `config/projects.yaml` 关联到固件目录；固件 `.ecra/` 只保存运行产物。在工具根目录执行：

```powershell
py -3.10 run_ecra.py --profile serial-continue
```

自动刷新 CMake 编译数据库、增量构建、排查自有目录、输出 `.ecra/index.html` 和 `.ecra/opencode_review.html`。新工程默认本地静态排查；当前 `serial-continue` 配置已启用真实 OpenCode 复核，并指向 `H:/stm32_RAG/test/serial - continue`。只做本地扫描时加 `--no-review`。`analysis.open_report: true` 可自动打开浏览器。

OpenCode 页面顶部直接显示总体结论：有问题、当前覆盖范围内未确认问题、或尚不能确定。确认存在一个变量缺陷即可回答“有问题”，但剩余疑似项、失败项和覆盖盲区仍保留，不能宣称全工程排查完成。`LIKELY` 不算最终定论，下次 `review` 会重新复核。

所有项目的首轮与反证复核统一使用 [OpenCode 输出协议 v2](docs/opencode-review-format.md)。一句话结论、实际参与者、抢占条件、逐步动作、操作前后状态、预期与实际结果均由 OpenCode 直接生成；页面按固定栏目展示，工具不会代写缺失解释。缺字段、无效引用或使用已排除入口构造冲突会退回 OpenCode 重试。旧回答保留并标注旧版格式，运行 `review` 后由 OpenCode 按新协议重新复核；仅刷新 `report` 不会伪造格式升级。

每项证据包含文件、行号、源码原文 `quote` 和事实说明 `claim`。新回答必须提供与该行一致的原文；程序保存引用处源码、文件 SHA-256、执行时间和原始 OpenCode JSONL 日志。缓存和 `report` 刷新会核对日志、答案与源码的一致性，缺日志或内容变化会失效。日志链接在每项结论中；这能检查记录完整性，但不代表模型推理已由硬件实验验证，也不是防恶意同时改写全部文件的签名。

`review.workers` 可设置为 1–8（默认 1，当前示例为 4）。独立只读会话分别处理候选，主线程保存完整、有序的队列；`max_items` 是本轮实际发起复核的总限额。每项输入补充完整相关函数（最多 1600 行，超出部分按路径继续读取），用于核对中断入口、提前返回和真实保护范围。权限按 [OpenCode 官方说明](https://opencode.ai/docs/permissions/) 配置，禁止修改、shell 和继续委派。

`review.audit_verdicts: true` 会对已返回的答案再做一次 OpenCode 反证复核，也会尝试恢复首轮执行失败的项。它重点查找安全证明遗漏的重置/错误恢复路径、无法成立的抢占、指针与缓冲区混淆、没有源码依据的业务读者，以及修复建议是否在 DMA 忙期间仍修改缓冲区。首轮答案和日志保留在 `previous_reviews`，新结论来自新日志；反证执行失败时保留未决，不能沿用首轮安全判断。两轮由同一 OpenCode 会话继续完成，属于模型自查，不是独立专家或板上实验。

判定时分开报告存储一致性与业务影响：没有额外业务消费者，不能据此否认 `++` 或位域/union 的非原子读改写会丢失更新；反过来，原子字节 store/store 的最后写者生效，也不能凭空推导出不存在的业务协议被破坏。变量结论绑定自己的 `symbol_id`，指针指向对象的问题不能重复算成指针本身的问题。

新工程先安装依赖，再生成一次**工具侧**配置：

```powershell
py -3.10 -m pip install -r requirements.txt
py -3.10 H:/global_static_concurrency_design/run_ecra.py init --project "D:/MyFirmware"
```

把示例固件路径换成自己的。检测到 `CMakeLists.txt` 时，初始化会在工具根目录 `config/projects/<项目名>/semantics.yaml` 生成 CMake 裸机模板，并登记到 `config/projects.yaml`；主要编辑包含/排除目录和 CMake 参数。以后只需执行一条完整排查命令；`doctor`、`review`、`report`、`status` 保留用于分步定位问题。

`py -3.10 run_ecra.py projects` 列出配置 ID、固件目录和配置路径。所有运行/分步命令均支持 `--profile <ID>`，也保留 `--project <目录>`；两者不混用。同名固件目录自动分配不同 ID。已安装工具目录不可写时，可在启动前设置 `$env:ECRA_CONFIG_HOME='D:/ecra-config'`，统一存放索引和语义配置。跨工程验证及已知边界见[移植验收记录](docs/portability-validation.md)。

初始化默认包含整个工程 `include_dirs: [.]`，排除常见第三方和产物目录，避免只识别 `Core` 导致遗漏 `BSP/User/Modules`。请按实际目录归属检查排除规则；第三方源码中的调用链仍作为依赖分析。CMake 初始化会识别根目录或 `cmake/` 下唯一的 Arm GCC 工具链文件；非标准位置可用 `init --toolchain-file <路径>` 指定。

```yaml
analysis:
  include_dirs: [Core/Src, Core/Inc]  # 多目录取并集，递归包含
  exclude_dirs: [Drivers, Middlewares, ThirdParty]  # 排除优先
  exclude_files: [Core/Src/system_stm32f1xx.c, Core/Src/syscalls.c, Core/Src/sysmem.c]
  cmake:
    build_dir: build/ecra
    generator: Ninja
    build_type: Debug
    # toolchain_file: cmake/arm-none-eabi.cmake
    args: []
    build: true
  auto_system_includes: true
  output_dir: .ecra
```

目录相对固件根目录，也可使用绝对路径。包含目录必须存在；空包含列表表示不限制范围。根据变量定义文件归属范围；头文件 static 保留不同编译单元的身份，extern 以实际定义归属。排除目录里的变量不进入清单、候选或模型任务。

**第三方文件可能混在业务目录中**：ST 的 `SystemCoreClock` 等变量定义在 `Core/Src/system_stm32f1xx.c`，只排除 `Drivers` 不会排除它们。用 `exclude_files` 列出这些文件，无需移动源码；最终输出会再次校验排除范围。

**依赖仍可被解析**：HAL 调用用户回调、库函数通过指针写用户变量的证据不能因排除第三方自有变量而消失。无关第三方盲区不进入队列；影响目标调用链的缺口和依赖解析失败仍保留并说明原因。旧 `analysis.exclude` 跳过匹配的编译单元，并过滤匹配头文件的变量；需要保留依赖分析时使用 `exclude_dirs` / `exclude_files`。

HTML 首页按变量给出“已确认风险 / 疑似并发风险 / 无法判断 / 已复核安全 / 已排查不存在并发风险”的数量，点击数字即可筛选；每行直接展示风险标签、关键读写和处理动作。最后一类是满足完整证据约束的本地静态筛除，与模型复核安全不同；仅仅未发现静态线索不代表已证明安全。

JSON 的 `risk_summary` 与 HTML、Markdown 共用变量风险分类；`review_summary` 单独统计模型复核进度。具备源码证据的快照候选可展开三步交错示例；打印会保留当前筛选并包含全部匹配分页。过期或失败的旧回答不进入当前结论和修复清单。

两个 HTML 均可离线打开，支持搜索、筛选、分页。变量页顶部展示排查范围；展开变量可查看读写、实际上下文、调用链和保护证据。未启用模型时，第二页仍生成并明确保留待复核状态；不能把静态候选或被排除目录当成安全结论。

## 日常使用：不必每次重扫固件

在固件目录执行以下命令，或加 `--project D:/firmware`：

| 命令 | 作用 |
|---|---|
| `python H:/global_static_concurrency_design/run_ecra.py` | 重新盘点源码并执行完整复核流程 |
| `python H:/global_static_concurrency_design/run_ecra.py review` | 校验已有扫描后继续 OpenCode 复核，不重跑 Clang；复用有效完成项，处理剩余项 |
| `python H:/global_static_concurrency_design/run_ecra.py report` | 校验已有扫描，仅刷新两个 HTML 及配套报告，不调用模型 |
| `python H:/global_static_concurrency_design/run_ecra.py status` | 显示已保存进度、未完成数量、能否恢复及下一步建议；加 `--json` 输出结构化信息 |
| `python H:/global_static_concurrency_design/run_ecra.py doctor` | 检查源码分析环境与 OpenCode 命令可用性，保留上轮运行记录和报告 |

恢复会验证源码、实际包含的外部头文件、嵌套 `@response` 文件、编译数据库、分析配置、分析实现和事实完整性。新增/删除源码、修改芯片宏或损坏事实会要求重新执行 `run`。修改复核设置无需重新解析；更换模型或命令会重新复核，调整数量限额、超时和重试次数会保留有效的已完成项。`review` 命令表示明确启用复核，即使配置中先前写了 `enabled: false`。

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
  max_items: 0
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

每个变量的相关风险合并为一个复核包；解析失败、未知调用目标等无法归属于具体变量的盲区也进入队列。默认串行处理全部项目，防止漏掉低置信度项。可用 `max_items` 限额；未处理项保留 `PENDING`，下次运行继续。

同一文件中的同类盲区合并成复核项，所有具体位置仍保存在原始事实和该项证据中。队列从开始就列出全部项，处理中断也能看到尚未处理的项目。`--no-review` 默认保存两个 HTML、静态报告与完整待办清单，证据包在实际复核时生成；需要提前导出全部包时可设置 `review.prepare_packets: true`。

通过 `opencode run --format json` 获取事件，并要求最终结构化结论。工具检查 finding ID、状态、必要字段，以及证据文件和行号是否存在。模型报错、超时、非法 JSON、证据缺失都会保留为失败/未完成，不接受为空结果。源码证据的语义正确性仍需工程评审。

复核使用独立 `ecra-review` 只读 agent 权限，禁止修改文件和执行 shell。实际源码及证据会交给你配置的 OpenCode 提供商处理。工具不会自动登录、选择付费提供商、设置自动分享或修改固件。

复核缓存绑定工具版本及 Python 实现内容、配置、项目源码和链接脚本、实际包含的外部头文件、编译参数、证据包、提示词和模型设置。构建产物、日志和报告不作为源码指纹，避免输出使自身复核过期。输入变更会重新复核。缓存答案会再次检查状态和证据；失败或 `NEED_MORE_CONTEXT` 会在后续运行重新尝试。扫描/复核期间输入变化会使本轮结果不完整；致命失败会同时替换两个 HTML 的旧结论为失败提示。风险 ID 不依赖访问行号；局部同名 static 使用函数内同名声明次序区分，新增同名声明可能改变后续 ID。

每次运行归档上一轮，`baseline.no_longer_observed` 仅表示本次不再观察到，不自动视为已修复。`known_safe` 注释会保留供复核参考，不隐藏候选。意外中止后若遗留 `scan.lock`，确认对应进程已结束再删除锁。归档会持续增长，可按团队保留策略清理 `snapshots`。

## 准确性边界

- 清单针对**配置排查目录内、实际解析到的当前编译配置**；范围外变量不作安全判断。数据库未列出的源文件和未包含的头文件单独报告；被 `#if` 关闭的声明、其他固件/核配置，不能声称已经完整提取。不同构建变体应分别扫描。
- 文件级 static 包含翻译单元身份，因此头文件里每个独立实例不会错误合并。函数级 static 区分函数和同名局部作用域。`extern` 按 Clang USR 合并。
- 展示每个上下文到访问函数的一条最短证据链；第一个 HTML 可按变量展开所有相关调用边，包括不同调用位置、已恢复的间接边、配置补充边和递归边。用调用图表达多路径，不穷举递归及组合爆炸的所有路径；无法恢复的间接目标仍标为未知。
- 指针采用不区分控制流的保守目标集合，支持跨 TU 参数/返回、初始化地址、结构成员指针、数组衰减、内存函数包装及部分函数指针。数组下标合并，目标仍可能过近似；未解析目标继续保留盲区。旧快照规则也是候选，未证明真实延迟。
- 数组/结构体字段保留容器和访问路径。撕裂风险按容器大小/对齐保守提示，不代表每一次字段访问都发生撕裂。位域和多字段协议需复核。
- 锁 API 出现在相关函数中时标记 `PARTIAL`，仅代表保护证据存在，**未证明路径被保护**；YAML 声明为 `DECLARED_ONLY`。第一版不输出 `VERIFIED`，不因 `volatile`、原子类型或 32 位访问自动消除竞态候选。
- DMA/Cache、动态回调、RTOS 时序、双核共享内存和复杂 C++ 语义尚不能静态证明。真实中断优先级分组、BASEPRI、PRIMASK、调度时序与硬件复现属于最终工程验证。
- 一键运行会产生最终的本轮报告；如信息不足，最终结果明确是“哪些项仍未完成”，不会承诺“所有变量无风险”。

原设计中的 Codex 复核已改为 OpenCode；`variable_scan` 的过滤选项不再隐藏常量和头文件变量；`native_extractor`/`auto_build_native` 等旧字段不适用于本版 Python/libclang 实现。

## 验证与代码结构

```powershell
python -m unittest discover -s tests -v
```

测试覆盖真实 Clang AST、符号身份、读写/RMW/宏、数组/指针/sizeof、C++ 静态成员、调用传播/递归、任务注册、保护不抑制、旧快照、部分失败、SQLite 和 OpenCode 子进程协议/超时/缓存。OpenCode 协议测试使用可控的假 CLI；未假装完成真实模型复核或目标板验证。

代码按 `config`、`compilation`、`extract`、`pointer_extract`、`points_to`、`analysis`、`multicore`、`review`、`report`、`html_report`、`cli` 分层。真实 STM32H747 三变体工程和可重复验收入口见 [验证工程说明](validation/stm32_concurrency/README.md)，当前进度见 [progress.md](validation/stm32_concurrency/progress.md)。已建立真实 ARM 构建和 GCC 独立变量台账，最终是否通过以 `acceptance.json` 为准；没有目标板烧录验证。逐项需求审核与本次修复见 [需求审核记录](docs/requirements-audit.md)。

用户复制的 STM32F103C8 `serial - continue` 工程已增加实际主循环/中断/DMA/FreeRTOS 并发注入与独立验收，见 [42 场景矩阵及复现入口](validation/serial_continue/README.md)。结果以该目录的 `acceptance.json` 为准，静态发现、真实模型复核和未做的板上验证分别记录；源文件保留故意注入的缺陷。

接口依据：[Clang libclang](https://clang.llvm.org/docs/LibClang.html)、[OpenCode CLI](https://opencode.ai/docs/cli/)、[OpenCode 权限](https://opencode.ai/docs/permissions/)。
# global_static_concurrency_design
