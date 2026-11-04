# 固定seed0大型原生v13：实际结束及完整语义对照

2026-11-04。此处是此前排队的冻结v32/`49960e041c5bc9b8a47ce14a5fd387477fa5d210`生产者，不是当前多核GUI或冻结父读取实现的新大型扫描。完整运行收据见[原生实测](evidence/inav-canonical-seed0-native-v13-final.json)、[前置校验](evidence/inav-canonical-seed0-native-v13-preflight.json)、[后置校验](evidence/inav-canonical-seed0-native-v13-postflight.json)、[原控制器](evidence/inav-canonical-seed0-native-v13-driver-result.json)。原子来源仍为冻结清单SHA `ca0eeba91f9f3efe2c2913b1d0153251dc521f48147a89db7e57fe3ff92b337e`。

真实INAV H743同一获准输入388TU/4123项，`PYTHONHASHSEED=0`与既有固定时间环境；CLI在16GiB安全Job中执行，55454.5s后以预期INCOMPLETE exit2结束，`analysis_valid=true`、输入闭包VERIFIED。2465份引擎文件及4123项输入前后均0变化。原始完整e69运行和独立只读备份保持，没有改写旧程序或基线。

原比较器及全部规范化规则未改，在完整typed/ordered原生权威图上做深检查和全字段对照，[结果](evidence/inav-canonical-seed0-native-v13-complete-comparison.json)事实/报告差异均0。两侧完整事实SHA `43153000056630428dd91c4af9787cda65c107f4690814e36b607e21de4696aa`，规范化报告SHA `26af6df2f8a675ef2be0a25f2be4b45c807f1ba2a8cd21a4d7af72aa53ed52db`；不是仅比较metadata摘要、数量或回放已有facts。

| 同输入生产者 | 完整CLI耗时 | Job进程树峰值Commit | 采样进程树RSS峰值 | 输出根采样文件分配峰值 | 完整语义对照 |
|---|---:|---:|---:|---:|---|
| 原始e69固定seed0 | 15454.922s（4.2930h） | 29811765248B（27.7644GiB） | 29559390208B | 46538663768B（43.3425GiB） | 原始独立图/完整原始备份 |
| 冷v12，v27/1493c05 | 31846.532s（8.8463h） | 10687008768B（9.9531GiB） | 10618966016B | 18794582808B（17.5038GiB） | 事实0/报告0，旧记录保留 |
| 冷v13，v32/49960e，writer64MiB | 55454.5s（15.4040h） | 10692485120B（9.9582GiB） | 10625884160B | 18795702152B（17.5049GiB） | 事实0/报告0，完整独立原生 |

原始及v12数值与[62号](62-fixed-seed-full-package-and-size-failure.md)、[65号](65-complete-compact-archive-retention.md)的原收据一致。本次v13采样进程树Private峰值10691432448B，结束时主进程峰值Pagefile/Commit10685960192B；资源字段含义不混用。结束时仅v13数据根文件分配9210574632B、逻辑23371646082B、6129文件；这不是含完整包/共享构建的最终G4保留集合。

运行机器是64GiB Windows及共享机械盘，不是物理32GiB真机；同期存在独立比较、归档与测试I/O。三个耗时均为实际观测，v13没有表现出时间改善，不能将它称为缓存提速或整体性能达标，也不能把差异单独归因于writer64MiB。采样分配峰值是文件层下界，不含目录/MFT/ADS、未观测到的瞬时或打开后删除文件；输出根峰值不包括共同外部构建的完整历史峰值。

| 尚在执行的验收 | 本次观察 / 已有事实 | 状态 |
|---|---|---|
| v13标准完整包与严格第二根导入 | 完整事实/报告对照已通过；打包控制器已进入严格导入阶段，完整结束收据尚未产生 | NOT_VERIFIED_FINAL_PACKAGE |
| v13全范围峰值与最终保留 | 扫描前已启动多根只读观察；最终保留控制器尚未全部结束。不能只拿9.21GB输出根替代全范围 | NOT_VERIFIED_FULL_G4 |
| 独立512MiB只读比较器 | 冻结v33/5bcfa01读取同一原始图与v27冷v12产物，仍运行；不改旧比较器，不取消原验证，不称已提速 | NOT_VERIFIED_READER_EXPERIMENT |
| 物理32GiB/第二PC/离线干净PC/原生DPI/工程师盲测 | 本次没有这些环境/测试 | NOT_VERIFIED |

准确时间点、原路径、当时文件SHA及完整观察对象保存在[进度快照](evidence/inav-native-v13-comparison-progress-v1.json)。这些旧观察不在后续结束时改写；后续须另给最终收据。

既有冷v12完整compact结果包3157389743B，完整保留集合13513190616B对同输入原始47665101856B下降71.649718%，已在65号实测通过；原DEFLATE对照仅下降69.865%且FAIL记录保留。两种编码及独立备份物理上都仍保留，重复编码A/B对照不纳入声明的生产保留集合。不能将这份v27生产、v34包内严格导入的历史compact包改名成v13或当前源码新包；全历史峰值仍未因此闭合。

复现argv与实际配置/工作盘/限额见原生前置和控制器收据。重新执行必须使用新的独立结果根，保持原工程/编译数据库/工具链、固定seed/时间环境和原比较器规则，结束后再做完整语义、严格包往返和一致范围物理分配测量。`all_gates_passed=false`，不是完整G1–G8或全部重构完成声明。
