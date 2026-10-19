# 一句话结论、完整分析与摘要修复

## 数据链路与根因

本次以 `optimize_cc` 工作区实际源码为准。以下“原实现”指本次修改之前的版本。用户给出的 `g_mfcInterface.msgSp`、260 字符及末尾 `PDI_Outpu` 是故障样本描述；它精确匹配原实现的展示切片，不能据此断言原始 OpenCode 响应已被模型截断。测试使用同类长调用链和旧值写回分析验证无损展示，不冒充该工程的真实模型结论。

| 层级/源码位置 | 原因与影响 | 本次处理 |
|---|---|---|
| `html_report.py:reviewed_variable_summary` | `[:260]` 对历史 summary 或回退 reason 硬切片；有效归档不变，变量清单显示残句 | 删除切片，统一字段选择并无损展示 |
| `html_report.py` 候选卡片 `review-brief` | `reason[:240]` 会丢失卡片后半段文字，且不表示内容已省略；全文原来可在复核页另查 | 优先显示独立 summary；完整 reason 提供展开入口；无摘要时展示完整 reason |
| `review_contract.py:validate_minimal_answer` | 原最小协议仅约束身份、状态、reason、evidence 和必要缺项；长 reason 合法，没有 summary 质量门槛 | 结构校验继续保护完整分析；新增独立、可测试的 `review_summary.py` 质量门槛 |
| `review.py` 修复触发 | FORMAT_FIX 在 JSON/结构异常时发生；260 字符截断在后续渲染层，未发生解析异常，因而不可能生成对应修复调用日志 | 将展示修复与输出修复分开；真实摘要异常才进入 SUMMARY_FIX |
| `review.py:review_answer_text/parse_answer_object` | JSONL 文本片段之间插入换行；若恰好在标识符或 JSON 字符串中分片，改变原文或使 JSON 失效；完整对象后跟同项残缺回答时也可能回退到旧对象 | 保持片段原样拼接；原始 JSONL 永久保留；选取最后匹配对象，发现其后还有同 finding_id 残缺回答则拒绝回退、进入格式修复 |
| `review.py` FORMAT_FIX 循环 | 进一步格式修复仍可能使用初次回答而非最近一次格式输出 | 后续格式修复使用当前最新完整输出；禁止格式阶段改变已有风险判断 |
| 历史 v2 与简化协议 | HTML 清单原先优先 explanation.summary，简化协议则用完整 reason 冒充短摘要；简化复核页没有独立摘要区 | 顶层 summary 优先；无顶层字段才读取 v2 summary；修复只添加/替换顶层 summary，不覆盖历史字段或 reason；两种报告一致 |
| 缓存/收据 | 原缓存只执行结构和语言校验，无法发现摘要异常；修复后只比最终输出也不足以核对多阶段修改边界 | 策略及新模块进入缓存指纹；命中缓存仍重验；仅改变摘要策略时复用已验证分析、必要时只修摘要；分别重放 LANGUAGE_ONLY 和 SUMMARY_ONLY 来源、哈希、字段一致性及质量门槛 |
| `review_integrity.py`、queue/result | 原归档状态一致性不包含摘要门槛 | 新收据包含摘要策略与校验状态；DONE 在归档和展示归一化时均再次校验；queue/result/本轮答案须一致 |
| HTML/CSS/JavaScript、Markdown | 本次检查未发现正文 `text-overflow/line-clamp/ellipsis` 隐藏；分页、折叠及模板延迟展开属于完整内容导航；其它访问/规则预览已有全文展开 | 保持完整正文、转义、换行及展开能力；重新生成报告不会重新引入长度切片 |

处理顺序：原始 stdout JSONL → 无损文本提取 → JSON/结构及既有语义证据门槛 → 分析正文 LANGUAGE_FIX（需要时）→ 独立摘要质量门槛 → SUMMARY_FIX（需要时）→ 收据/queue.json/逐项 result.json → JSON、HTML、Markdown → index.html。不从报告页面反向修改模型归档。

`_provider_error_message` 对错误诊断文本保留既有 1000 字符预览；它不处理 reason/summary，原始 stdout/stderr 仍完整保存。源码窗口、规则样例和热点列表的分页/抽样也不参与摘要生成。

## 配置

```yaml
review:
  enabled: true
  summary:
    enabled: true
    max_chars: 120
    fix_retries: 2
```

| 参数 | 默认值 | 合法值与行为 |
|---|---|---|
| `enabled` | `true` | 仅布尔值；关闭时不要求或修复独立摘要，reason、证据及完整解释不变 |
| `max_chars` | `120` | 整数 1–10000；含变量名、标点及空格；超长必须重新表述，不做切片 |
| `fix_retries` | `2` | 整数 0–10；0 表示只校验、不修复；失败明确标为技术失败 |

