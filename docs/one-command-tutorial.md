# 从零接入：在新的 STM32 CMake 工程中排查全局 / static 变量并发问题

本教程面向一个**刚创建或刚迁移到 CMake 的 STM32 固件工程**。完成一次接入后，日常只需一条命令：工具会重新配置 CMake、生成真实的编译数据库、增量构建、分析变量访问，并生成可离线阅读的报告。

它关注的是容易被中断、主循环、RTOS 任务、回调和 DMA 同时访问的**全局变量和 `static` 变量**。工具不会修改源代码、CMake 配置或烧录开发板；它只使用工程原有的编译参数来理解源码。

> 本文中的 `D:/firmware/MyBoard` 和 `H:/global_static_concurrency_design` 都是示例路径，请换成自己的实际路径。PowerShell 中含空格的路径必须保留双引号。

## 你将完成什么

假设新工程结构类似 STM32CubeMX/CMake 常见布局：

```text
D:/firmware/MyBoard/
├── CMakeLists.txt
├── cmake/arm-none-eabi.cmake       # 可选：交叉工具链文件
├── Core/
│   ├── Inc/
│   └── Src/
├── App/                            # 可选：自己的业务代码
├── Drivers/                        # HAL、CMSIS 等第三方代码
└── Middlewares/                    # 可选：FreeRTOS、文件系统等
```

最终会多出两个可忽略的本地目录：

```text
build/ecra/                         # ECRA 专用 CMake 构建目录与 compile_commands.json
.ecra/                              # 日志、JSON/SQLite 事实和 HTML 报告，不存新语义配置
```

建议将 `build/ecra/` 和 `.ecra/` 写进固件工程的 `.gitignore`。`semantics.yaml` 不再放在固件目录：它由并发工具根目录的 `config/projects/<项目名>/semantics.yaml` 管理，`config/projects.yaml` 记录固件目录与配置的对应关系；固件 `.ecra/` 只保存运行产物。

## 1. 先确认 CMake 工程能独立编译

在接入工具之前，先在固件工程目录使用你平时的方式完成一次 CMake 配置和编译。工具依赖真实的编译选项（芯片宏、`-I`、`-D`、CPU、FPU、语言标准等）；不能用只包含几个源文件的临时命令替代。

下面是适用于 PowerShell 的可复制示例。`cmake/arm-none-eabi.cmake` 只是示例文件名，必须先以实际存在的工具链文件替换它。命令会只删除本段指定的 `build/manual`，以清除上一次失败配置遗留的工具链和生成器缓存；不要把它改成 IDE 正在使用的构建目录。

```powershell
Set-Location "D:/firmware/MyBoard"
$toolchainFile = (Resolve-Path ".\cmake\arm-none-eabi.cmake").Path
$manualBuild = Join-Path (Get-Location) "build\manual"
if (Test-Path -LiteralPath $manualBuild) {
  Remove-Item -LiteralPath $manualBuild -Recurse -Force
}
cmake -S . -B $manualBuild -G Ninja "-DCMAKE_TOOLCHAIN_FILE=$toolchainFile" -DCMAKE_BUILD_TYPE=Debug
cmake --build $manualBuild
```

`Resolve-Path` 会在 CMake 启动前验证文件存在，并把路径转换为绝对路径；引号会保证路径中有空格时仍是一个参数。不要把 Markdown 中用于显示的反斜杠或转义字符输入命令。若出现 `Ignoring extra path from command line: ".cmake"`，说明 `.cmake` 被传成了单独参数；请完整复制上面的单行 `cmake` 命令。

这一步应能生成 `.elf` 或其他既有固件产物。若报 `Could not find toolchain file`，先确认 `$toolchainFile` 指向的文件名与实际文件完全一致，再删除**本次手工使用的** `build/manual` 后重新配置；不要仅在已有失败缓存上反复执行 CMake。`CMAKE_C_COMPILER`、`CMAKE_ASM_COMPILER` 和 `CMAKE_MAKE_PROGRAM` 未设置通常都是这个首个配置错误的连带信息。

若单独报 `CMake was unable to find a build program corresponding to "Ninja"`，先执行：

```powershell
Get-Command ninja
ninja --version
```

找不到时安装 Ninja 或把其所在目录加入当前终端的 `PATH`，然后重新打开终端并从清理构建目录开始。若工程本来使用 `MinGW Makefiles` 或其他生成器，应将本节的 `-G Ninja`、后文的 `cmake.generator` 一并换成实际生成器；不要只改其中一处，也不要为此手工设置 `CMAKE_MAKE_PROGRAM`。

