# 工程身份与异步导航阶段（2026-11-02）

本阶段接续ba866f4。v17实包不含此阶段代码，不能借用其验收。完整重构仍未完成；G1大型、G3/G4、生产H2及物理/UAT门禁保持原状态。

| 功能 / 场景 | 实现文件 | 实际验证 | 状态 / 证据 |
|---|---|---|---|
| H5，当前工程/构建身份 | `ecra/scan_identity.py`、`ecra/scan_persistence.py`、`ecra/studio/server.py`、`studio/src/ScanIdentity.vue`、CSS及编译资源 | 从InputSnapshot逐字节核验过的配置捕获名称/目标；变体取归档CMakeCache；顶部60px身份带及完整详情；实际Release/demo原生扫描可见 | 源码PASS；[13项真实Chrome](evidence/browser-scan-identity-v3.json)、[合同](ui/20-scan-identity-contract.md) |
| 旧归档不补造身份 | 同上 | 旧工程根目录名明确标来源，目标/变体/配置未知时标未记录；不读取当前profile/原固件反推；标准包往返一致；三个视口关闭按钮固定、Esc归还焦点且保留变量 | PASS；[旧归档Chrome11项](evidence/browser-identity-archive-v1.json)、[截图](ui/screenshots/scan-identity/identity-archive-v1-06-identity-archive-1366.png) |
| U09/U17，统计及撤销 | `scripts/validate_build_preflight_ui.py` | 当前F030实际四卡均按同分母下钻；真实确认后撤销新增第二事件，完整保留原理由和撤销所指事件ID；静态SHA不变 | 已验子范围PASS；13项收据含相应断言，不把软件自动化当工程师UAT |
| 异步导航与批次隔离 | `studio/src/App.vue` | 结果打开中的旧响应不再强制返回概览；只接纳当前refresh代次/批次；切换时同步清空旧summary；快速进入配置后保持新路由 | PASS；首轮[实际导航失败](evidence/browser-scan-identity-v2-failed.json)保留，修复后相同连续操作通过 |
| H1，完整同输入小工程 | `scan_identity.py`仅provenance增补，无保护区算法变化 | 原始配置路径/字节、固件4TU、宏、DB、工具链不变；只用同一WorkspaceResolver把输出引到新隔离目录；完整facts与严格规范report零差异；原文件SHA/mtime不变 | PASS；[原生严格对照](evidence/scan-identity-native-exact-v1.json)，不是大型G1/G2/G3 |
| API/包/原生回归 | `tests/test_scan_identity.py`、`tests/test_canonical_scan.py` | 8项新专项加原canonical/API/package共36项116.183s；随后新增真实持久化连接断言单独再跑1项；前端类型检查/构建与12条静态UI合同通过 | PASS；[36项](evidence/scan-identity-focused-v1.json)、[原生连接1项](evidence/scan-identity-native-wiring-v1.json)、[UI合同](evidence/scan-identity-ui-contract-v1.json) |

13项联测首轮仅控制器误把撤销备注当原文（实际按合同包含所撤销event_id前缀），[8项后失败](evidence/browser-scan-identity-v1-failed.json)保留；修正为精确匹配事件ID和完整理由。第二轮揭露真实导航竞态，改产品后第三轮13项全部通过，未延长超时或更改静态数据。随后只改身份详情的滚动/固定关闭布局，用真实旧归档11项重新验证截图与键盘行为，不重复无关原生扫描。

## ADR-016：显示身份属于归档来源，不属于静态判定

不向facts/report增加显示字段。`storage.json`保存配置文件指针；归档输入循环在读取并匹配输入SHA后，将同一字节中的显示名称/配置目标和实际CMakeCache变体追加到`provenance.display_identity`。原配置、未知字段、注释、数组顺序与事实全部保持。超过256KiB配置不再为显示重复解析，明确标注上限并保留原文件；超过16KiB显示字段通过现有段式证据查看，不恢复大对象。

旧库不回填、不改写。API只解析有界归档标量，字段缺失逐项未知。工程名称是配置声明，既不表示芯片识别，也不授予静态有效/人工/AI权限。现有标准结果包与Viewer协议直接携带新增provenance，旧读取器忽略未知字段即可。完整同输入对照仍保留原比较规则，未扩大规范化范围。

大型诊断发布仍在运行；已排队在它真正结束且4123输入/890引擎文件后验不变后，执行严格全图对比及标准包完整往返。该验证单独受2GiB Job限制；若原生无效则拒绝开始。排队不等于完成。
