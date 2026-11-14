# 结果包实操记录

后续真正新增事件的增量合并、并行冲突保留/显式解决及I12修复复验，见 [冲突补充](conflict-review.md)。此处早期“dc5为6事件”等为当时快照；最终主根dc5为原6+新增3=9事件，不覆盖历史。

日期：2026-11-14。使用独立持久 Chrome 156.0.8078.79 / Python Playwright，Windows，1366×768 视口、deviceScaleFactor=1；未模拟浏览器缩放或操作系统显示缩放。页面来自本轮隔离服务 `127.0.0.1:54917`，数据根 `H:/ECRA-ui-practical-20261114/data`。与主代理浏览器完全独立。

前半程前端为 `index-Jd5kW4Cc.js`。I05 修改后由主代理统一构建；重新打开持久浏览器，实际 script DOM 确认为 `index-Dz_fcmH4.js` 后复验通过（package-81～84）。

所有导出、文件选择、导入、打开归档、筛选项和进度操作均来自真实页面控件。只读审计用于核对结果；没有通过 API、DOM、数据库或浏览器存储写入制造操作成功。正常关闭并以原持久 profile 重开后，导入样例仍可见（package-41）。

|编号|入口/目的|适用条件、预期及依据|实际操作|实际结果|问题|状态|证据|
|---|---|---|---|---|---|---|---|
|P01|历史→详情→标准完整包|已有有效 dc5 归档；按 UI 完整包定位应保留完整证据与人工历史|打开 dc5 详情，导出，按提示前往数据与共享，展开导出记录，下载|736986 字节 ZIP；105 个清单成员全部尺寸/哈希正确；16 对象、6 人工事件、绑定和原记录一致|无|已通过|package-04～06、08～10；audit-export-full.json|
|P02|历史→人工确认增量|同一归档有人工记录；应下载包含事件身份/父链的增量|详情中导出并接收真实浏览器下载|8674 字节 UTF-8 JSON；6 个完整事件身份及父链与原库一致；新版本进度准确显示“人工确认增量已就绪”|进度误称完整包(I05)已修复|已修复并通过|package-07～09、81～84；audit-export-delta.json；ExportProgress.vue|
|P03|完整结果导入→已有同一归档|UI 约定失败不污染已有数据、完整历史合并|选择刚下载 dc5 完整包并等待|完整性验证成功，新增事件0，合并到现有归档；前后静态、绑定、人事件逐项一致|无|已通过|package-11～12；idempotent-import-comparison.json|
|P04|人工增量导入与重复导入|当前选择 dc5，增量属于同一证据版本；UI 约定重复去重|连续两次选择已导出的人工增量|两次均完成/新增人工事件0；dc5仍6事件、待办4；stress未受影响仍4事件/待办146|无；当前入口上传后直接校验并合并，没有独立“预检确认”弹窗|已通过|package-13～16；audit-after-idempotent-imports.json|
|P05|损坏完整包失败与恢复|测试准备52字节非ZIP文件；不能发布或损坏旧数据|选择 invalid-package.ecra-report，查看失败，再选择真实内置包|明确指出ZIP无效、旧数据保留及重新获取完整备份；随后正常包可成功导入|无|已通过|package-17～20；audit-package-flow.json|
|P06|完整包新归档导入、打开与证据|原库不存在 builtin-stm32-demo-v1；现成真实扫描包|选择 ecra/studio/sample_assets/stm32-demo.ecra-report→打开导入归档→g_counter证据→归档源码|发布新归档；16对象/6待办/0人工；清楚标教学示例、归档证据、来源尚未验证；31并发关系、7访问及源码可读；重开后仍在|无|已通过|package-19～25、41；audit-imported-sample-package.json、audit-after-sample-import.json|
|P07|跨项目人工增量拒绝|当前样例工程，输入demo-a增量；不可串项目/证据|在样例选择demo-a增量|明确“增量包不属于此扫描/证据版本”；样例仍0人工事件|无|已通过|package-27～28；audit-package-flow.json|
|P08|完整包压缩选项|完整包应保持完整证据，两种压缩由用户选择|当前样例选择“省空间”，导出并真实下载|442731字节，34成员校验正确，scan.db压缩类型BZIP2(12)；历史默认full为DEFLATE(8)，选择实际生效|无|已通过|package-29～30；audit-export-compact.json|
|P09|导入/导出记录与进度附属入口|已有成功和失败记录，应可查看、刷新、收起、隐藏再显示|两区查看记录、更新进度、隐藏/显示；失败信息仍清楚|真实完成状态和历史full导入任务可读，控制无报错|人工增量仅本页当前传输反馈，不将此前增量任务历史持久化作为已验证|已通过（列明范围）|package-09、31～37|
|P10|运行中取消后台导入|已存在sample归档，重复导入原包不覆盖；无延迟桩|独立浏览器重开后加载Covwq14P，UI选sample-compact包→动态“取消导入”→结束|dc723cb2ae2843d3bc71ce09bf9045f8为CANCELLED/VERIFY_DATABASE、result null；界面已有扫描和人工保留；本次16库SHA全相同|无|已通过后台导入取消；不包含上传阶段取消|package-180～185；import-cancel-preservation.json；185视口已实际查看|
|P11|运行中取消导出|stress真实归档155对象，选省空间压缩，不人为延迟后台|第一次导出7.3秒自然完成，取消点击未赶上，记录驱动超时；第二次重新发起后立即真实点击取消|任务bf82eb28a3e041239b031a2ed858ec8b为CANCELLED，界面“已取消导出；原扫描与人工记录保留”，无下载按钮/发布包；目标stress扫描/人工库SHA不变；另一个6919库变化已单独核对说明|无产品缺陷；第一次是时序未覆盖|已通过取消导出|package-167～179；tasks-and-exports-final.json、export-cancel-hash-investigation.json；179视口已实际查看|
|P12|上传阶段取消|上传中动态取消按钮，与后台导入取消不同；受支持CDP上传限速20KiB/s|先约29.6%实际取消发现文案问题；更新后端重启后约40.7%再取消，恢复网络|新job0476c1c6b9b741c2b504ca5bb953d0d3为CANCELLED/UPLOAD、无result，UI明确已取消导入上传；原失败记录保留|I13修复主动取消与断流提示语义|已修复并通过|package-225～235；[上传补充](upload-cancel-review.md)|