遗漏整个 summary 节点或其中字段时补默认值。`null`、列表、字符串数字、浮点数、把布尔值当整数、非法边界及未知字段都报错，关闭摘要时也检查配置合法性。加载配置只合并内存默认值，不重写用户文件；Python 普通/CMake 模板和中央配置均支持此节点，既有工程路径、命令、模型和构建设置保持用户值。

“字符”具体指 Python `len(str)` 的 Unicode 码点：中文、ASCII 字母、空格和标点通常各计 1；emoji、组合附加符及连接序列可能包含多个码点。模型 token 是分词单位，中文或标识符的 token 数不与码点一一对应；本配置不是模型输出 token 上限。即使变量名本身很长，也不能截断标识符；长度无法满足时应增大配置或关闭独立摘要，程序会报告失败。

## 协议与质量边界

`summary` 面向快速阅读，完整 reason 保存调用链、读写关系、并发窗口、保护依据、影响及不确定性；完整解释不受摘要上限影响。status/evidence/interleaving/protection/impact/fix/verification 等字段语义不变。

摘要按 status 使用以下开头加全角冒号：CONFIRMED → 已确认并发风险；LIKELY → 疑似并发风险；REVIEWED_SAFE → 已验证当前条件下安全；FALSE_POSITIVE → 已确认静态误报；NEED_MORE_CONTEXT → 证据不足，暂无法判断。随后必须保留变量名及技术原因或关键缺失条件；不能把疑似风险简化成确认风险。

程序检查字段类型/空值、码点长度、括号/引号配对、中文句尾、明显连接词/标识符/调用链残段、过多调用链、单句要求、英文正文、部分明确繁体表达、变量名、判定开头及可检测的明确反向结论。完整中文句子允许以分析正文中已经出现的完整标识符或函数名结束；不能仅因最后一个词是代码名称就判截断，未见于完整分析的标识符残段仍会拒绝。标点完整、符号完整、通过关键词检查或通过 SUMMARY_FIX，都不证明全部事实、语法和语义正确。程序不能穷尽中英文混写、繁简差异、同义改写和自然语言矛盾，也不能独立证明摘要中的每个技术事实；保留完整 reason/evidence 供核查，原分析的关键未知不得删除。明显相反结论无法在不改变分析的情况下修好时记录失败，不能靠摘要修复擅自改变 status。

旧归档仍可按完整原文生成报告；无顶层 summary 才回退 explanation.summary，再回退完整 reason。此回退只解决历史/关闭摘要的阅读，不声称生成了经过质量验证的新摘要。新复核与缓存命中必须遵循当前策略；报告生成本身不偷偷调用模型。

## 独立修复及日志

SUMMARY_FIX 使用已有完整有效复核回答，明确错误和字符上限，优先要求只返回 `{"summary":"修复后的结论"}` 补丁，由程序合并原始有效分析；模型不需要重抄 reason/status/evidence。不传 Packet、不延续源码会话，权限为 `{"*":"deny"}`；长输入经 stdin 原样传入，Prompt 文件永久保存。补丁只允许 summary 一个键，带其它字段的部分对象会拒绝；兼容返回完整 JSON 的旧提供商，但必须严格比较所有非 summary 字段（含值类型、列表顺序、嵌套历史字段），不接受任何重写 reason、status 或证据的回答。提示词明确逐码点计数并预留长度余量，可以整体省略非关键函数名，不能将其切成片段。通过质量门槛才替换当前答案。

执行异常按 `review.retries` 做技术重试；摘要重写按 `summary.fix_retries` 计数。修复响应 JSON 无效才进入最多两次 FORMAT_FIX；它仍须通过原始有效回答的非摘要一致性检查。正文英文进入 LANGUAGE_FIX，摘要英文归 SUMMARY_FIX；既有旧值写回安全挑战和 NVIC 事实挑战仍负责事实复核。不能把摘要故障标为 NEED_MORE_CONTEXT，不能静默归档残缺摘要；失败保留所有原始流和历史，`review-failed` 可重试。

逐项 `*.result.json` 和 `queue.json` 的 attempts 保存每一次实际调用：finding_id、stage、trigger_reason、before_summary/after_summary、max_chars、before_chars/after_chars、summary_attempt、technical_retry、model、实际 command 数组、input_method、prompt/stdout/stderr 文件及 SHA-256、started/finished、state、validation_result/validation_error。无法解析或未执行成功时，after_summary/after_chars 为 null，明确保存错误；不伪造修复后文本。model 未显式指定时记录使用 OpenCode 默认配置，不冒称已知提供商实际选用的模型 ID。

