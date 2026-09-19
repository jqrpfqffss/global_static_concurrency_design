# STM32 裸核并发排查工具——最终需求与设计说明

> **适用范围**：STM32 单核裸机工程，重点排查 global / file-static / function-static 共享状态在主循环、中断、回调、DMA 等异步执行场景下的并发风险。  
> **建设方式**：在现有 `global_static_concurrency_design` / `opencode` 分支 Demo 基础上迭代，不推翻现有架构。  
> **核心原则**：**全量归账、证据驱动、静态先筛、AI 精查、结果可快速人工确认。**

---

## 1. 建设目标

用户完成项目路径、扫描范围、中断入口和少量项目语义配置后，通过一条命令完成：

```bash
py -3.10 run_ecra.py
```

工具自动完成：

1. 发现扫描范围内全部 global、file-static、function-static 变量；
2. 提取每个变量能够静态解析到的 READ / WRITE / RMW / ADDRESS_TAKEN 等访问；
3. 建立函数调用关系，并将访问传播到 MAIN、ISR、Callback 等执行上下文；
4. 分析可证明的中断屏蔽、临界区、执行所有权等并发约束；
5. 将所有变量归类为：
   - `SAFE`：静态证据足够，可在当前扫描边界内排除目标并发风险；
   - `SUSPECT`：存在可成立的并发候选，需要进一步确认；
   - `UNKNOWN`：关键证据缺失，当前无法可靠判断；
6. 默认仅将 `SUSPECT + UNKNOWN` 交给 OpenCode 深度复核；
7. 输出：
   - `index.html`：全量变量总账和静态分析结果；
   - `opencode_review.html`：OpenCode 对重点变量的深度复核结果。

最终目标不是让用户人工查看几千个变量，而是：

> **先通过确定性静态分析排除绝大多数明显安全项，再把人工注意力集中到少量真正可能存在并发问题的变量。**

---

# 2. 设计原则与能力边界

这是整个工具必须首先明确的原则。

静态扫描能够发现很多事实，但不能把“发现某个语句”直接等价为“证明并发安全”。

例如：

```c
__disable_irq();
g_value++;
__enable_irq();
```

静态分析可以比较可靠地发现：

```text
__disable_irq()
g_value RMW
__enable_irq()
```

但要判定为“保护有效”，还必须确认：

```text
保护区是否覆盖完整冲突窗口？
目标 ISR 是否确实受该屏蔽机制影响？
是否存在其他未被屏蔽的异步执行者？
调用链和访问事实是否足够完整？
```

因此整个工具必须将分析结果分成三类能力。

| 类型         | 含义                   | 示例                                      |
| ---------- | -------------------- | --------------------------------------- |
| **直接事实**   | AST/CFG 可以可靠提取       | 变量定义、直接 READ/WRITE、`__disable_irq()` 调用 |
| **静态推导**   | 基于调用图、CFG、上下文、优先级等推导 | MAIN 与 ISR 是否可能交错、PRIMASK 是否覆盖完整 RMW    |
| **候选/待确认** | 发现相关迹象，但不足以证明        | BASEPRI 保护有效性、复杂函数指针、DMA 生命周期、自定义锁      |

**只有证据足够时才允许自动判 `SAFE`。**

---

# 3. 总体处理流程

```text
源码 + compile_commands.json + semantics.yaml
                    │
                    ▼
             Clang/AST 全量扫描
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
     变量事实     访问事实      调用事实
        │           │           │
        └───────────┼───────────┘
                    ▼
             执行上下文传播
       MAIN / ISR / CALLBACK / DMA候选
                    │
                    ▼
              并发关系分析
         抢占 / 串行 / UNKNOWN
                    │
                    ▼
          保护与执行约束分析
                    │
                    ▼
            确定性静态分类器
         ┌──────────┼──────────┐
         ▼          ▼          ▼
       SAFE       SUSPECT    UNKNOWN
         │          │          │
         │          └────┬─────┘
         │               ▼
         │         OpenCode 深度复核
         │               │
         └───────┬───────┘
                 ▼
       index.html / opencode_review.html
```

