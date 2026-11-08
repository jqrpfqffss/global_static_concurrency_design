# 显式兼容 HTML 的实际离线验收

本页是74c0冻结版本的历史实测，不作为后来修复后的file视觉通过；后续工具访问受阻与最新结论见[当前 V9 验收](continuation-final-v9.md)。

2026-11-08 在当前 Windows、Python 3.10.11 和最终静态引擎 `74c0b1c0f3fa204088534ad90f5bcefaf4bccb5a00ce42bce4cfb878eea509b2` 上验证。未修改生产代码、未调用 OpenCode、未写入真实人工确认数据。

## 实际生成与范围

从 `H:/ECRA-quality-20261108-delivery/final-engine-v3/f030.json` 派生隔离配置，保留真实 F030 工程与编译数据库，仅将输出改为 `H:/ECRA-quality-20261108/legacy-data`。`auto_system_includes:true`，模型与证据包关闭。CLI 帮助确认 `--legacy-output` 当前仍为“显式兼容验证入口”。

```powershell
py -3.10 run_ecra.py --config H:/global_static_concurrency_design/output/quality-20261108/legacy/config.json --legacy-output --no-review
```

实际复用现有获准编译数据库解析 4 个 TU，盘点 15 行 / 13 个分类对象，生成 6 项复核候选。退出码 2 / `INCOMPLETE`，未将两个部分解析 TU 当作完整覆盖。页面显示 1 项疑似、5 项无法判断、7 项静态安全，另有两个容器汇总；模型有效回答 0/6。此运行没有重新配置或链接固件，不能宣称固件重新构建已通过。

产物为 `H:/ECRA-quality-20261108/legacy-data/projects/firmware_1b46a7e5456fa22bd9bf/results/index.html` 及同目录 `opencode_review.html`、`classification_quality.html`、机器事实和状态。

## 实际浏览器操作

使用独立的有界面 Chrome / Playwright CLI 会话 `ecra-quality-legacy`，真实通过 `file:///H:/.../results/index.html` 打开，未用临时 HTTP 服务替代。

Playwright 默认阻止 `file://` 导航；其已安装官方 README 提供 `allowUnrestrictedFileAccess` 会话选项。本次仅在隔离的 `playwright-local-file.json` 配置它以访问指定报告，不改变 ECRA、浏览器系统配置或用户数据。测试使用固定隔离用户目录 `H:/ECRA-quality-20261108/legacy-browser`，关闭再重开仍用同一目录；未注入浏览器状态。

| 场景 | 实际结果 | 状态 |
|---|---|---|
| file:// 初次打开 | 无服务即可打开，项目、时间、输出目录与当前分类可读 | 已通过 |
| 搜索/空结果 | 搜索 `systicks` 得 1 行；`t_ms` 得 0 行并给出调整筛选提示 | 已通过 |
| 变量和证据定位 | 点击 systicks 定位变量；展开 3 处访问、main / SysTick 上下文与调用链入口 | 已通过 |
| 离线复核页 | 本地相对链接打开，搜索 systicks 得 1 项，明确“模型未启用”“不能当作安全” | 已通过 |
| 1366×768 和 1920×1080 视口 | 均取得真实视口截图并实际查看；所验内容无文字重叠或整页横向溢出 | 已通过，仅这些视口 |
| 关闭/再次打开 | 同一持久浏览器目录重新打开，报告与分类仍可读；筛选恢复默认 | 已通过离线阅读，未承诺保留筛选 |
| HTML 内签署及持久化人工结论 | 当前页面没有确认/备注保存控件，只有搜索输入；现有合同明确此接口不存在 | 不适用，不计作人工确认通过 |
| 浏览器页面缩放 / Windows 显示缩放 | 未改变实际缩放设置 | 尚未验证 |

当前 [工作区迁移说明](../workspace-migration.md)第87行明确：“当前分支没有独立的 HTML 人工确认持久化接口”。实际界面、只读源码检查与此一致：HTML 支持浏览、搜索、打印/保存当前筛选结果和排查模板；“打印 / 保存”不是签署人工结论。需要连续人工确认、保存和继续处理时，应从 `ECRA.cmd` 启动 Studio，采用其独立事件存储，不能把旧 HTML 当作该工作台的替代。

深层证据阅读需沿长页滚动；本次没有将当前兼容页面改造成另一套确认架构，也没有以手工注入 localStorage 或数据库证明不存在的恢复功能。

## 证据

- 运行配置、完整日志、退出码、最终 `status --json`、引擎与文件 hash：[原始证据目录](../../output/quality-20261108/legacy/)。结构化结论见 [acceptance.json](../../output/quality-20261108/legacy/acceptance.json)。
- 已实际查看的视口截图：[首次打开 1366](../../output/playwright/quality-20261108/legacy/01-index-1366.png)、[源码与调用链 1366](../../output/playwright/quality-20261108/legacy/04-callchain-open-1366.png)、[源码与调用链 1920](../../output/playwright/quality-20261108/legacy/05-callchain-open-1920.png)、[复核搜索 1920](../../output/playwright/quality-20261108/legacy/07-review-search-1920.png)、[同一目录重开 1366](../../output/playwright/quality-20261108/legacy/08-reopen-file-1366.png)。
- Playwright 控制台观察到错误 0；会话结束后已关闭，未留下测试浏览器。

本项通过只证明当前显式兼容 HTML 的所验离线阅读流程；不能等同于 Studio 人工确认、当前固件重新构建、全部工程覆盖或硬件运行验证。
