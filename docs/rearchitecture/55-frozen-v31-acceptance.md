# Portable v31：历史对比与真实满盘恢复已入包

封存运行时`30513deb015b9e3df690f9ecbe5c2223b25bcc1c`，2458份冻结文件。新增历史对象对比及满盘中文恢复提示已用本包实际解释器/Chrome验证；后续49960e的64MiB写缓存不在本包。全部重构门禁仍未通过，不作为完整发布宣告。

| Phase/验收 | 实测结果 | 状态/证据 |
|---|---|---|
| 完整冻结回归 | 1392项：1390PASS、2联网opt-in SKIP，1958.258s；全部冻结文件/测试副本SHA无变化 | [PASS限定版本](evidence/full-regression-studio-v31.json) |
| 独立F030原生 | 相同原配置/固件/编译库/工具，4TU；完整有序类型事实49e91182…及既有规范化报告62fd77e0…差异0，原输入不变；CLI23.500s、含核验26.703s | [审计后的真实来源](evidence/native-exact-f030-v31-v1-audited.json) |
| 真实构建/CLI | 572.813s；目录/中文ZIP解压各27CLI（21正常0、6预期INCOMPLETE 2）；不是干净物理离线机 | [构建](evidence/portable-studio-v31-build-v1.json)、[目录](evidence/portable-v31-cli-uncompressed.json)、[ZIP](evidence/portable-v31-cli-zip-extracted.json) |
| 实包UI | 19组普通实际Chrome验收，包含历史对比14项；另1组新建真实NTFS VHD/Chrome满盘恢复4项；合计20组、162个有重叠的断言 | [完整封存](evidence/portable-studio-v31-seal.json) |
| 真实满盘 | 实际内核ENOSPC；人工提交失败时原事件完整，导出失败无半成品最终包，释放自有填充后同界面可继续确认/完整包严格往返，中文原因/恢复动作均通过 | [4项实测](evidence/browser-portable-v31-real-disk-full.json)、[映像已卸载](evidence/portable-v31-real-disk-full-lifecycle.json) |
| 分发绑定 | 30743份分发文件全SHA核对，129份运行时源码/前端/许可匹配；静态包未在验收后改写 | [核对](evidence/portable-v31-files-verification.json) |
| 完整U/G | [U01–U24](ui/32-user-scenario-status-v31.md)仍11PASS/13NOT_VERIFIED。U16未在本包重跑1000；历史v23单独保留。其他工程、生产写隔离/dirty快照、全数据根迁移、自动确认继承、双核旧输出消费者、大型G1/最终G4、物理机/DPI/UAT等未齐 | FAIL/NOT_VERIFIED |

| 程序交付 | 实际值 |
|---|---|
| Windows入口 | `H:/ECRAStudio-build-20261103-studio-v31/ECRA-Portable/ECRA.cmd` |
| 程序ZIP | `H:/ECRAStudio-build-20261103-studio-v31/ECRA-Portable.zip` |
| 程序ZIP字节数 | 673314072 |
| 程序ZIP SHA-256 | ae1e9e380f2ae8eeff4ee38bc6fc2e20c397cd9182797f24e050868fa5781569 |

这是**软件分发ZIP**，不是INAV标准完整结果包大小。完整封存的控制器总包络含等待，不将其2802.813s误作单独文件核验耗时。构建与原生/严格对照共享机械盘，耗时不作隔离性能归因。

实际截图：[1366历史对象对比](ui/screenshots/portable-v31/history-11-comparison-reopen-1366.png)、[真实满盘未保存](ui/screenshots/portable-v31/real-disk-full-01-real-full-confirmation-not-saved.png)、[满盘导出保持旧包](ui/screenshots/portable-v31/real-disk-full-02-real-full-export-keeps-last-valid-package.png)。标准包/仅人工增量走原生下载，历史行可进入双方canonical对象证据，不是模拟页面。

来源审计：原F030控制器遗留旧HEAD字面值bdfc050，实际执行冻结30513de路径/101模块前后SHA及2458文件冻结清单证明了真实运行时；[原件](evidence/native-exact-f030-v31-v1-original.json)完整保留，[审计收据](evidence/native-exact-f030-v31-v1-audited.json)记录纠正依据。仅替换等待中的封存控制器，未取消原生/构建/浏览器；[取消记录](evidence/v31-sealer-v1-cancelled-before-output.json)。没有将错误原件静默改成PASS。

后续状态：49960e写缓存64MiB的独立冻结1392项1390PASS/2SKIP，2088.997s及真实F030差异0已完成，v32包另行验收。新388TU冷扫描v13及整范围存储采样运行中。冻结v27/1493c05的冷v12仍单独做严格大图对照；其原始事实根与原版已读到一致，但规范化报告及完整校验未结束，**不能提前关闭大型G1**。归档前78.31%不包含标准完整包，完整G4仍待验。
