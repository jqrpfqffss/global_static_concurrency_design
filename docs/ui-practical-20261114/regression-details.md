# 本轮前端修复的针对性回归与补充审查

日期：2026-11-14。范围：I01 文本筛选、已知覆盖缺口解释、证据标签加载竞争、I04 连续复核导航。下列自动检查不是实际界面验收；画面与原操作路径复验由主实操记录另行给出。

## 最终检查

在项目根运行：

```powershell
node --test studio/tests/evidence-interaction.test.mjs studio/tests/filter-updates.test.mjs studio/tests/investigation-state.test.mjs
```

结果：26 项通过，0 失败。包含：

- 文本条件静置后自动查询；关闭弹窗前提交最后输入；切换上下文取消旧待执行请求。
- DMA 共享生命周期/缓存/所有权及外部被调实现缺失的准确解释，未来未知类型仍明确显示未知。
- 实际 `loadSelection` 函数在待完成请求期间保留用户新选标签；同一规范对象重读保留源码位置，新对象使用其默认标签。
- 实际队列导航函数覆盖第 0、49、50、52、99、149 项移出后的后继/前项；测试对象故意全部同名而规范身份不同。
- 扫描身份或筛选条件变化时拒绝使用旧导航锚点。
- 末页只剩一项并移出后回到最后有效页；整个队列归零时双向导航无目标。
- I01 关联审查发现的输入法风险：composition 阶段不启动查询，Enter 不截走候选确认；提交字符后才查询。
- 原有人工草稿身份及证据名称/分页回归。

在 `studio/` 运行：

```powershell
.\node_modules\.bin\vue-tsc.cmd --noEmit
git diff --check -- src/App.vue src/filterUpdates.ts src/CoverageCenter.vue tests/evidence-interaction.test.mjs tests/filter-updates.test.mjs
```

结果：均退出 0，无类型错误或空白错误。该子任务没有构建、同步运行副本、重启服务或修改测试数据库。

`evidence-interaction.test.mjs` 从实际 Vue SFC 提取并执行待测函数，用受控延迟请求/只读测试状态核对边界；不复制生产逻辑作为测试实现。它不证明浏览器布局、原生输入法候选窗口或正式后端持久化已通过。

## 补充静态审查

- 切换 scan 的同步 watch 会调用 `invalidateResult` / `returnList`，清空选中对象及导航锚点。
- 旧锚点使用前必须匹配 scan、`evidence_side + symbol_id` 和查询身份；当前页仍含该对象时以实时规范身份查找的位置为准。
- 查询身份包含搜索、静态/人工分类、待办范围、额外筛选及排序，不以变量显示名称绑定。
- 普通筛选、清空筛选和关闭弹窗会取消或提交文本查询计时器；页面/扫描变化及组件销毁取消计时器。输入条件在前台查询期间禁用，避免同时提交相互覆盖的条件。
- 发现关联风险：Vue 在输入法 composition 期间尚未提交 v-model，新 `input` 监听若照常延迟查询，可能按旧文本查询并禁用正在组合输入的控件。现已在 compositionstart 取消旧计时，在 composing input/Enter 时保持输入，提交后再查询。**此项来自代码审查及事件级回归，不冒充已复现的 Windows 原生输入法问题。**
- `saveDecision` 本身不调用 `loadSelection`；它更新人工记录、对象元信息及列表。同对象重读可来自再次选中/继续位置等入口。不要把未观察到的调用链写成实操事实。

## 中间回归记录

|命令/阶段|结果|
|---|---|
|根目录 `node --test studio/tests/filter-updates.test.mjs`|首次 3 项通过|
|根目录 `npx vue-tsc --noEmit -p studio/tsconfig.json`|误从根目录调用，npx 未使用 Studio 固定本地工具；出现 CSS side-effect import 类型错误，不计验收通过。随后改为 Studio 本地已安装命令|
|`studio/` 中 `.\node_modules\.bin\vue-tsc.cmd --noEmit`|各次产品修改后均通过|
|根目录 `node --test studio/tests/investigation-state.test.mjs studio/tests/filter-updates.test.mjs`|11 项通过|
|`studio/` 中 `node --test tests/evidence-interaction.test.mjs tests/filter-updates.test.mjs tests/investigation-state.test.mjs`|补覆盖解释和标签竞争后 14 项通过|
|同上，补 I04 边界的首次运行|23 通过、1 失败；测试夹具遗漏真实默认 `extra.diff=''`，使查询身份不一致。按真实初始状态修正夹具后复跑|
|根目录三文件测试命令（见最终检查）|I04 后 24 项通过；补输入法保护后最终 26 项通过|
|`git diff --check`（全区或上述限定文件）|均通过；全区曾提示已有构建文件 LF/CRLF 转换，不是检查失败|

