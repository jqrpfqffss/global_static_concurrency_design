# 继续验收：完整回归与隔离故障矩阵

本记录从已完成的 2026-11-08 验收继续，不把旧的小测试合计成新的全套结果。原完整套件已真实跑完，结果为失败；运行期间生产分析源码冻结，起始和结束静态引擎均为 `74c0b1c0f3fa204088534ad90f5bcefaf4bccb5a00ce42bce4cfb878eea509b2`。

原 1646 全套、最终 v4 的 140 项相关组合、后继 test-only 修正分别保留原终态。后面的定向通过不能将前两次失败运行改写为“全套通过”，也不能合计成一次最终版本全套执行。

## 本次完整回归入口

按当前 README 声明的整套入口启动一次实际进程：

```powershell
py -3.10 -B -X utf8 -m unittest discover -s tests -v
```

启动时发现 204 个 `test_*.py` 文件、1646 个测试，无发现阶段错误。发现计数单独记录在 `output/quality-20261108/continuation/regression/discovery.json`，它只计数，不另算一次测试执行。

- 真实进程与完整 stdout/stderr：[full-suite-01/unittest.log](../../output/quality-20261108/continuation/regression/full-suite-01/unittest.log)。没有 `failfast` 或排除测试文件。
- 全套状态、最终退出码、汇总解析及源 hash 比对：[full-suite-01/receipt.json](../../output/quality-20261108/continuation/regression/full-suite-01/receipt.json)。原控制器将失败与不完整共用一个状态名；[独立终态核对](../../output/quality-20261108/continuation/regression/full-suite-01/assessment.json) 已确认这是有最终摘要及真实退出码的完整失败运行。
- 源文件 hash：同目录 `source-before.json` / `source-after.json`，479 个文件前后完全一致，0 变更。包含 ecra / tests / scripts 下 Python 文件与依赖声明；不把文档修改当成分析引擎变化。
- 资源：同目录 `resources.jsonl`，每 2 秒采样该测试进程树的工作集、私有提交、进程数，以及单列的 Windows 系统提交/物理内存、输出盘余量。采样峰值不是连续无遗漏的系统峰值，也不是整个产品的性能门禁结论。
- 显式关闭 `ECRA_DEEP_REVIEW_LIVE` 和 `ECRA_STALE_WRITEBACK_LIVE` 两种真实模型 opt-in。实际仅这两项 live 测试跳过，原 skip 原因逐项保留。其余 Windows、工具链与资源压力测试按当前条件执行，没有为了加速而筛掉长测试。
- 数据根和临时目录在 `H:/ECRA-quality-20261108/continuation/regression/`；不使用默认客户库。没有运行其他人的浏览器或服务。

实际运行 UTC 2026-11-08 05:55:26 至 11:32:40，unittest 摘要为 `Ran 1646 tests in 20226.883s / FAILED (failures=3, errors=3, skipped=2)`，子进程退出 1。三个 FAIL 方法各有一个过早清理活动 fixture 的 ERROR，共 3 个失败方法、3 个清理错误事件，不是 6 个独立失败方法；无其他 ERROR。原收据中的派生 `passed_tests` 会重复扣同方法的 FAIL 与 cleanup ERROR，因此本记录不据此报告通过方法数。逐事件 traceback 在同目录 `failure-events.json`。

采样测试进程树峰值 RSS 307,404,800 字节、private 274,329,600 字节、9 进程；这是测试运行的采样值，不能作为真实大工程性能结论。真实工作字节 CMake 的全量和差异长测均实际完成，初次 capture（包含配置、依赖盘点及完整 SDK 固定）曾耗时约 17 分钟；阶段原样快照在 `long-cmake-stage-snapshot.json` / `long-cmake-phase-transition.json`。不能把这一旧引擎、含未提交工作字节的特定路径耗时外推给最终引擎或其他模式。

结束后 PID 37536 及直接后代已退出，收据为同目录 `cleanup-observation.json`。另有 1 条原 ResourceWarning，来自负向 saved-command-monitor 收集失败测试：其测试代码随后按 PID / 创建时间等待自有短命子进程，该 PID 39504 也已退出；警告原文保留于原日志和独立核对，没有删去不利输出。

## 实际故障矩阵

本矩阵采用新隔离 F030 扫描、真实 CLI 子进程、独立原生 Studio 服务与鉴权 HTTP。受控复核响应只测试传输和恢复，保守返回 `NEED_MORE_CONTEXT`，不作为模型正确性或工程签署证据。

