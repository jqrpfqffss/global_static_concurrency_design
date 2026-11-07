# 最新大型完整包与整轮恢复的验收

本轮从 `optimize_ccc@45c7e0a43cdb7e996558652251604e69e52686ba` 的干净工作区继续，远程同名分支一致。重新完整阅读 `docs/ECRA_optimize_ccc_Codex.md`，遵守 H1–H6；直接由 Codex 执行，没有调用外部编码代理。本轮的优先顺序是核查两个既有大型任务，保留失败和运行中状态，再验证新归档的实际使用。

2026-11-07 11:01（上海时间），最新 INAV 完整包后处理最终 `PASS_COMPLETE_ROUNDTRIP_SCOPED`：完整事实/报告差异 0/0，原件后验无变化，完整保留量降低 **71.64745153628819%**。真实大型归档的六组 Chrome 操作及两次实际服务启动也已通过。整轮 Diff/恢复仍在运行；完整重构没有完成。

| 阶段 | 实现的核心功能 | 变更文件 | 测试/场景 ID | 状态 | 对应证据 |
|---|---|---|---|---|---|
| Phase 5/6 | 最新原生生产者实际完整导出、包内严格导入、所有图根/事件表及完整有序比较 | 本轮只归档既有完整包控制器与真实结果，正式引擎未改 | H1/H4/H6、G6；facts/report 0/0，全部原始根/表一致 | PASS_SCOPED | [最终收据](acceptance/latest-large-v78-final.json)、[完整比较](acceptance/latest-large-v78-ordered-comparison.json)、[导出](acceptance/latest-large-v78-export.json)、[严格导入](acceptance/latest-large-v78-import.json) |
| Phase 6 | 包含原始 Worker、缓存、共享构建和一份完整包的稳定保留量盘点 | 既有 `measure_storage_policy.py` 未改 | G4 最终大小子门限；整数比较 `after*100 <= before*30` | PASS_SCOPED，完整 G4 未关闭 | [策略](acceptance/latest-large-v78-retention-spec.json)、[逐类计量](acceptance/latest-large-v78-retention.json)、[原始资源样本证明](acceptance/latest-large-v78-raw-resources.json) |
| Phase 4/5/6 | 实际大归档下钻、113 组关系分页、真实源码定位、声明/撤销与服务重启后继续 | 新增 CLI 验收控制程序及截图；Vue/正式应用未改 | U09/U12/U13/U17/U19/U22 局部，六组真实操作；G6 局部 | PASS_SCOPED，不计完整 UAT/G7/G8 | [最终界面收据](acceptance/latest-viewer-v79-final.json)、[原失败](acceptance/latest-viewer-v79-first-controller-failed.json)、[继续位置补充](acceptance/latest-viewer-v79-continue-supplement.json)、[第二次服务](acceptance/latest-viewer-v79-second-service.json) |
| Phase 2/6 | 有真实源码改动的整轮 Diff、受控中断和恢复 | 冻结 v78 及原控制器未改，本轮只核查状态 | U04/U08、G1/G3/G5；独立全量与最终缓存命中尚未收齐 | RUNNING / NOT_VERIFIED | [控制器快照](acceptance/latest-large-v78-whole-controller-snapshot.json)、[资源过程快照](acceptance/latest-large-v78-whole-resource-snapshot.json)、[后处理等待快照](acceptance/latest-large-v78-whole-package-snapshot.json) |

所有新增原始证据按 [逐文件 SHA 清单](acceptance/latest-large-v78-evidence-index.json) 原样归档，并对这些路径禁用 Git 换行转换。资源 JSONL 和浏览器全部原始记录另有无损 ZIP 与 SHA，地址留在对应收据；包含会话凭据的两份浏览器启动日志只留私有工作目录。原始 FAIL 不重写为 PASS。

## 验收范围和条件

沿用 [120号整轮合同](120-current-and-whole-diff-validation-contract.md) 与 [124号完整包合同](124-latest-native-complete-package-contract.md)。不修改正在运行的冻结 v78、控制器、比较器、输入或已封存 Portable。完整包只有生产导出、包内 Python 3.10.9 严格导入、全部原始图根/人工与 AI 表、原完整有序比较、最终保留量及原件后验全部结束后才可判定通过。已有原生当前侧通过见 [125号](125-live-current-native-and-complete-package-acceptance.md)，不能代替整轮 Diff。

新增界面验收使用这次严格导入结果的独立完整副本，先逐文件核对复制字节，再以 v79 实际 `ECRA.cmd`、仅 Windows 的 PATH、真实 Chrome 操作。通过实际变量查询、归档代码定位和人工声明/撤销验证可用性。声明明确标为自动化验收，不是工程师风险判定；只写副本的 `reviews.db`。原包、原导入结果、原权威库及生产固件保持。此主机仍有原固件和工具，不能将受限 PATH 或独立目录说成第二台干净离线电脑。

