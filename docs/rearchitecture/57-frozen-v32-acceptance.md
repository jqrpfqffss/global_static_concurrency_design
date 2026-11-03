# Portable v32：有界写缓存与完整本机实包验收

实际运行时49960e041c5bc9b8a47ce14a5fd387477fa5d210，2465文件冻结清单SHA ca0eeba91f9f3efe2c2913b1d0153251dc521f48147a89db7e57fe3ff92b337e。包含v31历史对比、中文满盘恢复和新64MiB权威库写缓存；后续观察工具/第四批控制器/512MiB读取试验不在本包。完整重构仍未完成。

| Phase/验收 | 实测 | 状态/证据 |
|---|---|---|
| 完整冻结回归 | 1392项1390PASS/2联网SKIP，2088.997s，全部冻结/测试副本SHA不变 | [PASS](evidence/full-regression-studio-v32.json) |
| 真实F030 | 相同原配置/固件/编译库/工具，完整有序类型事实49e91182…和既有规范化报告62fd77e0…差异0；4TU、2PARSED/2PARTIAL、INCOMPLETE保留；CLI25.109s，101模块前后不变 | [PASS](evidence/native-exact-f030-v32-v1.json) |
| 构建及CLI | 实际目录/中文解压各27CLI，21正常0、6预期部分覆盖2；不是物理干净机 | [构建](evidence/portable-studio-v32-build-v1.json)、[目录](evidence/portable-v32-cli-uncompressed.json)、[ZIP](evidence/portable-v32-cli-zip-extracted.json) |
| Chrome/VHD | 19组普通Chrome及1组真实新建NTFS满盘Chrome验收，合计20组162个重叠断言；历史14、下载4、真实满盘4均包含 | [完整封存](evidence/portable-studio-v32-seal.json) |
| 源码/分发 | 129份运行时文件匹配，30749份分发文件全SHA核对；VHD实际正常卸载 | [文件](evidence/portable-v32-files-verification.json)、[VHD](evidence/portable-v32-real-disk-full-lifecycle.json) |
| U16额外 | 私有副本保留3000旧事件，真实GUI新增1000，三次重启恢复、共4000事件、原静态SHA不变，原件仍3000；首轮脚本恢复检索错误失败保留 | [PASS，另4组](60-u16-fourth-batch-v32-acceptance.md)，[完整矩阵12PASS/12待验](ui/34-user-scenario-status-v32.md) |
| 大型语义/占用 | v27冷v12原始事实根43153000…与原版一致只是诊断；完整校验/规范化报告/标准包尚未完成；v32冷v13已启动及整范围采样，尚无最终G3/G4结果 | NOT_VERIFIED，不改写旧失败 |

| 程序交付 | 实际值 |
|---|---|
| 入口 | `H:/ECRAStudio-build-20261103-studio-v32/ECRA-Portable/ECRA.cmd` |
| 程序ZIP | `H:/ECRAStudio-build-20261103-studio-v32/ECRA-Portable.zip` |
| 字节数 | 673327646 |
| SHA-256 | c0a3e3b382d1de08986afc1f2ef584d9430ce1e67a518b6511312f3884780adf |

这不是大型标准结果包大小。软件构建、校验、原生及UI共享本机机械盘，时间不得作独占性能归因。实际[历史对比](ui/screenshots/portable-v32/history-11-comparison-reopen-1366.png)、[真实满盘失败提示](ui/screenshots/portable-v32/real-disk-full-01-real-full-confirmation-not-saved.png)。自动化GUI通过不等于工程师UAT或物理第二电脑/DPI验收。

仍未完成：生产写隔离、include_uncommitted=true正式快照、全数据根迁移、可证明不变时自动确认继承、双核旧输出等消费者完整迁移、大型当前轮完整G1/G4，以及用户已延期的其他真实工程、32GB/干净离线/双机/DPI/UAT。所有完整H/U/G门禁不标全部通过。
