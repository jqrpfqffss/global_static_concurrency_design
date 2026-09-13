# 基于 Codex 的全局变量与 static 变量并发排查设计方案

> 文档版本：V1.0  
> 编写日期：2026-09-05  
> 适用平台：STM32H747，当前以 Cortex-M7（CM7）单核固件为第一阶段目标  
> 第一阶段范围：外部全局变量、文件级 static 变量、函数级 static 变量  
> 目标：配置一次 .ecra/semantics.yaml，之后在项目根目录执行一条命令，自动生成事实库、并发候选报告和 Codex 复核材料

---

## 1. 方案结论

这个方案可行，但必须准确理解自动化边界：

- Clang 可以较准确地发现全局变量和 static 变量的定义、类型、作用域、读写位置、读改写操作以及函数调用关系。
- semantics.yaml 用来补充运行时语义：哪些函数是中断、任务、主循环、回调或 DMA 上下文。
- 冲突分析引擎可以自动筛选“不同并发上下文访问同一变量”的候选问题。
- Codex 负责回到真实源码，核对控制流、NVIC/FreeRTOS 配置、临界区范围、变量 owner、业务时序和实际影响。
- 工具不能承诺一次性证明所有并发问题都不存在；当编译覆盖率、上下文配置、指针别名或函数指针信息不完整时，必须把结论标记为不完整。

第一阶段采用以下闭环：

~~~mermaid
flowchart TD
    A[semantics.yaml] --> B[一条命令运行器]
    B --> C[Clang 提取变量与访问事实]
    C --> D[SQLite 与规则引擎生成候选]
    D --> E[Codex 回到源码复核]
    E --> F[修复、编译、烧录与回归验证]
~~~

第一阶段先建立可靠的“共享变量清单 + 访问证据链”，后续再扩展 DMA、Cache/MPU、指针别名、函数指针、外设寄存器和底层驱动重入分析。

---

## 2. 第一阶段目标与非目标

### 2.1 必须实现的目标

| 编号  | 目标           | 具体要求                                           |
| --- | ------------ | ---------------------------------------------- |
| G1  | 自动发现变量       | 不要求用户逐个把变量写进 YAML；自动发现所有全局变量和 static 变量        |
| G2  | 区分 static 类型 | 区分文件级 static、函数级 static，不能只按名字识别               |
| G3  | 追踪访问         | 记录定义、声明、读取、写入、读改写、调用函数和源代码位置                   |
| G4  | 追踪上下文        | 将函数映射为 ISR、TASK、MAIN、CALLBACK、DMA 等上下文，并沿调用链传播 |
| G5  | 识别交错         | 判断 ISR↔任务、任务↔任务、ISR↔ISR、DMA↔CPU 是否可能交错         |
| G6  | 输出证据         | 每条候选包含变量、访问函数、源代码行号、访问类型、调用链和判定依据              |
| G7  | 单命令运行        | 只配置项目根目录的 .ecra/semantics.yaml，日常扫描只执行一条命令     |
| G8  | 持续使用         | 每次提交后可重复运行；函数命名或调度改变时只更新 YAML                  |
| G9  | 结果可审计        | 输出解析覆盖率、未知上下文、无法解析函数、分析版本和工程版本                 |
| G10 | 支持 Codex     | 同时生成 Markdown、JSON 和 SQLite，便于人读和工具读取          |

### 2.2 第一阶段暂不承诺完全自动判断的内容

以下内容可以生成“需要复核”项，但不能只靠第一阶段规则直接下结论：

- 通过任意指针、联合体、汇编或复杂宏产生的别名访问；
- 函数指针、回调表、链接脚本或启动代码间接建立的调用关系；
- 运行时动态决定的 DMA Buffer 地址和所有权；
- 只能在特定硬件报文顺序下触发的业务逻辑问题；
- 无法从源码和配置中确定的 NVIC 优先级、BASEPRI 屏蔽范围和 RTOS 调度条件；
- 多核 CM4 与 CM7 之间的共享内存并发。当前 CM4 关闭，第一阶段按 CM7 单核处理；以后启用 CM4 时必须重新建模。

---

## 3. 为什么要单独排查全局变量和 static 变量

嵌入式 C 工程中的很多并发问题，本质是多个执行上下文通过同一个长期存在的变量传递状态。

### 3.1 三类变量必须区分

~~~c
/* 1. 外部链接的全局变量：多个源文件可能通过 extern 使用 */
volatile uint32_t g_data_ready;

/* 2. 文件级 static：只在当前 .c 文件可见，但可由本文件多个函数共享 */
static uint16_t s_frame_length;

void Parser_Reset(void)
{
    s_frame_length = 0U;
}

void Parser_PushByte(uint8_t byte)
{
    s_frame_length++;
}

/* 3. 函数级 static：函数内可见，但整个程序生命周期只有一份 */
bool ParseByte(uint8_t byte)
{
    static uint8_t state;
    state = DecodeState(state, byte);
    return state == FRAME_DONE;
}
~~~

| 类型 | 作用域 | 生命周期 | 典型风险 |
|---|---|---|---|
| 外部全局变量 | 整个程序，可能跨文件 | 整个程序 | ISR、任务、主循环和多个模块同时读写 |
| 文件级 static | 当前源文件 | 整个程序 | 本文件多个入口共享；一个入口在 ISR，另一个入口在任务 |
| 函数级 static | 单个函数内部 | 整个程序 | 函数被 ISR 和任务调用时，内部状态交错覆盖 |
| static 函数 | 当前源文件 | 函数代码本身 | 不是共享变量，但会影响调用链和上下文传播 |

### 3.2 volatile 不能解决并发问题

volatile 主要告诉编译器：每次访问都要产生真实的内存读写，不能随意缓存或删除访问。它不能保证：

- 多个上下文访问的顺序符合业务预期；
- 读、修改、写是一个不可打断的整体；
- 结构体多个字段同时一致；
- DMA 与 CPU 看到的是同一份最新数据；
- 函数内部的 static 状态可重入。

例如：

~~~c
volatile uint32_t g_count;

/* 语义上包含：读取 → 加 1 → 写回 */
g_count = g_count + 1U;
~~~

如果中断在读取和写回之间修改 g_count，后一次写回可能覆盖前一次更新。

### 3.3 原子单次访问不等于业务无竞态

在 Cortex-M7 上，满足对齐和访问宽度条件的某些 32 位单次读写通常可以由单条指令完成，但这只解决“是否撕裂”的一部分问题，不解决：

- 旧值覆盖新值；
- 多字段状态不一致；
- 读改写被打断；
- 一个变量由多个上下文拥有；
- 事件丢失或重复消费。

因此工具应分别输出：

1. 访问是否可能交错；
2. 访问是否可能撕裂；
3. 访问是否存在读改写窗口；
4. 是否存在明确的 owner 和保护协议。

---

## 4. 总体使用方式：一次配置，日常一条命令

### 4.1 项目目录约定

~~~text
D:/project/mfc/
├─ Core/
├─ Drivers/
├─ Middlewares/
├─ App/
├─ CMakeLists.txt 或已有构建工程
└─ .ecra/
   └─ semantics.yaml       ← 用户维护的核心配置
~~~

工具输出目录建议固定在项目根目录下：

~~~text
D:/project/mfc/.ecra/
├─ semantics.yaml
├─ compile_commands.json
├─ facts.db
├─ facts.json
├─ doctor.json
├─ run.json
├─ run.log
├─ inventory/
│  ├─ global_static_inventory.md
│  └─ global_static_inventory.json
├─ reports/
│  ├─ global_static_concurrency.md
│  ├─ global_static_concurrency.json
│  └─ unknown_contexts.md
└─ snapshots/
   └─ <timestamp>/
~~~

### 4.2 日常运行命令

不使用虚拟环境，使用系统 Python：

~~~powershell
cd D:/project/mfc
D:/software/python/python.exe D:/tools/ecra-mvp/run_ecra.py
~~~

这条命令自动完成：

1. 以当前目录作为项目根目录；
2. 读取 .ecra/semantics.yaml；
3. 查找已有 compile_commands.json；
4. 找不到时按配置执行 CMake 配置；
5. 调用或构建 Clang facts 提取器；
6. 提取全局变量、static 变量、函数、调用和访问事实；
7. 写入 facts.db 和 facts.json；
8. 运行并发冲突规则；
9. 生成 Markdown、JSON、覆盖率和日志；
10. 返回本次扫描是否具备有效结论的状态。

日常分析不要使用测试夹具 tests/fixtures/facts.json，否则得到的是示例结果而不是当前工程结果。

### 4.3 一条命令的失败门槛

