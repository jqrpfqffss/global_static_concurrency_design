# ADR-023：完整图校验改为有序流（源码专项通过，整体验收中）

原完整INAV图实际约1890万节点、15690万边。旧校验器逐节点查询子边、标量边与重复键；小标量也单独读取。此改造只调度校验读取，不能减少验收字段、关系、覆盖、哈希范围或改变归一化，不能据此标G1/G6完成。

冻结3cf2ff9原完整validate方法于`tests/fixtures/v3cf_validate.py`，包括已修复的空/1MiB标量字节边界；编码/哈希/投影辅助函数不改。完整原方法LF源码SHA以夹具ORIGINAL_LF_SHA256记录并校验。新旧对同一库分别验证，任一负例不得因批量读取而被接受。

合同：同一只读事务保留integrity_check、真实外键、唯一扫描与权威根检查。以按nodeID排序的节点流和按(parent,ordinal)排序的全部边流归并，逐边完整哈希、检查类型/序号/长度/键、标量非法边、遗留孤立边。小标量最多4096字节随元数据取出；大字符串仍逐1MiB验证完整UTF8和哈希，SQL实际BLOB类型/长度先核对；原大整数/浮点解码行为不改，不据此宣称所有未知非字符串标量都恒定内存。

每个对象最多保留4096个重复键加速项；超过后改用原SQL完整GROUP BY检查，不截断对象。全部查询投影仍按原file-backed索引完整重建逐行对照；临时投影索引原先不复制nodes，原scratch外键设置不变，权威库外键检查保留。生产不关闭同步、外键或完整性门禁。

必须覆盖：真实旧/新schema、所有类型/Unicode/负零/大整数、空/1MiB/跨块/大文本、重复键的加速上界前后、非连续/多余/缺失边、错误类型/声明长度/哈希、坏投影与假根、只读事务一致性；独立旧函数接受/拒绝一致。另需SQL语句计数和实际分配容量验证，不能以查询变少直接断言大型提速。真实F030完整同输入对照、完整冻结回归、新实包与完整大库实际验证各需收据。当前NOT_VERIFIED。

## 实际已验范围

| 项目 | 当前结果 | 证据/限制 |
|---|---|---|
| 原函数固定 | 原完整方法LF SHA 2ae0baba1580a5d7392fc6a1ef47c86edc48632fc756328c5ffb42ea4633be13，独立执行其原循环与全部投影检查 | 新夹具SHA测试通过，编码/投影辅助函数未改 |
| 独立/既有完整性与包回归 | 42项PASS、26.623s，新增8项独立旧/新对照；20组seeded完整对象、重算全部祖先哈希的非规范编码、0/4KiB/1MiB边界、4096/4097/5000键重复、坏边/投影/根、真实WAL并发提交快照均通过 | [专项](evidence/stream-validation-focused-v2.json)。另补BLOB子哈希类型负例单项PASS，原/新均拒绝；完整冻结套件仍须运行 |
| 旧消费者 | 流式/旧迁移/保存/正式扫描43项PASS、115.123s | [消费者](evidence/stream-validation-consumers-v1.json) |
| 12000对象容量图 | 源库SQL 96032→23，完整绑定一致且源字节不变；tracemalloc峰值66412→363678字节，额外键集合保持有界 | [容量收据](evidence/stream-validation-capacity-v1.json)。两轮均带trace与SQL计数、原先新后、热缓存不同，2.594→1.297s不外推为大型提速，不宣称内存减少 |
| 实际F030同输入 | 完整facts/严格report差异0，42原文件与93引擎文件不变，原配置d13805...不变；预期INCOMPLETE exit2，含验证38.844s | [真实原生](evidence/stream-validation-native-exact-v1.json)，不改归一化/未知策略，不是大型G1/G3 |
| 完整1330冻结回归/新Portable/完整大库 | 下一步需独立冻结实际运行，不能借v23包收据 | NOT_VERIFIED |

开发复现：`py -3.10 -m unittest tests.test_integrity_validation_stream tests.test_scan_schema_layout tests.test_scan_store tests.test_report_package -v`；容量：`py -3.10 scripts/validate_integrity_validation_stream.py --work <新的独立目录> --objects 12000`。完整验收使用实际冻结源和`unittest discover -s tests -v`。未接入的空间压缩仍见[设计合同](31-owned-storage-compaction-contract.md)，不属于本实现。


2026-11-02后续实际验收：本schema3/流式校验源码aac467f已进入[v24实包封存](evidence/portable-studio-v24-seal.json)，完整1330项1328PASS/2联网SKIP、13组112项真实Chrome与额外5项实际崩溃/重试通过。上表原待验保留为当时状态；本次只关闭该冻结源码的本地回归/打包子范围，完整大型库/G1/G3/G4仍待真实生产结果。