必须满足：

```text
TOTAL = SAFE + SUSPECT + UNKNOWN
```

任何变量都不能因为未命中规则而从报告中消失。

---

# 4. 全量变量扫描

## 4.1 扫描对象

至少覆盖：

- global 变量；
- file-static；
- function-static；
- 头文件中形成独立实例的 static；
- 当前工程实际使用的 C++ namespace/global/static member（如已有支持则保留）。

普通自动局部变量和参数不进入“共享变量总账”，但必须参与：

- 指针传播；
- alias 分析；
- 地址逃逸；
- READ → MODIFY → WRITE 数据流识别。

同名 static 必须通过：

```text
translation unit
+ scope
+ declaration location
```

形成唯一 `symbol_id`，不能按变量名简单合并。

---

# 5. “全量”必须区分发现覆盖率和语义完整性

原设计中“全部运行期访问”容易造成能力过度承诺。

工具应改为：

> **展示全部已静态解析访问，并显式报告仍可能存在的访问盲区。**

每个变量增加：

```text
analysis_coverage:
    COMPLETE
    PARTIAL
```

以及阻塞原因：

```text
unresolved_alias
function_pointer_target_unknown
inline_asm
external_library
parse_failure
address_escape
dma_lifecycle_unknown
...
```

例如：

```text
g_rxBuffer

已解析：
  READ  app.c:120
  WRITE uart.c:88

覆盖状态：
  PARTIAL

原因：
  地址传入 External_Driver_Start()，
  当前无法确认外部实现是否继续访问该变量。
```

只有在与目标变量相关的证据覆盖足够时，才允许自动进入 `SAFE`。

---

# 6. 每个变量必须记录的事实

至少包括：

```text
symbol_id
name
type
size/alignment
storage_class
definition
declarations

accesses:
    READ
    WRITE
    RMW
    ADDRESS_TAKEN

function
source location
execution context
resolved call paths

protection facts
ownership/execution constraints
unknown evidence
analysis coverage
classification
classification reason
```

需要区分：

```text
direct_access
alias_resolved_access
possible_alias_access
```

其中 `possible_alias_access` 不能作为“已经确定访问”，但必须影响置信度。

---

# 7. 执行上下文与调用链

## 7.1 目标

针对每个变量的每一个**已解析访问点**，尽量回答：

```text
谁访问？
由哪个执行入口进入？
经过哪些函数？
在哪一行访问？
这个入口是否可能与其他入口交错？
```

示例：

```text
MAIN
└─ main
   └─ APP_Loop
      └─ Control_Process
         └─ INF_SetPoint
            └─ g_msgSp READ @ control.c:215
```

```text
TIM4_ISR
└─ TIM4_IRQHandler
   └─ HAL_TIM_IRQHandler
      └─ HAL_TIM_PeriodElapsedCallback
         └─ Control_Update
            └─ g_msgSp WRITE @ control.c:391
```

## 7.2 “调用链完整”的实际定义

不能要求静态工具证明所有理论运行路径。

本工具中的“调用链完整”定义为：

> **所有已经被分析器解析出的入口、调用边和变量访问点，在报告中不得被静默省略。**

必须做到：

1. 不只展示一条最短路径；
2. 不因函数去重而丢失同一函数内多个访问点；
3. 多条链允许折叠，但必须能够展开；
4. 递归调用显示 cycle；
5. 调用边注明来源：
   - `direct`
   - `function_pointer_resolved`
   - `configured_edge`
   - `inferred`
6. 无法恢复的间接调用明确标记：
   - `unresolved_call_edge`
   - 不得伪装成调用链完整。

---

# 8. 执行上下文识别

上下文不能主要依赖函数名猜测，应以“入口 + 调用传播”为主。

支持：

```text
MAIN
ISR
CALLBACK_FROM_ISR
CALLBACK_FROM_MAIN
DMA_ASYNC
UNKNOWN_CONTEXT
```

例如：

```text
HAL_TIM_PeriodElapsedCallback()
```