`summary_correction` 绑定原始有效复核 stdout、SHA-256 和答案摘要，`response_format` 区分 SUMMARY_PATCH/FULL_ANSWER；`summary_validation` 保存策略、变量名、校验范围及状态。收据验证会从原始有效回答和最终响应补丁重新构造完整 answer，复核质量与字段一致性，不能仅凭内存合并值认定有效。HTML 的“原始证据、执行日志与历史复核”展示全部实际调用和文件链接；Markdown 同样附 SUMMARY_FIX/相关 FORMAT_FIX 记录。原回答与补丁分别保留在不可覆盖日志中；摘要修复之后不会再改写其他字段。

## 验证

自动测试入口：`py -3.10 -m pytest tests/test_review_summary.py -q`。覆盖配置缺省与非法类型/边界、五种状态、Unicode 长度、残缺函数/括号/引号/连接词、调用链堆积、语言与明确矛盾、v2 兼容、字段不可变、禁用、0 次修复、配置变更和缓存、技术重试、FORMAT_FIX、语言后摘要修复、日志可追溯、收据篡改、queue/result 一致性以及长 reason 无损展示。

完整回归使用 `py -3.10 -m pytest tests -q`；真实模型测试保留项目既有环境变量开关，模拟响应验证的是程序行为，不代表模型语义质量已验证，也不表示已在真实固件硬件上复现。

2026-10-19 本次验证：全量 **711 passed、2 skipped、214 subtests passed**（215.32 秒），跳过项为需显式启用的真实 OpenCode 模型测试。摘要专项 **19 passed、45 subtests passed**，含实际 Python 子进程模拟 CLI 的长中文 stdin、权限、日志和收据校验；最终解析/展示相关定向回归 **41 passed、81 subtests passed**。`compileall` 与 `git diff --check` 通过。JUnit 结果保存于工作区 `output/summary_fix_regression.xml`。

真实测试可在当前 PowerShell 会话启用；模型和超时只作用于测试，不改写中央工程配置：

```powershell
$env:ECRA_DEEP_REVIEW_LIVE = '1'
$env:ECRA_STALE_WRITEBACK_LIVE = '1'
$env:ECRA_DEEP_REVIEW_MODEL = 'deepseek/deepseek-flash' # 换成已配置的 provider/model
$env:ECRA_STALE_WRITEBACK_MODEL = $env:ECRA_DEEP_REVIEW_MODEL
$env:ECRA_REVIEW_LIVE_TIMEOUT = '300'
$env:ECRA_DEEP_REVIEW_ARCHIVE = "$PWD/output/live-review/deep"
$env:ECRA_STALE_WRITEBACK_ARCHIVE = "$PWD/output/live-review/stale"
$env:PYTHONUTF8 = '1'
py -3.10 -m pytest tests/test_deep_review.py::DeepReviewTests::test_live_six_cases tests/test_stale_writeback.py::StaleWritebackTests::test_live_opencode_reviews_new_fixtures -q -s
```

两组共包含 6 个深度复核用例及 3 个旧值写回风险/安全对照。第一个深度用例还会对真实有效回答收紧摘要上限，检查只执行 SUMMARY_FIX、复用分析且不改变任何非摘要字段。两组均永久归档每项的输入、实际调用、原始响应、收据及源码副本，并通过 `verify_receipt` 验证；不会因临时测试工程清理而丢失日志。

2026-10-19 后续已启用真实测试，显式使用 OpenCode `1.18.35` / `deepseek/deepseek-flash`。最终轮 **2 组测试、9 个真实用例全部通过，0 跳过**，实际调用 OpenCode **10 次**；结果为 4 个 CONFIRMED、3 个 REVIEWED_SAFE、2 个 NEED_MORE_CONTEXT，均符合各用例允许的判定。真实 SUMMARY_FIX 使用单字段补丁将摘要 **79 → 48 字符**（上限 60），没有工具调用，所有非摘要字段保持一致。9 份收据、18 份归档源码/引用文件均再次通过离线校验。常规回归更新为 **714 passed、223 subtests passed**，其中两个 opt-in 项由上述真实测试单独运行。

真实测试同时发现并修正了完整句以 `g_mixed` 等标识符结尾的误判；对模型重抄完整 JSON 时把 reason 中“为”改成“是”的返回值，程序按不可变字段约束拒绝，现优先请求 summary 单字段补丁。安全/证据不足分支的案例正文阅读要求也已明确。初始失败轮及修复后的最终轮均保留原始日志，没有覆盖或手工修改模型回答。

最终报告与逐项日志入口：工作区 `output/live_review_20261019_r3/README.md`、`validation.json`、`junit.xml`、`regression.xml`；前两轮诊断数据保留在 `output/live_review_20261019` 和 `output/live_review_20261019_r2`。上述 PowerShell 开关只作用于当前会话，项目正常回归仍保留显式启用真实模型测试的方式。
