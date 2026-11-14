# 独立启动、存储和输出失败恢复补充实操

日期：2026-11-14。沿用已建 runtime、first-use-data、已手填 demo-b 配置及 backup-ui；没有重复制固件或 runtime，没有操作主根的偏好、存储策略或人工记录。这里补足 maintenance-review 的 MA01–MA03 后半程及代表性输出写入失败。

环境为 Windows 10 Pro 10.0.19044、Chrome 156.0.8078.79，项目 Python Playwright 操作 headed 持久浏览器，1366×768 CSS 视口、device_scale_factor=1；未更改系统缩放，未声称另外验证系统缩放。全部浏览器动作来自真实链接、按钮、表单及下载；DOM 只用于读取快照和资源版本。所有本节页面实际加载 `index-Covwq14P.js`。沿用 CUA 不支持 iab 时经用户授权的 Playwright 回退。

|编号|入口及目的|条件与预期依据|实际操作|实际结果、问题和状态|证据|
|---|---|---|---|---|---|
|RS01|设置→数据位置：默认目录影响下次正式启动|私有 LOCALAPPDATA，first-use-data；界面说明 CLI/环境优先，保存作用下次启动|UI 检查当前根→保存下次目录→关闭浏览器和副本服务；正式 ECRA.cmd 不传 --data-root，启动脚本移除子进程 ECRA_DATA_ROOT→重开设置|实际显示 first-use-data，来源“GUI保存的默认目录”；配置和样例仍可见。已通过，无新缺陷|firstuse-57～64；first-use-default-saved.json；launch-first-use-default.ps1；first-use-preference-closed-tree.json|
|RS02|设置→存储策略与工程配置→开始此配置扫描|已手填 profile 52b7a4123c704758b86d53b9a32293da；策略应作用新扫描|UI 保存 off→打开已保存“首次手填 demo-b”→开始此配置扫描→观察预检查/正式2TU→打开结果；完成后 UI 恢复 auto|真实任务 ca4ed67ca5754bddbe5345c6d0c153f4 发布，demo/Release/Cortex-M7，16对象；扫描元数据及任务快照 mode=off，89文件无 NTFS Compressed 标志，5条压缩诊断均 SKIPPED_POLICY_OFF。恢复后设置文件 auto，本次扫描仍保留 off。已通过|firstuse-65～76、85～88；first-use-off-storage-proof.json；scan diagnostics/storage-compaction.jsonl；first-use-output-recovery-proof.json|
|RS03|数据与共享→完整包：输出路径错误与重试|可恢复 first-use 根；测试准备独立于 UI 验收，校验绝对路径后以普通文件占用尚不存在的 exports 目录位|UI 导出→查看失败卡；恢复时校验 marker 内容并仅删该文件→UI 再导出→下载完整包|第一次 FAILED，明确 WinError183 与 exports 路径，无下载成功；第二次 COMPLETE/100%，可下载506856字节包。ZIP CRC正常，49成员，manifest 48文件大小/SHA全部正确，scan.db与本次扫描逐字节一致。已通过。此测试是输出目录被文件占用，不是 ACL 权限拒写|firstuse-77～83，已查看80和83；first-use-output-failure-preparation/restored.json；first-use-output-recovery-proof.json；失败47bca9d9bd0b490abbe3d096ede8a479、成功291cc822b10247e68d61da2dec7e2983|
|RS04|整套备份后的正式启动、历史与人工证据|已完成并逐文件验证的 backup-ui（1415文件）；独立私有偏好和浏览器，原副本未改人工结论|正式 ECRA.cmd --data-root backup-ui启动→历史5归档→打开dc5→人工确认有风险2→state main.c:5→人工历史→归档源码→设置核对实际根|三条原有修改/撤销历史、备注和事件ID完整，归档源码行5可读；设置明确 backup-ui/启动参数。5个scan.db SHA与启动前完全相同，14个人工事件（stress8+demo6）的数量和内容哈希全不变。已通过，无新缺陷|backupverify-01～14，已查看10/12/14；backup-launch-before/after.json；launch-backup-verify.ps1；原备份校验 backup-ui-integrity.json|

## 实际数据与过程说明

第一次导出失败记录仍保留在 `first-use-data/work/export-jobs/jobs.db`，不是清除失败后制造成功。trace 指向 `export_jobs.py:136 exports.mkdir(exist_ok=True)`。失败卡在导入进度之后，通过真实滚动看见；顶部提示为“已启动后台导出”，具体结果卡正确标为失败。本次没有修改产品代码或放松任何校验。

first-use-supplement 的“没有扫描、仅教学归档”是 FU01–FU09 完成时的记录；本补充随后实际执行了 RS02。现该隔离根包含教学归档和 ca4 扫描，不应继续引用旧时点的 tasks=[] 作为最终状态。

下载包 `H:/ECRA-ui-practical-20261114/downloads/first-use-off-full.ecra-report` SHA256 为 `3db128bae46873e50a5729d3e4ff5d570fc3c2454048a9c7703c56f834878779`；其 scan.db SHA256 为 `2cc0195b794c70fa39ec3d612e4c96667622fc488bd885ab18da5d352b0f8bc8`。本补充没新增人工确认事件。备份是在 earlier 5归档时点，不能与主根后来新增归档混为一谈。

完整操作日志是 `output/playwright/ui-practical-20261114/firstuse-operations.jsonl` 与 `backupverify-operations.jsonl`；每个动作有同名前缀当前视口 PNG 和可访问性 TXT。中间请求仍在进行时的截图不能作为完成依据：RS02终态用74/76，导出终态用82/83，策略恢复用88，备份历史用10。

## 收尾与最短继续步骤

两个持久浏览器均正常 close；只结束核对过命令行的专用启动进程树。最终60123和60718均无监听、对应进程已退出，主服务54917继续监听。证据为 first-use-final-closed-tree.json、first-use-final-shutdown.json、backup-verify-closed-tree.json、backup-verify-shutdown.json。GUI保存的 first-use 私有默认偏好保留用于重现，生产及主实操偏好未动，两个数据根与浏览器目录保留。

继续 first-use：运行 `output/ui-practical-20261114/launch-first-use-default.ps1`，用新 first-use-session.json 的 URL 打开；可直接在历史打开 ca4，或工程配置打开“首次手填 demo-b”。继续备份：运行 launch-backup-verify.ps1，使用新 backup-verify-session.json 的 URL。这些脚本使用独立私有偏好；一般主实操仍用 launch-isolated.ps1，不应拿副本启动替代主启动。

本节没有执行 ACL 拒写、真实磁盘满或操作系统缩放变化；不能由目录占用失败外推这些结果。没有新增超出父清单的功能数量，RS条目用于补足对应既有功能的证据。