原始收据：[fault-matrix-01/receipt.json](../../output/quality-20261108/continuation/regression/fault-matrix-01/receipt.json)。每个 CLI 命令、退出码和完整日志均在同目录。测试数据位于 `H:/ECRA-quality-20261108/continuation/fault-matrix-01`。

| 故障 / 用户目标 | 实际操作与结果 | 原矩阵状态（后继修复见下文） |
|---|---|---|
| 无效配置 | 实际读取错误 YAML，退出 3，报告具体 YAML 位置与原因 | 已通过此场景 |
| 工程路径不存在 | 指向独立不存在目录，退出 3，无新有效扫描 | 已通过此场景 |
| 输出路径无法作为目录 | custom_dir 指向预先存在的普通文件；退出 3，原文件字节不变 | 已通过此场景 |
| OpenCode 命令不存在 | 新 F030 静态扫描后将复核命令指向不存在 exe；6 项均记 TECH_FAILED，静态库 hash 保持 | 已通过此场景，未执行模型 |
| 单项真实进程超时 | 受控子进程中 1 项等待到超时，5 项完成；原始日志保留，超时进程清理 | 已通过传输/资源清理场景 |
| 恢复技术失败项 | 外部受控后端恢复后正常运行 review-failed；只再调用 1 项，先前 5 项完成收据原样保留 | 已通过恢复，不注入队列或历史 |
| 实际人工保存写锁 | 独立 SQLite 连接持有 EXCLUSIVE 锁，实际 HTTP 保存返回 409 / DATABASE_BUSY；原结论无新增 | 已通过此场景 |
| 写锁释放后继续保存 | 同一未改请求在释放锁后正常成功；静态证据不变 | 已通过此场景 |
| 标准完整导出 | 通过普通 export / download 接口保存包含实际人工事件的包 | 已通过此场景 |
| 损坏结果包输入 | 实际上传坏 ZIP，静态证据和已有扫描不变；但返回 500 泛化诊断号，未说明包损坏及恢复方法 | 已失败：Q106，待协调修复 |
| 单个显示清单结构损坏 | 隔离 scan 的 manifest.json 为合法 JSON `[]`；有效独立示例详情仍 200，但整个 /api/scans 返回 500 | 已失败：Q105，待协调修复 |
| 损坏任务必要字段 | 真实服务重启后，该任务明确 UNREADABLE，原字节保留，其余服务可用 | 已通过此场景 |
| 损坏 scan.db | 在正常导入的隔离副本中损坏 SQLite 文件头；目录明确标 FAILED，详情 400，原坏字节保留 | 已通过拒绝无效证据场景 |
| 标准包恢复 | 正常导入新独立数据根；包 manifest hash = 包内 scan.db hash = 导入 hash，逻辑事实/报告/变量指纹及原人工 event_id 一致，deep 完整性通过 | 已通过正常产品恢复，未注入历史 |

Q105 根因为 `/api/scans` 对 manifest 未检查映射结构便调用 `.get`；Q106 为 `zipfile.BadZipFile` 未提供输入错误映射。两者均由当前实际服务复现，已交协调者安排修复。没有为了完成矩阵直接修改生产分析模块，或把失败改成成功。

## Q105 / Q106 独立候选修复

为保持正在运行的完整套件使用冻结源码，修复先放在 `H:/ECRA-quality-20261108/continuation-server-candidate`，没有更改主工作区源代码或测试。候选仅修改 `ecra/studio/server.py` 并新增 `tests/test_studio_manifest_errors.py`。

- 列表、详情和既有导入合并目标共用有界清单校验，检查 JSON 对象、格式/版本、项目/扫描/证据身份及本机发布状态；目录逐项隔离坏记录。普通 `ECRA_REPORT` 包没有本机执行 state 时仍按静态 binding 浏览，不将包清单当作本机完成证明。
- 无效 ZIP、截断、CRC 错误明确返回 400 / INVALID_REPORT_ARCHIVE，保留技术原因，说明导入阶段失败、未发布、原件和人工记录保留以及重新获取完整包的下一步。合法 ZIP 内错误 JSON 容器同样不会成为内部 500。
- 已有目标清单损坏时，正常备份导入明确拒绝合并并指引在新独立目录恢复，不覆盖坏原件或旧人工记录。核心路径、压缩预算、哈希、完整性和绑定校验仍照常执行。
- 最终候选 49 项定向回归全部通过、0 跳过（49.839 秒），包含实际 native 与 derived 发布器正例；最终同字节服务器实际启动后，11 项鉴权 HTTP 复验通过，服务均已关闭。真实 F030 的隔离正例拷贝逐个核对 123 个原始文件 hash 后打开；错误非空状态 `COMPLETE` 被明确拒绝，原 F030 文件不变。派生正例采用既有最小 Clang / ELF 资产，不作双核硬件验证。证据见 [最终候选收据](../../output/quality-20261108/continuation/regression/server-candidate/candidate-state-contract-receipt.json)、[实际服务记录](../../output/quality-20261108/continuation/regression/server-candidate/candidate-actual-service-final.json)、[完整回归日志](../../output/quality-20261108/continuation/regression/server-candidate/candidate-state-contract-tests.log)。
- 最终精确变更：[q105-q106-state-contract.patch](../../output/quality-20261108/continuation/regression/server-candidate/q105-q106-state-contract.patch)，取代前一版 38 项候选。候选 server SHA-256 为 `672dac97992ad556150c47b38d23338fac6ae3f3396b9ca6dd838d1abd1b832f`；主区 server 仍为复制前 `244469a005522abbc6e02ca62fd9717218c6e4feb78821fe033ef3565d1eef55`。

