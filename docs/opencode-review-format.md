# OpenCode 跨项目复核格式 v2

并发候选由静态提取器发现；最终复核结论、原因、参与者、交错过程与用户解释由 **OpenCode** 生成。Codex 在本次任务中修改工具与测试，不代写项目复核答案。页面只展示当前有效回答，不生成缺失的执行步骤或推测状态。

## 迁移到其他工程

1. 按 README 注册项目，配置实际构建、排查目录、芯片/核心与必要的入口信息。需要自动执行模型复核时设置 `review.enabled: true`；需要首轮之后继续反证核对时设置 `review.audit_verdicts: true`。
2. 执行 `py -3.10 run_ecra.py run --profile <项目名>`；已扫描且源码未变时执行 `py -3.10 run_ecra.py review --profile <项目名>`。`review` 命令本身会明确启用 OpenCode，即使新项目配置原先关闭了模型。
3. 所有工程自动使用 `ecra/review_contract.py` 中的同一协议，首轮和反证轮均适用。不需要复制项目专属提示词，也不需要人工整理 OpenCode 的答案。
4. 打开工程输出目录中的 `opencode_review.html`，查看协议覆盖数、每项原始回答来源、具体执行过程及源码依据。

`--no-review` 只做静态提取，不生成 OpenCode 结论。`report` 只重新展示已经存在的回答，不会把旧文本转换成伪造的 v2 回答。旧记录显示“旧版 OpenCode”，执行 `review` 后由 OpenCode 重新输出；提示词和协议实现参与缓存键，新协议不会直接复用旧格式缓存。

## 固定字段

基础字段保持 `finding_id`、`status`、`reason`、`evidence`、`interleaving`、`protection`、`impact`、`fix`、`verification`。每份新回答还必须包含：

| 字段 | 内容 |
|---|---|
| `schema_version` | 整数 `2` |
| `review_type` | `VARIABLE` 或 `EVIDENCE_GAP`，必须匹配候选身份 |
| `explanation.summary` | 不超过 180 字的一句话结论，OpenCode 直接撰写 |
| `explanation.cause` | 具体原因，不能仅写“存在并发” |
| `explanation.scheduling` | 实际抢占、串行、跨核或硬件同时执行条件 |
| `explanation.evidence_refs` | 上述解释对应的 evidence 序号，从 1 开始 |
| `explanation.participants` | 每个入口的唯一 ID、名称、真实调用路径、读写对象、访问资格及源码依据 |
| `explanation.scenarios` | 分开的具体场景，每个含前提、逐步动作、状态变化、预期与实际结果 |
| `explanation.missing_evidence` | 缺失的具体证据列表；疑似/证据不足时不得为空 |

参与者固定包含 `id/label/eligibility/entry/access/evidence_refs`。`eligibility` 为 `ACTUAL/EXCLUDED/UNKNOWN`，一个 ID 只代表一个执行上下文。源码中的回调参数过滤、构建分支和 DMA 模式都应由 OpenCode 核对，不能把保守调用图中的所有路径都列为真实访问者。

场景固定包含 `title/kind/precondition/steps/expected/actual`。`kind` 为 `CONFLICT/BLOCKED/UNRESOLVED`。每步固定包含 `actor_id/action/state_before/state_after/evidence_refs`，列表顺序即 OpenCode 给出的执行顺序。示例初值必须注明是假设；未知值明确写未知。页面不会从自由文本、箭头、变量名或静态调用图重新构造另一条时序。

确认变量缺陷必须首先给出一个成立的冲突：至少两步、两个真实参与者，以及具体结果差异。安全/误报须展示冲突被哪个条件阻止；没有运行期访问时允许空步骤，避免为填表编造读写。未确认项不能展示为已成立冲突，独立证据缺口不计成变量缺陷。

## 校验与失败处理

新响应缺字段、编号越界、参与者 ID 不存在、用已排除入口构造冲突、状态与场景类型矛盾、引用原文不匹配时，工具拒绝完成状态，将具体错误交回 OpenCode 重试。重试耗尽保留失败记录，不代填字段，不把失败当成安全。

首轮和反证轮复用同一个协议常量与校验函数。执行回执记录协议版本、原始输出日志与提示词哈希；展示字段仍属于原始回答的一部分，手工修改会导致日志一致性校验失败。引用路径相对当前工程解析，并校验实际行号和原文；共享 SDK 等外部依赖仍按构建中的实际路径核对，不把旧工程的缓存当作新工程证据。

格式校验只保证结构、引用定位与记录一致性，不证明模型推理必然正确。反证复核负责继续核对语义。报告区分源码支持的结果、未证实的业务影响和待做的验证建议；没有板上实验就不能声称已经实测。

## 验证方式

`tests/test_review_contract.py` 和相关协议测试使用明确标记的模拟进程输出，只验证工具行为，不能作为项目风险证据。真实 OpenCode 的跨工程抽样输出、执行日志和页面保存在 `output/opencode-format-v2/`；实际完成数量和结果以其中回执为准。

2026-09-15 真实抽样验证完成：

| 工程 | 变量 | OpenCode 反证后的结论 | 输出版本 |
|---|---|---|---|
| serial - continue / STM32F103 | `pending_events` | CONFIRMED | v2 |
| serial - continue / STM32F103 | `guarded_total` | REVIEWED_SAFE | v2 |
| H747 CM7 裸机 / 双核验证工程 | `mailbox_shared` | CONFIRMED | v2 |
| H747 CM7 裸机 / 双核验证工程 | `control_shared` | REVIEWED_SAFE | v2 |

四项均实际调用 OpenCode 完成首轮和反证轮，程序核对两轮提示词包含同一协议、最终答案与原始日志一致、源码引用仍匹配当前文件。70 处最终源码引用及页面链接通过核对。过程中的模型输出与重试日志保留，未手工改写结论或解释。它们是格式与流程的真实抽样，不是重新复核两个工程的全部变量，也不是板上复现。

155 项自动化测试通过；后续 Markdown 展示和跨目录引用测试的针对性检查亦通过。浏览器已检查结构化步骤、操作前后状态、已排除参与者、源码链接和 390 像素手机布局。真实样例入口为 `output/opencode-format-v2/serial/opencode_review.html` 与 `output/opencode-format-v2/h747/opencode_review.html`，校验摘要为同目录上层的 `validation.json`。