上述计数为回归用例数，不计入逐功能实操清单的功能总数。

## 后续实操发现的任务与历史状态显示

主实操在已完成任务和历史对比中发现三处显示不准确，本次仅修正展示，不改任务引擎状态或历史比较算法：

- 任务 `41986655eb5c492aa549feb5b7e701bb` 的真实持久化记录为 `COMPLETE`、`published=true`。任务详情接口从已有扫描诊断及预检查文件追加 `progress_kind=TU_EXTRACTION`、`preflight.passed=true`（`ecra/studio/tasks.py`）。原界面先判断 `progress_kind`，终态仍显示带 `role=status` 的“已进入正式扫描”交接提示。`TaskCenter.vue` 新 `preflightNotice` 仅用于活动任务；终态保留真实标题及阶段历史。
- 真实 Git 差异任务 `9961ee33b67c4b40afe7df6e267008ab` 的任务元信息只有 `mode=scan`，并无 `scan_mode`/diff 字段；它与全量扫描共用模式。不能用后来可能编辑过的当前 profile 回推范围。任务名称改为准确的通用“扫描分析”；归档结果概览仍显示真实全量/差异身份。
- 引擎实际输出 `INCOMPLETE` 或 `MODELED_SCOPE_COMPLETE`（`ecra/analysis.py:1591`）。历史列表原靠局部 INCOMPLETE 特判正确显示，历史双方身份却用缺项的共用标签而显示“未识别”。在 `api.ts` 共用字典补 `INCOMPLETE: 部分覆盖（INCOMPLETE）` 并删除历史列表局部特判；未知新值仍原样明确提示未知。

最新回归：项目根再次运行上述三文件 `node --test` 命令，**29 项全部通过**；`studio/` 下运行 `.\node_modules\.bin\vue-tsc.cmd --noEmit` 通过。项目根运行：

```powershell
git diff --check -- studio/src/TaskCenter.vue studio/src/api.ts studio/src/HistoryCenter.vue studio/tests/evidence-interaction.test.mjs
```

退出 0，仅提示 TaskCenter 工作副本的常规 LF/CRLF 转换。新增用例直接执行实际任务提示、标题和共用标签函数，验证 COMPLETE/FAILED/INTERRUPTED 不留进度交接文案，活动扫描仍有阶段提示，已知覆盖状态正确而未来枚举不被吞掉。首次新增共用标签用例时测试提取器未设置模块格式，导致 VM 不支持 `export`（27 通过、1 测试装载失败）；修正提取器使用 TypeScript CommonJS 编译输出后再新增标题用例，最终 29 项通过。

本子任务未构建、同步运行副本或重启。以上为代码及自动回归结果；实际新界面复验由主实操继续完成并记入总清单。

## 头文件同名静态对象的编译单元提示

主实操搜索 stress 的 `state` 时，5 个 `header_state` 同名且全部定义于 `shared.h:9`，列表需要逐个打开完整规范身份才可区分。先以只读 `QueryService(...).symbols(search='header_state')` 核对真实扫描 `c11a3535eff94f158f6e786c14b4b7e3`：行字段没有 `translation_unit`，规范 ID 分别是 `tu::one.c::c:shared.h@header_state`、`tu::two.c::...`、`bulk.c`、`main.c` 及深目录 TU。这是 extractor 明确的内部链接 ID 格式（`ecra/extract.py:229`），并非根据名称猜对象。

`App.vue` 新 `translationUnitHint` 优先显式 `translation_unit`，否则仅解析上述已知前缀（包括 local 嵌套形式）；未知身份不猜测。TU 与定义文件相同时不重复提示。列表、详情顶部和当前确认对象展示“编译单元：路径”；完整规范身份和所有保存绑定保持原样，长路径允许列表折行并提供完整 title。没有增加 API 请求、全表哈希或对正式数据写入。

最新三文件测试命令 **30 项通过**；Studio 本地 `vue-tsc --noEmit` 通过。`git diff --check -- studio/src/App.vue studio/src/workbench.css studio/tests/evidence-interaction.test.mjs` 通过。新增用例验证同名同位置的不同 TU 提示、显式字段优先、已由定义位置区分的对象不重复提示、未知前缀不猜测和规范 key 仍不同。首跑时测试直接从 VM 上取 `const rowKey` 失败（29 通过、1 测试访问失败），改为从 VM 词法环境读取实际函数后 30 项通过。尚待主实操构建后复验实际列表、长路径及人工确认定位。

