# OpenCode 逐项复核后的 Studio 数据同步

本次在 Windows 上验证了 optimize_ccc 的工作副本，起点为 e0c64f2638a5a3de50ca90b3fe69507f34971182。测试使用独立数据目录。原有 Git 差异实现及其两份测试的本地修改已保留。

## 复现与修复

| 入口 | 旧版实际表现或代码依据 | 本次改动 |
|---|---|---|
| App.vue 的 refresh、invalidateResult、syncProjection | 有效批次的汇总短暂读取失败后，已显示的卡片消失。旧版继续轮询 10 秒，卡片仍未恢复。初始无 summary 时也可能一直跳过轮询。 | 区分临时失败、批次缺失和归档校验失败。临时失败保留最后成功数据并显示待同步，首次读取失败也可重试。切换批次清除上一批展示。 |
| App.vue 的 loadList、优先处理项和选中详情 | 汇总先应用新版本，后续列表或详情读取失败。版本探测已命中，新提交停止后，B 的行或详情仍显示静态疑似。 | 汇总、优先项、列表和详情分别记录成功应用的版本。列表另校验批次、筛选、排序、范围、分页和请求代次。过期返回和 finally 只影响自己的请求。末页消失时重新读取实际末页。 |
| ReviewCenter.vue 和 SymbolAI.vue | /ai 接受相同快照序号时可返回 unchanged，含义仅为 AI 归档未变化。旧版在选中 finding 离开列表、单独详情请求又失败后，持续显示技术失败。另一个入口的变量 AI 答复读取失败也缺少重试触发点。 | OpenCode 页分别记录已应用的查询和选中详情版本。新筛选完整读取，已对齐的同一查询才带条件版本。批次未变时可以独立补读详情。变量详情复用主页面刷新时钟。 |
| TaskCenter.vue | 任务目录查询和选中任务详情串行，前一项读取失败可阻断详情。当次任务处理数与全归档进度使用不同计数对象。 | 两类读取分别处理失败，切换任务后校验返回身份。任务结束时通知主页面。任务页同时标明本轮处理数、归档总进度和扫描阶段 TU 计数。 |
| server.py、query.py、current_results.py、scan_persistence.py、human_reviews.py | 在旧版 /summary 的全量与差异查询之间插入一次成功提交，单个 HTTP 响应出现全量 1:0:0、差异 2:0:0。单独查询列表行、人工记录或旧格式 AI 页也可能与所报水位分开读取。 | 全量和差异在同一只读事务内计算。列表行、完整命中数、人工状态及返回版本同读。/symbol、/human、/symbol-ai 提供各自读取版本。旧格式 AI 页使用实际数据所属快照的序号。相同插入点现在返回 1:0:0、1:0:0，下一读可见新提交。 |
| report_package.py、html_report.py、ScanDiff.vue、workflow.py | 导出包此前缺少便于复核的生成时刻及已封存结果版本。静态差异中的“当前疑似”容易与复核后风险混淆。只读代码变化也可能影响旧扫描的引擎指纹。 | 完整包从实际封存的数据库取版本并写入 UTC 生成时间，人工增量同事务读取并记录人工版本。旧 HTML 标出扫描时间和页面生成时刻。差异面板明确标出复核前的静态口径。已知的只读改动用精确内容摘要映射维持检查点兼容。 |

逐项提交仍走 commit_review_result，发布依据是 ai_events 和 ai_snapshots 的事务水位。保存于 snapshot 中的 report 允许沿用旧值。native_consumers 的风险汇总摘取项为扫描清单 total_variables。本次检查的 Studio 当前结果卡片、复核分组、待办和任务复核进度都从已发布结果读取。静态清单和覆盖证据继续从扫描归档读取。轮询没有启动工程扫描、重建 HTML 或加载整份 facts。

## 页面与指标清单

