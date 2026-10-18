# stale write-back 最小复现与修复报告

日期：2026-10-18。

## 1. 为什么没有真实 msgSp 源码仍能复现

这是通用的 C 并发语义缺口：共享对象的旧值在调用实参求值时被读取，随后经函数参数重新写回同一存储。识别不依赖历史 `g_mfcInterface.msgSp` 源码、业务背景、setter 名称或变量名称。全部验收使用本仓库新增 fixture，未读取或修改业务工程。

修改继续采用一个变量、一个 Review Packet、一个 JSON 结论和 `PENDING / DONE / TECH_FAILED`。未恢复 Conflict Class、逐 pair 覆盖、investigation、Partition 或复杂 Repair。

## 2. 构造的 fixture

目录：`tests/fixtures/stale_writeback/`。

`fixture.h` 使用 `uint32_t` 并以 `_Static_assert` 验证其为 32 位。AST 测试另外检查自然对齐和大小。`semantics.yaml` 明确配置 `IRQ_LOW`、`IRQ_HIGH` 两个物理 IRQ 及入口，关闭按名称自动发现；风险文件的 `main` 实际设置 NVIC 分组和优先级：LOW=3、HIGH=1、priority bits=4。测试检查恢复的关系确实为 `HIGH CAN_PREEMPT LOW`，而非仅靠函数命名。

| 文件 | 场景 |
|---|---|
| `unsafe_direct_writeback.c` | LOW 调用 `SetValue(g_value)`；HIGH 调用同一 setter 写 200；实际 store 仅一处 |
| `safe_irq_protected.c` | LOW 从实参读取之前到 setter 返回之后持续关中断 |
| `safe_same_context.c` | 读旧值、写回和常量 writer 都仅在同一不可重入 IRQ 执行 |
| `different_storage.c` | 读取 `g_other`，写 `g_value` |
| `member_writeback.c` | 读取 `g_state.a`，经 Forward→SetA 写回同一成员 |
| `member_different_storage.c` | 读取 `g_state.b`，写 `g_state.a` |
| `unknown_preemption.c` | 两个真实 IRQ，但不提供优先级配置 |
| `replay.c` | 主机 C 确定性回放风险文件，直接验证 100→200→100 |

测试还动态构造了更名、跨翻译单元且参数换位转发、数组同/不同元素、setter 忽略实参、参数被改写/取地址、仅 setter 内关中断等对照。

## 3. 正确的 stale write-back 时序

```text
初值 g_value = 100
LOW:  READ old = 100（C 实参求值）
      → PREEMPT
HIGH: WRITE new = 200（调用同一 setter）
      → RESUME
LOW:  WRITE old = 100（先前实参仍为 100）
最终 g_value = 100；HIGH 的更新丢失
```

`replay.c` 直接包含风险文件，在 LOW 的 setter 入口、实际 store 之前注入 HIGH。此时实参已读取。HIGH 返回后断言变量为 200，LOW 完成后断言为 100。初始化也调用原 setter，因此不新增该变量的 store 源码位置。测试实际编译并运行此 C 程序；它证明允许的交错会丢失更新，不模拟真实硬件调度器。

## 4. 为什么原子访问不能证明安全

对齐的 32 位 load/store 只能排除单次访问撕裂，不能把实参读取、值保存、调用和写回合成不可分割操作。last-writer-wins 在这里恰好使旧值最后覆盖新值。一个 store site 可以由多个 execution writer context 执行；fixture 检查同一个 WRITE access 同时属于 LOW 和 HIGH，不能据此称为单 writer。

仅在 setter 内关中断也不足以保护此前的实参读取。测试明确保留这种场景为 `SUSPECT`。

## 5. ECRA 静态层修改

`Extractor.function_body` 在已有事实上增加两类小型元数据：

- 直接调用的 `value_arguments`：参数位置及直接读取的源码位置，或未被改写的标量形参位置。
- 原 WRITE access 的 `writeback_parameter_index`：赋值 RHS 直接来自哪个未改写标量形参。

