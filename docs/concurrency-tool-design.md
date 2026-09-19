# ECRA：STM32 全局变量与 static 变量并发排查工具设计

本文档是本仓库中并发排查工具的设计基线。它说明工具解决什么问题、从哪个配置开始运行、如何形成结论，以及 STM32 裸机大型工程中的适用边界。实现、配置模板、测试和本文件必须一起维护；当行为变化时，优先更新本文件和对应回归用例。

## 1. 目标、范围与非目标

ECRA（Embedded Concurrency Risk Analyzer）面向 C/C++ STM32 固件，自动盘点当前构建配置中的全局变量、文件级 `static` 和函数内 `static`，建立“定义 → 读写 → 函数 → 任务/中断/DMA 上下文”的证据链，并筛选确有读写冲突可能的对象。

它的交付不是一串 grep 命中，而是可离线查看的完整变量清单、候选风险、覆盖缺口和可复核的原始事实。工具不修改固件源码、不烧录目标板，也不会把 `volatile`、锁名称或“看起来只有一个任务”当作安全证明。

排查范围包括：

- 全局对象、文件静态对象、函数静态对象、头文件静态实例及 C++ 静态成员；
- 当前 `compile_commands.json` 对应的宏、头文件、语言标准和目标参数；
- 主循环、硬件中断、FreeRTOS/CMSIS v2 任务、FreeRTOS 定时器/延后回调、DMA 合同和可恢复的函数指针调用；
- 通过配置补充的驱动回调、动态向量和自定义调度器入口。

不把普通局部变量、函数参数或结构体字段单独列为清单对象；它们仍参与指针和别名建模。工具也不试图静态证明所有 ARM 抢占、BASEPRI/PRIMASK、Cache、一切汇编、副核一致性或动态加载回调的运行时语义。遇到这些情况，必须保留为覆盖缺口或要求配置补充，不能输出“全工程无风险”。

## 2. 配置归属与目录约定

项目配置属于工具，而不是被排查固件。工具根目录的布局如下：

```text
global_static_concurrency_design/
├─ config/
│  └─ semantics.yaml                        # 当前唯一待排查项目的配置
├─ ecra/                                    # 分析器实现
├─ docs/                                    # 本文档和操作文档
└─ serial - continue/                       # 被排查的固件；不存放 semantics.yaml
```

`config/semantics.yaml` 是唯一的工具侧配置。`project.root` 以绝对路径或相对该配置所在 `config/` 目录的路径指定当前固件根目录；切换项目时改写该项及其 CMake、范围、芯片宏、任务入口和驱动注册语义。这样不会污染客户工程，也不会在工具侧遗留多份过期项目配置。

`<firmware>/.ecra/` 默认只存放扫描输出、可恢复状态、报告和缓存；建议加入固件 `.gitignore`，也可以指定 `analysis.output_dir`。早期版本创建的 `<firmware>/.ecra/semantics.yaml` 仍能被读取，但新配置一律放在工具侧。对旧工程执行 `init` 会原样迁移并登记，旧文件保留为备份；运行时已登记配置优先，不会混合两份设置。

默认查找 `config/semantics.yaml`；其中的 `project.root` 是唯一的当前目标。显式 `--config` 和 `--project` 仅保留给临时兼容/诊断使用，不会创建或登记更多配置。旧版固件目录 `.ecra/semantics.yaml` 可显式兼容读取，但新流程不会写入它。YAML 重复键、语法错误、入口类型冲突、错误正则、非法超时会在扫描前失败，不静默覆盖。

`ECRA_CONFIG_HOME` 可在进程启动前指定独立可写配置目录（默认工具根目录的 `config`）；该目录中仍只使用一份 `semantics.yaml`。`project.root` 相对配置文件解析；其余分析/输出路径仍以固件根目录为基准。

## 3. 使用模型：一条命令与可诊断分步命令

完成一次配置后，日常完整排查只有一条命令：

```powershell
py -3.10 H:/global_static_concurrency_design/run_ecra.py --project "D:/firmware/MyBoard"
```

