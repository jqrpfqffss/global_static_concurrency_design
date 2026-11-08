# 后续原生缩放检查：尚未验证

本次独立检查从解压候选 `H:/ECRA-quality-20261108-delivery/解压 终验/ECRA-Portable/ECRA.cmd` 实际启动，当前目录为 `H:/`，子进程 PATH 仅 Windows 系统目录；新数据根为 `H:/ECRA-quality-20261108/continuation-ui-data`。Playwright 使用独立 Chrome headed 持久会话 `ecra-quality-continuation-ui`，仅完成1366×768空库首页观察。

准备进行真实浏览器100%/约125%页面缩放时，Windows Computer Use 的 `sky.get_window_state` 自动停止，返回：无法足够可靠地确定当前 Windows 浏览器 URL 以执行策略，并要求停止本轮 Computer Use。没有继续原生输入、重试同一受阻动作或通过其他窗口工具绕过。

因此以下项目保持 **NOT_VERIFIED**：真实页面100%/125%缩放、原生系统DPI、在该缩放条件下的长证据/人工填写/错误状态，以及本次真实F411/CDC报告的浏览器导入和跨项目使用。没有把 `resize 1366 768`、CSS缩放或静态检查冒充真实浏览器缩放。

主代理随后明确发出独立的非UI任务，要求只清理本次会话并转为CLI。已通过该Playwright会话的关闭命令关闭测试浏览器；按进程命令行核对 `continuation-ui-session.json` 所属后停止本次Studio服务。收据在 `output/quality-20261108/continuation/ui/closed.json`。未输入Windows GUI、未关闭其他测试服务或窗口。

为原计划准备的两份完整报告包仍可作为后续明确授权的验收资产：

- `H:/ECRA-quality-20261108/continuation-real-reports/f411.ecra-report`，26,697,672字节，SHA256 `ae19a66cdea71f4a2e3bce9cdcc478f7183762b33573fd3d0d8b4d7ed3f8f84d`。
- `H:/ECRA-quality-20261108/continuation-real-reports/cdc.ecra-report`，110,319,665字节，SHA256 `17fbc852a51e3660b1f79c9f6bdbaf9410a872f15143c3377bfb17e3c692ecf1`。

报告导出使用原扫描的完整独立副本，通过正式 `export_report(..., compression='deflate')` 生成；原scan.db、reviews.db、manifest.json前后SHA相同，记录见 `output/quality-20261108/continuation/ui/real-report-packages.json`。没有在原真实扫描写入人工确认，也未将这些“已生成包”表述为“浏览器导入验收通过”。
