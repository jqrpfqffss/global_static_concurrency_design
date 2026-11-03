# Portable v34：读取器与多核派生消费者完整本机封存

实际运行时5cf7b61d6a3ea5e3f999077e492f048a88ff51b1，2808份冻结文件，清单SHA0394bea612b4e97a1e83ba1c65d66239a3b17e56e93f33c48a50c1591eb22916。含512MiB校验读取、64MiB写缓存、独立多核合并发布与来源提示；后续省空间包选项、会话原子写入与调用边加载提示不在本包。完整重构仍未完成。

| Phase/验收 | 已取得实测 | 状态/证据 |
|---|---|---|
| 完整冻结回归 | 1401项1399PASS、2联网SKIP，2028.737s；冻结/测试副本SHA无变化 | [全套](evidence/full-regression-studio-v34.json) |
| 真实F030 | 同一原配置/固件/编译库/工具，完整有序事实49e91182…与既有规范化报告62fd77e0…差异0；2PARSED/2PARTIAL和INCOMPLETE保持 | [原生](evidence/native-exact-f030-v34-v1.json) |
| 构建/CLI | 实际目录及中文ZIP解压各27CLI，21正常0、6预期部分覆盖2 | [构建](evidence/portable-studio-v34-build-v1.json)、[目录](evidence/portable-v34-cli-uncompressed.json)、[中文ZIP](evidence/portable-v34-cli-zip-extracted.json) |
| 实际包浏览器 | 20组普通Chrome及1组新建NTFS VHD满盘验收，共21组166个重叠断言，全部通过 | [完整封存](evidence/portable-studio-v34-seal.json) |
| 包内多核CLI | 包内Python实际执行新CLI，F030同图/ELF两个明确声明别名，对e69完整事实/规范化报告零差异；不是新增双核原生工程 | [包内CLI证明](evidence/portable-v34-multicore-cli-proof.json) |
| 文件 | 31088份分发文件全SHA、129份运行时逐文件匹配；真实VHD正常卸载 | [文件核对](evidence/portable-v34-files-verification.json)、[VHD](evidence/portable-v34-real-disk-full-lifecycle.json) |

| 软件交付 | 实际值 |
|---|---|
| 入口 | `H:/ECRAStudio-build-20261103-studio-v34/ECRA-Portable/ECRA.cmd` |
| 程序ZIP | `H:/ECRAStudio-build-20261103-studio-v34/ECRA-Portable.zip` |
| 大小 | 704357462B |
| SHA-256 | 161b864abcb674dd493376d96af6cc1eda3fba4e184169f4519ca5bdeb32c373 |

程序ZIP不是大型标准结果包。大型固定输入的旧生产者完整对照已通过、标准包4.01GB，而含包的尺寸降低69.865%仍FAIL，见[62号记录](62-fixed-seed-full-package-and-size-failure.md)。不将当前软件测试数量或F030结果替代真实大项目当前轮全流程。

首轮示例完成8个行为组后，重启探针恰好读到尚未写完的会话JSON而失败，原[失败收据](evidence/portable-v34-sample-original-failed.json)和[失败整组](evidence/portable-v34-original-failed-browser-suite.json)保留。只修正验收控制器的完整JSON就绪等待，在**相同未修改的v34运行时**、全新私有数据根重跑全部11项通过，未降低任何断言。实际[审计后整组](evidence/portable-v34-audited-browser-suite.json)记录新控制器SHA及旧行；分发文件仍与原冻结源码逐字节一致。生产会话文件原子写入是后续源码修复，不倒填进本包。

实际[派生对象工作台](ui/screenshots/portable-v34/multicore-publication-01-derived-canonical-object-real-workbench.png)、[人工记录](ui/screenshots/portable-v34/multicore-publication-02-real-human-declaration.png)、[标准包下载](ui/screenshots/portable-v34/multicore-publication-03-actual-complete-browser-export.png)。U16实际4000事件容量证明属于[旧v32独立批次](60-u16-fourth-batch-v32-acceptance.md)，v34没有新跑1000项，不借用成当前新批次。

当前完整U/G门禁仍未通过。生产强写隔离、dirty快照接入、全数据根迁移、证据不变自动继承、多核向导、完整大Diff/恢复矩阵均未完成；其他真实工程按用户决定待验，物理32GB/第二电脑/干净离线/DPI/真实OpenCode联网及工程师盲测继续NOT_VERIFIED。


后续大型补验已实际完成：本v34的ECRA.cmd读取严格验证/独立导入的冷v12原生标准包，6组全部PASS，完整113冲突及5423边/1486页、main真实见证、未知NVIC/保护与归档SysTick RMW源码均已核对，静态SHA与原人工事件保持；[收据](evidence/native-inav-evidence-ui-v34-v1.json)。该6组独立于基础21组166断言，[U矩阵](ui/35-user-scenario-status-v34.md)13PASS/11NOT_VERIFIED，不代表真实双机/DPI/UAT或当前writer64冷v13已完成。
