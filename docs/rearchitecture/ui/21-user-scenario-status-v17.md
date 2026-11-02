# U01–U24：Portable v17完整场景状态

实际运行时efc8556，包内Python3.10.9；旧v15状态单独保留。场景PASS限表中实际输入与动作，不代替G1–G8或真实用户满意度。

| ID | 完整场景 | 已验范围与剩余项 | 证据组 |
|---|---|---|---|
| U01 | PASS | 实际ECRA.cmd、Windows-only PATH、包内Python、私有默认数据根，首屏三入口/真实示例；非物理干净机双击。 | launcher,sample,main |
| U02 | PASS | 实际四步向导与回退；真实编译器/全部TU命令/输入闭包检查；检查前禁用启动；缺工具修复；实包深路径Release/demo真实ARM外置构建。仅已验获准F030与教学构建。 | preflight,profile,contexts,directories |
| U03 | NOT_VERIFIED | 42文件真实ACL只读DB扫描/原新对照/原数据不变已验；只读外置CMake全模式、物理只读挂载与生产写保护未齐。 | main; readonly-native-f030-v2 |
| U04 | NOT_VERIFIED | 真实refs/HEAD/dirty提示/分页/保存6项已验；dirty字节正式固定和大型原生Diff输入/结果尚未完成。 | git |
| U05 | PASS | 实际缺ARM编译器与CMake toolchain路径阻断；源码efc的私有工具根分别缺CMake/Ninja/Git，3种具体字段/修复/不发布扫描；非物理干净机。 | preflight; browser-missing-tools-v1 |
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
| U16 | PASS | 实包读取原版INAV完整原生图的独立17.8GB字节副本，1000个真实不同UNKNOWN对象；350/700/1000处关闭并重启真实服务，数量/筛选/位置持续；1000事件与源/静态SHA保持；不是新版原生G1/G3或UAT。 | human1000 |
| U17 | PASS | 实际撤销追加审计事件，原确认及理由/历史继续可见；不覆盖旧事件。 | main |
| U18 | NOT_VERIFIED | 底层变化证据RECHECK/历史保留已有原生回归；当前包源码/构建变化后GUI继承和重新确认完整流程仍待验。 | main |
| U19 | NOT_VERIFIED | 一台主机两独立根/服务/origin完整包与继续确认已验；无固件Viewer可实际启动；第二台物理机待验。 | collaboration,sample,launcher |
| U20 | PASS | 两真实服务的GUI增量传播、重复导入、并行冲突、缺理由拒绝、全父分支显式解决及再导出重开7项通过。 | collaboration |
| U21 | NOT_VERIFIED | 完整旧结果6项真实迁移及缺证据原件Viewer6项已通过，归属/原字节/禁安全补造/标准包/幂等已验；大型双旧来源迁移仍未完整验收。 | legacy-v2,legacy-degraded |
| U22 | NOT_VERIFIED | 1366/1600/1920及工作台/对话框主操作已验；浏览器密度模拟不作Windows原生系统DPI，全部极端状态/长名未齐。 | main,sample,directories,contexts |
| U23 | NOT_VERIFIED | 实际GUI清理计划/恢复/二次确认释放通过；较早50GiB容量证据保留，当前包完整50GB场景仍未重验。 | main |
| U24 | PASS | 实际UI恶意/损坏结果包拒绝且旧库/人工记录不变；严格包校验单元覆盖另有证据，不等于G5全故障矩阵。 | main,legacy |

{'PASS': 10, 'NOT_VERIFIED': 14}；完整G7仍FAIL。

[封存收据](../evidence/portable-studio-v17-seal.json)记录精确尝试路径，sample/legacy/collaboration/launcher使用v2并保留首轮失败。其他证据组对应../evidence/browser-portable-v17-{组名}.json；U05源码独立故障收据为browser-missing-tools-v1.json。

缺源码的第二台物理机、32GB真机、Windows真实DPI与工程师UAT继续NOT_VERIFIED。CLI现有只读记录是历史已验子范围，当前完整U03未验。
