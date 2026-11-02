# ADR-021：显式版本的紧凑复合主键布局（源码专项通过，完整验收未完成）

## 原因与边界

完整原版INAV图17,831,825,408字节。当前正式schema2的edges和records使用普通rowid表加复合唯一主键索引；四个record查询索引也包含无对应ID的空行。F030完整独立副本试验将这两表改为WITHOUT ROWID、四索引改为`WHERE <ID> IS NOT NULL`，全字段/完整投影对照一致，物理字节10,665,984→8,044,544。该试验不是生产格式、完整大工程收益或G4通过；原标准包校验器实际拒绝该陌生布局。没有改旧库或固件。

原物理schema完整冻结于`tests/fixtures/v23_scan_schema.sql`，实际生成的LF规范UTF8 SHA `70454bb86688f090e98669d587ba11623a1c22419cd9eb2ab63a0f2fcc6360a9`；使用Python通用换行读取校验，避免Git平台换行误报。本ADR先定义合同，实际验收前不得标记已完成。

## 实现合同

- 新写入使用schema3；v1/v2继续使用原精确SQL白名单读取/校验，旧库/旧包不自动原地转换。由版本注册表选择对应物理schema，不对未知SQL或未知版本放宽校验；JSON布尔值不得当作整数版本。
- 仅edges的`(parent,ordinal)`、records的`(dataset,relation,ordinal)`改为WITHOUT ROWID；nodeID/根/节点哈希/标量BLOB/所有字段与完整逻辑关系保持。所有原排序、重复次数和未知字段保留，不依赖这两表的私有rowid。
- 四个record索引只省略其对应ID为NULL的项。表中所有NULL行仍保留；IS NULL、无过滤、分页计数仍须返回全部正确行，不以索引未收录为理由漏事实。
- 外键、唯一性、安全同步、事务和完整深检保留；不关闭FK或用样本代替完整哈希/查询投影。`nodes`仍保留INTEGER PRIMARY KEY rowid，既有GraphWriter/流式标量/GC扫描消费者不变。
- import/export、authority审计脚本均按数据库版本选精确schema；修复版导出须在产生标准包前拒绝未知布局，不能导出一个正式读取器会拒绝的库。

调用审计：权威/业务查询按明确dataset/relation/ordinal或parent/ordinal访问；未发现edges/records rowid消费者。`garbage_collection._tokens`在静态库只扫描nodes.value，其他rowid扫描针对独立人工/AI表；它们不改布局。受保护的扫描算法与GraphWriter逻辑不变。`report_package`和`validate_large_report`必须同步使用版本注册表。

## 必须通过的验收

| 项目 | 门禁 | 当前状态 |
|---|---|---|
| 独立旧SQL | LF规范SHA固定，v1/v2旧布局完整包往返；真正的内置schema2教学包仍按2读取/再导出，原资产SHA不变 | PASS，[专项34项](evidence/compact-layout-focused-v1.json)，其中7项新增格式/结构回归；v1为结构兼容夹具，不冒充真实旧发行归档 |
| 新布局 | 完整有序typed根/全部nodes/edges/records行及查询投影与独立旧DDL副本一致，NULL/重复/未知字段保留；原有8MiB有界标量测试继续通过 | PASS，同34项；SQL类型/逻辑数量和完整顺序未改变 |
| 版本/恶意输入 | 假版本、布尔版本、重算数据库摘要但混用物理布局、未知SQL导入/导出拒绝；有效旧库/人工历史不变 | PASS，同专项；导出先进行精确schema校验，不产生正式读取器会拒绝的包 |
| 旧消费者 | 流式证据、旧迁移、保存消费者、正式扫描43项，115.385s | [PASS](evidence/compact-layout-consumers-v1.json)，不是完整1322项 |
| F030真实原生 | 原配置SHA d13805...、编译器/宏/42原文件/93引擎文件前后不变；facts 49e91182...与严格report 62fd77e0...均差异0；预期INCOMPLETE exit2，驱动含验证25.375s | [PASS](evidence/compact-layout-native-exact-v1.json)，不调整归一化，不代替大型G1/G3 |
| 冻结完整1322回归/新Portable | 必须绑定本源码，不能借v23包收据；还需结合实际物理空间策略验收 | NOT_VERIFIED |
| 完整大型物理占用/性能 | 原数据不变，实际库和整项策略计量；未达70%仍记FAIL/待优化 | NOT_VERIFIED |

v23冷原生和第三批确认继续绑定c311aa4冻结源；其结果不包含schema3。新候选仅在本表所需实测通过后独立提交/冻结，不将局部约25%布局试验误报为70%全策略收益。

## 原始全图的真实空间归因

[全量B-tree收据](evidence/graph-storage-attribution-v2-audited.json)：原17,831,825,408字节图，edges表5,636,194,304、其复合主键索引2,777,784,320、edge_child索引2,259,456,000、nodes表2,184,257,536、node hash索引1,608,056,832字节。原records表1,096,024,064字节；四个record索引分别839,168,000（function）、631,005,184（symbol）、269,492,224（source）、269,479,936（target）。不根据F030比例外推大工程结果。

完整DBSTAT只读查询53.375s，512MiB受控Job峰值86,081,536字节，原图前后完整SHA 660dffb2...不变。宿主原Python缺少DBSTAT，使用已有MSYS2 SQLite3.51.1作为独立观察工具，未替换产品SQLite。[首轮汇总FAIL](evidence/graph-storage-attribution-v1-metric-contract-failed.json)源于误把B-tree总和当成整个文件；差4096字节。[SQLite合同](https://www.sqlite.org/dbstat.html)明确不计空闲、pointer-map和lock页；本文件头实查freelist=0、auto-vacuum=0，一页lock恰解释4096差值。后续审计复用全部原始测量和两次源SHA，未伪装重新运行或改写首轮收据。

[F030完整布局试验](evidence/sqlite-layout-f030-v1.json)是全部字段相同的独立物理副本对照；后续真实原生的归档元数据更丰富，不把两者不同provenance的文件大小直接相减作为格式收益。