工具从 `config/semantics.yaml` 读取 `project.root` 及配置，刷新 CMake 编译数据库（如已配置）、构建、解析、建立上下文和指针关系、生成报告，并按 `review.enabled` 决定是否继续逐项复核。当前配置可直接执行：

```powershell
py -3.10 run_ecra.py
```

首次接入只需执行一次 `init`；它在工具侧创建配置并登记索引，不会在固件目录写入语义配置：

```powershell
py -3.10 H:/global_static_concurrency_design/run_ecra.py init --project "D:/firmware/MyBoard"
```

分步命令保留用于定位失败，而不是正常流程的前置要求：

| 命令 | 用途 |
|---|---|
| `doctor --project <目录>` | 验证配置、libclang、编译数据库/CMake 和复核命令；不扫描。 |
| `run --project <目录>` 或省略 `run` | 从源重新执行完整本地分析及可选复核。 |
| `review --project <目录>` | 只继续已保存扫描的复核队列，不重新解析。 |
| `report --project <目录>` | 只刷新 HTML/Markdown/JSON，不调用模型。 |
| `status --project <目录>` | 查看本轮覆盖、候选和恢复建议。 |

以上运行/分步命令都使用唯一配置中的 `project.root`。初始化默认不启用模型；仅显式指定 `--model` 或设置 `review.enabled: true` 后，完整运行才调用复核工具。`review` 子命令本身表示显式要求复核。

`run` 前配置或构建失败时应先运行 `doctor`，再看 `<firmware>/.ecra/doctor.log`、`cmake-configure.log`、`cmake-build.log` 与 `run.log`。`review`/`report` 会校验配置、源码、编译参数和事实库指纹；任一分析输入变化都会要求重新执行完整 `run`，避免用旧证据刷新新结论。

## 4. `semantics.yaml` 的职责

最小配置只需要真实编译数据库（或 CMake）和排查目录。变量列表不需要手工填写。

```yaml
version: 1
project:
  chip: STM32H7
  core: Cortex-M7
  concurrency_model: single_core_preemptive
  native_word_bits: 32
analysis:
  include_dirs: [Core/Src, Core/Inc, App]
  exclude_dirs: [Drivers, Middlewares, ThirdParty, build, .ecra]
  exclude_files: [Core/Src/system_stm32h7xx.c]
  cmake:
    build_dir: build/ecra
    generator: Ninja
    build_type: Debug
    toolchain_file: cmake/arm-none-eabi.cmake
    args: [-DPRODUCT_X=ON]
    build: true
  auto_system_includes: true
  output_dir: .ecra
contexts:
  - id: main
    kind: MAIN
    functions: [main]
review:
  enabled: false
  command: [opencode]
```

关键规则如下。

- `include_dirs` 决定“变量定义的所有权范围”；`exclude_dirs` 和 `exclude_files` 优先。范围外源码仍可作为依赖解析调用链，不能据此遗漏用户变量的回调写入。
- `analysis.cmake` 必须与正常固件构建使用相同工具链和 `-D` 选项；CMake 每次完整运行会导出并使用真实数据库。非 CMake 工程应先从 CubeIDE/Make/Keil/IAR 的真实构建导出数据库。
- `contexts` 适合声明无法自动发现的 `MAIN`、`TASK`、`ISR` 或 `CALLBACK` 根；多个任务若复用同一入口函数，必须配置多个不同 id。
- 一个上下文 ID 下的多个入口默认串行，不因入口数量多而自动变成重入；确实可并发重入时显式设置 `reentrant: true`。不同 IRQ 或任务实例不能为了减少告警合并为同一 ID。
- `call_edges` 仅用于补充已经确认但 Clang 无法恢复的真实运行调用边，不能把“注册回调”误写成同步调用。
- `preemption` 与 `concurrency` 保存已知调度关系作为复核证据，当前版本不会仅据优先级数字排除候选。
- `resources`、`protection`、`known_safe` 是工程注释和证据，不会自动压掉风险。

### 4.1 分层中断/回调注册

STM32 大型工程常见 `IRQHandler → HAL 分发 → BSP 回调表 → 业务回调`，也可能通过 `NVIC_SetVector` 或自定义 `BSP_Register...` 动态注册入口。ECRA 的处理分三层：

