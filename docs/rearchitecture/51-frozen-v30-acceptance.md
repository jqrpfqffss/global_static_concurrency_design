# Portable v30：冻结源码、完整回归与真实浏览器验收

实际冻结运行时`bdfc050981d2b9ba7dd6ec5dfb4f6bf61cbabb85`，2260个冻结文件，清单SHA`ea3c2f827ac4025fad02c878429e4c730fedb1a5cb717bc3216ad514db38844d`。包含旧调用边归属修复、冲突分页原子显示、未提交选项的明确生产阻断/可取消、空洞夹具与失败计数修复、浏览器原生下载。后续磁盘满中文提示和历史对象对比不在此包。

| Phase/验收 | 实测 | 状态/证据 |
|---|---|---|
| 完整冻结回归 | 1383项：1381PASS、2项真实联网opt-in SKIP；1896.978s；冻结引擎与测试副本全部SHA无变化 | [PASS限定范围](evidence/full-regression-studio-v30.json) |
| 原生F030同输入对照 | 真实4TU、相同原配置路径/字节、原固件/编译库/工具；完整有序类型事实根49e91182…、既有规范化报告根62fd77e0…均一致；2PARSED/2PARTIAL及INCOMPLETE保留；CLI33.969s，含验证包络38.578s | [PASS、差异0](evidence/native-exact-f030-v30-v1.json)，不是大型G1 |
| 实际构建 | 2203.016s；目录/中文ZIP解压各27CLI（21正常0，6预期部分覆盖2）；构建源SHA无变化 | [构建](evidence/portable-studio-v30-build-v1.json)、[目录CLI](evidence/portable-v30-cli-uncompressed.json)、[ZIP CLI](evidence/portable-v30-cli-zip-extracted.json) |
| 19组真实Chrome | 152个有重叠的功能断言，使用本包Python3.10.9/真实Windows Chrome；不是152个独立完整用户场景 | [完整封存](evidence/portable-studio-v30-seal.json) |
| 分发/源码绑定 | 30549个分发文件全SHA核对；128个运行时源码/前端/许可文件匹配冻结源码；ZIP大小657050351B，SHA见下 | [核对](evidence/portable-v30-files-verification.json) |
| 真实磁盘满后续 | v30完整性/恢复子范围通过，但实际错误仅英文，可操作性FAIL。源码修复另验，不能改写本包结论 | [50号记录](50-real-disk-full-and-recovery.md) |
| 全部H/U/G门禁 | 未完成。未提交输入正式隔离、生产强制写保护、全数据根迁移、自动确认继承、大型G1/完整归档占用、其他真实工程、物理32GB/双机/干净离线/DPI/UAT等仍未齐 | FAIL/NOT_VERIFIED，未声明发布完成 |

| Chrome组 | 断言数 | Chrome组 | 断言数 |
|---|---:|---|---:|
| preflight | 16 | sample | 11 |
| main | 17 | legacy-degraded | 6 |
| profile | 7 | contexts | 8 |
| directories | 7 | git | 9 |
| capacity | 9 | coverage | 8 |
| legacy | 6 | collaboration | 7 |
| launcher | 4 | history | 8 |
| data-root | 6 | crash-recovery | 5 |
| storage-policy | 8 | native-download | 4 |
| inav-original-navigation | 6 | 合计（重叠断言） | 152 |

INAV导航组读取真实原版比较图，完整113冲突、5423相关边等导航；旧图没有归档源码，实际显示原源码不可用。不能将它改称v30新原生INAV包或补造源码。1000项确认未在v30重跑，历史v23批次收据独立保留。

实际入口：`H:/ECRAStudio-build-20261103-studio-v30/ECRA-Portable/ECRA.cmd`。ZIP：同级`ECRA-Portable.zip`，SHA-256`a7e5f6d1e9b3cee21d65be47136eddbd7c5b4b3cdab58a29120a4792a48bdb1f`。构建与大型测试/备份共用机械盘，耗时不是隔离性能基准；构建父进程启动时IO_LOW，随后明确改为IO_NORMAL，CPU仍BelowNormal，[调整收据](evidence/v30-build-priority-adjustment-v1.json)保留，不声称所有后代一直低优先级。

实际截图：[历史检索](ui/screenshots/portable-v30/history-01-real-native-archives-page-one.png)、[完整包原生下载](ui/screenshots/portable-v30/native-download-01-real-complete-native-browser-download.png)。各组机器收据和完整PNG目录均在[evidence](evidence/portable-studio-v30-seal.json)逐项绑定。
