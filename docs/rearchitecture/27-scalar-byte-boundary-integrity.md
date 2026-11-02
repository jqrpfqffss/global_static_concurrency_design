# 标量字节边界与失败界面状态修正（源码验收通过，实包待验）

## 已确认的缺口

旧`EvidenceProvider.validate(deep=True)`按声明长度循环读取1MiB块；空字符串不读取任何块，恰为完整块长度时不会读取块后的附加内容。未先确认SQL字段实际BLOB长度，导致这两类字符串可以附加未参与原节点哈希的内容。普通短字符串以及本次普通整数/浮点追加测试原已拒绝，不能把问题扩大描述为全部标量都可绕过。

在独立私有合成库和真实ZIP导入流程中重现：修改空的future_note、保持事实/报告根及人工指纹不变、重算包内数据库文件摘要后，旧导入接受了额外内容，并保留原NEED_MORE_EVIDENCE事件。没有修改真实固件或真实归档；这些负例不作为原生G1/G2或用户安全判断。

## 实现

`scan_store.py`在同一只读快照的节点遍历中，读取`typeof(value)`及`length(value)`元数据，验证声明长度为非负整数、容器的未使用payload必须NULL、每个标量必须为BLOB且实际字节数恰等于声明。仍逐块计算原有完整有序类型化SHA、验证编码/关系/全部查询投影；没有缩小或取消其他门禁，没有改schema、节点哈希、有效数据或分析策略。

新增三个黑盒回归：空/短/1MiB边界/跨块Unicode的尾部拒绝；SQL存储类型/非法容器payload/分数长度拒绝；重算ZIP外层摘要的恶意包导入和坏源导出均拒绝，已有有效静态库及人工库逐字节不变。

GUI控制器增加`--scalar-tail-adversary`：以真实F030标准包的独立副本制造坏输入，只修改攻击包的批次头和payload/外层摘要，使用实际文件选择控件/本地API导入，核对字节长度错误、无新扫描发布、原库与全部事件未变。它不模拟页面/API、不作新原生扫描或目标板安全宣告。

同时按FAILED状态合同修正`App.vue`：操作失败时清除仍以“正在”开头的临时提示；已提交的成功提示不会因此被当作未提交。布局、配色、导航、扫描与确认语义保持。真实浏览器须验证失败后不再显示“正在校验”。

## 验收边界

| 范围 | 当前实测 | 状态 |
|---|---|---|
| 原缺口 | 私有空/1MiB字符串边界实际接受；私有恶意ZIP实际导入且根/既有事件指纹未变 | [边界重现](evidence/scalar-boundaries-before-v1.json)、[实际ZIP重现](evidence/scalar-tail-package-before-v1.json)，旧候选该项FAIL；原包/日志保留 |
| 新字节边界/标准包回归 | 27项PASS、11.170s，含3个新增对抗回归与原有8MiB有界验证 | [源码专项](evidence/scalar-boundary-regression-v1.json)，不能代替新实包 |
| 旧格式/流式/保存消费者 | 首轮显式模块运行遗漏tests目录，test_saved_json按原代码import test_ecra失败；按discover相同路径设置后43项PASS、115.005s | [首轮FAIL](evidence/scalar-boundary-legacy-v1-harness-failed.json)、[更正后专项](evidence/scalar-boundary-legacy-v2.json)；未修改原消费者来适应测试 |
| Vue/TypeScript与实际源码GUI | vue-tsc/vite实际构建成功；真实Chrome17项PASS、无页面异常/外部请求，重算摘要的真实F030恶意包被400拒绝，旧静态库/全部人工事件未变；失败后无“正在校验”提示 | [浏览器收据](evidence/browser-scalar-tail-host-v1.json)、[实际截图](ui/screenshots/scalar-tail-host-v1/11-unhashed-scalar-package-rejected.png)。不是新Portable/物理DPI/UAT |
| 实际同输入F030原生 | 完整facts及严格规范report差异0，42原输入与93引擎文件前后不变、原配置SHA不变，预期INCOMPLETE exit2；驱动含验证共26.625s | [原生对照](evidence/scalar-boundary-native-exact-v1.json)，不是大型G1/G3 |
| 完整1315项/新Portable/最终大型冷扫描 | 须在本修复提交后冻结源码运行 | NOT_VERIFIED，不借用v20/v21/v22旧收据 |

旧候选程序包不覆盖或删除；其原测试结果仅证明当时已测场景，不能声称已拒绝此新增恶意输入。当前完整G6/H6与发布门禁仍未关闭。新的默认验收必须包含本修复，最终冷扫描也必须绑定修复后冻结源。

此勘误适用于修复前所有使用该节点校验器的候选（包括v19/v20/v21/v22）；它们不是已通过本次对抗场景的发行版本。v19原封存收据保持历史记录；v20/v21候选汇总明确将G6记为已知FAIL。v22仅完整1312回归和实际构建完成，未运行十三组浏览器验收，不封存成全验实包。

开发机复现：`py -3.10 -m unittest tests.test_scan_store tests.test_report_package -v`；完整套件使用`py -3.10 -B -m unittest discover -s tests -v`。真实GUI负例使用`scripts/validate_studio_ui.py --scalar-tail-adversary`，其余原生/包/工作目录参数见收据；必须指定新的独立验收目录，不能覆盖历史数据。
