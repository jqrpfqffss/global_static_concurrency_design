# 完整证据不变后的人工确认继承

优先级按[87号执行顺序](87-functional-priority-execution.md)。实现复用 `reviews.db` 的不可变事件和 `prior_decisions`，没有修改分析算法、覆盖、静态分类或旧事件。

## 实现与边界

- 相同canonical ID只是必要条件。旧报告的有序Merkle根见证将 `report.fingerprint` 绑定到原报告摘要，再核对当前完整输入fingerprint、完整facts根和原人工事件fingerprint。完整输入fingerprint沿用扫描器已有合同，覆盖有效配置、引擎、宏/预处理、实际输入和编译参数。任何变化或缺证明都要求重新确认，不根据名称、局部摘要或时间猜测安全。
- 原事件始终保留原扫描身份、确认者声明、时间和依据；当前事件列表不会凭空新增SAFE。界面沿用已有人工历史/固定操作区域显示来源，不新增导航或改变设计体系。
- 新的可选 `evidence_parents` 记录显式重新确认/撤销所确认过的旧来源。撤销后再次扫描不能复活旧SAFE；再次显式确认可作为后续来源。并行分支保留为冲突，要求填写依据并显式解决，不按时间覆盖。校验跨扫描前驱存在性、对象/指纹和无环性。
- 列表统计、筛选和详情使用相同继承验证。完整结果包与人工增量包均携带原始历史及见证，导入端重新计算；增量即使没有本轮事件也能传播沿用的来源。旧无证明包继续可读，但不自动继承。含新可选事件字段的包需要支持此合同的新软件，旧软件会拒绝未知事件字段。
- 同一来源扫描出现不同历史快照时仍拒绝覆盖既有 `prior_decisions`。两份原数据保留；第一版不自动拼接来源载荷。不同来源的并行确认已支持显式冲突解决。
- 采用保守的全扫描输入及事实相等要求：升级引擎、其他文件变化或缺证明可能要求重新确认。这不是“本变量未变就自动沿用”的宽松规则。

## 实际验证

| 范围 | 结果 | 证据 |
|---|---|---|
| 人工事件/独立包/继承专项及完整真实单TU扫描套件 | 31 PASS，108.387s | `tests/test_review_inheritance.py`、`tests/test_human_reviews.py`、`tests/test_report_package.py`、`tests/test_canonical_scan.py`；后补零本轮事件增量及因果环反例另行专项验证 |
| 增量同时携带旧来源、零本轮事件沿用增量、因果环拒绝及原人工/包回归 | 最终23 PASS，15.220s | `py -3.10 -B -X utf8 -m unittest tests.test_review_inheritance tests.test_human_reviews tests.test_report_package -q` |
| 获准STM32F030真实4TU重复扫描 | 两次完整facts根一致，自动沿用；原源码/原事件不改 | 下列实际Chrome收据及其 `fixture_origin`；真实事实根 `514fa4543569ada226992813ef3b63164d99032f505e7b01e7919e29126e4c48` |
| 实际Chrome 1366×768 | 来源/零本轮事件、撤销、刷新、独立完整包及增量幂等 PASS；无页面错误/外部请求 | [收据](acceptance/review-inheritance-f030-v6.json)、[沿用](ui/screenshots/review-inheritance-v6/01-inherited-source.png)、[撤销后](ui/screenshots/review-inheritance-v6/02-undo-reloaded.png) |
| 前端类型检查与离线资产构建 | PASS | `cd studio; npm run build`，Vue/TypeScript/Vite实际构建 |

实际Chrome重验复用此前已完成的两次F030原生扫描的独立副本，收据明确记录 `fixture_origin`，没有冒充新的原生扫描。早期脚本分别因旧占位符、选中旧扫描、待确认默认筛选、中文标签和刷新后未重新选择对象而失败；旧失败收据均保留在私有工作目录，没有改写为成功。最终v6实际通过全流程。

复现：`py -3.10 -B -X utf8 scripts/validate_review_inheritance_ui.py --config <获准F030配置> --work <新的独立空路径>`；可选 `--reuse-fixture <先前实际两次原生扫描目录>` 仅重验界面。禁止指定未授权固件。自动化确认声明只用于功能验收，不是固件安全或硬件复现结论。

前一阶段冻结源码5c4281b的完整回归现已实际结束：1459总项、1457 PASS、2联网opt-in SKIP、2309.861s，全部3688冻结源/测试副本SHA不变，详见[独立收据](acceptance/full-regression-studio-v42-final.json)。这不是本次新增功能的完整回归，也不是新Portable验收。

此项的上述功能范围通过；整套搬迁、正式未提交输入的构建/恢复、最后的完整消费者省内存及原H/G总门禁仍未关闭。其他G2工程按用户要求待验；物理第二台PC、真实原生DPI、干净离线机和工程师UAT均NOT_VERIFIED，不宣称完整重构完成。
