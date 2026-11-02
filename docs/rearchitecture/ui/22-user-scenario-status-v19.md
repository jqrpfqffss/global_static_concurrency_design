# U01–U24：Portable v19场景状态（2026-11-02）

实际运行时034ecb5604，包内Python3.10.9；v17历史状态单独保留。本表引用v19实际13组Chrome，U05的额外缺CMake/Ninja/Git故障仅在efc源码独立验过，不能借此宣称v19重验。场景PASS限实际输入与动作，不代替G1–G8或真实用户满意度。

| ID | 完整场景 | 已验范围与剩余项 | 证据组 |
|---|---|---|---|
| U01 | PASS | 实际ECRA.cmd、Windows-only PATH、包内Python、私有默认数据根，首屏三入口/真实示例；非物理干净机双击。 | launcher,sample,main |
| U02 | PASS | 实际四步向导与回退；真实编译器/全部TU命令/输入闭包检查；检查前禁用启动；缺工具修复；实包深路径Release/demo真实ARM外置构建。仅已验获准F030与教学构建。 | preflight,profile,contexts,directories |
| U03 | NOT_VERIFIED | 42文件真实ACL只读DB扫描/原新对照/原数据不变已验；只读外置CMake全模式、物理只读挂载与生产写保护未齐。 | main; readonly-native-f030-v2 |
| U04 | NOT_VERIFIED | 真实refs/HEAD/dirty提示/分页/保存6项已验；dirty字节正式固定和大型原生Diff输入/结果尚未完成。 | git |
| U05 | PASS | 实际缺ARM编译器与CMake toolchain路径阻断；额外缺CMake/Ninja/Git三故障的旧源码收据保留；v19未重跑该额外组，非物理干净机。 | preflight; browser-missing-tools-v1 |
| U06 | PASS | F030通过向导启动、停止恢复后保存；首页同profile真实重扫，原结果/人工记录保留。仅已验小工程。 | main |
| U07 | NOT_VERIFIED | 小工程真实任务资源/日志与共享占用故障已验；388TU当前为CLI受控测量，不替代大型GUI验收。 | main |
| U08 | NOT_VERIFIED | 真实停止/恢复/旧指针和TU复用已有浏览器及单元证据；仍缺当前包原生任务中途服务/系统重启完整流程。 | main |
| U09 | PASS | 实际SQL口径与卡片下钻/筛选一致；完整类别和统计来源保留，示例未伪装安全。 | main,sample,capacity |
| U10 | PASS | 20007行真实服务端分页/精确搜索/排序/恢复位置/有界响应；大整数、负零、代理字符及长文本完整分页。 | capacity |
| U11 | NOT_VERIFIED | HCLK和g_counter精确身份/访问/归档源码已验；g_mfcInterface.msgSp所属工程按用户决定待验，不伪造该输入。 | main,sample |
| U12 | NOT_VERIFIED | 真实相关调用边双向查询和完整计数已验；尚缺当前包真实main/IRQ大型完整交错场景。 | main |
| U13 | NOT_VERIFIED | 保护/NVIC语义回归存在；当前包真实NVIC/PRIMASK/BASEPRI不明确的组合GUI流程未完整验收。 | main |
| U14 | NOT_VERIFIED | 真实2PARSED/2PARTIAL、236原始缺口和覆盖阻断的8项下钻通过；完整失败TU/原因组合与大型输入仍待验。 | coverage |
| U15 | NOT_VERIFIED | 实际缺复核工具故障保持静态库、TECH_FAILED未变SAFE已验；真实联网工具修复/重试未验，两项opt-in跳过。 | main |
| U16 | PASS | v19同数据根续接v17的1000事件，再向1000个不同UNKNOWN对象追加声明；新350/700/1000处重启服务，原1000逐事件不变、共2000事件、17.8GB原版图SHA不变；不是新版原生G1/G3或UAT。 | review-upgrade-batch-v19-v1 |
| U17 | PASS | 实际撤销追加审计事件；新增真实reviews.db写锁阻塞、只读核对无早发事件、Esc关闭详情后释放锁/提交/重开/撤销；原确认及理由可追溯。 | main |
| U18 | PASS | 实包私有教学副本Release→Debug原生重扫、RMW表达式变化后再原生重扫，旧SAFE均只作历史，当前RECHECK_REQUIRED并可重新确认，原事件保留。此输入不充作G2第三类真实工程。 | preflight |
| U19 | NOT_VERIFIED | 一台主机两独立根/服务/origin完整包与继续确认已验；无固件Viewer可实际启动；第二台物理机待验。 | collaboration,sample,launcher |
| U20 | PASS | 两真实服务的GUI增量传播、重复导入、并行冲突、缺理由拒绝、全父分支显式解决及再导出重开7项通过。 | collaboration |
| U21 | NOT_VERIFIED | 完整旧结果6项真实迁移及缺证据原件Viewer6项已通过，归属/原字节/禁安全补造/标准包/幂等已验；大型双旧来源迁移仍未完整验收。 | legacy-v2,legacy-degraded |
| U22 | NOT_VERIFIED | 1366/1600/1920及工作台/对话框主操作已验；浏览器密度模拟不作Windows原生系统DPI，全部极端状态/长名未齐。 | main,sample,directories,contexts |
| U23 | NOT_VERIFIED | 实际GUI清理计划/恢复/二次确认释放通过；较早50GiB容量证据保留，当前包完整50GB场景仍未重验。 | main |
| U24 | PASS | 实际UI恶意/损坏结果包拒绝且旧库/人工记录不变；严格包校验单元覆盖另有证据，不等于G5全故障矩阵。 | main,legacy |

{'PASS': 11, 'NOT_VERIFIED': 13}；完整G7仍FAIL。

[v19封存收据](../evidence/portable-studio-v19-seal.json)绑定当前源码/包文件，全部13组通过；分项证据为../evidence/browser-portable-v19-{组名}.json。U16另见[升级续确认](../evidence/browser-review-upgrade-batch-v19-v1.json)。v18快速撤销失败仍保留，不把旧失败改成PASS。

缺源码的第二台物理机、32GB真机、Windows真实DPI与工程师UAT继续NOT_VERIFIED。CLI现有只读记录是历史已验子范围，当前完整U03未验。
