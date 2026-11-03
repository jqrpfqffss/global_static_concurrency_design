> 后续最终结果：v34已完整封存，见[63号记录](63-frozen-v34-acceptance.md)；旧生产者冷v12大型严格对照/完整包通过、最终含包69.865%尺寸目标FAIL，见[62号记录](62-fixed-seed-full-package-and-size-failure.md)。以下保留当时的队列观察，不将当时RUNNING收据改写。

# 当前读取校验、消费者迁移与后续整包验收

2026-11-03，本轮重新核对HEAD5bcfa01、工作区干净后执行。实际新增代码/验收已提交为5cf7b61d6a3ea5e3f999077e492f048a88ff51b1，分支optimize_ccc；未推送、未重置或清理旧产物。用户已延期的其他G2工程继续NOT_VERIFIED_USER_DEFERRED。

| 阶段/功能 | 变更或测试 | 已取得结果 | 证据 |
|---|---|---|---|
| Phase2校验读取 | scan_store.validate连接局部缓存512MiB，全部检查保留 | 冻结v33/5bcfa01：1392项1390PASS、2联网SKIP，2136.539s，2784份冻结/测试副本SHA差异0 | [全套](evidence/full-regression-studio-v33.json)、[ADR](58-validation-read-cache-adr.md) |
| Phase1/3派生合并 | multicore、独立根/输入固定/权威库/人工库/最后发布；server/App来源说明 | 51PASS；e69相同F030图和ELF两个声明别名，完整有序事实/既有规范化报告差异0；不是新的双核原生扫描 | [实现与实测](59-multicore-publication-adr.md) |
| Phase4实际界面 | 派生结果真实Chrome、精确对象、确认/继续/下载和严格导入 | 最终4组PASS，126份运行时前后SHA差异0；现有2事件保留再增1。截图等待实际请求结束 | [当前源码GUI](evidence/multicore-publication-ui-v5.json) |
| Phase4 U16 | 实包v32、原版INAV图私有人工库副本 | 3000+1000=4000事件；三次重启恢复、原始3000及静态SHA不变 | [U16完整实测](60-u16-fourth-batch-v32-acceptance.md)，[矩阵12PASS/12待验](ui/34-user-scenario-status-v32.md) |
| Phase6当前候选 | 冻结v34/5cf7b61，2808文件，清单SHA0394bea612b4e97a1e83ba1c65d66239a3b17e56e93f33c48a50c1591eb22916 | 1401全套运行中；仅通过后再做原配置F030、实际Portable构建/CLI/浏览器与新建VHD；不能把排队称PASS | [带时间状态](evidence/v34-queue-observation-v1.json) |

v34验收还包含包内Python实际执行多核CLI，使用前述明确声明的F030输入对，与e69完整输出比较后才打开真实包内GUI；20组普通Chrome和1组新建VHD共21组166个重叠断言需实际结束。控制器及所有日志在独立continuation-h3，失败原件保留；未发布前不替换v32入口。分发全文件SHA、运行时匹配、中文ZIP和目录CLI必须另验。**本文件记录队列与已经取得的证据，不预写未来PASS。**

## 大型固定输入：实际前/后，门禁仍未关闭

原版e69与原生冷v12/1493c05使用同一seed0、date-epoch、配置SHA d1bc911b…和4123输入；不是本轮v34的新原生生产者。64GiB主机、共享机械盘且有其他验收并行，时间不作独占速度归因。

| 指标 | 原版e69 seed0 | 候选1493c05冷v12 | 当前判定 |
|---|---|---|---|
| 原生CLI耗时 | 15454.922s | 31846.532s | 候选更慢，未宣称提速 |
| Job峰值提交 | 29811765248B | 10687008768B | 受控32/16GiB Job；物理32GB机未验 |
| RSS峰值 | 29559390208B | 10618966016B | 真实进程树测量 |
| 进程树Private峰值 | 29741166592B | 10685960192B | 不等同总系统提交 |
| 主进程peak_pagefile | 29805244416B | 10680487936B | 原Windows高水位计数器，非RSS |
| 输出采样分配峰值 | 46538663768B | 18794582808B | 采样下界，非全策略瞬时精确峰值 |
| 最终输出分配 | 46538663768B | 9210561128B | 尚不含标准完整结果包 |
| 完整标准归档 | 原版完整备份独立保留 | 标准包导出/严格导入须待完整对照 | NOT_VERIFIED |
| 全字段语义差异 | 原始事实根43153000… | 原始事实根相同只是元数据诊断 | 完整深校验/规范化报告仍执行中，不称G1通过 |

归档前合并公共构建/缓存后的物理计量：47665101856B→10336999216B，降低78.3133%；**未计标准完整包，不关闭G4**。原始全量前后收据见[原生v12记录](52-fixed-seed-native-v12-completion.md)及evidence中同输入收据。新版writer64MiB的原生冷v13/49960e另在运行，不能把上述v27结果改标v34。整范围观察器已在v13输出创建前启动；它记录非原子窗口及缺失/部分窗口，不伪称无遗漏的历史峰值。

新的独立512MiB只读比较使用原版完整图与冷v12图、原比较器SHA427998f4…、2GiB Job。已完成前置两图完整文件SHA，现执行全部深校验。旧64MiB比较器保持运行且未修改。另有提前的完整报告规范化Merkle元数据诊断，用于尽早发现差异；它不重复节点字节/投影深校验，**即使诊断一致也不能关闭G1**。完整最终SHA、标准包及独立导入仍由完整流程验收。

## 当前使用与复现

已封存入口仍为`H:/ECRAStudio-build-20261103-studio-v32/ECRA-Portable/ECRA.cmd`，ZIP673327646B，SHA c0a3e3b382d1de08986afc1f2ef584d9430ce1e67a518b6511312f3884780adf。它是软件分发包，不能当作大型标准结果包大小。v32不含后续512MiB读取及多核发布迁移。

专项：`py -3.10 -B -X utf8 -m unittest tests.test_multicore_publication tests.test_multicore tests.test_studio_api tests.test_report_package tests.test_scan_store -v`。整套：`py -3.10 -B -X utf8 -m unittest discover -s tests -v`。本轮实际在精确冻结副本执行，manifest/日志/计数可独立核对。

当前源码GUI复现脚本为`scripts/validate_multicore_publication_ui.py`；所需实际case、Python/engine、全新work/evidence路径和已有事件数必须明确传入。不能重置已有人工库以重跑。新旧完整对照驱动、输入绑定和失败trace在continuation-h3，详见59号记录。

仍未实现：正式dirty字节快照接入、生产强写隔离、全数据根迁移、完整证据证明一致时的自动确认继承、全局大Diff/外存及全消费者恢复门禁；多核普通用户向导也未完成。大型当前轮完整G1/G4、完整故障矩阵、其他真实工程、物理32GB/第二电脑/干净离线/DPI、真实OpenCode联网和工程师UAT继续待验。所有完整Phase及H/G门禁均不标全部完成。
