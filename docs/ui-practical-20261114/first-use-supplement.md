# 首次空库入口与手填配置补充实操

日期：2026-11-14。沿用本轮 runtime、工程和样例包，仅为已在主数据中消失的空库状态建立独立 fixture；没有再次复制程序或固件，没有改主服务。下表是供主功能清单合并的补充操作证据，不将截图/点击次数计为功能数。

## 环境与边界

- 正式入口：`output/ui-practical-20261114/launch-first-use.ps1` 调用现有 runtime 的 `ECRA.cmd --data-root H:/ECRA-ui-practical-20261114/first-use-data --port 0 --no-browser --session-file .../first-use-session.json`。继承主启动脚本的 CMake/Ninja/ARM GCC PATH。独立 LOCALAPPDATA=`H:/ECRA-ui-practical-20261114/first-use-private-localappdata`。
- 本次监听 `127.0.0.1:58776`；首次启动前确认数据根不存在，初始页面未选择结果且无扫描历史。主服务及其数据根未更改。
- Windows 10 专业版 10.0.19044；Chrome 156.0.8078.79；headed、persistent Playwright，独立 `first-use-browser` 用户目录；1366×768 CSS 视口、device_scale_factor=1。没有调整 OS 显示缩放或浏览器缩放，不把上述视口验证计作缩放验证。
- 本代理 Computer Use 浏览器 inventory 为空，实际 `createBrowserTab('iab', ...)` 返回 `Browser is not available: iab`。按用户明确允许的 fallback，复用项目 Python Playwright 驱动，使用 `py -3.10`（系统默认 `python` 环境未安装 Playwright）。每步取得真实 accessibility snapshot 与当前视口截图，并实际查看关键截图。
- 实际前端脚本：`./assets/index-Dz_fcmH4.js`，所有操作记录均含该标识。UI 写操作没有通过 DOM 注入、localStorage、数据库或内部 API 替代。

## 操作记录

证据目录均为 `output/playwright/ui-practical-20261114/`，同前缀 `.png` 为当前视口截图，`.txt` 为对应可访问树。连续机器记录是 `firstuse-operations.jsonl`。

|编号|页面/入口与目的|适用条件、预期及依据|实际操作及结果|状态|证据|
|---|---|---|---|---|---|
|FU01|正式启动/空库首页：新用户找到开始方式|独立空数据根；正式启动应成功，并显示新建、导入、示例入口|通过现有 ECRA.cmd 启动，出现“开始使用 ECRA Studio”和三个清晰入口|已通过|firstuse-01-initial、02-initial；logs/first-use-launch.log|
|FU02|空库首页“导入历史结果”：进入导入页面|未选择结果，按钮应进入“数据与共享”完整包导入|真实点击后进入结果交接页，显示选择 `.ecra-report` 控件|已通过|firstuse-03-empty-import-entry|
|FU03|导入已有样例包并打开：离线查看已有结果|已有合法 sample-compact.ecra-report；成功必须有归档和可打开入口|选择真实文件，经历上传/校验，显示完整性100%、新增事件0；点击“打开导入归档”进入 builtin-stm32-demo-v1 概览，16对象、6待确认；核对 scan.db 与包中 scan.db 字节完全相同|已通过|firstuse-04/05、09/10/11；first-use-data-proof.json|
|FU04|“打开示例”：进入教学数据|样例包已在本次根内导入，尚未选中结果；应打开真实示例且明确教学范围|回到未选结果的概览，真实点击“打开示例”；进入 ECRA-DEMO-S4，显示非用户工程/未链接固件/无硬件验证提示。此处验证的是已有教学归档分支，不冒充未安装样例时的首次复制分支|已通过|firstuse-06/07/08|
|FU05|手填工程第1步：输入名称并选择正确根|首次手填，名称/路径应进入待保存配置；目录选择仅登记路径|进入工程配置空表单，输入“首次手填 demo-b”；目录树输入 demo-b 根并打开，点击“使用此目录”，进入第2步|已通过|firstuse-12至19|
|FU06|第2步真实构建字段：输入/切换模式|本轮保存使用 CMake；切换数据库应呈现数据库字段，不能把数据库路径当成CMake目标|输入 Cortex-M7、demo、Release；切换database出现编译数据库路径；再切CMake时目标清空，重新填写demo，工具链与Release保留。最终保存CMake配置|已通过|firstuse-20/21/22、29、39/40、55|
|FU07|Toolchain选择：取消与确认|固件根存在 arm-toolchain.cmake；取消不能写路径，确认应填真实文件|打开选择器后取消，字段仍空；再次打开可见 `.cmake` 文件，选中并“使用此文件”，字段为 demo-b/arm-toolchain.cmake|已通过|firstuse-23至28；26为已查看截图|
|FU08|编译数据库选择：取消与确认|已有本轮 demo-b 的真实 compile_commands.json；取消不改字段，确认填文件路径|切数据库模式并取消首次选择，路径仍空；再次打开到本轮已有外置构建目录，选中compile_commands.json并确认，输入框显示完整路径。仅只读选择，随后切回CMake且该数据库路径未进入保存结果|已通过|firstuse-30至38；35为已查看截图|
|FU09|检查/保存/刷新重开：确认手填数据持久化|完整输入应通过检查并保存；保存后刷新再打开仍对应同工程与字段|检查显示工具可用3/3；点击保存，生成profile 52b7a4123c704758b86d53b9a32293da；刷新使编辑表单回到空白，从已保存列表重新打开，展开YAML并返回步骤3/2；名称、根、Cortex-M7、demo、Release、toolchain、纳入目录`.`均正确。UI重新读取的YAML与磁盘profile文本完全一致|已通过|firstuse-41至55，重点46/48/49/51/55；first-use-reopened.yaml；first-use-data-proof.json|

FU01–FU09 完成时没有发现新的产品问题，没有修改产品代码。当时没有启动新的扫描；新数据根仅一个教学归档，任务目录为空。该时点仅验证手填配置保存与重读。随后应父任务要求已实际启动该配置扫描，见 [recovery-startup-supplement.md](recovery-startup-supplement.md) RS02；不要把本段旧时点视为最终数据状态。

## 数据核对与收尾

`output/ui-practical-20261114/first-use-data-proof.json` 记录：

- 重新打开的 UI YAML 与磁盘 profile 完全一致，SHA-256 `00123f2a524d15c420704acf73c8b88289256e3754956e8b6d22e2dce540c3be`。
- 教学 `scan.db` 与上传包内 `scan.db` 字节一致，SHA-256 `261ff9b60b1ce40f233704520d93e280804d07ee1bc119cb5430bd9b67bae12e`。
- 数据库核对仅只读；没有写入任何人工确认事件。

浏览器通过驱动正常 `context.close()` 退出；核对专用启动进程树后结束本次服务，58776已无监听、无本次 Chrome/profile 或 Python/server 进程，详见 `first-use-shutdown.json`。测试数据与浏览器持久化目录保留，便于重现。需要继续时运行 `launch-first-use.ps1`，读取新的 `first-use-session.json` 中 URL，在工程配置的“已保存配置”打开“首次手填 demo-b”。主实操环境仍用原 `launch-isolated.ps1`。