候选首轮回归曾因新校验错误要求离线包包含本机 state 而有 2 项失败，日志 `candidate-tests.log` 保留；按当前普通导出包的独立合同修正，未改既有预期。最终回归包含实际内置包和无 state 包清单正例。

本机 state 的独立依据是 `scan_persistence.py` 第257行以 UNVERIFIED 发布不可变库，第474–476行在最终输入校验后另写 LOCAL 清单 STATIC_VALIDATED；`multicore.py` 第288–290行同样固定该发布状态。实际 F030 也为“DB UNVERIFIED / manifest STATIC_VALIDATED / run_state INCOMPLETE”。因此 LOCAL 的合法值按发布协议固定，不与 DB state 作错误的相等约束，也不以本机发布状态代替运行完整性。ECRA_REPORT 不从原发布者的可选 state 建立当前源码证明。

**这一阶段仅“候选验证通过”**，没有更改主区源码。原完整套件现已结束且源 hash 核对完成，后续同字节落地主区及最终复验由协调者的交付记录确认。

### Q105 候选的旧归档兼容遗漏与收敛

协调者发现首版白名单遗漏了当前 `legacy_import.py:250` 的真实发布格式 `ECRA_LEGACY_IMPORT`。这是候选兼容性回归，不能用前述 49 项通过覆盖。另建 `H:/ECRA-quality-20261108/continuation-legacy-server-candidate`，基于冻结 v3，仅改 server 和 manifest_errors 测试，不修改主区或 v3。

- 先用真实完整旧归档和缺失 facts 的降级旧归档转换器，均等转换完全返回再浏览。未修候选的列表将两者错误标为 FAILED，1 个测试的 2 个子场景失败；原日志为 `legacy-server-candidate/before-tests.log`（186.710 秒），没有活动迁移目录被提前删除。
- 修正精确接受该现有格式，其 state 必须等于 DB binding，且只允许转换器实际产生的 LEGACY_READ_ONLY / UNVERIFIED。LOCAL_SCAN 仍只接受 STATIC_VALIDATED；REPORT 仍取 DB，未知格式、坏身份和坏版本仍拒绝。没有将旧归档变成当前源码证明。
- 两种真实转换后的列表、详情、历史、普通完整包导出/HTTP 导入往返，以及旧归档错误 state/identity，已加入定向回归。首段控制器的 1200 秒外限设置过短，完整完成 27 个方法后在 history 首项中止；无最终 unittest 摘要，明确记 INCOMPLETE_CONTROLLER_TIMEOUT，不能写成一次 51 项运行通过。随后验证同 2 个修改文件 hash、同引擎、相对冻结 v3 恰好只有预期的两处差异，再单独运行剩余 24 项：24/24、794.614 秒、退出 0、完整 Python 源 hash 不变。两段共覆盖 51 个不同方法，记录见 [coverage-chunks.json](../../output/quality-20261108/continuation/regression/legacy-server-candidate/coverage-chunks.json)、`final-receipt.json`、`remainder/receipt.json`；原中止日志保留。
- 独立真实 Studio HTTP 降级迁移已从 POST 等到真实 COMPLETE：启动响应后 49.844 秒。原语义检查均通过，包括 UNVERIFIED、0 可核验对象、禁当前人工/AI、原始脚本文本仅作文本、列表/历史可浏览、原字节不变。证据为 [实际 API 收据](../../output/quality-20261108/continuation/regression/legacy-server-candidate/actual-api/receipt.json) 和同目录脱敏 API 事件。自有服务、后代和私有会话已清理；没有启动新的固件任务。