| 页面或控件 | 指标、对象及范围 | 数据来源与刷新依据 |
|---|---|---|
| 项目概览的当前风险、无法判断、安全、待确认 | 按 canonical 变量计数。普通批次取完整范围，差异批次取差异范围。风险合并 CONFIRMED 与 LIKELY。安全可来自静态证明或有效 AI 结论。 | /summary 返回静态分组、当前分组及同版本 diff_results。主页面约每 2 秒探测 /result-revision，重新打开、返回前台和相关页面切换会触发读取。 |
| 概览的优先处理项及各卡片下钻 | 优先项最多五个。点击卡片后，列表页脚为相同范围及筛选的完整命中数。 | /symbols 使用相应 review_scope、current_result 和 diff。优先项、分页列表独立对齐到汇总版本。 |
| 变量与风险的筛选、行、页脚和选中详情 | 静态筛选按原始分类，当前筛选按有效结论。范围及证据侧参与查询，基准侧独立识别；结构体字段和容器沿用扫描清单规则。工作区每页最多 50 行。 | /symbols 的 total 与 items 属于同一读版本。/symbol 返回当前结论来源、原始静态状态及人工状态。变量 AI 分页使用 /symbol-ai。翻页、搜索、排序、切批次及有未补齐区域时重新读取。 |
| OpenCode 的总量、进度、分组、按钮、列表与详情 | 按冻结集合中有效 finding_id 计数。包含安全抽样及无 symbol_id 的独立缺口。分组和进度覆盖全部目标；搜索和分组下钻仅改变匹配总数。历史尝试另计。 | /ai 的整数 revision 是 AI 快照序号。约每 1.5 秒轮询。总量等于完成、技术失败、其余对象之和；DONE + NEED_MORE_CONTEXT 计入完成及无法判断组。配置、本机可复核状态、待处理量与失败量约束相应按钮。 |
| 人工确认的待办、已确认、处理状态和草稿 | 按变量计数。待办结合当前风险与已有人工状态。已确认或冲突筛选可查队列外的人工记录。对象退出队列后保留打开的详情，显示更新后的人工状态，并按剩余队列限制上下项导航。 | /summary、/symbols、/human、/symbol 使用复合结果版本。用户输入的草稿绑定原证据指纹和原人工 heads。外部签字后重试旧草稿时，服务端可识别冲突。 |
| 扫描任务的任务状态、处理数、进度和完成摘要 | 任务生命周期、扫描 TU、本轮选择的复核对象、整个冻结集合分别计数。任务正常结束时仍可能存在技术失败。 | /tasks 及 /tasks/{id} 约每秒刷新。任务阶段记录给出本轮实际处理数，归档给出同批次的最新复核对象进度。恢复窗口或任务结束会触发刷新。 |
| Git 差异 | 差异变量范围的当前结论用于概览和下钻。基准侧、当前侧静态分类，静态风险变化、影响分类、变更文件和缺口均属于冻结的双版本扫描。 | 当前列来自 diff_results 和 diff=changes 的 /symbols。静态列来自 diff_summary、/diff-changes 和对象证据，按扫描身份、筛选和分页读取。 |
| 历史与对比、覆盖与诊断 | 历史列表计归档数；对比按双侧静态分类、对象指纹。覆盖项、TU 和阻断证据属于扫描时的事实。打开相关变量后显示当前动态结论。 | /history、/history/compare、/coverage 及各分页接口。静态统计依赖所选归档，历史日期来自归档。 |
| 完整导出、人工增量、旧 HTML | 已写出的文件是生成时快照。完整包可离线重开并继续新增人工记录。人工增量仅含人工历史和沿用来源。 | 完整包 manifest 的 generated_at、result_revision；人工增量的 generated_at、human_revision；旧 HTML 页首的扫描与生成时间。 |

Studio 的 result_revision 由已发布 AI 水位、人工事件数及沿用记录数组成。只将相同字段作相等性比较。跨窗口在成功读取新版本前可能短暂处于待同步状态。

## 可手算的确定性验证

夹具见 tests/projection_fixture.py，E 显式调用现有安全抽样选择器取一个合格对象，gap1 独立于变量。通过原生归档接口构造有效收据；无需调用外部模型。下表列出断言的期望与实际共同值。