### CMakeLists.txt 要点

工具会在自己的构建目录中配置 CMake，并要求生成 `compile_commands.json`。大多数 CMake + Ninja 工程无需改动，因为工具会传入导出选项。若工程显式关闭了该选项，请删除该覆盖，或确保如下设置为 `ON`：

```cmake
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
```

工具链文件在 `CMakeLists.txt`、`CMakePresets.json` 和命令行中的引用必须使用同一个、实际存在的文件名。例如工程内文件是 `cmake/arm-none-eabi.cmake` 时，下面这些引用都必须是该文件，而不能有一处仍写成不存在的 `arm-none-eabi-toolchain.cmake`：

```cmake
# CMakeLists.txt：工程自行加载工具链时
include("${CMAKE_CURRENT_LIST_DIR}/cmake/arm-none-eabi.cmake")
```

```json
// CMakePresets.json：使用 Preset 时
"CMAKE_TOOLCHAIN_FILE": "${sourceDir}/cmake/arm-none-eabi.cmake"
```

命令行传入 `CMAKE_TOOLCHAIN_FILE` 可以临时绕过工程中“自动 include 工具链”的分支，但不会修复错误的 `CMakeLists.txt` 或 Preset。应先统一这些引用，之后才能可靠地使用不带 `-D` 的普通配置命令或 `cmake --preset ...`。

不要在编译数据库中手工删减 `-DSTM32xxxx`、`-DUSE_HAL_DRIVER`、`-mcpu`、`-mthumb`、FPU/ABI 或 include 路径。这会令 Clang 看到与真实固件不同的条件编译分支，报告不再可信。

## 2. 一次性准备电脑环境

在安装 ECRA 的目录执行一次：

```powershell
Set-Location "H:/global_static_concurrency_design"
py -3.10 -m pip install -r requirements.txt
cmake --version
ninja --version
arm-none-eabi-gcc --version
```

需要 Python 3.10 或更高版本、CMake、构建生成器（本文使用 Ninja）和工程实际使用的 Arm GCC。若你使用 Makefiles，可把后文的 `generator` 改成与你平时调用 CMake 时一致的生成器名称；不要仅为了运行工具而换一种构建系统。

可选：安装命令入口，之后可以直接输入 `ecra`：

```powershell
py -3.10 -m pip install -e "H:/global_static_concurrency_design"
```

若 Python Scripts 目录不在 `PATH`，继续使用本文中的 `py ... run_ecra.py` 命令即可，不影响功能。

## 3. 在新工程中生成配置

下面的命令只创建配置，不会覆盖已有配置，也不会编译或扫描：

```powershell
py -3.10 "H:/global_static_concurrency_design/run_ecra.py" init `
  --project "D:/firmware/MyBoard"
```

生成文件为：

```text
H:/global_static_concurrency_design/config/projects/myboard/semantics.yaml
```

如果工程根目录有 `CMakeLists.txt`，`init` 会创建 CMake 模板，并尝试识别根目录及 `cmake/` 下唯一的 Arm GCC 工具链文件。非标准位置请在初始化命令加 `--toolchain-file cmake/custom.cmake`；多个候选不会替你猜选。两类模板均默认 `include_dirs: [.]`，排除 `Drivers/Middlewares/ThirdParty/build/.ecra`，避免漏掉 `BSP/User/Modules` 等自定义业务目录。仍需按实际归属检查排除规则：如果自己的代码放在 `Drivers`，应移除该目录级排除，改用精确第三方路径。

没有 CMake 时，自动查找也支持 `Debug/Release` 和嵌套构建目录。发现多个 `compile_commands.json` 会要求在 `analysis.compile_database` 指定唯一变体，不能把两个变体的访问混成同一固件。标准头文件未找到时检查真实工具链，并设置 `analysis.auto_system_includes: true`。

旧项目的 `.ecra/semantics.yaml` 可用同一条 `init` 命令迁移到工具侧，原内容不变，旧文件作为备份保留。已登记配置不会被覆盖。使用 `py -3.10 run_ecra.py projects` 查看实际配置 ID，之后直接 `py -3.10 run_ecra.py --profile myboard`。两个模板均默认不调用模型；显式 `init --model <模型>` 或配置 `review.enabled: true` 才启用自动复核。

## 4. 编辑工具侧 `semantics.yaml`：先做最小正确配置

打开 `H:/global_static_concurrency_design/config/projects/myboard/semantics.yaml`（以 `init` 实际打印路径为准），按实际项目改成类似下面的配置。YAML 只能有一个 `analysis:` 和一个 `review:` 节；不要把同名节再复制一遍。

```yaml
version: 1

