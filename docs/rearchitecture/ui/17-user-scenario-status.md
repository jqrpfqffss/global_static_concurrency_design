# U01–U24 当前完整场景状态

逐项使用PASS/FAIL/NOT_VERIFIED。已通过的子步骤不自动升级为完整场景PASS。运行时b50103f、实际Portable v15；真实浏览器步骤、数据库断言、截图和失败日志见下列收据对应的scripts/validate_*.py。完整UAT/G7仍未通过。

| ID | 完整场景 | 已验范围与剩余项 | 证据组 |
|---|---|---|---|
| U01 | PASS | 实际ECRA.cmd、Windows-only PATH、包内Python、私有默认数据根，首屏三入口/真实示例；非物理干净机双击。 | launcher,sample,main |
| U02 | FAIL | 四步/回退/往返/目录/上下文已验；完整真实构建参数与执行计划在启动前尚未验证，不能把路径检查称作构建通过。 | main,profile,contexts,directories |
| U03 | NOT_VERIFIED | 42文件真实ACL只读DB扫描/原新对照/原数据不变已验；只读外置CMake全模式、物理只读挂载与生产写保护未齐。 | main; readonly-native-f030-v2 |
| U04 | NOT_VERIFIED | 真实refs/HEAD/dirty提示/分页/保存6项已验；dirty字节正式固定和大型原生Diff输入/结果尚未完成。 | git |
| U05 | FAIL | 工具缺失路径提示存在，但当前profile检查不是完整的、阻止启动的真实工具/编译环境门禁。 | profile,main |
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
| U16 | NOT_VERIFIED | 确认/筛选/页码/继续位置、真实服务重启已验；1000项分批人工操作压力场景未完整实测。 | main,sample,capacity |
| U17 | PASS | 实际撤销追加审计事件，原确认及理由/历史继续可见；不覆盖旧事件。 | main |
| U18 | NOT_VERIFIED | 底层变化证据RECHECK/历史保留已有原生回归；当前包源码/构建变化后GUI继承和重新确认完整流程仍待验。 | main |
| U19 | NOT_VERIFIED | 一台主机两独立根/服务/origin完整包与继续确认已验；无固件Viewer可实际启动；第二台物理机待验。 | collaboration,sample,launcher |
| U20 | PASS | 两真实服务的GUI增量传播、重复导入、并行冲突、缺理由拒绝、全父分支显式解决及再导出重开7项通过。 | collaboration |
| U21 | FAIL | 真实完整旧结果归属/转换/审计原文件/确认/重复/失败保护6项通过；缺证据降级Viewer及大型双旧结果迁移仍未齐。 | legacy |
| U22 | NOT_VERIFIED | 1366/1600/1920及工作台/对话框主操作已验；浏览器密度模拟不作Windows原生系统DPI，全部极端状态/长名未齐。 | main,sample,directories,contexts |
| U23 | NOT_VERIFIED | 实际GUI清理计划/恢复/二次确认释放通过；较早50GiB容量证据保留，当前包完整50GB场景仍未重验。 | main |
| U24 | PASS | 实际UI恶意/损坏结果包拒绝且旧库/人工记录不变；严格包校验单元覆盖另有证据，不等于G5全故障矩阵。 | main,legacy |

证据组对应evidence/browser-portable-v15-{组名}.json；只读见evidence/readonly-native-f030-v2.json。机器表为evidence/user-scenarios-v15.json，含用户原始预期。完整Playwright步骤在对应脚本，trace/video/详细日志留在收据的外部work/output路径。legacy首轮误用UNKNOWN筛选以及launcher提前断言的失败记录保留，修正控制器后重验；未改产品数据或放宽后端校验。

{'PASS': 7, 'FAIL': 3, 'NOT_VERIFIED': 14}；不能宣称U01–U24全部完成。工程师5–8人盲测和Windows原生系统DPI仍NOT_VERIFIED。