### 原完整套件的异步等待失败

原整套 EOF 后确认三项 FAIL，每项又跟随一次清理 ERROR：旧归档降级 API、多核归档配置发布、多核预检变化后的重试。前两项独立原样复现分别保留在 `legacy-failure-diagnostic-01/` 和 `multicore-failure-diagnostic-01/`；实际原 traceback 也确认前者是 10 秒 migration 等待，后两者都是同一 40 秒 `wait_task` 等待到期，没有因业务断言错误而失败。三个清理事件分别为活动 legacy-import 锁、后台发布中的 scan.db、scan-budget 锁不能删除，继而 tempfile 的 WinError 267；不能把这些错误掩去。

产品没有这两个秒数的完成 SLA，实际迁移在约 49.8 秒正常完成，不能把固定等待到期直接写成产品迁移挂起。也不能据此把原失败抹掉。原整套始终原样运行，原过程没有修改测试；最终 479 个源码/依赖 hash 和 engine74 已核对全部一致，中途多次冻结核对也保留。

在独立 `continuation-async-test-candidate` 修正测试控制器：保留业务断言，给真实终态有界 600 秒观察；多核失败清理先通过普通 stop API，再等真实终态及监督器释放；迁移没有取消接口，finally 等实际终态和 lease。无法确认释放时保留测试根并报失败，不递归删除活动文件，也不把中断当完成。共同临时目录钩子只影响测试清理。

9 项定向已通过（426.709 秒、退出 0、源 hash 不变）：三项实际多核发布/失败后修源重试/共享预算，两项迁移 API，现有 lease 单测及三项控制器保护。原方法里的业务断言 AST 比较保持完全一致：legacy 14 方法/95 个 assert、workflow 6 方法/37 个、publication 9 方法/44 个。候选只改 5 个测试文件（含两个新增 helper/测试），不改生产；[结果](../../output/quality-20261108/continuation/regression/async-test-candidate/final-receipt.json)、[精确 patch 与 AST 依据](../../output/quality-20261108/continuation/regression/async-test-candidate/patch-receipt.json) 可复核。三项控制器测试中，一项用真实 Windows activity lease 验证活动目录不会被删；模拟客户端的 stop/timeout 单测不冒称真实产品使用。不能把这些定向结果计作新的完整套件或改写原 FAIL/ERROR。

### Q105 History 与列表仍不同步：共享读取 r2

r1 上新隔离 API 实际复现：LOCAL 清单 state 为合法 JSON 字符串 COMPLETE 时，/scans=FAILED、summary=400，但 /history 仍 COMPLETE / can_open:true，原静态和人工未变。原例见 `legacy-server-candidate/history-corruption-api.json`。这是同根读取规则遗漏，本轮继续闭合，不能因 r1 的合法归档正例通过而忽略。

新的独立 `continuation-studio-manifest-r2` 将有界解析、格式/版本、身份和三种发布格式的 state 合同抽到 `studio/display_manifest.py`，server/history 共用，避免循环依赖；错误目录都 FAILED / can_open:false。有效 native、derived、REPORT 与真实 legacy 的原合同保留。统一原先 history 1MiB 与服务/包 4MiB 的显示清单预算，并保留超预算拒绝。改动限于 3 个 Studio 生产文件与针对性 manifest 测试，不改分析核心。

19 项定向全部通过（1142.022 秒、0 跳过、退出 0、全 Python 源 hash 不变）。包括原 COMPLETE 字符串反例，坏 JSON/format/version/identity/state 在两目录一致失败，summary=400；合法 native、派生、两种实际 legacy 发布及普通包往返保持，静态和人工 DB 字节不变。派生正例仍为既有最小 Clang/ELF 资产，不是双核硬件认证。原 r1 的两个共享函数归一 AST 与 r2 完全一致，除复用入口/可打开标记外未放宽校验。证据见 [checks/receipt.json](../../output/quality-20261108/continuation/regression/studio-manifest-r2/checks/receipt.json)、[完整日志](../../output/quality-20261108/continuation/regression/studio-manifest-r2/checks/unittest.log)、[精确 patch/文件 hash/AST 比较](../../output/quality-20261108/continuation/regression/studio-manifest-r2/patch-receipt.json)。这是原主 1646 当时保持冻结期间完成的独立候选验证。

## 升级后新任务控制器与实际中断

入口与参数核对见 [new-task-upgrade-readonly.md](../../output/quality-20261108/continuation/regression/new-task-upgrade-readonly.md)，控制器为同目录 `start_new_studio_scan.py`。准备阶段只做语法、脱敏与不执行路径检查。原根实际有 64 对持久缓存，facts SHA 全匹配各自 manifest；旧诊断 extracted=72、旧 completed_units=64/388 分开保留，不推测差异原因。