| 情况 | 处理方式 |
|---|---|
| 缺少 .ecra/semantics.yaml | 直接失败，不生成“未发现问题”结论 |
| Clang/LLVM 不可用 | 直接失败，提示修复环境 |
| 编译数据库不存在且 CMake 配置失败 | 直接失败 |
| 部分源文件解析失败 | 生成报告，但标记 INCOMPLETE |
| 上下文未配置 | 生成 UNKNOWN-CONTEXT，不能隐藏 |
| 扫描成功且覆盖率完整 | 生成正式候选报告 |

核心原则：**工具不能把“没有扫描到”伪装成“没有问题”。**

---

## 5. 分析流程总览

| 阶段 | 名称 | 输入 | 输出 |
|---|---|---|---|
| 0 | 环境检查 | Python、CMake、LLVM、工程路径 | doctor.json |
| 1 | 配置加载 | .ecra/semantics.yaml | 标准化配置 |
| 2 | 编译数据库 | CMake 或已有 compile_commands.json | 编译命令集合 |
| 3 | Clang 提取 | 编译命令、源码、头文件、宏 | 原始 facts |
| 4 | 事实归一化 | 原始 facts | facts.db、facts.json |
| 5 | 上下文推导 | 函数事实、YAML、调用图 | 函数→上下文映射 |
| 6 | 并发规则分析 | 变量访问、上下文关系、保护信息 | 候选问题 |
| 7 | 报告生成 | 候选、覆盖率、未知项 | Markdown/JSON |
| 8 | Codex 复核 | 报告、事实库、源码 | 确认结论和修复建议 |
| 9 | 编译与回归 | 修改后的代码、测试、硬件 | 验证证据和闭环状态 |

---

## 6. 阶段 0：环境检查

### 6.1 必须具备的内容

~~~text
项目根目录可访问
.ecra/semantics.yaml 存在
源码扩展名已配置
工程能够生成或已经生成 compile_commands.json
Clang 能够使用工程真实的宏和头文件路径
~~~

### 6.2 doctor.json 示例

~~~json
{
  "project_root": "D:/project/mfc",
  "python": "D:/software/python/python.exe",
  "python_version": "3.10.11",
  "cmake_found": true,
  "clang_found": true,
  "native_extractor_found": true,
  "semantics_found": true,
  "compile_database_found": true,
  "ready_for_scan": true
}
~~~

### 6.3 为什么必须先做 doctor

如果编译数据库缺少以下信息，Clang 可能得到错误事实：

- STM32H747xx 等芯片宏；
- USE_HAL_DRIVER 等功能宏；
- FreeRTOS、EtherCAT、HAL 相关条件编译开关；
- 实际头文件搜索路径；
- 与固件一致的 C 语言标准和编译选项。

例如固件真实编译命令包含：

~~~text
-DSTM32H747xx -DUSE_HAL_DRIVER -DCORE_CM7
~~~

而扫描时没有这些宏，某些中断函数和变量可能被条件编译掉，报告看似正常，实际扫描的不是固件版本。

---

## 7. 阶段 1：semantics.yaml 配置设计

### 7.1 配置原则

semantics.yaml 只配置 Clang 无法可靠推断的运行时语义，不要求用户手工列出全部变量。

必须手工配置的内容主要是：

- 芯片、处理器核和并发模型；
- 工程如何生成编译数据库；
- ISR、任务、主循环和回调入口；
- 中断优先级或可能抢占关系；
- 锁、临界区、DMA 和 Cache API 语义；
- 关键变量的 owner、保护机制或已知安全原因。

工具自动发现的内容主要是：

- 所有外部全局变量；
- 所有文件级 static 变量；
- 所有函数级 static 变量；
- static 函数；
- 变量的定义、声明和引用；
- READ、WRITE、RMW、ADDRESS_TAKEN；
- 直接调用关系；
- 变量所在文件、函数和行号。

### 7.2 推荐完整模板

~~~yaml
version: 1

project:
  chip: STM32H747
  core: CM7
  cm4_enabled: false
  concurrency_model: single_core_preemptive
  native_word_bits: 32
  source_extensions:
    - .c
    - .h
    - .cpp

analysis:
  output_dir: .ecra
  compile_database: auto
  auto_configure_cmake: true
  cmake_build_dir: .ecra/cmake-build
  cmake_generator: MinGW Makefiles
  cmake_build: false
  native_extractor: auto
  auto_build_native: true
  native_build_config: Release
  # cmake_toolchain_file: config/arm-none-eabi.cmake

  cmake_args:
    - -DSTM32H747xx=1
    - -DUSE_HAL_DRIVER=1
    - -DCORE_CM7=1

  variable_scan:
    enabled: true
    kinds:
      - GLOBAL
      - FILE_STATIC
      - LOCAL_STATIC
    include_headers: false
    include_generated_sources: false
    report_const_objects: false
    report_unmatched_accesses: true
    treat_volatile_as_safe: false
    report_all_discovered_variables: true

contexts:
  - id: main
    kind: MAIN
    functions: [main]
    enabled: true
    preemptive: false

  - id: algorithm_isr
    kind: ISR
    functions: [Algorithm_1ms_IRQHandler]
    priority: 0
    enabled: true
    preemptive: true

  - id: tim4_isr
    kind: ISR
    functions: [TIM4_IRQHandler]
    priority: 1
    enabled: true
    preemptive: true

  - id: ecat_isr
    kind: ISR
    patterns:
      - "*ECAT*IRQHandler"
      - "*PDI*IRQHandler"
      - "*ETH*IRQHandler"
    priority: 2
    enabled: true
    preemptive: true

  - id: algorithm_task
    kind: TASK
    patterns:
      - "*Algorithm*Task"
      - "*Algorithm*Thread"
    enabled: true
    preemptive: true

  - id: ecat_task
    kind: TASK
    patterns:
      - "*ECAT*Task"
      - "*Ecat*Task"
    enabled: true
    preemptive: true

  - id: uart_callback
    kind: CALLBACK
    patterns:
      - "HAL_UART_*Callback"
    enabled: true
    preemptive: false

  - id: cm4_disabled
    kind: CORE
    patterns: ["*CM4*"]
    enabled: false
    preemptive: false

preemption:
  - higher: algorithm_isr
    lower: algorithm_task
  - higher: algorithm_isr
    lower: ecat_task
  - higher: tim4_isr
    lower: algorithm_task
  - higher: tim4_isr
    lower: ecat_task
  - higher: ecat_isr
    lower: ecat_task

concurrency:
  - contexts: [algorithm_task, ecat_task]
    relation: may_interleave
    reason: FreeRTOS tasks can be preempted or time-sliced

api_patterns:
  lock_enter:
    - taskENTER_CRITICAL
    - taskENTER_CRITICAL_FROM_ISR
    - portSET_INTERRUPT_MASK_FROM_ISR
    - __disable_irq
    - "xSemaphoreTake*"
    - "osMutexAcquire*"

  lock_exit:
    - taskEXIT_CRITICAL
    - taskEXIT_CRITICAL_FROM_ISR
    - portCLEAR_INTERRUPT_MASK_FROM_ISR
    - __enable_irq
    - "xSemaphoreGive*"
    - "osMutexRelease*"

  dma_start:
    - "HAL_*_Transmit_DMA"
    - "HAL_*_Receive_DMA"
    - "HAL_ADC_Start_DMA"

  dma_stop:
    - "HAL_*_Abort_DMA"
    - "HAL_*_Stop_DMA"

  cache_clean:
    - SCB_CleanDCache_by_Addr
    - SCB_CleanDCache

  cache_invalidate:
    - SCB_InvalidateDCache_by_Addr
    - SCB_InvalidateDCache

resources:
  - name: g_msgSP
    kind: GLOBAL
    owner_context: ecat_isr
    atomic_width: 16
    business_critical: true

  - name: g_mfcInterface.msgSp
    kind: GLOBAL_FIELD
    owner_context: ecat_isr
    atomic_width: 16
    business_critical: true

  - name: s_frame_length
    kind: FILE_STATIC
    owner_context: ecat_task
    atomic_width: 16

  - name: ParseByte::state
    kind: LOCAL_STATIC
    reentrant: false

protection:
  - resource: g_msgSP
    context: ecat_isr
    mechanisms: [none]
    rationale: PDO processing is the single writer by design

  - resource: s_frame_length
    context: ecat_task
    mechanisms:
      - taskENTER_CRITICAL
      - taskEXIT_CRITICAL

known_safe:
  - resource: s_data_ready
    status: reviewed
    reason: single producer ISR, single consumer task; event loss behavior verified
    evidence: docs/concurrency_review/s_data_ready.md
~~~

### 7.3 配置字段说明

