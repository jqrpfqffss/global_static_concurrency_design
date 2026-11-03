# U01–U24：Portable v34场景状态（2026-11-03）

实际运行时5cf7b61，包内Python3.10.9；1401项1399PASS/2联网SKIP、21组166个重叠Chrome/VHD断言通过，31088份分发文件全SHA核对。另有真实冷v12完整标准包6组补验，原始图/标准包及旧失败均保留。U12/U13按已验main/SysTick与未知NVIC场景通过；U16的v32千项批次保留为历史，未当作本包新批次。后续省空间包/原子会话/调用加载提示不在v34。

| ID | 完整场景 | 已验范围与剩余项 | 证据组 |
|---|---|---|---|
| U01 | PASS | 实际ECRA.cmd、Windows-only PATH、包内Python、私有默认数据根，首屏三入口/真实示例；非物理干净机双击。 | launcher,sample,main |
| U02 | PASS | 实际四步向导与回退；真实编译器/全部TU命令/输入闭包检查；检查前禁用启动；缺工具修复；实包深路径Release/demo真实ARM外置构建。仅已验获准F030与教学构建。 | preflight,profile,contexts,directories |
| U03 | NOT_VERIFIED | 42文件真实ACL只读DB扫描/原新对照/原数据不变已验；只读外置CMake全模式、物理只读挂载与生产写保护未齐。 | main; readonly-native-f030-v2 |
| U04 | NOT_VERIFIED | 真实refs/HEAD/dirty提示/分页/保存、开启未提交后阻断及清除已经保存的true标志9组已验；dirty字节正式隔离仍未实现，大型原生Diff未验。 | git |
| U05 | PASS | 实际缺ARM编译器与CMake toolchain路径阻断；额外缺CMake/Ninja/Git三故障的旧源码收据保留；v34未重跑该额外组，非物理干净机。 | preflight; browser-missing-tools-v1 |
| U06 | PASS | F030通过向导启动、停止恢复后保存；首页同profile真实重扫，原结果/人工记录保留。仅已验小工程。 | main |
| U07 | NOT_VERIFIED | 获准388TU的e69/1493c05原生、完整语义、标准包及本包查看已验；大型任务仍由独立CLI观测器运行，不能冒充本包任务中心的大型实时阶段/TU/资源验收。当前writer64冷v13另待结束。 | main; 62/63号记录 |
| U08 | PASS | 实际F030原生中途Worker异常退出→FAILED、GUI重试；服务异常退出→Job后代结束、重开INTERRUPTED、再次GUI重试；原有效静态库/全部旧事件/最新指针保留，两次恢复均真实TU命中。不是断电或系统重启全故障矩阵。 | portable-v34-crash-recovery |
| U09 | PASS | 实际SQL口径与卡片下钻/筛选一致；完整类别和统计来源保留，示例未伪装安全。 | main,sample,capacity |
| U10 | PASS | 20007行真实服务端分页/精确搜索/排序/恢复位置/有界响应；大整数、负零、代理字符及长文本完整分页。 | capacity |
| U11 | NOT_VERIFIED | HCLK和g_counter精确身份/访问/归档源码已验；g_mfcInterface.msgSp所属工程按用户决定待验，不伪造该输入。 | main,sample |
| U12 | PASS | 实际v34包打开严格验证的冷v12完整标准导入：5访问、main/SysTick域、113冲突、5423相关边/1486页及main→scheduler→micros真实见证、归档RMW源码通过；完整边保留，不宣称枚举全部路径或硬件时序。 | native-inav-evidence-ui-v34-v1，6组 |
| U13 | PASS | 同一真实原生包的UNRESOLVED优先级与保护成立前提正确显示，不编造抢占结论；这是已验main/SysTick未知配置，不代表全部芯片/动态配置组合或硬件复现。 | native-inav-evidence-ui-v34-v1 |
| U14 | NOT_VERIFIED | 真实2PARSED/2PARTIAL、236原始缺口和覆盖阻断的8项下钻通过；完整失败TU/原因组合与大型输入仍待验。 | coverage |
| U15 | NOT_VERIFIED | 实际缺复核工具故障保持静态库、TECH_FAILED未变SAFE已验；真实联网工具修复/重试未验，两项opt-in跳过。 | main |
| U16 | NOT_VERIFIED | v34未另跑1000容量批次。旧v32实际保留3000+新增1000、三次重启/4000事件/静态SHA及原件不变的收据独立保留，不借用为本包新批次。 | 60号记录；本包主流程/多核人工记录通过 |
| U17 | PASS | 实际撤销追加审计事件；新增真实reviews.db写锁阻塞、只读核对无早发事件、Esc关闭详情后释放锁/提交/重开/撤销；原确认及理由可追溯。 | main |
| U18 | PASS | 实包私有教学副本Release→Debug原生重扫、RMW表达式变化后再原生重扫，旧SAFE均只作历史，当前RECHECK_REQUIRED并可重新确认，原事件保留。此输入不充作G2第三类真实工程。 | preflight |
| U19 | NOT_VERIFIED | 一台主机两独立根/服务/origin完整包与继续确认已验；无固件Viewer可实际启动；第二台物理机待验。 | collaboration,sample,launcher |
| U20 | PASS | 两真实服务的GUI增量传播、重复导入、并行冲突、缺理由拒绝、全父分支显式解决及再导出重开7项通过。 | collaboration |
| U21 | NOT_VERIFIED | 完整旧结果6项真实迁移及缺证据原件Viewer6项已通过，归属/原字节/禁安全补造/标准包/幂等已验；大型双旧来源迁移仍未完整验收。 | legacy,legacy-degraded |
| U22 | NOT_VERIFIED | 1366/1600/1920及工作台/对话框主操作已验；浏览器密度模拟不作Windows原生系统DPI，全部极端状态/长名未齐。 | main,sample,directories,contexts |
| U23 | NOT_VERIFIED | 实际GUI清理计划/恢复/二次确认释放通过；较早50GiB实盘合成缓存证据保留，本包完整50GB原生引用/恢复场景未重验；本包另有真实逻辑/分配量及空间策略8项GUI。 | main |
| U24 | PASS | 实际UI路径恶意包及重算摘要的F030未哈希标量尾包均拒绝，旧库/全部事件不变；失败后没有残留正在校验提示。仅已覆盖输入集合，不等于完整G5/G6。 | main,legacy; scalar-boundary |

{'PASS': 13, 'NOT_VERIFIED': 11}；完整G7仍FAIL。

[v34实包封存](../evidence/portable-studio-v34-seal.json)绑定5cf7b61/全部分发文件，实际20组通过，额外U16第四批另封存。U08当前包见browser-portable-v34-crash-recovery.json；U16历史v23/v32证明分别保留；本包大型6组补验与21组166断言分开。原控制路径错误和旧v18输入丢失失败不改写为PASS。

缺源码的第二台物理机、32GB真机、Windows真实DPI与工程师UAT继续NOT_VERIFIED。CLI现有只读记录是历史已验子范围，当前完整U03未验。

空间策略8项是U07/U23等子范围补验，不将50GiB历史容量、32GB预算或各场景重叠断言汇总为完整G门禁通过。当前仍13PASS/11NOT_VERIFIED，参见[完整封存](../63-frozen-v34-acceptance.md)。

本包实际VHD磁盘满完整性/恢复4项及中文可操作性均通过，源文案失败另保留，不关闭完整G5。新版原生v27归档前78.31%计量同样不是本包完整G4。