| 操作 | 复核对象（完成 / 失败 / 待复核） | 变量结果与下钻 |
|---|---|---|
| A 的 a1 安全，a2 仍待复核 | 冻结对象总量 7 | A 仍为 LIKELY |
| 指定检查点 | 5 / 1 / 1 | 共 6 个变量。CONFIRMED 1、LIKELY 1、UNKNOWN 1、SAFE 2、SHARED_NO_REVIEW 1。待办 B、C、D。按 finding 分组分别为 confirmed 1、likely 0、safe 3、unresolved 3。 |
| b1 重试为 FALSE_POSITIVE，并重复提交同一收据 | 6 / 0 / 1 | SAFE 3、LIKELY 0，待办 C、D。重复提交的水位、所有分组和总量保持一致。 |
| gap1 完成为 NEED_MORE_CONTEXT | 7 / 0 / 0 | SAFE 仍为 3，C、D 仍待人工确认。 |
| 人工确认 D 安全 | 7 / 0 / 0 | 待办只剩 C。D 原始 UNKNOWN、AI 的 NEED_MORE_CONTEXT 和人工签字均可独立读回。 |
| 冻结前后各导出一个完整包，重新导入 | 早期包完成 5，后期包完成 7 | 包内版本与离线重开读数相符。人工增量的人工版本为 1:0。 |

## 真实 Chrome 与故障注入

测试在独立 SQLite 批次提交 b1，仅对目标浏览器请求注入一次 503。修复后在 commit_review_result 返回后启动计时，记录浏览器第一次观察到新显示值的时间，包含等待轮询和读取界面所用时间。没有再次提交或手动刷新。

| 区域 | 旧资源，观察 10 秒 | 最终资源，实际可见结果 |
|---|---|---|
| /summary | 卡片消失 | 3.047 秒，安全卡为 3 |
| 汇总成功、/symbols 失败 | B 行停在静态疑似 | 3.281 秒，B 行显示安全及 OpenCode 来源 |
| 列表成功、/symbol 失败 | B 详情停在静态疑似 | 3.625 秒，B 详情显示 OpenCode 安全，原始分类仍为静态疑似 |
| /ai 主列表成功、离开当前页的选中详情失败 | B 的详情停在技术失败 | 2.047 秒，B 的详情显示 FALSE_POSITIVE 及完整答复 |
| 另一个窗口的人工待办 | 2.641 秒，显示 2 | 1.656 秒，显示 2 |

另在未产生新版本时验证了变量 AI 答复首次失败后 0.937 秒自动恢复、新搜索第一次失败后显示 C 一行、初次汇总失败后卡片自动出现。故意延迟旧搜索和旧批次返回，A→B→A 后仍显示 6 个当前变量。待办末页从 51 减到 50 后，页脚、实际行、分页边界、当前选中详情一致。后台冻结页恢复后，B、C 差异范围的风险、未知、安全、待确认由 2 / 0 / 0 / 2 变为 1 / 0 / 1 / 1；风险下钻只剩 C。页面滚到 320 像素时发布新结果，列表自动补读后的滚动位置仍为 320 像素。草稿内容保留，旧 heads 提交被拒。新完整包的 manifest 记录生成时刻 2026-11-20T14:09:24.758305+00:00，导出版本为 8:0:0。另在私有测试归档故意写入无效清单，再打开不存在的批次。实际接口分别返回 INVALID_SCAN 和 SCAN_MISSING，页面均显示读取错误并撤下上一批卡片。历史页显示三个测试归档。三名并行写入者向新冻结集合提交 7 个不同 finding，随后重复提交其中一项，使用独立会话的两个 Chrome 进程观察结果。概览窗口最终显示风险 1、未知 1、安全 3、待办 2；OpenCode 窗口显示完成 7 / 7。详见 verified-final/navigation.json 和 verified-final/parallel.png。受控浏览器记录没有未捕获的页面异常。

## 本机真实 OpenCode 验证