#### project

~~~yaml
project:
  chip: STM32H747
  core: CM7
  cm4_enabled: false
~~~

- chip：用于报告和平台规则选择。
- core：当前分析目标是 CM7。
- cm4_enabled: false：当前不分析 CM4 与 CM7 的核间并发，但不能替代对残留 CM4 源文件的排除。
- concurrency_model：单核抢占式模型下，ISR 可以抢占任务；FreeRTOS 任务之间可以交错。
- native_word_bits：用于撕裂风险提示，不能直接作为原子性证明。

如果以后启用 CM4，需要改成：

~~~yaml
cm4_enabled: true
concurrency_model: dual_core_shared_memory
~~~

并增加共享 SRAM、Cache、内存屏障、HSEM 或消息通道配置，不能继续沿用 CM7 单核结论。

#### analysis

如果工程已经有稳定的编译数据库，推荐：

~~~yaml
analysis:
  compile_database: build/compile_commands.json
  auto_configure_cmake: false
~~~

如果工程没有稳定构建目录，再使用：

~~~yaml
analysis:
  compile_database: auto
  auto_configure_cmake: true
  cmake_build_dir: .ecra/cmake-build
~~~

Windows 路径建议使用正斜杠：

~~~yaml
compile_database: D:/project/mfc/build/compile_commands.json
~~~

variable_scan.kinds 是第一阶段扫描边界。即使变量没有写入 resources，只要属于这三类，工具仍必须自动发现并加入清单。

#### contexts

| kind | 含义 | 并发特点 |
|---|---|---|
| ISR | 中断服务函数 | 可能抢占任务或低优先级 ISR |
| TASK | FreeRTOS 或其他 RTOS 任务 | 任务之间可调度、抢占或时间片切换 |
| MAIN | 主循环 | 可能被 ISR 打断 |
| CALLBACK | HAL/驱动/协议回调 | 必须根据调用链确定实际运行上下文 |
| DMA | DMA 硬件访问域 | 可与 CPU 访问同一 Buffer |
| CORE | 处理器核 | CM4/CM7 多核场景使用 |

匹配规则建议按以下顺序实现：

~~~text
functions 精确匹配
    ↓
patterns 通配符匹配
    ↓
regex 正则匹配
    ↓
调用链传播
    ↓
unknown
~~~

具体规则必须放在宽泛规则前面。不要配置 patterns: ["*"]，否则几乎所有函数都会被错误归类。

#### preemption 和 concurrency

preemption 表示优先级方向：

~~~yaml
- higher: tim4_isr
  lower: ecat_task
~~~

含义是 tim4_isr 可能在 ecat_task 执行期间抢占它。

concurrency 用于表达不适合表示成高低优先级的关系，例如两个 FreeRTOS 任务：

~~~yaml
- contexts: [algorithm_task, ecat_task]
  relation: may_interleave
~~~

priority 主要作为证据，显式 preemption 作为分析关系。不能只根据优先级数字盲推完整的屏蔽和抢占结论。

#### resources

resources 是补充变量设计意图的区域，不是完整变量清单。

建议规则：

- 单写者变量配置 owner_context；
- 多写者变量不要随意配置 owner，应配置消息传递、锁或双缓冲设计；
- 关键业务变量配置 business_critical: true；
- 结构体字段使用稳定的资源 ID；
- 不同源文件中同名 file static 必须使用不同 canonical ID；
- 函数级 static 的 ID 至少包含函数名，例如 ParseByte::state。

#### protection

保护配置表达设计意图；工具还必须检查源码是否真正覆盖访问路径，并输出：

| 状态 | 含义 |
|---|---|
| VERIFIED | 找到完整保护区，且覆盖冲突访问 |
| PARTIAL | 某些路径保护，某些路径未保护 |
| DECLARED_ONLY | YAML 声明了保护，但源码无法完成验证 |
| UNKNOWN | 没有找到保护信息 |
| NOT_REQUIRED | 复核确认不需要共享保护，且有证据 |

不能因为 YAML 写了 taskENTER_CRITICAL，就自动消除并发候选。必须核对临界区范围、ISR 屏蔽范围、BASEPRI 阈值、绕过保护的调用路径和异常 return 路径。

## 8. 阶段 2：编译数据库

### 8.1 为什么必须使用 compile_commands.json

Clang 解析 C 工程时需要知道每个源文件原本使用的：

- 头文件路径；
- 宏定义；
- 编译标准；
- 目标架构参数；
- 条件编译开关；
- 预编译头和强制包含头文件。

compile_commands.json 是“每个源文件真实编译命令”的集合，能够让扫描尽量接近固件实际构建。

### 8.2 自动查找顺序

~~~text
<project_root>/compile_commands.json
<project_root>/build/compile_commands.json
<project_root>/out/build/compile_commands.json
<project_root>/cmake-build-debug/compile_commands.json
<project_root>/.ecra/cmake-build/compile_commands.json
~~~

如果发现多个候选，报告必须列出全部路径和选择理由，不能静默选择。

### 8.3 自动生成命令

当 compile_database: auto 且没有现成文件时，工具执行等价操作：

~~~powershell
cmake -S D:/project/mfc -B D:/project/mfc/.ecra/cmake-build -G "MinGW Makefiles" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DSTM32H747xx=1 -DUSE_HAL_DRIVER=1 -DCORE_CM7=1
~~~

如果工程需要 ARM 工具链文件，还要追加：

~~~text
-DCMAKE_TOOLCHAIN_FILE=D:/project/mfc/config/arm-none-eabi.cmake
~~~

### 8.4 编译数据库验收

至少检查：

~~~text
源文件数量 > 0
每条命令的 file 存在或可定位
命令中包含预期芯片宏
命令中包含主要头文件目录
工程核心源文件已覆盖
没有全部指向测试夹具或空工程
~~~

示例结果：

~~~json
{
  "translation_units_total": 428,
  "translation_units_found": 428,
  "translation_units_parsed": 421,
  "translation_units_failed": 7,
  "coverage_percent": 98.36,
  "expected_defines_found": [
    "STM32H747xx",
    "USE_HAL_DRIVER"
  ],
  "status": "INCOMPLETE"
}
~~~

报告顶部必须显示：

~~~text
分析状态：INCOMPLETE
原因：7 个编译单元解析失败
结论限制：不能根据本次报告下“全工程未发现并发问题”的结论
~~~

---

## 9. 阶段 3：Clang 提取器

### 9.1 变量事实

每个目标变量至少记录：

| 字段 | 说明 |
|---|---|
| symbol_id | 稳定的 canonical ID，不能只用变量名 |
| name | 源码中的变量名 |
| qualified_name | 包含命名空间、结构体或函数作用域的名字 |
| kind | GLOBAL、FILE_STATIC、LOCAL_STATIC、GLOBAL_FIELD |
| storage_class | static、extern、普通全局等 |
| linkage | external、internal、none |
| scope | global、file、function、block |
| type | 完整 C 类型 |
| size_bytes | 类型大小，未知时为 null |
| alignment_bytes | 对齐大小，未知时为 null |
| qualifiers | const、volatile 等 |
| definition_file | 变量定义文件 |
| definition_line | 变量定义行 |
| translation_unit | 所属编译单元 |
| initializer | 初始化摘要 |
| is_array | 是否数组 |
| is_struct | 是否结构体或联合体 |
| is_bitfield_container | 是否可能涉及位域读改写 |

### 9.2 变量身份必须正确

~~~c
/* A.c */
int g_count;
static int s_count;

void Foo(void)
{
    static int local_count;
}

static void Helper(void)
{
}
~~~

正确的资源身份应类似：

~~~text
external::g_count
file::A.c::s_count
function::A.c::Foo::local_count
~~~

不能只使用变量名。特别是：

- 不同源文件中的 file static 同名，但不是同一个变量；
- 不同函数中的 local static 同名，但不是同一个变量；
- static 函数不是共享变量，但必须用于调用图和上下文传播。

### 9.3 访问事实

每个访问点至少记录：

| 字段 | 示例 |
|---|---|
| access_id | A_000123 |
| symbol_id | function::protocol.c::ParseByte::state |
| function_id | F_ParseByte |
| access_kind | READ、WRITE、RMW、ADDRESS_TAKEN |
| is_volatile | true/false |
| is_atomic_candidate | 访问宽度和对齐候选，不是安全结论 |
| file | App/ecat.c |
| line | 128 |
| column | 17 |
| source_text | 当前语句摘要 |
| call_depth | 直接访问为 0，间接调用为 1、2… |
| access_path | 上下文入口到当前函数的调用路径 |
| parse_confidence | exact、conservative、unknown |

