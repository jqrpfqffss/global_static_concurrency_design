# 设置、备份与维护实操补充

这是 `aux-review.md` 的写入闭环补充，使用同一隔离 Studio 服务、Windows Chrome 156.0.8078.79、独立持久 Playwright 配置、1366×768 视口，实际脚本版本 `index-Dz_fcmH4.js`。所有操作来自真实界面；准备数据、只读核验与测试结束后的环境恢复另行注明。截图/DOM位于 `output/playwright/ui-practical-20261114/package-*`，完整操作日志为同目录 `package-operations.jsonl`。

|编号|入口和目的|前提、预期依据|实际操作与结果|状态、证据|
|---|---|---|---|---|
|MA01|设置→整套备份与恢复：复制完整可恢复数据|新空目标；产品说明不覆盖原根且全部校验后发布|填 `H:/ECRA-ui-practical-20261114/backup-ui`，检查计划1415文件，确认复制。进度从179、329、747、985、1306到1415，最终复制完成；源数据根继续工作，目标副本已发布|已通过复制及文件校验；package-94～109、backup-ui-integrity.json、audit-backup-ui.json。恢复副本后独立启动未在此项验证|
|MA02|数据位置：保存下次启动偏好并重新进入|当前根由CLI明确指定；界面说明保存不覆盖当前运行位置|检查已完成备份根，保存默认目录，刷新后仍显示该默认值，而当前使用仍为data/启动参数。再经UI检查并保存回data|已通过保存和刷新持久化；package-110～118，preferences-after-ui-save.json、preferences-after-ui-restore.json。未重启服务验证无CLI启动的默认根选择|
|MA03|存储策略：保存与重新读取|策略作用于下一次扫描，默认auto；已有归档保留|选off保存，刷新并重开tab显示“保持普通文件”，文件mode=off；选择auto保存再重新读取，显示自动，文件mode=auto|已通过设置保存/回读；package-119～126、storage-policy-after-ui-save.json。未据此声称off下新扫描文件布局验证|

备份期间后台页面信息请求真实遭遇数据根独占锁，出现历史失败红条；复制组件仍持续显示进度，最终完成。正常刷新后红条清除（108→109）。它没有把复制失败报成成功，也没有改变备份校验结果，记录为历史请求反馈，不新增问题编号。

`backup-ui-integrity.json`核对1415个副本收据文件，SHA全部一致；10个扫描/人工数据库复制前后源SHA未变，副本与源一致。副本深审计5个归档、4个项目无审计错误。副本保存的是复制时点；之后其他UI扫描/签署不应被误认为已包含其中。

环境恢复：本轮私有 `private-localappdata/ECRAStudio/preferences.json` 初始不存在。先由UI把偏好改回当前data并保存收据，再仅移除本次新建的这个私有测试偏好文件，恢复“未设置”初态。该步骤属于测试结束恢复，不是UI重置功能验收；没有修改正式用户偏好、扫描、确认记录。存储策略由UI恢复auto，保存文件保留。

|编号|入口和目的|前提、预期依据|实际操作与结果|状态、证据|
|---|---|---|---|---|
|MA04|旧结果迁移：兼容旧格式正常转换|父代理按tests/test_legacy_import.py准备5文件兼容fixture，明确不是native扫描；原件不能改写、旧复核不能冒充当前结论|UI填写legacy-fixture/.ecra与其工程root→检查→开始只读迁移→打开结果；发布1对象UNKNOWN、人工待办1、当前人工事件0；顶部明确旧格式只读|已通过此兼容fixture路径；package-128～137；legacy-fixture-receipt.json、maintenance-after-legacy.json|
|MA05|旧原件/事实查看|迁移完成，保留5文件原件与事实结构|查看旧文件与复核历史→review/answer.txt归档片段，显示原70字节UTF-8文本和非安全证明说明；关闭→完整权威证据→覆盖页全部索引→展开完整事实，看到对象/访问/order结构；关闭|已通过；package-138～149。没有把完整事实入口只跳覆盖页计作已读事实，继续打开索引后核验|
|MA06|重复迁移幂等|相同源目录和归属，不能覆盖旧归档或重复确认|再填同一路径→检查→迁移完成，提示“相同来源已导入：打开已有归档，原人工确认保留”；仍仅1 legacy归档，所有既有DB SHA不变|已通过；package-150～155；maintenance-after-legacy-repeat.json、maintenance-preservation-summary.json|
|MA07|空间清理：实际隔离与恢复|完整备份已在；候选全部属于隔离根且通过引用/哈希校验|预览18项（10个可重建TU缓存+8个未引用证据对象），核对路径和SHA→勾隔离确认→确认暂存；实际18项源位置消失、QUARANTINE。点击恢复原路径→RESTORED18，无冲突，全部原SHA匹配|已通过隔离/恢复；package-156～166；maintenance-before-quarantine.json、maintenance-quarantined.json、maintenance-after-restore.json|
|MA08|永久释放入口|仅隔离后出现，不应默认可用|隔离完成时显示永久释放复选框及禁用按钮；未勾、未执行永久释放，直接恢复|入口/禁用反馈已观察；永久释放结果受阻未验证（本轮选可恢复验证，不把恢复等同永久删除）|

