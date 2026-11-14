# ECRA 上位机逐项实操检查

日期：2026-11-14。本轮13项已确认问题均已修复并在实际程序复验，**仍有受阻未验证功能，不宣称上位机完整验收通过**。

|功能总数|直接通过|修复后通过|仍有问题|受阻未验证|不适用|
|---:|---:|---:|---:|---:|---:|
|87|70|12|0|5|0|

按独立用户目标去重，对应135条操作/边界记录；点击、截图、同名、分页、失败重试不重复算功能。I01–I13共13个缺陷均已修复并实操通过；I06/I08属于同一个任务状态展示功能，因此为12个修复后通过功能。核对见[功能汇总](functional-summary.md)、[详细清单](checklist.md)、[结构化清单](checklist.json)、[映射](function-map.json)。待检查项为0；受阻项未混入通过数。

## 主要修复

|问题|用户原先遇到的行为|新版原路径实操结果|
|---|---|---|
|I01 文本筛选失效|摘要已变，列表仍为旧数据|other.c正确1项；不存在函数+关闭、不存在上下文+Esc均0项|
|I02 已知缺口没有准确说明|DMA类型被显示为未识别|中文/原code一致，完整证据说明核查范围，不把缺口直接当错误|
|I03 阅读标签被重设|后到证据数据或同对象重读覆盖所选标签|加载中切调用、同对象重读/保存后阅读选择保持|
|I04 确认后下一项跳回|第二页052确认后跳回048|054→055、页末100→101正确，保存身份和持久记录一致|
|I05 增量误称完整包|增量下载完成提示可能误导用户|增量与完整包文字分别正确，实际内容完整|
|I06 终态仍提示运行|已发布任务仍提示进入扫描|已结束任务没有交接进行态，阶段历史保留|
|I07 比较覆盖未映射|INCOMPLETE被显示为未识别|双方完整根摘要显示部分覆盖及原状态码|
|I08 Diff误称全量|真实差异任务标题与结果范围冲突|标题准确显示扫描分析，归档保留真实差异身份|
|I09 同名头文件对象难区分|同名同文件行的5个static实例外观相同|列表/详情/确认对象显示TU；one/two分别签署与下一项准确|
|I10 长YAML失败无可见原因|正确拒绝后，错误在当前视口之外|错误进入1366当前视口、保存仍禁用，原配置可恢复|
|I11 同根配置难选择|仅路径和短ID，不能按名称找方案|名称/路径/短ID同时显示，切换后摘要及任务绑定正确|
|I12 并行冲突动作不清楚|普通确认文字未说明合并分支，空依据可点后端拒绝|明确三种合并动作、空依据禁用；填依据合并成功，刷新3条历史和双父链均正确|
|I13 取消上传原因错误|主动取消虽CANCELLED却提示断网重选|后端读取真实取消意图；正式新进程同包40.7%取消，准确提示已取消且原记录完整|

根因、修复位置、前后截图见[问题台账](issues.md)。修改围绕App.vue、filterUpdates.ts、CoverageCenter.vue、TaskCenter.vue、HistoryCenter.vue、ExportProgress.vue、api.ts、workbench.css与对应测试；I13还修复ecra/studio/import_jobs.py和server.py的真实上传生命周期根因，未放宽校验或清空历史。最终全部Studio测试32/32、I13相关后端组合测试41/41、npm构建/类型检查、git diff检查通过，见[回归详情](regression-details.md)和[最终测试日志](../../output/ui-practical-20261114/studio-tests-final.log)。

## 实际环境与版本