project:
  chip: STM32F103C8       # 换成实际芯片
  core: Cortex-M3         # 换成实际内核，如 Cortex-M4 / Cortex-M7
  native_word_bits: 32

analysis:
  # 只审查这些目录中“定义”的全局/static 变量。
  include_dirs: [Core/Src, Core/Inc, App]

  # 第三方变量不进入变量清单、风险候选或模型复核任务。
  exclude_dirs: [Drivers, Middlewares, ThirdParty, build, .ecra]

  # 有些 CubeMX/ST 支撑文件混在 Core/Src，需要逐个排除。
  exclude_files:
    - Core/Src/system_stm32f1xx.c
    - Core/Src/syscalls.c
    - Core/Src/sysmem.c

  cmake:
    build_dir: build/ecra
    generator: Ninja
    build_type: Debug
    # 若 CMakeLists.txt 没有自行加载交叉工具链，取消下一行注释：
    # toolchain_file: cmake/arm-none-eabi.cmake
    args: []
    build: true

  # 使用实际 Arm GCC 自动查找标准头文件路径。
  auto_system_includes: true

  # 可选：防止误用错误芯片或错误构建变体；它只检查、不注入宏。
  expected_defines: [STM32F103xB, USE_HAL_DRIVER]
  output_dir: .ecra
  open_report: false

contexts:
  - id: main
    kind: MAIN
    functions: [main]

review:
  enabled: false
  command: [opencode]
  timeout_seconds: 300
  retries: 1
  max_items: 0
```

先不要为了让报告“更干净”而跳过 `Core/Src`。工具需要看到中断入口、主循环和业务代码之间的真实调用链。

### 关键字段怎么填

| 字段 | 怎么填写 | 常见误区 |
|---|---|---|
| `include_dirs` | 自有 `.c` 和 `.h` 所在目录；相对工程根目录，可列多个 | 只填 `Core/Src`，漏掉头文件中的 `static` 实例 |
| `exclude_dirs` | HAL、CMSIS、RTOS、第三方组件等目录 | 排除目录并不表示其中变量已经安全，只表示不作为审查对象 |
| `exclude_files` | 混在自有目录的 ST 启动/支撑源文件 | 不要用通配符；这里必须是明确文件路径 |
| `cmake.build_dir` | 专用、未被 IDE 占用的构建目录 | 不要复用 IDE 的构建目录，避免生成器和缓存互相冲突 |
| `cmake.generator` | 与本机 CMake 工程实际一致，如 `Ninja` | CMake 缓存已经由别的生成器创建会报错，换专用目录即可 |
| `cmake.toolchain_file` | 仅当工程未在 `CMakeLists.txt`/Preset 中自行指定工具链时填写 | 同时在工程和此处以不同方式指定工具链，会造成配置不一致 |
| `cmake.args` | 原工程需要的 `-D` 选项，每项一个字符串 | 不要写成一个带空格的大字符串 |
| `expected_defines` | 实际编译命令必然含有的芯片/功能宏 | 它不替代 CMake 定义宏，只用于尽早发现选错变体 |

路径规则：`Core/Src` 指的是 `D:/firmware/MyBoard/Core/Src`，不是 `.ecra/Core/Src`。`include_dirs` 必须存在；`exclude_dirs` 可暂时不存在，以便同一份配置在不同板型分支复用。

### 为什么要分开“排除变量”和“跳过解析”

`exclude_dirs` / `exclude_files` 会把第三方**自身定义的变量**排除出清单，但相关的 HAL 调用链仍可作为证据。例如：

```text
USART2_IRQHandler → HAL_UART_IRQHandler → HAL_UART_RxCpltCallback
                  → App_OnByteReceived → g_rx_events