不能仅因为名称叫 Callback 就单独创建一个线程式上下文。

如果调用链是：

```text
TIM4_IRQHandler
→ HAL_TIM_IRQHandler
→ HAL_TIM_PeriodElapsedCallback
```

则该 Callback 应继承：

```text
TIM4_ISR
```

如果同一函数既能从 MAIN 调用，又能从 ISR 调用，则必须记录多个执行上下文。

---

# 9. 中断抢占关系

## 9.1 MAIN 与 ISR

若没有有效中断屏蔽证据：

```text
ISR 可抢占 MAIN
```

这是 STM32 裸机最常见的并发来源。

## 9.2 ISR 与 ISR

必须结合：

```text
NVIC priority
priority grouping
preemption priority
PRIMASK
BASEPRI
FAULTMASK
动态优先级修改
```

如果优先级无法确定，则：

```text
ISR_A ↔ ISR_B = UNKNOWN_PREEMPTION
```

不能武断判定“会抢占”或“不会抢占”。

应优先解析：

```c
HAL_NVIC_SetPriorityGrouping(...)
HAL_NVIC_SetPriority(...)
NVIC_SetPriority(...)
```

以及项目宏展开后的实际值。

---

# 10. 静态识别的并发保护证据

保护分析必须严格区分：

```text
发现保护操作
≠
证明保护有效
```

## 10.1 PRIMASK / 全局中断屏蔽

重点支持：

```c
__disable_irq();
__enable_irq();

__get_PRIMASK();
__set_PRIMASK();
```

这是第一版最值得做深的保护分析。

分析器应在 CFG 上传播抽象状态：

```text
IRQ_STATE:
    ENABLED
    DISABLED
    UNKNOWN
```

例如：

```c
uint32_t key = __get_PRIMASK();
__disable_irq();

g_value++;

__set_PRIMASK(key);
```

如果能够确认：

- 完整 RMW 位于屏蔽区；
- 候选竞争方均属于 PRIMASK 可屏蔽中断；
- 无其他异步执行者；

则可以形成：

```text
PROTECTION_EFFECTIVE
```

而不是仅仅：

```text
发现 __disable_irq()
```

### 反例

```c
__disable_irq();
tmp = g_value;
__enable_irq();

tmp++;
g_value = tmp;
```

正确结果：

```text
检测到 PRIMASK 保护，
但只覆盖 READ，
未覆盖完整 READ→MODIFY→WRITE 窗口。

PROTECTION_PARTIAL
```

不能判安全。

---

# 11. BASEPRI

静态扫描可以可靠发现：

```c
__set_BASEPRI(...)
__get_BASEPRI()
```

但仅发现 BASEPRI 不等于保护有效。

要证明某 ISR 被屏蔽，还必须得到：

```text
BASEPRI 实际值
目标 IRQ 实际优先级
NVIC priority bits
priority grouping
相关优先级是否运行期改变
```

因此第一版建议使用：

```text
PROTECTION_DETECTED
PROTECTION_EFFECTIVE
PROTECTION_INEFFECTIVE
PROTECTION_UNRESOLVED
```

例如：

```text
BASEPRI = 0x50 已识别

但 TIM4_IRQn 最终抢占优先级无法恢复

=> PROTECTION_UNRESOLVED
=> 进入 SUSPECT/UNKNOWN 或 OpenCode 复核
```

绝不能使用：

```text
函数内发现 BASEPRI
=> 变量安全
```

---

# 12. 自定义临界区

C 语言没有“临界区”这一通用语义。

项目中可能存在：

```c
APP_EnterCritical();
...
APP_ExitCritical();
```

或者：

```c
key = IntLock();
...
IntUnlock(key);
```

因此需要：

```text
CMSIS 内建语义
+
semantics.yaml 项目语义
```

例如：

```yaml
critical_sections:
  - enter: "__disable_irq"
    exit: "__enable_irq"
    type: "primask"

  - enter: "APP_EnterCritical"
    exit: "APP_ExitCritical"
    type: "irq_mask"

  - save: "IntLock"
    restore: "IntUnlock"
    type: "irq_mask"
```

