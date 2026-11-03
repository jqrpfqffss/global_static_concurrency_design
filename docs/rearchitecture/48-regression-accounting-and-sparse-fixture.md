# v28完整回归失败、真实空洞夹具及计数修复

2026-11-03。实际冻结v28/f747643、2185文件在独立副本执行完整回归，2009.813s：**1371项＝1368PASS＋1FAIL＋2联网SKIP**；源/测试副本文件SHA差异0。不得记为完整通过，不构建或封存v28实包。原日志、原失败、原汇总收据均保留，不用本轮20项专项代替完整重跑。

| 实测 | 结果与证据 |
|---|---|
| 唯一失败 | NativeMetricsTests.test_actual_sparse_file_allocation_is_smaller_than_logical_length_and_disappearing_root_is_partial：逻辑256MiB，实际分配30277632B，超过原断言16777216B。[核算收据](evidence/full-regression-studio-v28-failed-audited.json) |
| 原汇总脚本错误 | 只匹配OK(skipped=...)，失败轮漏算skipped，并把全部tests误填为passed_tests。原文件没有覆盖；新增核算收据引用其SHA并列出错误字段，依据未改动原日志修正为1368/1/2。原passed=false/exit=1仍正确。 |
| 独立真实文件诊断 | 三个新建私有临时文件，原构造各分配1048576B，显式空洞后均65536B；payload回读正确。[实测](evidence/sparse-fixture-allocation-v1.json) |
| 修复范围 | 仅测试夹具：truncate后使用fsutil sparse setrange明确创建整个零区，再写已知payload并fsync；增加首尾零字节及payload回读。原256MiB逻辑长度、<逻辑长度/16的严格分配阈值保留。未改FileAllocation、生产空间计数、NTFS压缩策略或任何旧/新实际扫描产物。 |
| 联合专项 | 20PASS、0SKIP、4.610s；真实分配/硬链接/PDH、原压缩/策略与新增回归计数测试。[收据](evidence/native-allocation-receipt-focused-v1.json) |
| 后续完整回归 | 新增v1调用查询1项、表单/Git4项、计数3项后预计1379项；新冻结及实际结果待验，不能借1371旧源失败轮或20项专项记为通过。 |

稀疏标志本身不保证普通写零不分配簇。Microsoft要求应用通过FSCTL_SET_ZERO_DATA维护空洞；fsutil sparse setrange是官方提供的指定零区操作。这里修正的是夹具前提，并未从历史实测磁盘占用中减去预分配空间，也没有将G4阈值放宽。[Sparse File Operations](https://learn.microsoft.com/en-us/windows/win32/fileio/sparse-file-operations)、[FSCTL_SET_ZERO_DATA](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_set_zero_data)、[fsutil sparse](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/fsutil-sparse)。CRT扩展文件追加零字节有官方说明，但本轮未跟踪原失败进程的底层I/O，不能断言其30277632B全部来自某次CRT调用。[Microsoft _chsize_s](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/chsize-s)。

新增scripts/unittest_receipt.py只解析最后一次完整Ran/OK/FAILED摘要，分别核算失败、错误、跳过、预期失败和意外成功；缺摘要、重复/未知计数、互相矛盾的终态均拒绝。释放门禁还必须独立要求实际exit_code=0、精确测试/跳过数和冻结源SHA不变。tests/test_unittest_receipt.py覆盖旧OK后新FAILED、失败轮skipped、缺失/重复/不一致日志，不能只看测试总数或早先OK行。

新原生v12仍使用已通过1369完整回归的冻结v27源；本轮修复既不注入该运行进程，也不把它改名为v28/v29原生扫描。原G1差异及G4未达70%的历史FAIL保留；新受控G1和新完整保留策略仍须等实际运行完成。

后续已实际执行：700befd/v29冻结2229文件，独立完整回归1379项**1377PASS/2联网SKIP/0FAIL/0ERROR**，1923.089s，源与测试副本SHA差异0；[实际收据](evidence/full-regression-studio-v29.json)。这关闭本轮稀疏夹具/计数修复的完整回归问题；不抹去v28失败，也不覆盖后续原生下载/复选框变更。新1383项当前源仍须另冻结验证。