源码 ECRA.cmd 启动独立的 result-sync-live 数据根，在 STM32 工程 `H:\stm32_RAG\code\serial - opencode` 新建全量扫描批次 `9be1b560f1e34b9aa971e31d5ef7d744`。本机 opencode.exe 使用配置的 deepseek/deepseek-flash。扫描清单 58 个变量，初始化 23 个复核目标。使用现有 review.finding_ids 限定试运行范围；本地实现不提供 max_items 参数。

| 操作 | 实际归档（完成 / 失败 / 待复核） | 同批次可见结果 |
|---|---|---|
| 新扫描，选两个对象复核 | 0 / 0 / 23 | 风险 23，安全 26，人工待办 23，变量页总量 58 |
| huart2.Instance 已提交，请求安全停止 | 1 / 0 / 22 | 任务 INTERRUPTED。风险 22，安全 27，待办 22 |
| 同一批次恢复，huart2.gState 完成 | 2 / 0 / 21 | 扫描任务和 OpenCode 页一致。风险 21，安全 28，待办 21。变量分页 1–50 / 58 |
| 限定 huart2.Init.WordLength，配置一次 1 秒真实调用超时 | 2 / 1 / 20 | 对象 TECH_FAILED，变量仍为静态疑似、待确认 |
| 恢复调用超时预算，点击“仅重试技术失败” | 3 / 0 / 20 | 同一 finding 有两次尝试。有效答复 REVIEWED_SAFE，变量原始 SUSPECT。任务页本轮处理 1 / 1，归档总对象持续为 23。重新打开源码入口后风险 20，安全 29，待办 20。 |

在上述已结束任务页面另对任务目录、任务详情各注入一次 503，2.438 秒后实际显示全归档进度 3 / 0 / 20 和本轮 1 / 1。真实模型仅运行少量选择项；冻结集合最后一个对象、并行完成、重复通知及旧 worker 的场景使用可重复的本地测试。

## 复跑与证据

在仓库根目录运行 Python 和 Node 测试，在 studio 目录执行前端构建。

```powershell
py -3.10 -m pytest -q tests/test_studio_current_results.py tests/test_studio_ai_results.py tests/test_studio_api.py tests/test_studio_manifest_errors.py tests/test_studio_filters.py tests/test_engine_digest_coverage.py tests/test_review_maintenance.py tests/test_report_package.py tests/test_html_report.py tests/test_sealed_export.py tests/test_review_resume.py
py -3.10 -m pytest -q tests/test_effective_decisions.py tests/test_nested_container_projection.py tests/test_human_reviews.py tests/test_review_inheritance.py tests/test_native_diff_reader.py
py -3.10 -m pytest -q tests/test_studio_current_results.py tests/test_studio_ai_results.py -k 'PublishedCheckpoint or conditional_ai_read'
py -3.10 -m pytest -q tests/test_sealed_export.py::SealedExportTests::test_repeat_import_reuses_only_freshly_verified_identical_bytes
py -3.10 -m pytest -q tests/test_effective_decisions.py::ExportTests
node --experimental-strip-types --test studio/tests/*.test.mjs
Push-Location studio
npm.cmd run build
Pop-Location
py -3.10 scripts/validate_projection_sync.py --output output/playwright/result-sync/delivery
py -3.10 scripts/validate_projection_sync.py --output output/playwright/result-sync/acceptance
py -3.10 scripts/validate_projection_sync.py --output output/playwright/result-sync/verified-final
```

真实界面取证在本机 output/playwright/result-sync 下。before 保存修复前取证。delivery 保存最终资源及 Portable 使用的完整包记录；verified-final/observations.json 保存从事务返回起算的界面延迟。interleave.json 保存同响应的全量及差异水位，live.json 与 live-retry.json 保存真实任务及答复。task-sync.json 记录真实任务页的目录与详情补读。legacy.json 保存 Chrome 实际打开 index.html、opencode_review.html、classification_quality.html 时读取的扫描和生成时间。

## 启动入口与构建产物