对于未配置的：

```c
APP_Lock();
```

Clang 只能知道它是函数调用，不能凭名称认定它是同步保护。

---

# 13. 原子操作和内存屏障

可扫描：

```text
LDREX / STREX
C/CMSIS atomic API
项目自定义原子封装
DMB / DSB / ISB
```

但必须区分语义：

### 原子操作

原子操作只能证明对应原子操作本身不可被撕裂或具备规定的原子语义。

不能自动推出：

```text
整个业务操作安全
```

### DMB / DSB / ISB

它们属于：

```text
内存顺序 / 指令同步证据
```

**不是互斥保护。**

因此：

```text
发现 DMB
```

绝不能直接降低变量并发风险等级。

---

# 14. 单 Owner 不属于“保护机制”

“单 Owner”应从“保护证据”中移出，单独归为：

# 执行约束 / Ownership 证据

例如：

```text
Single Writer
Single Context
Single Owner
No Address Escape
Non-Reentrant Path
```

这些信息可以由调用图和访问事实推导，但：

```text
只有一个 Writer
≠
没有并发风险
```

例如：

```text
ISR WRITE
MAIN READ
```

依然可能存在一致性、时序或复合数据结构读取问题。

因此 Ownership 只能作为分类依据的一部分，不能单独作为通用安全证明。

---

# 15. DMA 必须作为独立异步执行者处理

DMA 不应简单等价成普通 ISR。

需要区分：

```text
CPU 对 buffer 的访问
DMA Engine 对 buffer 的异步访问
DMA Complete/Error ISR
```

如果能够从项目语义明确得到生命周期：

```text
StartDMA
→ DMA owns buffer
→ CompleteCallback
→ CPU owns buffer
```

可以进一步判断。

如果只能发现：

```c
HAL_DMA_Start(..., g_buffer, ...);
```

但无法证明 DMA 完成前 CPU 是否继续访问，则：

```text
DMA_LIFETIME_UNKNOWN
```

应进入 `UNKNOWN` 或 OpenCode 复核。

不能因为存在 DMA Complete Callback 就自动认为 buffer 生命周期安全。

---

# 16. 保护证据状态模型

建议统一使用：

| 状态            | 含义             |
| ------------- | -------------- |
| `NOT_FOUND`   | 未发现相关保护        |
| `DETECTED`    | 发现保护操作，但未证明有效  |
| `EFFECTIVE`   | 已静态证明覆盖目标冲突    |
| `PARTIAL`     | 仅覆盖部分访问窗口      |
| `INEFFECTIVE` | 已知保护不能阻止目标竞争者  |
| `UNRESOLVED`  | 保护存在，但关键参数无法确认 |

`index.html` 应展示：

```text
保护机制：PRIMASK
状态：PARTIAL

原因：
READ 位于中断屏蔽区，
WRITE 位于恢复中断之后，
完整 RMW 窗口未被覆盖。
```

---

# 17. 静态风险分类

## 17.1 SAFE

UI 推荐显示：

> **静态已判安全（当前扫描证据范围内）**

只有证据充分时才能进入 `SAFE`。

典型情况：

### A. 无运行期访问

变量仅定义或初始化，从未运行期读取/修改。

### B. 真正只读

已解析范围内只有 READ，并且：

- 没有地址逃逸；
- 没有相关外部写入；
- 没有 DMA/汇编/未知别名写入证据。

### C. 单一串行执行上下文

所有访问均由同一个已证明不可重入的执行路径触发，并且不存在其他异步访问者。

### D. 完整有效保护

所有可能冲突访问都被已证明有效的保护机制覆盖。

### 不能单独作为安全理由

以下都不能直接判安全：

```text
volatile
8/16/32 bit 单次访问
“CPU 读写是原子的”
Single Writer
变量名是 flag/state
发现 __disable_irq()
发现锁函数
当前没有复现问题
```

---

# 18. SUSPECT

存在可成立的并发候选，且当前证据不足以排除时进入。