1. 无参数 `*IRQHandler` 和 Cortex-M 异常入口自动作为 ISR 根；`HAL_*_IRQHandler` 不是独立根，而是从真实调用者继承上下文。
2. 跨函数、跨翻译单元的函数指针赋值、参数转交、回调表字段和一部分强转由保守 points-to 求解器恢复为 `INDIRECT_RESOLVED` 边。链路完整时，根上下文会沿每一层分发函数传播到变量访问。
3. 无法从源码恢复“哪个 API 的第几个参数是异步入口”时，用 `entry_registrations` 显式声明 API 语义。该配置创建入口上下文，但不会虚构回调函数之间的同步调用。

例如驱动将第二个参数登记为 ADC 中断回调：

```yaml
entry_registrations:
  - api: BSP_RegisterIrqCallback       # 支持通配模式，如 BSP_*RegisterCallback
    callback_arg: 1                    # 从 0 开始计数
    kind: ISR                           # ISR、TASK 或 CALLBACK
    context_id: adc_irq                # 同一物理 IRQ 的多个回调共用该 id
    may_repeat: false
```

`context_id` 很重要：同一个物理 IRQ 内串行分发的多个回调应该共享一个 id，不能被误判为彼此并发的多个中断。不同硬件 IRQ、不同任务实例则使用不同 id。`may_repeat: true` 仅适用于确实可能在前一次执行未结束前再次进入的入口；任务创建默认保守地可重复，单个中断回调通常应写 `false`。

恢复支持 `Register(&Callback)`、跨文件多层包装传参、`(*slot)()` 调用、结构体指定字段初始化（包括与声明顺序不同的 `.callback = &Handler`），以及可恢复函数地址的 `NVIC_SetVector` 整数强转。它是保守静态目标集合，不是运行时目标唯一性证明。数组索引、动态改写、复杂别名可能扩大目标集合或留下缺口。

注册规则匹配不到 API 时输出 `UNMATCHED_ENTRY_REGISTRATION`，无法恢复回调目标时输出 `UNRESOLVED_REGISTERED_ENTRY`。多个规则覆盖同一调用时保留所有可能入口并输出 `AMBIGUOUS_ENTRY_REGISTRATION`，不会按 YAML 顺序只取最后一条。同一上下文聚合后的重入标记取逻辑或，任何声明的可能重入都不能被后续条目抹掉。

内置识别的 API 包括 FreeRTOS/CMSIS v2 任务创建、FreeRTOS 软件定时器/延后函数，以及 `NVIC_SetVector`。软件定时器和 `xTimerPendFunctionCall*` 归入同一个串行 timer daemon，重复投递不会被误报为多任务并发；但如果该回调也被真实 ISR/任务直接调用，工具会保留不同上下文的竞争。

无法恢复的场景会以 `FUNCTION_ADDRESS`、`INDIRECT_CALL`、`UNRESOLVED_TASK_ENTRY`、`UNRESOLVED_POINTEE` 等缺口进入报告。应补充 `entry_registrations`、`contexts` 或最小 `call_edges`，而不是删除候选或强行标安全。

## 5. 分析流水线与事实模型

```text
真实构建参数
  → 编译数据库/CMake 校验
  → 每个 C/C++ 翻译单元的 libclang AST 提取
  → 完整静态存储期变量清单 + 直接读写/调用/注册/保护事实
  → 跨 TU points-to 与函数指针求解
  → 任务、ISR、DMA 上下文根及调用图传播
  → 变量级冲突筛选 + 覆盖缺口
  → JSON / SQLite / Markdown / 两个离线 HTML
  → （可选）只读逐项复核
```

每一条访问记录都有 `READ`、`WRITE`、`RMW` 或 `ADDRESS_TAKEN`，并包含源码位置、访问函数、变量/字段路径、已恢复上下文和每个上下文的一条最短调用链。调用图保存全部直接边、已恢复间接边和配置边，HTML 只展示最短链以避免递归组合爆炸。