I05 根因：`studio/src/ExportProgress.vue` 完成态成功提示未区分 `job.kind`。只对 delta 改成“人工确认增量已就绪”，保留完整包原文。此改动不影响导出逻辑。

实际查看的关键视口截图：package-08（导出页面）、12（完整包合并完成）、18（损坏包失败）、24（导入后证据）、28（跨项目拒绝）、30（压缩导出）、84（新版本增量/完整包文案）。截图与每步ARIA DOM位于 [output/playwright/ui-practical-20261114](../../output/playwright/ui-practical-20261114/)，记录 [package-operations.jsonl](../../output/playwright/ui-practical-20261114/package-operations.jsonl)。上述截图均已通过 view_image 实际查看。

下载保存位置：`H:/ECRA-ui-practical-20261114/downloads`。审计位于 [output/ui-practical-20261114](../../output/ui-practical-20261114/)。`audit-export-full.json`、`audit-export-delta.json`、`audit-export-compact.json` 保存文件大小、SHA-256、成员/事件验证；`audit-package-flow.json` 保存后台导入任务、跨项目拒绝后样例事件数及重扫继承证明。

重扫关联只读核验：41986655eb5c492aa549feb5b7e701bb 的3个历史引用分别对应 g_counter、main.c state、other.c state，FULL_INPUT_AND_FACTS_V1 全部验证通过，原6事件逐字段保留，当前没有伪造新签署；原dc5归档仍6事件，未被改写。

本记录仅说明本表范围；真正新增事件的增量合并与并行冲突解决已在独立可恢复副本上补验，见[冲突补充](conflict-review.md)。没有把同机独立副本测试称为两台物理机器验证；超大包断点续传未经过本轮真实UI验证。
