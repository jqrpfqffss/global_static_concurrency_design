# AI 不可用及恢复入口实操

环境与证据根同 package-review.md。独立持久 Chrome、1366×768；没有启动真实 OpenCode、Claude Code 或其他编码代理，没有用成功桩替代复核。

测试准备：从真实“高级完整 YAML”文本框只读备份 demo-a 当前配置到 `output/ui-practical-20261114/demo-a-yaml-before-missing-tool.yaml`。在 UI 输入完整文本，唯一新增 `review.command: [H:/ECRA-ui-practical-20261114/missing-opencode.exe]`，`enabled: false` 保持。实际确认该 exe 不存在。命令只在隔离 profile 保存，未修改固件源码或正式配置。错误输入阶段曾使用 scalar，校验正确拒绝并暴露 I10。

|编号|入口/目标|适用条件/预期依据|实际操作与结果|状态|证据|
|---|---|---|---|---|---|
|AUX-AI01|工程配置的复核命令校验/保存|命令应是参数数组；禁用自动复核不应阻止静态配置保存|scalar正确报“review.command 必须是非空参数数组，不能是 shell 命令字符串”，保存禁用；改数组后检查/保存成功。只读回读确为缺失路径且enabled false|校验已通过；错误可见性I10已修复并通过|package-45～52、88～93|
|AUX-AI02|复核配置说明与发起全部|本机41986655…归档、原输入可核对；UI说明工具不可用记录技术失败|展开配置选择确认demo-a→复核全部疑似与未知；任务0cde4ec3392a4280aee207f21824f34c核对输入后处理6/6，成功0/技术失败6，归档INCOMPLETE|已通过（失败路径）|package-57～60；tasks-after-ai-unavailable.json|
|AUX-AI03|技术失败详情与原始收据|失败不能显示安全；应能找出失败阶段/原因|AI表6项均技术失败/尝试1；g_counter详情明确launch找不到命令、没有当前有效结论；展开身份/收据，打开stderr原件，77字节中文原因与缺失路径一致；关闭原件|已通过|package-62～67；实际查看63、66截图|
|AUX-AI04|仅重试技术失败|已存在6技术失败且缺失工具尚未修复；应重试并保留失败历史|点击仅重试技术失败→任务0315191be41a421c8470285613c4dfad，仍6技术失败/成功0；回AI页每项尝试数2，无伪成功|已通过（重试失败路径）|package-68～71；tasks-after-ai-retry.json|
|AUX-AI05|恢复原配置与保留已有结论|原YAML已备份；不能遗留故障注入|通过UI填回备份→检查→保存，实际profile与备份字节完全相同SHA256 `8aa03fee48e414566630872faf3e1c1fd8e018ad29f7b92e4a03a98de77629b5`；review仅enabled false|已通过|package-72～78、91～93；ai-profile-restoration.json|
|AUX-AI06|失败/重试不覆盖静态和人工|独立来源按产品约定保留|前后4198的静态分类/完整binding/新人工事件/3历史引用均相同，待办4；旧dc5也逐项保持。只有4198的AI快照1→16、AI事件6→30（两次失败）增加|已通过（辅助只读核对）|ai-failure-preservation.json；audit-after-ai-retry.json|
|AUX-AI07|真实模型成功及失败后成功恢复|当前会话明确禁用外部编码代理|未调用真实模型；恢复原配置后不发起真实复核，不能声称模型成功/成功恢复|受阻未验证|会话约束；原配置已恢复|

I10 初始问题：工程配置第4步展开长YAML，编辑末尾后点击“检查配置与工具路径”。全局错误存在于 main 开头，但 main 当前已滚动到第4步，错误在视口上方；package-48 的DOM有错误，而实际截图没有错误可见，只有保存禁用。问题是反馈位置，不是 schema 拒绝。

修复由主代理/fix_filters完成：App.vue 提交失败后等渲染，将全局alert滚入可见区并聚焦；后台读取不抢焦点，弹窗用自身错误区，未放宽校验。新版本 `index-Dz_fcmH4.js` 实际从浏览器 script DOM核对（package-81起日志含scripts）。沿原错误完整重做，package-90当前视口顶部可见完整红色错误，保存仍禁用；随后原YAML再次UI恢复、实际文件字节相同。package-90截图已实际查看。

完整步骤、每步当前视口PNG和ARIA快照：`output/playwright/ui-practical-20261114/package-38～93-*`。实际查看关键截图48（修复前不可见）、60（真实任务阶段）、63（技术失败详情）、66（stderr原件）、90（修复后可见）。任务状态“已结束”仅表示处理结束，日志和AI列表明确6技术失败，不将任务完成误记为AI成功。
