# UX审核与证据登记

冻结布局见02、交互见04、状态见05。全部页面必须记录真实目标、默认动作、入口/返回、状态/错误、键盘/屏幕、测试、截图与待人工项。已有早期及续轮真实Chrome截图；完整页状态仍需逐项验收，不把旧概念图或少量流程当成全部实现。

| 页面 | 目标/主动作 | 入口与返回 | 验证/截图状态 |
|---|---|---|---|
| 概览 | 找到下一件事/状态动作 | 启动↔九导航 | NOT_VERIFIED |
| 工程 | 完成四步接入/下一步 | 概览↔向导 | NOT_VERIFIED |
| 扫描 | 了解真实阶段/状态动作 | 概览↔任务 | NOT_VERIFIED |
| 变量 | 查清对象风险/打开证据 | 卡片/诊断↔列表 | NOT_VERIFIED |
| 覆盖 | 修复输入缺口/下钻 | 概览↔对象 | NOT_VERIFIED |
| AI | 可选完整复核/状态动作 | 导航↔对象 | NOT_VERIFIED |
| 人工 | 继续确认/保存 | 概览/对象↔列表 | NOT_VERIFIED |
| 历史 | 打开正确版本/打开 | 导航↔结果 | NOT_VERIFIED |
| 共享 | 安全传递/校验导入 | 启动/历史↔结果 | NOT_VERIFIED |

所有页的LOADING/EMPTY/VALID/STALE/PARTIAL/FAILED/OFFLINE_ARCHIVE/PERMISSION_ERROR须逐个验证。截图组合：1366×768、1600×900、1920×1080 × 100/125/150/200%。关键主动作与搜索无需水平滚动；详情完整中文、长路径、调用边继续加载；Ctrl+F/Esc/Tab与焦点回归。浏览器CSS缩放不能冒充Windows系统DPI测试。

需用户组织5–8名独立嵌入式工程师盲操作U01/U02/U06/U11/U16/U19，记录成功率/失败/点击/反馈。当前NOT_VERIFIED。自动浏览器通过不代表真实用户满意度，静态推断不代表板上复现。

## 本轮实际截图与操作证据

早期可运行布局见 `output/playwright/studio-20261031-attempt3/`，实际发现人工操作位于长页末尾，未接受为最终布局。ADR-006把证据区改为独立滚动与分组，人工操作保持可见。

包内Python3.10.9最终真实Chrome记录：[`acceptance.json`](../../../output/playwright/studio-portable-20261031-verified/acceptance.json)。含9项实际操作测试、SQLite断言、无外部资产请求、无pageerror；不替代全部U01–U24。

| 页面 | 截图 | 验证范围 |
|---|---|---|
| 概览 | [首页](../../../output/playwright/studio-portable-20261031-verified/01-overview.png) | 真实黄金统计、UNKNOWN卡下钻；没有全工程安全横幅 |
| 工程 | [向导](../../../output/playwright/studio-portable-20261031-verified/02-project-wizard.png) | 前后保留输入、真实profile提交；未做真实构建/启动 |
| 变量 | [证据工作台](../../../output/playwright/studio-portable-20261031-verified/03-evidence-workbench.png) | 规范身份、访问摘要、分页原始证据、固定人工操作；完整图形导航未齐 |
| 扫描 | [真实阻断状态](../../../output/playwright/studio-portable-20261031-verified/04-scan-task-gate.png) | 明确迁移未完成，无模拟进度/假启动 |
| 人工 | [确认历史](../../../output/playwright/studio-portable-20261031-verified/05-human-history.png) | 保存/重开/继续/撤销；原事件与理由保留 |
| 共享 | [导入校验](../../../output/playwright/studio-portable-20261031-verified/06-import-validated.png) | 文件选择真实上传、完整校验、数据库发布；恶意包失败不污染 |
| 源码 | [归档代码](../../../output/playwright/studio-portable-20261031-verified/07-archived-source.png) | 从归档节点读取代码，不调用任意本机文件读取 |

1366×768、1600×900、1920×1080截图同目录。浏览器截图不等于Windows系统DPI通过。技术证据详情仍存在通用字段导航，完整专业调用图、所有筛选/错误/权限/损坏状态需要继续实现，不能在最终汇报称H5通过。

## 续轮：真实任务与专业证据闭环

最新包内流程参考 `output/playwright/studio-portable-canonical-v5/acceptance.json`：14项真实Chrome流程通过，含原生扫描/停止/恢复和缺工具复核故障。当前图/代码/过滤/分栏/资源/清理均为真实API，不是概念页面。v6另断言1366×768和1600×900下任务主操作完整落在首屏，并以新截图复查；系统DPI仍NOT_VERIFIED。

20007行容量夹具真实浏览器最大API响应16,656B；清理引用与50GiB实盘有独立收据。目录图和合成容量不代替g_mfcInterface.msgSp真场景、目标板或三类大工程。所有页全部状态与独立工程师盲测继续未通过。