`read_then_writeback_hints` 在现有数组/成员 canonicalization、上下文恢复和 MaskAnalysis 之后运行。它按实参 READ→标量形参转发→实际 WRITE 追踪，要求 READ 和 WRITE 的 canonical `symbol_id` 一致，并保留可行上下文交集及调用边的 `allowed_contexts` 限制。遍历有访问集合，递归不会无限展开。

输出是变量的附加 `concurrency_hints`，包含 `kind=READ_THEN_WRITEBACK`、存储身份、read/write access ID、位置、上下文和一条转发见证路径。完整路径仍由原调用图承担；见证不是额外的完整路径枚举。

不删除或合并任何 READ/WRITE，不把关系变成新的访问类型，不根据该关系直接判定并发风险。已有静态分类器仍根据物理上下文、写者和保护判断，风险 fixture 为 `SUSPECT`。

## 6. Review Packet 修改

`build_variable_review_packet` 将该关系合入现有顶层 `concurrency_hints`，并去除 variable 中的重复副本。原变量声明、全部访问、完整调用图导航、上下文、保护、unknowns 和源码位置保留。没有发送 raw pairs 或恢复旧的复杂复核结构。

风险 fixture 的两个执行 writer 均在同一个实际 store access 的 `contexts` 中保留，READ 作为单独 access 保留。

## 7. OpenCode Prompt 修改

明确要求优先核查完整 `READ位置→旧值保存→调用链→实际WRITEBACK` 窗口，并在现有 reason/interleaving/protection 中回答：是否可抢占、哪些 writer 可插入、是否完整保护、是否旧值覆盖。

明确排除“原子、对齐、无撕裂、单条 store、last-writer-wins、同一 setter、单一源码赋值位置”作为独立安全证明，并区分 store site 和执行 writer。完整保护、同一不可重入上下文仍可安全；优先级未知允许 `NEED_MORE_CONTEXT`。

## 8. SAFE 最小兜底

仅当 Packet 有 `READ_THEN_WRITEBACK` 且答案是 `REVIEWED_SAFE / FALSE_POSITIVE` 时，要求：

```json
{
  "stale_writeback_assessment": {
    "applicable": true,
    "blocked": true,
    "reason": "覆盖整个窗口的阻塞依据",
    "evidence": [{"file": "app.c", "line": 6}]
  }
}
```

布尔值必须是真正的 true；reason 非空；evidence 必须非空且路径属于工程、文件存在、行号有效。复用原 evidence 校验器，未恢复逐 pair 证明。

另有一个范围很小的中英文“仅凭原子性等捷径”检查：若 reason 只描述这些属性、未提出窗口保护/串行/优先级/阶段或存储反证，则拒绝安全结论。它不是自然语言证明器，不能保证识别所有虚构或矛盾的反证；最终源码语义判断仍由 OpenCode 负责。

assessment 引用也纳入源码片段与 SHA 存档。`verify_receipt` 从绑定的 Packet 重新应用该门禁，避免恢复/缓存路径绕过检查。

## 9. 一次轻量 Challenge

安全结论缺少上述证明时，抛出专用验证错误，发起一次 `STALE_WRITEBACK_CHALLENGE`。不先由 FORMAT_FIX 补造安全证据，也不由 ECRA 将 SAFE 改写成 CONFIRMED。

挑战只发送变量身份、原答案、writeback 关系和位置、相关上下文/执行关系及端点保护；不附整个 Packet、全部访问或源码正文。它保持只读源码权限；FORMAT_FIX 仍禁用全部工具，最多两次，两个计数独立。

挑战后可正常完成为风险、安全或证据不足。若第二次仍给无有效证明的安全结论，则 `TECH_FAILED` 且无当前有效 answer，可用原 `review-failed` 重试。挑战不重入技术重试循环，最多一次。现有命令选择规则和顶层三种状态不变。

## 10. 测试矩阵与结果

