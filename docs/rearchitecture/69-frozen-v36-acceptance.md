# v36实际Portable、完整大图导航与千项续批

2026-11-04。冻结源码 `176ed696e34354593ff2bc5aa800972a641d152e`，3050文件、manifest SHA `ca27507d93b9bfa527e65a3ee06cf99e63a158fc1297135207b24e14c743dc8d`。这是[67号队列](67-frozen-v36-validation-queue.md)后续实际完成结果；原观察收据仍保留，不把原待验时间点改写成通过。

| 阶段 / 功能 | 实际验证 | 状态 / 证据 |
|---|---|---|
| Phase6完整回归 | 1408项，1406PASS、2联网opt-in SKIP，1987.622s；冻结源及测试副本全部SHA不变 | [完整回归](evidence/full-regression-studio-v36.json)，PASS_SCOPED |
| Phase2真实F030 | 原配置4TU，2PARSED/2PARTIAL及INCOMPLETE保持；全字段有序、有类型事实和既有规范化报告差异0；输入/引擎字节不变 | [原生对照](evidence/native-exact-f030-v36-v1.json)，PASS_SCOPED |
| Phase4/5实际包内操作 | 21普通Chrome组+1实际owned VHD组，共174个重叠断言；含新证据归属4、容量/文本11、调用加载/重试示例12、双完整编码下载5；实际磁盘满后完整性及中文恢复4 | [完整封存](evidence/portable-studio-v36-seal.json)，PASS_SCOPED |
| Phase6分发及CLI | 31328份分发文件完整SHA、129运行时与源匹配；目录及中文ZIP解压各27CLI命令，其中21exit0、6预期INCOMPLETE exit2 | 同封存；不是干净离线物理PC验收 |
| Phase4大型完整归档 | 实际v36 ECRA.cmd读取严格导入的冷v12完整压缩包；5访问、main/SysTick、113冲突、5423相关边/1486页、真实调用见证/未知NVIC/归档RMW源码全部6组通过 | [大型6组](evidence/native-inav-evidence-ui-v36-v1.json)、[驱动](evidence/native-inav-evidence-ui-v36-v1-driver.json) |
| Phase4/U16 | 旧3000声明的独立副本再新增1000个不同对象的NEED_MORE_EVIDENCE，350/700/1000三次实际重启；4000事件、计数/筛选/位置及18GB静态图SHA保持；原根3000及其人工库不变 | 2284.891s，[千项](evidence/review-fourth-batch-v36-v1.json)、[原根/控制器验证](evidence/review-fourth-batch-v36-v1-driver.json) |

Windows入口：`H:/ECRAStudio-build-20261104-studio-v36/ECRA-Portable/ECRA.cmd`。软件ZIP为724567087B，SHA-256 `42a3110189c6f71cd7dedc995deb6c6e81ef78c9cdefd80827152c4d13baf805`；这是软件分发大小，不是大型扫描结果包。完整大型结果包3157389743B及最终保留策略71.6497%另见[65号实测](65-complete-compact-archive-retention.md)。

v35普通集合也实际通过：1408项1406PASS/2SKIP、1910.258s，21组168重叠断言；31309分发文件。软件ZIP723454240B，SHA `529db6a6ec929bdb650664f26ca0bcd2204c95d7af90b7c02292c130fa4215c6`，见[原封存](evidence/portable-studio-v35-seal.json)。但它仍有额外真实探针发现的[证据串入FAIL](evidence/portable-v35-additional-release-readiness.json)，没有据较早集合宣称无已知缺陷；v36在实际包内重新通过同一归属控制器。

U01–U24最新逐条状态为 **14PASS/10NOT_VERIFIED**，见[矩阵](ui/36-user-scenario-status-v36.md)。U12/U13来自本包实际读取v27生产的原生归档，U16来自本包新续批；不能混作v36新原生扫描、物理第二电脑、原生系统DPI或工程师满意度。千项控制器仅将版本标签从v32改为v36，完整3000+1000、三次重启、静态SHA和原事件合同不变，两个控制器SHA均写入驱动收据。

截图：[本包全部操作](ui/screenshots/portable-v36/)、[大型原生证据](ui/screenshots/native-inav-v36/)、[千项续批](ui/screenshots/review-fourth-batch-v36/)。这些实际Chrome图像与数据库断言是自动化功能验收，未开展工程师盲测。复现命令在[66号](66-evidence-request-identity-and-retry.md)、[67号](67-frozen-v36-validation-queue.md)及对应收据的argv中；所有重验必须使用新的work/evidence目录。

整体仍未完成。当前writer64MiB冷原生v13/49960e和独立512MiB完整读取/5bcfa01仍执行中；当前完整G4峰值未闭环。其他G2工程用户延期，物理32GB/第二PC/干净离线/DPI、真实联网OpenCode/UAT继续待验。剩余代码与实施顺序见[68号详细方案](68-remaining-refactor-execution-plan.md)，不能由本包局部通过关闭所有H/G或Phase。
