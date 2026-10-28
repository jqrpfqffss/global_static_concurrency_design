# 人工确认功能开发与验收记录

开发分支：`optimize_cc`。由 Codex 直接执行，未委派 Claude Code/OpenCode 开发，未引用或合并其他分支实现。用户同时编辑的 `.gitignore` 保留原样。

## 1. 修改文件

| 文件 | 职责 |
|---|---|
| `ecra/manual_review.py`（新增） | 人工工作量、稳定身份、证据指纹、SQLite 当前状态和历史、事务、修订冲突、失效、导入导出及 WAL 一致备份 |
| `ecra/manual_server.py`（新增） | 标准库 loopback HTTP 服务、扫描/收据校验、API、安全检查及固定报告/原始证据文件服务 |
| `ecra/manual_ui.py`（新增） | 人工栏目、三个操作入口、依据与备注对话框、进度、继续确认、历史、导入导出及保存反馈 |
| `ecra/html_report.py` | 在原布局接入人工栏目；变量清单、风险列表和模型复核页共享人工状态；沿用搜索、分页、锚点和按需展开 |
| `ecra/cli.py` | 新增 `serve`、`--port`、`--no-browser`；扫描快照通过 SQLite 备份 API 备份人工账本 |
| `ecra/workflow.py` | 人工展示/服务模块不纳入静态分析引擎摘要；保留默认包含未来未知分析模块的原规则 |
| `build_portable.ps1` | 随包分发人工确认指南；原有所有 `.py` 复制规则自动包含新模块 |
| `scripts/validate_portable.py` | 内置 Python/SQLite 实测、服务模块导入、真实 HTTP 提交、重启恢复及新交付文件检查 |
| `tests/test_manual_review.py`（新增） | SQLite 事务、历史、冲突、导入导出、身份/进度、WAL 备份等测试 |
| `tests/test_manual_server.py`（新增） | 真正的 Clang 扫描/checkpoint、HTTP、源码/配置/模型结论变化、快照、失败扫描和分类隔离集成测试 |
| `scripts/prepare_manual_ui_fixture.py`（新增） | 创建全新 33 变量真实 Clang 浏览器夹具，已有目录拒绝覆盖 |
| `scripts/validate_manual_ui.js`（新增） | Playwright 浏览器自动断言，含跨分页继续、双页面冲突、XSS、恢复、打印及离线模式 |
| `docs/manual-review.md`（新增） | PowerShell / Portable 操作、数据模型、接口、备份与有效性规则 |
| `docs/portable-usage.txt`、`README.md` | 添加人工确认入口与指南链接 |

未改动 `decisions.py`、`review.py`、`review_integrity.py`、`report.py` 的原有分类或复核协议，也未修改 facts、queue、静态报告的数据格式。没有新增配置项或依赖。

## 2. 基于实际源码的架构检查

1. `extract.Extractor.fid()` 使用 Clang USR；内部链接加 `tu::<TU>::`。函数 static 使用 `local::<owner_function_id>::<name>::<ordinal>`，不以名称单独匹配。
2. 结构体成员由 `analysis.member_symbol_id()` 添加 `::member::<field_path>`；数组元素由 `storage` 添加 `::element::<index>`。容器继续保留原始证据但不重复计数。
3. finding ID 是 `GS-` 加对 symbol、规则、上下文集合摘要的前缀，不等价于存储身份；人工按 symbol 聚合多个 finding。
4. 静态分类、模型的 state/verdict 和 `decisions.effective_decision()` 的展示分类维持原语义；人工结论另存，不进入这些计算。
5. `report.generate()`、运行/复核进度检查点调用 `write_html()`；HTML 最终采用临时文件替换。人工数据不嵌入为可离线写入的记录，也不被 HTML 重建覆盖。
6. `run` 保存事实、输入清单、scan_state 和队列；`saved_run` 为 `review`、`review-failed`、`report` 共用恢复入口，先 `checked_scan()` 后校验模型收据。服务复用这些校验，不触发扫描或复核。
7. 原快照按固定文件/目录白名单复制。本实现将人工账本保持在白名单外，并在快照中另用 SQLite 在线备份生成一致副本。
8. `checked_scan()` 校验工程根、分析配置、引擎、facts/manifest SHA、清理后的报告摘要和当前全部输入。模型 DONE 记录还须通过 `checked_reviews()`/`verify_receipt()` 校验。
9. 原前端按栏目使用 rows/views、搜索索引、page-size 和 `reveal()` 进行跨页锚点定位。人工栏目沿用这些机制；待确认优先排序后同步 view.rows，不改变变量身份。
10. 输入失效、缺失检查点、扫描期间源码改变或不完整解析均不能继续提交人工确认；复核收据失效会影响人工指纹。运行锁只临时暂停有效性，实际证据变化才永久追加失效事件。