修复前先执行两个新增测试，实际得到：缺少关系（0 条，预期 1 条）；错误 SAFE 直接成为 `DONE + REVIEWED_SAFE`，未挑战。随后才修改生产代码。

| 场景 | READ_THEN_WRITEBACK | 验证结果 |
|---|---|---|
| LOW 读旧值，HIGH 可抢占写新值 | 是 | 静态 SUSPECT；Mock 挑战后 DONE+CONFIRMED；真实 OpenCode CONFIRMED |
| 完整 IRQ 屏蔽 | 是 | 有证据的 SAFE 正常 DONE；真实 OpenCode REVIEWED_SAFE |
| 同一不可重入物理上下文 | 是 | 静态 SAFE_PROVEN；安全抽样入口正常 DONE；真实 OpenCode REVIEWED_SAFE |
| 读取 other、写 shared | 否 | 不强制 assessment，不触发挑战 |
| 同成员，经一层 wrapper 转发 | 是 | canonical 成员身份一致，静态 SUSPECT |
| 不同成员/不同数组元素 | 否 | 未错误关联同一根对象下的不同存储 |
| 跨文件、参数换位转发 | 是 | 保留真实 read/write 文件和 3 层见证 |
| IRQ 优先级未知 | 是 | NEED_MORE_CONTEXT 正常 DONE，不是技术失败 |
| atomic/same setter 的错误 SAFE | 是 | 必须挑战，不能直接 DONE |
| blocked=true 但仅有原子性理由/无效证据 | 是 | 拒绝安全结论 |
| 两次无证明 SAFE/FALSE_POSITIVE | 是 | 仅挑战一次，TECH_FAILED，无自动 CONFIRMED |
| setter 忽略参数或改写参数 | 否 | 不伪造原实参到 store 的值流 |
| 仅 setter 内关中断 | 是 | 静态仍为 SUSPECT |
| C 确定性回放 | 是 | 实际运行，最终值为 100，HIGH 的 200 丢失 |

当前静态保护汇总主要证明 MAIN-vs-IRQ；因此完整保护的 IRQ-vs-IRQ fixture 仍可保守保留 `SUSPECT`，交由源码复核判安全。本次没有扩大保护证明器。

执行命令：

```powershell
py -3.10 -m unittest tests.test_stale_writeback -v
py -3.10 -m unittest discover -s tests -v
$env:ECRA_STALE_WRITEBACK_LIVE='1'
py -3.10 -m unittest tests.test_stale_writeback.StaleWritebackTests.test_live_opencode_reviews_new_fixtures -v
```

真实 OpenCode 1.18.35 集成测试已通过（1 个测试、3 个新 fixture，72.866 秒）。独立回归模块 17 个测试中 16 个通过，真实复核默认 opt-in 跳过，已单独启用执行。

生产代码冻结后的终轮全量：**638 项，637 通过、1 项默认跳过，0 失败/错误，151.460 秒**。唯一跳过项就是已单独实际通过的 opt-in 真实复核。完整日志为 `output/stale_writeback_full_tests_verified.log`；真实复核摘要为 `output/stale_writeback_live_tests.log`。`git diff --check` 通过。

可检查的各 fixture facts、静态报告、Packet 和 HTML 已生成到 `output/stale_writeback_fixture_validation/<case>/.ecra/`，分类与 hint 数量汇总为该目录下的 `summary.json`。风险 fixture 已实际生成兼容的 `index.html` 并验证只有一个变量顶层决策。

首次全量运行期间仍有生产代码编辑，两个扫描测试因现有 engine digest 的“扫描期间分析实现已变化”保护而拒绝混用版本。终轮在生产代码冻结后执行。

## 11. 修改文件清单

