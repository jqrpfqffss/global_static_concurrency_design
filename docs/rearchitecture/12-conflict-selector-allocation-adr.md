# ADR-011：冲突选择器与结果记录的物理分配（实施前合同）

## 已实施的局部结果

已按以下合同修改，仅conflict_pairs的结果编码/分配；11项独立回归通过，另包内CPython3.10.9同11项通过。见[evidence/conflict-selectors-v1.json](evidence/conflict-selectors-v1.json)。3969个inline结果的完整有序JSON相同，Python保留分配3,085,707→2,176,803B；32上下文/12,800访问的496个product结果同样全字段相同，保留分配3,850,608→452,595B、临时峰值14,331,588→5,732,039B。此处基准为冻结e69，包含已存在ADR-009的累计效果；不是单独ADR-011或原生工程的内存降幅。inline采样耗时略增，不声称所有场景加速。

冻结779文件后实际F030原生扫描22.281秒、Job峰值148,512,768B、analysis_valid=true且仍INCOMPLETE；严格比较facts/规范report差异0，哈希分别49e91182…与62fd77e0…。没有修改配置以隐藏部分覆盖。完整回归在单独冻结测试目录运行，尚未预报PASS；同输入新INAV冷提取安排在黄金备份最终复验通过后启动，16GiB受控预算。源/config/build/引擎在执行前逐文件核验；它改用H盘独立数据根，耗时不可直接归因于分配变化。

短字符串intern试验已因完整388TU归并无内存收益而回退，见11-live-string-sharing.md。本实现的冻结源不含该试验。前述16GiB FAIL、32GiB发布中断继续保留，G1/G3/G4仍未通过。

## 原始实施前合同

真实388TU受控16GiB失败栈为analysis.conflict_pairs的participant_b_write_access_ids集合/排序构造（I:/ECRA-N3/scans/native-golden/diagnostics/exception.log）；32GiB诊断分类后Job峰值22,429,601,792B，发布未完成，不能称资源达标。

当前product表示对相同variable/context的读/写access_id每一对上下文都重新排序并保存独立列表；其输入grouped在构造完后不变。改成仅在该变量本次调用内按context构造一次两个完整、原生list选择器，结果行复用它们。依旧使用相同sorted(set(access_id))，不能改访问去重规则、排序、次数、完整路径或4096阈值。只在product分支需要一个非零pair时创建；不提前对原本不会构造的上下文施加新假设。

同时让inline/product结果用既有RecordDicts建立共享键布局的普通dict，保持关键字原顺序和独立的记录值。任何判断/关系/计数/ID摘要输入都不变。来源访问记录与participant对象的既有行为保留。

已审计消费者：ecra/evidence.py仅把选择器读入新set求并集，diagnostics.py仅判空，scripts/preopencode_benchmark_scan.py仅拼接成新列表；持久化/比较/前端按只读证据读取。没有追加/排序原选择器的消费者。物理共享不能允许后续修改；如发现消费者需要修改，必须在那里复制，不能让一个pair的操作修改另一个pair的证据。

须由tests/fixtures/e69_conflict_pairs.py冻结原函数独立对照全部字段/类型/对象键与数组顺序，包含inline边界、product、serial/reentrant/unknown、重复ID、路径数与witness。新增多域product及接近阈值inline的保留分配测量，不以数量统计代替比较；小型容量结果不得冒称G3。随后实际F030原生全字段比较、冻结完整回归和INAV完整原生门禁。任何未证明差异须撤回；G1/G3/G4在大工程未验前保持未通过。