- 当前工作区`H:/global_static_concurrency_design`，分支`optimize_ccc`，起始提交`06d5a39`。用户原有10个ZIP/PPTX删除项保留，未纳入本轮修复提交。验收阶段没有提交或推送；验收完成后，用户另行授权提交本轮修改并推送当前远程分支。没有合并或发布。
- 正式入口为`ECRA.cmd`，实际为Vue页面、FastAPI回环服务及独立扫描任务。本轮通过`output/ui-practical-20261114/runtime`物理隔离副本中的正式入口启动，不是独立HTML。正式配置、报告和人工判断未被测试写入。
- 最终前端`index-CdM0AXW-.js`、`index-Dw60A1lg.css`，已由主线及冲突专项实际重载核对；I13后端两文件与源码SHA完全一致，经正式launcher同54917重启，新server31456。主线新会话读取位置/历史通过（36号）；同步与重启收据见i13-runtime-sync.json、i13-server-restart.json。早期B6iWxTn0、Cn6c7cff、BjcqUQke、Jd5kW4Cc、Dz_fcmH4、Covwq14P原图保留各自真实时点，不冒充最新构建。
- Windows 10 Pro build19044，Python3.10.11；主线CUA IAB，附属采用独立持久Chrome156.0.8078.79/Python Playwright。各专项明确可见窗口或无头模式，关键当前视口截图均实际查看。
- 主线覆盖1366×768、1920×1080；结束时恢复宿主默认1280×720 CSS视口、devicePixelRatio1.75。最终38号（已等加载完成）及后端重启后的36号图中6待人工、g_counter和旧历史无遮挡；37号是读取中间态，不作完成证据。没有单独调整验证浏览器缩放/Windows显示缩放，不能由dPR推定175%缩放。
- 主数据根`H:/ECRA-ui-practical-20261114/data`，独立偏好与runtime/config副本；first-use-data和backup-ui为额外隔离根。demo-a、demo-b、stress使用外置独立Git工程。两个分支冲突试验在同一Windows设备的不同数据根，不声称两台物理机器实测。

## 已完成的用户流程与数据核对

五条组合流程详见[用户流程记录](user-flows.md)。主线实际覆盖正式启动→工程/必要配置→真实构建/扫描→完整证据，连续筛选/分页复核、页面/浏览器退出重开、代表性失败恢复，以及跨项目/同工程多次扫描。纯手填新配置还实际从配置页启动ca4扫描并发布16对象。

- demo-a真实构建/扫描为16对象（6疑似、8安全、2容器）；扫描安全停止未发布，重试命中2TU缓存后发布。无效CMake目标明确FAILED，UI纠正后成功发布。1GiB预算正确拒绝，manual2GiB/1worker真实任务和auto恢复任务分别核对。
- stress真实155对象（150疑似、5安全），覆盖长名称/路径、40处访问、12层调用、多页待办和同名作用域/TU。最终8人工事件正确绑定，142待办，静态分类未被人工判断覆盖。
- 同输入重扫4198正确保留3组历史来源；同profile将隔离main.c:25的+1改+3后，6919真实重扫命中1TU/重提1，g_counter证据为+3、当前需重新确认。原历史仍在，本轮事件0，当前待办6。原源码字节备份见[恢复记录](recovery-supplement.md)。
- 人工SQLite写锁失败保留草稿、没有假成功，释放后同草稿保存成功；完整包输出目录被普通文件占用时真实WinError183，恢复后UI重试下载，49ZIP成员/manifest48项哈希与扫描库一致。后者不是ACL拒写或磁盘满测试。
- 完整包/增量下载、重复去重、新归档导入、损坏包失败恢复、跨项目拒绝、两种压缩，以及后台导入/导出取消均实际操作。上传阶段也通过支持的CDP限速形成真实进度，发现I13后在新后端原路修复通过。
- 真实新增增量使g_msgSP并行两分支可见，修复I12后显式合并，再刷新/重复导入仍唯一解决head。主dc5原6事件payload保留，新增2分支+1解决，共9；副本原14事件保留、授权新增1，共15。最新主根8归档/5项目、0绑定问题/0深审计错误，其余7归档业务不变，所有scan.db字节不变。见[冲突实操](conflict-review.md)与[分支审计](../../output/ui-practical-20261114/audit-post-conflict-checks-20261114.json)；最终上传复验后[终审](../../output/ui-practical-20261114/audit-post-upload-checks-20261114.json)确认16库字节和17事件payload全同、原5导入任务保留、临时文件0。
- 1415文件整套备份全哈希通过，备份根独立正式启动后人工历史/源码可读；无CLI/环境根重启正确采用GUI保存默认根；off策略真实扫描文件无压缩且诊断SKIPPED_POLICY_OFF，UI恢复auto。旧格式兼容fixture迁移、重复幂等、原件与事实阅读通过；18候选实际隔离再恢复原路径/原SHA，16保护数据库不变。

