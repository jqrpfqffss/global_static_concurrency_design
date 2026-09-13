# 两小时后执行：真实 STM32 工程并发排查验收

工作目录：H:/global_static_concurrency_design
这是用户明确授权的实施任务，到了计划时间直接执行，不要停留在方案，也不要再次询问是否继续。当前只创建任务，真正实施从计划时间开始。

用户原始要求：
> 请创建真实的stm32项目，stm32项目里面包含所有的并发类型，设计的并发类型要足够隐蔽，符合真实的场景，创建完成后用上面的stm32并发排查工具排查测试，如果stm32并发排查工具代码有问题请修复后重新执行测试，直到把所有类型的并发变量都排查出来才算完成测试。

## 执行方式

Codex 直接实现、调试和测试；Claude Code 委派保持禁用，不创建或执行 Claude bridge/task 文件。不要覆盖用户已有修改。不要提交、推送、发布或发送外部消息。任务范围内可创建工程、下载公开的官方依赖/工具链到工作区、修改 ECRA、运行构建和测试，无需重复确认。沿用现有 OpenCode 提供商与模型配置进行只读逐项复核，不擅自更换账号或购买服务。

先读 README.md、codex_global_static_concurrency_design.md、docs/implementation-notes.md、ecra/ 和 tests/。当前已经存在 Python/libclang 的盘点、上下文传播、候选和 OpenCode 复核管线；18 项回归测试及小示例已经运行过。不要把 examples/stm32_demo 当作本任务要求的真实固件工程。

## 真实工程

在 validation/stm32_concurrency/ 建立具有真实业务组织的 STM32 验证项目：以 STM32H747/Cortex-M7 为主，配置 CM4 共享内存变体覆盖跨核；使用官方 CMSIS/设备头、真正的启动代码、向量表、链接脚本、ARM 交叉编译和真实 FreeRTOS/CMSIS-RTOS 接口。依赖来源和版本/许可证必须记录。不得用仅能主机编译的自造 typedef/空任务声明冒充完整 STM32 固件。

工程应能实际交叉编译链接为 ELF，生成真实 compile_commands.json。为不同核/编译宏变体分别构建扫描。围绕采样控制、串口 DMA 通信、命令邮箱、协议解析、定时器回调、双缓冲、设备状态和故障诊断组织模块；风险埋在跨文件多层调用、包装 API、宏、指针和回调中，不靠变量名 risk/race 显露问题。

没有目标板时，不声称烧录或硬件测试完成；补充可重复的主机侧调度/交错注入 harness，用它证明风险时序，但不得用 harness 替代 ARM 固件构建。请查阅官方 STM32/FreeRTOS/Clang 文档确认需要的平台细节。

## 必须先定义再验收的覆盖矩阵

先在独立 ground-truth 清单中冻结场景、所有全局/static 变量、预期读写上下文、预期调用链和风险变量。明确“全部”是以下可审计场景矩阵中的全部，不声称覆盖所有理论上可能的并发算法。至少覆盖：

1. 任务↔任务、任务↔ISR、主循环↔ISR、ISR↔ISR 嵌套抢占与优先级分组。
2. 同一入口创建多个任务；ISR 和任务共同调用非重入 helper 的函数级 static 状态。
3. 外部全局、跨文件 extern、同名文件 static、同名局部/不同块 static、头文件 static 各 TU 实例；常量/无访问项保留盘点。
4. ++、复合赋值、宏内 RMW、位域/共享容器、宽数据或未对齐撕裂、多字段不一致。
5. 跨调用/等待的旧快照写回、丢事件的标志位、check-then-act、环形缓冲索引与发布顺序、双缓冲所有权交接。
6. 局部/全局指针别名、跨函数参数和返回指针、结构体成员指针、数组衰减、memcpy/memset 包装写入、静态初始化地址逃逸。
7. 函数指针、回调表、HAL IRQ 分发与回调、FreeRTOS 软件定时器及延后处理、自定义任务注册包装、同一回调的多种真实执行上下文。
8. DMA↔CPU、DMA 生命周期内复用 buffer、接收长度/完成标志竞态、Cache clean/invalidate 与屏障/所有权时序。
9. CM7↔CM4 共享 SRAM/邮箱、HSEM/屏障/Cache 的正确和错误协议；不能把两个核的独立同名 static 合并成共享变量。
10. 错误临界区范围、提前 return、检查在锁外/使用在锁内、不同锁、mutex 与 ISR 不兼容、BASEPRI 不能屏蔽高优先级 ISR、volatile/单次原子但复合协议有竞态。
11. 提供正确保护、只读共享、单上下文、单写者但安全协议等对照，量化误报，防止把所有变量都标高风险来通过测试。
12. 缺失 TU/头文件、条件编译、多构建变体、未知上下文等不完整性负向测试。

