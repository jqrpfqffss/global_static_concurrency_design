# R2b完整回归与INAV v13标准完整包：最终实测

本页补充78号、75号当时尚在执行的任务；原观察收据保持原字节。完整重构仍未完成，`all_gates_passed=false`。这些冻结运行不包含本页之后的R2c源码。

| 阶段 | 实测结果 | 状态 / 收据 |
|---|---|---|
| 冻结v39，源码`0aa9363`，3631文件 | 1439项，1437通过、2项真实联网opt-in跳过，1981.792秒；源文件差异0 | PASS_SCOPED：[完整收据](evidence/full-regression-studio-v39.json) |
| 同冻结源、原路径/原字节F030 | 4 TU，2 PARSED / 2 PARTIAL；完整有序事实和既有规范化报告差异0/0；原配置、固件、引擎SHA均不变 | PASS_SCOPED：[原生对照](evidence/native-exact-f030-v39-v1.json) |
| 冷原生INAV v13，冻结v32/`49960e0` | 与原始固定seed0的完整事实和报告差异0/0；没有重跑或改标为v39 | PASS_SCOPED：[语义、完整包](evidence/inav-seed0-v13-complete-package-v1.json) |
| v13标准完整包及独立严格导入 | 4,008,150,203B；导出3299.719秒，导入2432.016秒；全对照/归档/导入8609.688秒；源DB不变 | PASS_SCOPED：[执行资源及保护](evidence/inav-seed0-v13-complete-package-execution-v1.json) |
| v13计入标准包的稳定保留策略 | 分配47,665,101,856B → 14,363,963,800B，降低69.86482092623099%，未满足整数70%门限 | **FAIL**：[策略](evidence/inav-seed0-v13-standard-retention-v1.json)、[完整测量](evidence/inav-seed0-v13-standard-retention-measured-v1.json) |
| 独立512MiB只读页缓存实验，冻结v33/`5bcfa01` | 旧原始图与冷v12完整图，完整深校验/事实/报告0/0；69103.422秒，Job峰值614,744,064B；输入和引擎SHA不变 | PASS_SCOPED：[独立读取](evidence/inav-seed0-v12-reader512-final-v1.json)；**不宣称提速** |

v13完整标准包：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/inav-seed0-v13-comparison-package-v1/inav-seed0-v13-full.ecra-report`。SHA-256：`f3279b067b4b01e872a6769ce564c11ed9b72c24f075cd4faa1d7f6aab671118`。严格导入使用单独的数据根，绑定保留原有`UNVERIFIED`状态，没有自动授予当前源码可信性。源DB的完整SHA保护成功。

归档/对照阶段的2GiB受控Job实际峰值141,021,184B，RSS峰值134,623,232B；这是归档任务，不能冒充原生扫描内存。扫描阶段实际数据如下：

| 固定输入生产者 | CLI秒 | Job峰值B | RSS峰值B | 扫描输出采样分配峰值B | 完整事实/报告 |
|---|---:|---:|---:|---:|---|
| 原始e69 seed0 | 15454.922 | 29811765248 | 29559390208 | 46538663768 | 黄金基准 |
| 冷v12，v27/`1493c05` | 31846.532 | 10687008768 | 10618966016 | 18794582808 | 0/0 |
| 冷v13，v32/`49960e0` | 55454.500 | 10692485120 | 10625884160 | 18795702152 | 0/0 |

同一64GiB Windows主机/机械盘存在并行读取及测试，耗时不代表隔离环境性能。采样分配峰值只覆盖记录范围，是全盘历史峰值的下界；不能据此关闭G4，也没有物理32GiB主机证明。完整策略含相同common build和一份完整标准包，未删除原备份/对照库/独立导入/旧包；它们作为实验副本的排除范围见原始策略。旧v12 compact包71.6497%的实测仍只属于[65号](65-complete-compact-archive-retention.md)，不能用于把本次69.8648%改判通过。

最新版已封存Portable仍为[v37](77-frozen-v37-acceptance.md)，其源码为`7066dea`；v39是R2b源码回归，未凭空成为新Portable。R2c内部完整执行、正式dirty/Diff/恢复、其余消费者、确认继承、整根迁移及UAT继续按[68号](68-remaining-refactor-execution-plan.md)、[76号](76-dirty-production-integration-audit.md)推进。其他真实工程用户延期、物理机/DPI/独立第二PC/真实联网模型/工程师盲测继续待验。