变量身份由 Clang USR 和翻译单元信息确定：`extern` 声明会合并到实际定义；不同文件的同名 `static`、头文件的每个实例、函数内同名静态变量均保留为不同对象。补充扫描未列入数据库的源文件和条件编译分支时只盘点声明，不向当前构建注入假的访问或 ISR 上下文。

DMA 通过已知 HAL API 的缓冲区方向建立硬件读/写上下文；这能发现 CPU/DMA 共享，但不证明生命周期、缓存维护或所有权协议。多核变体由独立汇总工具处理，普通单核报告不会暗示 CM7/CM4 共享内存已经安全。

## 6. 风险判定和“已排查不存在并发风险”

候选至少需要已知或不确定的共享执行关系，且至少一方写入。典型规则包括多上下文、多写者、读改写可交错、旧快照回写、函数 static 重入、结构体一致性、DMA 共享、所有者违反、解析失败和未知入口。

过去版本把“只有一个读点/写点”的对象与真正共享变量一起送去复核。当前版本新增 `SCREENED_NO_CONCURRENCY_RISK`：报告明确标记为“已排查：不存在并发风险”，并记录 `screening_reason`。

进入该状态需要同时满足以下条件：

1. 当前构建下变量定义和相关翻译单元解析成功，且无漏编源文件、未覆盖头文件等影响安全结论的全局缺口；
2. 所有已观察访问都有可追溯的执行上下文；
3. 没有该变量及其上游调用链相关的解析、指针、DMA、取址逃逸或动态入口不确定性；外部可见对象还受未解析外部调用和汇编等缺口约束；
4. 没有任何已有风险规则，且满足以下任一无冲突条件：仅有读取；只有一个读写访问位置、单一上下文且不可重入；或所有读写都在同一个不可重入上下文中。

特别注意：**一个源码写点不等于一个执行者**。两个 IRQ 调用同一个 `Write()` 时，即使只有 `value = 1` 一行，也保留多写者风险；一个读点加一个写点同样不能凭计数排除并发。上游回调取址逃逸的影响沿全部调用边向下传播，即使已知主循环路径同时存在，也不能把被调用函数里的 static 判为安全。未知问题按符号和函数索引，避免逐变量扫描全部未知项；展示最短调用链不限制实际安全检查的传播范围。

阻止安全筛除的原因写入 `screening_blockers`。原本没有候选规则但受到覆盖缺口影响的对象产生 `GS-COVERAGE-INCOMPLETE`；报告保留“无法判断/待复核”，不会删除清单行。非单核模型不会套用单核安全结论。已有风险候选优先于旧的安全标签，防止不一致事实产生错误绿色计数。

这不是“固件永远安全”的断言。无访问证据、汇编访问、未建模 DMA/回调、失败解析、地址逃逸和未知上下文仍保留为 `REVIEW_REQUIRED` 或覆盖缺口，绝不因为读写计数小就标为安全。`const` 仍保留为 `CONST_INVENTORY`；未发现线索但不满足上述严格条件的对象显示为“未发现风险线索”，不显示安全。

## 7. 输出、状态与审计

输出均在 `<firmware>/.ecra/`：

| 文件 | 内容 |
|---|---|
| `index.html` | 全量变量、读写上下文、调用链、已筛除无风险项、候选和覆盖缺口。 |
| `opencode_review.html` | 可选复核的确认/疑似/安全/未完成结论。 |
| `inventory/global_static_inventory.{md,json}` | 完整变量台账及静态盘点状态。 |
| `reports/global_static_concurrency.{md,json}` | 风险规则、统计、限制和机器可读摘要。 |
| `reports/unknown_contexts.md` | 动态回调、间接调用、解析失败、DMA 等待补证据项。 |
| `facts.json` / `facts.db` | 所有变量、访问、调用、上下文、注册和保护事实。 |
| `scan_state.json` / `input_manifest.json` | 恢复时校验的配置、实现、源文件和构建参数指纹。 |

HTML 的“已排查：不存在并发风险”计数与 JSON 的 `risk_summary` 共用同一变量级结论；它与 OpenCode 的“已复核安全/误报”不同，前者是严格静态无冲突筛除，后者是对原候选的人工/模型结论。所有输出可离线打开。