```

这样可以保留“用户变量 `g_rx_events` 在中断上下文中被写”的事实，而不让 HAL 内部变量淹没报告。

旧字段 `analysis.exclude` 的语义不同：它会跳过匹配的编译单元/头文件。普通 STM32 CMake 工程通常不需要它。只有确定某些文件**不属于当前构建变体**（例如同仓库保留的另一套 RTOS 源文件）时才使用，且不要用它排除 `Drivers/*`。

### 有 RTOS、多个任务或动态回调时补充上下文

无参数的 `*IRQHandler`、常见 Cortex-M 异常和 `main` 会自动识别。FreeRTOS/CMSIS v2 常见任务注册也会尽力恢复。若任务入口通过自己的封装、CMSIS v1 或动态函数指针注册，显式补充，例如：

```yaml
contexts:
  - id: main
    kind: MAIN
    functions: [main]
  - id: control
    kind: TASK
    functions: [ControlTask]
  - id: telemetry
    kind: TASK
    functions: [TelemetryTask]
  - id: tim2_irq
    kind: ISR
    functions: [TIM2_IRQHandler]
    priority: 1

# 可选：为报告补充已知抢占关系；它是证据，不会自动消除风险。
preemption:
  - higher: tim2_irq
    lower: control

# 当库回调无法由静态调用图恢复时，补充一条真实运行边。
call_edges:
  - caller: TIM2_IRQHandler
    callee: HAL_TIM_PeriodElapsedCallback
```

不要把普通主循环直接调用的函数另建成 `TASK`；它会被当作可并发的独立执行体。两个不同任务若复用同一个入口函数，应创建两个不同的 `TASK` id。

## 5. 先做环境检查，再执行第一次扫描

环境检查不会覆盖上次报告，也不会进行变量分析：

```powershell
py -3.10 "H:/global_static_concurrency_design/run_ecra.py" doctor `
  --project "D:/firmware/MyBoard"
```

通过后执行完整扫描：

```powershell
py -3.10 "H:/global_static_concurrency_design/run_ecra.py" `
  --project "D:/firmware/MyBoard"
```

### 已登记工程：一次性生成 `serial-opencode2` 结果

本仓库已在 `config/projects.yaml` 登记 `serial-opencode2`，其配置在 `config/projects/serial-opencode2/semantics.yaml` 中，并已指定实际工具链 `cmake/arm-none-eabi.cmake`、专用构建目录 `build/ecra` 和 Ninja。直接在 ECRA 根目录执行下面这一条命令即可重新配置、增量构建、分析并写出结果：

```powershell
Set-Location "H:/global_static_concurrency_design"
py -3.10 .\run_ecra.py --profile serial-opencode2
```

当前该 profile 的 `review.enabled` 为 `false`，因此此命令只进行本地静态分析，不会调用 OpenCode。结果位于 `H:/stm32_RAG/code/serial - opencode2/.ecra/`，其中可直接打开 `index.html`；CMake 的专用编译数据库位于 `build/ecra/compile_commands.json`。若只想先检查环境而不做完整分析，使用：

```powershell
py -3.10 .\run_ecra.py doctor --profile serial-opencode2
```

该命令依次完成：

```text
读取 semantics.yaml
    ↓
配置 CMake（导出 compile_commands.json）
    ↓
增量构建固件，不烧录
    ↓
用真实编译参数解析源码和依赖
    ↓
盘点范围内全局/static 变量，关联读写、调用链和执行上下文
    ↓
生成 HTML、JSON、Markdown 和 SQLite 报告
```

首次运行中常见的正常输出包括 `CMake 配置并刷新编译数据库…`、`CMake 增量构建固件…` 和 `Clang n/m [依赖]: Drivers/...`。出现 `[依赖]` 不代表第三方变量被纳入结果；它只表示工具在恢复用户变量的调用证据。

若希望完成后自动打开报告，把 `open_report` 改为 `true`；也可手工打开：

```powershell
Invoke-Item "D:/firmware/MyBoard/.ecra/index.html"
```

## 6. 第一次报告应该怎样读

先打开 `.ecra/index.html`，按下面顺序判断这轮扫描是否可用：

1. 看“过滤结果与排查范围”。`include_dirs`、排除目录和逐文件排除应与配置一致，并确认没有范围外变量进入结果。
2. 看“源码解析”或“过滤与覆盖校验”。有解析失败、未知调用或漏编译源文件时，先处理其诊断；这些不是“安全”。
3. 看“变量风险结论”。每个全局变量、文件 `static`、函数 `static`（含头文件 `static` 的各翻译单元实例）都有记录。普通局部变量、参数和结构体字段不会单独成行。
4. 对橙色“疑似风险”或灰色“无法判断”，展开读写明细和调用链，确认读写是否确实处于 `main`、ISR、不同任务或回调上下文中。
5. 对候选查看“可能出问题的执行顺序”。它是基于源码的可交错示例，用于指导人工复现，不是工具声称已经捕获的实际运行轨迹。

报告中的常见结论应这样理解：

| 页面状态 | 含义 | 下一步 |
|---|---|---|
| 疑似并发风险 | 发现跨上下文读写、读改写、旧快照写回、可重入 `static` 等静态线索 | 在源码和板上/单元测试中验证交错是否真的可发生 |
| 无法判断 / 覆盖缺口 | 动态回调、间接调用、DMA、解析失败或别名关系未恢复 | 补充上下文/调用边，或保留为人工审查项 |
| 未发现静态线索 | 当前建模路径中没有触发规则 | 不是“变量已证明线程安全” |
| 已复核安全 / 误报 | 仅在明确列出的前提条件下成立 | 记录前提，代码或配置变化后重新扫描 |

特别注意：`volatile` 不等于互斥；32 位 Cortex-M 上的单次对齐访问也不等于 `x++`、读取快照后回写、多个字段协议或 DMA 缓冲区安全。报告将保护 API 仅标为“存在保护证据”或“部分保护”，仍需检查临界区是否覆盖整条执行路径。

常用输出如下：

| 文件 | 用途 |
|---|---|
| `.ecra/index.html` | 全量变量清单、读写、调用链、静态候选和覆盖缺口 |
| `.ecra/opencode_review.html` | 模型复核状态；未启用模型时也会明确显示待复核 |
| `.ecra/cmake-configure.log` / `cmake-build.log` | CMake 配置或构建失败时首先查看 |
| `.ecra/reports/global_static_concurrency.json` | 机器可读的风险、范围和覆盖信息 |
| `.ecra/reports/unknown_contexts.md` | 未能恢复的上下文、间接调用、DMA 等盲区 |
| `.ecra/run.log` / `run.json` | 本轮运行过程、结束状态和返回码 |

## 7. 日常怎么用

修改源码、CMake 参数、芯片宏或构建变体后，重复完整命令即可。CMake 模式会刷新已有编译数据库，无需手工删除或复制 `compile_commands.json`：

```powershell
py -3.10 "H:/global_static_concurrency_design/run_ecra.py" `
  --project "D:/firmware/MyBoard"
```

如已安装命令入口，则在固件根目录可简化为：

```powershell
Set-Location "D:/firmware/MyBoard"
ecra
```

其他命令：

| 命令 | 适用场景 |
|---|---|
| `ecra doctor` | 检查依赖、CMake/数据库和模型命令，不重扫源码 |
| `ecra status` | 查看上次扫描状态、未完成数量和建议下一步 |
| `ecra report` | 不重新解析源码，只刷新已有 HTML/配套报告 |
| `ecra review` | 已扫描且源码未变，只继续未完成的模型复核 |
| `ecra --no-review` | 本次只做本地静态扫描，不调用模型 |

`report` 和 `review` 会验证已有扫描是否仍与源码、配置和编译输入匹配。若新增源文件、变更宏或构建变体，应回到完整的 `ecra` 重新扫描。

## 8. 可选：启用 OpenCode 逐项复核

默认 `review.enabled: false`，所以首次接入不需要 OpenCode 帐户。静态报告会照常生成，候选显示为待人工核对。

当本机已安装并配置好 OpenCode 后，将配置改为：

```yaml
review:
  enabled: true
  command: [opencode]
  # model: provider/model
  timeout_seconds: 300
  retries: 1
  max_items: 0
```

然后仍运行同一条完整命令。工具会把每个候选的相关源码证据交给已配置的模型提供商进行复核，费用、数据政策和模型名称取决于该提供商。建议先将 `max_items: 1` 做一次连通性验证，再改回 `0`（不限数量）。OpenCode 的安装与登录请参阅其[官方 CLI 文档](https://opencode.ai/docs/cli/)。

模型结论是代码审查辅助，不替代编译、硬件时序验证、代码评审或目标板测试。 `CONFIRMED` / `LIKELY` 需要处理和验证；`REVIEWED_SAFE` 仅在报告列出的条件成立时有效；`PENDING`、`FAILED`、`STALE`、`NEED_MORE_CONTEXT` 都不能当作安全结论。

## 9. 常见故障与处理

| 现象 | 原因与处理 |
|---|---|
| `缺少配置` | 在工程根目录运行 `ecra init`，或用 `--project` 指向正确的固件根目录 |
| `排查目录不存在` | 检查 `include_dirs` 相对的是固件根目录；不要相对 `.ecra` 填写 |
| `Could not find toolchain file` | 先用 `Resolve-Path .\cmake\实际文件名.cmake` 核对文件；再检查 `CMakeLists.txt`、Preset、`cmake.toolchain_file` 是否全都引用同一文件名。删除本次失败的专用构建目录后再配置，避免复用错误缓存 |
| `Ignoring extra path from command line: ".cmake"` | 工具链参数被拆成了两个参数。使用 `"-DCMAKE_TOOLCHAIN_FILE=$toolchainFile"` 这种整体加引号的写法；不要从 Markdown 复制反斜杠转义符 |
| `CMake was unable to find a build program corresponding to "Ninja"` | 执行 `Get-Command ninja` 和 `ninja --version`。安装/加入 PATH 后重开终端；或将命令和 `cmake.generator` 一起改为工程实际的 Makefiles 生成器 |
| CMake 配置失败 | 先看 `.ecra/cmake-configure.log`；确认 toolchain、Preset、生成器和 `cmake.args` 与正常工程构建一致 |
| CMake 缓存/生成器不匹配 | 更换 `cmake.build_dir` 到新的专用目录，例如 `build/ecra`；不要删除 IDE 构建目录 |
| 没有 `compile_commands.json` | 确认 CMake 没有关闭 `CMAKE_EXPORT_COMPILE_COMMANDS`；再看 configure 日志 |
| `arm-none-eabi-gcc` 找不到或标准头文件失败 | 确认交叉编译器在 `PATH` 中且能运行；特殊工具链可关闭 `auto_system_includes` 并用 `extra_args` 补充必要 `-isystem` 路径 |
| GCC 构建成功但 Clang 报 `stdatomic.h` / `_Atomic` 类型错误 | 检查是否显式把 GCC 私有 include 放在运行库之前；自动探测现在将私有内建头作为后备。特殊运行库需配置兼容的 Clang 资源头；不要删除 `_Atomic` 或忽略解析错误 |
| `expected_defines` 不满足 | 选错芯片宏、Core 变体或 CMake `-D` 参数；修正真实构建参数，不要只删除检查项掩盖问题 |
| 报告中看见 HAL 文件 | 这是分析用户变量调用链所需的 `[依赖]` 证据；检查第三方变量是否确实未进入目标变量清单 |
| 自己头文件的 `static` 未显示 | 把头文件目录加入 `include_dirs`，确认它未被 `exclude` 跳过，并查看覆盖诊断 |
| 同名 `static` 看起来重复 | 这是正常的：不同 `.c` 文件或不同翻译单元中的头文件 `static` 是独立对象，应按定义位置区分 |
| 返回码为 1 或 2 | 报告已经生成；1 表示有候选，2 通常表示覆盖盲区或复核未完成。先打开报告而不是把它当作崩溃 |
| 遗留“已有扫描锁” | 先确认上一个 ECRA 进程确已退出；仅在确认后删除工程 `.ecra` 下的过期锁文件 |

返回码 `0` 表示环境检查成功或当前建模范围内没有候选，`1` 表示流程完成但仍有候选，`2` 表示解析/上下文/复核不完整，`3` 表示配置、构建或运行失败，`130` 表示用户中断。无论返回码如何，是否存在风险都应以报告的范围、覆盖情况和逐项证据为准。

## 10. 接入完成后的建议

- 将 `semantics.yaml` 中的目录、芯片、工具链和任务入口作为工程配置的一部分维护；增加新模块或新任务时一并更新。
- Debug、Release、不同 MCU 型号、双核的 CM7/CM4、启用/关闭 FreeRTOS 等都是不同编译变体，应分别运行并分别阅读报告。
- 每次新增 ISR、DMA 回调、任务注册、共享缓冲区或临界区后运行一次完整扫描；修复后再扫描一次，确认候选和覆盖缺口的变化。
- 对高优先级候选，结合源代码、临界区、真实中断优先级、DMA/cache 配置和目标板压力测试作最终判断。

如果想先对照一个已经接入的裸机项目，可查看仓库中的 [`config/projects/serial-continue/semantics.yaml`](../config/projects/serial-continue/semantics.yaml)。其中包含该示例特有的 `SERIAL_CONCURRENCY_RTOS` CMake 参数和 RTOS 注入文件排除项，不能原样复制到新工程。关于复杂中断/回调注册和安全筛除规则，请阅读[工具设计文档](concurrency-tool-design.md)；关于如何针对具体变量判断“可能丢事件、读改写被打断或 DMA 竞争”，继续阅读[真实变量排查案例](variable-investigation-guide.md)。