协调者随后在 v3 / `6cede835...` 上通过真实 CLI、profile POST 和 NEW task POST 执行，任务 `d2529566dda44dc38a53c72e37dd4899`。因独立发现的严重分析问题 Q205，协调者通过正式 stop API 主动停止。控制器已自行观察到 INTERRUPTED / 130 / published:false 并收尾；原源文件/索引、配置、旧 scan/任务/cache、冻结引擎字节均保持，16 GiB Windows Job 的实际 limit/flags 被观察到，无自有后代残留，会话清理完成。证据为 [new-upgrade-first/receipt.json](../../output/quality-20261108/continuation/new-upgrade-first/receipt.json)。

该次在 TU 提取之前结束，**没有完成新缓存 key miss 或大型完整扫描验收**。Q205 的分析修复由协调者另行收敛；不能将该中断任务当成新引擎通过。旧缓存和旧扫描没有手改、删除或重新注入。

## 最终冻结 v4 的相关组合回归

协调者冻结 v4 后，另复制到 `H:/ECRA-quality-20261108/continuation-v4-state-regression`，651 个原件文件与副本逐字节一致，复制期间原 v4 未变。该副本用于可能临时修改自身测试配置的 API 检查，不与协调者的原 v4 UI/critical/build 检查共用可写源码目录。

UTC 2026-11-08 09:31:01 实际启动 16 个相关模块、发现 140 项，静态引擎精确为 `63a5cff7e9babcf0a4982726f68ca8390ad5f840b92d31d41e511a859d857710`。范围包括 manifest/API/history、整根复制与导入、目录偏好、坏任务、SQLite 停止桥、当前结果与嵌套容器边界、异步 helper、旧归档和多核相邻流程、资源策略、AI 只读视图和下载。核心 critical/构建/实际 UI 由协调者另验，不把该组当作全项目套件。

真实 OpenCode 两个 live opt-in 均显式为 0；TEMP/TMP/SQLITE_TMPDIR、LOCALAPPDATA/XDG 与 ECRA_DATA_ROOT 均指向独立测试目录，避免碰客户默认目录。UTC 2026-11-08 11:06:25 完整结束：`Ran 140 tests in 5716.344s / FAILED (errors=2)`，子进程退出 1，0 跳过。两个 ERROR 均属于同一 SQLite busy 方法的 publish / validate 子场景，实际都是原 12 秒子进程外限到期，未出现其他 FAIL / ERROR。原结果保留为“完成但失败”，没有改成全过。

651 个文件前后完全一致，原冻结 v4 的 651 个文件也不变；采样进程树峰值 RSS 143,540,224 字节、private 116,289,536 字节、4 进程，结束后测试 PID 36476 及其直接后代已退出。完整命令、源码前后、退出码、跳过和资源在 [原组合收据](../../output/quality-20261108/continuation/regression/v4-state-combined/checks/receipt.json)，[独立终态核对](../../output/quality-20261108/continuation/regression/v4-state-combined/checks/assessment.json) 列出原摘要与两个实际失败事件；同目录 `failure-events.json` 和 `unittest.log` 保留完整 traceback。下面的 test-only 修正另行复验，不替换此原组合。该组运行时，原 1646 进程同时使用主区 engine74，互不混源；两者现均已终态。

### SQLite 停止样例的准备时钟问题

组合运行中，busy SQL 方法的进度行没有成功状态。Python 3.10 的 unittest 对该类子测试错误在结尾才打印 traceback，不能因中途没有 FAIL 文本而计为通过。独立原字节模块的结果回调确认：3 个方法实际执行，2 个普通方法成功，busy 方法的 publish / validate 两个子场景都在子进程总计 12 秒处 TimeoutExpired。原失败保留于 [原字节监听收据](../../output/quality-20261108/continuation/regression/v4-sqlite-result-observation/receipt.json) 和同目录完整日志。原 140 组合 EOF 后也确认了完全相同的两个错误事件。

仪表化原字符串另行保留了阶段数据，不覆盖上述失败。旧库准备分别耗时 14.25 秒和 14.015 秒，已经超过整个子进程的 12 秒限额，尚未进入被测 SQL。publish 的请求线程在启动后 5 秒先结束，实际 busy SQL 到子进程相对时间 32.531 秒才进入；诊断使用正常停止文件协议收尾，33.0 秒捕获中断，无新发布、无 pending、零连接、旧库字节不变。该收尾不是原测试通过。validate 的原自动请求于相对时间 14.078 秒写入 stop，14.578 秒捕获中断，实际停止约 0.5 秒。详见 [阶段诊断](../../output/quality-20261108/continuation/regression/v4-sqlite-fixture-diagnostic/receipt.json)；没有强杀子进程或修改被测生产代码。