Vue 类型检查和 Vite 构建成功，输出目录为 ecra/studio/web。两种入口都用 --no-browser、--data-root 和 --session-file 启动，再让本机 Chrome 打开启动器生成的同一会话地址。源码 ECRA.cmd 重开真实 STM32 批次后，读取到结果版本 13:0:0。使用 build_portable.ps1 -OutputDir dist/projection-sync-20261120 -SkipZip 生成独立的未压缩 Portable 候选。在其验收副本启动 ECRA.cmd，通过“数据与共享”上传浏览器刚导出的完整包，打开归档并重新加载。差异批次版本为 8:0:0，卡片为 1 / 0 / 1 / 1，安全下钻匹配 1 个变量 B；OpenCode 页显示 7 个目标、完成 6、失败 0、待复核 1。

两次启动实际下载的 index-CN46WGxP.js 的 SHA-256 都是 ef12a4cf95a56b314c203db88090e13151c8ee17fd39d384980e6d93fbde7c5e。源码、Portable 及验收副本引用的 index-b7ek73eC.css 字节也一致。独立候选目录是在构建期间准备的，含一对未被入口引用的中间 JS/CSS 文件；源码输出目录只含最终资源。已有发行目录未覆盖。source-launcher.json 与 portable-launcher.json 记录两次启动的实读值和资源摘要。

原打包命令在临时验收副本触发项目已有的 Windows 短路径长度限制。将同一清洁候选复制到 dist/ps26 后，使用其内置 Python 执行官方验证器，工作目录为 dist/qa26。官方验证器返回 PASS，记录 31 条命令。真实 ARM 编译、原生 SQLite 扫描、三轮全量 / Git 差异验证以及安装文件内容复核全部完成。这三轮验证未调用模型。命令和结果保存在 output/playwright/result-sync/short-portable.log 与 dist/qa26/acceptance.json。

```powershell
.\dist\ps26\runtime\python.exe -B .\dist\ps26\validate_portable.py --bundle .\dist\ps26 --work .\dist\qa26
```

## 测试结果与验证边界

- 前端 34 项测试通过。vue-tsc --noEmit 与 Vite 构建通过。Chrome 故障注入、统计下钻、导出、启动入口和并行补读均有实际渲染结果。
- 11 个后端测试模块的组合运行耗时 40 分 36 秒，98 项通过、2 项失败，另有 92 个子场景通过。本次新增的 3 项检查点及条件读取回归另行运行，3 项通过。
- 组合运行的一项失败是旧引擎迁移摘要正例 test_review_publication_upgrade_accepts_only_matching_static_bytes。在 e0c64f2 原代码的独立副本保留进场时的 Git 差异改动后，单独运行同一断言也失败。真正使用修复前检查点的 STM32 批次通过了恢复与重试。更早发布版的全部检查点组合仍未经实机验证。
- 另一项失败发生在 test_repeat_import_reuses_only_freshly_verified_identical_bytes 首次导入时。Windows 在发布暂存目录的 rename 上返回 WinError 5。同一工作副本立即单项重跑通过（40.88 秒），原代码的封存导出模块 8 项也通过。暂未定位该次拒绝访问的持有者。完整包数据、版本和重开后的读数已有独立的接口、源码和 Portable 界面验证。
- 另跑决策矩阵、结构体容器、人工记录、确认沿用和基准侧读取共 42 项。首次 38 项通过。其余 4 项原先试图从已停用的 .ecra/facts.json 读取夹具输入，原提交也复现。test_effective_decisions 的 ExportTests 现通过原生扫描入口获取 scan.db，从中取事实与静态报告后执行同一组旧版导出断言。单独重跑 4 项全部通过，另有 15 个子场景通过。运行记录为 decisions.log、baseline-decisions.log、canonical-decisions.log。
- 核对失败与重跑可查看 python-regression.log、baseline-engine.log、retry-sealed.log 和 baseline-sealed.log。本次没有执行解压 ZIP 或另一台干净 Windows 主机的发行验收；真实 STM32 复核覆盖了所选 3 个对象。