legacy归档身份为 `legacy-8f71d4cb67b5baa438dc92a513c36c95f259f571f568510d63e30a92a5f57147`，manifest为 `LEGACY_READ_ONLY`；兼容fixture的5个输入SHA从准备到重复迁移、清理恢复均未变。原件声明不作为当前AI复核，当前人工事件为0。

清理计划 `8efe1137b5284db29d4b364aecfedcab`，恢复任务 `422836f46baa4c4592e7c772c2b53d9a` 已COMPLETE。`maintenance-preservation-summary.json`核对隔离期间与恢复后16个scan/reviews数据库SHA均未变，18候选逐个恢复原路径和原SHA；未执行purge。

更正导出取消时间窗的全库SHA表述：`audit-completion-checks-20261114.json`原始字段为false，实际15库字节不变，仅6919的reviews.db变化；导出目标stress的scan/reviews两库均不变。6919前后全部已审计业务字段完全相同，包括静态/规范绑定、0人工事件、3个prior完整payload哈希及AI数量；其scan.db SHA不变。主代理同期进入6919“继续人工确认”，代码路径continueReview→loadSelection→rememberList会PUT position并UPSERT positions，当前保存g_counter浏览位置。没有该时间窗之前的positions完整值快照，所以位置保存是与事实一致的解释，不能宣称已通过逐表字节对比证明唯一原因。明确保留这一归因限制，不把false改成true。详见 `export-cancel-hash-investigation.json`。后补sample后台导入取消的独立前后时间窗，16库SHA确实全部一致，见 `import-cancel-preservation.json`。

最终只读数据审计正式引用 `output/ui-practical-20261114/audit-completion-20261114.json`（8归档、5项目、0绑定问题/0深审计错误）及 `audit-completion-checks-20261114.json`。旧dc5的6人工事件从包操作前到最终完全相同；同输入4198正确继承3旧对象，变更输入6919保留3旧事件组但校验为需重新确认，raw RECHECK3，实际待办6。stress8人工事件正确绑定，风险6/安全2，142待办。任务7057失败与6919成功均manual 2GiB/1 worker，9dd0恢复成功为auto，不能混写。多核上传目录无文件且没有合并task。

已实际查看视口截图：package-105（复制中）、108（复制完成）、115（偏好保存刷新）、123（策略保存刷新）、132（迁移预览）、137（旧归档概览）、141（旧文本原件）、148（完整事实索引）、159（长候选路径）、162（隔离后恢复入口）、165/166（恢复状态）。这些是当前视口图，不是整页长截图。

附属验证结束，所有本浏览器弹窗已关闭，独立持久浏览器正常关闭，驱动输出 `PACKAGE_BROWSER_CLOSED`。主浏览器、主服务均未关闭。

后续已补足 MA01 的备份副本正式启动与人工历史/归档源码查看、MA02 无 CLI/环境覆盖时读取 GUI 默认根、MA03 off 下真实新扫描与文件布局，并完成代表性输出目录占用失败→恢复→重试导出。详见 [recovery-startup-supplement.md](recovery-startup-supplement.md) 的 RS01–RS04；原表的“未在此项验证”保留为先前时点记录，最终状态按此补充。专用副本服务60123/60718与浏览器均已关闭，主54917保留。