返回码：`0` 表示覆盖门槛通过且无未解决候选，`1` 表示流程完成但仍有候选，`2` 表示存在解析/上下文/别名/复核未完成等覆盖问题，`3` 表示配置、依赖或构建致命失败，`130` 表示用户中断。任何 `INCOMPLETE` 都不能用于宣称项目不存在并发问题。

## 8. STM32 裸机大型项目的确认结论

工具适合 STM32 裸机大型项目的“全局/static 变量并发排查第一阶段”，前提是使用目标固件的真实编译数据库、正确的变体宏和完整的自有源码范围。对普通向量入口、HAL 分发链、FreeRTOS/CMSIS v2 任务、常见回调表和 DMA，它能建立可复查的静态证据；新增的 `entry_registrations` 覆盖了层层注册但 API 语义不在标准库中的常见结构。

它不能在没有语义信息时自动猜出自定义注册 API、汇编向量表、运行时写入的回调表、Bootloader 跳转后的入口、外设触发频率、NVIC 优先级分组、PRIMASK/BASEPRI 临界区覆盖或 Cache/双核协议。因此准确性的正确表述是：**已建模、已解析的入口链会被追踪；未建模或无法恢复的链路会明确暴露，不会伪装成安全。**

大型项目接入建议是：先执行 `doctor`，再完成一次 `run`；优先清零解析失败和未知入口；为每类 BSP 注册 API 加一条语义配置；分别扫描 CM7、CM4、Debug/Release 等真实变体；最后针对高风险项在目标板或可控调度测试中验证。这样工具既能减少明显无并发可能变量的噪声，也不会以“静态没有报”替代工程安全论证。

## 9. 实现模块与维护职责

| 模块 | 职责与修改时必须检查的契约 |
|---|---|
| `ecra/config.py` | 模板、严格 YAML 校验、中央项目索引、路径解析、旧配置兼容。新增字段必须同步校验、模板与本文档。 |
| `ecra/cli.py` | 初始化/项目选择、完整流程与分步恢复、输出锁、扫描输入指纹、进度和返回码。失败不能留下可被误用的有效扫描状态。 |
| `ecra/compilation.py` | CMake 配置/增量构建、数据库发现、编译参数清洗、响应文件与标准头文件处理。必须保留实际 CPU/宏/包含路径。 |
| `ecra/extract.py`、`ecra/pointer_extract.py` | Clang AST 事实提取、访问和指针约束。无法建模的表达式应暴露缺口，不猜测唯一目标。 |
| `ecra/points_to.py` | 跨过程保守指针求解、间接调用、入口注册、常见 DMA 参数合同。达到求解限制不是成功。 |
| `ecra/analysis.py` | 翻译单元合并、上下文传播、未知影响传播、风险规则和严格安全筛除。标签必须能追溯到事实。 |
| `ecra/report.py`、`ecra/html_report.py` | 台账、候选、覆盖统计、两个离线页面及交互。按变量去重与按复核项计数不能混用。 |
| `ecra/review.py` | 可选逐项复核、结构化结果校验、重试和恢复。模型未完成或回答缺少证据不能变成安全结论。 |
| `tests/` | 单元、真实 Clang 集成、故障恢复、报告和跨项目接入回归。新增能力必须同时有正例与不会错误筛安全的反例。 |

事实流是单向的：源码和配置形成原始事实，事实形成候选和覆盖缺口，复核消费证据并形成独立结论。不能让模型回答回写原始访问或修改静态风险规则。相同名称的不同 static 对象通过符号身份区分，复核与 HTML 链接也必须保持同一身份。

## 10. 新工程接入策略与故障恢复