| 文件 | 函数/入口 | 修改内容 |
|---|---|---|
| `ecra/extract.py` | `Extractor.function_body` | 记录实参读取/标量形参转发和形参赋值到 store 的元数据 |
| `ecra/stale_writeback.py` | `read_then_writeback_hints` | 在 canonical 存储上建立附加写回关系，保留上下文限制 |
| `ecra/analysis.py` | `analyze` | 在现有分析流程中将关系附加到变量 facts |
| `ecra/review.py` | `build_variable_review_packet`、`parse_answer`、`review_all` | 传递事实、门禁安全结论、最多一次语义挑战；原格式修复和命令模式保留 |
| `ecra/review.py` | `stale_writeback_challenge_prompt`、`collect_evidence`、`verify_receipt` | 小型挑战、保存 assessment 证据、恢复/缓存时复核门禁 |
| `ecra/review_contract.py` | `validate_stale_writeback_safety`、`validate_source_evidence` | 条件性最小 assessment 和复用源码位置检查 |
| `ecra/review.py`、`ecra/review_contract.py` | Prompt 常量 | 完整窗口、逻辑 writer、无效原子性论据和条件性输出字段 |
| `tests/test_stale_writeback.py` | `StaleWritebackTests` | 真实 AST、C 回放、Mock 和 opt-in 真实 OpenCode 验证 |
| `tests/fixtures/stale_writeback/fixture.h` | 类型、IRQ/CMSIS 声明、回放 hook | 32 位断言和共享测试声明 |
| `tests/fixtures/stale_writeback/semantics.yaml` | contexts/project | 显式物理 IRQ 入口及 NVIC 位数 |
| `tests/fixtures/stale_writeback/unsafe_direct_writeback.c` | `SetValue`、LOW/HIGH、`main` | 单一 store、多 writer、已知可抢占风险 |
| `tests/fixtures/stale_writeback/safe_irq_protected.c` | LOW/HIGH、`SetValue` | 完整临界区安全对照 |
| `tests/fixtures/stale_writeback/safe_same_context.c` | LOW、`SetValue` | 同一不可重入 IRQ 安全对照 |
| `tests/fixtures/stale_writeback/different_storage.c` | LOW、`SetValue` | 不同标量存储对照 |
| `tests/fixtures/stale_writeback/member_writeback.c` | LOW、`Forward`、`SetA` | 同成员及直接调用转发 |
| `tests/fixtures/stale_writeback/member_different_storage.c` | LOW、`SetA` | 不同成员对照 |
| `tests/fixtures/stale_writeback/unknown_preemption.c` | LOW/HIGH、`main` | 未提供 IRQ 优先级的对照 |
| `tests/fixtures/stale_writeback/replay.c` | `preempt_after_argument_load`、`main` | 编译运行，断言实际旧值覆盖 |
| `docs/stale_writeback_fixture_fix.md` | 本报告 | 复现、设计边界、测试及修改清单 |

没有修改 CLI、CMake、数据库 schema、扫描目录策略或 HTML 页面。`index.html` 继续每变量一个顶层结果，writeback 只作为既有事实/原因/时序/保护/证据的内容。

## 12. 已知能力边界

- 支持直接 `Setter(shared)`，同一标量/结构体成员/常量数组元素；支持经多个直接调用、未改写标量形参的转发及跨翻译单元。
- 新关系暂不支持 `tmp = shared; Setter(tmp)`。已有保守 snapshot 事实仍保留，但没有用它建立本次新的 setter 写回关系和安全门禁；没有引入通用 def-use 框架。
- 算术表达式、return 值链、间接函数调用、指针/引用参数、动态数组索引，以及被赋值/自增/取地址的形参，不纳入这条精确关系。它们仍由原访问、别名、snapshot、unknown 和复核机制处理，未声称全部覆盖。
- 函数体中出现形参改写/取地址即保守停止该形参的转发关联，包括可能不可达的改写；这优先避免伪造旧值来源，可能遗漏更复杂的真实值流。
- Hint 是候选路径的附加值流关系，分支可达性、全部调用路径和完整保护必须结合原 Packet/源码核查；不是自动风险 verdict，也不是自动安全证明。
- 无效安全证明耗尽一次挑战后为技术失败，不表示已经证明有风险。`NEED_MORE_CONTEXT` 仍是正常 DONE。