### 9.4 读取、写入和 RMW

工具至少识别：

~~~c
g_value = 10U;                 /* WRITE */
temp = g_value;                /* READ */
g_value++;                     /* RMW */
g_value += delta;              /* RMW */
g_value = g_value + delta;     /* RMW */
flags |= FLAG_READY;           /* RMW */
g_struct.field = value;        /* 字段 WRITE，可能涉及容器 RMW */
memcpy(&g_buffer, src, len);   /* g_buffer WRITE */
memcpy(dst, &g_buffer, len);   /* g_buffer READ */
UseBuffer(&g_buffer);          /* ADDRESS_TAKEN，需要参数语义复核 */
~~~

对以下指针访问应保守标记：

~~~c
uint32_t *p = GetAddress();
*p = 1U;
~~~

如果无法确定 p 是否指向目标变量，应生成别名不确定项，不能假设不存在访问。

### 9.5 调用关系

Clang 需要输出：

~~~text
caller_function → callee_function
~~~

并保留：

- 直接调用位置；
- 是否为 static 函数；
- 是否为函数指针调用；
- 是否存在递归；
- 是否因宏或条件编译无法解析。

例如：

~~~c
static void UpdateSP(void)
{
    g_msgSP = 0U;
}

void TIM4_IRQHandler(void)
{
    UpdateSP();
}
~~~

即使 UpdateSP 未配置在 YAML 中，也应通过调用图推导：

~~~text
UpdateSP reachable_contexts = { tim4_isr }
~~~

---

## 10. 阶段 4：facts.db 设计

### 10.1 建议的数据表

~~~text
translation_units
  - tu_id
  - source_file
  - compile_command
  - parse_status
  - parse_error

functions
  - function_id
  - name
  - qualified_name
  - file
  - line
  - linkage
  - is_static

variables
  - symbol_id
  - name
  - qualified_name
  - kind
  - storage_class
  - linkage
  - scope
  - type
  - size_bytes
  - alignment_bytes
  - is_const
  - is_volatile
  - definition_file
  - definition_line

accesses
  - access_id
  - symbol_id
  - function_id
  - access_kind
  - is_rmw
  - file
  - line
  - column
  - source_text
  - call_depth
  - parse_confidence

calls
  - caller_function_id
  - callee_function_id
  - file
  - line
  - call_kind

context_bindings
  - function_id
  - context_id
  - binding_source
  - confidence

protection_events
  - function_id
  - event_kind
  - api_name
  - file
  - line
  - nesting_depth

findings
  - finding_id
  - rule_id
  - symbol_id
  - risk_level
  - confidence
  - status
  - evidence_json
~~~

### 10.2 facts.json 示例

对于下面代码：

~~~c
static uint16_t g_msgSP = 0U;

void ECAT_PDO_Process(void)
{
    g_msgSP = 1800U;
}

void ECAT_Task(void)
{
    uint16_t snapshot = g_msgSP;
    if (g_valve_state_changed)
    {
        g_msgSP = snapshot;
    }
}
~~~

facts.json 可以包含：

~~~json
{
  "variables": [
    {
      "symbol_id": "file:App/ecat.c::g_msgSP",
      "name": "g_msgSP",
      "kind": "FILE_STATIC",
      "scope": "file",
      "type": "uint16_t",
      "size_bytes": 2,
      "alignment_bytes": 2,
      "is_volatile": false,
      "definition_file": "App/ecat.c",
      "definition_line": 1
    }
  ],
  "accesses": [
    {
      "access_id": "A001",
      "symbol_id": "file:App/ecat.c::g_msgSP",
      "function": "ECAT_PDO_Process",
      "access_kind": "WRITE",
      "file": "App/ecat.c",
      "line": 6,
      "source_text": "g_msgSP = 1800U;"
    },
    {
      "access_id": "A002",
      "symbol_id": "file:App/ecat.c::g_msgSP",
      "function": "ECAT_Task",
      "access_kind": "READ",
      "file": "App/ecat.c",
      "line": 11,
      "source_text": "uint16_t snapshot = g_msgSP;"
    },
    {
      "access_id": "A003",
      "symbol_id": "file:App/ecat.c::g_msgSP",
      "function": "ECAT_Task",
      "access_kind": "WRITE",
      "is_rmw": true,
      "file": "App/ecat.c",
      "line": 14,
      "source_text": "g_msgSP = snapshot;"
    }
  ]
}
~~~

如果工具不能完整追踪 snapshot 来源，也必须输出旧值覆盖风险，并将证据等级标为 conservative。

---

## 11. 阶段 5：上下文和并发关系推导

### 11.1 入口函数与调用链

上下文推导从 YAML 配置的入口开始：

~~~text
Algorithm_1ms_IRQHandler [ISR]
    ↓ calls
Control_Update
    ↓ calls
UpdateSP
    ↓ accesses
g_msgSP
~~~

访问记录应携带：

~~~text
direct_function = UpdateSP
root_function = Algorithm_1ms_IRQHandler
context = algorithm_isr
call_path = Algorithm_1ms_IRQHandler → Control_Update → UpdateSP
~~~

### 11.2 多上下文函数必须保留集合

~~~c
static void UpdateSP(void)
{
    g_msgSP = g_requested_sp;
}

void TIM4_IRQHandler(void)
{
    UpdateSP();
}

void FlowTask(void *argument)
{
    UpdateSP();
}
~~~

应保存：

~~~json
{
  "function": "UpdateSP",
  "reachable_contexts": ["tim4_isr", "flow_task"],
  "context_confidence": "exact_roots"
}
~~~

函数被多个上下文调用时，内部 static 状态和文件级 static 共享风险要提升。

### 11.3 STM32H747 CM7 单核并发矩阵

| 左侧上下文 | 右侧上下文 | 默认是否可能交错 | 还需要核对 |
|---|---|---:|---|
| ISR | TASK | 是 | 临界区、BASEPRI、目标 ISR 优先级 |
| ISR | MAIN | 是 | 是否关中断、访问是否完整保护 |
| 高优先级 ISR | 低优先级 ISR | 是 | NVIC 优先级分组和中断使能 |
| 同优先级 ISR | 同优先级 ISR | 通常不在执行中嵌套 | pending、退出后顺序、共享外设状态 |
| TASK | TASK | 是，FreeRTOS 下 | 调度点、互斥锁、临界区、优先级 |
| MAIN | MAIN | 否，单线程 | 仍需关注被 ISR 打断 |
| DMA | CPU | 是 | DMA 生命周期、Buffer、D-Cache、内存区域 |
| CM4 | CM7 | 当前否 | cm4_enabled 为 false；启用后重新建模 |

“可能交错”只说明存在分析必要性，不代表每次运行都会发生。

### 11.4 保护对并发关系的影响

~~~c
taskENTER_CRITICAL();
local = g_value;
g_value = local + 1U;
taskEXIT_CRITICAL();
~~~

工具要检查：

1. 任务的读改写是否都在临界区内；
2. 另一个 ISR 是否也受到该临界区屏蔽；
3. 临界区是否存在提前 return 未退出；
4. 是否有其他调用路径绕过保护；
5. ISR 侧是否使用了不适用的 RTOS API。

保护判定至少分为：

~~~text
访问存在冲突
    ↓
是否识别到保护区
    ├─ 没有：UNPROTECTED
    ├─ 部分覆盖：PARTIALLY_PROTECTED
    ├─ 覆盖完整但屏蔽范围未知：PROTECTED_NEEDS_PLATFORM_REVIEW
    └─ 覆盖完整且平台语义已配置：PROTECTED
~~~

## 12. 阶段 6：全局变量和 static 变量冲突规则

规则不能只输出“变量被访问多次”，而应说明具体冲突形态。

### 12.1 规则总表

| 规则 ID | 检查内容 | 典型结果 |
|---|---|---|
| GS-ALL-VARIABLES | 全局和 static 变量清单 | 盘点完整性 |
| GS-MULTI-CONTEXT | 同一变量被多个上下文访问 | ISR 与任务共享状态 |
| GS-MULTI-WRITER | 多个上下文写同一变量 | 所有权不清、后写覆盖先写 |
| GS-RMW-INTERLEAVE | 一个上下文 RMW，另一个上下文可交错写入 | 计数丢失、旧值覆盖 |
| GS-STALE-SNAPSHOT | 先读入局部快照，随后跨调用或等待后使用 | 使用旧值下发硬件 |
| GS-TEAR-RISK | 访问宽度、对齐或结构体不满足单次访问条件 | 读取到半更新数据 |
| GS-STRUCT-INCONSISTENT | 多字段状态由不同上下文分别更新 | 状态组合不一致 |
| GS-LOCAL-STATIC-REENTRANT | 函数级 static 被多个上下文经由同一函数访问 | 解析状态被破坏 |
| GS-FILE-STATIC-SHARED | 文件级 static 被不同入口访问 | 模块内部隐式共享 |
| GS-OWNER-VIOLATION | 非 owner 上下文写入 owner 变量 | 设计约束被破坏 |
| GS-UNKNOWN-CONTEXT | 访问函数没有可靠上下文 | 不能完整判断并发 |
| GS-INDIRECT-ACCESS | 指针或函数指针无法精确归属 | 需要 Codex 复核 |
| GS-CONST-EXEMPT | 只读常量或只读表 | 可过滤候选，但保留盘点 |