重点规则：

```text
MAIN ↔ ISR READ/WRITE
ISR ↔ ISR
Multi-Writer
RMW
Stale Snapshot
Local Static Reentrant
Cross-context Struct/Buffer Access
Address Escape + Known Concurrent Access
CPU ↔ DMA
```

例如：

```c
snapshot = g_msgSp;

/* ISR may preempt */

g_msgSp = snapshot;
```

同时 ISR：

```c
g_msgSp = new_sp;
```

应生成：

```text
STALE_SNAPSHOT candidate
```

---

# 19. UNKNOWN

`UNKNOWN` 不是默认兜底。

只有缺失信息**真正影响当前变量结论**时使用。

典型原因：

```text
function pointer target unresolved
alias unresolved
relevant translation unit parse failed
address passed to unavailable external library
inline assembly may access variable
execution context unresolved
IRQ priority unresolved and it affects preemption conclusion
DMA lifetime unresolved
custom synchronization semantics unknown
```

必须输出可操作原因。

错误：

```text
上下文未知
```

正确：

```text
g_rxBuffer 地址传入 Driver_StartDMA()。

当前无法判断 DMA 完成前 MAIN 是否继续 WRITE 该 buffer。

需要补充：
Driver_StartDMA() 生命周期或 DMA ownership 语义。
```

---

# 20. UNKNOWN 必须局部传播

必须采用：

> **变量级 / 证据级 UNKNOWN 传播。**

例如：

```text
third_party.c 某函数无法解析
```

如果它与 `g_temperature`：

- 没有调用关系；
- 没有地址逃逸；
- 没有别名传播；
- 不阻断上下文判断；

则不能影响 `g_temperature` 的状态。

禁止：

```text
工程存在未知函数
=> 大量无关变量全部 UNKNOWN
```

---

# 21. `index.html` 设计

`index.html` 定位为：

> **全量变量总账 + 确定性静态分析结果。**

## 21.1 首页概览

至少显示：

```text
扫描变量总数
SAFE
SUSPECT
UNKNOWN

解析成功 TU / 总 TU
解析失败 TU
存在证据缺口的变量数
OpenCode 待复核数

Git Commit
扫描时间
工具版本
配置摘要
```

---

## 21.2 全量变量表

建议：

| 字段 | 内容 |
|---|---|
| 变量 | name + symbol_id |
| 类型 | 类型/大小 |
| 类别 | GLOBAL / FILE_STATIC / LOCAL_STATIC |
| 定义 | file:line |
| 访问 | R/W/RMW 数量 |
| 上下文 | MAIN / ISR / DMA... |
| 覆盖率 | COMPLETE / PARTIAL |
| 分类 | SAFE / SUSPECT / UNKNOWN |
| 主要原因 | 一句话说明 |
| 操作 | 展开详情 |

支持：

```text
变量名
文件
分类
执行上下文
保护状态
覆盖率
风险规则
```

筛选。

---

# 22. 单变量详细信息

每个变量固定展示以下栏目。

## A. 当前结论与依据

例如：

```text
SUSPECT

g_msgSp 同时被 MAIN 和 TIM4_ISR 访问。
TIM4_ISR 可抢占 MAIN。
MAIN 中存在 READ → WRITE 窗口。
未发现能够覆盖完整窗口的有效保护。
```

---

## B. 全部已解析访问点

不能只显示前 N 个。

例如：

```text
control.c:101 READ
control.c:115 READ
control.c:128 WRITE
control.c:151 RMW
```

若存在盲区：

```text
注意：
变量地址传入 External_Process()，
因此访问覆盖率为 PARTIAL。
```

---

## C. 所有已解析调用链

按执行入口分组：

```text
MAIN
main
└─ APP_Loop
   └─ MFC_Process
      └─ g_msgSp READ
```

```text
TIM4_ISR
TIM4_IRQHandler
└─ HAL_TIM_IRQHandler
   └─ MFC_Control
      └─ g_msgSp WRITE
```

若存在无法解析的调用边必须显示。