原型、导航、版式、颜色和交互合同不变；沿用 [16号视口合同](ui/16-workbench-viewport-contract.md) 与 [45号源码定位合同](ui/45-archived-source-target-visibility.md)。浏览器真实 DOM、后端响应、持久化事件和截图一同验收，不能只凭按钮存在判定通过。遇到真实缺陷另立修复及复验记录。

## 本轮真实界面验收

以此次新包严格导入的 2668 个文件作独立逐字节复制，使用 v79 实际 `ECRA.cmd` 启动两次；第一次服务退出后才启动第二次。原始导入根保持不变。真实 Chrome 完成以下六组检查：

1. 首页“静态疑似 1318”点击后，匹配数与实际 SQL 分类计数都为 1318，首段只显示 50 项。
2. 精确查找 `tu::src/main/drivers/time.c::c:time.c@sysTickUptime`，核对全部五个真实访问的函数、文件和行号；保留静态 `SUSPECT`、覆盖 `PARTIAL`、无法恢复全部竞争 IRQ 优先级及“非目标板实测”的说明。
3. 113 组并发关系逐页访问，共 12 页，序号完整且不重复；每页第一项展开后的真实证据引用与权威库相同。此项没有声称枚举全部调用路径或逐字段展开每一组关系。
4. 1366×768、1600×900、1920×1080 下，真实跳转到第 57 行 `sysTickUptime++;`，整行 22.09375px 可见，文档滚动为 0，四个操作按钮可见，声明者和理由草稿保留。视口尺寸不等于 Windows 系统 DPI。
5. 通过界面提交 `NEED_MORE_EVIDENCE`，再撤销为 `PENDING`；两个事件、原理由及一个前驱关系完整保留。刷新页面后按“人工确认 → 继续上次位置”找回原变量和历史。
6. 关闭第一次实际服务，第二次启动 Portable 后，从首页“继续人工确认”恢复同一数据库位置及完全相同的两条事件。没有启动扫描任务、调用真实模型或产生外部网络请求。

第一版新增验收脚本错误地等待“刷新后自动选中变量”，因此超时。这不是现有继续位置流程的操作方式：既有 `scripts/validate_studio_ui.py` 已使用“人工确认 → 继续上次位置”。原 FAIL 收据及脚本保持不变，后续按既有流程单独补充实测；未修改应用、旧事件、超时门限或数据完整性断言来消除失败。最终六组结果须结合原 FAIL 及补充收据阅读。

人工身份为“自动化归档验收声明”，不是已认证工程师；理由明确“不代表工程风险结论”。本次没有新建“确认无风险”结论。两次服务均使用独立 2GiB 自有 Job；该资源范围只包含 ECRA 服务树，不含另行启动的 Chrome、CLI 或验收控制程序，不能用作完整 GUI/G3 的内存成绩。

已实际检查截图：[真实 IRQ 证据](ui/screenshots/latest-large-viewer-v79/02-real-main-irq-1366.png)、[1366 下实际第57行及固定操作](ui/screenshots/latest-large-viewer-v79/04-source-1366.png)、[第二次启动后的两条原始历史与理由](ui/screenshots/latest-large-viewer-v79/06-actual-process-restart-history-1600.png)。八张截图的原 SHA 均在最终界面收据中。两次服务树提交峰值分别为 58265600、54591488 B，静态库及全部归档证据对象后验不变。

## 最新完整包与资源口径

新标准完整包为 `3157606474 B`，SHA256 `7e72bc5d7ee4f01d5e88bf17845aa6c50d7cae5974a11f5422193b970fc787f5`。导出 2668 个 ZIP 成员，含全部 2665 个证据对象。原始 facts/report/provenance 图根、全部人工与 AI 表均保留；此次源结果没有人工事件，保留 3540 条 AI 状态事件及一份快照。非空人工记录的完整包往返另见 [125号真实 F030 副本](125-live-current-native-and-complete-package-acceptance.md)，本轮新增的是大型导入库上的实际 GUI 声明/撤销/服务重启。

完整有序、类型敏感比较的事实/报告差异为 0/0，规则未改。原生权威库 SHA 为 `d5349eebc74464a4c5343f901806c7340372f7160fc76ce03fe48214847b9e16`，一致快照导入后的静态库 SHA 为 `c6180f66323ae9ce72711ee8c83858cdce04114cc1e210a30aaa7dc3e760163b`；SQLite 快照的物理文件身份不混为原库身份，完整逻辑图和严格对照都相同。跨 Python 版本导入不是跨版本重新执行提取/求解，不能据此撤销 [114号原跨环境严格报告 FAIL](114-portable-v71-typed-cold-reader-acceptance.md)。