## 3. 数据模型、页面与持久化

项目 ID 是规范化工程根目录的摘要；变量 ID 是版本化 symbol_id 摘要；analysis_scope_id 是分析配置摘要。模型可扩展将来其他扫描范围，不引入本次不要求的差异扫描。

账本在工程输出目录 `manual_review/manual_review.sqlite3`。`current_review` 的复合主键为项目与变量，payload 包含名称、文件/位置、范围、证据摘要、decision、依据、确认人、时间及 revision。`history` 独立记录每次前后状态/证据、原因、确认人、时间、修订号和事件类型。更新使用 `BEGIN IMMEDIATE`，当前状态与历史同事务提交，陈旧修订拒绝覆盖。导入追加 IMPORT 事件并保存原始历史来源，不替换本地历史；恢复原确认时间。

页面提供“确认有风险”“确认无风险”“撤销确认”；已确认项可通过相同入口修改，必须提供原因。无风险依据为空时前后端均拒绝。所有状态、进度只在成功响应后更新；保存中、冲突、失败均明确反馈。模型分歧单独提示。继续确认每次寻找当前未完成变量，能跨页定位；不记录行数或“做到第几行”。

WAL + FULL 同步、事务、独立目录和在线备份共同保护关闭页面、工具重启、facts 重建、报告重建和扫描异常期间的数据。导出来自同一 SQLite 读事务，保留当前及范围外历史。SQLite 不是浏览器缓存。

## 4. 旧结论有效性

证据指纹覆盖对象、访问/RMW、保护、别名、相关调用分量、上下文/抢占、未知事实、编译输入与宏、配置、引擎和经验证的模型答案。全局集合及非语义位置/缓存信息规范化；调用路径和编译参数的有意义顺序保留。

对同一调用分量复用源码与图摘要，避免为成千变量重复遍历。已验证的无关函数实现变化可继承；边界不明确的函数、头文件、全局未知、构建输入等采用保守策略。新源码在确认前重新校验；人工写入与扫描共用运行锁，避免证据替换期间写入。

失效会追加 INVALIDATE 事件并显示 NEEDS_RECHECK，不销毁旧依据，不自动恢复旧结论。删除/移出范围的变量不计当前工作量，仍保留账本历史。

## 5. 操作

完整中文步骤与 Windows 命令见 [人工确认操作指南](manual-review.md)。正常顺序为 `run` → `serve` → 分批确认 → 下次 `serve` → “继续确认”；需要刷新展示时使用 `report`，历史在页面查询或导出。

## 6. 验证结果

本机日期：2026-10-28；Windows 主机，Python 3.10，Portable 内置 Python 3.10.9。