---

## D. 并发关系

例如：

```text
TIM4_ISR -> MAIN
状态：CAN_PREEMPT

USART_ISR -> TIM4_ISR
状态：UNKNOWN_PREEMPTION
原因：USART IRQ priority 未解析
```

---

## E. 并发保护证据

只放真正属于同步/中断屏蔽的证据：

```text
PRIMASK
BASEPRI
FAULTMASK
配置的 Critical Section
Atomic Operation
```

每项显示：

```text
DETECTED / EFFECTIVE / PARTIAL / INEFFECTIVE / UNRESOLVED
```

不能把 Single Owner 放入此栏目。

---

## F. 执行约束 / Ownership

单独展示：

```text
Single Writer
Single Context
Single Owner
Non-Reentrant
No Address Escape
```

这些是“执行模型证据”，不是互斥保护。

---

## G. 未决信息

只显示真正阻断当前变量结论的证据缺口。

---

# 23. OpenCode 二次复核

OpenCode 默认只处理：

```text
SUSPECT + UNKNOWN
```

静态 `SAFE` 不应全部发送给模型。

但可提供：

```text
--review-safe-sample
```

用于抽样验证静态规则质量。

---

# 24. OpenCode 的职责边界

OpenCode 用于解决：

- 复杂跨函数语义；
- 自定义保护封装；
- 函数指针目标；
- 宏和业务状态组合；
- stale snapshot 真实业务含义；
- DMA ownership；
- 静态规则难以表达的多阶段时序。

OpenCode **不能凭空补齐不存在的事实**。

如果：

```text
外部库源码不可用
硬件行为未知
运行期动态函数指针无约束
```

则最终仍应：

```text
NEED_MORE_CONTEXT
```

而不是为了减少 UNKNOWN 强行给结论。

---

# 25. OpenCode Evidence Packet

每个变量独立形成最小但充分的证据包：

```text
变量定义
全部已解析访问
访问覆盖率
相关函数源码
已解析入口调用链
未解析调用边
执行上下文
IRQ 优先级信息
抢占关系
保护证据及状态
Ownership 证据
候选规则
未知证据
源码 file:line
明确待回答问题
```

禁止仅将静态分类结论发给 OpenCode，让模型反向猜原因。

---

# 26. OpenCode 状态

建议：

```text
CONFIRMED
LIKELY
REVIEWED_SAFE
FALSE_POSITIVE
NEED_MORE_CONTEXT
```

映射：

```text
CONFIRMED
=> 已确认风险

LIKELY
=> 高可信疑似风险

REVIEWED_SAFE / FALSE_POSITIVE
=> 已复核安全

NEED_MORE_CONTEXT
=> 仍无法判断
```

---

# 27. `opencode_review.html`

目标：

> **让 STM32 工程师在很短时间内确认并发是否真实成立，而不是阅读大段 AI 分析。**

每个变量固定显示以下内容。

## 27.1 一句话结论

例如：

```text
确认存在并发风险：

TIM4 中断可以在 MAIN 读取 g_msgSp 后抢占，
写入新值；MAIN 恢复后继续使用旧 snapshot，
最终可能覆盖 ISR 刚写入的数据。
```

---

## 27.2 实际参与者

```text
A：MAIN
main
→ APP_Loop
→ SetPoint_Process

B：TIM4_ISR
TIM4_IRQHandler
→ HAL_TIM_PeriodElapsedCallback
→ ECAT_UpdateSetPoint
```

---

## 27.3 并发发生过程

必须按步骤展示：

| 步骤 | 执行者 | 动作 | g_msgSp |
|---|---|---|---:|
| 1 | MAIN | 读取旧值到 snapshot | 0 |
| 2 | TIM4_ISR | 抢占并写入新值 | 1800 |
| 3 | MAIN | ISR 返回，继续使用 snapshot=0 | 1800 |
| 4 | MAIN | 旧值重新写回 | 0 |

结果：

```text
预期：
ISR 更新后的 1800 保留。

实际可能：
MAIN 将旧值 0 覆盖回去。
```

