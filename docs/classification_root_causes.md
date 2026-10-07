# Pre-OpenCode 分类队列根因基线

本文冻结四分类重构前最后一组可复现结果，用来回答“为什么真实工程的
SUSPECT + UNKNOWN 仍然过多”。所有类别都按 canonical variable 去重，
但同一变量可以同时命中多个根因，所以各行不能相加为变量总数。

| 工程 | 分析变量 | SAFE | SUSPECT | UNKNOWN | OpenCode 队列 | 队列比例 |
|---|---:|---:|---:|---:|---:|---:|
| Serial STM32 Demo | 154 | 55 | 96 | 3 | 99 | 64.29% |
| Klipper MCU / STM32 | 733 | 494 | 48 | 191 | 239 | 32.61% |
| Blackmagic STM32 baseline | 682 | 8 | 0 | 674 | 674 | 98.83% |

这些数字使用旧三分类名称 `SAFE`，仅作为修改前基线。新引擎统一输出
`SAFE_PROVEN / SHARED_NO_REVIEW / SUSPECT / UNKNOWN`，不会把旧 SAFE
直接当作新证明。

## Serial 根因

分母分别为 154 个分析变量和 99 个复核变量。

| 根因 | 变量数 | 占全部变量 | 占复核队列 | 解释 |
|---|---:|---:|---:|---|
| MULTI_CONTEXT | 96 | 62.34% | 96.97% | 变量被赋予两个以上物理上下文。旧实现还会把部分逻辑回调路径重复看成执行者。 |
| MULTI_WRITER | 64 | 41.56% | 64.65% | 已恢复到两个以上写者；其中既有真实冲突，也有初始化写没有与运行期分离。 |
| RMW | 33 | 21.43% | 33.33% | 跨上下文读改写，属于破坏性冲突，不能仅因单次访问宽度而降级。 |
| UNKNOWN_PREEMPTION | 41 | 26.62% | 41.41% | 冲突 pair 的 IRQ 优先级没有完整恢复；这应保留为 SUSPECT 的 MHP=MAYBE，不应变成 UNKNOWN。 |
| ADDRESS_ESCAPE | 5 | 3.25% | 5.05% | 目标变量地址进入不可分析代码，属于变量局部缺口。 |
| INDIRECT_CALL / FUNCTION_ADDRESS | 15 | 9.74% | 15.15% | 主要来自同一 HAL UART function-address 位置；旧传播范围仍大于实际对象关系。 |
| MISSING_SOURCE | 0 | 0.00% | 0.00% | 当前目标构建闭包没有此类变量级 blocker。 |
| UNKNOWN_CONTEXT | 15 | 9.74% | 15.15% | 某些访问函数仍继承了未恢复入口。 |
| DMA | 3 | 1.95% | 3.03% | 目标缓冲区确实进入 DMA，生命周期/方向需要变量级证明。 |
| INIT_WRITE | 50 | 32.47% | 50.51% | 呈现“foreground 初始化写 + IRQ 运行期读”形态；旧证明只接受 main 内直接写，遗漏 helper 与嵌套 NVIC enable。 |
| HAL / callback context expansion | 37 | 24.03% | 37.37% | 同一个源码访问被赋予多个物理上下文；部分为对象不敏感的 HAL callback 扩张。 |
| alias unknown | 5 | 3.25% | 5.05% | points-to 尚未闭合且与目标变量直接相关。 |
| other: whole-object/member overlap | 15 | 9.74% | 15.15% | 整体访问与成员访问重叠；需要保留，除非布局证明不重叠。 |

Serial 的 32 个“单写者 + 其余读者”形状中，旧证据只有 8 个接近严格门禁；
函数指针、动态环形数组、多字段一致性和初始化阶段仍阻止直接进入
`SHARED_NO_REVIEW`。因此这里不能靠放宽标准批量降级。高收益方向是证明
INIT→RUNTIME 不同时发生，以及把同一物理 foreground/IRQ 内的逻辑路径折叠。

## Klipper 根因

分母分别为 733 个分析变量和 239 个复核变量。当前 compact index 没有保存
全部旧 conflict-pair relation；无法从索引精确恢复的项明确标为“待重跑”，
不使用推测值填充。