## I10：提交失败反馈必须出现在用户当前可见范围

实操证据 `output/playwright/ui-practical-20261114/package-48-missing-command-check-result.png/.txt`：工程配置步骤 4 展开长 YAML，在底部点击检查，`review.command` 写成字符串时后端正确拒绝，错误原文为“review.command 必须是非空参数数组，不能是 shell 命令字符串”。App 的主 `main` 是滚动容器，错误只插入顶部全局 alert；原视口仍停在 YAML 底部，用户看到保存按钮禁用却看不到原因。

最小共用修复：全局 alert 增加 ref 和 `tabindex=-1`；`run` 捕获用户操作失败后等 Vue 渲染，再将该 alert 滚入可见区域并聚焦。正常成功无滚动；后台 `readPage` 读取失败仍被动显示，不夺取用户输入焦点；已经打开 WorkspaceDialog 时保留其注入的、位于滚动内容之外的错误栏，不将焦点移至 modal 后方。校验及保存条件没有变化。

最新仍使用根目录三文件 `node --test` 命令：**32 项通过，0 失败**。新增用例执行实际 `run` / `revealActionError`，验证失败先更新原错误、等待渲染、滚动/聚焦，成功不抢焦点，打开 modal 不跳出。Studio 本地 `vue-tsc --noEmit` 与上述 App/CSS/测试限定 `git diff --check` 均通过。尚待主流程构建与 data_audit 的原长 YAML 路径实操复验；本子任务未自行构建或重启。

## I11：同工程的扫描配置名称遗漏

主实操在任务中心看到两个名称不同的 demo-b 配置，下拉只给相同工程路径和不易识别的 ID 前缀（证据 `27-budget-invalid-and-opaque-profile.jpg/.txt`）。API 已提供 `name`，复核中心也已正常显示，根因是 TaskCenter 展示模板遗漏。最小修复仅在扫描配置下拉和折叠摘要加用户配置名；路径与 ID 前 8 位继续保留，无名旧项显示“未命名配置”。不更改配置选择绑定、任务启动或验证逻辑。

按主实操本次明确授权，在 `studio/` 运行 `npm.cmd run build`（内含本地 vue-tsc 和 Vite）成功；新资源 `index-Covwq14P.js`，CSS仍为 `index-Dw60A1lg.css`。将资源复制到既有隔离 runtime 的 `ecra/studio/web/assets` 后最后更新 index.html；三个文件与源构建 SHA-256 完全一致，见 `output/ui-practical-20261114/i11-build-sync.json`。未重启主服务、未删除历史资产，`git diff --check -- studio/src/TaskCenter.vue ecra/studio/web/index.html` 通过。低影响显示改动未新增镜像实现测试；待 root 重新加载新资产后沿原下拉/折叠摘要路径实操复验。

## I13：主动取消与连接断开的后端边界

真实限速上传主动取消时，原持久任务为CANCELLED，但错误文字为断网重选。根因是server把ClientDisconnect统一包装成OperationCancelled。最小修复涉及`ecra/studio/import_jobs.py`、`ecra/studio/server.py`，用UploadDisconnected表示连接丢失，并在事务内核对持久取消意图；避免晚到异常改写终态，保留服务停止与一般写入/校验失败原因。

最终准确命令（项目根）：

```powershell
py -3.10 -m unittest tests.test_import_jobs tests.test_report_package tests.test_sealed_export tests.test_export_jobs -v
```

执行代理结果：41项全部通过，25.652秒；其中import模块17项（包括最后增加的COMPLETE终态覆盖），不是较早16项时点。新增/补充回归在`tests/test_import_jobs.py`。限定两产品文件与此测试文件的`git diff --check`通过，主代理已审查最小生产差异。没有重复运行大型固件工程。

源码/runtime两文件SHA完全相同，正式launcher在同54917重启，实际新server31456，见[i13-runtime-sync.json](../../output/ui-practical-20261114/i13-runtime-sync.json)和[重启收据](../../output/ui-practical-20261114/i13-server-restart.json)。前端仍CdM0AXW-；其现有Studio32项和构建/类型检查记录保留。

真实UI原主动取消路径已通过，详见[上传取消实操](upload-cancel-review.md)；新任务0476…为CANCELLED/UPLOAD，文案准确、无发布。附加UC02非主动断流未形成真实断流，两个任务实际重复合并0；这部分只有自动回归支持，不能用41项通过冒充真实故障画面通过。