1. **选择真实变体。** CMake 新工程自动识别唯一 Arm GCC 工具链；自定义位置用 `init --toolchain-file`。已有数据库可放在根目录、Debug/Release 或嵌套构建目录；出现多个候选时显式选择 `analysis.compile_database`。不同核/变体应使用独立配置和输出目录，通过 `--project ... --config ...` 分别运行（中央索引每个根目录只登记一个默认配置）。
2. **确认变量所有权。** 默认包含整个工程，排除常见第三方和产物目录。工程使用 `User/BSP/Modules` 不需依赖目录名称自动猜测；如果自有代码位于默认排除目录，必须改为精确排除第三方路径。范围外实现仍可保留调用链依赖。
3. **处理构建和解析。** CMake 失败先看构建日志；缺标准头文件应核对真实 Arm GCC 和 `auto_system_includes`；错误芯片/核宏用 `expected_defines` 提前检查。工具不会生成假编译命令掩盖工程不可构建的问题。
4. **处理执行入口。** 常规 IRQ 命名自动识别，HAL 分发沿调用链继承。自定义异步注册补 `entry_registrations`；不明的汇编调用可补经过工程确认的 `call_edges`。不能将同一注册调用误当立即执行回调。
5. **读结论和缺口。** 先看解析/覆盖，再看多上下文共享写入；安全筛除项仍保留完整变量证据。`report` 刷新页面，`status --json` 可供脚本判断恢复状态；配置或源码变化后需完整重扫。

CubeIDE/Make 工程已有 GCC 兼容数据库时可以直接接入。Keil/IAR 专属命令行、工程文件和运行库不能仅改文件扩展名就视为兼容数据库；当前没有通用自动转换器，必须导出并验证 Clang 能准确理解的真实目标参数。复杂 C++、预编译库、链接器别名、自定义汇编向量、运行时改写函数表及 Cache/跨核协议仍需专项建模和外部证据。

`expected_defines: [STM32H747xx, CORE_CM7, APP_RTOS=0]` 支持宏存在性和精确命令行宏值校验。按参数顺序处理 `-D`、`-U` 和后续重定义，`-DNAME` 等价于值 `1`；不注入宏，也不声称求值源码内的宏表达式或验证所有后续 `#undef`。目标宏校验的失败会明确进入诊断，不能把某个变体扫描结果冒充另一个变体。

自动探测系统头文件时，C 运行库目录使用 `-isystem`；同时含 `stddef.h` 与 `stdarg.h` 的 GCC 私有头目录改用 `-idirafter` 后备搜索，避免 GCC 私有 `stdatomic.h` 覆盖运行库的 Clang 兼容实现。显式用户 include 参数不改动，也不注入 `-ffreestanding` 或删除 `_Atomic` 来掩盖错误。编译器内建头与 C 运行库头并非可任意互换，参见 [LLVM 的系统头文件说明](https://clangd.llvm.org/guides/system-headers)及 [Clang 的 stdatomic 实现](https://clang.llvm.org/doxygen/stdatomic_8h_source.html)。特殊或老旧运行库仍可能需要兼容的 Clang 资源头与显式路径配置；有诊断时继续保留解析失败，不能声称已适配所有 GCC/Clang 版本组合。

## 11. 验证标准与设计演进

验收分层而不是用“测试全绿”替代硬件正确性证明：

- **语义层：** 实际 Clang 提取验证跨文件多层回调、取址、指定字段初始化、动态向量；反例验证单写点多 IRQ、缺失翻译单元、逃逸回调和重入声明不会误标安全。
- **接入层：** Cortex-M0/M3/M4/M7 编译参数分别走 `init → run → status → report`，使用带空格路径、自定义业务目录、工具侧配置和无模型模式；检查同名工程隔离与 Debug/Release 冲突。
- **构建层：** 有 Arm GCC/CMake/Ninja 时构建真实 ARM 目标对象并检查 ELF 架构，不把宿主机编译成功当成交叉编译成功；另对仓库 F103/H747 固件进行完整构建和扫描。
- **交付层：** JSON/HTML 分类一致、点击安全计数确实筛出安全变量、搜索和证据展开正常、两页面离线脚本不依赖第三方服务；复核的正常、失败、中断与过期结果通过本地可控协议测试。

每次涉及提取/分析实现变化，必须重跑完整扫描，不能仅刷新历史 HTML。本轮可复现命令、实际统计、日志及未完成边界集中保存在[跨项目移植验收记录](portability-validation.md)。未来扩展入口 API 时优先增加最小真实 C 夹具；未经测试的项目形态应写入限制，不宣称“所有 STM32 项目自动准确识别”。
