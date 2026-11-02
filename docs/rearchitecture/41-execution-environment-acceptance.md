# 固定执行环境与完整校验页缓存：实现验收

2026-11-03（北京时间）。本阶段不修改extract.py、求解器、判定方法或严格比较器；[环境ADR](40-fixed-execution-environment-baseline.md)与[页缓存ADR](38-validation-page-cache-adr.md)给出范围。页缓存只在完整提交后的检查与只读完整校验连接生效，不改变写入同步或事务。

| 实现/验收 | 实际结果 | 收据 |
|---|---|---|
| ECRA.cmd/任务/TU环境 | 未指定/空seed取0，保留显式值，调用者env不被修改；父与子seed/日期epoch写入provenance，不改变facts/report | ECRA.cmd、ecra/cli.py、ecra/studio/tasks.py、ecra/scan_persistence.py |
| TU缓存 | seed或日期epoch改变不能命中旧载荷；旧缓存字节保留；显式random不跨轮命中 | ecra/tu_cache.py、tests/test_extraction_runtime_cache.py |
| 最新49项专项 | 49PASS，44.844s；包含随机seed边界、完整类型/顺序/重复、实际WAL一致读、恶意标量/schema/归档 | [专项v2](evidence/execution-environment-focused-v2.json) |
| 消费者43项 | 43PASS，168.546s；在增加random分支之前执行，最新完整回归仍需覆盖全部 | [消费者v2](evidence/execution-environment-consumers-v2.json) |
| 最新真实F030 | facts/report完整有序、类型敏感比较差异0，33.109s；原输入与95个引擎文件后验无变化 | [原生v2](evidence/execution-environment-native-exact-v2.json) |
| 原消费者控制失败 | 漏加tests搜索路径导致test_saved_json依赖无法导入，31项中1导入错误；不改生产代码，在新v2重跑43PASS | [原失败](evidence/execution-environment-consumers-v1.json) |
| 完整回归/大型成对原生 | v26已冻结2007文件，1355项完整回归正在独立副本执行；尚未启动的v11原生队列已核对身份撤销，改为等待含新空间策略的v27冻结回归后启动；不是已运行扫描被停止 | [未启动撤销](evidence/inav-canonical-seed0-native-v11-not-started.json)，大型对照NOT_VERIFIED |

F030严格facts摘要49e91182b4d91954a3ee18b03068cc70650952ce9366b30179d56815a1987f0f，report摘要62fd77e001bef0561313db0d9d148bab6c29ddf47a4b930bbc813e325a0af4b6，原/新相同。原配置d13805dc...路径/字节不变；仍有真实INCOMPLETE覆盖，不将exit2写成SAFE。

同阶段的独立只读物理空间观察器scripts/measure_storage_policy.py已完成完整根实测，输出位置不能进入任何被测根；[实际边界负例](evidence/allocation-observer-boundary-v1.json)拒绝该重叠且保留原文件。G4仍为40.2058%的FAIL。

另保留[实际低完整性F030探针](evidence/low-integrity-native-f030-prototype-v1.json)：同一原配置真实扫描、Medium哨兵写入被拒绝、全facts/report零差异，146239488B Job峰值。这只是既有GuardedProcess的独立原型；生产任务隔离舱/发布代理/共享缓存/只读CMake/完整MIC审核未接入，H2不得据此标PASS。

复现专项：`py -3.10 -B -X utf8 -m unittest tests.test_extraction_runtime_cache tests.test_bounded_extraction tests.test_integrity_validation_stream tests.test_scan_schema_layout tests.test_scan_store tests.test_report_package -v`。消费者使用现有unittest discovery或显式将tests加入sys.path，避免上文已保留的控制错误。
