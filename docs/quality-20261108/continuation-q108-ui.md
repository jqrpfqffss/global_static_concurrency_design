# 损坏报告后的界面恢复（Q108）

本项是独立的结果加载失败回归，不恢复被自动停止的原生页面缩放检查。只使用已配置的 Playwright CLI/Chrome；没有模拟页面缩放或操作系统显示缩放。

## 实际复现

复制已有受控故障目录到 `H:/ECRA-quality-20261108/continuation-q108-data`，不修改原故障现场、客户数据或历史签署。坏扫描 `53ddbc84962f42faa02f80456f7904f8` 的 manifest 原样为 `[]`，旁边保留有效教学归档。该坏扫描在目录排序首位。

服务：独立 `continuation-ui-candidate`，包含已冻结的 Q105/Q106 服务修复，开始时使用主区旧前端 `index-C8CfT7jx.js`。启动 `py -3.10 -B -X utf8 -m ecra.studio --data-root <上述副本> --no-browser --session-file <独立凭据文件>`。浏览器持久目录 `continuation-q108-browser`、会话 `ecra-quality-q108`，真实视口 1366×768。

从全新浏览器打开正式 URL 后，清单错误已显示，但“查看全部变量”仍可点。进入清单选择 systicks，实际控制台出现 `Cannot read properties of null (reading 'result_revision')`，真实截图为整个应用空白。不是只根据源码或接口推断崩溃。

证据：`output/quality-20261108/continuation/q108-before-console.log`，截图 `output/playwright/quality-20261108/continuation/q108-before-overview.png`、`q108-before-detail.png`，均已实际查看。

## 修复与实际复验

候选 App.vue 以当前扫描绑定且已成功读取的 summary 作为变量读取、详情和签署的共同前提；失败时清除旧列表/详情及编辑依据，草稿仍由原 ReviewDrafts 保存。失败状态提供“重试读取”和“选择其他历史结果”，不再当作空库或零结果。ScanIdentity 显示“结果读取失败”。首次未选择结果时优先跳过目录中明确 FAILED 的项目，用户原来选中的坏结果保留并解释失败。降级旧归档继续走原只读分支。

`npm run build` 的类型检查和生产构建通过，最终脚本 `index-DoBeaJ3o.js`。主区因完整基线回归仍在运行，没有中途替换源码；前端与服务字节已复制到联合冻结候选。

真实操作：在原空白页面直接刷新 → 同一坏扫描显示明确失败状态 → 点击重试仍解释原错误且无空白 → 选择其他历史结果 → 历史中坏项显示失败、打开按钮禁用，有效教学项可打开 → 打开 g_counter 证据 → 填写明确标注仅教学验收的人工风险确认 → 页面保存成功、静态疑似独立保留、待办6变5 → 真正关闭整个测试浏览器 → 用同一持久目录与正式URL重开 → 仍人工风险1、待办5 → 点击继续，选中未确认 g_msgSP，已签署项排除。

没有 state-save/state-load、写入 localStorage 恢复或手工注入人工数据库。截图 `q108-after-failure.png`、`q108-after-saved.png`、`q108-after-reopened-continue.png` 均已实际查看；保存和重开快照 `q108-after-*.txt` 保留在运行证据目录。修后两次400对应首次读取和实际重试的预期故障，没有把它们称为零网络错误。

本项不代表真实联网AI通过。坏扫描中的AI条目来自受控故障数据；没有调用外部OpenCode。

## 真实报告相邻操作

通过产品“数据与共享”的文件选择器实际上传由原真实扫描导出的CDC 110,319,665字节与F411 26,697,672字节标准包，均由产品完整验证后导入，新人工事件0。没有直接复制扫描数据库到新根模拟导入。它们是原74引擎的历史报告，用于验证当前前端读取/导航，不冒充v2静态扫描结果。

CDC批次 `de8e72e7359840caa3b81a7ac884a4cd` 显示244项，50项分页；选择TimHandle.Instance读到24个访问，沿HAL_TIM_Base_Init→TIM_Config→CDC_Itf_Init→USBD_CDC_Init逐层展开真实调用，定位归档usbd_cdc_interface.c:47。1366×768与1920×1080视口截图已实际查看；项目/批次和当前对象可识别，独立证据滚动保留主要导航与填写入口。没有将改变视口称为浏览器页面缩放。截图 `q108-real-cdc-evidence-1366.png`、`q108-real-cdc-tree-1366.png`、`q108-real-cdc-tree-1920.png`、`q108-real-cdc-deep-tree-final.png`、`q108-real-cdc-source.png`。

历史列表同时显示一坏项、两真实项目和教学归档；坏项打开禁用，两个真实归档可选择，各自批次和总数独立。实际从CDC244项切到F411171项，再回教学归档，原人工风险1/待办5保持。数据复验 `q108-data-receipt.json` 确认两个导入静态库分别与标准包内scan.db字节一致，两个真实工程无测试人工风险签署；教学与坏扫描的原静态SHA不变，坏manifest字节不变，唯一新签署属于教学g_counter且确认者一致。

最终重开浏览器会话控制台0错误/0警告，与前一会话预期注入的两次400分开记录。已实际查看F411清单与返回教学的截图，关闭本次浏览器并核对命令行归属后停止本次服务；`q108-closed.json`记录，不关闭他人服务。
