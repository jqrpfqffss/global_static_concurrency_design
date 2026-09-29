# UNKNOWN 根因聚类（验证进行中）

当前表格为冻结 baseline 的同构建闭包结果；最终新引擎仍需更新。计数是受该 blocker 影响的变量数，多个原因可落在同一变量，因此不能把百分比相加。

| 原因 | Klipper（345 UNKNOWN） | Blackmagic native（674 UNKNOWN） |
|---|---:|---:|
| FUNCTION_ADDRESS | 132 | 481 |
| INDIRECT_CALL | 131 | 469 |
| POINTER_SUBSCRIPT | 132 | 460 |
| POINTER_DEREFERENCE | 104 | 434 |
| UNRESOLVED_POINTEE | 110 | 434 |
| EXTERNAL_CALLEE | 110 | 433 |
| STATIC_INITIALIZER_REFERENCE | 139 | 224 |
| ADDRESS_ESCAPE | 181 | 217 |
| INLINE_ASSEMBLY | 132 | 202 |
| DMA_SHARED_REVIEW | 0 | 3 |

两项目都超过 10% 诊断阈值，必须继续分析；该阈值不用于强行判 SAFE。优先排查静态函数表/注册表关联性、指针间接访问目标、物理上下文继承与无关调用的跨变量传播。具体比例变化需等新引擎跑完，不能把 baseline 高 fanout 本身当作“所有相关 blocker 都无关”的证明。

Betaflight 的冻结 baseline 在 `context_graph()` 的 `all_paths[child][cid].append(child_route)` 发生内存耗尽，因此不存在可用于分类降幅的 baseline 数量。新引擎把显式路径族换成完整调用图存储，避免把分析资源耗尽混成变量 UNKNOWN；这属于分析可完成性的修复，不是降低安全标准。
