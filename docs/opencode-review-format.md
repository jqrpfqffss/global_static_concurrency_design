# OpenCode 简单变量级复核格式

ECRA 找全访问事实，OpenCode 结合本地源码判断其含义。每个候选变量只有一个最终语义答案；无需逐 pair、逐 ID、参与者或场景作文。详细设计和本轮验证见 [设计报告](opencode_review_simple_stable_design.md)。

## 三个入口

```powershell
py -3.10 run_ecra.py
py -3.10 run_ecra.py review
py -3.10 run_ecra.py review-failed
```

完整运行执行静态扫描、复核、报告；`review` 使用经校验的扫描，强制重新复核当前全部 SUSPECT/UNKNOWN，包括已有正常答案；`review-failed` 只重试 TECH_FAILED，永不因失败次数永久放弃。无法归属具体变量的覆盖缺口继续独立保留。

## 输入

Packet 包含全部访问及其身份、成员/元素、读写种类、上下文、完整路径、保护和未知事实；不默认复制整段函数正文。`call_path_set` 对应 `call_path_sets[].id`，仅对重复路径映射无损去重。`functions`、`files_to_check` 和源码行号提供导航，完整静态冲突、CFG 与构建事实仍可按 `facts_path/static_report_path/project_evidence_path` 读取。

OpenCode 按声明 → 所有访问点 → 完整调用链 → 入口 → 保护 → unknowns → 直接关联源码检查；需要时继续核查 NVIC、DMA、同步和别名，不无理由遍历全仓。工程补充声明从 semantics.yaml 旁的 review_context.md 读取，并须经源码核实。

## 输出

```json
{
  "finding_id": "原样返回",
  "status": "CONFIRMED",
  "reason": "结论与依据",
  "interleaving": "主要交错，或无法形成危险交错的原因",
  "protection": "保护机制、覆盖范围和有效性",
  "impact": "源码支持的影响",
  "evidence": [{"file": "src/a.c", "line": 123, "claim": "该位置支持的事实"}],
  "fix": "修复建议",
  "verification": "验证建议",
  "missing_context": []
}
```

| status | 含义与必要依据 |
|---|---|
| CONFIRMED | 源码及执行关系证明实际风险；至少一处有效源码 evidence |
| LIKELY | 较强的现存风险证据，少量运行条件未定；明确 missing_context |
| REVIEWED_SAFE | 完整证据证明不冲突或完整保护有效；至少一处有效源码 evidence |
| FALSE_POSITIVE | 不可达、不同存储、上下文互斥或访问不存在等证伪；源码 evidence |
| NEED_MORE_CONTEXT | 已分析源码但缺决定性事实；明确 missing_context，禁止猜测 |

五者全部为 `review_state=DONE`。执行状态只有 PENDING、DONE、TECH_FAILED；`state/status` 为既有报告兼容字段，与 `review_state/review_status` 一致。NEED_MORE_CONTEXT 不计为技术失败，也不表示安全。

## 最小校验与格式恢复

硬校验：finding_id 相同、合法 status、非空 reason、evidence 为列表；每条证据的文件在工程内且存在、整数行号有效；上述三种明确结论至少一处 evidence；两种不确定结论至少一个非空 missing_context。无字数限制，不要求 quote、schema_version 或结构化解释。

Parser 支持整体 JSON、fenced JSON、前后解释、JSONL 和最后一个与 finding_id 匹配的完整对象。输出格式错误最多进行两次 FORMAT_FIX，只传原始分析文字、当前错误、简单格式、finding_id 和枚举。格式会话没有工具权限、不附 Packet、不延续源码分析会话，不得增添事实或改变原结论。两次后仍无有效结果才为 TECH_FAILED；provider 错误、退出异常、启动失败、timeout 直接按技术失败/有限技术重试处理。

## 归档与展示

每次执行保存不可覆盖的时间戳 Packet、Prompt、stdout、stderr、解析答案、模型、时间及 SHA-256；格式修正的原始分析也校验。稳定文件名仅为最新输入副本，收据引用时间戳原件。历史失败不阻碍以后重新复核；旧结论进入历史，当前答案只来自本轮有效日志。

index.html 保持变量级清单和中文栏目；简单字段直接映射为原因、时序、保护、影响、证据、修复、验证和缺失事实。旧 v2 解释仅为历史展示兼容，不再进入新答案的硬校验。源码/扫描指纹变化仍使旧答案失效，要求重新扫描。

`max_items` 控制每批大小，命令自动处理完所有目标；`workers` 为 1–8。旧 `audit_verdicts` 配置可删除，当前流程不执行额外反证轮。