每组包含多个适当组合，保持业务合理、可解释的最短交错。每个预埋风险必须有确切变量身份和证据，不要用无限扩展的“所有可能类型”造成不可验收的目标。

## 扫描、修复、重测闭环

1. 建立独立自动比较器 validation/stm32_concurrency/verify_acceptance.py。使用单独维护的 ground-truth 对比 ECRA 真正从 Clang/分析管线产生的 inventory、访问链、上下文和 findings。
2. 生产提取器/规则不得读取 ground-truth、识别测试变量名字或直接复制预期结果。必要运行语义配置可补入口、外设/核身份，但不能靠 YAML 把所有风险变量手工列出来冒充发现。
3. 首次扫描保存漏变量、缺失访问/上下文、缺失风险以及错误合并的明细；优先修正通用分析逻辑并新增针对根因的回归测试。
4. 每次实质修复后重新运行对应测试、原有测试及真实固件扫描。保留每轮修复原因和前后检测统计，继续处理剩余漏检，不能在“有了一些告警”时结束。
5. 所有预埋风险变量必须能在变量清单中定位，并有对应场景的实际风险候选和可追踪访问/上下文证据。单纯整文件 UNKNOWN、笼统列为有风险或只有地址逃逸告警，不等价于已发现具体场景。
6. 按工具的 OpenCode 流程对这些风险逐项复核；记录真实结果、源码引用、漏判/误判。若提供商未配置、登录/额度/网络等导致无法复核，不能用假 CLI 代替或宣称完成。能继续的本地实现与验证先做完，再明确阻塞条件。
7. 为交叉核/DMA 等新增建模时保持默认保守，不能为了通过测试关闭覆盖门槛、隐藏未知项、删除难用例或降低验收标准。

## 完成标准与交付

全部矩阵场景有实现和自动断言；所有预期变量盘点成功；所有预埋风险有具体匹配证据；模型复核未解决项为零；真实 ARM 工程构建通过；原有回归与新增验收通过。保留安全对照及误报统计。没有达到这些条件就继续工作；遇到真实外部依赖阻塞需明确报告，不得假装成功。

输出以下文件：
- validation/stm32_concurrency/README.md：工程、依赖、构建/扫描/验证命令。
- validation/stm32_concurrency/ground_truth.json：独立真值与场景矩阵。
- validation/stm32_concurrency/verify_acceptance.py：执行实际结果比较，失败非零退出；不得仅信任最终总结。
- validation/stm32_concurrency/acceptance.json：比较器生成的验收状态，至少包含 status、expected_variables、matched_variables、expected_risk_cases、matched_risk_cases、missing_variables、missing_risk_cases、unresolved_reviews、build_passed、regression_passed、firmware_artifacts。
  其中 missing_variables / missing_risk_cases 为数组；firmware_artifacts 为相对工程根目录的 ELF 文件路径数组。只有完整比较通过时 status 为 PASS。
- validation/stm32_concurrency/final_report.md：场景覆盖表、每轮漏检与修复、最终结果、真实模型复核和未进行的硬件验证。
- 每轮真实的编译、测试、扫描、模型复核日志和结果。

保持 validation/stm32_concurrency/progress.md 持续更新，供下一轮恢复。如果本轮上下文即将耗尽但仍能推进，写好进度，最终结构化输出 status=CONTINUE，控制器会启动下一轮。仅在所有完成标准满足且比较器刚刚通过时返回 COMPLETE。外部依赖确实阻塞时返回 BLOCKED 并说明具体条件。不要更改 scheduled/stm32-concurrency-20260906/ 中的控制器、任务或验收门槛以取得成功状态。