协调者授权在新 `continuation-sqlite-test-candidate` 中只改 `tests/test_sqlite_scan_stop.py`：总观察有界 180 秒；请求等待真实 SQL 入口，并在操作结束后停止等待；必须真实写入 stop、捕获中断且延迟非负。原 `<5 秒` 阈值保持，时钟改为真实 stop 写入调用开始到捕获中断，包含写入成本，原总操作时间仍单独保留。源码已证实 SQL 未进入、正常提前完成、未发出停止或未捕获中断都不能通过；旧库、无新发布、无 pending、零连接与子进程退出断言保留。

单模块 3 方法与 2 个 busy 子例均有明确 SUCCESS 回调（45.585 秒）；另 8 项未改的任务恢复邻居通过（30.795 秒），均无跳过，651 文件前后和原冻结 v4 均不变。该测试修复不改变静态引擎 `63a5cff7...`，不把原组合或原完整套件改写为全过。证据与精确字节为 [patch-receipt.json](../../output/quality-20261108/continuation/regression/sqlite-test-candidate/patch-receipt.json)、[精确 patch](../../output/quality-20261108/continuation/regression/sqlite-test-candidate/sqlite-stop-phase-clock.patch)、同目录两个独立回归日志；原文件 SHA-256 `96c1df15...`，候选 `1707971a...`。原完整套件现已 EOF 且源 hash 验证完成，后续精确字节合入由协调者确认。

## 主区 V6 有界 smoke 与 Git 版本差异

协调者实际落地主区 V6 后，另在主工作区运行 8 个相关模块，而非再次运行 1646 全套。父进程及实际执行子进程均核对静态引擎 `65c0fb3dbc29bda7ad74aeeadeb4666c6b1eeda545bc9521c3961f476eca7682`，ecra / workflow / 所有测试模块都从 `H:/global_static_concurrency_design` 导入。环境是实际 Windows、Admin=True、host Python 3.10.11 64bit；这项记录不代替便携 Python 的验证。TEMP、用户配置和数据根均在新隔离目录，两个 live 模型 opt-in 为 0，控制器总观察上限 900 秒。

| 模块 | 实际方法数 | 原结果 |
|---|---:|---|
| context_evidence_collision | 13 | 通过 |
| function_alias_entries | 13 | 通过，包括实际 ARM GCC 编译/链接正反例 |
| exception_masks | 7 | 通过 |
| nested_container_projection | 7 | 通过 |
| sqlite_scan_stop | 3 | 通过，含两个实际 busy SQL 子例 |
| async_jobs | 3 | 通过 |
| readonly_git_admission | 12 | 10 通过，1 FAIL、1 ERROR |
| input_watch_identity | 7 | 实际 Windows 目录身份、通知、回滚检查通过 |

实际终态 `Ran 65 tests in 191.376s / FAILED (failures=1, errors=1)`，退出 1、0 跳过；明确有 63 个成功方法回调和 76 个成功子例。651 个 ecra/config/tests/scripts/studio 及关键入口文件前后完全相同，结束引擎仍为 `65c0fb3...`。没有改源码/测试或覆盖原失败，完整 [收据](../../output/quality-20261108/continuation/regression/main-v6-smoke/receipt.json)、[日志](../../output/quality-20261108/continuation/regression/main-v6-smoke/unittest.log)、同目录 `test-events.json` / `discovery.json` / 前后 hash 保留。

两个失败均为只改文件 stat 的兼容性问题：`changes()` 将字节不变的 stable.c 错列为修改；`check_isolated_tree()` 将 stat-only 副本误拒绝为源码污染。它们不能通过更换预期或修改调用者 index 消除。新隔离对照实测 host PATH Git 为 `D:/git/Git/cmd/git.exe`，版本 2.37.2.windows.2；已接受 V4 包的 MinGit 为 2.56.0.windows.3。原 smoke 没有保存 PATH 即时字符串，旧独立 19 项日志也没有保存完整 argv/env；当前 PATH 和按 smoke 控制器重建的环境属于**新执行证据**，不冒称恢复历史环境。

