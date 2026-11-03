# ADR：权威库写入页缓存由8MiB调整为64MiB

2026-11-03，接续冻结30513de/v31。此前388TU新版冷扫描耗时31846.532s，比同环境原版15454.922s更长；共享机械盘/并发备份等影响未隔离，不能将耗时差归因于单一代码点。源码证实发布写入连接仍为`cache_size=-8192`，提交后的完整校验已为`-65536`。

本变更只将**新私有权威库写入连接**改为`cache_size=-65536`。仍使用相同SQLite、schema3、唯一索引、类型/顺序/重复次数、碰撞核对、FULL同步、完整事务、完整校验、无损压缩和独占发布。GraphWriter对象/标量LRU大小不变；没有修改求解、判定、工作线程调度、事实集合、磁盘保留或规范化规则，也没有VACUUM或改写旧库。冻结v27/v31、运行中的原版图转换和严格对照完全不变。

SQLite文档规定负cache_size按当时页大小折算KiB，连接关闭后失效；默认缓存按需分配。它是连接缓存建议值，**不代表整个进程/Job内存上限**；整体资源约束仍由原Job预算执行。[SQLite官方说明](https://www.sqlite.org/pragma.html#pragma_cache_size)。本轮实际SQLite3.40.1，两套连接的真实SQL trace分别记录首次`-8192`/`-65536`；仅观察SQL，不注入替代结果。

| 验收 | 实际结果 | 证据 |
|---|---|---|
| 库/流式导入/压缩/完整包专项 | 48PASS，14.519s | [专项](evidence/writer-cache-focused-v1.json) |
| 同输入真实F030原生重扫 | 4TU，完整有序类型事实49e91182…、既有规范化报告62fd77e0…与原版一致；2PARSED/2PARTIAL、INCOMPLETE保留；原固件/配置/编译库不变；101模块前后SHA不变 | [原生收据](evidence/writer-cache-native-f030-v1.json) |
| 原生时间 | CLI22.797s、含核验25.063s；共享宿主/盘，不作大型加速归因 | 同上 |
| 完整F030图A/B首轮 | 完整facts/report/provenance恢复后重新编码，未采样或截断；8/64MiB输出均8904704B，整库SHA完全相同 | [A/B v1](evidence/writer-cache-complete-f030-v1.json) |
| 可复用脚本实际复测 | 同样整库逐字节一致；源库SHA保持81b4f16b…；完整3根均相同 | [A/B v2](evidence/writer-cache-complete-f030-v2.json) |
| 输出整库SHA | 两轮两种缓存均`3343d0b068c8c7a09a9bb8d2b84f6243cb0774089b63b4c66bd73a4b7a428348` | 同上 |
| 小图编码观察值 | v2写入6.469s→5.641s，Job峰值51273728B→51712000B；不是大型速度/RAM提升证明 | 同上 |
| 大型原生/完整回归 | 新版独立冻结1392项及388TU冷重扫待执行；旧v31的1392项不能冒充本变更已验 | NOT_VERIFIED |

已验源码文件SHA由旧`79409368ca12a3d4625142b58ddbcbc9b155a45d62898257457654e7e50ee219`变为`75de677f1bebf827b6db688f70a039921e18953d021a8d1db62edb7df40fa23e`。原生试验先于提交执行，收据明确`source_worktree_dirty:true`和父HEAD30513de，没有伪称该缓存变更已在v31中。

可复用脚本[scripts/measure_writer_cache_small_graph.py](../../scripts/measure_writer_cache_small_graph.py)只接受不超过64MiB的**完整小图**，超过则在复制/发布前拒绝，绝不生成截断事实。这里允许整图恢复仅供明确的小图编码A/B；生产扫描及大图验证继续使用原生/流式路径，不能把本脚本当成G1/G2/G3大型验收。

```powershell
py -3.10 -B -X utf8 -m unittest tests.test_scan_store tests.test_streamed_evidence tests.test_storage_compaction tests.test_report_package -v
py -3.10 -B -X utf8 scripts/measure_writer_cache_small_graph.py --before-engine H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/frozen-engine-studio-v31 --after-engine H:/global_static_concurrency_design --scan H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/native-exact-f030-v31-v1/data/scans/native-exact/scan.db --work H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/new-cache-ab-attempt
```

收据审计补充：复制v31原生控制器时遗留了旧字面值HEAD bdfc050；实际执行路径是冻结v31、101模块前后未变。原收据不改写，依据2458文件冻结清单及全部101模块摘要生成[独立来源审计](evidence/native-v31-source-head-audit.json)，真实HEAD为30513de。v31最终封存必须使用审计收据并保留原件；这不是重跑原生扫描或改写静态差异结果。
