# NVIC 优先级恢复与中文复核专项修复

日期：2026-10-19。工作分支：`optimize_cc`。代码修改由 Codex 直接执行；未修改被分析固件的业务源码。

## 根因与原有链路

1. `extract.py` 原来已经保存部分 NVIC 调用的 AST 参数和常量，但参数、局部变量、外设句柄字段以及跨函数调用中的值没有形成可供优先级模型消费的配置结果。
2. `interrupts.priority_model()` 只接受 `main()` 中、首次应用调用和共享访问之前、没有条件祖先的单次配置。`HAL_Init → HAL_InitTick`、`MX_*_Init → HAL_*_Init → HAL_*_MspInit` 等真实路径因此被排除。把宏展开后的原始事件传给复核模型，并不能补上这一步。
3. Packet 原来主要提供 `irq_priority_events`，缺少已求值的优先级、分组解释、配置调用链和有效性边界。复核模型容易把 Packet 的不足误写为源码未配置。
4. 复核协议只检查答案结构、状态和源码位置，未检查自然语言。HTML 与 Markdown 会直接展示英文正文；即使常规解释区经过处理，候选调试区的 `review_result` 仍可能重新嵌入旧英文答案。

## 最终实现

| 层次 | 实现与证据 |
|---|---|
| 源码 → Clang AST | 按真实编译命令提取函数、枚举、字段偏移、参数、常量、当前 MCU 的 `__NVIC_PRIO_BITS`；不按源码正则猜测条件分支 |
| AST → 值流 | `nvic_extract.py` 保存可序列化语义表示；`nvic.py` 解释初始化调用、局部赋值、指针/句柄字段、实参、条件和整数转换 |
| 配置事件 | 保留文件、行号、函数、完整调用链、参数值、已证明的分支、未定条件及初始化/运行期阶段 |
| 优先级模型 | 分开保存源码配置、初始化合流结果、运行期有效性和供抢占证明使用的稳定性；未知调用、间接写、重配置或未建模控制流阻断安全证明 |
| IRQ 关联 | 使用当前构建 IRQn 数值、真实向量表槽位、Handler 和上下文调用路径；同一共享向量保持一个物理执行域；不同 IRQ 共用 Handler 时按各自槽位取优先级，名称歧义不能建立串行证明 |
| Packet | 追加 `nvic_priorities`、`nvic_resolved_events`、`nvic_lifecycle_barriers`、`nvic_recovery` 和 `preemption_relations`，不移除原始事件 |
| OpenCode 核实 | 指明必须沿实际向量、实例、HAL MSP 初始化和重配置路径核对；对与已恢复源码配置直接冲突的“缺失事实”发起独立事实核实，不通过格式修正删改事实 |
| 中文生成与校验 | 协议要求自然语言使用简体中文；逐字段检查长段英文，同时允许 API、代码和内部枚举 |
| 中文修正 | 独立 `LANGUAGE_FIX` 会话禁用工具；必须保留字段结构、列表顺序、状态、布尔值、数值、源码位置和技术标识符，否则拒绝接受 |
| 归档与展示 | 原始答案、提示词、证据包和执行日志保留各自校验值；语言修正绑定原始答案摘要及原始日志。历史英文需重新复核，未经处理不混入当前中文正文，原始归档仍可查看 |

支持 HAL/CMSIS（包括 `__NVIC_*`）优先级、分组及启停 API，标准外设库 `NVIC_InitTypeDef` / `NVIC_Init` / `NVIC_PriorityGroupConfig`，以及有架构地址、字段偏移和 AIRCR 写密钥依据的寄存器配置。`NVIC_Init` 禁用分支只禁用中断，不凭配置结构体中的值伪造一次优先级写入。

优先级换算采用当前有效位数与 `PRIGROUP`：抢占位数为 `min(__NVIC_PRIO_BITS, 7-PRIGROUP)`，其余为子优先级位。子优先级不产生 ISR 嵌套；BASEPRI 使用编码与分组边界核对。PRIMASK/BASEPRI 保护继续按完整访问窗口证明，并补充 FAULTMASK 的窗口证明及 NMI 排除。

## 实际工程与边界工程

