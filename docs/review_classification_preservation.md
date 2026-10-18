# 静态风险与 OpenCode 复核的合并修复

验证日期：2026-10-18。代码基线：`51c1771`，分支 `optimize_cc`。

## 根因与数据流

静态分析在 `analysis.analyze()` 中把分类分别保存到 variable 与 finding 的
`static_classification`。原有复核流程没有把这个字段改成 UNKNOWN；回归发生在后续解释层：

1. `decision()` 对普通 PENDING、RUNNING、TECH_FAILED、FAILED、STALE 提前返回
   unresolved；关闭复核时则靠错误文字中的“自动复核已关闭”绕过该分支。同一静态结果因开关改变分类。
2. 变量聚合把 unresolved 放在 likely 前面，使一个证据不足项掩盖同变量的有效疑似风险。
3. `reviewed_variable_summary()` 优先用失败、待复核等运行状态充当变量结论。
4. OpenCode 页面用原始 `category(record)` 分组，首页与 risk_summary 用
   `decision(finding, record)`；NEED_MORE_CONTEXT 的原始分组是 unresolved，
   但原单 finding 的静态 SUSPECT 回退已经是 likely。两页因此互相矛盾。
5. 无 finding 的 SUSPECT/UNKNOWN 曾落入 inventory；解析失败分支也可能遮蔽明确复核结论。

修复后的数据流：

```text
analysis → variable/finding.static_classification（保持原值）
         → queue / packet / receipt（携带静态分类）
         → 原始 review state/status（保留语义与执行结果）
         → decisions.effective_decision（单 finding 合并）
         → decisions.variable_decisions（变量聚合）
         → risk_summary / HTML / JSON / Markdown
```

## 合并规则

有效 DONE + CONFIRMED/LIKELY/REVIEWED_SAFE/FALSE_POSITIVE 分别得到
confirmed/likely/safe/safe。其他情况回退到静态分类：SUSPECT 为 likely，
UNKNOWN 为 unresolved。没有复核记录也使用同一规则。

同变量的聚合顺序是 `confirmed > likely > unresolved > safe`，与 finding 顺序无关。
REVIEWED_SAFE 与 FALSE_POSITIVE 的原始区别保留，并在变量标签中分别显示。
真正 UNKNOWN 不会因为携带并发规则名就自动升级；旧版缺少静态字段的 finding
先使用变量的静态字段，最后才回退到已有规则证据。

`review_category()` 只描述 OpenCode 原始结果，供进度、覆盖完整性和原始解释使用。
review_summary 的 unresolved 因此仍可以包含复核未完成或证据不足项；它不是变量风险计数。
最终变量计数统一读取 risk_summary。OpenCode Prompt、五种语义状态及校验标准保持原样。

报告新增的 `effective_decision` / `decision_label` 属于派生数据；清理静态报告和
构建再次复核的 Packet 时移除，防止污染模型输入、扫描指纹和跨进程缓存。

## 真实固件的同输入对比

读取当前配置所指固件已经保存的 facts 与 queue；不重新构建固件，不执行真实 OpenCode。
静态分析共有 23 个 SUSPECT、26 个 SAFE_PROVEN；容器不进入变量风险分母。
下面的状态替换只用于验证分类器，不代表真实模型曾返回这些结果。

| 同一份静态输入的复核状态 | 修复前 likely / unresolved | 修复后 likely / unresolved |
|---|---:|---:|
| enabled=false | 23 / 0 | 23 / 0 |
| enabled=true + PENDING | 0 / 23 | 23 / 0 |
| enabled=true + RUNNING | 0 / 23 | 23 / 0 |
| enabled=true + NEED_MORE_CONTEXT | 23 / 0 | 23 / 0 |
| enabled=true + TECH_FAILED | 0 / 23 | 23 / 0 |
| enabled=true + STALE | 0 / 23 | 23 / 0 |
| 实际保存队列：22 PENDING + 1 REVIEWED_SAFE | 0 / 22 | 22 / 0 |

最后一行另有 1 个已复核安全变量，修复前后均保留。
唯一离开 SUSPECT 风险分类的是 `huart2.Instance`，对应显式 REVIEWED_SAFE；
其保存的原始日志、答案和源码引用经 `verify_receipt()` 校验通过。
因此 23 = 22 个仍疑似 + 1 个明确复核安全，没有变量仅因复核不确定而变成 UNKNOWN。

NEED_MORE_CONTEXT 行的单 finding 数量在旧代码中本来就没有变化；修复针对它的
变量聚合、摘要和复核页归类不一致，不能把这个原有行为误报成此次新增。

## 文件与验证范围

- `ecra/decisions.py`：统一单项合并、变量聚合、分类标签与优先级。
- `ecra/html_report.py`：统一首页、清单、详情和复核页；分开最终分类与原始复核状态。
- `ecra/report.py`：输出派生分类、统一风险统计和 Markdown；保留静态与原始复核字段。
- `ecra/review.py`：队列各阶段保留静态分类，复核输入排除派生报告字段。
- `ecra/workflow.py`：初始队列保留静态分类，扫描指纹排除派生字段。
- `ecra/review_integrity.py`：发现复核记录与原始静态分类不一致时报告完整性错误。
- `tests/test_effective_decisions.py`：全状态矩阵、不修改输入、多 finding 顺序、真实
  Clang 扫描、队列/Packet/收据、开关一致性及各报告格式一致性。
- `tests/test_html_report.py`、`tests/test_scope_cmake.py`：把旧版降级预期改为本次要求，
  保留失效答案不得作为当前证据或生成修复建议的断言。

新增用例覆盖用户要求的十个场景，并额外检查无复核记录、RUNNING、STALE、旧 FAILED、
变量字段回退、解析失败、复核副本被修改、再次复核输入与跨进程缓存。

最终执行 `python -m unittest discover -s tests -v`：**621 项测试全部通过**，
耗时 201.316 秒。新增测试文件含 10 个测试方法，状态矩阵和顺序排列使用子用例展开。
另执行 `git diff --check`，未发现空白错误。未删除原有测试或放松失效证据校验。

本地验证产物：

- `output/review-classification-full-tests.log`：完整测试日志。
- `output/review-classification-comparison.json`：基线与修复后逐状态统计、唯一离开疑似的变量及收据校验结果。
- `output/review-classification-preview/index.html`：真实固件已保存事实的修复后预览；
  同目录含 JSON、Markdown、SQLite 和当前收据引用的输入与日志。

预览的 HTML 行、变量详情、JSON 与原始复核状态已交叉校验：22 个 likely、1 个 safe，
另有 26 个静态安全对象。原固件目录中的扫描事实、报告和队列没有被覆盖。

## 边界

在当前合并链路中，SUSPECT 遇到证据不足、待复核或技术失败都会回退为 likely。
安全和误报仍需有效 DONE 语义结论；过期答案不会用来证明安全。
完整性检查和运行状态可以保持 INCOMPLETE，这表示流程/覆盖未完成，并不降低变量风险。
补充声明和未参与构建的对象继续遵守原有范围约束，不计入当前构建的风险分母。
