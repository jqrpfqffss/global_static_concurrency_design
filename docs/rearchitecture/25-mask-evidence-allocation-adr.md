# ADR-019：保护观察与窗口证据的只读物理共享（实施中）

## 实测起点

原INAV全388TU严格缓存重建探针v4，鲜预处理/闭包校验后恢复388个真实匹配缓存，原cache零写入。分类准备开始前Private12043042816字节；首变量前traced live4893393440字节，tracemalloc自身1214703792字节，快照等仪器使Job峰值23077654528字节。1587.031s后计划停止，没有静态库/有效报告。因此不是新Clang全量、G1/G2/G3、32GB真机或独占性能验收。

实际分配点包含：逐访问路径映射两处约1013434632字节、contexts排序267960848字节、保护观察577244520字节、窗口node_ids等571124808字节、最终mask_windows记录371102528字节。语句位置包含Python容器扩容/构造的分配，不把reachability赋值点的925615456字节误说成单个状态字符串占用。ADR-018已单独实现路径外层共享，当前v20回归和实包仍在验收，不能以本诊断提前宣称资源门禁通过。

## 语义不变合同

只替换保护证据的物理分配：观察字典、整数节点列表以及窗口记录的dict布局。保留MaskAnalysis原控制流、join/transfer/evaluate、原递归/步数/未知门禁、NVIC/PRIMASK/BASEPRI/faultmask判定、重复观察次数、每个窗口的全部节点及其顺序、窗口数量/顺序、access到观察的关联。不得合并逻辑行，不合并不同上下文/配置/节点/寄存器状态/complete值，不按变量名或访问名继承证明。

新增有界只读复用器：确切内建str键和None/bool/int/str值用完整有序且带类型的键复用整个观察字典；浮点（包含负零）、未知对象或容器旁路共享。整数列表仅接受确切内建int，哈希命中还比较完整列表，碰撞只能减少命中，不能误合并；bool/float不因Python相等而混入整数。两份LRU各最多4096项，逐出只失去加速，不丢事实。

所有返回值仍为原生dict/list。最终含列表的mask_windows记录不共享整个字典，只用已有RecordDicts创建独立dict、共享schema键；原字段插入顺序、未知字段及值引用保持。每条观察仍照原逻辑append，不删重复。原node_ids、mask_states、mask_windows消费者仅查询/遍历，未发现就地修改；若未来消费者需修改，必须先独立复制并重验本合同。

## 必须验收

冻结完整原protection.py及其SHA，独立运行原/新MaskAnalysis对同一完整CFG和访问数据；覆盖分支/循环/递归、上下文/allowed_contexts、缺CFG/未匹配访问、未知调用/不确定控制流、寄存器保存恢复、同符号多访问、RMW、完整重复与顺序。另测typed共享旁路、强制列表哈希碰撞及有界索引逐出。实际同输入F030全字段与严格report对照、完整冻结套件及真实大型实测仍必须通过，不能借用v19/v20收据。无实际大型收益时继续NOT_VERIFIED，不降低门禁。

当前实施中；完整重构、G3和其余尚缺项未完成。v20实包不包含本改造。


## 当前实际验收

| 范围 | 实测结果 | 状态 / 证据 |
|---|---|---|
| 原INAV分配探针 | 388真实严格缓存命中、零miss/corrupt，原890引擎文件SHA及4123输入stat前后不变；不重复声称本轮4123全SHA，之前v1全SHA独立保留；退出1为计划停止，无scan.db | 诊断PASS，[v4原始收据](evidence/inav-preclass-allocation-v4.json)。v3日志多线程tmp冲突FAIL仍[保留](evidence/inav-preclass-allocation-v3-failed.json) |
| 独立原模块对照 | 5项PASS、含10种CFG/遮罩/递归情形、25组seeded完整比较、重复access_id/未匹配/缺CFG、类型/顺序/负零/未来字段、强制列表hash碰撞/逐出 | [专项](evidence/mask-evidence-focused-v1.json)，原模块以LF规范源码SHA固定，跨Git换行不影响校验 |
| 既有保护/for-CFG/旧值覆盖/NVIC/完整调用图交互 | 96项中95 PASS、1项真实联网OpenCode opt-in SKIP，22.616s | [交互回归](evidence/mask-evidence-interactions-v1.json)；不是完整1307项冻结回归 |
| 实际同输入F0304TU | 原配置路径/原字节/编译闭包/工具链，42.219s，预期INCOMPLETE exit2；完整facts及严格规范report差异0，42原输入与92引擎文件不变 | [实际原生](evidence/mask-evidence-native-exact-v1.json)，未调整归一化 |
| 容量CFG/25000访问/50000观察/10000窗口 | 全字段有序摘要相同；保留Python分配24343336→3879227字节，峰值35156416→14765906；带tracemalloc运行1.156→1.750s | [容量收据](evidence/mask-evidence-capacity-v1.json)。不宣称速度提高，额外查找有CPU代价；不外推真实大型G3或G4 |
| 全部1307项/新实包/大型冷原生 | 尚未完成，另需冻结后实际运行；v20只含ADR-018 | NOT_VERIFIED；原G3 FAIL仍有效 |

开发机复现：`py -3.10 -m unittest tests.test_mask_evidence_allocation tests.test_protection_index tests.test_controlflow_for tests.test_stale_writeback tests.test_nvic_recovery tests.test_call_graph_scaling -v`；容量命令：`py -3.10 scripts/validate_mask_evidence_allocation.py --work <新的独立诊断目录> --symbols 5000`。实际原生对照以收据原配置/输入和`scripts/compare_native_graphs.py`为准，不可用不同宏/路径替代黄金输入。