### 12.2 多上下文访问

最小判定条件：

~~~text
同一 symbol_id
被上下文 A 访问
被上下文 B 访问
A ≠ B
A 与 B 可能交错
~~~

例如：

~~~text
g_alarm_state
  - Alarm_IRQHandler: WRITE
  - AlarmTask: READ
~~~

至少生成 GS-MULTI-CONTEXT。

单写者 ISR + 单读者任务不应直接判为确定 Bug，而应标记为需要复核，重点核对状态协议、事件丢失容忍度和内存可见性。

### 12.3 多写者

~~~text
变量 g_msgSP
  - ECAT_PDO_Process: WRITE
  - ECAT_Task: WRITE
~~~

至少核对：

- 两个写者是否可能在同一时间窗口交错；
- 谁是最终 owner；
- 是否有明确覆盖规则；
- 后写入是否可能覆盖先写入；
- 是否要求“阀状态变化后下一个周期才更新 SP”等时序；
- 是否存在“先读旧值、被抢占更新、恢复后写旧值”的窗口。

### 12.4 读改写

下面形式优先级较高：

~~~c
g_count++;
g_count += delta;
g_flags |= FLAG_READY;
g_state = g_state + 1U;
~~~

即使 g_count 是对齐的 32 位变量，只要存在两个可交错上下文同时执行，仍可能丢失更新。

### 12.5 旧快照使用

~~~c
uint16_t snapshot = g_msgSP;

DoSomethingThatMayBeInterrupted();

ApplySetPoint(snapshot);
~~~

工具应把 snapshot 与 g_msgSP 建立数据流关系，至少生成 GS-STALE-SNAPSHOT。

如果中间是函数调用，不能默认它“很快”或“不会被抢占”，应根据上下文和保护区判断。

### 12.6 函数级 static 重入

~~~c
static bool DecodeFrame(const uint8_t *data, uint16_t len)
{
    static uint8_t state;
    static uint16_t index;

    state = DecodeState(state, data[index]);
    index++;
    return state == FRAME_DONE;
}

void UartTask(void *argument)
{
    DecodeFrame(rx_buffer, rx_length);
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    DecodeFrame(rx_buffer, rx_length);
}
~~~

如果回调和任务可能交错，应输出：

~~~text
规则：GS-LOCAL-STATIC-REENTRANT
函数：DecodeFrame
共享状态：DecodeFrame::state、DecodeFrame::index
上下文：uart_callback、uart_task
风险：一次解析过程可能被另一入口覆盖
~~~

### 12.7 文件级 static 共享

~~~c
static uint8_t s_tx_buffer[128];
static uint16_t s_tx_length;

void ProtocolTask(void *argument)
{
    BuildFrame(s_tx_buffer, &s_tx_length);
}

void DMA_TxComplete_IRQHandler(void)
{
    s_tx_length = 0U;
}
~~~

虽然 s_tx_length 只能在当前 .c 文件访问，但 ProtocolTask 和 DMA_TxComplete_IRQHandler 仍可能并发。文件级 static 不是天然安全，只是限制了链接可见性。

---

## 13. 实际示例一：ECAT/SP 旧值覆盖并发问题

### 13.1 示例代码

下面示例模拟“ECAT PDO 更新 SP”和“ECAT 任务使用旧快照”的问题：

~~~c
static uint16_t g_msgSP = 0U;
static bool g_valve_state_changed;

/* 配置为 ecat_isr 或真实 PDO 处理上下文 */
void ECAT_PDO_Process(void)
{
    g_msgSP = 1800U;
}

/* 配置为 ecat_task */
void ECAT_Task(void)
{
    uint16_t snapshot = g_msgSP;

    if (g_valve_state_changed)
    {
        /* 代表任务恢复后仍使用旧快照 */
        g_msgSP = snapshot;
    }
}
~~~

### 13.2 配置片段

~~~yaml
contexts:
  - id: ecat_isr
    kind: ISR
    functions: [ECAT_PDO_Process]
    priority: 2

  - id: ecat_task
    kind: TASK
    functions: [ECAT_Task]

preemption:
  - higher: ecat_isr
    lower: ecat_task

resources:
  - name: g_msgSP
    kind: FILE_STATIC
    owner_context: ecat_isr
~~~

### 13.3 工具提取事实

~~~text
变量：g_msgSP
类型：uint16_t
类别：FILE_STATIC
定义：ecat.c:1

访问 1：ECAT_PDO_Process，WRITE，ecat.c:7
访问 2：ECAT_Task，READ，ecat.c:12
访问 3：ECAT_Task，WRITE，ecat.c:17

上下文关系：ecat_isr 可以抢占 ecat_task
owner：ecat_isr
非 owner 写入：ECAT_Task
~~~

### 13.4 报告候选

~~~text
Finding ID: GS-0001
Rule: GS-MULTI-WRITER、GS-STALE-SNAPSHOT、GS-OWNER-VIOLATION
Risk: HIGH
Confidence: HIGH

Resource:
  name: g_msgSP
  kind: FILE_STATIC
  definition: App/ecat.c:1

Conflicting contexts:
  ecat_isr  -> ECAT_PDO_Process -> WRITE at App/ecat.c:7
  ecat_task -> ECAT_Task        -> READ  at App/ecat.c:12
  ecat_task -> ECAT_Task        -> WRITE at App/ecat.c:17

Reason:
  ecat_task 先读取 g_msgSP 到 snapshot；
  ecat_isr 可在任务执行期间写入 1800；
  任务恢复后仍可能使用旧 snapshot 写回，覆盖最新值。

Protection:
  未识别到覆盖完整读-改-写路径的共同保护机制。

Required Codex review:
  核对 ECAT_Task 的真实运行上下文、PDO 到达顺序、NVIC 优先级、
  g_msgSP 的最终 owner 和实际业务时序。
~~~

### 13.5 可能的运行时序

| 时刻 | 执行上下文 | 动作 | 变量结果 |
|---|---|---|---|
| T0 | ecat_task | snapshot = g_msgSP | snapshot=0，g_msgSP=0 |
| T1 | ecat_isr | g_msgSP = 1800 | g_msgSP=1800 |
| T2 | ecat_task | 中断返回，继续使用 snapshot | snapshot 仍为 0 |
| T3 | ecat_task | g_msgSP = snapshot | g_msgSP 被覆盖为 0 |

这就是静态报告需要交给 Codex 复核的可交错时序，而不是工具凭变量名猜出的结论。

### 13.6 修复方向

修复不能只给变量增加 volatile。常见方案如下。

#### 方案 A：单一写者

如果设计要求 PDO 流程是 SP 唯一写者：

~~~c
static volatile uint16_t g_msgSP;

void ECAT_PDO_Process(void)
{
    g_msgSP = 1800U;
}

void ECAT_Task(void)
{
    /* 任务只读取，不再写 g_msgSP */
    uint16_t sp = g_msgSP;
    ApplySetPoint(sp);
}
~~~

#### 方案 B：消息交接

如果任务必须产生目标值，不让两个上下文共同写最终输出变量：

~~~c
static volatile uint16_t s_pdo_requested_sp;
static uint16_t s_applied_sp;

void ECAT_PDO_Process(void)
{
    s_pdo_requested_sp = 1800U;
}

void ECAT_Task(void)
{
    uint16_t requested_sp = s_pdo_requested_sp;

    /* 最终硬件输出由唯一 owner 负责 */
    s_applied_sp = requested_sp;
    ApplySetPoint(s_applied_sp);
}
~~~

如果请求由多个字段组成，应使用临界区、队列、序号或双缓冲保证整个消息一致性，不能只保护其中一个字段。

### 13.7 修复验收

Codex 必须检查：

~~~text
g_msgSP 的写入点是否从多个上下文减少为单一 owner
是否仍有宏、函数指针或结构体字段绕过检查
阀状态变化和 SP 下发时序是否符合需求
是否引入旧值读取、重复应用或丢请求问题
编译器优化级别下是否仍正确
~~~

