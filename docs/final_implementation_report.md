# STM32 裸核并发排查工具：增量开发与验收报告

本报告替换上一版记录。此前“全套通过”的说法缺少可靠完成证据；本轮重新运行发现并修复 missing compilation unit 对变量关联阻塞的回归。以下结果以可持久化日志为准，不将测试启动成功当作通过。

## 本轮实现

- 保留现有架构，新增 AST 派生 CFG、掩码抽象解释和 NVIC 证据检查三个模块。直接事实、状态推导、候选分类分别保存。
- PRIMASK 按单个位处理，跟踪分支/循环汇合、提前返回、保存恢复与跨函数状态。检查完整 READ→MODIFY→WRITE 窗口，防止“两个端点被屏蔽，中间开过中断”误判 SAFE。保存值被覆盖、自减或复合赋值后不能沿用旧值。
- 局部指针写入、内存库调用或未知被调效果会使缓存的保存值失效。独立 RMW 事务分别检查，不要求循环各次事务之间持续关中断；拆分 READ/WRITE 则仍检查整个快照窗口。
- BASEPRI 核对 NVIC 位数、优先级分组、阈值对齐及每个竞争 IRQ；未调用/条件执行的初始化不算证明。已知更高紧急度 IRQ 为 INEFFECTIVE。
- 全部解析无环调用路径、调用点与来源进入访问详情。递归边和 unresolved_call_edge 单列。默认无路径数上限，用户显式设置上限且超出时扫描失败，不静默截断。
- 每变量保存分类、覆盖、safe_reason/safe_evidence、unknown_reason/blocking_evidence/required_context；TOTAL 及安全/复核互斥并集强校验。
- 缺失源码的变量/函数词法引用只作为局部阻塞候选；无关 parse/unlisted TU 不再无差别污染变量。源码在扫描期间变化仍阻断整个结果的有效性。
- DMB/DSB/ISB 明确不提供互斥。Ownership/Single Writer 与保护状态分开，DMA 保持独立并发主体。
- Evidence Packet 增加 CFG、掩码窗口、NVIC 配置、上下文、抢占和未知边。SAFE 抽样有独立 HTML 栏目/SQLite 表/计数，不混入默认风险队列。
- 新增 20 个独立 Demo、跨层验收、控制流与优先级对抗测试，以及持久化验收脚本。
- 复验发现 Windows 原子替换报告队列时偶发拒绝访问。JSON、SQLite 和 HTML 的原子替换对 WinError 5/32/33 最多尝试 5 次，总等待 0.75 秒；不删除旧文件、不降级非原子复制，持续权限错误仍抛出。新增瞬时/永久/非 Windows 错误测试。

## 验证

最终命令：

```powershell
python scripts/verify_design.py --all
```

最终运行结果见 [verification.json](../output/design-acceptance/verification.json) 与 [verification.log](../output/design-acceptance/verification.log)（开发环境生成物，不提交）。已确认最终进程退出码为 0。

每个 D01–D20 都经过真实 libclang 抽取，验证 facts、分类/覆盖/保护、归账、访问/调用链、SQLite、两个 HTML、离线队列和 Packet。D20 逐个验证 32 个访问及两条 MAIN 调用路径。D10 另有 INEFFECTIVE、未调用初始化和条件初始化反例。完整场景预期见 [Demo 矩阵](../examples/stm32_demo/cases/README.md)。

默认离线复核仍为 PENDING/NEED_MORE_CONTEXT，没有伪造 CONFIRMED 或模型安全结论；本轮没有调用 Claude Code/OpenCode，也没有目标板验证。

## P0 对照

| 项目 | 验收方法 |
|---|---|
| TOTAL=SAFE+SUSPECT+UNKNOWN | 每变量显式分类，唯一 ID、安全集合/复核集合互斥并集检查 |
| 已解析访问不丢失 | D01–20 对 facts、变量访问集合、数据库计数和 HTML access_id 逐项断言 |
| 调用链不静默截断 | diamond/D20 全路径、调用边及 cycle/未知边展示；显式资源上限失败 |
| SAFE 必须证明 | safe_reason/safe_evidence 和 COMPLETE 校验；控制流反例不得 SAFE |
| DETECTED != EFFECTIVE | D08–11/D16–18 和掩码间隙/更高 IRQ 反例 |
| UNKNOWN 可解释 | coverage_reasons、关联阻塞证据和补充上下文 |
| UNKNOWN 不无关扩散 | unrelated parse/D13 与 missing-source 关联回归同时通过 |
| OpenCode 不伪造确定性 | 合约/收据/引用测试；离线保留未完成，SAFE 抽样独立 |

## 明确未完成的能力边界

不把测试通过等同于完整 C/硬件形式化验证，追踪矩阵保留 Partial：

- CFG 尚不证明 for/switch/goto、异常、inline asm 或无序复杂表达式；这些构造阻断保护证明，不由词法区间兜底判安全。
- NVIC 只接受可证明位数/分组/唯一初始化位置；动态优先级重配、复杂初始化、NMI/HardFault、任务或 DMA 不套用普通 MAIN↔ISR 掩码证明。
- 递归、过深调用、不完整函数体、未知局部指针效果及复杂 BASEPRI 被调窗口保守处理。
- DMA 生命周期/Cache 协议、任意所有权转移、复杂 alias 和自定义锁算法没有完整自动证明。
- 模型逐步时序只有真实复核答案才作为模型结果展示；静态快照示例明确是有前提的候选，不是假运行轨迹。
- 真实 ARM 工具链构建、真实 OpenCode 服务和目标板并发实验不能由离线夹具替代。

这些缺口不会在文档中改名为“已完成”；后续可沿 CFG 节点/状态域、IRQ 配置证据和 Packet 合约继续扩展。

## 最终统计

- 全量：225 项，224 通过，1 跳过，0 失败、0 错误；耗时 139.654 秒。
- 跳过项：`test_fresh_cmake_project_auto_toolchain_builds_real_arm_object`，当前环境缺少其要求的 CMake/Ninja/Arm GCC 工具链组合；没有声称真实 ARM 构建通过。
- 定向：设计与原子输出 47 项全部通过，其中 D01–D20 全部通过。
- 旧 Demo：`TOTAL 13 = SAFE 5 + SUSPECT 2 + UNKNOWN 6`，8 个变量复核项及 2 个独立证据缺口；离线状态为 INCOMPLETE，命令退出码 1 表示仍待复核，不是扫描崩溃。
- `git diff --check` 通过；仅出现 Windows 行尾提示。

可直接打开 [D20 全部访问清单](../output/design-acceptance/D20/.ecra/index.html)、[D20 离线复核页](../output/design-acceptance/D20/.ecra/opencode_review.html)；其他场景按 D01–D20 目录对应查看。
