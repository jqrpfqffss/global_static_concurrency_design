# 分类根因统计（三工程，四类分类）

生成时间：2026-09-30。数据来源：三工程缓存提取 parts 经修复后提取器重建、
四类分类引擎重放（`D:/ecra-bench/bench_one.py` 链路）。口径：编译变量
（`coverage_source == compile_database`，不含结构体容器）。

## 汇总

| 工程 | TOTAL | SAFE_PROVEN | SHARED_NO_REVIEW | SUSPECT | UNKNOWN | OpenCode 队列 |
|---|---|---|---|---|---|---|
| klipper | 901 | 841 (93.3%) | 1 (0.1%) | 37 (4.1%) | 22 (2.4%) | **59 (6.5%)** |
| blackmagic | 716 | 498 (69.6%) | 9 (1.3%) | 121 (16.9%) | 88 (12.3%) | **209 (29.2%)** |
| betaflight | 7936 | 4630 (58.3%) | 180 (2.3%) | 2693 (33.9%) | 433 (5.5%) | **3126 (39.4%)** |

## SUSPECT 根因（破坏性冲突模式，按用户 taxonomy）

| 工程 | 双写者(MULTI_WRITER) | RMW 交叉 | CPU↔DMA 写重叠 | 多字段一致性 | 位域 | 宽度/对齐不可证明 |
|---|---|---|---|---|---|---|
| klipper | 22 | （含于左） | 0 | 16 | 0 | 0 |
| blackmagic | 28 | （含于左） | 0 | 93 | 0 | 0 |
| betaflight | 2693 中的主要构成：MULTI_WRITER ≈2264、DMA ≈318、其余为一致性/宽度 | | | | | |

## UNKNOWN 根因

| 工程 | RELEVANT_MISSING_TU | EXECUTION_CONTEXT | ADDRESS_ESCAPE | DMA_LIFETIME |
|---|---|---|---|---|
| klipper | 12 | 6 | 4 | 0 |
| blackmagic | 25 | 51 | 13 | 1 |
| betaflight | 297 | 85 | 81 | 9 |

## 根因解释与不可静态消除的原因

1. **双写者（最大桶）**：同一变量被两个物理域写（含 RMW）。betaflight 的
   飞行栈按设计共享（陀螺仪 EXTI 写 → PID 任务读改写；USB VCP 双指针环形
   缓冲；blackmagic 的 DFU/USB 栈）。两个写者交错即丢失更新，静态无法证明
   串行化 → 必须复核。
2. **多字段一致性**：同 root struct 的多个字段被一个域修改、另一域在同一
   函数内成对读取（value+valid、state+length 协议模式）。撕裂的字段组合
   无法用字段敏感分析排除（这正是 field-sensitive 降噪的守门规则）。
3. **CPU↔DMA 写重叠**：HAL DMA 契约恢复的缓冲区被 CPU 在 DMA 活动期写入。
   双缓冲/半缓冲协议需要运行期事实，静态保守保留。
4. **UNKNOWN_EXECUTION_CONTEXT**：`t->tc->unlink(...)` 两级堆指针链使
   points-to 无法收敛回调目标；其执行上下文（进而写者集合）诚实保留为未知。
   这是当前流不敏感 points-to 的表达能力边界。
5. **UNKNOWN_RELEVANT_MISSING_TU**：声明存在于闭包、定义由链接库/汇编提供
   且不在编译数据库中——无法证明其不访问该变量。
6. **UNKNOWN_ADDRESS_ESCAPE**：地址流入无实现函数（HAL 弱符号、外部库）。

## 降噪贡献（coverage['classification_quality']，每次运行生成
`.ecra/classification_quality.html`）

原始共享写候选（≥2 物理域且一方写）经以下规则精化：

- SAFE_SINGLE_FOREGROUND：前台串行域合并（含 reset 链修正）——betaflight 1322+、
  blackmagic 引导链 240 函数整体归并。
- SAFE_MULTI_CONTEXT_READ_ONLY / SAFE_READ_ONLY：全读者证明。
- SHARED_NO_REVIEW：单写者 + 只读者 + 原子宽度（betaflight 180、blackmagic 9）。
- SAFE_SINGLE_IRQ / SAFE_EFFECTIVE_PROTECTION / SAFE_INIT_ONLY_WRITE 等。

保留量（SUSPECT + UNKNOWN）即上述破坏性模式与证据缺口，未为比例牺牲判定标准。