如需白盒验证，可在读取后、写入前插入测试延时，确认不会再出现“SP=1800 但实际输出为 0”。

---

## 14. 实际示例二：函数级 static 解析状态重入

### 14.1 问题代码

~~~c
static bool ParseByte(uint8_t byte)
{
    static uint8_t state = WAIT_HEADER;
    static uint16_t length = 0U;

    if (state == WAIT_HEADER && byte == FRAME_HEADER)
    {
        state = RECEIVING;
        length = 0U;
    }
    else if (state == RECEIVING)
    {
        length++;
    }

    return state == FRAME_DONE;
}

void UartTask(void *argument)
{
    ParseByte(ReadTaskByte());
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    ParseByte(ReadInterruptByte());
}
~~~

### 14.2 静态事实

~~~text
function::protocol.c::ParseByte::state
function::protocol.c::ParseByte::length

state:
  kind: LOCAL_STATIC
  READ/WRITE: ParseByte

length:
  kind: LOCAL_STATIC
  READ/WRITE: ParseByte

ParseByte 的调用入口：
  UartTask                -> task
  HAL_UART_RxCpltCallback -> callback/ISR
~~~

### 14.3 工具结论

~~~text
GS-LOCAL-STATIC-REENTRANT
风险：HIGH
原因：同一个函数级 static 状态被任务和回调共享
影响：解析状态、长度和帧边界可能被另一入口修改
~~~

### 14.4 修复方向

优先将状态移到显式上下文对象：

~~~c
typedef struct
{
    uint8_t state;
    uint16_t length;
} ParserContext;

static bool ParseByte(ParserContext *ctx, uint8_t byte)
{
    if (ctx->state == WAIT_HEADER && byte == FRAME_HEADER)
    {
        ctx->state = RECEIVING;
        ctx->length = 0U;
    }
    else if (ctx->state == RECEIVING)
    {
        ctx->length++;
    }

    return ctx->state == FRAME_DONE;
}

static ParserContext s_task_parser;
static ParserContext s_irq_parser;
~~~

如果业务必须共享同一解析状态，应明确只有一个 owner，通过队列把字节交给 owner 处理，不能让两个入口同时调用非重入解析函数。

---

## 15. 实际示例三：单标志位需要复核

~~~c
static volatile bool s_data_ready;

void ADC_IRQHandler(void)
{
    s_data_ready = true;
}

void MeasureTask(void *argument)
{
    if (s_data_ready)
    {
        s_data_ready = false;
        ProcessSample();
    }
}
~~~

工具不能直接判为安全，也不能直接判为确定 Bug，应输出：

~~~text
共享变量：s_data_ready
访问：ISR WRITE，TASK READ/WRITE
候选：GS-MULTI-CONTEXT

风险点：
  1. 多次中断是否允许合并为一次处理；
  2. 任务清零和 ISR 置位的先后是否会丢事件；
  3. ProcessSample 是否会再次被打断；
  4. 是否需要计数器、队列或通知机制。

结论：需要结合业务对事件丢失的容忍度复核。
~~~

如果确实只需要表示“至少有一次数据待处理”，且丢失中间次数符合设计，Codex 可以标记 REVIEWED_SAFE，但必须记录业务依据。

## 16. 阶段 7：报告设计

### 16.1 输出文件

~~~text
.ecra/inventory/global_static_inventory.md
.ecra/inventory/global_static_inventory.json
.ecra/reports/global_static_concurrency.md
.ecra/reports/global_static_concurrency.json
.ecra/reports/unknown_contexts.md
.ecra/doctor.json
.ecra/run.json
.ecra/run.log
~~~

### 16.2 变量清单报告

清单必须包含所有扫描到的变量，即使它们没有并发候选：

| ID | 名称 | 类型 | 类别 | 定义位置 | 访问上下文 | 读 | 写 | RMW | 风险状态 |
|---|---|---|---|---|---|---:|---:|---:|---|
| S001 | g_msgSP | uint16_t | FILE_STATIC | ecat.c:1 | ecat_isr, ecat_task | 1 | 2 | 1 | CANDIDATE |
| S002 | s_data_ready | bool | FILE_STATIC | adc.c:3 | adc_isr, measure_task | 1 | 2 | 0 | REVIEW |
| S003 | ParseByte::state | uint8_t | LOCAL_STATIC | protocol.c:2 | uart_callback, uart_task | 2 | 2 | 0 | CANDIDATE |

### 16.3 每条 finding 的固定结构

每条 finding 必须输出：

~~~text
1. 问题摘要
2. 规则 ID、风险等级、置信度
3. 变量定义证据
4. 所有访问点
5. 上下文与调用链
6. 并发或抢占关系
7. 读写顺序和 RMW 证据
8. 保护机制及覆盖状态
9. 可能触发时序
10. 影响分析
11. Codex 复核任务
12. 最小修复方向
13. 验证建议
14. 当前状态和版本信息
~~~

### 16.4 finding 示例

~~~markdown
## GS-0001：g_msgSP 存在多上下文写入和旧快照覆盖风险

- 规则：GS-MULTI-WRITER、GS-STALE-SNAPSHOT、GS-OWNER-VIOLATION
- 风险：HIGH
- 静态置信度：HIGH
- 状态：NEED_CODEX_REVIEW
- 变量：g_msgSP
- 类别：FILE_STATIC
- 定义：App/ecat.c:1

### 访问证据

| 上下文 | 函数 | 操作 | 行号 |
|---|---|---|---:|
| ecat_isr | ECAT_PDO_Process | WRITE | 7 |
| ecat_task | ECAT_Task | READ | 12 |
| ecat_task | ECAT_Task | WRITE(old snapshot) | 17 |

### 判定依据

ecat_task 先读取 g_msgSP 到局部快照，ecat_isr 可以在任务执行期间写入新值，任务恢复后继续使用旧快照写回，存在覆盖最新值的路径。

### 需要 Codex 核对

- ECAT_PDO_Process 的真实运行上下文；
- 真实 PDO 到达顺序和帧间隔；
- g_msgSP 的设计 owner；
- 是否有共同的临界区或消息队列；
- 修复后 SP 更新时序是否符合业务要求。
~~~

### 16.5 报告顶部必须有覆盖率结论

~~~markdown
# 全局变量与 static 变量并发排查报告

- 扫描时间：2026-09-05T...
- 工程版本：<git commit>
- 编译单元：428
- 成功解析：421
- 解析失败：7
- 函数上下文覆盖率：92.4%
- 变量访问上下文未知数：38
- 分析状态：INCOMPLETE

> 本报告可以用于定位候选问题，但由于存在解析失败和未知上下文，
> 不允许据此得出“全工程未发现并发问题”的结论。
~~~

---

## 17. 风险等级与置信度

风险和置信度必须分开，不能混成一个字段。

### 17.1 风险等级

| 等级 | 适用情况 |
|---|---|
| CRITICAL | 可能导致安全相关输出、执行器失控、保护动作失效或严重设备状态错误 |
| HIGH | 多上下文多写者、RMW 旧值覆盖、非重入解析/控制状态、关键 SP/阀控变量冲突 |
| MEDIUM | 共享状态读取不一致、事件标志可能丢失、普通模块 static 状态冲突 |
| LOW | 低影响共享、保护范围尚未完全证明但暂未发现写冲突 |
| INFO | 变量盘点、常量、已复核安全项、未使用变量 |

### 17.2 静态置信度

| 置信度 | 判定依据 |
|---|---|
| HIGH | 变量身份、访问行号、上下文入口和调用链均精确匹配，且未发现有效保护 |
| MEDIUM | 存在宏、封装函数或部分调用链无法展开，但冲突路径合理 |
| LOW | 主要依赖指针别名、函数指针、条件编译或不完整上下文 |
| UNKNOWN | 事实不足，只有盘点信息，不能形成有效冲突判断 |

例如：

~~~text
风险：HIGH
静态置信度：MEDIUM
~~~

表示业务影响可能很大，但仍需 Codex 核对部分事实，不表示问题已百分之百确认。

---

## 18. 阶段 8：Codex 复核

### 18.1 Codex 的职责

Clang 和规则引擎负责“找全、定位、形成候选”；Codex 负责“理解业务、追踪控制流、核对平台语义”。

Codex 不应直接把下面内容当成确认结论：

- 变量名中含有 global、state 或 sp；
- 变量被 ISR 和任务访问就一定是 Bug；
- 变量是 volatile 就一定安全；
- 变量是 32 位就一定无竞态；
- YAML 中写了锁名就一定已经保护；
- 报告没有列出变量就一定没有访问。

### 18.2 给 Codex 的复核提示词