新实验在相同四个 fixture（pure-stat、真实 staged/dirty、真实重命名、真实删除）上对两种 Git、原环境/禁 system-global 环境，共记录 16 行。所有 stable 的 HEAD blob 都与工作字节相同，所有原 index 字节保持，完整 patch 都没有 stable；旧 2.37 的 raw `--exit-code --name-status` / `--name-only` 仍包含 stat-only 项，新 2.56 正确省略。禁用 system/global 后行为分叉不变。安全配置仅查询白名单及来源，未读取或保存凭据；精确当前 PATH、实际 executable hash/version、配置来源、原 stdout/hex/退出码在 [环境诊断收据](../../output/quality-20261108/continuation/regression/main-v6-smoke/git-environment-diagnostic/receipt.json) 及同目录记录。

应分析负责人的请求，另在同样 16 行保存 `diff --numstat -z --find-renames HEAD --`：两版均正确不含 stat-only 项，真实 mixed/rename/delete 保留，退出 0、原 index 不变。真实零行数重命名仍为 `0\t0\t\0value.h\0renamed header.h\0`，不能按行数非零过滤。证据见 [numstat-matrix.json](../../output/quality-20261108/continuation/regression/main-v6-smoke/git-environment-diagnostic/numstat-matrix.json)。这只是修复依据；生产修复与最终后继回归由协调者及分析负责人收敛，本组原 65 仍保留失败。

### Q207 最终候选的独立复核

在分析负责人独立 `q207-v3-candidate-source` 上执行最终字节 `git_diff.py` SHA-256 `216c6aa53dcfd8d5d21aa7d6fc23db12be12c8ed8b95ba8507c72c0a0df9cee0`，静态引擎 `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`。127 个生产 Python 文件前后及最后冻结核对保持一致。相对冻结 V6，唯一生产 Python 差量是 git_diff.py；新增/变化函数仅 `_content_changes`、`changes`、`check_isolated_tree`、`prepare_base`，其余顶层 AST 完全相同，analysis/protection 等分类代码字节不变。

独立实际执行 32 行产品用例：原四个原因场景 × 两 Git × 两配置模式为 16 行；binary、empty add/delete、纯 mode commit 差异、空格/中文路径、textconv、external diff 共八个边界 × 两 Git 再 16 行。另以原主失败测试文件的原字节 `aa585d6f...`，将原两个 FAIL/ERROR 方法在两 Git 各跑一次，均通过；这是 2 个方法的 4 次执行。8 个真实 invalid-ref 技术错误均明确拒绝，所有 12 个物理 fixture 的 index 最后再次核对不变。配置的常量 textconv / external 脚本没有执行，真实 C 源码修改保留。

源码复核确认内容与 raw 查询显式禁止 textconv/external；NUL 记录保留 binary、零行数和重命名路径对，所有真实内容路径必须被 raw 覆盖，否则报错；三处洁净判断共用内容依据。在所审范围未发现新增阻断。完整 [独立复核](../../output/quality-20261108/continuation/regression/q207-v3-independent/review.json)、[生产差量](../../output/quality-20261108/continuation/regression/q207-v3-independent/source-delta-review.json)、同目录实际四执行 JSON/日志及 `actual-git-executables.json` 可复核。控制器最初有“48 行”的描述笔误，已仅按真实 `12+4+12+4=32` 校正 metadata；原收据/控制器字节及 SHA 单独保留，没有改变结果或预期。

### 主区 V8 最终相关回归

协调者实际合入最终 V8 后，从主仓再运行新的有界回归。实际引擎前后均为 `2b9e8750...`，父/执行子进程和全部测试模块均从主仓导入；默认宿主 Git 是 `D:/git/Git/cmd/git.exe` 的 2.37.2.windows.2，SHA-256 `0908ce576b90e22d3a9764f3dcf6c8159c609f38bfecf1969b9cc74d3134ae48`。没有注入便携 Git；实际 PATH 与安全 ENV 在本次子进程启动前存入 `git-environment.json`，不再依赖历史环境推测。

原只读/内容协议/入口权限/目录身份完整组为 25 项（新增内容协议 6 项已经纳入，不再沿用旧 19 计数），另有现有 semantic impact 25 项、严格配置/旧字段迁移 2 项、实际 patch 往返/子目录/失败保留 3 项，共 55 项。UTC 2026-11-08 12:15:30 至 12:18:08 实际完成：`Ran 55 tests in 156.600s / OK`，退出 0，55 个成功方法回调、14 个成功子例，0 FAIL / ERROR / skip。没有运行长 SDK 组合或再次完整 1646。

