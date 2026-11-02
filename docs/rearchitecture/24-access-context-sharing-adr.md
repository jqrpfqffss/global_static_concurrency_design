# ADR-018：访问上下文容器按实际函数/选择条件复用（实施与验收中）

## 约束与审计

原`analysis.py`在分类准备阶段，逐访问构造`contexts`列表、`call_chains`字典、`all_call_chains`字典和`protection_evidence`列表。INAV黄金完整图有1208049条访问；同一函数/相同allowed_contexts下这些容器的内容相同，路径、保护事件本身已经按引用保留，外层容器却重复分配。当前大型诊断在首变量前已超过16GiB，不能只优化数据库发布器；分配诊断另行测量，不能据此先宣布某条语句占用多少。

本候选只减少上述只读外层容器的物理分配。调用恢复、allowed_contexts的成员测试、原映射遍历次序、contexts排序、reachability、原路径/重复次数、完整调用边/循环、保护事件筛选与顺序、by_var原访问顺序均保持。访问记录自身仍独立可变，`MaskAnalysis`新增`mask_states`等字段不影响别条记录。

读取审计：`evidence.py`、`protection.py`、`initialization.py`、`stale_writeback.py`、`git_diff.py`、`review.py`、`html_report.py`、`report.py`及权威发布器读取这些容器，未发现就地修改；原`canonicalize_member_resources`已浅共享内层路径并明确后续只替换访问顶层字段。路径恢复和events构造先于本阶段完成，此后不修改其映射/事件列表。保护事件行本就共享，不改变该约定。

## 实现合同

独立`access_enrichment.py`复用原循环，使用两份最多4096项LRU辅助索引，索引逐出不丢事实，仅允许未来同值再次分配。实际访问仍持有完整容器；不会截断函数、上下文、路径或访问。不将新索引当作持久化/恢复状态。

仅对确切内建字符串函数ID及None/确切内建字符串list/tuple/set/frozenset选择器复用；选择器的重复/排列不影响原成员谓词，缓存键使用frozenset，输出键及次序仍取原paths/all_call_paths。未知对象/自定义成员测试旁路复用，继续逐访问计算。保护列表单独按确切字符串函数ID复用，不根据变量名/访问ID/哈希推测内容相同。

这属于受保护入口的分配调度例外，必须保留独立原循环、原块SHA校验、有序类型敏感全字段/全关系回归、实际同输入F030原生对照与完整套件。没有大型同输入实测前不声称大型G1/G3通过；当前v19实包保持独立冻结，不能把v19收据用于本候选。大型收益不成立或语义有差异时撤回候选，不能调整归一化或阈值。

## 验收状态

| 验证 | 实测结果 | 证据 / 限制 |
|---|---|---|
| 独立原循环 | 5项PASS，含40组seeded完整比较、0..3缓存逐出、自定义动态membership旁路、重复运行与原访问独立字段 | [专项](evidence/access-enrichment-focused-v2.json)。首轮测试错误假设defaultdict不能新增空bucket，原/新都按原语义新增；[失败保留](evidence/access-enrichment-focused-v1-failed.json)，改测原/新后映射一致 |
| 实际F0304TU | 原配置路径/字节/宏/编译DB/toolchain，原生34.359s、预期INCOMPLETE exit2；全部有序typed facts及严格规范report差异0，42原文件与91引擎文件前后不变 | [原生收据](evidence/access-context-native-exact-v1.json)，不是大型G1/G3 |
| 128000访问容量fixture | 保留分配135197861→74780560字节，峰值135201573→74786528；完整有序根摘要相同，全部访问及by_var次数保留 | [容量收据](evidence/access-enrichment-capacity-v1.json)，不将tracemalloc局部指标/带仪器时间外推为原生进程峰值或独占性能 |
| 全部1302项冻结回归 | 待后续实际运行 | NOT_VERIFIED，不能借用v19的1297项收据 |
| 大型同输入 | 原诊断未应用本改造且仍在发布；分配探针独立运行 | NOT_VERIFIED；此前G3 FAIL继续有效 |

完整重构仍未完成。全局工作集、生产H2沙箱及其余未完目标不因本候选自动关闭。