~~~text
你是嵌入式并发问题复核工程师。当前工程是 STM32H747 CM7 固件，CM4 当前关闭，工程可能包含裸机、HAL、FreeRTOS、ISR、回调和 DMA。

请读取并复核：
1. .ecra/reports/global_static_concurrency.md
2. .ecra/reports/global_static_concurrency.json
3. .ecra/inventory/global_static_inventory.md
4. .ecra/facts.db 或 .ecra/facts.json
5. .ecra/semantics.yaml
6. 工程真实源码和编译配置

第一阶段只处理：
- 外部全局变量；
- 文件级 static 变量；
- 函数级 static 变量；
- static 函数导致的调用链和上下文传播。

请逐条复核每一个 finding，禁止把静态候选直接判定为已确认问题。每条 finding 必须输出：

1. finding ID 和变量 canonical ID；
2. 是否能在源码中确认所有访问点；
3. 真实调用链和执行上下文；
4. ISR、任务、主循环、回调之间是否可能交错；
5. 是否存在 RMW、旧快照、结构体多字段不一致或函数级 static 重入；
6. NVIC 优先级、FreeRTOS 调度、BASEPRI/PRIMASK 和临界区的实际证据；
7. 保护机制是 VERIFIED、PARTIAL、DECLARED_ONLY 还是 UNKNOWN；
8. 可能触发的最短时序和业务影响；
9. 结论：CONFIRMED、LIKELY、REVIEWED_SAFE、FALSE_POSITIVE、NEED_MORE_CONTEXT；
10. 最小修复方案，优先明确单一 owner、消息交接、临界区或拆分 static 状态；
11. 修复后的编译、白盒注入、黑盒长跑和回归验证方法。

要求：
- 所有结论必须引用真实文件和行号；
- 不因为 volatile、32 位访问或已有函数名就判定安全；
- 不擅自修改源码；先生成 .ecra/reports/codex_global_static_review.md；
- 对不完整调用链、指针别名、函数指针和解析失败项单独列出；
- 如果存在高风险问题，再生成 .ecra/reports/codex_patch_plan.md，给出最小改动范围、影响文件和验证清单。
~~~

### 18.3 单条 finding 的复核顺序

~~~text
读取报告摘要
  ↓
定位变量定义与所有访问点
  ↓
查询 facts.db 的调用边
  ↓
回到源码确认真实调用路径
  ↓
读取 NVIC、RTOS、临界区和编译宏配置
  ↓
判断是否存在实际交错窗口
  ↓
构造最短触发时序
  ↓
检查业务影响
  ↓
给出结论和最小修复方向
~~~

### 18.4 Codex 复核结果示例

~~~markdown
## GS-0001 复核结论

- 结论：CONFIRMED
- 置信度：HIGH
- 业务影响：设置 SP 后 ECS 回读正常，但实际执行值可能被旧值覆盖
- 触发条件：阀状态报文先到，SP 报文后到；任务已读取旧 SP，PDO 在写回前抢占
- 根因：同一目标值由两个上下文写入，且任务使用了可过期快照
- 保护状态：UNKNOWN；未发现覆盖完整读改写路径的共同保护
- 修复方向：取消 ECAT 任务对最终 SP 的写入，PDO 流程作为唯一更新入口；如需跨上下文传递，使用请求变量或队列
- 验证：并发窗口插入 1 ms 延时，连续执行 45000 次，确认不会再出现 SP=1800 而实际输出约为 0
~~~

---

## 19. 阶段 9：修复和验证闭环

### 19.1 修复前必须保留证据

第一次发现候选后不要立即大范围重构。先保存：

~~~text
当前 git commit
原始 facts.db
原始 global_static_concurrency.md
Codex 复核报告
触发条件和现场日志
~~~

### 19.2 验证层级

| 层级 | 内容 | 目的 |
|---|---|---|
| L1 | 规则单元测试 | 验证 ++、+=、字段、函数级 static 等规则不漏报 |
| L2 | 事实覆盖率检查 | 验证工程源文件和访问点被完整解析 |
| L3 | 主机侧最小复现 | 验证旧快照、双写者和非重入模型 |
| L4 | 目标板白盒注入 | 在读取后、写入前插入延时或断点，扩大并发窗口 |
| L5 | 目标板黑盒长跑 | 使用真实主站、ECAT、串口和传感器流程 |
| L6 | 回归测试 | 验证正常功能、异常恢复、复位、升级和性能 |

### 19.3 白盒并发窗口注入

~~~c
uint16_t snapshot = g_msgSP;

#if defined(CONCURRENCY_TEST_INJECT)
DelayMs(1U);
#endif

ApplySetPoint(snapshot);
~~~

测试编译时定义：

~~~text
-DCONCURRENCY_TEST_INJECT=1
~~~

延时注入只用于测试，不能合入正式固件。记录必须包含：

- 注入位置；
- 注入持续时间；
- 主站报文顺序；
- 中断和任务优先级；
- 触发次数；
- 变量值时间线；
- 修复前后对比。

### 19.4 最低验收标准

~~~text
1. 能自动列出全部 GLOBAL、FILE_STATIC、LOCAL_STATIC 变量；
2. 同名但不同文件的 file static 不被错误合并；
3. 同名但不同函数的 local static 不被错误合并；
4. 能识别 READ、WRITE、RMW 和至少一层调用传播；
5. 能识别 ISR↔TASK、TASK↔TASK 共享访问候选；
6. 能输出未知上下文和解析失败项；
7. 对 g_msgSP 旧快照覆盖案例生成候选；
8. 对函数级 static 重入案例生成候选；
9. 配置一次 semantics.yaml 后可一条命令运行；
10. 不使用虚拟环境；
11. 解析不完整时不会输出“全工程无问题”；
12. Codex 可以根据报告逐条回到源码复核。
~~~

## 20. Codex 实施任务拆分

下面顺序可以直接交给 Codex 执行。每步都要保留测试结果和变更文件。

### M1：配置和一条命令入口

实现：

- 自动发现 .ecra/semantics.yaml；
- 无参数运行器；
- 自动创建输出目录；
- 使用系统 Python，不依赖虚拟环境；
- 配置缺失时明确失败；
- 生成 doctor.json、run.json、run.log。

验收：

~~~powershell
D:/software/python/python.exe D:/tools/ecra-mvp/run_ecra.py
~~~

可以在测试工程根目录完成一次完整运行。

### M2：变量事实提取

实现：

- 外部全局变量；
- 文件级 static；
- 函数级 static；
- static 函数；
- canonical symbol ID；
- 声明、定义、读写位置；
- 类型、大小、对齐、volatile 和 const；
- 结构体字段、数组和位域容器基础识别。

验收：不同文件、同名变量、同名函数级 static 的 fixture 不得误合并。

### M3：函数和调用图

实现：

- 直接函数调用；
- static 函数调用；
- 多入口共享函数；
- 调用深度；
- 递归检测；
- 函数指针和宏调用的 unknown 标记。

验收：一个普通函数被 ISR 和任务分别调用时，报告能显示两个上下文。

### M4：访问分类和冲突引擎

实现：

- READ、WRITE、RMW；
- 多上下文访问；
- 多写者；
- 旧快照；
- 函数级 static 重入；
- owner 违规；
- 保护覆盖状态；
- unknown context 和间接访问。

验收：

- g_count++ 能识别 RMW；
- ECAT/SP 示例能输出高风险候选；
- ParseByte::state 能输出函数级 static 重入；
- 有保护和无保护 fixture 的报告状态不同。

### M5：报告和 Codex 输入

实现：

- 变量完整清单；
- finding 固定格式；
- Markdown/JSON 双输出；
- 覆盖率门槛；
- unknown context 清单；
- finding 状态和 baseline。

验收：人工只打开 global_static_concurrency.md，就能知道每条候选的变量、访问、上下文、行号和下一步复核动作。

### M6：真实 STM32H747 工程验证

实现：

- 使用真实编译数据库；
- 验证 CM7/CM4 配置；
- 验证 NVIC 优先级和 FreeRTOS 语义；
- 扫描实际工程；
- 统计解析覆盖率和 unknown context；
- 对高风险 finding 进行白盒或黑盒复现。

验收至少完成：

~~~text
doctor → scan → report → Codex review → 修复 → 编译 → 烧录/测试 → 复盘
~~~

---

## 21. 自动化测试 Fixture

工具自身必须带有最小测试工程，不能只在真实项目里试错。

### 21.1 全局变量 fixture

~~~c
volatile uint32_t g_counter;

void Isr(void)
{
    g_counter++;
}

void Task(void)
{
    g_counter++;
}
~~~

预期：

