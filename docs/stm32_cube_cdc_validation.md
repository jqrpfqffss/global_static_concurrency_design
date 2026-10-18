# STM32CubeF4 裸机实工程与深层并发复核验证

验证日期：2026-10-18。模型与构建的逐项记录见
[机器可读结果](stm32_cube_cdc_validation_results.json)，可重复执行的场景与说明见
[用例目录](../tests/fixtures/stm32_cdc/README.md)。

首轮实际结果为 18/20，13 个风险场景全部识别，但有安全样本误报和不确定性过度确认。
优化后四项定向复测为 4/4；额外重复验证受提供商余额限制中止，不能宣称最终全矩阵稳定通过。
工程构建、模型事件、独立预期与失败记录均已保留，没有目标板烧录验证。

## 工程选择与证据边界

选择 ST 官方维护的 [STM32CubeF4](https://github.com/STMicroelectronics/STM32CubeF4)，
固定 v1.28.3 / `94cae6e83f00e276a11957e7833c01ac3d0bd7af`，使用
`Projects/STM324xG_EVAL/Applications/USB_Device/CDC_Standalone`。
这是 STM32F407IG Cortex-M4 的 USB↔USART3 桥接裸机应用，使用 HAL、USB 中间件、
TIM3、USART3 IRQ 和 DMA1 stream3，无 FreeRTOS。
[官方说明](https://github.com/STMicroelectronics/STM32CubeF4/blob/v1.28.3/Projects/STM324xG_EVAL/Applications/USB_Device/CDC_Standalone/readme.txt)
描述了实际收发流程，并明确提醒 ISR 内 HAL_Delay 的 SysTick 优先级依赖。
这是厂商参考应用，不宣称是经量产认证的完整产品。

保留完整驱动依赖、原应用、真实启动向量和链接布局；由 MDK FS target 的源文件及
头文件路径构造 GNU ARM CMake 构建，使用 CubeIDE 的启动、链接与系统调用文件。
GCC 10.3 不支持新版链接脚本的 `READONLY` 段属性，按原脚本注释移除该标注。
使用 `-Og -fno-inline` 保留可审查的跨函数窗口；结论仅对应此构建与源码条件。

共构建 p00 基线及 p01～p20 二十个独立变体。新增场景经 main 的 Init/Poll、
SysTick、真实 TIM6/TIM7 IRQ 或 DMA2 stream0 接入固件，未用空壳工程替代原应用。
DMA2 M2M 配置采用 FIFO，与原有 DMA1 UART TX 分开；对应官方例程依据是
[DMA_FLASHToRAM](https://github.com/STMicroelectronics/STM32CubeF4/blob/v1.28.3/Projects/STM324xG_EVAL/Examples/DMA/DMA_FLASHToRAM/Src/main.c)。

没有目标板烧录、外设总线/真实时间仿真或板上复现。真实完成的层次为 ARM 编译链接、
Clang 提取、ECRA 正常分析、真实 OpenCode 模型只读复核，以及明确限定的宿主机调度回放。
只对矩阵指定的二十个变量和少量原生变量进行 AI 复核，不能据此宣称整个工程已完成安全认证。

## 独立预期与流程

首轮前固定 `expectations.json`：13 个风险、5 个安全对照、2 个源码证据不足场景。
真值、场景标题和二进制板级实现源码均留在验证仓库，未复制到模型可读的工程。
模型读取正常 Packet、实际 `App/lab.c`、板级 IRQ/DMA 配置及案例库；项目仅用中性编号命名。
二进制场景的预期衡量源码证据边界，不等同于已知对象代码实际会触发缺陷。

每个工程均列出 39 个编译单元。基线使用普通 CLI 完成冷提取；其余变体复用哈希匹配的
真实 Clang 响应，变化的 `lab.c` 分别解析。复用同时验证引擎、编译参数、源文件、包含头文件
和响应内容哈希。另在 p01 对 `App/board.c` 独立重提取，完整结构与路径迁移后的响应相等。
复用只在提取子进程传输边界实施，合并、调用恢复、分析、报告与队列仍执行原流程。
因此不能将结果称为“21 次完全独立冷扫描”。

基线盘点 244 个变量，生成 205 个候选/盲区项；矩阵只取指定变量送审，完整静态清单不删减。
安全样本使用已有抽查接口，并以 `run` 模式显式送审，静态分类与正常队列保持原样。
首轮基线起初使用 `review` 模式，静态安全的 Out 索引没有送审；工具已改为 `run` 模式，
该样本另轮补测。首轮原生三份真实答案与未送审记录均保留，不把 PENDING 当成安全。

工具是 OpenCode 1.18.35，模型 `kimi/kimi-k2.7-code`。所有调用使用 ECRA 现有只读 agent，
保留 JSONL 工具事件、源码读取、案例正文读取、Packet、提示词、答案和哈希收据；成功项重新校验收据。
未使用模拟模型答案计算识别率，也没有把编写代码工作委托给 OpenCode。

两份扫描在更新复核提示词时触发实现版本一致性保护并中止，已在固定版本后重跑；
中止结果不计作已完成扫描。正常 `--no-review` 报告显示 INCOMPLETE 是因为完整候选队列仍待审，
不能将它误报成 39 个编译单元解析失败。

## 二十项矩阵

首轮二十项均完成真实模型调用、格式校验及收据校验：18/20 状态符合独立预期。
其中风险 13/13，安全对照 4/5，证据不足 1/2；没有技术失败，但有两项语义错误。

| 场景 | 机制/独立预期 | 首轮状态 | 评估 |
|---|---|---|---|
| p01 | 直接旧值写回／风险 | CONFIRMED | 符合 |
| p02 | 四层函数传播旧值／风险 | CONFIRMED | 符合 |
| p03 | 只保护最终写／风险 | CONFIRMED | 符合 |
| p04 | BASEPRI 阈值不足／风险 | CONFIRMED | 符合 |
| p05 | 双字段不变式／风险 | CONFIRMED | 符合 |
| p06 | memcpy 对象快照写回／风险 | CONFIRMED | 符合 |
| p07 | 函数指针共用 Setter／风险 | CONFIRMED | 符合 |
| p08 | 不同原子锁保护同一全局量／风险 | CONFIRMED | 符合 |
| p09 | 对象代际复用／风险 | CONFIRMED | 符合 |
| p10 | DMA 源过早复用／风险 | CONFIRMED | 符合 |
| p11 | ISR 等待低级 SysTick／风险 | CONFIRMED | 符合 |
| p12 | 长度 double-fetch／风险 | CONFIRMED | 符合 |
| p13 | 完整 PRIMASK／安全 | REVIEWED_SAFE | 符合 |
| p14 | 同抢占级 IRQ／安全 | FALSE_POSITIVE | 符合 |
| p15 | 有效 BASEPRI／安全 | REVIEWED_SAFE | 符合 |
| p16 | DMA 完成后复用源／安全 | REVIEWED_SAFE | 符合 |
| p17 | 后续二进制 IRQ 策略／证据不足 | CONFIRMED | 过度确认 |
| p18 | 二进制回调触发者／证据不足 | NEED_MORE_CONTEXT | 符合 |
| p19 | 盲写单字 GPIO 命令／安全 | CONFIRMED | 误报 |
| p20 | IRQ 先使能后初始化／风险 | CONFIRMED | 符合 |

首轮有 89 次成功源码 read，20/20 项均读取源码；19/20 项读取案例正文，共 31 次。
p12 首轮只利用索引，没有读取正文，不能声称所有首轮推理均使用了案例正文；该项在后续复测中读取了相关正文。

风险与修复有实际对照：p01/p03 的完整保护对应 p13；p04 的有效阈值对应 p15；
p10 的 DMA 所有权回收对应 p16。预埋风险源码保留，便于后续模型与案例库回归。
仅按合法状态计分不足以证明推理正确，还逐份核对了参与者、窗口、优先级与错误结果。

## 原生应用复核与发现的复核问题

原生 `UartHandle.gState`、`LineCoding.bitrate` 及环形缓冲区索引另作探索性复核，
没有事先可量化真值，不进入二十项准确性分母。模型答案不是上游已确认安全公告或缺陷公告。

首轮 `LineCoding.bitrate` 被判 REVIEWED_SAFE：模型沿 USB 的 Control 回调与实际类表核对，
排除了静态过近似的入口；全部实际访问在同一 OTG_FS 物理上下文内。
`UartHandle.gState` 也被模型判 REVIEWED_SAFE：它检查了 USART3/USB/DMA 的实际写值及
检查后设置路径。该结论是针对所选变量的源码分析，未代替 UART 生命周期与在途 DMA 的板上验证。

发现的实质复核问题是对 `UserTxBufPtrIn` 的过度确认。首轮把“消费者可能读到旧索引”
直接解释为丢数据；一致旧边界可以把新字节留到下一轮，这不足以证明错误。
第一次优化后，模型改称比较与减法间重新读取了回绕后的 In，导致长度下溢，仍报 CONFIRMED。
但本次固件反汇编显示：`0x08000adc` 把 In 载入 r4，比较和减法沿用该值，
`0x08000b0e` 是寄存器减法，没有模型所依赖的第二次 load。
这只反驳该构建中的特定 double-fetch 时序，不能证明缓冲区过载、USB 在途复用等其他风险不存在。

补充证据的原生索引复核没有得到可用最终答案：一次只有执行事件，另一次在提供商额度问题后主动中止。
因此目前不能声称原生 `UserTxBufPtrIn` 的过度确认已通过最终模型验收；反汇编反证及规则修正已完成，
这项原生变量复核仍需恢复额度后继续。`binary-context` 命令可以从真实 ELF 重建补充观测，
其中仅含编译信息、符号及反汇编，不注入“应判安全/风险”的答案。

受控矩阵的另两项错误也逐条保留：p17 看见早期 `Lab_Configure(10,2)` 后忽略了
`Board_IrqPolicy()` 的未知效果。后续一轮虽然承认该缺口，仍以“使能到策略调用前”短暂窗口确认风险，
却没有证明定时器周期、阶段延迟与竞争访问足以让该窗口发生。不能把这一猜测当作调用后持续抢占的证据。
p19 则虚构了“高优先级 IRQ 的值必须胜出”以及“GPIO 任意时刻等于最新共享值”的业务要求；
源码只有完整盲写与单次快照，没有保存每个事件或零传播延迟的协议。

一次中间规则版本的九项复测为 6/9：p01/p11/p12/p13/p14/p20 符合预期，p17/p19 仍过度确认，
并新增 p16 误报。它把 DMB 的顺序语义错误地理解为数据对 DMA 仍可落后于使能寄存器写。
[Arm AN321 §4.18](https://documentation-service.arm.com/static/5efefb97dbdee951c1cd5aaf)
明确以“数据写入、DMB、DMA 启动”说明发布顺序；此处为无数据 Cache 的 F407 普通 SRAM，
不能照搬 M7 Cache 维护条件。这个反例已补入复核规则和 CASE-0021 的适用边界。
原始错误答案没有删除，不能将提示词增长本身当作准确率提高的证据。

最终规则的定向复测 `verified` 为 4/4，均有真实模型答案与可校验收据：

| 场景 | 最终定向状态 | 核对结果 |
|---|---|---|
| p16 DMA 完成握手 | REVIEWED_SAFE | 核对 DMB 发布顺序、完成位与 EN 清零，排除 F407 不存在的 D-Cache 条件 |
| p17 不可见 IRQ 策略 | LIKELY | 明确 Board_IrqPolicy 对最终抢占/屏蔽的影响未知，不再作为已确认缺陷 |
| p18 不可见回调调用者 | NEED_MORE_CONTEXT | 缺少触发上下文；一次技术失败后的重试得到此结论 |
| p19 单字命令邮箱 | REVIEWED_SAFE | 排除凭空添加的“高优先级值胜出”义务和零传播延迟要求 |

p17 的个别风险措辞仍偏强，必须结合其 missing_context 作为待核实条件阅读，不能当成板上已证实风险。
四项是针对已知失败类型的回归；不是最终版本全矩阵的新一轮独立准确率，也不证明对未知项目普遍可靠。
首轮、中间回归、每次失败及最终定向记录都在结果 JSON 中分别保存。

对 p16/p19 的同配置重复验证，以及最终规则下 p01/p11/p12/p20 的额外回归未能完成：
提供商实际返回 HTTP 429，提示账户余额不足，已停止新的付费模型调用并将中断项记录为 TECH_FAILED。
这些项不能算作复测通过；已有成功答案也不能掩盖后续技术失败。
恢复额度后应另开 round 继续验证，不能以一次定向通过承诺模型稳定性。

## 本次优化与案例库补充

优化集中在复核侧，不改变 AST 提取、静态分类算法、输出 Schema、Validator 或报告状态机：

- 追踪等待条件的唯一推进者，区分软件 IRQ 更新与自主硬件完成；检查 SysTick 依赖超时是否也会卡住。
- 排除单生产者发布索引的合法旧快照；要求指出真实协议错误，而不以无锁读写本身确认缺陷。
- 核对特定重新 load 的证据条件，区分源码可能交错与当前机器代码已验证的交错。
- 修复建议保存/恢复原屏蔽状态；避免用无条件 `__enable_irq()` 作为通用临界区结尾。
- 启动、重启与回调发布前核对对象初始化完整性。
- 区分 NVIC 调度优先级与业务值的胜出约束；区分 DMB 发布顺序、DSB 完成语义、Cache 维护与 DMA 所有权。

另修复了实测暴露的诊断问题：OpenCode 以非零码退出、stderr 为空且把 APIError 写入 stdout JSONL 时，
此前只显示空泛的 `OpenCode exit=1`；现在提取 HTTP 状态和提供商消息，仍归为 TECH_FAILED，
不进入格式修复。概要不复制响应头和响应体，原始事件仍在本地归档。
该修复用真实失败类型的合成回归测试覆盖，不再额外消耗提供商额度。

案例库由 23 条增至 26 条，保持无外链：CASE-0024 是官方 SysTick 等待依赖依据与受控回放；
CASE-0025 是自行构造的 IRQ 初始化窗口；CASE-0026 是发布索引的误报排除方法。
新增三条没有计入独立真实事故数，原有 17 个实际缺陷/厂商修复记录口径保持不变。
公开来源链接集中放在本报告与原有来源文档，案例库本体只保留来源名称和定位信息。

## 验证与复现

14 个宿主机回放均通过：对实际用例 C 源码的副本插入一次性抢占点，检查旧值覆盖、
混合快照、代际不一致、长度 32 对 8 字节容量的冲突，以及完整屏蔽/同级 IRQ 阻止介入。
SysTick 场景检查 16 次循环均无推进的有界模型，不宣称模拟了无限物理运行。
回放不模拟 DMA 或外设总线；对应 DMA 判断依赖真实 ARM 配置源码与芯片语义。

最终全量 `py -3.10 -X utf8 -m unittest discover -s tests -q`：659 项，2 项可选测试跳过，其余通过。
真实模型调用另行运行，没有把可选 live 单元测试的跳过当作模型通过。
另核对 46 份本轮复核归档，队列、结果文件与静态目标一致；技术失败与首轮未送审项均未伪装成 DONE。

```powershell
py -3.10 scripts/validate_stm32_cdc.py prepare
py -3.10 scripts/validate_stm32_cdc.py scan
py -3.10 scripts/validate_stm32_cdc.py review --round replay --workers 3
py -3.10 scripts/validate_stm32_cdc.py summary --round replay
py -3.10 scripts/replay_stm32_interleavings.py
```

定向复核与补充二进制观测的入口：

```powershell
py -3.10 scripts/validate_stm32_cdc.py binary-context
py -3.10 scripts/validate_stm32_cdc.py review --cases p00 --targets UserTxBufPtrIn --round native-recheck --timeout 600
py -3.10 scripts/validate_stm32_cdc.py review --cases p16,p17,p18,p19 --round directed-recheck --refresh-library
```

原始材料在 `validation/stm32_cube_cdc_20261018`：`provenance.json` 和工具版本、
21 份 ELF/链接日志/符号、各工程 `.ecra` 完整事实与报告、各轮 review 的 JSONL 与收据、
`native-callback-disassembly.txt`、`cache-audit.json`、`host-replays/results.json`。
这些大体积材料被 Git 忽略；可重建的脚本、场景源码、预期与精简结果已纳入本次修改。
中央 `config/semantics.yaml` 保持不变。