---

# 28. 安全结论也必须解释

例如：

```text
REVIEWED_SAFE

MAIN 的完整 READ→MODIFY→WRITE 位于 PRIMASK 临界区。

候选竞争方 TIM4_ISR 属于可被 PRIMASK 屏蔽的普通可配置中断。

因此该 ISR 无法插入此 RMW 窗口，
当前候选竞争时序不能成立。
```

而不能只输出：

```text
SAFE
```

---

# 29. `semantics.yaml` 的职责

配置文件不应手工罗列每个变量，而应描述**项目语义**。

建议至少支持：

```yaml
contexts:
  main_entries:
    - main

  isr_entries:
    - TIM4_IRQHandler
    - USART1_IRQHandler

critical_sections:
  - enter: APP_EnterCritical
    exit: APP_ExitCritical
    type: irq_mask

  - save: IntLock
    restore: IntUnlock
    type: irq_mask

atomic_wrappers:
  - Atomic_Set
  - Atomic_Get

dma:
  start_functions:
    - HAL_DMA_Start
  complete_callbacks:
    - HAL_DMA_XferCpltCallback

known_call_edges:
  - caller: Some_Dispatch
    callee: Target_Handler
```

原则：

> 能从源码可靠推导的不要强迫用户配置；只有项目私有语义才进入 `semantics.yaml`。

---

# 30. Demo 回归场景

`examples/stm32_demo` 建议至少覆盖：

| ID  | 场景                            | 期望                       |
| --- | ----------------------------- | ------------------------ |
| D01 | 无运行期访问                        | SAFE                     |
| D02 | 真正只读                          | SAFE                     |
| D03 | 单 MAIN 串行访问                   | SAFE                     |
| D04 | MAIN + ISR READ/WRITE         | SUSPECT                  |
| D05 | MAIN + ISR Multi-Writer       | SUSPECT                  |
| D06 | stale snapshot                | SUSPECT                  |
| D07 | function-static 被 MAIN/ISR 重入 | SUSPECT                  |
| D08 | PRIMASK 完整覆盖 RMW              | SAFE                     |
| D09 | PRIMASK 只覆盖 READ              | SUSPECT                  |
| D10 | BASEPRI 值和 IRQ priority 均可解析  | 验证 EFFECTIVE/INEFFECTIVE |
| D11 | BASEPRI 关键优先级未知               | UNKNOWN/待复核              |
| D12 | function pointer 目标未知且影响变量    | UNKNOWN                  |
| D13 | 未知调用与变量无关                     | 不得污染该变量                  |
| D14 | 地址逃逸到外部库                      | UNKNOWN                  |
| D15 | CPU 与 DMA 生命周期未知              | UNKNOWN                  |
| D16 | 自定义 Critical 已配置              | 正确识别                     |
| D17 | 自定义 Lock 未配置                  | 不得自动当成保护                 |
| D18 | DMB/DSB 存在                    | 不得自动判安全                  |
| D19 | Single Writer + ISR/MAIN READ | 不得仅凭 Single Writer 判安全   |
| D20 | 同函数多处访问                       | HTML 必须全部展示              |

---

# 31. 每个 Demo 的验收层次

每个场景同时检查：

1. AST/facts 是否正确；
2. access classification 是否正确；
3. context propagation 是否正确；
4. call graph 是否正确；
5. protection status 是否正确；
6. SAFE/SUSPECT/UNKNOWN 是否正确；
7. `index.html` 是否与 facts 一致；
8. OpenCode Queue 是否只包含应复核项；
9. `opencode_review.html` 是否能还原实际并发过程。

不能只验证“脚本成功运行”。

---

# 32. P0 验收标准

## 32.1 变量归账

```text
TOTAL = SAFE + SUSPECT + UNKNOWN
```

必须强校验。

## 32.2 已解析访问不丢失

facts 中的每个访问必须能够在报告中追溯。

## 32.3 调用链不静默截断

已解析出的入口和调用边不得因为 UI 摘要被隐藏。

## 32.4 SAFE 必须有证明理由

