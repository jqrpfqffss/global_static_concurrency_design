# Q205独立复核：物理入口身份与人工标签碰撞

已完成对独立冻结候选的只读复核和实际ARM对照，范围内通过。原生产源、旧冻结引擎、客户数据均未修改；Q206函数别名遗漏另行修复，本文不代表组合引擎或完整交付已经验收。

## 独立判断依据

Cortex-M向量槽2为NMI、槽3为HardFault，不能因为C函数名称或手工逻辑标签改变其架构身份。[Arm CMSIS-Core异常枚举](https://arm-software.github.io/CMSIS_5/Core/html/group__NVIC__gr.html)

PRIMASK不阻止NMI和HardFault；FAULTMASK仍不阻止NMI。已知这些物理竞争方时，不能仅由PRIMASK窗口得出安全结论。[Arm CMSIS-Core寄存器接口](https://arm-software.github.io/CMSIS_5/5.7.0/Core/html/group__Core__Register__gr.html)

原证据 `output/quality-20261108/continuation/diff/q201-real-vector-manual-override.json` 的10个样例均真正经ARM GCC对象编译，objdump证明 `.isr_vector` 偏移8/12指向任意命名的ExceptionRoute。无手工标签、不同逻辑ID时均SUSPECT/INEFFECTIVE；六个相同ID样例把slot/vector/unmaskable字段覆盖后错误变为SAFE_PROVEN/EFFECTIVE。旧输出是缺陷实证，不是修复的预期答案。原输入SHA及独立oracle保存在 `q205-independent-review/oracle-baseline.json`。

独立复核将检查：所有自动producer与配置的正反碰撞；真实slot、unmaskable、function及root、已恢复优先级不得消失；相容普通IRQ补充与真实注册分组保留；矛盾配置明确拒绝或保留不确定性；异常不被吞掉后继续判安全；Q109新容器及旧归档只读派生逻辑保留。

## 归一阶段的同类入口

实际调用旧v3 `physical.normalize_contexts`：配置group包含TIM1/TIM2两个IRQ，另一个合法配置ID `group:TIM2_IRQHandler` 包含USART1根。模式拆分生成同名ID后，实际输出把USART1根丢失。独立预期是配置根集合必须保留，或在冲突处清楚拒绝；不得无声覆盖。该函数级复现没有声称Clang全流程或风险分类通过，证据 `physical-split-collision-baseline.json`。已交实现者在同一碰撞修复中处理。

## BASEPRI优先级旁路对照

只读检查v3数据流，NVIC/interrupts/protection不直接读取cfg.contexts的priority；已恢复NVIC事实优先，配置priority和preemption按README约定是复核证据。为防修复后旁路，另准备实际ARM对象编译、向量偏移0x54（slot21）、Clang→NVIC→BASEPRI完整分析的五个独立对照：

| 实际源码优先级 | 同ID手工值 | v3实际结果 | 独立判断 |
|---|---|---|---|
| 1 | 无 | model1，SUSPECT/INEFFECTIVE | 高于BASEPRI逻辑阈值2，不能筛除 |
| 1 | 15 | model仍1，SUSPECT/INEFFECTIVE | 手工值不能覆盖源码证明 |
| 3 | 无 | model3，SAFE_PROVEN/EFFECTIVE | 完整窗口且该普通IRQ被阈值屏蔽 |
| 3 | 0 | model仍3，SAFE_PROVEN/EFFECTIVE | 相冲突手工证据不改变已证实的硬件值 |
| 未恢复 | 3 | 无猜值，SUSPECT/UNRESOLVED | 手工值仍保留为复核证据，不能凭数字制造静态安全 |

因此目前没有确认cfg.contexts优先级旁路缺陷；上述是修复候选必须保持的对照。源代码、真实GCC命令、对象、objdump及模型结果均保存 `output/quality-20261108/continuation/q205-independent-review/v3-oracle-priority/`，控制器为同目录父级的 `basepri_compare.py`。这只是明确API合同的对象级编译和分析证据，不是完整固件链接或HIL，不计作第四个真实工程。

## 最终候选复核

候选为 `H:/ECRA-quality-20261108/continuation-diff/q205-candidate-source`，静态指纹 `f6eae1a34b00edf020355f3c7281da4d8dd9f26cae544fe9d1d3f6c68442df7b`。三处生产文件SHA已与实现者冻结收据核对：analysis `016b421f…`、physical `e945769e…`、protection `f6447721…`；完整值见 `output/quality-20261108/continuation/q205-independent-review/frozen-review-receipt.json`。

实际独立重跑上述五个ARM/NVIC/BASEPRI相同输入，全部保持预期：源码priority1不被手工15放宽、源码3不被手工0覆盖、无源码优先级时手工3保留为单独证据且保持不确定。完整源/对象/重定位/模型结果在 `q205-frozen-priority/receipt.json`。归一拆分的旧反例已改为明确冲突错误，未再默默丢根。

逐段审阅确认：同槽相容多来源保留全部source_entries和roots；同ID配置先验证kind、选择器、物理身份，再将相容补充单列configuration_evidence；自动生成入口反向碰撞与拆分均显式检查。NVIC模型和保护判据没有通过cfg.contexts重新读取冲突数字。FAULTMASK仅对已确认物理槽集合恰为 `{3}` 的HardFault保留有效性，NMI和未知不可屏蔽域仍不能证明有效。Q109从canonical_member_path之后的analysis字节与v3相同。

另以独立会话重跑候选13个针对方法，15.885秒通过，日志 `independent-candidate-tests.log`。这些方法与实现者测试重叠，不累加成额外覆盖总数。此结论仍依赖既有手工ISR身份声明合同，不声称未恢复ABI时手工信息已获得独立硬件证明；GNU函数alias造成的入口遗漏Q206不在此候选中。

后续Q205与Q206已组合至最终v4（core63a5…），[三工程实际全量及相邻审计](continuation-final-projects-v4.md)已完成；原同ID/别名目标体反例在组合副本的10个实际ARM场景也已验证SUSPECT或明确拒绝。原候选f6eae的收据仍保留其独立范围，不假称自身已经包含Q206。