| 验证 | 指令/证据 | 结果 |
|---|---|---|
| 完整自动回归 | `py -3.10 -m pytest tests -q --tb=short`；`output/manual_final_tests.log` | 766 passed，2 skipped，247 subtests passed；222.48 秒 |
| 新增人工账本/服务集成 | `py -3.10 -m pytest tests/test_manual_review.py tests/test_manual_server.py -q` | 25 passed，11 subtests passed |
| 浏览器自动流程 | `npx --yes --package @playwright/cli playwright-cli run-code --filename scripts/validate_manual_ui.js`；`output/manual_browser_final.log` | 全部断言通过，无页面脚本异常 |
| Portable 实际组装 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1 -OutputDir .\output\manual-portable-20261028 -SkipZip` | 内置工具链、真实 ARM ELF 构建、扫描及标准命令通过 |
| Portable 人工服务 | 包内 `validate_portable.py`；`portable-evidence/*/acceptance.json` | HTTP 提交、WAL 持久化、停止/重建服务恢复通过 |
| 2000 变量组件基准 | `output/manual_scale.json` | 证据目录 0.164 秒；SQLite 状态加载 0.058 秒；人工 HTML 0.298 秒、约 2.30 MB |
| 语法/空白 | `py_compile`、`git diff --check` | 通过 |

最终重点回归为 **76 passed、36 subtests passed**，见 `output/manual_focused_final.log`。最终包复验 `output/manual-portable-20261028/portable-evidence/final-release/acceptance.json` 的结果为 **PASS**，其人工服务测试使用最后的人工模块与文件分发版本。

浏览器覆盖 33 变量/两页：依据必填、确认与撤销、统计即时更新、刷新恢复、搜索和状态筛选、跨页继续、双页面陈旧修订拒绝、全部历史、恶意 HTML 备注、导出、模型页状态一致、仅更新当前变量 DOM 标记、打印及 `file://` 禁用写入。截图 `output/playwright/manual-review.png`；打印文件 `output/playwright/manual-review-print.pdf`。

集成流程使用真正 Clang、报告、scan_state、输入摘要、模型复核队列/收据和真实 HTTP/SQLite；仅模型进程返回值使用明确的 synthetic-cli 模拟。覆盖扫描→模型复核→报告→人工确认→服务/页面重开→继续→report/review/review-failed→相同扫描继承→改源码重新扫描→需重新确认。没有跳过事实、源码、收据或分类校验。

两个 opt-in live OpenCode 测试未启用；未调用真实模型提供商，不能将模拟复核称为真实 LLM 验收。本次 Portable 使用 `-SkipZip`，组装目录与内置运行时验收通过，未新生成 ZIP。2000 变量数字为组件基准，不代表大型 STM32 工程的全量扫描或浏览器性能；未新增真实大型固件工程的完整人工端到端验收。

## 7. 浏览器测试复现

fixture 目录需全新；脚本遇到已有目录会停止，保护之前的确认数据。浏览器脚本默认使用 `output/manual-browser-fixture` 和 8876 端口，重复验收前先归档旧测试目录。

```powershell
py -3.10 .\scripts\prepare_manual_ui_fixture.py
$fixture = (Resolve-Path .\output\manual-browser-fixture).Path
py -3.10 .\run_ecra.py serve --project $fixture --config "$fixture\semantics.yaml" --port 8876 --no-browser
# 另一个 PowerShell 窗口执行：
npx --yes --package @playwright/cli playwright-cli open http://127.0.0.1:8876/index.html
npx --yes --package @playwright/cli playwright-cli run-code --filename scripts/validate_manual_ui.js
```

## 8. 兼容性与限制

原有静态分类、模型复核/完整性、report 恢复、按需详情、搜索/分页/锚点/打印和 Portable 回归保持通过。服务只监听 IPv4 loopback，严格 Host/Origin/token/Fetch Metadata 检查，固定报告与按 finding 约束的原始证据文件列表，拒绝路径越界。数据库异常返回失败，不能显示伪成功。

保守证据影响范围、目录迁移身份策略、8 MiB 导入限制见操作指南。持久化记录由下次有效人工状态查询进行证据继承/失效同步，离线页面不尝试维护可写审计状态。升级后旧扫描的引擎指纹变化时需要一次 run；serve 不自动运行扫描。