不能：

```text
规则未命中
=> SAFE
```

## 32.5 保护必须区分“发现”和“有效”

```text
DETECTED != EFFECTIVE
```

这是 P0 要求。

## 32.6 UNKNOWN 必须可解释

每个 UNKNOWN 都要明确：

```text
缺什么证据
为什么影响该变量
需要补充什么
```

## 32.7 UNKNOWN 不得无关扩散

无关解析失败不能污染整个工程。

## 32.8 OpenCode 不能伪造确定性

证据仍不足时允许保留：

```text
NEED_MORE_CONTEXT
```

---

# 33. 工程级质量指标

真实 STM32 工程验证时至少统计：

```text
变量总数
SAFE 数量/占比
SUSPECT 数量
UNKNOWN 数量

UNKNOWN 原因 TopN
解析失败 TU 数量
unresolved call edge 数量
address escape 数量

OpenCode：
CONFIRMED
LIKELY
REVIEWED_SAFE
NEED_MORE_CONTEXT

最终人工需要确认数量
```

重点优化目标是：

> **减少“无价值的人工排查”，而不是人为追求 SAFE 占比。**

宁可保留少量 UNKNOWN，也不能为了报表好看造成错误判安全。

---

# 34. Codex 改造优先级

## 第一阶段：事实层可靠

优先完成：

```text
变量唯一标识
访问不丢失
访问覆盖率
调用链不截断
上下文传播
TOTAL 归账
```

这是整个工具的地基。

---

## 第二阶段：确定性并发模型

完善：

```text
MAIN / ISR
ISR / ISR priority
RMW
Multi-Writer
Stale Snapshot
Local Static Reentrant
```

---

## 第三阶段：保护分析

优先级建议：

### P0

```text
__disable_irq / __enable_irq
PRIMASK save/restore
CFG 范围覆盖
```

### P1

```text
BASEPRI + NVIC priority
自定义 Critical Section
```

### P2

```text
LDREX/STREX
复杂原子封装
DMA ownership
复杂锁语义
```

---

## 第四阶段：UNKNOWN 局部传播

重点解决：

```text
一个未知点
不能让大量无关变量一起 UNKNOWN
```

这是工具能否用于大型工程的关键。

---

## 第五阶段：OpenCode 深度复核

OpenCode 必须建立在结构化 Evidence Packet 上。

优先解决：

```text
复杂语义
自定义同步
函数指针
DMA 生命周期
旧快照业务含义
```

而不是让 AI 代替基础 AST 扫描。

---

# 35. 最终产品形态

用户只需要运行：

```bash
py -3.10 run_ecra.py
```

主要查看：

```text
.ecra/index.html
```

用于：

```text
全部变量总账
静态 SAFE / SUSPECT / UNKNOWN
全部已解析访问
调用链
并发关系
保护状态
Ownership
证据缺口
```

以及：

```text
.ecra/opencode_review.html
```

用于：

```text
重点变量二次复核
真实并发参与者
调用链
抢占条件
逐步执行时序
安全/风险理由
修复建议
验证建议
```

---

# 36. 最终评价标准

工具是否真正实用，最终只看三个问题：

## 1. 是否真正“归账”

所有扫描到的 global/static 都能在总账中找到，不遗漏、不静默丢失。

## 2. 是否能够可靠缩小排查范围

不是简单减少变量数量，而是：

```text
有充分证据的自动排除；
证据不足的保留；
真正值得关注的送去深度分析。
```

## 3. 用户是否能快速确认

点击一个变量后，应快速看清：

```text
变量在哪里？
谁读？
谁写？
从哪个 MAIN/ISR/DMA 入口进入？
调用链是什么？
两个上下文能否交错？
保护是否只是被发现，还是已经证明有效？
并发窗口在哪里？
具体按照什么顺序发生？
最终错误结果是什么？
为什么判风险、安全或 UNKNOWN？
```

只有做到这三点，这个项目才真正从一个静态分析 Demo 变成可用于实际 STM32 裸机项目的并发排查工具。