| 根因 | 变量数 | 占全部变量 | 占复核队列 | 解释 |
|---|---:|---:|---:|---|
| MULTI_CONTEXT | 48 | 6.55% | 20.08% | 至少 48 个 SUSPECT 有多个物理上下文。UNKNOWN 中的上下文缺口另列。 |
| MULTI_WRITER | 45 | 6.14% | 18.83% | 主要集中在 48 个 SUSPECT；需先清除伪 alias 写者再判断。 |
| RMW | 15 | 2.05% | 6.28% | 已知破坏性访问，继续留在 SUSPECT。 |
| UNKNOWN_PREEMPTION | 待新引擎重跑 | — | — | 旧 compact index 未保留全部 pair relation；新输出必须直接记录 MHP=YES/NO/MAYBE。 |
| ADDRESS_ESCAPE | 142 | 19.37% | 59.41% | 其中大量来自 `command.c` 标量/变参被错误当作指针 provenance 的单点扇出。 |
| INDIRECT_CALL / FUNCTION_ADDRESS | 80 | 10.91% | 33.47% | `SCB->VTOR=(uint32_t)VectorTable` 等已恢复向量表仍被当作变量 blocker。 |
| MISSING_SOURCE | 25 | 3.41% | 10.46% | 包含链接脚本边界符号、不可达 CMSIS inline，以及 function-static 多 declarator 假缺定义。 |
| UNKNOWN_CONTEXT | 32 | 4.37% | 13.39% | 访问入口尚未恢复；必须只影响可达该访问函数的变量。 |
| DMA | 旧索引未报告 | — | — | 不据此断言不存在 DMA；新 benchmark 按变量保存方向和生命周期原因。 |
| INIT_WRITE | 待新引擎重跑 | — | — | 旧索引没有阶段字段。 |
| HAL / callback context expansion | 44 | 6.00% | 18.41% | 44 个 SUSPECT 的访问同时落入 foreground 与 SysTick，暴露调用点/保护状态传播不足。 |
| alias unknown | 130 | 17.74% | 54.39% | `command.c:168` 等少数 provenance 错误污染大批只读常量。 |
| other: const/read-only UNKNOWN | 151 | 20.60% | 63.18% | 151 个 UNKNOWN 根对象为 const；多数应在修复伪 escape/alias 后由 READ_ONLY 证明筛除。 |

最集中的污染点是 `src/command.c:178`：一次错误 ADDRESS_ESCAPE 传播到约
123 个 compile-time request 常量；相邻 alias 位置影响约 101 个对象。根因是
把普通整数、长度和 varargs 标量加入 pointer may-set。第二个簇是 pointer
slot/pointee 混淆：从 `digital_regs[]` 或 `i2c_bus[].i2c` 读取外设指针后写
MMIO，旧 alias 通道把写入错误归到指针容器本身。

## Blackmagic baseline

`after-shared-evidence` 只完成了 83.2 MB raw facts，分类在序列化阶段中断，
因此下面只能使用旧 baseline。它反映项目级 blocker 扩散，不能与新变量
Evidence Slice 结果直接比较。

| 旧 blocker | 变量数 | 占全部变量 | 占复核队列 |
|---|---:|---:|---:|
| FUNCTION_ADDRESS | 481 | 70.53% | 71.36% |
| INDIRECT_CALL | 469 | 68.77% | 69.58% |
| POINTER_SUBSCRIPT | 460 | 67.45% | 68.25% |
| POINTER_DEREFERENCE / UNRESOLVED_POINTEE | 434 | 63.64% | 64.39% |
| EXTERNAL_CALLEE | 433 | 63.49% | 64.24% |
| STATIC_INITIALIZER_REFERENCE | 224 | 32.84% | 33.23% |
| ADDRESS_ESCAPE | 217 | 31.82% | 32.20% |
| INLINE_ASSEMBLY | 202 | 29.62% | 29.97% |

同一批变量同时命中许多 blocker，正是 UNKNOWN 全局污染的证据。新 benchmark
默认不再重复序列化完整 facts/report；分类索引、审计样本和统计保持线性规模。

## 已确认的通用根因与修复方向

1. **UNKNOWN 曾被当作项目全局 taint。** 未解析函数指针、缺失 caller 或解析
   失败会跨越不相关 call graph、链接可见性和 TU 边界。修复后 blocker 只有
   进入该变量 `VariableEvidenceSlice` 才能改变分类。
2. **逻辑 callback/task 被误当成物理线程。** 新冲突层以 `physical_id` 判断；
   cooperative foreground 和同一 IRQ 的所有调用路径内部串行。
3. **已知冲突被 coverage 覆盖。** 新顺序先判断真实冲突；优先级或保护未解析
   只令 MHP/保护保持保守，分类仍为 SUSPECT。
4. **pointer provenance 过宽。** 普通整数不再继承指针 may-set；显式
   pointer→integer→pointer round-trip 仍保留。pointer slot 读取与 pointee
   写入分离，旧 flow-insensitive alias 写入通道已删除。
5. **初始化证明只看 main 直接语句。** 新 phase 数据流跨已解析 helper 传播，
   并使用 NVIC disable/enable 或已验证 Cortex-M reset vector 证明
   INIT 写与 IRQ runtime 读的 MHP=NO。
6. **定义与构建闭包不完整。** function-static 多 declarator、weak override、
   vector/section 注册、链接脚本符号和实际 linked TU 必须分别恢复；缺失事实
   只按链接可见性进入相关变量。
7. **输出格式不可扩展。** Klipper 曾重复写出约 12 GB facts/report；
   Betaflight points-to may-set 达到约 2.16 亿值。新 benchmark 默认输出 compact
   classification index 和分层审计样本，完整 facts 仅显式请求。

本基线只用于解释修改前队列，不是新实现的验收结果。三个真实工程必须在同一
冻结引擎上重新提取、重新分类和分别审计 30 个 `SAFE_PROVEN` 与 30 个
`SHARED_NO_REVIEW` 后，才能写入最终 benchmark 报告。