| 指标 | 原 e69 同输入历史原生控制 | 最新 v78 当前侧 |
|---|---:|---:|
| 原生 Job 提交峰值 | 29811765248 B | 10700746752 B |
| 原生进程树 RSS 采样峰值 | 29559390208 B | 10635071488 B |
| 生产者输出根分配采样峰值 | 46538663768 B | 18793679792 B |
| 原生段观察耗时 | 15454.922 秒 | 20812.985 秒，含额外完整活数据比较 |
| 最终完整保留集合 | 47665101856 B | 13514271104 B，含本次标准完整包 |
| 本次标准完整包 | 不将旧 HTML/JSON 集合当作新格式包 | 3157606474 B |
| 同输入全字段语义 | 原黄金到 A13 的已有完整等价链 | v78 对 A13 事实/报告 0/0；本次包往返再核对 0/0 |

最终盘点对原 58354 个、现 8308 个文件分别做两次稳定遍历，按 NTFS 文件身份去重硬链接。当前口径包含整个 `H:/ECRA-NATIVE-L78-SEED0`（原生库、缓存、原始 Worker、诊断、恢复资料等全部保留）、同一共享构建 `I:/ECRA-B1` 和一份新完整包；原口径为整个 `I:/ECRA-O3-SEED0` 加同一共享构建。验证用独立 Viewer、副本、浏览器日志和冻结程序单独列为验收基础设施，仍在磁盘保留。没有清理有效历史、缓存或恢复资料来满足目标。

完整导出、内嵌严格导入、完整有序对照、稳定盘点的实测 Job 时长分别为 4636.750、2557.343、2560.047、515.062 秒；提交峰值分别为 628346880、618037248、615636992、24477696 B。导出和导入工作目录的分配采样峰值分别为 15746531408、18210963584 B；这包括一致快照/验证副本，不能以 3.16GB 最终包大小冒充导出过程峰值，也不能将其当整轮 Diff 磁盘峰值。采样不包含 MFT/ADS 和未观测瞬时峰值。

最终控制器已核对全部 6945 个原扫描文件的 SHA/大小/mtime、全部冻结引擎与 Portable 文件以及包 SHA，差异均为零。其 32070.922 秒包含从 02:06 开始等待前置原生验收的时间，不能称导出耗时。另在两个真实 GUI 服务退出后核对 [全部分发文件名](acceptance/latest-viewer-v79-portable-namespace-final.json)：32305 个负载文件加清单共 32306 个文件，无新增或缺失。完整 G4、物理 32GB G3 及整轮 Diff 仍单独保留未完成状态。

## 使用入口与复现范围

实际程序入口仍为 `H:/ECRAStudio-build-20261106-studio-v79/ECRA-Portable/ECRA.cmd`，ZIP 同级；其身份与包内 34 项后端专项的继承范围见 [122号](122-portable-v79-and-source-target-acceptance.md)。此次没有改动正式 Python 引擎、Vue 或已封存程序，不重复执行已通过的 1568 项回归，也没有重新打包来替换原 ZIP。

新结果包位于 `H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/native-final-package-inav-v78-r2/standard-complete.ecra-report`。用户通过“数据与共享”选择导入；新归档仍标“来源尚未验证/归档证据模式”，可以查看及确认，不能声称原固件已重新核对。

后处理重现命令形态如下，`<新外置目录>` 必须尚不存在，不能覆盖本次收据或旧数据：

```powershell
py -3.10 -B -X utf8 H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/run-native-final-package-v78-r2.py --source H:/ECRA-NATIVE-L78-SEED0/scans/native-golden --gate H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/inav-current-published-native-v78-live-queue.json --work <新外置目录> --old-data-root I:/ECRA-O3-SEED0 --common-root I:/ECRA-B1
```

界面验证使用 `@playwright/cli` 的实际 Chrome 会话、逐次新 snapshot 引用及 DOM 坐标读取。过程是先复制已严格导入的结果并核对所有字节，执行首页下钻与精确查询，再运行分页及源码/确认分段脚本，最后按既有“继续上次位置”流程完成补充和真实服务重启。所有 `cli-*.log`、`restart-cli-*.log`、页面快照、声明/撤销记录及截图留在工作根 `latest-large-viewer-v79`；含临时会话凭据的启动日志不放入公开证据归档。CLI 对验收人员需要 Node，最终软件用户仍不需要 Node。

复验前须把验收控制程序指向新的独立工作目录和相应已验证包；准备程序拒绝覆盖已有目录。图形界面的实际操作和 API/SQL 断言均有记录，但这是自动化 GUI 功能验收，不是嵌入式工程师盲测满意度或目标板硬件复现。

## 尚未关闭的门禁

整轮恢复必须满足真实新增计数器的 `DIRECT_CHANGED` 影响、至少两个 TU 缓存命中、完整独立全量零语义/分类差异，以及旧基准库、私有固件/Git和冻结引擎不变。运行中日志或首段受控中断均不能计作最终通过。

其它 G2 工程按用户决定继续待验。32GB 物理机、第二台干净离线电脑、Windows 系统 DPI、真实模型及人工 UAT 保持 `NOT_VERIFIED`；原跨环境严格报告 FAIL 和逐字段审计保留，不放宽比较规则。完整重构和完整 G1–G8 尚未完成。