证据审计保留真实不一致信息：导出取消前后“全部16库字节不变”为false，未强改为true。目标stress与其余共15库字节不变；同期查看的6919 reviews.db字节变，但已审计业务事件/prior/静态/绑定均不变。变化与保存阅读位置路径相符，缺原positions整表快照，因此不作确定因果归属。见[范围解释](../../output/ui-practical-20261114/export-cancel-hash-investigation.json)。

## 剩余事项

5个受阻功能对应以下4类缺口：

1. 外部VS Code协议被Browser安全策略拒绝；未绕过。站内源码查看已通过。
2. 多核输入和合法ELF上传2项缺独立各核真实链接ELF及共享RAM绑定；同固件别名/对象库不替代。新增/移除输入、重复事实根和无效ELF拒绝已操作。
3. 真实模型成功调用授权范围尚待澄清。机器有OpenCode；人为缺命令只是负向测试，6项技术失败及仅重试失败不能代表模型成功。
4. 永久释放未执行。Computer Use工具原文要求：“Permanently delete data: Confirm before any deletion the user cannot reverse through the product’s normal recovery flow.” 用户已授权并完成可恢复清理；产品不支持原路径恢复的永久释放仍需该操作时确认。
附加UC02异常边界没有形成真实无主动取消的socket断流：CDP离线只短时影响轮询，正常关闭浏览器时上传也完成。两任务实际重复合并0，该分支仅有自动回归，不声称真实断流失败/恢复已验；它不是新增产品功能，不增加功能总数。

此外，浏览器和OS缩放未单独调整验证；实际视口与dPR已如实记录。受阻分支之后的动态入口不能据当前记录宣称已验证。

## 证据与继续入口

本次仓库提交包含修复代码、回归测试、构建页面和本目录记录。`output/`按现有`.gitignore`保留在验收机器，未随提交上传；下列截图、运行日志和数据审计链接是本机证据位置，远程检出不会自动带有这些文件。独立测试数据根与临时会话凭据也不在提交中。

- 核心记录：[清单](checklist.md)、[功能汇总](functional-summary.md)、[问题台账](issues.md)、[完整用户流程](user-flows.md)。
- 专项：[附属入口](aux-review.md)、[结果包](package-review.md)、[AI失败与I10](ai-failure-review.md)、[首次手填](first-use-supplement.md)、[维护/迁移](maintenance-review.md)、[扫描恢复/源码变化](recovery-supplement.md)、[独立启动/输出恢复](recovery-startup-supplement.md)、[新增增量/冲突](conflict-review.md)、[上传取消与I13](upload-cancel-review.md)。
- 截图/DOM在`output/playwright/ui-practical-20261114/`：38为最终就绪主页面，36保留后端正式重启时点，35保留上一进程时点，24为TU区分，package209/219为冲突修复及重开；firstuse80/83为输出失败与恢复。
- 数据、任务和包核验在`output/ui-practical-20261114/`。旧时点completion与备份收据保留，最新主38号画面后的状态以audit-post-upload-*为准；post-conflict收据保留分支/父链证明。

主54917服务和IAB标签保留，副本服务/专项浏览器已关闭。直接继续现有主标签，最新demo-a的6项待人工可从“继续上次位置”回g_counter；其旧确认须按+3新证据复核。若主服务已退出，在项目根运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\output\ui-practical-20261114\launch-isolated.ps1
```

它通过正式ECRA.cmd启动隔离副本并打开新会话。核对数据根后，从历史选择6919db5f…或stress继续。隔离demo-a保留+3源码和原始备份；backup-ui后来新增了明确标注的测试分支事件，不应当作未修改的初始备份。启动日志/session.json含临时会话凭据，不对外分享。