当前 `config/semantics.yaml` 指向 `H:/stm32_RAG/code/serial - opencode`，真实构建为 STM32F103C8 串口工程。该构建没有 TIM8/TIM13/TIM16 初始化，不能把其他芯片或测试工程的中断配置冒充其源码事实。

实际工程恢复结果：

| IRQ | 源码抢占/子优先级 | 分组/有效位数 | 配置证据 |
|---|---|---|---|
| `USART2_IRQn` | `0 / 0` | `3 / 4` | `Core/Src/stm32f1xx_hal_msp.c:117`；`main → MX_USART2_UART_Init → HAL_UART_Init → HAL_UART_MspInit` |
| `SysTick_IRQn` | `15 / 0` | `3 / 4` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal.c:245`；分别沿 `HAL_Init → HAL_InitTick` 与时钟配置路径恢复 |

初始化结果中的数值和源码证据与运行期有效性分开保留。运行期还有未完全求解的间接访问及调用条件时，不能仅据初始化数值宣称所有访问窗口均可抢占或均已安全。

定时器边界工程位于 `tests/fixtures/nvic_recovery/`。它使用明确标注的合成 IRQ 布局，不声称这些向量组合属于某一个真实芯片。四个翻译单元经过 Arm GCC 编译及重新扫描；五个定时器对应四个物理 IRQ：

| 物理向量 | 抢占/子优先级 | 调用链与映射 |
|---|---|---|
| `TIM3_IRQHandler` | `3 / 0` | 向量槽位 45 |
| `TIM4_IRQHandler` | `2 / 1` | 向量槽位 46 |
| `TIM8_UP_TIM13_IRQHandler` | `1 / 2` | 槽位 60；TIM8、TIM13 在同一物理 IRQ 中串行分派 |
| `TIM1_UP_TIM16_IRQHandler` | `0 / 3` | 槽位 41 |

分组为 `5`，有效位数为 `4`，抢占/子优先级各占 `2` 位。配置链为 `main → Board_Init → HAL_TIM_Base_Init → HAL_TIM_Base_MspInit → SetIRQ`；中断访问链为向量 → Handler → `HAL_TIM_IRQHandler` → 用户回调 → `Business_Update`。

## 分类与测试约束

加入不同 IRQ 共用 Handler 的回归后，最终全量测试执行 694 项，692 项通过。2 项原有按环境变量启用的 OpenCode 实测测试在默认套件中跳过；本专项另行执行最小工程的实际 OpenCode 复核，不能把这 2 项跳过记录描述为通过。最终日志：`validation/nvic_verified_delivery_tests.log`。

实际批量复核还暴露并修复了一个语言检查误报：`huart->Init.StopBits` 等成员访问表达式不应计入英文词数。此类代码表达式现在按技术标识符处理；既有失败收据保留，后续通过失败项重试接受新的有效结果。

实际工程与修复前快照逐变量比较，静态分类没有变化：49 个参与分类的对象中，`SAFE_PROVEN=26`、`SUSPECT=23`、`UNKNOWN=0`。完整清单为 58 行，其余为父容器及嵌套成员容器。OpenCode 开关、技术失败、缺失条件和语言修正不改变这些静态分类。

新增自动化覆盖直接配置、多层传参、HAL MSP 条件分支、宏与表达式、分组与位数、共享向量、ISR/ISR 与 MAIN/ISR、启停与屏蔽、初始化后重配置、未知配置、Packet 源码证据、错误缺失项挑战、语言修正防篡改、HTML/Markdown 一致性、缓存与历史归档，以及标准外设库禁用分支。

可复现命令：

```powershell
py -3.10 -m unittest discover -s tests
py -3.10 scripts/validate_nvic_fix.py
py -3.10 scripts/validate_nvic_fix.py --live
py -3.10 run_ecra.py --no-review
py -3.10 run_ecra.py review
py -3.10 run_ecra.py report
py -3.10 scripts/audit_nvic_acceptance.py
```

`validate_nvic_fix.py` 默认进行明确标记的协议模拟；`--live` 才调用实际 OpenCode。两种模式都重新编译、提取和扫描，不复用旧 facts。生成的验收记录位于 `validation/nvic_acceptance/acceptance.json`。

`audit_nvic_acceptance.py` 只读取当前实际工程的归档，要求全部目标已有有效答案，逐条验证源码收据、中文字段、已知 NVIC 事实和 Packet，检查两份 HTML、SQLite 和修复前后的静态分类，写出 `validation/nvic_final_audit.json`。未满足条件会失败，不会用未完成的复核生成“通过”记录。

本轮真实工程的最终复核使用临时配置将已有 `review.workers` 设为 `8`，原始配置保持 `1`。此前的串行及 4 路会话与成功/失败调用都保留在归档中。提供商证书失败属于技术失败，重试通过之前不计为验收成功。

浏览器验收使用真实生成的 HTML，检查优先级表展开、共享变量搜索、详情展开、复核页与手机宽度；截图保存在 `output/playwright/`。最终测试日志与真实工程复核统计见 `validation/` 下本轮验收文件及工程 `.ecra/review/queue.json`。

最终产物审计通过，记录为 `validation/nvic_final_audit.json`：

- 实际工程完成 20/20 个编译单元解析，0 个部分解析、0 个解析失败。
- 23/23 个复核目标均为 `DONE`，当前技术失败为 0；原始模型结果为 16 个 `REVIEWED_SAFE`、7 个 `FALSE_POSITIVE`，未通过翻译改变状态。
- 每条收据的原始日志、证据包、源码引用及校验值有效；全部用户说明字段通过中文检查。
- 两份 HTML、Markdown、SQLite 和 Packet 中的 NVIC 事实经过检查；配置值和源码调用链保留完整。
- 修复前后的逐变量静态分类完全相同；未修改被分析固件的业务源码。
- 原始配置中的单路复核及 `report` 命令可以继续使用，最终报告已用原始配置重新生成。

实际工程总体 `analysis_status` / `run_status` 继续保留 `INCOMPLETE`。这是原有指针解引用、间接调用和未确定指向等未知记录所形成的覆盖边界，不是复核目标尚未完成。本次没有删除这些记录或强行把总体状态改成完整，亦不把当前 23 条条件安全/误报答案解释为全固件无风险证明。

## 证据边界

这是一套有限、保守的静态求值。无法证明的动态调用、未知寄存器别名、递归/预算上限、未建模跳转或汇编，以及外部 Bootloader/运行期重配置继续保留为未知。缺少向量表时会明确标记仅有构建枚举和 Handler 约定依据，不补造业务回调来源。

语言修正通过结构与技术锚点检查约束表达，不是自动证明自然语言语义完全等价的定理证明器；原始回答与修正日志可独立审计。未进行目标板烧录和硬件抢占实验，验证建议不计作已执行测试。

## 修改文件

| 文件 | 变更 |
|---|---|
| `ecra/extract.py`、新增 `ecra/nvic_extract.py` | AST 语义、当前构建枚举、全局零初始化及宏常量提取 |
| 新增 `ecra/nvic.py`、`ecra/interrupts.py` | 参数/句柄求值、分组编码、配置生命周期、向量关联与抢占模型 |
| `ecra/analysis.py`、`ecra/points_to.py` | 新事实合并、模型接入和强定义覆盖弱 MSP 实现 |
| `ecra/protection.py` | FAULTMASK 完整窗口证明，保留既有 PRIMASK/BASEPRI 逻辑 |
| `ecra/review.py`、`ecra/review_contract.py`、新增 `ecra/review_language.py` | Packet、源码主动核实、事实冲突挑战、语言检查及修正收据 |
| `ecra/review_presentation.py`、`ecra/html_report.py`、`ecra/report.py` | 中文展示、统一 NVIC 摘要、Markdown 标签、历史原文归档链接 |
| `ecra/workflow.py` | 语言/展示修改不触发静态重扫；新增静态模块仍纳入扫描指纹 |
| `ecra/context_points.py`、`ecra/vectors.py` | 静态分析自然语言说明中文化 |
| 新增 `tests/test_nvic_recovery.py`、`tests/test_review_language.py`、`tests/fixtures/nvic_recovery/` | 31 项新增回归与可编译多文件边界工程 |
| `tests/review_fixtures.py` 及相关既有复核测试 | 模拟合法结果改用中文；保留英文解析兼容性，新增原始证据不变检查 |
| `scripts/validate_nvic_fix.py`、`scripts/audit_nvic_acceptance.py` | 真实生成产物的可复现验收 |