651 个 ecra/config/tests/scripts/studio 及关键入口文件 before/after 完全相同；真实模型 opt-in 仍为 0。完整 [V8 收据](../../output/quality-20261108/continuation/regression/main-v8-git-smoke/receipt.json)、[原日志](../../output/quality-20261108/continuation/regression/main-v8-git-smoke/unittest.log)，同目录 discovery/test-events、前后 hash、preflight/postflight、Git 环境与资源记录保留。此结果闭合本次宿主 Git 回归，原 V6 的 FAIL/ERROR 仍保留；便携包、真实工程和实际 UI 的最终验收由协调者另行记录，不能把该 55 项写成最终版本全套通过。

## 相邻界面消费层：只读核对

没有重新运行被停止的原生 UI 检查，也没有将 API 成功表述为 GUI 恢复通过。证据为 [consumer-recovery-readonly.json](../../output/quality-20261108/continuation/regression/server-candidate/consumer-recovery-readonly.json) 和现有 `App.vue` / `HistoryCenter.vue`。

- 首行坏归档会被当前 `refresh()` 默认选中，summary 请求失败后为 null。`run()` 的 finally 会解除 busy；bootstrap 已先赋值，主导航始终存在，历史页只依赖 bootstrap，不依赖 summary。
- 历史页的坏项 `can_open:false`、有效示例 `can_open:true` 已由实际接口确认。按现有 `openScan()` 调用顺序，切换有效 ID 后 summary、优先项、完整列表、profiles 请求均为 200，源码保留恢复路径。是否在实际窗口中容易找到并操作此入口，仍未验证。
- **Q108 相邻风险，待协调者处理**：summary 为 null 时，概览“查看全部变量”入口仍可启用；`drillResult()`、列表及工作区只检查 scan。实际坏归档的列表和五个详情接口均为 200，`systicks.ai_answer_count=1`；`loadSelection()` 会切到 AI 页签，而模板直接读取 `summary.result_revision`。这是确定的 null 解引用前提，可能使错误后的直接查看流程再次失败。未实际观察页面崩溃，不把代码推理当作视觉证据；没有修改主 UI。

控制器首次启动的外部传输夹具从固件目录运行，因缺少显式 PYTHONPATH 无法导入测试辅助模块；保留 `fault-controller.log` 和 `receipt-controller-first-failure.json`。仅修复 output 下控制器的环境后，沿产品实际保存的技术失败队列正常重试，没有手工改账本或调整预期。

恢复检查首次错误地要求“导入库物理文件 hash = 原活库物理 hash”。现有导出明确使用 SQLite online backup，新文件头及页布局不承诺与活库逐字节相同，因此这不是产品数据丢失。原失败检查完整保留；补充按现有包合同独立核对了包清单 hash、导入文件字节、原/导入的 scan_id、project_id、facts_hash、report_hash、变量 fingerprint、人工 event_id 和 deep 完整性。所有核对通过，未修改已导入的数据或放宽任何逻辑证据要求。

上述故障控制器已结束；所有由它启动的 Studio 服务已关闭。真实失败仍保留在收据中，`all_checks_passed:false`，不把数据保留等同于错误体验通过。

真实磁盘空间耗尽、断电、硬件故障和不同物理机器没有在本矩阵中制造。已有异常映射测试、真实写锁及文件路径冲突各自记录，不把它们冒称真实磁盘满。

## Q107 停止桥独立只读复核

在冻结的 `H:/ECRA-quality-20261108/continuation-final-engine-v2` 上复核新增 SQLite 停止桥，没有修改候选或重复运行协调者的联合回归。在所读范围内未发现新增阻断。逐项依据和文件 SHA-256 见 [q107-readonly-review.json](../../output/quality-20261108/continuation/regression/q107-readonly-review.json)。

重点核对了连接登记与关闭的先后关系、同锁保护的移除/遍历、请求早于登记的竞争窗口、先排入 Python 中断再唤醒 SQLite 的顺序、无停止请求时原异常的保留，以及事务/完整校验/独占发布未被放宽。临时投影库没有登记，但其现有操作是固定建表与逐行投影，不是源库的大型单条完整校验；不由此声称任意存储卡顿都有严格停止时限。当前两个生产入口没有对同一连接嵌套登记；若以后增加这种用法，需要重新审查集合登记的生命周期。此结论是源码复核，不能替代协调者的实际大型库停止证据或界面验收。

本责任范围的原全套、最终 v4 相关组合、故障矩阵、候选修复和 test-only 修正均已留下独立结果。原失败没有被删去；真实模型调用未执行，真实磁盘满/断电等限制仍如上所列。最终主区合入、UI 成品和大工程整体验收以协调者的最终交付记录为准，不能把本记录合成为一次最终源码的 1646 项全过证明。