~~~text
GS-MULTI-WRITER
GS-RMW-INTERLEAVE
~~~

### 21.2 文件级 static fixture

~~~c
static uint16_t s_value;

void Isr(void)
{
    s_value = 1U;
}

void Task(void)
{
    s_value = 2U;
}
~~~

预期：

~~~text
变量类别：FILE_STATIC
规则：GS-MULTI-WRITER
~~~

### 21.3 函数级 static fixture

~~~c
static void Update(void)
{
    static uint8_t state;
    state++;
}

void Isr(void)  { Update(); }
void Task(void) { Update(); }
~~~

预期：

~~~text
变量 ID：Update::state
规则：GS-LOCAL-STATIC-REENTRANT
~~~

### 21.4 受保护 fixture

~~~c
static uint32_t s_value;

void Task(void)
{
    taskENTER_CRITICAL();
    s_value++;
    taskEXIT_CRITICAL();
}
~~~

预期：

~~~text
识别 RMW：是
保护状态：DECLARED 或 PARTIAL，取决于另一个上下文是否也被覆盖
~~~

### 21.5 同名变量 fixture

~~~c
/* a.c */
static int state;

/* b.c */
static int state;
~~~

预期：

~~~text
a.c::state ≠ b.c::state
~~~

这是验证 canonical ID 的必要用例。

---

## 22. 误报、漏报和人工介入

### 22.1 误报处理

发现候选后不要直接删除规则，使用状态管理：

~~~text
NEW
  ↓
NEED_CODEX_REVIEW
  ├─ CONFIRMED
  ├─ LIKELY
  ├─ REVIEWED_SAFE
  ├─ FALSE_POSITIVE
  └─ NEED_MORE_CONTEXT
~~~

只有 REVIEWED_SAFE 或 FALSE_POSITIVE 且有源码证据时，才允许写入 known_safe 或 baseline。

### 22.2 漏报控制

每次报告重点显示：

- 未解析的编译单元；
- 未知上下文函数；
- 间接调用；
- 指针别名；
- 条件编译分支；
- 没有访问者映射的变量；
- DMA/硬件访问未建模项。

建议质量门槛：

~~~text
解析覆盖率 < 100%：报告为 INCOMPLETE
关键函数上下文未知：报告为 SEMANTICS_INCOMPLETE
间接访问占比过高：报告为 ALIAS_LIMITED
~~~

### 22.3 人工介入最小化

人工主要参与：

1. 首次配置真实 ISR、任务和优先级关系；
2. 对高风险候选核对业务时序和硬件影响；
3. 对修复固件进行编译、烧录和目标板验证。

之后每次提交代码，自动步骤完成变量盘点和候选增量分析，人工只看新增、升级或重新打开的 finding。

---

## 23. 性能和持续使用

### 23.1 增量分析

第一版可以全量扫描，确保事实库正确。稳定后增加：

- 根据 Git diff 找受影响源文件；
- 只重新解析变更编译单元；
- 对调用关系受影响的上游函数重新传播上下文；
- 保留上一次 facts.db，生成增量报告。

### 23.2 提交后自动执行

~~~powershell
D:/software/python/python.exe D:/tools/ecra-mvp/run_ecra.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
~~~

建议门槛：

- 新增 CRITICAL/HIGH finding：阻止合入或要求评审；
- 现有 finding 变化：要求 Codex 复核；
- 解析覆盖率下降：阻止产生“通过”结论；
- 只有报告内容变化、没有新增风险：允许继续，但归档报告。

### 23.3 finding 去重

finding ID 不能只依赖行号，因为代码插入后行号会变化。建议使用：

~~~text
hash(rule_id + canonical_symbol_id + context_pair + normalized_access_pattern)
~~~

行号作为证据字段，不能作为问题身份唯一依据。

---

## 24. 与 STM32H747 工程的重点适配

### 24.1 ECAT、TIM4、算法中断和任务

建议将以下入口配置到 contexts：

~~~text
算法 1 ms 中断
TIM4 6 ms 中断
EtherCAT/PDI/ETH 中断
ECAT 协议处理任务
流量控制或算法任务
主循环
~~~

重点检查：

~~~text
SP、阀状态、流量、告警状态、ECAT PDO 缓冲区、任务间消息、定时器状态
~~~

### 24.2 两个地方设置同一变量

以下模式应自动提升风险：

~~~text
一个 ISR 写入 g_msgSP
一个任务也写入 g_msgSP
任务读取旧值后调用函数或等待
ISR 在窗口内更新新值
任务恢复后继续使用旧值
~~~

这类问题不需要多个线程同时运行，单核中断抢占就足以触发。

### 24.3 底层 I2C/SPI 接口的关联检查

虽然第一阶段重点是变量，但底层驱动内部可能存在文件级 static 状态：

~~~c
static I2C_HandleTypeDef *s_current_handle;
static uint8_t s_i2c_buffer[64];
static bool s_i2c_busy;
~~~

如果 ECS 查询和周期任务同时调用读取 PCA9555 的接口，工具至少应把这些静态状态标记为多上下文访问，并要求 Codex 核对：

- 底层接口是否可重入；
- 同一总线一次访问是否完成；
- 是否有 mutex、临界区或 busy 状态保护；
- ISR 中是否调用会阻塞的 I2C/SPI 接口；
- DMA 完成前是否允许复用 Buffer。

第一阶段不直接证明总线协议正确，但能先把隐含共享状态暴露出来。

### 24.4 DMA 和 Cache

~~~c
static uint8_t s_rx_buffer[256];

HAL_UART_Receive_DMA(&huart1, s_rx_buffer, sizeof(s_rx_buffer));
~~~

工具应额外记录：

~~~text
CPU 访问 s_rx_buffer
DMA 可能访问 s_rx_buffer
DMA Start/Complete 生命周期
D-Cache Clean/Invalidate 是否出现
Buffer 是否对齐
Buffer 所在内存区域是否 DMA 可访问
~~~

这类结果单独标记为 DMA_SHARED_REVIEW，不与普通 ISR/任务冲突混为一谈。

---

## 25. 真实边界和最终判断标准

### 25.1 可以自动化得比较好的部分

~~~text
所有全局/static 变量盘点
变量类别区分
读写位置定位
RMW 语法识别
直接调用链传播
ISR/任务共享候选
多写者候选
函数级 static 重入候选
未知上下文和解析覆盖率统计
报告生成和结果归档
~~~

### 25.2 仍需 Codex 或人工确认的部分

~~~text
真实中断是否在该代码路径被使能
FreeRTOS 任务是否同时运行到该代码
临界区实际屏蔽哪些优先级
变量写入的业务优先级和所有权
跨函数快照是否真的会被延迟使用
事件丢失是否被业务允许
指针和函数指针的真实目标
DMA 与 Cache 的实际生命周期
硬件现场是否具备触发条件
~~~

### 25.3 什么时候可以说本轮完成

必须同时满足：

1. 全部目标编译单元解析成功，或失败项已逐项说明；
2. 所有重要入口函数均完成上下文配置；
3. 所有 UNKNOWN-CONTEXT 和间接访问项均有处理结论；
4. 所有 HIGH/CRITICAL 候选完成 Codex 复核；
5. 已确认问题完成修复或形成明确遗留项；
6. 关键问题完成目标板或等价白盒验证；
7. 报告、代码版本和测试证据可以相互对应。

只有满足这些条件，才能对某一版本说：

~~~text
本轮已完成全局变量和 static 变量并发排查；未关闭项、覆盖限制和遗留风险已明确记录。
~~~

不能把下面这句话当作有效结论：

~~~text
工具没有报错，所以代码没有并发问题。
~~~

---

## 26. 最终交付物清单

Codex 完成第一阶段后，应在项目中生成或维护：

~~~text
.ecra/semantics.yaml
.ecra/facts.db
.ecra/facts.json
.ecra/doctor.json
.ecra/run.json
.ecra/run.log
.ecra/inventory/global_static_inventory.md
.ecra/inventory/global_static_inventory.json
.ecra/reports/global_static_concurrency.md
.ecra/reports/global_static_concurrency.json
.ecra/reports/unknown_contexts.md
.ecra/reports/codex_global_static_review.md
.ecra/reports/codex_patch_plan.md       # 存在待修复问题时生成
tests/fixtures/global_static/
docs/concurrency/
~~~

日常使用只保留一条命令：

~~~powershell
D:/software/python/python.exe D:/tools/ecra-mvp/run_ecra.py
~~~

核心设计目标不是让工具替代工程师，而是把人工工作从“全工程盲目找变量、找调用、猜时序”，收敛为“阅读有证据的高风险候选，确认业务语义，并验证修复结果”。
