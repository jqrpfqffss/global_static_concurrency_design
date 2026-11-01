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

当前源码v6十四项浏览器流程通过，1366×768/1600×900任务主操作完整位于首屏；[任务截图](screenshots/v6/04-scan-published.png)、[变量证据](screenshots/v6/03-evidence-workbench.png)、[源码行](screenshots/v6/07-archived-source.png)、[清理结果](screenshots/v6/09-cleanup-recovered-and-purged.png)已随仓库保存。对应视频/trace位于output/playwright/studio-viewport-v6。

## 旧归档迁移与证据翻页续轮

共享页六项真实迁移场景：`evidence/browser-legacy-v3.json`；[归属计划](screenshots/legacy-v3/01-legacy-owner-and-plan.png)、[实际完成](screenshots/legacy-v3/02-legacy-real-conversion-complete.png)、[确认重开](screenshots/legacy-v3/03-legacy-confirmation-reopened.png)、[旧审计分段](screenshots/legacy-v3/04-legacy-opaque-audit-segments.png)、[损坏输入不覆盖](screenshots/legacy-v3/05-legacy-damaged-input-preserves-valid-result.png)。页面没有执行旧HTML/脚本/SQL，原复核文件可继续分段读取；缺完整facts.json或活WAL明确失败。

当前编译资产另跑十四项原生/复核故障/确认/调用/源码/清理流程通过：`evidence/browser-wire-v1.json`。20007行浏览器容量新增精确大整数/负零/JSON转义、407条前后页、长UTF-8前后段，并断言每页/段不累积；[实际证据截图](screenshots/legacy-v3/typed-evidence-bounded-pages.png)。当前占用带采样时间，可主动更新，迁移完成后刷新。Windows系统DPI、全部场景与独立工程师仍未验收；六项迁移不等于U21全部通过。

排序续轮：按交互合同增加服务器白名单排序，默认顺序保留；排序/筛选/分页位置与人工继续位置共同保存。20007行浏览器九项通过（browser-capacity-sort-v1.json），最大API17,192B；改变顺序、跨页、关闭页面后继续、独立SQLite位置断言均实际执行。十四项主流程再通过（browser-sort-v1.json），静态库不变。该后续不在封存v8中，不能拿v8源码匹配收据冒称包含排序功能。


覆盖诊断续轮：见[实施规格](07-coverage-contract.md)、[TU命令/零关联/源码](screenshots/coverage-v4/03-tu-filter-and-original-command-evidence.png)、[阻断返回重开](screenshots/coverage-v4/01-blocker-return-and-reopen.png)。8项F030真实浏览器操作、17项查询/API专项通过；首次可访问名称失败已修复，另一次失败为验证器相对定位器误用，均保留失败收据。系统DPI与独立工程师UAT仍未验收。
