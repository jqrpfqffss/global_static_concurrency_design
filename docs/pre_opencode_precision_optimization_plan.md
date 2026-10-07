# STM32 裸核并发排查工具（ECRA）OpenCode 前静态分类精度优化 · 技术规划

> 文档类型：技术设计 / 实施规划（本文只规划，不修改代码、不执行实现）
> 版本：v1.0（2026-10-07）
> 适用分支：`optimize_z`

---

## 0. 文档信息与阅读指南

### 0.1 代码与数据基线

| 项 | 内容 |
|---|---|
| 代码基线 | `optimize_z` HEAD `3fb7ef7`（分类优化四）+ 工作区未提交改动（Phase 2：const 不可写剔除 `ecra/analysis.py:706-739`、`ecra/classify.py:280-294`；标准 C 库参数语义表 `ecra/common.py:88-107`；数组元素读 decay 修复 `ecra/extract.py:269-329`），见 `docs/classifier_progress.md` Phase 2 |
| 全量测试基线（本次实测） | `python -m unittest discover -s tests -q`：267 项，1 项 error（`tests/test_acceptance.py` 引用仓库中不存在的 `validation/stm32_concurrency/verify_acceptance.py`，先于本轮存在），其余全部通过，耗时 117 s |
| 基准工程 | `D:/ecra-bench/{klipper, blackmagic, betaflight}`（各自 `semantics-ecra.yaml` 只声明构建目标、目录范围、上下文入口） |
| 基准数据 | klipper `facts-final-klipper.json`、blackmagic `facts-final-blackmagic.json`（均为 Phase 2 后重放 dump）；betaflight 只有汇总 `baseline-roots-betaflight.json`、`bench-new-betaflight-dump.log` 与调用链追踪 `bf-trace2.log`（全量 dump 15 GB，无法整体载入，见 §24） |

### 0.2 证据等级标注

本文每条结论都标注证据来源，凡证据不足一律标注“需进一步确认”，不作推断性结论。

| 标注 | 含义 |
|---|---|
| 【代码】 | 来自源码阅读，附 `文件:行号` |
| 【探针 Pn】 | 本次在仓库外临时目录用最小 C 用例跑通当前引擎（真实 libclang 提取 + `analyze()`）得到的实际输出，用例与结果见附录 A |
| 【基准】 | 来自 `D:/ecra-bench` 已有 dump / 日志的统计（统计脚本为临时脚本，未进入仓库） |
| 【需进一步确认】 | 现有信息不足以下结论；同时给出确认方法 |

### 0.3 术语

| 术语 | 定义 |
|---|---|
| 资源（Resource） | 分类的最小对象。当前实现 = 全局 / 文件 static / 函数 static 变量，结构体按成员拆为 `STRUCT_MEMBER`（`ecra/analysis.py:298-416`）。本规划改为 C11 §3.14 意义的“存储位置”（标量成员、位域组、union 视图），见 §13 |
| 访问（Access） | `READ / WRITE / RMW / ADDRESS_TAKEN` 一行事实，含函数、源码位置、访问路径、上下文 |
| 上下文（Context） | 一个执行入口（MAIN、ISR、TASK、CALLBACK、DMA…）；`facts['contexts']` |
| 物理执行域（Domain） | 真正可并发的执行者。当前 `context_domains()`：所有 MAIN → `FOREGROUND`，其余一上下文一域（`ecra/classify.py:30-47`） |
| MHP | May-Happen-in-Parallel，两个域的访问能否交错 |
| 证据切片（Evidence Slice） | 与某变量判定相关的全部事实集合（访问、所在函数的上下文推导、指向集、取址流向、DMA 契约、使能事件等），见 §6 |
| 见证（Witness） | 支撑某个破坏性冲突结论的最小事实组（两条访问 + 域对 + 交错依据 + 未被排除的原因） |
| Review Rate | (SUSPECT + UNKNOWN) / TOTAL；口径定义见 §1.3 与 §20 |
| false-safe | 真实存在并发风险的资源被判为 `SAFE_PROVEN` 或 `SHARED_NO_REVIEW`（两者都不进入 OpenCode 复核队列） |

### 0.4 需求覆盖索引

任务要求的 24 项与章节对应关系见附录 C；每一项都有独立章节或独立小节，不合并省略。

---

## 1. 背景、问题与目标

### 1.1 问题陈述

工具迁移到大型复杂 STM32 裸机工程后，“疑似并发风险（SUSPECT）+ 无法判断（UNKNOWN）”比例超过 50%，需要 OpenCode 与人工复核的变量过多，违背“尽可能自动排除绝大多数无需关注的变量”的目标。

### 1.2 当前三工程基准（编译变量口径）

| 工程 | TOTAL | SAFE_PROVEN | SHARED_NO_REVIEW | SUSPECT | UNKNOWN | S+U | Review Rate |
|---|---|---|---|---|---|---|---|
| klipper（STM32F405，58 TU） | 889 | 841 | 0 | 38 | 10 | 48 | 5.4% |
| blackmagic（STM32F103 / libopencm3，192 TU） | 691 | 493 → 537 | 9 | 121 → 93 | 68 → 52 | 189 → 145 | 27.4% → **21.0%** |
| betaflight（STM32F405 / SPL，497 TU） | 7630 | 5041 → 5071 | 68 | 2380 → 2359 | 141 → 132 | 2521 → 2491 | 33.0% → **32.6%** |

箭头左侧为 `3fb7ef7` 基线（`docs/classification_root_causes_before.md`），右侧为工作区 Phase 2 修改后的重放结果【基准：`bench-new-blackmagic-p2.log`、`bench-new-betaflight-dump.log`】。TOTAL 已扣除定义不在构建闭包内的依赖声明（klipper 12 / blackmagic 25 / betaflight 306）。

**真实 CubeMX HAL 工程实测**：用户配置的工程 `H:/stm32_RAG/code/serial - opencode`（STM32F103C8，CubeMX + HAL，20 TU，审计范围 `Core/Src`、`Core/Inc`）用本仓库当前引擎在内存中重放（只读取源码，不向该工程写任何文件，§3.6）：TOTAL 44、SAFE_PROVEN 14、SUSPECT 30、UNKNOWN 0，**Review Rate 68.2%**。该工程 `.ecra` 中已有的报告（30/49 = 61.22%）是由另一份工具副本（`H:/global_static_concurrency_design`，其 `doctor.json` 中的配置路径）生成的，版本不同，只作旁证、不作基线。三个基准工程都不使用 STM32 HAL，这是第一份 HAL 工程的当前引擎数据。

### 1.3 统计口径问题（先决发现，P0）

工具自己输出的 Review Rate 与基准文档的口径不一致，这可能是“>50%”观感的直接来源之一：

1. `coverage.classification_quality.review_rate`（`ecra/analysis.py:1155`）的分母 `len(ids)` 包含补充盘点变量（`coverage_source ∈ {supplemental, inactive_branch}`，即非活动 `#if` 分支和未编译源文件里的声明）。这些变量在 `ecra/analysis.py:909-925` 被固定判为 `UNKNOWN / ACCESS_NOT_ANALYZED` 并计入 UNKNOWN。`cli.run` 每次扫描都会调用 `supplement()`（`ecra/cli.py:197-201`）。
2. 补充盘点规模【基准】：klipper 370、betaflight 1113、blackmagic 11。按工具自身口径，klipper 会显示 (48+370)/(889+370) = **33.2%**，betaflight 显示 (2491+1113)/(7630+1113) = **41.2%**，而按编译变量口径分别只有 5.4% 和 32.6%。
3. `report.py` 生成的 `classification_root_causes.md` 分子用 `coverage['static_classification']`（含补充盘点 UNKNOWN），分母用 `compiled`（只含编译变量）（`ecra/report.py:37-62`），同一份报告里分子分母口径不同。

用户在大型工程上观察到的“>50%”中，补充盘点声明占多少【需进一步确认】：用该工程的 `.ecra/facts.json` 按 `coverage_source` 拆分 `static_classification` 即可得到，见 §20.4。作为对照，上述 CubeMX 工程的补充盘点声明为 0，68.2% 全部来自编译变量——说明在 HAL 工程上 >50% 并不只是口径问题，精度缺陷与真实共享状态都占相当比例（§3.6）。

这不是精度问题，但必须先修（OPT-01），否则所有优化都无法正确度量。修正方式是把两个口径同时展示，而不是隐藏补充盘点声明（§20.1）。

### 1.4 目标

| 编号 | 目标 | 说明 |
|---|---|---|
| G1（P0，硬约束） | false-safe ≈ 0 | 黄金风险样例 100% 不被判为 SAFE/NO_REVIEW；真实工程分层抽样审计 0 例 false-safe（报告置信上界，§16.2）；注入式竞态在真实工程中检出率 100% |
| G2（目标） | RR_build ≤ 10% | 在 G1 前提下，只能依靠更精确的静态证明实现（§1.5 禁止项）；若某工程真实风险密度本身高于 10%，按 §23 的“诚实残留”规则逐变量给出证据，不得强行达标 |
| G3 | 每个 S/U 变量都有结构化最小见证或精准缺口 | 原因码可统计、可反事实分析（§21） |
| G4 | 性能可用 | Stage A 在 betaflight 规模的耗时不超过当前（约 780 s）的 1.3 倍；Stage B 只处理候选并有预算上限（§15.5） |

### 1.5 不可违背的约束（摘要，完整清单见 §23.3）

- 不得通过放宽规则、隐藏结果、降低阈值、扩大排除范围、强行归为安全来降低比例。
- 不得出现项目名、变量名、函数名特例；工程差异只能放在 `semantics-ecra.yaml`，且配置只能**增加**上下文/入口证据，不能删除风险。
- 标准 API 语义（CMSIS / HAL / LL / SPL / libopencm3 / C 标准库）属于通用事实，可以建模；它们只能作为“证据来源”或“有标准语义依据的证明前提”，不能作为排除名单。
- 不能为了比例牺牲检出能力：§5.2 的硬风险守门全部有回归测试，任何优化不得绕过。
- 健全性修复（§3.5）优先于精度优化，即使它会让 S+U 暂时上升，也必须先做，并在基准报告中单独列出。

---

## 2. 当前完整分类流程与数据流（需求 1）

### 2.1 端到端流水线

```text
cli.run (ecra/cli.py:75)
 ├─ compilation.prepare                     编译数据库 → units（audit_role=target/dependency）、
 │                                            unlisted_sources、assembly_sources
 ├─ 每个 TU 一个子进程：extract.Extractor.run (ecra/extract.py:550)
 │    ├─ declare()            变量 / 函数清单（record_members 记录结构体字段，无偏移）
 │    ├─ function_body()      accesses / calls / unknowns / protection_events /
 │    │                       irq_priority_events / registrations / snapshots；
 │    │                       局部指针别名（流不敏感，只记 root）
 │    ├─ controlflow.build_cfg 每个函数的 CFG（供屏蔽分析）
 │    ├─ initializers()       静态初始化器中的取址 → STATIC_INITIALIZER_REFERENCE
 │    ├─ FUNCTION_ADDRESS     非调用位置的函数名引用
 │    └─ PointerExtractor     pointer_constraints / semantic_calls / indirect_accesses
 ├─ analysis.merge(parts)                   多 TU 事实合并与去重
 ├─ supplemental.supplement                 非活动分支 / 未编译文件的“仅声明”盘点
 ├─ cli 追加：SOURCE/HEADER_CHANGED_DURING_SCAN、MULTIPLE_BUILD_VARIANTS、
 │            EXTERNAL_CALLEE、SOURCE_NOT_IN_DATABASE、PARSE_FAILED
 └─ analysis.analyze (ecra/analysis.py:574)
      ① 汇编源扫描（按标识符）→ ASSEMBLY_SYMBOL/FUNCTION_REFERENCE；内联汇编操作数中的
         函数地址 → ASSEMBLY 调用边                               (:588-634)
      ② points_to.enrich → Solver.solve：分配站点堆对象、包含式约束不动点（≤1000 轮）、
         实参/返回绑定、INDIRECT_RESOLVED 边、库函数访问、注册入口、HAL DMA 契约、
         按调用点的对象敏感访问归属                                 (:635-636)
      ③ 缺失源码词法扫描 → MISSING_SOURCE_CALLER / SOURCE_NOT_IN_DATABASE (:639-658)
      ④ canonicalize_member_resources：结构体成员资源化、整对象访问继承到成员 (:662)
      ⑤ EXTERNAL_CALLEE 补齐                                         (:663-679)
      ⑥ context_graph：上下文发现 + 调用图 BFS 绑定 + 全部无环调用链   (:680)
      ⑦ interrupts.relations：上下文两两关系（SERIAL/CAN_PREEMPT/...）  (:681)
      ⑧ ClassificationModel：域、逃逸、入口不确定性、死函数、相位模型  (:697-699)
      ⑨ scope.select_facts（审计范围）；const 对象写入剔除            (:703-739)
      ⑩ 逐访问证据（上下文 / 调用链 / 未解析边）；protection.MaskAnalysis (:767-816)
      ⑪ 多字段一致性 coherent_members                                (:838-870)
      ⑫ 依赖声明 / 补充盘点 / 逐变量 protection.assess + model.classify (:879-1055)
      ⑬ 结构体父节点汇总、GAP findings、归账校验、分布统计            (:1058-1167)
 → report.generate：JSON / Markdown / SQLite / HTML / classification_root_causes.md
 → review.review_all：只把 SUSPECT、UNKNOWN 与无符号的 GAP 发现送入 OpenCode
```

### 2.2 各阶段与分类的关系

| 阶段 | 模块 / 函数 | 主要输出 | 对分类的影响 |
|---|---|---|---|
| 提取 | `extract.access_mode` (`ecra/extract.py:266-330`) | 访问种类与成员路径 | 决定 READ/WRITE/RMW 与成员归属；嵌套路径逆序缺陷见 RC-3 |
| 提取 | `extract.function_body` 别名 (`:397-421`, `:515-533`) | `via_alias` 访问 | 局部指针别名只记 root，丢失基路径（RC-3） |
| 提取 | `extract` 库函数语义 (`:469-492`) / DMA 名称启发 (`:493-499`) | 库函数访问、`DMA_SHARED_REVIEW` | 后者产生 `UNKNOWN_DMA_LIFETIME` 缺口 |
| 提取 | `controlflow.build_cfg` (`ecra/controlflow.py:5-171`) | CFG、`complete` 标志 | for/switch/goto/asm/无序表达式使整函数不完整（RC-4） |
| 指针 | `points_to.Solver.solve` (`ecra/points_to.py:93-162`) | 指向集、间接边、DMA 硬件上下文 | 上下文不敏感、数组下标不敏感（RC-1） |
| 指针 | `_attribute_indirect_accesses` (`:245-281`) | 按调用点重新归属的经形参访问 | 只处理数据访问、只一层；访问改挂到调用者（RC-4 P8） |
| 成员 | `canonicalize_member_resources` (`ecra/analysis.py:298-416`) | 成员资源、继承整对象访问 | 路径不匹配时回退整对象并继承到全部成员（RC-3） |
| 上下文 | `context_graph` (`:63-265`) | contexts、bindings、paths | 按调用图 BFS 传播，所有 may-target 边与直接边同等对待（RC-1） |
| 关系 | `interrupts.relations` (`ecra/interrupts.py:94-125`) | 两两关系 | ISR↔ISR 只在优先级可证时 SERIAL（RC-5） |
| 模型 | `ClassificationModel.__init__` (`ecra/classify.py:148-185`) | 逃逸、入口不确定、死函数、相位 | UNKNOWN 与 SAFE_INIT_ONLY_WRITE 的主要来源（RC-6、RC-7） |
| 屏蔽 | `protection.MaskAnalysis` (`ecra/protection.py:23-225`) | 每访问屏蔽状态、窗口 | 只有完整 CFG 才能证明 |
| 保护 | `protection.assess` (`:243-315`) | `EFFECTIVE/PARTIAL/...` | 变量级判定、只看 MAIN 窗口（RC-4） |
| 一致性 | `analysis.py:838-870` | `coherent_members` | 一个域写 ≥2 成员 + 另一域同函数读 ≥2（RC-2） |
| 裁决 | `ClassificationModel.classify` (`ecra/classify.py:740-935`) | 四类 + 原因 + 缺口 | 见 §2.4 |

### 2.3 分类直接依赖的数据结构

**变量记录**（`ecra/extract.py:167-178`，成员由 `ecra/analysis.py:328-341` 生成）：`symbol_id`、`kind`（GLOBAL / FILE_STATIC / LOCAL_STATIC / STRUCT_MEMBER）、`linkage`、`type`（**带 typedef 的拼写**，非规范类型）、`size_bytes`、`alignment_bytes`（**类型对齐**，非成员实际对齐）、`is_const`、`is_volatile`、`is_array`、`is_pointer`、`is_struct`、`is_bitfield_container`、`member_definitions`（字段路径、类型、尺寸、是否位域；**无偏移、无位宽、不区分 struct/union**）、`root_symbol_id`、`field_path`、`coverage_source`、`parse_status`、`definition_file`。

**访问行**：`symbol_id`、`function_id`、`access_kind`、`file/line/offset`、`access_path`、`access_scope`（MEMBER_ACCESS / WHOLE_OBJECT_ACCESS / WHOLE_MEMBER_OBJECT_ACCESS / INHERITED_WHOLE_OBJECT_ACCESS）、`via_alias`、`via_api`、`conditional_ancestor`、`contexts`、`call_chains`、`all_call_chains`、`mask_states`、`inherited_from_access_id`（**在 `:413-414` 重新编号后失效**，见 RC-3）。

**上下文 / 绑定 / 关系**：`contexts[cid] = {kind, discovery, reentrant, execution_domain?, registration?}`；`context_bindings = {function_id, context_id, path, call_depth}`；`preemption_relations = {contexts, relation ∈ SERIAL|CAN_PREEMPT|MAY_INTERLEAVE|UNKNOWN_PREEMPTION, higher?, lower?}`。

**指针**：`pointer_targets = [{location, targets}]`（`obj:<sid>/<field>`、`heap:<file>:<off>`、`fn:<fid>`、`<fid>:param:<i>`、`<fid>:return`、`call:...`、`local:...`）。

**控制流与屏蔽**：`control_flow = [{function_id, nodes[{id, op, successors, offset, end_offset, ...}], complete, unsupported}]`；`mask_windows = [{symbol_id, context_id, node_ids, complete, primask, basepri_values, basepri_known}]`。

**未知事实（unknowns）**：按 `kind` 区分全局失效（`SOURCE_CHANGED_DURING_SCAN` 等）、不透明代码（`EXTERNAL_CALLEE`、`INDIRECT_CALL`、`UNRESOLVED_POINTEE`、`INLINE_ASSEMBLY`、`ASSEMBLY_SOURCE_REVIEW`）、入口不确定（`ENTRY_UNCERTAIN_KINDS`，`ecra/classify.py:98-109`）与变量绑定缺口（`SYMBOL_UNKNOWN_CODES`，`:112-118`）。

### 2.4 当前裁决顺序（`ClassificationModel.classify`，`ecra/classify.py:740-935`）

| 步 | 行号 | 规则 | 结果 |
|---|---|---|---|
| 0 | 760-778 | 取运行期访问（READ/WRITE/RMW）；按上下文聚合到域；`unresolved_context` = 无上下文或函数属于 `entry_uncertain` 的访问 | — |
| 1 | 787-815 | 收集缺口：全局失效 / 多核；地址逃逸（const 除外）；`POINTS_TO_LIMIT`（**全局**）；变量绑定未知；解析失败；定义缺失；**未知上下文的写入**；汇编引用 | gaps |
| 2 | 817-823 | 扫描失效或未建模并发 | UNKNOWN |
| 3 | 832-836 | 全部写入为 PRE 相位且 ≥2 域 | SAFE_INIT_ONLY_WRITE |
| 4 | 839-859 | 破坏性模式：可交错域对双写；可重入写者；CPU↔DMA；位域（**无域数检查**）；多字段一致性 | — |
| 5 | 860-875 | 有破坏性模式：保护 EFFECTIVE → SAFE_EFFECTIVE_PROTECTION，否则 SUSPECT | SAFE / SUSPECT |
| 6 | 879-883 | 存在未知上下文写入 | UNKNOWN |
| 7 | 887-924 | 单一写者域 + ≥2 域：宽度/对齐门槛；失败且有非 ACCESS_NOT_ANALYZED 缺口 → UNKNOWN，否则 SUSPECT；**通过即 SHARED_NO_REVIEW（不检查缺口）** | NO_REVIEW / SUSPECT / UNKNOWN |
| 8 | 926-930 | 有缺口 | UNKNOWN |
| 9 | 931-963 | `_safe_rule`：无运行期访问 / 只读 / 单域 / 有效保护 / main 初始化写 / 多域不可交错 | SAFE_PROVEN |

裁决之后：配置所有权违例把 SAFE/NO_REVIEW 改为 SUSPECT（`ecra/analysis.py:953-956`）；SUSPECT 的规则标签仅用于风险排序（`:962-989`）；归账校验保证每个变量唯一进入“已筛除”或“复核队列”（`:1094-1125`）。

### 2.5 输出与复核队列

- `findings`：每个 SUSPECT/UNKNOWN 变量一条，另有无符号缺口的 `GAP-*` 发现（`ecra/analysis.py:1075-1090`），一起进入 OpenCode 复核。
- `coverage.static_classification`、`classification_quality`、`blocker_fanout`、`unknown_reason_distribution`、`safe_reason_distribution`（`:1123-1167`）。
- `report.write_classification_diagnostics`：`reports/classification_root_causes.md` 与 `classification_quality.html`（`ecra/report.py:31-88`）。

---

## 3. “疑似并发风险 / 无法判断”比例过高的根因分析（需求 2、3、4）

### 3.1 现有根因统计的局限

现有根因报告（`docs/classification_root_causes_before.md`，脚本 `D:/ecra-bench/baseline_roots.py`）有三处口径问题，直接拿来排序会误导优化方向：

1. **“DMA_CONFLICT”桶不是硬件 DMA**。脚本的 `is_dma_domain()` 只要域名中含 `DMA` 就归入该桶；betaflight 的 531 个 DMA_CONFLICT 样例（`APP_Rx_Buffer`、`GPS_directionToHome` 等）冲突对全是 `FOREGROUND ↔ auto:DMA1_Stream0..3_IRQHandler`，即 **DMA 流中断服务函数（ISR）上下文**，不是 DMA 硬件域【基准：`baseline-roots-betaflight.json`】。
2. **单一主桶掩盖多重原因**。优先级为“一致性 > DMA > 双写者 > …”，同时是一致性和双写者的变量只记在一致性下，修好一致性不一定能让它离开队列。
3. **原因来自字符串匹配**（`'多字段一致性' in reason`），而不是分类器输出的结构化原因码，无法做反事实分析。

因此本规划第一步（OPT-02，§21）是让 `classify()` 输出结构化的破坏性模式码、最小见证与门槛失败码，再按“去掉某类证据后有多少变量改判”的反事实方式排序根因。下文排序综合了现有统计、本次 dump 统计与探针，凡排序依据不足之处已标注。

### 3.2 Top 根因总表

| 排名 | 根因 | 性质 | 主要受影响模式 | 量化证据 | 处理章节 |
|---|---|---|---|---|---|
| 前置 | RC-0 统计口径 | 度量缺陷 | 所有工程 | 工具自报口径 klipper 33.2%（编译口径 5.4%）、betaflight 41.2%（32.6%） | §1.3、§20 |
| 1 | RC-1 回调 / 句柄 / 描述符表的上下文不敏感传播（上下文污染） | 误传播 | betaflight；HAL 多实例回调 | `bf-trace2.log`；探针 P13、P14 | §7、§10、§11、§15 |
| 2 | RC-2 多字段一致性守门过宽且有漏洞 | 过度保守 + 健全性缺口 | 全部 | betaflight 主桶 1528；blackmagic 65；探针 P6、P7、P12 | §14.2 |
| 3 | RC-3 成员访问路径缺陷 → 整对象回退放大 | 误判 | 结构体、结构体内数组、局部别名 | blackmagic 3339 行继承访问来自回退，≤19 个 SUSPECT 纯由此产生（上界）；探针 P1、P2、P32 | §10.2、§13 |
| 4 | RC-4 控制流 / 屏蔽分析不完整 | 过度保守 | 使用临界区的工程 | klipper 38/38 SUSPECT 为 PARTIAL；CFG 完整率 27.9% / 82.8%；探针 P4、P8、P21、P22 | §12 |
| 5 | RC-6 入口不确定性函数级前向传播 | 误传播 | 函数指针表 / 回调注册多的工程 | blackmagic 47 个 UEC 中 43 个写入函数有已知上下文；249 种子 → 1042 函数；探针 P5 | §6 |
| 6 | RC-7 相位模型（全局首个使能 + API 名单） | 过度保守 + 健全性缺陷 | CubeMX（`HAL_Init` 先开 SysTick）、libopencm3、SPL | 探针 P24、P9 | §9 |
| 7 | RC-5 抢占优先级恢复窄 | 过度保守 | SPL、libopencm3、表驱动优先级 | betaflight 2334 个 SUSPECT 带“抢占优先级待确认” | §12.3 |
| 8 | RC-8 DMA 模型（仅 HAL、无生命周期、寄存器级不可见） | 过度保守 + 健全性缺陷 | HAL DMA、SPL/LL/寄存器级 DMA | 探针 P18、P26、P31 | §7.4、§12.8 |
| 9 | RC-9 / RC-10 存储粒度与无复核门槛 | 过度保守 + 健全性缺陷 | 位域、typedef/枚举、packed、结构体数组 | 探针 P3、P10、P16、P27、P28；三工程计数小，HAL 工程【需进一步确认】 | §8、§13 |
| 10 | RC-11 逃逸 / 不透明代码 / 内联汇编 | 过度保守 + 健全性缺陷 | 库函数指针参数、asm | ADDRESS_ESCAPE：klipper 4、blackmagic 6、betaflight 68–78；探针 P23、P29 | §6.6、§10.3、§10.4 |

排名说明：RC-1 与 RC-2 的相对大小、RC-3 在 betaflight 上的规模都【需进一步确认】，确认方法是 OPT-02 的反事实统计（§21.3）；排名用于安排实施顺序，不作为收益承诺。

### 3.3 各根因的机制、证据与代码位置

#### RC-1 回调 / 句柄 / 描述符表的上下文不敏感传播（上下文污染）

- **机制**
  1. points-to 是流不敏感、上下文不敏感的包含式分析（`ecra/points_to.py:1-6`、`:105-117`）：形参位置 `<fid>:param:<i>` 合并所有调用点的实参；经形参的存储（注册函数里 `h->cb = f`）把所有调用点的回调写进所有调用点的句柄字段。
  2. 数组元素共享一个抽象位置（`ecra/pointer_extract.py:47-49`）：设备表、DMA 描述符表、SPI 段数组的全部元素合并。
  3. 间接调用的全部 may-target 被写成 `INDIRECT_RESOLVED` 边（`ecra/points_to.py:140-145`），`context_graph` 的 BFS 与直接调用边同等传播上下文（`ecra/analysis.py:175-186`）。
  4. 没有路径相关性：回调里按句柄身份分支（`if (huart == &huart1)`）的访问仍继承全部句柄的上下文。
  5. `_attribute_indirect_accesses` 只对“经形参的数据访问”按调用点归属，且只一层（`ecra/points_to.py:245-281`）；经形参的存储、经形参字段的间接调用不按调用点处理。
- **证据**
  - 【探针 P13】`reg(&h1, cb1); reg(&h2, cb2);`，USART1/USART2 中断分别调用 `irq_common(&h1/&h2)` → `h->cb(h)`：只在 `cb1` 中自增的 `d1` 带 USART1、USART2 两个上下文 → SUSPECT。
  - 【探针 P14】HAL 弱回调 `HAL_UART_RxCpltCallback` 中按 `huart == &huart1 / &huart2` 分支累加 `rx1/rx2`：两者都带两个 UART 上下文 → SUSPECT。
  - 【基准】betaflight 前台函数 `esc4wayProcess` 被挂上约 45 个自动 ISR 上下文（`docs/classifier_progress.md` Phase 2c）；`bf-trace2.log` 中 `TIM2_IRQHandler → … → esc4wayProcess` 的见证链含 4 条 INDIRECT_RESOLVED 边。
  - **源码细节（防止误判为“全部是污染”）**：betaflight 的 ELRS SPI 接收路径里，SPI 段完成回调 `sx1280GetStatsCmdComplete`（ISR 上下文）调用 `processRFPacket`（`src/main/drivers/rx/rx_sx1280.c:826-834`），之后 `processRFMspPacket → processMspPacket（rx/expresslrs_telemetry.c:300）→ handleCrsfMspFrameBuffer → handleMspFrame → processMspPacket（telemetry/msp_shared.c:144）→ mspFcProcessCommand(..., &mspPostProcessFn)`，`msp/msp.c:325` 写 `*mspPostProcessFn = esc4wayProcess` 后被调用。也就是说，启用 `USE_MSP_OVER_TELEMETRY` 时，“MSP 命令处理（写配置结构）在 ISR 中执行”是**真实存在的静态路径**。可以确定属于过近似的是**上下文的倍数**（全部 DMA 流 ISR、全部 SPI 段回调相互合并，来自下标不敏感的描述符 / 段表），以及发送序列中出现接收回调。
- **推论**：只消除倍数时，配置结构可能仍因“至少一个真实 ISR 写者 + 前台读写”保持 SUSPECT。betaflight 能因此下降多少【需进一步确认】：用 §21.3 的见证反事实，统计“冲突对只依赖 fanout>1 的 may-target 边”的变量数。
- **性质**：误传播。

#### RC-2 多字段一致性守门：过宽且有漏洞

- **机制**（`ecra/analysis.py:838-870`，`ecra/classify.py:857-859`）
  1. 写侧：一个域在整个工程中写过同一 root 的 ≥2 个成员即满足，不要求同一次调用（事务）；整对象写（包括 RC-3 的回退继承写）天然满足。
  2. 读侧：另一个域在**同一函数**内读过其中 ≥2 个成员，不要求在同一条路径上。
  3. 只要求“写域 ≠ 读域”，不检查两域能否交错（MHP）。
- **证据**
  - 过宽：【探针 P7】两个已证明同抢占优先级（SERIAL）的 ISR，一个写 `s.value/s.valid`、一个成对读 → 仍 SUSPECT；【探针 P12】读者在 `if/else` 互斥分支中分别读 `c.a`、`c.b` → 仍 SUSPECT；【探针 P32】环形缓冲结构因 RC-3 回退，`r.head/r.tail/r.buf` 全部带一致性标记。
  - 回退放大【基准】：去掉回退产生的继承行后重算一致性成员，blackmagic 67 → 42（−37%），klipper 16 → 12（−25%）。这是上界（修复后访问会落到正确成员，仍可能构成一致性），修复后须重放确认。
  - **漏洞（健全性）**：【探针 P6】value+valid 协议经访问器读取（`if (get_valid()) return get_value();`），两次读在不同函数 → 不标记 → 两个成员都是 SHARED_NO_REVIEW（不进复核）。现有守门 G9 只覆盖同函数直接读。
  - 体量：betaflight 主桶 1528（S+U 的 60.6%）、blackmagic 65（Phase 2 后）、klipper 16；其中多少同时是双写者【需进一步确认】。
- **性质**：过度保守 + 误判 + 健全性缺口。

#### RC-3 成员访问路径构造缺陷 → 整对象回退与继承写放大

- **机制**
  1. **嵌套直接访问路径逆序**：`access_mode` 从内向外遍历祖先依次追加成员名（`ecra/extract.py:279-288`），返回前又 `reversed` 拼接（`:330`），两层及以上的路径被反转：`u.h.lo → lo.h`、`s.inner.x → x.inner`、`r.buf[i] → [].buf`（【探针 P1、P2、P32】实际输出）。
  2. **局部别名丢失基路径**：`p = &s.inner` 只记录 `p → s`（`:411-419`），`p->y` 被记为 `s` 的路径 `y`（`:526-532`）。
  3. `canonicalize_member_resources` 找不到成员时降级为 `WHOLE_OBJECT_ACCESS`（`ecra/analysis.py:377-380`）并复制到**全部**成员（`:381-391`）。
  4. **证据链断裂**：继承行的 `inherited_from_access_id` 是重新编号前的 ID（`:389` 写入、`:413-414` 重编号），继承行无法追溯来源（本次统计用 ID 关联得到 0 行，用路径特征关联得到 102 行，证实断链）。
  5. **潜在误归属**：逆序路径恰好等于另一真实成员路径时（如同时存在 `a.b` 与 `b.a`），写入落到错误成员，真实成员丢失该写；直接访问只由提取器产生，points-to 不会补出正确行，因此是低概率健全性风险。
- **证据**
  - 【探针 P2】`s.x` 只被 main 读，却因 ISR 中 `s.inner.x = 5`、`p->y = 3` 的回退继承写成为 SHARED_NO_REVIEW（应为 SAFE_READ_ONLY）。【探针 P32】`r.tail` 只被前台写，却因 ISR 中 `r.buf[...] = 1` 的回退继承写成为双写者 SUSPECT。
  - 【基准】blackmagic：103 行回退访问（WRITE 22、RMW 10、READ 64、ADDRESS_TAKEN 7，其中 91 行来自局部别名、19 行是嵌套路径）生成 3339 行继承访问（全部继承行 4284 的 78%）；93 个 SUSPECT 中 43 个受影响，19 个在去掉这些继承行后不再有任何跨域写（上界）。klipper：18 行回退 → 102 行继承，8 个 SUSPECT 受影响，1 个不再有跨域写。
  - betaflight 结构体成员 5170 个（占 TOTAL 68%），同口径规模【需进一步确认：内存内重放统计】。
- **性质**：误判 + 过度保守 + 低概率健全性风险。

#### RC-4 控制流与屏蔽分析不完整，保护几乎无法被证明

- **机制**
  1. `build_cfg` 遇到 `FOR_STMT / SWITCH_STMT / GOTO_STMT / INDIRECT_GOTO_STMT / 任意 ASM 语句` 记入 `unsupported`（`ecra/controlflow.py:153-160`）；表达式“含调用且引用全局”或“含 ≥2 个调用”记为 `UNSEQUENCED_EXPRESSION`（`:58-67`）；`unsupported` 非空则整函数 `complete=False`（`:169`）。
  2. 不完整 CFG 的函数中所有点的屏蔽状态未知（`ecra/protection.py:124-135`）；调用不完整 CFG 的被调函数（含 CMSIS `__NOP()` 等内联汇编函数）之后状态未知（`:102-111`）。
  3. 对象敏感归属把经形参的访问改挂到调用者（`ecra/points_to.py:277`），源码位置仍在被调函数：屏蔽分析在调用者 CFG 里找不到节点，被调函数的屏蔽事件也不在 `related` 集合中。
  4. `assess` 只看 MAIN 窗口（`ecra/protection.py:276`）；`participants` 要求全部 ISR 两两 SERIAL（`:292-293`），即使 ISR 之间只有读-读；保护是变量级，不是冲突对级。
  5. 以内联汇编（`cpsid i`）实现的工程封装（如 klipper 的 `irq_disable/irq_save`）不被识别，除非在 `critical_sections` 逐一配置。
- **证据**
  - 【探针 P4】PRIMASK 窗口内含 `for` 循环 → UNRESOLVED → SUSPECT；同构无循环窗口 → EFFECTIVE。
  - 【探针 P21、P22】函数中任一处出现 `g = f();`，同函数后面完全独立的 `__disable_irq(); k++; __enable_irq();` 也被判 UNRESOLVED；窗口内调用 `__NOP()` 同样失效。
  - 【探针 P8】在被调函数内完整屏蔽的 `q_add(&q1)` → `q1.count` 保护 NOT_FOUND → SUSPECT；直接访问全局的同构函数 → EFFECTIVE。
  - 【基准】CFG 完整率：klipper 858/3078（27.9%；按函数计不完整原因 ASM 1993、UNSEQUENCED 144、FOR 118、GOTO 12、SWITCH 11），blackmagic 2003/2419（82.8%；UNSEQUENCED 193、FOR 181、SWITCH 161、ASM 31、GOTO 6）。klipper 全部 38 个 SUSPECT 保护状态为 PARTIAL；betaflight 1829 个 SUSPECT 带“保护有效性待确认”。betaflight 的 `ATOMIC_BLOCK` 由 `for` 循环 + `__cleanup__` 属性实现（`src/main/build/atomic.h:121`），当前 CFG 与屏蔽分析都不支持。
  - 修复后能证明多少【需进一步确认】：其中一部分是真实未保护冲突（如 klipper 文档记录的唤醒标志双写），只有重放才能区分。
- **性质**：过度保守（方向安全）。

#### RC-5 抢占关系（MHP）恢复范围窄

- **机制**（`ecra/interrupts.py:15-80`，`ecra/extract.py:461-468`）：只识别 `HAL_NVIC_SetPriority / NVIC_SetPriority / *PriorityGrouping`；SPL `NVIC_Init(&init)`、libopencm3 `nvic_set_priority`、直接写 `NVIC->IP[]/SCB->SHP[]` 不识别；要求每个 IRQ 恰好一次、无条件、只在前台函数设置；表驱动或循环设置即放弃；未证明的 ISR↔ISR 关系按可交错处理。
- **证据**：【基准】betaflight 2334 个、blackmagic 19 个 SUSPECT 带“抢占优先级待确认”。
- **性质**：过度保守。

#### RC-6 入口不确定性按函数整体前向传播（UNKNOWN 扩散）

- **机制**（`ecra/classify.py:357-389`、`:777-778`、`:806-813`）：种子函数（取址但无已解析分派、地址流入未解析调用、经逃逸对象可达、`ENTRY_UNCERTAIN_KINDS`）沿调用图把“不确定”传给所有被调函数，即使被调函数本身有完整已知上下文；不确定函数中的**任何写入**都成为未知上下文写入 → UNKNOWN_EXECUTION_CONTEXT。另外，没有任何上下文绑定又未被证明死亡的函数（`UNKNOWN_ENTRY`）中的写入同样计入；只要工程中存在任何不透明代码，外部链接函数一律不能证明死亡（`:424-427`）。
- **证据**：【探针 P5】从未被分派的函数指针表项 `cb` 调用公共函数 `log_write`（也被 main 调用），只在前台访问的 `shared_log_idx` 变成 UNKNOWN。【基准】blackmagic 249 个种子 → 1042 个不确定函数；UEC 变量中写入函数自身有已知上下文的：blackmagic 43/47、klipper 6/6；函数可达性 UNKNOWN_ENTRY：klipper 2104、blackmagic 604。
- **性质**：误传播。

#### RC-7 初始化 / 运行期相位模型

- **机制**（`ecra/classify.py:122-136`、`:528-707`、`:482-508`）：PRE = 任一已识别使能 API 之前；API 是固定名单；不区分中断源；PRE 写者与任一运行期写者组合时仍计入冲突（守门 G5）。
- **证据**
  - 过度保守：【探针 P24】`SysTick_Config()` 之后、`HAL_NVIC_EnableIRQ(USART1)` 之前写 `cfg_mode`，USART1 ISR 运行期写，SysTick ISR 与该变量无关 → SUSPECT。CubeMX 工程 `main()` 第一句就是 `HAL_Init()`（使能 SysTick），初始化窗口几乎为空。
  - 健全性：【探针 P9】`nvic_enable_irq(30)`（libopencm3，未识别）之后、`SysTick_Config()` 之前写 64 位 `stamp`，TIM4 ISR 读 → SAFE_INIT_ONLY_WRITE（false-safe）。SPL `NVIC_Init`、直接写 `NVIC->ISER`、调用无源码 BSP 库、汇编 `cpsie i` 同理。
  - 历史：Phase 2 曾尝试“PRE 写者 + 可屏蔽 ISR 运行期写者不参与冲突”，7 个测试失败后回滚（`docs/classifier_progress.md:114-122`）。原因分析见 §9.5。
- **性质**：过度保守 + 健全性缺陷。

#### RC-8 DMA 模型

- **机制**：只识别 5 个 HAL DMA API 的缓冲参数（`ecra/points_to.py:342-369`）；所有接收缓冲共用上下文 `dma_rx`、所有发送缓冲共用 `dma_tx`（`:360`）；无生命周期（`ecra/classify.py:850-854` 的条件等价于“DMA 写或 CPU 写”）；名称启发：名字含 `DMA` 的任何调用，只要实参引用了非指针变量（哪怕按值）就产生 `DMA_SHARED_REVIEW`（`ecra/extract.py:493-499`）；寄存器级 DMA（`DMAx_Streamy->M0AR = (uint32_t)buf`、SPL 初始化结构 + `DMA_Init`、LL 寄存器写内联函数）完全不可见。
- **证据**：【探针 P18】先填 `txbuf` 再 `HAL_UART_Transmit_DMA` → SUSPECT；【探针 P26】按值传 `cfg_word` 给 `dmaSetHandler` 即产生 DMA 缺口；【探针 P31】寄存器级配置的 `rxbuf` 只被前台读 → SAFE_READ_ONLY（false-safe）。SPL 工程（betaflight）中硬件 DMA 缓冲是否因此被判安全【需进一步确认】。
- **性质**：过度保守 + 健全性缺陷。

#### RC-9 存储粒度：union / 位域 / 结构体数组

- **机制**：`record_members` 不记录字段偏移、位宽，不区分 struct/union（`ecra/extract.py:201-231`），union 成员被当作互不重叠的资源；位域成员只要存在写者即判破坏性（`ecra/classify.py:855-856`，无“≥2 域”检查），兄弟位域共享存储单元未建模（守门 G7 依赖这条无条件规则通过）；结构体数组不生成成员，整个数组一个资源。
- **证据**：【探针 P1】ISR 写 `u.w`、前台写 `u.h.lo`：`u.h.lo/u.h.hi` → SAFE_SINGLE_FOREGROUND（false-safe）；【探针 P3】只在前台访问的位域 → SUSPECT；【探针 P16】ISR 写 `arr[i].a`、前台写 `arr[j].b` → 双写者。【基准】位域 SUSPECT：klipper 0、blackmagic 0、betaflight 1；寄存器镜像 / 标志位风格工程规模【需进一步确认】。
- **性质**：健全性缺陷（union）+ 过度保守（位域、结构体数组）。

#### RC-10 SHARED_NO_REVIEW 门槛与 SAFE_NON_INTERLEAVING

- **机制**：宽度按类型拼写匹配（`ecra/classify.py:712-738`），typedef 标量与枚举失败；对齐取字段类型对齐（`ecra/extract.py:220`），packed 不对齐成员仍报 4；门槛通过即返回 NO_REVIEW，不检查缺口（`ecra/classify.py:887-924`），原因文本却声称“无 DMA、地址逃逸”；“多写者全部 SERIAL”直接返回 SAFE_NON_INTERLEAVING（`:962-963`），不检查其它域读者的撕裂；没有中间值暴露、多元素快照、可见性三类守门。
- **证据**：【探针 P10】`timeUs_t`、`mode_e` 单写者 → SUSPECT，同构 `unsigned int` → NO_REVIEW；【探针 P25】ISR 单写 + 前台读 + 地址传给无源码函数 → NO_REVIEW；【探针 P27】packed 偏移 1 的 `uint32_t` → NO_REVIEW；【探针 P28】两个同优先级 ISR 写 64 位、前台读 → SAFE_NON_INTERLEAVING。【基准】blackmagic 9 个 NO_REVIEW 中 4 个带原始 ADDRESS_ESCAPE 事实（上界，是否落在未解析区间【需进一步确认】）。
- **性质**：过度保守 + 健全性缺陷。

#### RC-11 地址逃逸、不透明代码与内联汇编

- **机制**：提取器用 16 函数的 `LIBC_ARG_SEMANTICS`（`ecra/extract.py:472-492`），points-to 仍用旧 4 函数表（`ecra/points_to.py:148-152`），经指针的 `strcpy` 等写不建模；`_collect_pointer_escapes` 用 USR（`c:@F@strcpy`）与裸名集合比较（`ecra/classify.py:315`），豁免从不生效——目前因此保持保守（【探针 P29】→ UNKNOWN_ADDRESS_ESCAPE），但若只修名称比较、不补 points-to 语义就会引入 false-safe。内联汇编输出操作数按默认 READ 记录；`_assembly_symbol_references` 的文本扫描条件写反（`:449`，内联汇编本身就使 `opaque_code=True`），扫描永远不执行。`POINTS_TO_LIMIT` 是全局缺口（`:792-793`）。闭包不完整时所有存入外部链接对象的地址都算逃逸（`:309-312`）。
- **证据**：【探针 P23】ISR 中 `__asm volatile("" : "=m"(g_op))` → `g_op` SAFE_MULTI_CONTEXT_READ_ONLY；汇编文本 `ldr r1, =g_txt; str r0, [r1]` → `g_txt` SAFE_READ_ONLY（均为 false-safe）。【基准】ADDRESS_ESCAPE：klipper 4、blackmagic 6、betaflight 68–78。
- **性质**：健全性缺陷 + 过度保守。

### 3.4 过度保守、误传播、误判、漏判机制清单（需求 4）

| ID | 类别 | 机制 | 代码位置 | 证据 | 处理 |
|---|---|---|---|---|---|
| M-01 | 过度保守 | 位域无“≥2 域”检查，单域写入也判破坏性 | `classify.py:855-856` | P3 | §13 |
| M-02 | 过度保守 | 一致性不检查写读两域是否可交错 | `analysis.py:862-869` | P7 | §14.2 |
| M-03 | 过度保守 | 一致性读对不要求同一路径 | `analysis.py:857-858` | P12 | §14.2 |
| M-04 | 过度保守 | 一致性写侧不要求同一事务 | `analysis.py:859-860` | 代码 | §14.2 |
| M-05 | 误判 | 嵌套成员路径逆序 | `extract.py:279-288, 330` | P1、P2、P32 | §10.2 |
| M-06 | 误判 | 局部别名丢失基路径 | `extract.py:411-419, 526-532` | P2 | §10.2 |
| M-07 | 过度保守 | 路径不匹配回退整对象并继承到全部成员 | `analysis.py:377-391` | blackmagic 3339 行 | §13 |
| M-08 | 过度保守 | 结构体数组无字段敏感 | `extract.py:175`；`analysis.py:311` | P16 | §13 |
| M-09 | 过度保守 | for/switch/goto/asm 使整函数 CFG 失效 | `controlflow.py:153-160, 169` | P4 | §12.4 |
| M-10 | 过度保守 | 无序表达式使整函数 CFG 失效 | `controlflow.py:58-67` | P21 | §12.4 |
| M-11 | 过度保守 | 调用内联汇编函数（`__NOP` 等）后屏蔽状态丢失 | `protection.py:102-111` | P22 | §12.4 |
| M-12 | 误判 | 对象敏感归属改挂调用者，丢失被调函数内的保护 | `points_to.py:277` | P8 | §11.3 |
| M-13 | 过度保守 | 保护只看 MAIN 窗口；要求 ISR 两两 SERIAL；变量级判定 | `protection.py:276, 292-293` | 代码 | §12.5 |
| M-14 | 过度保守 | 优先级只识别 HAL/CMSIS 且单次无条件 | `interrupts.py:15-80` | betaflight 2334 | §12.3 |
| M-15 | 误传播 | 形参合并、经形参存储 → 跨实例回调 | `points_to.py:105-117` | P13 | §11 |
| M-16 | 误传播 | 数组元素合并 → 描述符 / 设备表回调合并 | `pointer_extract.py:47-49` | `bf-trace2.log` | §10.6 |
| M-17 | 误传播 | may-target 边与直接边同等传播上下文 | `analysis.py:175-186` | `bf-trace2.log` | §11.2、§15.2、§17.1 |
| M-18 | 误传播 | 回调内句柄身份分支无路径相关性 | — | P14 | §11.2 |
| M-19 | 误传播 | 入口不确定函数级前向传播 | `classify.py:375-389` | P5 | §6.4、§6.5 |
| M-20 | 过度保守 | 存在任一不透明代码时外部函数不能证明死亡 | `classify.py:424-427` | klipper UNKNOWN_ENTRY 2104 | §6.7 |
| M-21 | 过度保守 | `POINTS_TO_LIMIT` 全局缺口 | `classify.py:792-793` | 代码 | §6.6 |
| M-22 | 过度保守 | 全局首个使能定义 PRE，不按中断源 | `classify.py:528-691` | P24 | §9 |
| M-23 | 过度保守 | 无复核门槛的宽度按 typedef 拼写匹配 | `classify.py:712-738` | P10 | §8 |
| M-24 | 过度保守 | DMA 无生命周期；所有 DMA 共用一个域 | `points_to.py:342-369`；`classify.py:850-854` | P18 | §7.4、§12.8 |
| M-25 | 过度保守 | DMA 名称启发（按值实参也算） | `extract.py:493-499` | P26 | §7.4 |
| M-26 | 过度保守 | 闭包不完整 → 全部外部链接对象地址逃逸 | `classify.py:309-312` | 代码 | §6.6 |
| M-27 | 漏判 | union 重叠未建模 | `extract.py:201-231` | P1 | §13 |
| M-28 | 漏判 | 访问器方式的成对读不计入一致性 | `analysis.py:857-858` | P6 | §14.2 |
| M-29 | 漏判 | 未识别的使能机制不阻断 PRE | `classify.py:122-136` | P9 | §9 |
| M-30 | 漏判 | NO_REVIEW 不检查缺口 | `classify.py:887-924` | P25 | §8 |
| M-31 | 漏判 | asm 输出操作数记为 READ；asm 文本扫描是死代码 | `extract.py:266-330`；`classify.py:449` | P23 | §10.4 |
| M-32 | 漏判 | packed 成员按类型对齐 | `extract.py:220` | P27 | §8、§13 |
| M-33 | 漏判 | 多写者 SERIAL 时忽略其它域读者撕裂 | `classify.py:962-963` | P28 | §8 |
| M-34 | 漏判 | 未知上下文中的读访问被完全忽略 | `classify.py:777-813` | P30 | §6.3 |
| M-35 | 漏判 | 寄存器级 DMA 地址发布不可见 | `points_to.py:342-369` | P31 | §7.4 |
| M-36 | 统计误判 | 根因桶按上下文名含 `DMA` 归入 DMA_CONFLICT；单主桶 | `D:/ecra-bench/baseline_roots.py` | baseline-roots | §21 |
| M-37 | 统计误判 | 工具 Review Rate 含补充盘点；报告分子分母口径不一 | `analysis.py:1155`；`report.py:37-62` | §1.3 | §20 |
| M-38 | 潜在漏判 | LIBC 豁免名称/USR 不一致（目前保守） | `classify.py:315`；`points_to.py:148` | P29 | §10.3 |
| M-39 | 潜在漏判 | 逆序路径与真实成员同名时误归属 | `extract.py:330` | 代码推断 | §10.2 |
| M-40 | 误判 | 指针成员链上的解引用没有终止左值链：`h->Instance->CR1 \|= x` 被记为对指针成员 `Instance` 的 RMW；直接访问 `g.ptr->x = v` 同样把写记到 `g` 上（并因路径逆序回退整对象） | `pointer_extract.py:128-145`；`extract.py:279-288` | P33；HAL 工程中 `huart2.Instance`、`huart2.hdmarx` | §10.2 |

### 3.5 已确认的健全性缺陷（false-safe / 错误免复核）——P0，先于一切精度优化

| ID | 缺陷 | 现象（当前输出） | 探针 | 修复 | 守门测试 |
|---|---|---|---|---|---|
| FS-1 | union 成员重叠未建模 | `u.h.lo` SAFE_SINGLE_FOREGROUND，而 ISR 写重叠的 `u.w` | P1 | OPT-11 / §13 | GR-12 |
| FS-2 | 访问器方式的 value+valid 成对读 | 两成员 SHARED_NO_REVIEW | P6 | OPT-12 / §14.2 | GR-09b |
| FS-3 | 未识别使能机制之后的“初始化写” | 64 位 SAFE_INIT_ONLY_WRITE | P9 | OPT-13 / §9 | GR-15 |
| FS-4 | NO_REVIEW 不检查缺口 | 地址逃逸的单写者 NO_REVIEW | P25 | OPT-10 / §8 | GR-16 |
| FS-5 | 内联汇编写入 | 输出操作数与汇编文本写入被判只读 | P23 | OPT-14 / §10.4 | GR-14 |
| FS-6 | packed 不对齐成员 | 非原子访问判 NO_REVIEW | P27 | OPT-15 / §8 | GR-13 |
| FS-7 | 多写者 SERIAL + 其它域读者 | 64 位 SAFE_NON_INTERLEAVING | P28 | OPT-16 / §8 | GR-11b |
| FS-8 | 未知上下文读 | 未知入口函数读 64 位，变量判单前台安全 | P30 | OPT-17 / §6.3 | GR-26 |
| FS-9 | 寄存器级 DMA | DMA 写入的缓冲判 SAFE_READ_ONLY | P31 | OPT-18 / §7.4 | GR-24 |
| FS-10（潜在） | LIBC 豁免与 points-to 语义不一致 | 当前保守；“修名”即成缺陷 | P29 | OPT-19 / §10.3 | GR-27 |
| FS-11（潜在） | 逆序路径误归属 | 低概率丢写 | 代码推断 | OPT-20 / §10.2 | GR-28 |

说明：这些修复会让部分变量从 SAFE/NO_REVIEW 回到 SUSPECT/UNKNOWN，Review Rate 可能短期上升。这是如实暴露风险，必须在基准报告中单列“健全性修复引起的上升”，不能被后续精度收益抵消后不报（§20.3）。

### 3.6 实测：用户 CubeMX HAL 工程的 SUSPECT 构成

**方法**：对 `H:/stm32_RAG/code/serial - opencode` 使用本仓库引擎，在临时进程中逐 TU 运行 `Extractor`、`merge`、`analyze`（未运行补充盘点；审计范围与该工程现有配置一致；脚本放在系统临时目录，不向该工程写入任何文件）。发现的上下文：main 与 11 个自动识别的异常 / 中断（USART2、DMA1_Channel6/7、SysTick、PendSV、SVC、NMI、HardFault、MemManage、BusFault、UsageFault）。30 个 SUSPECT 涉及的域全部只有 {FOREGROUND, USART2_IRQHandler}。

| 组 | 成员 | 数量 | 当前原因 | 访问事实（去掉路径回退产生的继承行后） | 根因 | 修复后预期（估计，须实测） |
|---|---|---|---|---|---|---|
| `huart2.Init.*` | BaudRate、WordLength、StopBits、Parity、Mode、HwFlowCtl、OverSampling | 7 | 仅多字段一致性 | 前台只读 + ISR 只读：真实的初始化写 `huart2.Init.X = ...` 只以逆序路径回退（`BaudRate.Init` 等）的继承行存在 | RC-3 + RC-2 | 路径修复后为“前台初始化写 + ISR 读”；`MX_USART2_UART_Init` 的写先于 `HAL_UART_MspInit` 中的 USART2 NVIC 使能，§9.3（A）可证 → SAFE_ORDERED_INIT |
| `huart2` 指针成员 | Instance、hdmarx、pTxBuffPtr | 3 | 双写者 / 一致性 | Instance 的 ISR 侧 RMW 来自 `huart->Instance->CR1 \|= …`（M-40）；hdmarx、pTxBuffPtr 的前台写只来自回退 | M-40 + RC-3 | Instance → SAFE_ORDERED_INIT；hdmarx、pTxBuffPtr 只剩 ISR 访问 → SAFE |
| `huart2` HAL 内部协议字段 | gState、RxState、RxXferCount、RxXferSize、TxXferCount、pRxBuffPtr、ErrorCode、ReceptionType、RxEventType | 9 | 前台 ↔ USART2 双写 | 前台 HAL API 与 ISR 内 HAL 处理函数都写 | 按 NVIC 级语义是真实双写；HAL 靠“先写字段、再开外设中断源（RXNEIE/TXEIE）、ISR 结束时关闭”的所有权协议避免冲突 | 没有外设中断源级次序模型（OPT-80，P2，§9.5）时无法证明，诚实保留 SUSPECT |
| `cli.uart_error`、`cli.rx_overflow` | — | 2 | 双写者 | ISR 置位（`cli.c:116, 257`），前台“读到非 0 后清零”（`cli.c:46-56`） | **真实风险**（HR-04 模式：清零前 ISR 再次置位的事件会丢失） | 保持 SUSPECT（正确结论） |
| `cli.rx_head`、`cli.rx_cr_seen` | — | 2 | 双写者 + 一致性 | ISR 入队 / 接收处理中写（`cli.c:79-101, 262`）；前台 `Cli_Process` 在出错或溢出后**运行期**调用 `Cli_ResetInputState` 把它们清零（`cli.c:49, 57 → 221-227`） | **真实风险**：前台复位索引时 ISR 可能正在入队，队列索引被破坏 | 保持 SUSPECT（正确结论） |
| `cli.rx_queue`、`cli.rx_byte` | — | 2 | 双写者 + 一致性 | ISR 运行期写；前台写只有 `Cli_Init` 中的 `memset(cli, 0, …)`（`cli.c:25`） | `Cli_Init`（`main.c:107`）位于 USART2 NVIC 使能（`MX_USART2_UART_Init`，`main.c:101` → `stm32f1xx_hal_msp.c:118`）之后、`Cli_Start` 开启接收（`main.c:108` → `cli.c:218`）之前：NVIC 级 HB 不成立，只有外设中断源级次序才能证明 | OPT-80 可证时排除，否则保留 |
| `cli.rx_tail`、`cli.uart` | — | 2 | 仅一致性 | 前台单写，ISR 读 | RC-2（ISR 在入队函数中成对读 head/tail） | 一致性 v2 的 C5（ISR 抢占前台、前台单次调用只写一个成员）下不再标记 → SHARED_NO_REVIEW（volatile 对齐标量 / 指针） |
| `DebugCliStats` 计数器 | rx_bytes、rx_overflow、uart_error | 3 | 双写者 | ISR `++`（`cli.c:75, 115, 256`）；前台写只有 `Cli_Init` 中的 `memset(&DebugCliStats, 0, …)`（`cli.c:29`） | 与上一行相同的初始化次序问题 | OPT-80 可证时排除，否则保留 |

**结论**：30 个 SUSPECT 中，约 10 个由路径 / 解引用缺陷（RC-3、M-40）直接造成，修复后加上逐 IRQ HB（A）可离开队列；2 个依赖一致性 v2；5 个取决于初始化与“外设中断源开启”的先后，需要 OPT-80 才能静态证明；13 个按静态语义是真实共享写——其中 4 个是源码可见的真实缺陷（`uart_error`、`rx_overflow` 的置位 / 清零丢失事件，`rx_head`、`rx_cr_seen` 的运行期复位竞争），9 个是 HAL 内部协议字段。估计修复 P0/P1 后该工程约为 18–20 / 44（41%–45%），引入 OPT-80 后约 13–15 / 44（30%–34%）。**这个小型工程的大部分全局状态本来就是 ISR 共享状态，其中还有真实缺陷，10% 在该工程上不能靠精度达到**；10% 目标应在大型工程上评估（§19、§23.4）。上述估计都必须在修复后用同一方法重放确认。

### 3.7 根因与优化项的对应

| 根因 | 优化项（§6–§15） |
|---|---|
| RC-0 | OPT-01（口径）、OPT-02（结构化原因码与反事实） |
| RC-1 | OPT-42（类型过滤）、OPT-43（HSCP）、OPT-44（常量下标 / 按调用点存储）、OPT-61 B1/B2 |
| RC-2 | OPT-12（访问器读组）、OPT-24（一致性 v2） |
| RC-3、M-40 | OPT-20（路径代数）、OPT-21（布局模型）、OPT-03（证据 ID） |
| RC-4 | OPT-30、OPT-31、OPT-32、OPT-33、OPT-53 |
| RC-5 | OPT-51 |
| RC-6 | OPT-17、OPT-40、OPT-41、OPT-47 |
| RC-7 | OPT-13、OPT-50、OPT-80 |
| RC-8 | OPT-18、OPT-52 |
| RC-9、RC-10 | OPT-10、OPT-11、OPT-15、OPT-16、OPT-21、OPT-22、OPT-23、OPT-25 |
| RC-11 | OPT-14、OPT-19、OPT-45 |

---

## 4. 四类结论的严格定义（需求 5）

### 4.1 基本概念

- **资源 r**：C11 §3.14 的存储位置（标量对象或非位域成员；一组相邻非零宽位域构成一个位域组；union 的各成员是同一段字节的不同视图）。资源的字节/位范围由 §13 的存储布局模型给出。
- **重叠访问集 A(r)**：所有字节/位范围与 r 相交的访问（直接成员访问、整对象访问、union 其它视图的访问、同组位域访问、经指针/库函数/汇编的访问），扣除“已证明不可达”的函数中的访问和“已证明不可能”的写（const 非 volatile 对象）。
- **域与 MHP**：域见 §7；MHP(d1, d2) ∈ {NO（同优先级串行 / HB 有序 / 同一非重入域）, YES（可交错）, UNKNOWN（按 YES 处理）}。
- **见证 w**：二元组（访问 a1@域 d1，访问 a2@域 d2）+ 破坏性模式码 + MHP 依据 + 当前未被排除的原因。
- **证明记录 ProofRecord**：排除一个见证或满足一项门槛的依据（规则、版本、前提事实 ID、假设清单）。
- **缺口相关性**：缺口 g 与 r 相关，当且仅当把 g 取最坏解释后可能（i）在新域中增加对 r 的写或使某域可重入；（ii）在 r 有写者时于新域增加读（影响撕裂、一致性、可见性判断）；（iii）使 r 的某个证明前提失效（死函数、HB 次序、保护窗口完整性）。

### 4.2 SAFE_PROVEN（静态已判安全）

**定义**：在当前构建闭包与已建模的单核抢占并发模型下，可以证明 r 的任意两次访问都不会形成可交错的破坏性冲突，并且 r 的证据切片中不存在相关缺口。

**证明码**（保留现有码，语义收紧；新增码标“新”）：

| 证明码 | 必要条件（全部满足） |
|---|---|
| SAFE_NO_RUNTIME_ACCESS | A(r) 中无运行期访问；地址没有流入不透明代码、汇编、外设寄存器；无汇编按名引用 |
| SAFE_READ_ONLY / SAFE_MULTI_CONTEXT_READ_ONLY | A(r) 全部为 READ（含重叠视图）；无写逃逸、无汇编写、无 DMA/外设写、无未知上下文写 |
| SAFE_SINGLE_FOREGROUND / SAFE_SINGLE_IRQ / SAFE_SINGLE_CONTEXT | A(r) 全部属于同一非重入域；**无未知上下文访问（读也不行，修 FS-8）**；同一处理函数不挂在不同优先级的多个向量上 |
| SAFE_ORDERED_INIT（新，取代并泛化 SAFE_INIT_ONLY_WRITE） | 每个写 w 对每个访问 r 的其它域 X 都满足 w ≺ X（§9.3，健全使能模型；NMI/HardFault 永不满足）；运行期只读 |
| SAFE_EFFECTIVE_PROTECTION | 每个破坏性见证都被**逐对**有效保护排除（§12.5） |
| SAFE_NON_INTERLEAVING | 每个含写的跨域访问对都 MHP=NO；非原子宽度时读者对也必须 MHP=NO（修 FS-7） |

**禁止作为 SAFE 依据**：`volatile`；访问宽度本身；“只有一个写者”；“没有发现问题”；`resources / protection / known_safe` 等配置声明；OpenCode 或人工结论；变量名 / 函数名。

**必需证据字段**：`proof_code`、参与证明的访问 ID、域列表、被排除的见证及其 ProofRecord、已检查的缺口种类及结论、显式假设（如“程序无 C 未定义行为：不写 const 对象、不经不兼容类型调用函数指针”）。

### 4.3 SHARED_NO_REVIEW（共享访问，无需复核）

**定义**：r 确实被 ≥2 个可交错的物理域访问，但可以证明任何交错都不会产生破坏性结果——没有丢失更新、没有撕裂、没有中间值暴露、没有字段/元素一致性依赖、读者可见性有保证。它**不是**“不可能交错”的安全证明，但无需人工复核，不进入 OpenCode。

**门槛（全部满足）**：

| 编号 | 条件 | 现状 | 变化 |
|---|---|---|---|
| NR-01 | 运行期写者域恰好 1 个；HB 有序的初始化写不计入（前提是 §9 的健全使能模型）；写者域不可重入 | 有（不含 HB） | 加 HB |
| NR-02 | 其它域只读（包括重叠视图上的访问、未知上下文访问） | 部分 | 加重叠与未知上下文 |
| NR-03 | 单拷贝原子：规范类型是标量（整型、枚举、指针、float、bool）；`sizeof` ≤ 目标核单拷贝原子宽度；**有效对齐**（考虑 packed 与字段偏移）≥ `sizeof`；不是位域；不与更宽的 union 视图重叠写 | 拼写匹配、类型对齐 | 规范类型 + 有效对齐（FS-6、P10） |
| NR-04 | 无中间值暴露：若某读者域能抢占写者域，写者一次调用内对 r 至多存储一次（任一路径） | 无 | 新增（HR-21） |
| NR-05 | 不属于多字段 / 多元素一致性候选（§14.2 v2） | 有（同函数） | 跨函数读组（FS-2） |
| NR-06 | 无 DMA / 外设总线主机参与（DMA 域访问、DMA 证据缺口、地址发布到外设寄存器） | 仅 HAL DMA 域 | 加缺口与寄存器级（FS-9） |
| NR-07 | 证据切片无相关缺口（逃逸、别名未收敛、缺失 TU、汇编引用、未知上下文、相关的 POINTS_TO 限额位置） | **无此检查** | 新增（FS-4） |
| NR-08 | 可见性：r 为 volatile 或 C11 原子；或者每个读者访问都不在可被编译器提升的轮询循环中（循环体内无 volatile 访问、编译器屏障或不透明调用） | 无 | 新增（HR-22） |
| NR-09 | 写者不是可重入任务/回调 | 有 | 保留 |
| NR-10 | 允许写者域内 RMW（单站点事务）及“先读后写”分离站点：唯一写者不会丢失更新（现有设计决定，守门 G3 的双写者 stale snapshot 仍由双写者拦截） | 有 | 保留 |
| NR-11 | 结论附 `shared_no_review_evidence`：写者域、读者域、规范类型、尺寸、有效对齐、原子性依据（架构条款）、NR-01…NR-10 逐项结果、已检查缺口 | 部分 | 补全 |

门槛失败时：若存在相关缺口 → UNKNOWN；否则失败本身就是破坏性模式（D-08 撕裂、D-09 中间值、D-07 一致性、D-10 可见性） → SUSPECT。

### 4.4 SUSPECT（疑似并发风险）

**定义**：存在已知破坏性冲突模式的见证（能指出具体两条访问、两个域和交错方式），MHP≠NO，且该见证没有被任何证明排除。即使优先级或保护细节未恢复、或存在其它缺口，也**不得**降为 UNKNOWN；缺口作为附注保留。

| 码 | 破坏性模式 |
|---|---|
| D-01 | 跨域写-写（含 RMW）且可交错 |
| D-02 | 可重入写者（同一域自身可并发） |
| D-03 | CPU↔DMA 重叠，DMA 活动期内至少一方写 |
| D-04 | 位域组跨域写（共享存储单元的读改写） |
| D-05 | union / 重叠视图跨域写 |
| D-06 | 整对象写 ↔ 成员访问跨域 |
| D-07 | 多字段 / 多元素一致性（撕裂快照） |
| D-08 | 非原子宽度共享（NR-03 失败） |
| D-09 | 中间值暴露（NR-04 失败） |
| D-10 | 可见性（NR-08 失败） |
| D-11 | 配置所有权违例（`owner_context`，现有 `analysis.py:953-956`） |
| D-12 | NMI / HardFault 参与的写冲突（PRIMASK/BASEPRI 无法排除） |

每个 SUSPECT 输出 `destructive_codes[]`、最小见证 `witnesses[]`、`pending_confirmation`（保护待确认 / 抢占待确认）与附注缺口。

### 4.5 UNKNOWN（无法判断）

**定义**：没有已知破坏性冲突见证，但 r 的证据切片中存在**相关缺口**（§4.1）。必须附精准原因码、阻塞证据（文件 / 行 / 函数 / 事实 ID）与恢复动作；禁止宽泛兜底；工程其它位置的缺口不得进入（§6）。

原因码沿用现有 `UNKNOWN_LABELS`（`ecra/classify.py:63-74`），语义收紧：

| 原因码 | 何时相关 |
|---|---|
| UNKNOWN_ADDRESS_ESCAPE | r 的地址流入可能保留指针并异步写入的不透明代码（无库摘要的外部函数、未解析间接调用、未知汇编），且 r 非 const |
| UNKNOWN_RELEVANT_ALIAS | 指向集未收敛的位置（POINTS_TO 限额局部化后）可能指向 r 且被写 |
| UNKNOWN_RELEVANT_INDIRECT_CALL | 未解析间接调用的可能目标集合包含写 r 的函数，且该调用点上下文会给 r 增加新域 |
| UNKNOWN_RELEVANT_MISSING_TU | 缺失 / 解析失败 TU 中按名称引用了 r |
| UNKNOWN_EXECUTION_CONTEXT | 访问 r 的函数带未界定的未知入口上下文 `UNK(seed)`，且该访问满足相关性（写；或在 r 有写者时的读） |
| UNKNOWN_DMA_LIFETIME | r 被发布给 DMA / 外设，方向或活动期无法确定，且没有已知破坏性见证 |
| UNKNOWN_INLINE_ASM | 汇编按名称或操作数引用 r 且语义无法恢复 |
| UNKNOWN_SCAN_INVALID / UNKNOWN_UNMODELED_CONCURRENCY | 全局失效（保持全局，属于正当的工程级 fail-closed） |
| ACCESS_NOT_ANALYZED | 补充盘点声明（单独计数，§20.1） |

### 4.6 新裁决顺序与不变式

```text
classify(r):
  if 扫描失效 or 未建模并发:            return UNKNOWN(SCAN_INVALID | UNMODELED)
  A   ← 重叠访问集 A(r)                     # §13；扣除死函数、const 不可能写
  for a in A: ctx(a) ← 已解析上下文 ∪ UNK(seed) 抽象上下文      # §6.3
  W   ← 破坏性见证(A, 仅已解析域, MHP≠NO)  # D-01…D-07、D-11、D-12
  W   ← W − 已证明排除(W)                  # 逐对保护 / HB / DMA 生命周期 / 路径不可行（Stage B）
  G   ← 相关缺口(r, A)                      # §4.1 相关性判定
  if W: return SUSPECT(W, 附注 G)
  if G: return UNKNOWN(G)
  if 跨域 ≥2 且 运行期写者域 = 1:
      f ← 失败的 NR 守门(NR-03/04/05/08)
      if f: return SUSPECT(对应 D-08/D-09/D-07/D-10 见证)
      return SHARED_NO_REVIEW(证据)
  return SAFE_PROVEN(证明码, ProofRecords)
```

| 不变式 | 内容 | 落实方式 |
|---|---|---|
| I-1 | SAFE / NO_REVIEW 的证据切片中不存在相关缺口 | `analyze()` 末尾断言，违反即抛错（与现有归账校验同级） |
| I-2 | 存在未排除的已知破坏性见证时，只能是 SUSPECT | 同上 |
| I-3 | 每个被排除的见证都有 ProofRecord | 同上；缺失按 SUSPECT 处理 |
| I-4 | 精化只能删除见证或缺口，不能删除访问或上下文事实；删除事实只能依据“不可达 / 不可能 / HB”证明 | 代码评审 + 差分测试（§16.3） |
| I-5 | 配置只能增加上下文、入口、关系证据；`known_safe`、`protection` 声明不影响分类 | 现有语义保持，加测试 |
| I-6 | r 的分类只依赖 slice(r) | 无关缺口注入测试（扩展 T07/T09） |
| I-7 | TOTAL_BUILD = SAFE + NR + S + U，每个资源唯一归类 | 现有 `ecra/analysis.py:1094-1125` 保留 |
| I-8 | 同输入、同引擎摘要 → 同结果 | 确定性回放测试 |

---

## 5. 可安全自动排除的变量与必须保留的风险（需求 6、7）

### 5.1 可以安全自动排除的变量及其证明条件

| 编号 | 排除类别（结论） | 必须具备的证明条件 | 典型 STM32 场景 | 证据输出 |
|---|---|---|---|---|
| E-01 | 无运行期访问（SAFE_NO_RUNTIME_ACCESS） | §4.2 对应行；补充盘点声明不适用（它们是 ACCESS_NOT_ANALYZED） | 未使用的全局、仅在静态初始化器中取址且从未被解引用的表 | 访问集为空的说明 + 逃逸 / 汇编 / 外设检查结果 |
| E-02 | 只读（SAFE_READ_ONLY / MULTI_CONTEXT_READ_ONLY） | 全部重叠访问为 READ；写逃逸需库摘要证明只读；无汇编 / DMA / 外设 / 未知上下文写；const 幻影写按 C11 §6.7.3 剔除并记录假设 | 查表、常量配置、只读标定表 | 读访问列表 + 无写证明 |
| E-03 | 单一串行域（SAFE_SINGLE_*） | 全部重叠访问属于一个非重入域；无未知上下文访问；不跨多向量 | 主循环状态机、单一 ISR 私有计数、仅一个上下文使用的函数 static | 域列表 + 上下文推导链 |
| E-04 | 有序初始化（SAFE_ORDERED_INIT） | 逐竞争域 HB（§9.3）；健全使能模型（未识别机制 fail-closed）；运行期只读 | CubeMX `MX_*_Init` 中在对应 IRQ 使能前写入的句柄 `Init.*` 字段；启动校准结果 | 每个 (写, 竞争域) 的 HB 证明 |
| E-05 | 有效保护（SAFE_EFFECTIVE_PROTECTION） | 每个见证逐对被保护排除：完整 CFG、完整调用摘要、屏蔽覆盖整个事务窗口、竞争者可被屏蔽（非 NMI/HardFault；BASEPRI 阈值覆盖竞争者已证明优先级） | `__disable_irq(); x++; __enable_irq();`；`ATOMIC_BLOCK(prio)`（需优先级可证） | 每对的窗口节点、屏蔽值、竞争者优先级 |
| E-06 | 不可交错（SAFE_NON_INTERLEAVING） | 含写的跨域对全部 MHP=NO；非原子宽度的读者对也 MHP=NO | 同抢占优先级的多个定时器 ISR 共享状态 | 每对的优先级证明 |
| E-07 | 共享无需复核（SHARED_NO_REVIEW） | NR-01…NR-11 | ISR 更新、主循环读取的 32 位 volatile 计数器 / 时间戳 / 状态字 | `shared_no_review_evidence` |
| E-08 | 依赖声明（DEPENDENCY_DECLARATION，不计入 TOTAL） | 定义不在构建闭包内（现有 `ecra/analysis.py:879-900`） | 链接库 / 汇编定义的外部变量 | 盘点记录 |
| E-09 | 不可达访问剔除 | 函数被证明死亡（§6.7 收紧后的规则） | 未被任何入口、取址、汇编、链接引用的 static 函数 | 死函数证明 |
| E-10 | const 非 volatile 对象的写剔除 | C11 §6.7.3 + Cortex-M `.rodata` 位于 flash；若对象被段属性放入 RAM，该假设不成立【需进一步确认：提取器目前只记录函数属性，不记录变量段属性】 | points-to 流不敏感并集造成的幻影写 | `impossible_const_writes` 计数与样例（已有） |

不在上表中的任何“排除”都不允许实现；尤其禁止按名称、目录、类型名、注释、`volatile`、单写者本身排除。

### 5.2 必须始终保留的明显风险（硬守门，需求 7）

以下模式在任何优化后都**不得**被判为 SAFE_PROVEN 或 SHARED_NO_REVIEW。每条对应黄金风险样例（§18.3），每次改动都必须运行，任一条失守即阻断合入。

| 编号 | 风险模式 | 要求结论 | 现有测试 | 新增测试 |
|---|---|---|---|---|
| HR-01 | MAIN 运行期写 + ISR 写 | SUSPECT | G1、D05 | — （初始化写的 HB 排除须先经用户确认，§9.5） |
| HR-02 | ISR RMW + 另一 ISR 写（优先级不同或未知） | SUSPECT | G2、T06 | — |
| HR-03 | 旧快照回写（读旧值 → 他域写 → 写回） | SUSPECT | G3、D06、`test_snapshot_and_local_static_reentrancy` | — |
| HR-04 | ISR 置位 / 主循环清零标志 | SUSPECT | G4 | — |
| HR-05 | PRIMASK 只覆盖部分窗口 | SUSPECT | G5、T14、D09、`test_both_endpoints_masked_but_window_open` 等 | — |
| HR-06 | DMA 活动期 CPU 写 | SUSPECT | G6、T16 | 寄存器级版本 GR-24 |
| HR-07 | 位域组跨域写 | SUSPECT | G7 | 跨存储单元不误报 GP-07 |
| HR-08 | 整对象写 ↔ 成员访问跨域 | SUSPECT | G8 | — |
| HR-09 | value+valid 一致性（同函数） | SUSPECT | G9 | HR-09b 访问器版本 GR-09b |
| HR-10 | 函数 static 在 MAIN 与 ISR 重入 | SUSPECT | G10、T11、D07 | — |
| HR-11 | 64 位单写者共享 | SUSPECT | G11 | HR-11b 同优先级多写者 + 他域读者 GR-11b |
| HR-12 | union 重叠视图跨域写 | SUSPECT | — | GR-12 |
| HR-13 | packed 不对齐成员共享 | 不得 NO_REVIEW | — | GR-13 |
| HR-14 | 内联汇编写（操作数 / 文本） | 不得 SAFE | — | GR-14 |
| HR-15 | 未识别使能机制之后的“初始化写” | 不得 SAFE_ORDERED_INIT | — | GR-15（libopencm3、SPL、`NVIC->ISER`、无源码 BSP 各一例） |
| HR-16 | 单写者 + 地址逃逸 | UNKNOWN | — | GR-16 |
| HR-17 | NMI/HardFault 竞争者 | 保护不得 EFFECTIVE | `protection.assess` 不可屏蔽分支 | GR-17 |
| HR-18 | BASEPRI 阈值未覆盖更高优先级 ISR | SUSPECT | `test_more_urgent_irq_is_not_masked` | — |
| HR-19 | DMB/DSB/ISB 当作保护 | SUSPECT | D18 | — |
| HR-20 | 未配置的锁名当作保护 | SUSPECT | D17 | — |
| HR-21 | 中间值暴露（`idx++; if (idx>=N) idx=0;` + 高优先级读者） | SUSPECT | — | GR-21 |
| HR-22 | 非 volatile 轮询标志（ISR 置位、主循环 `while(!flag)`） | SUSPECT | — | GR-22 |
| HR-23 | 可重入任务 / 回调写者 | SUSPECT | `test_reentrant_single_write_remains_candidate` | — |
| HR-24 | 寄存器级 DMA 缓冲 | 不得 SAFE | — | GR-24 |
| HR-25 | 句柄回调跨实例：身份无法证明时保留全部上下文 | 不得因裁剪变 SAFE | — | GR-25 |
| HR-26 | 未知上下文读非原子 / 一致性变量 | 不得 SAFE | — | GR-26 |
| HR-27 | 库函数经指针写（`strcpy(gp, ...)`） | 不得 SAFE | — | GR-27 |
| HR-28 | 逆序路径同名误归属 | 写必须落到正确成员 | — | GR-28 |
| HR-29 | 同一处理函数挂在不同优先级的多个向量 | 按可重入处理 | — | GR-29 |
| HR-30 | SysTick / PendSV 与外部 IRQ 冲突（系统异常优先级未证明） | 按可交错处理 | — | GR-30 |
| HR-31 | 配置所有权违例 | SUSPECT | 现有 `GS-OWNER-VIOLATION` 路径 | — |

---

> **§6–§15 的写法约定**：每个优化点编号为 OPT-xx，并给出四项内容——**为什么需要 / 当前代码问题 / 计划如何解决 / 如何验证**，以及优先级（P0 强制、P1 重要、P2 可选）和实施阶段（§22）。阶段编号：0 度量与基线；1 健全性修复；2 资源粒度与证据精度；3 控制流与保护；4 上下文精度；5 时序与硬件；6 两阶段精化；7 多工程验证与验收。

## 6. 变量局部 UNKNOWN：避免无关未知信息扩散（需求 8）

### 6.1 现状评估

已经是变量局部的部分（保留并加测试）：地址逃逸按变量记录（`ecra/classify.py:296-353`）；变量绑定未知（`SYMBOL_UNKNOWN_CODES`）、解析失败、定义缺失按变量判断；T07、T09、`test_unknown_reason_codes_are_precise_and_local` 已守护“无关函数指针 / 其它 TU 解析失败不传播”。

仍然**非局部**的四个机制：

| 机制 | 代码 | 后果 |
|---|---|---|
| 入口不确定性函数级前向传播 | `classify.py:357-389` | 公共被调函数整体变“未知上下文”（RC-6，P5） |
| `POINTS_TO_LIMIT` 全局缺口 | `classify.py:792-793` | 一旦触发，所有变量带 UNKNOWN_RELEVANT_ALIAS |
| 闭包不完整 → 全部外部链接对象地址逃逸 | `classify.py:309-312` | 与缺失源码无关的对象也逃逸 |
| 存在任何不透明代码 → 外部函数不能证明死亡 | `classify.py:424-427` | 无入口的外部函数访问一律“无上下文” |

同时存在一个**相反方向的健全性缺口**：未知上下文中的**读**被完全忽略（`classify.py:777-813` 只把写计为缺口），见 FS-8 / 探针 P30。

### 6.2 证据切片的形式定义

```text
slice(r) = Acc(r)                         重叠访问集（§4.1）
         ∪ Ctx(r)                         Acc(r) 中各函数的上下文推导：绑定链上的每条边、边种类、may-target 扇出
         ∪ Ptr(r)                         指向集包含 r 且被解引用的指针位置
         ∪ Esc(r)                         r 的地址流入的调用 / 汇编 / 外设寄存器
         ∪ Asm(r)                         按名称或操作数引用 r 的汇编
         ∪ Dma(r)                         发布 r 地址的 DMA 契约或寄存器写
         ∪ Prem(r)                        r 的证明所依赖的前提事实（使能事件、屏蔽窗口节点、优先级事件、死函数证明）
```

缺口 g 进入 r 的 UNKNOWN，当且仅当 g ∈ slice(r) 且满足 §4.1 的相关性条件。实现上，每个缺口记录 `slice_path`（经哪条事实进入切片）与 `relevance`（哪一条相关性成立），写入 `gap_evidence`，供 §21 统计。

### 6.3 OPT-17（P0，阶段 1）未知上下文读访问参与判定

- **为什么需要**：未知入口的函数可能是 ISR；它读取前台写入的非原子变量或一致性字段组时会撕裂（FS-8）。
- **当前代码问题**：`unresolved_context` 中只有写入进入缺口（`classify.py:806-813`），读访问既不计入域、也不产生缺口，【探针 P30】中 64 位 `stamp` 被判 SAFE_SINGLE_FOREGROUND。
- **计划如何解决**：未知上下文中的读，在下列任一条件成立时作为相关缺口（UNKNOWN_EXECUTION_CONTEXT）：r 有写者且 r 不满足 NR-03（非原子）；r 属于一致性候选组；r 不满足 NR-08（可见性）。r 有写者、原子、无一致性关系时，未知只读者不改变结论的安全性，但 r 不再是“单域”，结论从 SAFE_SINGLE_* 改为 SHARED_NO_REVIEW（证据中注明“存在未知上下文只读者”）。
- **如何验证**：P30 在 OPT-41 之前必须为 UNKNOWN（OPT-41 证明 `cb` 没有任何可能调用者之后可为 SAFE）；GR-26（回调地址交给无源码注册函数、无法界定的变体）任何阶段都必须为 UNKNOWN；原子宽度版本应为 SHARED_NO_REVIEW；T05、T12 结论不变。

### 6.4 OPT-40（P1，阶段 4）以抽象上下文 UNK(seed) 取代函数级污染

- **为什么需要**：RC-6；blackmagic 47 个 UEC 中 43 个、klipper 6/6 的写入函数有完整已知上下文，未知性只是“可能再多一个入口”。
- **当前代码问题**：`_entry_uncertain_functions` 把种子沿调用图传给所有被调函数，`classify()` 把这些函数中的任何写入都视为“上下文未知”。
- **计划如何解决**：
  1. 为每个种子函数 s 创建抽象上下文 `UNK(s)`（kind=`UNKNOWN_ENTRY`），与真实上下文走同一套 BFS 传播；函数的上下文集合 = 已解析上下文 ∪ {UNK(s)…}，已解析上下文保持不变。
  2. 裁决：已解析域之间的破坏性见证照常优先判 SUSPECT（保持现有“破坏性冲突优先于未知写者”的顺序）；`UNK` 上的访问按 §4.1 相关性成为缺口：`UNK` 写总是相关；`UNK` 读按 OPT-17 判定。
  3. 若 OPT-41 能把 `UNK(s)` 界定为具体上下文集合，就用该集合替换，绑定的 provenance 记为 `DISPATCH_BOUND`。
- **如何验证**：P5 中 `log_write` 的上下文应为 {main, UNK(cb)}；在 OPT-41 证明 `cb` 无可能调用者之前，`shared_log_idx` 仍为 UNKNOWN（`UNK` 写相关），之后变为 SAFE_SINGLE_FOREGROUND；新增测试“已知 ISR 双写 + UNK 写”必须仍为 SUSPECT。

### 6.5 OPT-41（P1，阶段 4）分派点上下文界定（未知入口的健全上界）

- **为什么需要**：把 UNKNOWN_EXECUTION_CONTEXT 转换为具体上下文，是 blackmagic UNKNOWN 的主要降噪来源（命令表、目标驱动回调）。
- **当前代码问题**：只要函数取址但没有被 points-to 解析到任何分派点，就视为“可能从任意上下文进入”。
- **计划如何解决**：在 C 语义下，函数 f 只能经以下途径被调用：（a）直接调用；（b）间接调用点，其被调表达式的值可能为 `fn:f`；（c）获得 f 地址的不透明代码（无源码库、未知汇编）；（d）硬件向量（启动文件 / 向量表 / VTOR 发布 / 链接脚本引用）。据此：

  ```text
  bound(f) = ⋃ { ctx(site) | site 是未解析的间接调用点，且其函数指针类型与 f 兼容（OPT-42） }
           ∪ { 已解析且目标含 f 的间接调用点上下文 }               # 已有
           ∪ { HW_VECTOR(f) | f 出现在向量表证据中（OPT-46）}
           ∪ { ANY        | f 的地址流入不透明代码或未知汇编 }
  若 ANY ∉ bound(f)：UNK(f) := bound(f)；若 bound(f) = ∅：f 只能经已解析路径进入（可能为死函数）
  ```

  前提条件（任一不满足即保持 UNK）：构建闭包完整（无缺失 TU / 解析失败 / 未展开汇编）；f 的地址没有流入不透明代码；向量表证据检查完成。
- **如何验证**：P5、P30 的 `cb` 无任何间接调用点 → bound=∅；同一用例加 `SCB->VTOR = (uint32_t)table;` 后 `cb` 必须成为 ISR 上下文（GR-26 变体）；blackmagic 重放统计 UEC 变量转换情况，并对转换为 SAFE 的变量 100% 列出证明、抽样核对（§16.3）。

### 6.6 OPT-45（P2，阶段 4）`POINTS_TO_LIMIT` 与闭包不完整逃逸的局部化

- **为什么需要**：两者都是工程级缺口，会一次性污染所有变量。
- **当前代码问题**：`Solver.solve` 以“全量重扫约束 ≤1000 轮”迭代（`ecra/points_to.py:105-117`），超限即追加全局 `POINTS_TO_LIMIT`；闭包不完整时，所有外部链接对象中的地址都算逃逸（`classify.py:309-312`）。
- **计划如何解决**：（1）改为差分传播工作表算法，减少触发限额的概率；仍超限时记录“最后一轮仍在变化的位置集合”，只有指向集依赖这些位置的变量才得到 UNKNOWN_RELEVANT_ALIAS。（2）闭包不完整时，只有在缺失源码中按名称出现的外部对象（缺失源码词法扫描已计算名称集合，`ecra/analysis.py:639-658`）才算“可按名称获得”。
- **如何验证**：构造不收敛用例，确认只影响相关变量；构造缺失 TU 用例，确认未被缺失源码引用的外部对象不逃逸；三工程重放中确认不出现新的全局缺口。

### 6.7 OPT-47（P2，阶段 4）外部函数死亡证明的收紧

- **为什么需要**：无入口外部函数中的写入被当作“未知上下文写入”。klipper 有 2104 个 UNKNOWN_ENTRY 函数，其中有多少包含对审计变量的访问【需进一步确认：按函数统计访问数】。
- **当前代码问题**：存在任何不透明代码时，所有外部链接函数都作为根（`classify.py:424-427`）。
- **计划如何解决**：区分不透明代码种类：未解析间接调用只能调用“地址被取过”的函数（C 语义），不能让未取址函数成为根；无源码外部库只能按名称调用用户函数——只有提供链接 map（`--cref`）或 ELF 重定位证据（OPT-82，可选输入）时才能证明某函数不被库引用，否则保持保守。
- **如何验证**：未取址、无调用的外部函数在“只有未解析间接调用、无外部库”时被证明死亡；存在外部库且无 map 时保持现状；提供 map 时按交叉引用表判断。

---

## 7. FOREGROUND、ISR、DMA 等物理执行上下文建模（需求 9）

### 7.1 现状

| 种类 | 来源 | 代码 |
|---|---|---|
| FOREGROUND | 配置的 MAIN；`main / reset_handler / Reset_Handler / ResetHandler`；`execution_domain` 声明 | `analysis.py:15, 108-114`；`classify.py:30-47` |
| ISR | 无参 `*IRQHandler`（排除 `HAL_*`）与系统异常名单；无参、无调用者的小写 `*_isr / *_irq / *_handler`；`NVIC_SetVector` 注册；配置 | `analysis.py:106-125`；`points_to.py:310-313` |
| TASK / TIMER / DEFERRED | RTOS 注册 API；配置 | `analysis.py:130-174` |
| DMA | 5 个 HAL DMA API，共用 `dma_rx / dma_tx` | `points_to.py:342-369` |

缺失：上下文没有优先级、可屏蔽性、向量号属性（不可屏蔽仅按 `NMI_Handler / HardFault_Handler` 名称判断，`analysis.py:823-826`）；SysTick / PendSV / SVC 的可配置优先级未建模；同一处理函数挂在多个向量时不视为可重入；DMA 通道身份、寄存器级 DMA、其它总线主机（USB OTG 内部 DMA、ETH DMA、SDIO）未建模。

### 7.2 OPT-48（P1，阶段 4）物理执行域记录

- **为什么需要**：MHP、保护、HB、方向相关守门（NR-04、§14.2 方向规则）都需要域的优先级与可屏蔽性。
- **当前代码问题**：域只是一个字符串 ID（`context_domains`），属性散落在 `interrupts.py`、`protection.py`。
- **计划如何解决**：新增 `Domain` 记录：

  | 字段 | 含义 |
  |---|---|
  | `domain_id` / `kind` | `FOREGROUND`、`ISR`、`SYSTEM_EXCEPTION`（SysTick/PendSV/SVC/DebugMon）、`FAULT_UNMASKABLE`（NMI/HardFault）、`FAULT`（MemManage/BusFault/UsageFault）、`DMA_ENGINE`、`HW_MASTER`、`TASK`、`UNKNOWN_ENTRY` |
  | `vector` | 异常号 / IRQn（来自 OPT-46 向量表或 CMSIS 名称） |
  | `priority` | `{status: PROVEN/UNKNOWN, preempt, sub, evidence}`（OPT-51） |
  | `maskable_by` | `PRIMASK: bool`、`BASEPRI: 依优先级`、`FAULTMASK: bool` |
  | `run_to_completion` | ISR / 系统异常为真；FOREGROUND 为假（可被抢占） |
  | `reentrant` | 可重入任务；同一处理函数位于不同优先级的多个向量 |
  | `provenance` | 根的发现方式与证据（配置 / 命名 / 向量表 / 注册 / DMA 契约 / 寄存器发布） |

  域合并规则不变：所有 MAIN 与声明为 `FOREGROUND` 的协作任务合并为一个前台域；每个向量一个域；同一处理函数挂在多个向量时每个向量各一个域，且若优先级可能不同则在函数级标记“自重入”（HR-29）。
- **如何验证**：每个种类各一条单元测试；`unmaskable` 判断改由 `Domain.kind` 驱动后，`test_design_acceptance` 中 NMI/HardFault 相关测试结论不变。

### 7.3 OPT-46（P1，阶段 4）向量表解析

- **为什么需要**：ISR 身份目前依赖命名约定；IRQ 号到处理函数的映射依赖 `irq_key()` 的名称规整（`ecra/interrupts.py:11-12`），对非 CMSIS 命名不可用；也影响 OPT-41 的硬件入口证据与 OPT-50 的逐 IRQ 使能。
- **当前代码问题**：汇编源只做标识符级扫描（`analysis.py:588-604`），不解析 `.isr_vector` 中 `.word` 的顺序；C 定义的向量数组与 `SCB->VTOR` 重定位不被识别。
- **计划如何解决**：（1）解析启动汇编 `.section .isr_vector` 中 `.word` 序列，按序号得到异常号 → 处理函数；`.weak/.thumb_set` 别名到同一默认处理函数时记录“多向量共享”。（2）C 数组：带 `section` 属性（需提取器记录变量属性）或地址被发布到 `SCB->VTOR`（OPT-18 的寄存器发布识别）的函数指针数组，元素按下标映射。（3）链接脚本做文本级符号引用扫描（仅作为“硬件可能引用”的证据）。命名约定保留为补充来源，冲突时以向量表为准并记录。
- **如何验证**：用 STM32CubeF4 风格 `startup_stm32f405xx.s` 与 libopencm3 风格 C 向量表各写一组测试；非标准命名的处理函数必须被识别为 ISR；VTOR 重定位用例中表内函数成为 ISR。

### 7.4 OPT-18（P0，阶段 1）DMA 与外设总线主机：地址发布识别

- **为什么需要**：FS-9（寄存器级 DMA 缓冲被判只读安全）。非 HAL 的 STM32 工程（SPL、LL、libopencm3、寄存器级）都通过把内存地址写入外设寄存器来配置 DMA。
- **当前代码问题**：只认 5 个 HAL API（`points_to.py:342-369`）；整数常量强转得到的外设指针在 points-to 中没有位置（`pointer_extract.py:52-77` 对整数常量返回 `empty`），对外设寄存器的存储被丢弃。
- **计划如何解决**：
  1. 在 PointerExtractor 中为“整数常量强转为指针”引入抽象位置 `mmio:<地址>`；对其的字段访问、数组访问、指针算术保持 `mmio:` 前缀。
  2. **地址发布事实** `HW_ADDRESS_PUBLISH(obj, mmio_target, site)`：一个包含 `obj:<sid>` 的值被存入 `mmio:` 位置（或存入随后整体传给已知 DMA 初始化 API 的结构字段，例如 SPL 初始化结构的内存地址字段）。STM32 外设地址区间 0x4000_0000–0x5FFF_FFFF、系统控制空间 0xE000_E000–0xE000_EFFF 作为通用硬件事实；地址不可求值时按“可能是外设”保守处理。
  3. 被发布的对象获得一个 `DMA_ENGINE` / `HW_MASTER` 域的访问（方向可由已知契约或寄存器语义确定，否则 READ+WRITE），范围为整个对象（长度可求值时取发布长度）。
  4. 收紧名称启发：`extract.py:493-499` 只对**按地址**传递（`&x`、数组退化、指针值）的实参生效，按值传递不再产生 `DMA_SHARED_REVIEW`（修 P26 的过宽）。
  5. DMA 域身份：能求出控制器 / 流号时每个流一个域，否则每个发布点一个域（取代共用的 `dma_rx/dma_tx`）。
- **如何验证**：GR-24（P31 必须不是 SAFE）；SPL `DMA_Init(&init)` 用例、LL `LL_DMA_SetMemoryAddress` 用例、libopencm3 `dma_set_memory_address` 用例；VTOR 发布用例被识别为向量表而不是 DMA；betaflight 重放后统计新增的 DMA 相关 S/U，单列为“健全性修复引起的上升”。

---

## 8. Single Writer + Reader 的精确降噪（需求 10）

### 8.1 现状与缺陷

现有规则（`classify.py:887-924`）：唯一写者域 + 其余域只读 + 宽度可识别 + 对齐 ≥ 宽度 → SHARED_NO_REVIEW。缺陷：宽度按拼写匹配（P10）、对齐取类型对齐（P27）、不检查缺口（P25）、同类结构在 `_safe_rule` 中的多写者 SERIAL 分支不检查读者撕裂（P28）、缺少中间值 / 可见性 / 多元素守门。三工程中 NO_REVIEW 只有 0 / 9 / 68 个，说明大量“单写者 + 读者”变量因其它机制（RC-1、RC-2、RC-3）根本走不到这条规则——本章的修复首先是健全性，其次才是精度。

### 8.2 OPT-10（P0，阶段 1）NO_REVIEW 前必须检查相关缺口

- **为什么需要**：FS-4，且原因文本与事实不符（声称“无地址逃逸”）。
- **当前代码问题**：门槛通过即返回（`classify.py:916-924`），`gaps` 只在门槛失败时检查（`:907`）。
- **计划如何解决**：在单写者分支之前插入“相关缺口 → UNKNOWN”（与 §4.6 顺序一致）；原因文本改为逐项列出 NR 检查结果，而非固定文案。
- **如何验证**：GR-16（P25 → UNKNOWN）；T04、T05、T17、T18 结论不变；blackmagic 9 个 NO_REVIEW 重放后逐个列出变化原因。

### 8.3 OPT-15（P0，阶段 1）有效对齐

- **为什么需要**：FS-6。Cortex-M3/M4/M7 的非对齐字访问会被拆成多次总线访问，不是单拷贝原子；M0/M0+ 直接 HardFault。
- **当前代码问题**：成员对齐取字段类型对齐（`extract.py:220`），不看字段偏移和 packed。
- **计划如何解决**：提取器为每个成员记录 `bit_offset`（libclang `Cursor.get_field_offsetof()`）与所在记录的 packed / aligned 属性；有效对齐 = min(类型对齐, 由根对象对齐与字节偏移推出的最大 2 的幂)。顶层变量取声明对齐（含 `__attribute__((aligned))`）。
- **如何验证**：GR-13（P27 不得 NO_REVIEW）；非 packed 结构的成员结论不变。

### 8.4 OPT-16（P0，阶段 1）SAFE_NON_INTERLEAVING 的读者撕裂检查

- **为什么需要**：FS-7。
- **当前代码问题**：`_safe_rule` 在“多写者且写-写对全部不可交错”时直接返回安全（`classify.py:962-963`），不看写者与其它域读者之间的关系。
- **计划如何解决**：只有当**所有含写的跨域对**（包括写-读对）都 MHP=NO 时才是 SAFE_NON_INTERLEAVING；否则把互相串行的写者域视为一个“写者组”，对写者组与读者域套用 NR-03/04/05/08：全部满足 → SHARED_NO_REVIEW，否则 SUSPECT（D-08 等）。
- **如何验证**：GR-11b（P28 → SUSPECT）；32 位同构用例 → SHARED_NO_REVIEW；现有 SERIAL 相关测试结论不变。

### 8.5 OPT-22（P1，阶段 2）规范类型宽度判定

- **为什么需要**：RC-10；STM32 工程中 typedef 标量（`uint32_t` 的二次 typedef、`timeUs_t`）与枚举状态（HAL 的 `HAL_UART_StateTypeDef gState`）非常普遍。
- **当前代码问题**：`_element_width` 用类型拼写与 `_SCALAR_WIDTHS` 匹配（`classify.py:712-738`）。
- **计划如何解决**：提取器记录 `canonical_kind`（libclang 规范类型种类：BOOL/CHAR/INT/UINT/LONG/…/FLOAT/DOUBLE/ENUM/POINTER/RECORD/CONSTANTARRAY）与数组元素的规范种类、尺寸；宽度 = 规范标量种类的 `sizeof`（枚举尺寸由 libclang 按目标参数如 `-fshort-enums` 给出）；非标量返回 None。单拷贝原子宽度按 `project.core` 取值（M0/M0+/M3/M4/M7/M33 均为 32 位，64 位类型永不原子），`native_word_bits` 保留为显式覆盖。
- **如何验证**：P10 中 `timeUs_t`、`mode_e` → SHARED_NO_REVIEW；`uint64_t` 的 typedef → SUSPECT（G11 不变）；`-fshort-enums` 下的枚举宽度测试。

### 8.6 OPT-25（P1，阶段 2）NR 新守门：中间值暴露、可见性、多元素快照

- **为什么需要**：HR-21、HR-22 以及数组整体读的撕裂；它们是真实且常见的嵌入式缺陷，现有规则会把它们判为 NO_REVIEW。
- **当前代码问题**：NR 只看“单写者 + 原子宽度”。
- **计划如何解决**：
  1. **NR-04 中间值暴露**：若某读者域可以抢占写者域（读者为更高或未知优先级的 ISR；写者为 FOREGROUND 时总是成立），且写者一次调用内（含被调函数，依 OPT-53 摘要）对 r 存在 ≥2 次存储的路径 → D-09。写者为 ISR、读者为更低优先级时不适用（ISR 运行到完成，读者看不到中间值）。CFG 不完整时按“同一调用内 ≥2 个写站点”保守判断。
  2. **NR-08 可见性**：r 非 volatile、非原子，且某读者访问位于循环内，循环体内无对 r 的 volatile 访问、无编译器屏障（`asm volatile` 带 `memory` clobber、`__DMB/__DSB/__ISB`）、无不透明调用 → D-10。
  3. **多元素快照**：数组资源的写者一次调用写 ≥2 个元素（循环或多站点），读者一次调用读 ≥2 个元素（循环 / 块拷贝）→ 作为一致性候选（D-07）。
- **如何验证**：GR-21、GR-22、多元素快照用例必须 SUSPECT；T18（单元素读）仍为 SHARED_NO_REVIEW；这三项可能使 S 上升，基准中单列。

### 8.7 原子性依据（实现时须按 Arm 架构手册条文复核）

| 访问 | M0/M0+（ARMv6-M） | M3/M4/M7（ARMv7-M）/ M33（ARMv8-M） | NR-03 |
|---|---|---|---|
| 对齐的字节 / 半字 / 字 | 单拷贝原子 | 单拷贝原子 | 可 |
| 非对齐半字 / 字 | 触发 HardFault | 允许（LDR/STR/LDRH/STRH），不是单拷贝原子 | 不可 |
| 64 位（LDRD/STRD、LDM/STM、`uint64_t`、`double`） | 拆为多次字访问 | 每个字原子，整体不原子 | 不可 |
| 单精度浮点 VLDR/VSTR（S 寄存器，对齐） | — | 单拷贝原子 | 可 |
| 位域写 | 容器读改写 | 容器读改写 | 不可（D-04） |

依据：Arm ARMv6-M / ARMv7-M Architecture Reference Manual 的 “Atomicity in the ARM architecture” 一节（§A3.5.3）【需在实现时逐条复核条文】。

---

## 9. Init / Runtime 阶段分析（需求 11）

### 9.1 现状与缺陷

现有相位模型（`classify.py:528-707`）：PRE = main 入口出发、任一“已识别异步使能 API”（`ASYNC_ENABLE_APIS`，`:122-136`）之前；PRE 写者只能在“全部写者都是 PRE”时整体降噪（`:832-836`），否则照常计入冲突（守门 G5）。问题：（1）不区分中断源（P24）；（2）使能识别是封闭名单，对未识别机制不健全（P9 / FS-3）；（3）CubeMX 工程 `HAL_Init()` 先开 SysTick，初始化窗口几乎为空。

### 9.2 OPT-13（P0，阶段 1）健全的使能事件模型（fail-closed）

- **为什么需要**：FS-3。PRE 证明直接产生 SAFE_INIT_ONLY_WRITE，并让一致性检查跳过 PRE 写（`analysis.py:852-860`），不健全时会掩盖真实风险。
- **当前代码问题**：只要调用不在名单中，就被当作“不会使能中断”；无源码的外部函数、未解析间接调用、未知汇编、直接寄存器写都不阻断 PRE。
- **计划如何解决**：定义 `EnableEvent{kind, irq, site, evidence}`：

  | kind | 识别依据（通用标准语义） |
  |---|---|
  | `NVIC_IRQ_ENABLE(irq)` | CMSIS `NVIC_EnableIRQ`、HAL `HAL_NVIC_EnableIRQ`、libopencm3 `nvic_enable_irq`、SPL `NVIC_Init`（初始化结构中 `NVIC_IRQChannelCmd=ENABLE`，通道号可求值时具体化）、直接写 `NVIC->ISER[k]`（掩码常量时具体化） |
  | `SYSTICK_ENABLE` | `SysTick_Config`、`HAL_SYSTICK_Config`、`HAL_InitTick`、libopencm3 `systick_interrupt_enable / systick_counter_enable`、`LL_SYSTICK_EnableIT`、直接写 `SysTick->CTRL` |
  | `GLOBAL_UNMASK` | `__enable_irq`、`__set_PRIMASK(0)`、`cpsie i`、降低 BASEPRI（复位时 PRIMASK 已为 0，保守地仍视为使能事件） |
  | `DYNAMIC_VECTOR` | `NVIC_SetVector`、写 `SCB->VTOR` |
  | `RTOS_START` | `vTaskStartScheduler`、`osKernelStart` 等（现有） |
  | `UNKNOWN_MAY_ENABLE` | 调用无函数体且无语义摘要的外部函数；未解析间接调用；语义未知的内联汇编；对系统控制空间或地址不可求值的 `mmio:` 位置的写 |

  规则：任何 `EnableEvent`（含 `UNKNOWN_MAY_ENABLE`）都阻断其后的 PRE；处理函数存在但找不到任何使能事件的 IRQ，视为“复位即可能使能”（因为可能经未识别途径使能）。函数级效果（是否可能使能、使能哪些 IRQ）进入 OPT-53 摘要，取代 `_build_phase_model` 中基于名单的 `may_enable` 反向传播。
- **如何验证**：GR-15 四个变体（libopencm3、SPL、`NVIC->ISER`、无源码 BSP）都不得 SAFE_ORDERED_INIT / SAFE_INIT_ONLY_WRITE；`test_init_write_before_enable_is_safe_init_only` 等三条现有测试结论不变；betaflight SAFE_INIT_ONLY_WRITE（272）的变化逐个列出原因。

### 9.3 OPT-50（P1，阶段 5）逐竞争域 happens-before

- **为什么需要**：P24、HAL 句柄初始化字段、blackmagic `st_usbfs_dev.*`（初始化写 + USB ISR）这类“初始化与某个中断有序”的情形。
- **当前代码问题**：只有“全局首个使能”一条时间线。
- **计划如何解决**：
  - 定义：前台写站点 w 与竞争域 X，`w ≺ X` 当且仅当从复位到 w 的每条路径上都没有发生“可能使能 X”的事件，且 w 不在“X 可能已使能”之后的循环迭代中。NMI/HardFault 与“复位即可能使能”的 IRQ 永不满足。
  - 算法：在前台过程间 CFG 上做前向“可能已使能集合”数据流。状态 = 可能已使能的竞争域集合 ∪ {ANY}；`NVIC_IRQ_ENABLE(x)` 加入 x；`SYSTICK_ENABLE` 加入 SysTick；`GLOBAL_UNMASK`、`UNKNOWN_MAY_ENABLE` 加入 ANY；调用点用被调函数摘要；循环取不动点；被多处调用的函数入口状态取各调用点的并集。CFG 不完整时退化为现有的“偏移 + 循环守卫”保守判定（`classify.py:595-611`）。
  - 用途：（A）**SAFE_ORDERED_INIT**：r 的全部写都在前台，且对 r 的每个其它访问域 X 都有 `w ≺ X`，运行期只读；（B）**逐对排除**：写-写对（前台 w，X 中的写）在 `w ≺ X` 时不构成冲突；写-读对同理不构成撕裂。之后对剩余的运行期写者集合套用 NR 门槛。
  - 复杂度：一次前台数据流 + 每个写站点查表；竞争域集合用位向量。
- **如何验证**：P24 在（B）启用时为 SHARED_NO_REVIEW，仅（A）时保持 SUSPECT；运行期重新初始化（错误处理中 `HAL_UART_DeInit/Init`）必须不被排除；使能在循环中的用例不被排除；blackmagic 重放统计 `st_usbfs_dev.*` 的变化并抽样核对。

### 9.4 与守门 G5 / HR-01 的关系（需用户确认）

1. Phase 2 的回滚（`docs/classifier_progress.md:114-122`）使用的是不健全的全局模型：G5 中 `value = 1` 位于 `__enable_irq()` 之前，但 TIM4 的 NVIC 使能从未出现。按 §9.2 的规则 TIM4 属于“复位即可能使能”，`value = 1` 不满足 `≺ TIM4`，G5 仍为 SUSPECT；T13、D08 是 PRIMASK 保护用例，与 HB 无关。因此预期（B）不会破坏这些测试——须在实现时以测试确认。
2. 但 HR-01 的原始表述是“MAIN WRITE + ISR WRITE ⇒ SUSPECT，任何优化都不能绕过”。逐对排除（B）实际上把 HR-01 解释为“**可并发的** MAIN 写 + ISR 写”。HB 有序的初始化写按硬件语义（NVIC 使能之前该 ISR 不可能执行）不可并发，但这改变了守门的字面含义。
3. **决策请求**：默认只实现（A）（不改变任何守门的字面含义）；用户确认 HR-01 的解释后，再以影子模式（§15.6）启用（B），影子期结论与（A）并列输出、逐个审计，审计通过后切换。

### 9.5 OPT-80（P2，阶段 5 之后）外设中断源级次序

- **为什么需要**：CubeMX 工程在 `HAL_UART_MspInit` 等函数中很早就使能了外设的 NVIC 中断，但外设真正能触发中断要等到中断源位（如 `RXNEIE / TXEIE / TCIE`）被打开（`HAL_UART_Receive_IT`、`__HAL_UART_ENABLE_IT`、`HAL_DMA_Start_IT`）。§3.6 中 5 个 SUSPECT（`Cli_Init` 中 `memset` 的初始化写）和 9 个 HAL 内部协议字段都依赖这一层次序，仅靠 NVIC 级 HB 无法证明。
- **当前代码问题**：不存在外设寄存器状态模型；HAL 宏展开后的 `SET_BIT(huart->Instance->CR1, …)` 只是对 `mmio:` 位置（OPT-18 之后）的写。
- **计划如何解决**（研究型，默认不启用）：
  1. 识别 ISR 内“由中断源位守卫的分支”：条件形如 `(flags & FLAG) && (cr_reg & IE_BIT)`，其中 `cr_reg` 读自 `Instance->CRx`；
  2. 在前台过程间 CFG 上做“外设中断源位可能已开启”的数据流（位掩码常量求值；`Instance` 由 HSCP 绑定与初始化后常量确定）；
  3. 前台写 w 对“ISR 中受 IE_BIT 守卫的代码”满足 HB，当且仅当 w 之前所有路径上该 IE_BIT 都不可能已开启，且该守卫是到达相关访问的必经条件；
  4. 外设实例、寄存器偏移、位掩码任一不可求值 → 不排除。
- **风险与边界**：涉及寄存器语义与 HAL 版本差异，复杂度高；必须在影子模式下逐条审计；不能用“库可信”代替证明——若用户希望把“只被审计范围外库代码访问的句柄内部字段”单独处理，属于审计范围的语义变更，需要用户决定（§24 Q-18），本规划默认不做。
- **如何验证**：CubeMX 黄金工程中 `Cli_Init` 型初始化写、`HAL_UART_Receive_IT` 启动前的缓冲区写可被排除；在 ISR 中重新打开中断源、错误中断（`EIE/PEIE`）提前开启、DMA 循环模式三类用例必须保持 SUSPECT。

---

## 10. Alias、Pointer、Function Pointer、Mod/Ref、NoEscape 精化（需求 12）

### 10.1 现状

- points-to：Andersen 风格包含式约束，流不敏感、上下文不敏感、字段敏感、数组下标不敏感，堆对象按分配站点区分（`ecra/points_to.py:82-102`），≤1000 轮迭代。
- 提取器局部别名：函数内流不敏感，只记录别名 → root（`ecra/extract.py:397-421`）。
- 对象敏感归属：经形参的数据访问按调用点重新求值，一层（`points_to.py:245-281`）。
- 逃逸：指向集流入未定义函数形参 / 闭包不完整时的外部链接对象（`classify.py:296-329`）；取址表达式落在未解析调用区间（`:345-353`）；地址经已解析函数流入未解析间接调用（`UNRESOLVED_CALL_ESCAPE`，`points_to.py:118-139`）。

### 10.2 OPT-20（P0，阶段 2）访问路径代数（修 RC-3、FS-11）

- **为什么需要**：RC-3 是 blackmagic SUSPECT 的主要误判来源之一（3339 行继承访问、≤19 个 SUSPECT），也是一致性放大的来源；且有低概率误归属风险。
- **当前代码问题**：`access_mode` 的逆序拼接（`extract.py:330`）；局部别名不带基路径（`:411-419`）。
- **计划如何解决**：
  1. 路径表示为步骤元组：`Field(name) | Elem(*)`（OPT-44 后增加 `Elem(k)`）；`access_mode` 由内向外收集后按正确顺序拼接，`[]` 依附于前一个字段（`s.buf[i] → buf[]`）。
  2. 局部别名映射为 `别名 → {(root_sid, base_path)}`：`p = &s.inner → (s, [inner])`；`p = s.arr → (s, [arr, Elem])`；`p = &s → (s, [])`。经别名的访问路径 = 基路径 + 相对路径。
  3. 无法解析到成员的访问（与成员布局不符的类型双关）仍回退整对象，但记录 `fallback_reason` 并计入统计，不再静默。
  4. **解引用终止左值链（修 M-40）**：路径中遇到“指针类型成员 + `->` / `*` 解引用”时，该成员本身只是被**读取**（作为地址），写 / RMW 作用于被指向对象（由 points-to 归属到 `obj:` 或 `mmio:` 位置）。`PointerExtractor.mode()`（`ecra/pointer_extract.py:128-145`）对 `MEMBER_REF_EXPR` 祖先无条件 `continue` 的逻辑改为：父节点以指针解引用方式使用当前节点的值时返回 READ；`extract.access_mode` 中间成员为指针类型时同理截断。
- **如何验证**：GR-28（误归属用例）；P1、P2、P32 每条访问都落到正确成员；P33 中 `huart2.Instance` 在 ISR 中只有 READ、`fake_usart.CR1` 有 RMW；三工程与 HAL 工程（§3.6）重放中回退行应只剩真实类型双关（逐条列出）；继承行数量与一致性成员数变化单列。

### 10.3 OPT-19（P0，阶段 1）标准库语义统一

- **为什么需要**：FS-10；三处语义表不一致是潜在的 false-safe 来源。
- **当前代码问题**：`extract.py:472-492` 用 16 函数表，`points_to.py:148-152` 用旧 4 函数表，`classify.py:315` 用 USR 与裸名比较。
- **计划如何解决**：唯一语义表（`ecra/common.py:88-107` 扩展为结构化条目：参数方向、是否保留指针、长度参数位置）；提取器、points-to、逃逸判定统一按**被调函数名**查表；points-to 对指针实参按方向生成访问（目的指针的指向对象 WRITE、源 READ；长度可求值时限定范围）；只有当表中声明“不保留指针”时，地址流入该函数才不构成逃逸。可变参数函数（printf 家族）保持不透明。
- **如何验证**：GR-27（P29 的 ISR 经 `gp` 写 `buf` 必须作为 ISR 写出现，变量不得 SAFE）；`strcmp` 只读实参不产生逃逸；`memcpy(&s.inner, ...)` 只写 `s.inner.*`。

### 10.4 OPT-14（P0，阶段 1）内联汇编操作数与文本引用

- **为什么需要**：FS-5。
- **当前代码问题**：`access_mode` 不认识 `GCC_ASM_STMT` 祖先，输出操作数按默认 READ 记录；`_assembly_symbol_references` 的扫描条件写反（`classify.py:449`）。
- **计划如何解决**：（1）解析 GCC 扩展汇编的操作数约束：`=`/`+` 输出 → WRITE / RMW；`m` 输入 → READ；`"r"(&x)` 这类地址操作数 → 地址流入汇编（除非模板是已识别指令）。（2）汇编模板中的标识符与已盘点变量（外部链接 + 同 TU static）匹配 → `ASSEMBLY_SYMBOL_REFERENCE`；只有能识别的 `ldr/str` 字面量池模式才转成具体 READ/WRITE，否则 UNKNOWN_INLINE_ASM。（3）修正条件：只要存在内联汇编就扫描。（4）已识别的屏蔽 / 屏障类指令模板（`cpsid/cpsie i|f`、`mrs/msr primask|basepri|basepri_max|faultmask`、`nop/wfi/wfe/sev/dsb/dmb/isb`）在 OPT-31 中给出精确语义。
- **如何验证**：GR-14（P23 两个变量都不得 SAFE）；CMSIS 内建函数（只操作局部寄存器变量）不产生新的变量访问。

### 10.5 OPT-42（P1，阶段 4）函数指针类型过滤

- **为什么需要**：降低间接调用的 may-target 扇出（blackmagic 最大扇出 61，klipper 一个调用点 124 个目标），从源头减少上下文污染（RC-1）与未知入口界定的范围（OPT-41）。
- **当前代码问题**：`Solver.targets()` 返回表达式可能值中的全部函数（`points_to.py:55-57`），不看类型。
- **计划如何解决**：比较间接调用的函数指针规范类型与候选函数的规范类型（返回值 + 参数；可变参数与无原型函数不过滤）。经不兼容类型调用函数在 C 中是未定义行为，因此过滤以“程序无此类 UB”为假设，写入 ProofRecord；若函数地址在任何位置被强转为别的函数指针类型，则该函数对那些类型也视为兼容（提取 FUNCTION_ADDRESS 时记录外层强转类型），对经 `void*` / 整数中转的值不做过滤。
- **如何验证**：类型不兼容的候选被排除；强转、`void*` 中转、无原型声明三类用例不被误过滤；blackmagic / klipper 扇出分布前后对比。

### 10.6 OPT-44（P1，阶段 4）常量下标数组敏感与“经形参存储”按调用点求值

- **为什么需要**：RC-1 中描述符表、设备表、注册函数造成的跨实例合并（P13）。
- **当前代码问题**：数组下标一律合并（`pointer_extract.py:47-49`），designator 的下标被剥掉（`:85-92`）；约束 `h->cb = f` 用形参的全局合并指向集求值。
- **计划如何解决**：（1）编译期常量下标的元素得到独立子位置 `elem[k]`，另设汇总位置 `elem[*]`：动态下标的写进入 `elem[*]`，常量下标的读取 `elem[k] ∪ elem[*]`，动态下标的读取全部——这一构造是健全的。designator `[IDX] = v` 在 IDX 可求值时写入 `elem[IDX]`。（2）左值依赖函数 F 形参的约束（经形参存储）在 F 的每个调用点用该点的实参绑定求值（与 `_attribute_indirect_accesses` 的 env 求值同构），绑定不完整的调用点退回全局合并。
- **如何验证**：P13 中 `cb1` 只获得 USART1 上下文；常量下标表、动态下标表、混合表各一条测试；betaflight 的 DMA 描述符表在运行期下标下仍合并（这是正确结论），重放统计实际变化【需进一步确认】。

### 10.7 OPT-53（P1，阶段 3）Mod/Ref 与效果摘要

- **为什么需要**：屏蔽分析中的无序表达式（M-10）、一致性写事务与读组（RC-2、FS-2）、HB 的使能效果（§9）、逃逸相关性（§10.8）、中间值暴露（NR-04）都需要函数级效果。
- **当前代码问题**：没有函数摘要；屏蔽分析遇到调用只能递归求值或置为未知；一致性只看单函数。
- **计划如何解决**：在 SCC 收缩后的调用图上自底向上计算每个函数 F 的摘要：`MOD(F)` / `REF(F)`（抽象位置集合，形参相关部分以形参相对路径表示）、`mask_effect`（PRIMASK / BASEPRI 转移函数：中性 / 置位 / 恢复 / 未知）、`may_enable`（IRQ 集合或 ANY）、`calls_opaque`、`retains_param_pointer`、对每个资源的最大存储次数上界。递归 SCC 取不动点；含不透明调用的摘要相应字段取“未知”。
- **如何验证**：摘要单元测试（访问器、setter、递归、不透明调用）；用摘要替代递归求值后，`test_design_acceptance` 的屏蔽测试全部保持。

### 10.8 NoEscape：逃逸的相关性收紧（OPT-19 与 OPT-53 的组合，P1）

- **为什么需要**：现在“地址流入不透明代码”一律产生 UNKNOWN_ADDRESS_ESCAPE；但同步调用的不透明函数只能在调用者的域内访问对象，真正危险的是“保留指针、之后在其它上下文访问”。
- **计划如何解决**：地址流入域 D 中调用的不透明函数时：（1）显式加入 D 域内对 r 的 READ+WRITE 访问（同步效果，现在被忽略，属于漏建模）；（2）若该函数没有“不保留指针”的语义证据，再加入 `UNK` 上下文的 READ+WRITE（保留后的异步效果）→ 按 §4.1 相关性形成缺口。有“不保留指针”证据时只有第（1）项。const 对象不产生写（保留现有规则）。
- **如何验证**：T08 仍为 UNKNOWN；库摘要声明不保留指针的函数只产生同域访问；单域变量地址传给“不保留指针”的库函数后仍可 SAFE_SINGLE_*。

---

## 11. HAL Callback / Handle 对象敏感上下文传播（需求 13）

### 11.1 STM32 工程中的典型模式

| 编号 | 模式 | 例子 | 当前结果 |
|---|---|---|---|
| H1 | 向量 → `HAL_XXX_IRQHandler(&hX)` → 内部函数 → 弱回调 `HAL_XXX_CpltCallback(hX)`，用户在回调中按 `hX == &huartN` 或 `hX->Instance == USARTN` 分支 | 多路 UART 共用一个 `HAL_UART_RxCpltCallback` | 每个分支的数据带全部 UART 上下文（P14） |
| H2 | 注册式回调（`USE_HAL_XXX_REGISTER_CALLBACKS=1`）：`HAL_UART_RegisterCallback(&huart1, ID, fn)` 写 `huart->RxCpltCallback`，IRQ 处理中 `huart->RxCpltCallback(huart)` | 每个外设实例各自的回调 | 全部回调合并到全部实例（P13 同构） |
| H3 | DMA 关联：`__HAL_LINKDMA(huart, hdmarx, hdma_rx)` 写 `hdma->Parent`；DMA IRQ → `HAL_DMA_IRQHandler(&hdma)` → `hdma->XferCpltCallback(hdma)` → `huart = hdma->Parent` → 用户回调 | UART RX DMA 完成 | 句柄父子关系合并 |
| H4 | 用户驱动对象 + ops 表：`dev->ops->read(dev)`；描述符表 `dmaDescriptors[i].irqHandlerCallback` | betaflight 设备 / DMA 描述符 | 运行期下标时合并（部分是正确结论） |
| H5 | 访问经句柄形参发生在被调函数内部，且被调函数内有临界区 | `q_add(&q1)` | 保护丢失（P8） |

### 11.2 OPT-43（P1，阶段 4）句柄敏感上下文传播（HSCP）

- **为什么需要**：RC-1 在 HAL 工程中的主体就是 H1–H3；不解决它，多外设工程中按实例分开的数据会系统性地成为双写者 SUSPECT。
- **当前代码问题**：上下文以“函数”为粒度传播（`ecra/analysis.py:175-186`）；经形参的存储与经形参字段的间接调用在 points-to 中全局合并（`ecra/points_to.py:105-117`）；对象敏感只用于数据访问且一层（`:245-281`）。
- **计划如何解决**：
  1. **句柄形参识别（通用、结构性）**：函数 F 的指针形参 p 满足任一条件即为句柄形参——经 p 的字段做间接调用（`p->cb(...)`）、经 p 的字段做分支比较（`p == &obj`、`p->field == 常量`）、经 p 访问被审计对象、把 p 原样转发给另一函数的句柄形参。只依据语法结构，不依据名字。
  2. **按接收对象克隆**：上下文从“(域)”扩展为“(域, 句柄绑定)”。在向量入口 `HAL_UART_IRQHandler(&huart1)` 处，句柄形参绑定为 {huart1}；绑定沿“原样转发”的调用链传递（深度上限 N，默认 8）；绑定集合为单元素时才克隆，否则合并为普通上下文。
  3. **按绑定解析间接调用**：`p->cb(p)` 在绑定 {huart1} 下只取 `points[huart1/cb]`；对应地，注册函数中的存储 `h->cb = f` 按 OPT-44 在每个调用点求值，使 `points[huart1/cb]` 只含为 huart1 注册的回调。H3 中 `hdma->Parent` 在绑定 {hdma_usart1_rx} 下只取 `points[hdma_usart1_rx/Parent]`。
  4. **句柄身份路径裁剪**：在绑定为单元素时求值分支条件：
     - 指针相等 `p == &obj` / `p != &obj`：可直接求值；
     - 字段常量 `p->Instance == USART1`：仅当该字段对绑定对象是“初始化后常量”（全工程只有一处常量存储、该存储对所有访问该字段的竞争域 HB 有序（§9.3）、对象地址没有流入不透明代码、无其它写入，依 OPT-53 的 MOD 摘要确认）时求值；
     - 不可求值的条件不裁剪。被裁剪的分支内的访问不获得该绑定对应的上下文。
  5. **保底**：绑定非单元素、句柄地址逃逸、深度超限、克隆数超过上限（每函数默认 64）时，退回上下文不敏感结果（即当前结果）。
- **如何验证**：P13、P14 中 `d1/rx1` 只带 USART1 上下文、`d2/rx2` 只带 USART2 上下文；GR-25：分支条件依赖运行期可变字段时不得裁剪；CubeMX 黄金工程（两路 UART + DMA + 定时器回调）逐变量核对；三工程重放统计克隆数与耗时。

### 11.3 OPT-32（P1，阶段 3）对象敏感归属后保留访问站点函数

- **为什么需要**：H5 / P8：经句柄形参的访问在被调函数内部受保护，但归属到调用者后保护证据丢失。
- **当前代码问题**：`add_access(locs, dict(item, function_id=caller), ...)`（`ecra/points_to.py:277`）同时改变了“上下文来源”和“代码位置所属函数”。
- **计划如何解决**：访问行拆分两个字段——`site_function_id`（代码所在函数，用于 CFG / 屏蔽窗口 / 保护事件 / 条件祖先）与 `attribution`（调用点、句柄绑定、由调用者推导的上下文集合）。屏蔽分析在 `site_function_id` 的 CFG 中定位节点，入口屏蔽状态取调用点处的状态（与现有过程间求值 `MaskAnalysis.evaluate` 的被调函数分支同构，`ecra/protection.py:102-111`）；`related` 函数集合加入 `site_function_id` 及其祖先。
- **如何验证**：P8 中 `q1.count` → SAFE_EFFECTIVE_PROTECTION；被调函数内部分覆盖窗口的变体必须仍为 SUSPECT；`test_helper_access_inherits_mask` 等现有测试保持。

---

## 12. MHP、NVIC 优先级、PRIMASK、BASEPRI 与临界区分析（需求 14）

### 12.1 现状

- 关系：MAIN–MAIN 为 SERIAL；MAIN–ISR 为 CAN_PREEMPT；ISR–ISR 在优先级可证时按抢占优先级比较，否则 UNKNOWN_PREEMPTION；其它组合 MAY_INTERLEAVE（`ecra/interrupts.py:94-125`）。域对聚合时只有“全部为 SERIAL”才不可交错（`ecra/classify.py:189-212`）。
- 优先级：见 RC-5。
- 屏蔽：PRIMASK 为单比特、BASEPRI 为值的格上抽象解释，按上下文根求值，过程间递归（深度 48），窗口按“访问到访问”的节点集合计算（`ecra/protection.py:23-225`）。
- 保护裁决：变量级；只看 MAIN 窗口；竞争者只能是可屏蔽 ISR 且两两 SERIAL（`:243-315`）。

### 12.2 MHP 关系模型（OPT-48 的组成部分）

把关系从“是否可交错”细化为带方向的格，用于 NR-04、§14.2 的方向规则和逐对保护：

| 关系 | 含义 | 来源 |
|---|---|---|
| `SAME_SERIAL` | 同一非重入域 | 域合并 |
| `SERIAL` | 不同域但不可互相抢占（同抢占优先级） | OPT-51 |
| `HB_ORDERED(a→b)` | a 的相关写全部先于 b 的任何执行 | OPT-50 |
| `PREEMPTS(a→b)` | a 可抢占 b，b 不能抢占 a（a 优先级更高，或 b 为 FOREGROUND） | OPT-51 |
| `MAY_INTERLEAVE` | 方向未知（优先级未证明、DMA、外部异步） | 默认 |

冲突判定只关心“能否交错”（除 `SAME_SERIAL / SERIAL / HB_ORDERED` 外都能）；方向只用于 §8.6 与 §14.2 的细化，未知方向时取两个方向中更保守的一个。

### 12.3 OPT-51（P1，阶段 5）NVIC 优先级恢复 v2

- **为什么需要**：RC-5；betaflight 2334 个、blackmagic 19 个 SUSPECT 带“抢占优先级待确认”；同优先级 ISR 之间的 SERIAL 证明、BASEPRI 阈值证明都依赖它。
- **当前代码问题**：只识别两个 API；要求恰好一次无条件设置（`ecra/interrupts.py:38-80`）；只在提取阶段记录这四个 API 的参数（`ecra/extract.py:461-468`）。
- **计划如何解决**：
  1. 识别器（均为通用标准库语义）：CMSIS `NVIC_SetPriority`（含 SysTick/PendSV 等负 IRQn → SCB->SHP）、HAL `HAL_NVIC_SetPriority`、SPL `NVIC_Init`（读取初始化结构的抢占 / 子优先级 / 通道字段，要求在调用前对该局部结构的常量存储可确定）、libopencm3 `nvic_set_priority`、直接写 `NVIC->IP[n]` / `NVIC->IPR[n]` / `SCB->SHP[n]`。
  2. 值求值：沿用 `constant_value`（clang `Cursor_Evaluate`，`ecra/extract.py:40-57`）处理宏 / 枚举 / 常量表达式；对“常量表中的元素经常量下标读取”做有限常量传播。
  3. 放宽“恰好一次”为健全条件：同一 IRQ 的所有设置都可求值且值相同；或所有设置都在该 IRQ 使能之前（OPT-50）、且使能前最后一次设置无条件——取最后值；运行期（使能后）的任何重设置 → 放弃。
  4. 未恢复的优先级保持 UNKNOWN，按 `MAY_INTERLEAVE` 处理。
- **如何验证**：SPL `NVIC_Init` 用例、libopencm3 用例、表驱动用例、重复相同值、使能后重设（必须放弃）各一条；`test_uncalled_priority_setup_is_not_evidence`、`test_conditional_priority_setup_is_not_evidence` 保持；betaflight 统计“抢占待确认”次要标记的变化。

### 12.4 OPT-30 + OPT-31（P1，阶段 3）CFG 完整化与屏蔽效果摘要

- **为什么需要**：RC-4；CFG 完整率 klipper 27.9%、blackmagic 82.8%，不完整函数内任何临界区都无法证明。
- **当前代码问题**：`for/switch/goto/asm` 与无序表达式令整函数不完整（`ecra/controlflow.py:58-67, 153-160, 169`）；调用内联汇编函数后状态丢失（`ecra/protection.py:102-111`）。
- **计划如何解决**：
  1. **OPT-30 语句覆盖**：`FOR_STMT`（init → cond 分支 → body → inc → 回边）、`SWITCH_STMT`（分派到各 `case/default`，含 fallthrough 与 `break`）、`GOTO_STMT / LABEL_STMT`（标签表；`INDIRECT_GOTO` 仍不支持）、`LABEL_STMT` 包裹语句的正确处理（当前会把被包裹的 `if` 当作表达式）、`CXX_*` 保持不支持。GNU `__cleanup__` 属性（betaflight `ATOMIC_BLOCK`）在作用域出口插入对清理函数的调用节点。
  2. **局部化不完整**：单条语义未知的语句（未知汇编、间接 goto）只产生一个 `unknown` 节点，状态在该节点之后置为未知，不再让整函数 `complete=False`；函数级 `complete` 只在 CFG 结构本身无法构造时为假。
  3. **OPT-31 内联汇编指令语义**：模板（拆分 `;` 与换行）只含已识别指令时给出转移函数：`cpsid i` → PRIMASK=1；`cpsie i` → 0；`msr primask, rX` → 恢复 rX 的值（rX 来自输出操作数绑定的局部变量）；`mrs rX, primask` → 读取；`msr basepri(_max), rX` → BASEPRI 赋值 / 取严；`cpsid f / cpsie f` → FAULTMASK；`nop/wfi/wfe/sev/dsb/dmb/isb` → 中性。含其它指令 → 未知节点。这样工程自写的屏蔽封装（如 klipper 以 `cpsid i` 实现的 `irq_disable`）可由摘要自动识别，不需要按名字配置。
  4. **无序表达式精化**：利用 OPT-53 的 `mask_effect`，表达式中只要所有调用的屏蔽效果都是“中性”，求值顺序就不影响屏蔽状态，不再产生未知节点；只有存在非中性调用且与访问同处一个无序表达式时才保守处理。
- **如何验证**：P4、P21、P22 → EFFECTIVE；`test_unsupported_goto_preserves_uncertainty` 改为“间接 goto / 未知汇编保持不确定”；`test_design_acceptance` 其余屏蔽测试（分支汇合、提前返回、条件解除屏蔽、嵌套保存恢复、覆盖保存键……）全部保持；三工程 CFG 完整率前后对比。

### 12.5 OPT-33（P1，阶段 3）逐冲突对的保护判定

- **为什么需要**：保护应该针对“某两个域之间的冲突”，而不是变量整体；现规则要求所有 ISR 两两 SERIAL，即使它们之间只有读-读。
- **当前代码问题**：`assess` 的 `participants` 条件（`ecra/protection.py:292-293`）与“只看 MAIN 窗口”（`:276`）。
- **计划如何解决**：对每个破坏性见证对 (A, B) 分别判断：
  - A 为 FOREGROUND、B 为可屏蔽 ISR：A 在该资源上的每个事务窗口（现有窗口语义：访问到访问之间的全部节点，RMW 单独成事务）都处于 PRIMASK=1，或 BASEPRI 阈值覆盖 B 的已证明优先级 → 该对被排除。
  - A、B 都是 ISR：若 MHP 为 SERIAL → 排除；若 A 被 B 抢占（B 优先级更高），A 的事务窗口内 BASEPRI / PRIMASK 覆盖 B → 排除；否则保留。
  - B 为 NMI / HardFault、DMA、外部异步：不能被屏蔽排除。
  - 变量只有在**全部**见证对都被排除时才是 SAFE_EFFECTIVE_PROTECTION；部分排除时保留剩余见证（原因中注明哪些对已被保护）。
- **如何验证**：两个 ISR 只读 + 前台在 PRIMASK 内 RMW → EFFECTIVE；两个 ISR 都写且优先级未知 → SUSPECT（即使前台已屏蔽）；ISR 内 BASEPRI 屏蔽更高优先级 ISR 的用例；`test_more_urgent_irq_is_not_masked` 保持。

### 12.6 OPT-34（P2，阶段 3）原子操作

- **为什么需要**：`LDREX/STREX` 循环、C11 `atomic_*`、GCC `__atomic_* / __sync_*` 的 RMW 本身不会丢失更新。
- **当前代码问题**：PointerExtractor 已标记 `atomic=True` 的访问（`ecra/pointer_extract.py:179-193`），但分类器未使用【需进一步确认：直接访问路径上是否有同等标记】。
- **计划如何解决**：当某对冲突中所有写都是原子 RMW / 原子 store 且宽度满足 NR-03 时，该对的 D-01 不成立（D-07 一致性仍按字段判断）；CMSIS `__LDREXW/__STREXW` 循环按模式识别（由 OPT-31 的指令语义支持）。
- **如何验证**：两个 ISR 对同一计数器 `atomic_fetch_add` → 不因 D-01 SUSPECT；一方原子、一方普通写 → SUSPECT。

### 12.7 临界区配置与 RTOS 宏

- 保留 `critical_sections` 配置（工程私有封装的显式声明，`ecra/config.py:252-263`），它只增加“屏蔽事件”的证据，不直接判安全；OPT-31 能自动识别以汇编实现的封装后，配置只用于无源码的封装。
- `api_patterns` 中的 `taskENTER_CRITICAL` 等只是“检测到保护”的事实（`ecra/extract.py:387-391`）。若 FreeRTOS 端口源码在构建中，其宏展开后的 `msr basepri` 由 OPT-31 精确建模；否则保持 DETECTED（不能证明有效）。

### 12.8 OPT-52（P1，阶段 5）CPU↔DMA 的 MHP：DMA 生命周期

- **为什么需要**：P18；HAL 工程中“填充后启动”“完成回调中读取”是 DMA 的标准用法。
- **当前代码问题**：DMA 访问与所有 CPU 访问任意交错（`ecra/classify.py:850-854`），没有启动 / 完成次序。
- **计划如何解决**：对每个 DMA 域（OPT-18 的流 / 发布点粒度）建立区间：`start` 事件（HAL `*_DMA` 启动 API、寄存器 `CR |= EN`、LL `LL_DMA_EnableStream`）与 `stop/complete` 事件（`HAL_DMA_Abort`、完成回调入口、`CR &= ~EN`）。
  - CPU 访问 a 与 DMA 域 X 不交错，当且仅当 a 在同一前台路径上严格位于 X 的每个 `start` 之前且 X 当时未运行（`start` 前没有尚未停止的同一 DMA 区间），或 a 位于“X 已停止”可证明的位置（例如 X 的完成回调中，且循环 / 双缓冲模式未启用——需从配置常量判断 `DMA_CIRCULAR` / `DBM` 未置位）。
  - 无法证明时保持 D-03。环形 / 双缓冲模式下保持 SUSPECT（半缓冲协议属于语义层面，静态无法证明）。
- **如何验证**：P18 → 不再因 D-03 SUSPECT（缓冲在启动前写入，启动后只读）；循环模式用例保持 SUSPECT；“完成回调中读取 + 回调里立即重启 DMA 前读取完毕”用例；GR-06 / G6 保持。

---

## 13. 结构体字段、数组、whole-object、位域、union 的存储重叠分析（需求 15）

### 13.1 现状

- 成员资源化：结构体（含嵌套结构体）按字段路径生成成员资源，嵌套结构体字段作为 `STRUCT_MEMBER_CONTAINER`（`ecra/analysis.py:298-416`）。
- 整对象访问继承到全部叶子成员（`:378-391`）；根对象级缺口继承到成员（`:400-410`）。
- 缺失：字段偏移、位宽、struct/union 区分、位域存储单元、结构体数组的字段、`memcpy/memset` 的长度范围。

### 13.2 OPT-11（P0，阶段 1）union 重叠最小修复

- **为什么需要**：FS-1，是当前唯一会把**双写**判成 SAFE 的存储模型缺陷。
- **当前代码问题**：union 成员被当作互不重叠的独立资源（P1）。
- **计划如何解决**：在完整布局模型（OPT-21）落地之前先做保守修复：提取器为记录类型标记 `is_union`（libclang `CursorKind.UNION_DECL`）；对 union 内的任一成员（含嵌套）的 READ/WRITE/RMW，复制为同一 union 下全部其它成员的 `OVERLAP_ACCESS` 继承行（与整对象继承同一机制，`access_scope='OVERLAP_ACCESS'`，记录来源）。
- **如何验证**：GR-12（P1 中 `u.w`、`u.h.lo`、`u.h.hi` 全部 SUSPECT）；非 union 结构结论不变。

### 13.3 OPT-21（P1，阶段 2）存储布局模型

- **为什么需要**：精确的重叠判断同时解决 FS-1（健全）、M-07 / M-08（精度）与 NR-03 的有效对齐。
- **计划如何解决**：
  1. **布局提取**：每个记录类型记录字段的 `bit_offset`、`bit_width`（位域）、`byte_size`、是否 union、packed / aligned 属性；数组记录元素布局与元素数。
  2. **资源 = C11 存储位置**：非位域标量成员各为一个资源；相邻非零宽位域构成一个**位域组**资源（遇到零宽位域 `:0` 或非位域成员即结束）；union 的成员是同一字节区间的不同视图；数组为 `elem[*]` 视图，结构体数组在元素内部继续字段敏感（`arr[*].a` 与 `arr[*].b` 不相交）。
  3. **访问映射到范围**：每个访问换算为根对象上的 `[bit_start, bit_end)`：成员访问取成员范围；整对象访问取全范围；`memcpy/memset` 长度可求值时取 `[offset, offset+len)`，否则全范围；经强转指针的类型双关取“指向路径的起点 + 访问类型尺寸”，不可求值时全范围。
  4. **冲突判定按重叠**：资源 r 的访问集 A(r) = 所有范围与 r 相交的访问（§4.1）。整对象继承、union 继承因此不再需要复制访问行，只需在查询时按区间求交（同时消除 3339 行继承行造成的数据膨胀）。展示层仍可生成“继承影响”视图。
- **如何验证**：P1（union 重叠为 SUSPECT）、P16（结构体数组不同字段不冲突）、G8（整对象写 ↔ 成员读保持 SUSPECT）、`memset` 局部成员只影响该成员、`test_struct_members_are_canonical_resources_with_all_context_paths` 保持。

### 13.4 OPT-23（P1，阶段 2）位域组

- **为什么需要**：M-01（P3 单域位域 SUSPECT）与 G7（跨域兄弟位域必须 SUSPECT）要同时满足。
- **当前代码问题**：`is_bitfield_container and writer_domains` 无域数检查（`ecra/classify.py:855-856`），G7 依赖这条无条件规则。
- **计划如何解决**：对位域成员的写一律视为对整个位域组的 RMW（D-04 的事实基础）；位域成员 x 的风险按“组内任一成员的跨域写”判断：组内存在两个可交错的域都写（任意成员）→ 组内所有被写成员 SUSPECT（D-04）；组内只有一个域写、其它域只读 → 读者成员按 NR 判断（位域不满足 NR-03 → SUSPECT，D-08）；组内所有访问都在一个域 → 按单域规则 SAFE。
- **如何验证**：G7（`f.a` ISR 写、`f.b` 前台写，两者都 SUSPECT）保持；P3 → SAFE_SINGLE_FOREGROUND；位域组被 `:0` 分隔的两组互不影响（GP-07）。

---

## 14. Multi-field coherence、stale snapshot、RMW、多 Writer 等风险守门机制（需求 16）

### 14.1 守门架构

每个守门是一个“破坏性模式检测器”，输出带最小证据的见证（§4.4 的 D-01…D-12）。守门先于 NO_REVIEW / SAFE 判定执行；精化（保护、HB、MHP、HSCP、Stage B）只能在给出 ProofRecord 时排除某个见证，不能修改检测器的判定条件本身。检测器条件的任何变更都必须同时满足：（1）给出风险语义论证；（2）黄金风险样例全部保持；（3）基准翻转报告逐条审计（§16.3）。

### 14.2 多字段一致性 v2：OPT-12（P0，阶段 1）与 OPT-24（P1，阶段 2）

- **为什么需要**：RC-2：既过宽（P7、P12、回退放大）又有漏洞（P6）。
- **当前代码问题**：`ecra/analysis.py:838-870` 的写侧“域内任意写 ≥2 成员”、读侧“同函数读 ≥2 成员”、不查 MHP。
- **计划如何解决**：候选组仍限于同一 root 对象的成员（跨对象的语义耦合不在静态可判定范围内，作为残留风险写入报告限制说明），以及 OPT-25 的多元素数组。对成员对 {a, b}、写者域 W、读者域 D：

  | 条件 | 内容 | 来源 |
  |---|---|---|
  | C1 读组（OPT-12，P0） | D 中某函数 R 在一次调用内读 a 与 b：R 内的直接读，加上 R 中对“返回值 / 输出参数来自成员 m 的访问器函数”的调用点（按 m 的读计入 R，依 OPT-53 的返回值来源摘要，可传递） | 修 FS-2（P6） |
  | C2 同路径（OPT-24） | 两次读在 R 中存在一条不经过同时包含两者的循环回边的路径（排除互斥分支）；CFG 不完整时保守成立 | 修 P12 |
  | C3 写侧 | W 写过 a 与 b（不再计入因路径缺陷产生的回退继承写，见 OPT-20；真实整对象写仍计入） | — |
  | C4 MHP | MHP(W, D) 不属于 `SAME_SERIAL / SERIAL / HB_ORDERED` | 修 P7 |
  | C5 方向（OPT-24） | 若 D 可抢占 W 且 D 运行到完成（如 W=前台、D=ISR）：D 只能看到 W 的某一瞬间，只有当 W 在**一次事务**内写 a 与 b（两次写同路径，含被调函数的 MOD 摘要）时才可能撕裂；若 W 可抢占 D（如 W=ISR、D=前台）或方向未知：D 的两次读可跨越 W 的执行，C3 即足够 | 方向见 §12.2 |
  | C6 保护 | 读窗口（D 的 C1 读组区间）对 W 有效屏蔽，或写事务对 D 有效屏蔽（§12.5 逐对规则） → 排除 | OPT-33 |
  | C7 次序 | W 的写全部 HB 先于 D（§9.3） → 排除 | OPT-50 |

  满足 C1–C5 且未被 C6/C7 排除 → a、b 两个成员都带 D-07 见证。
- **如何验证**：G9 保持；GR-09b（P6）SUSPECT；P7 → 不因一致性 SUSPECT；P12 → 不因一致性 SUSPECT；“前台事务写 + 高优先级 ISR 成对读”保持 SUSPECT；“前台分别在两个独立命令处理函数中写 a、b + ISR 成对读”按 C5 不标记，但该用例必须在报告的“残留语义风险”中出现（避免静默）；blackmagic / klipper 一致性成员数前后对比。

### 14.3 Stale snapshot（旧值回写）

- 现状：提取器记录“局部变量取自全局、之后使用”的快照事实（`ecra/extract.py:420-421, 511-514`），仅作 SUSPECT 的规则标签（`ecra/analysis.py:970-971`）；真正的拦截来自双写者（G3：前台读旧值 → ISR 写 → 前台写回，属于两个写者域）。
- 规划：保持“单写者域内先读后写允许 NO_REVIEW”的既有设计（唯一写者不会丢失他人的更新）；把快照事实纳入见证证据（指出读站点与回写站点），提高复核效率；HSCP / HB 只能在给出 ProofRecord 时排除其中一个写者域。
- 验证：G3、D06、`test_snapshot_and_local_static_reentrancy` 保持。

### 14.4 RMW 交叉

- 现状：RMW 视为写，参与 D-01；RMW 单站点事务在屏蔽窗口计算中独立成事务（`ecra/protection.py:174-177, 196-199`）。
- 规划：保持；新增原子 RMW 例外（OPT-34）；逐对保护（OPT-33）只能排除被屏蔽的对。
- 验证：G2、T14、`test_each_loop_rmw_is_independently_masked`、`test_independent_helper_rmws_may_unmask_between_transactions` 保持。

### 14.5 多 Writer

- 现状：可交错域对双写即 D-01（`ecra/classify.py:839-845`）；可重入写者 D-02（`:846-848`）。
- 规划：检测条件不变；精度来自上游——域对是否真实存在（HSCP、类型过滤、常量下标、UNK 界定），是否可交错（OPT-51 SERIAL、OPT-50 HB），是否被保护（OPT-33）。任何上游精化都只能删除“不存在的上下文”或“已证明不可交错 / 已保护的对”。
- 验证：G1、G2、G10、T06、T11、D05、D07 保持。

### 14.6 撕裂、中间值暴露、可见性

见 §8.6（NR-03、NR-04、NR-08）；它们既是 NO_REVIEW 门槛，也是 SUSPECT 的破坏性模式（D-08、D-09、D-10）。

### 14.7 守门回归

§5.2 的 HR-01…HR-31 全部进入黄金风险样例集（§18.3），作为每次改动的阻断性测试。

---

## 15. 两阶段静态分析：先快速筛选，再只对候选做高精度分析（需求 17）

### 15.1 动机

betaflight 规模（约 4 万资源、2028 个上下文）下，当前 `analyze()` 约 780 s（`docs/pre_opencode_classification_benchmark.md` §3）。路径敏感、句柄敏感克隆、逐对保护、逐 IRQ 的 HB、需求驱动的指针分析，如果对全工程执行，代价不可接受；但它们只对 10%–35% 的候选变量有意义。

### 15.2 Stage A：全量快速筛选

- 内容：当前流水线 + 阶段 1 健全性修复 + 阶段 2–5 中代价线性或近线性的精化（路径代数、布局模型、规范宽度、位域组、CFG 完整化、函数摘要、使能事件模型、类型过滤、常量下标、UNK 抽象上下文）。
- 输出（每个资源）：`decision_A`；最小见证集合；相关缺口及相关性说明；`refinable_by`（见证或缺口依赖哪类可精化的近似）：

  | 标记 | 触发条件 |
  |---|---|
  | `MAY_TARGET_EDGE` | 见证中的某个上下文推导经过扇出 > 1 的 INDIRECT_RESOLVED 边 |
  | `HANDLE_BINDING` | 推导经过句柄形参函数且绑定在 Stage A 被合并 |
  | `UNK_ENTRY` | 缺口来自 `UNK(seed)` |
  | `COHERENCE_PATH` | D-07 见证中 C2 / C5 在 Stage A 按保守成立 |
  | `PROTECTION_DETECTED` | 见证对所在函数有屏蔽事件但窗口未证明 |
  | `HB_CANDIDATE` | 见证中的前台写在 Stage A 不能证明 HB 但存在使能事件 |
  | `PRIORITY_UNKNOWN` | ISR 对优先级未证明但存在优先级事件 |
  | `DMA_ORDER` | D-03 见证存在可识别的 start / stop 事件 |

- Stage A 的 SAFE / NO_REVIEW 结论即为最终结论（它们已有完整证明）；Stage B 只处理 S/U。

### 15.3 Stage B：候选精化

| 精化器 | 作用 | 对应设计 |
|---|---|---|
| B1 句柄敏感重传播 | 仅在见证涉及的调用子图上执行 HSCP 克隆，绑定上限可高于 Stage A | §11.2 |
| B2 需求驱动指针分析 | 对见证路径上的具体间接调用点做调用点敏感（k-CFA，k≤2）+ 函数内流敏感（强更新局部变量 / 单例对象字段）的解析 | §10 |
| B3 一致性路径分析 | 对 D-07 见证精确计算 C2 / C5 | §14.2 |
| B4 逐对保护 | 对见证对做完整过程间屏蔽求值 | §12.5 |
| B5 逐 IRQ HB | 对见证中的前台写求 HB | §9.3 |
| B6 DMA 生命周期 | 对 D-03 见证求 start/stop 次序 | §12.8 |
| B7 UNK 界定 | 对 UNKNOWN_EXECUTION_CONTEXT 缺口做分派点界定 | §6.5 |
| B8 优先级求值 | 对未证明的 ISR 对做初始化代码中的常量求值 | §12.3 |

调度：按“排除杠杆”排序——把见证按共享元素（边、上下文、函数、对象）聚类，先精化依赖它的变量最多的元素，结果缓存复用（同一条 may-target 边被证伪后，所有依赖它的见证同时更新）。

### 15.4 健全性契约

1. Stage B 只能**排除**见证或缺口，不能新增 SAFE 理由以外的结论，也不能修改 Stage A 的事实。
2. 每个排除生成 `ProofRecord{refiner, version, witness_id, premises[事实ID], assumptions[], checks[]}`；没有 ProofRecord 的排除在 I-3 断言中失败。
3. 变量的最终结论 = 对剩余见证与缺口重新执行 §4.6 的裁决；只有全部见证与相关缺口都被排除时才可能离开 S/U。
4. 精化器内部任何未建模情况（不支持的语句、预算耗尽、摘要未知）一律返回“无法排除”。

### 15.5 预算

- 全局预算：默认不超过 Stage A 耗时的 30%（可配置，仅影响能精化多少，不影响健全性）。
- 单元素预算：每个聚类元素的时间 / 克隆数 / 路径数上限；超限即放弃该元素。
- 报告：每次运行输出精化覆盖率（已尝试 / 已排除 / 预算放弃的见证数），预算放弃的变量在复核包中注明“未完成精化”，供用户决定是否加大预算。

### 15.6 影子模式与翻转报告

- 新精化器上线先以影子模式运行：最终结论仍取 Stage A，Stage B 结论写入 `stage_b_shadow`，并生成翻转报告（S/U → SAFE/NR 的变量列表、ProofRecord、源码位置）。
- 翻转报告按 §16.3 审计通过后，该精化器才切换为生效模式。

### 15.7 代码集成点

- 当前逐变量循环在 `ecra/analysis.py:903-1055` 中“分类后立即写入变量记录与 findings”。需要改为三步：（1）对全部资源计算 Stage A 结果（不写入）；（2）对 S/U 运行 Stage B；（3）统一写入变量记录、findings、归账（`:1094-1125` 的校验不变）。
- 新模块 `ecra/refine.py`（Stage B 调度与精化器）、`ecra/witness.py`（见证、ProofRecord、聚类），见 §17。

### 15.8 验证

- 差分不变式：Stage B 从不改变 Stage A 的 SAFE / NO_REVIEW；从不在无 ProofRecord 时排除见证。
- 黄金风险样例在“只 Stage A”与“Stage A+B”两种模式下都必须保持。
- 三工程 Stage B 的排除结果全部列入翻转报告并抽样审计。

---

## 16. 如何减少 SUSPECT / UNKNOWN，同时保证 false-safe 接近 0（需求 18）

### 16.1 原则

| 编号 | 原则 | 落实 |
|---|---|---|
| P-1 | 健全性优先 | 阶段 1 的健全性修复先于一切精度优化，即使 Review Rate 上升 |
| P-2 | 精化 = 证明 | 任何 S/U → SAFE/NR 的变化都必须对应 ProofRecord（I-3） |
| P-3 | 单调 | 精化只删除见证 / 缺口，不删除访问与上下文事实（I-4） |
| P-4 | 检测器条件不放宽 | §14.1：检测器条件的任何修改都要有风险语义论证、黄金样例全部保持、翻转审计 |
| P-5 | 不确定即保守 | 精化器遇到未建模语句、预算耗尽、摘要未知时返回“无法排除” |
| P-6 | 无名单排除 | 标准库 API 语义只作证据或有标准依据的证明前提；不按变量名、函数名、目录、注释排除 |
| P-7 | 配置只增不减 | `semantics-ecra.yaml` 只能增加上下文、入口、关系证据（I-5） |
| P-8 | 假设显式 | 每个证明码列出所依赖的假设（如“无 C 未定义行为”“const 对象位于 flash”），写入报告限制说明 |

### 16.2 false-safe 的四层度量

1. **黄金风险样例集**（§18.3）：100% 不得为 SAFE / NO_REVIEW；任何一条失守即阻断合入。
2. **注入式竞态**（§18.6）：在每个验证工程的真实代码路径中注入每类 HR 模式至少 1 例（标识符随机生成、不含任何提示性名字），要求注入变量 100% 为 SUSPECT / UNKNOWN 且见证指向注入点。
3. **分层抽样审计**：每个工程 SAFE / NO_REVIEW 按“证明码 × 资源种类”分层，抽样 ≥ 60 个，每个证明码 ≥ 10 个，新证明码（SAFE_ORDERED_INIT、逐对保护、经 HSCP / 分派点界定得到的单域结论）≥ 20 个；逐项核对访问是否找全、上下文是否正确、是否遗漏 ISR / DMA / 逃逸 / 汇编、证明是否成立。0 例 false-safe 时按“三法则”报告 95% 置信上界 3/n（n=60 时约 5%），并注明这只是统计上界。
4. **翻转审计**：每个阶段相对上一阶段，所有 S/U → SAFE/NR 的变量全部列入翻转报告（证明码、ProofRecord、源码位置）；≤100 个时全部人工审计，>100 个时按证明码分层抽样 ≥20% 且每码 ≥20 个。发现任一 false-safe：停止该阶段，定位通用规则缺陷并修复，重跑全部基准，不得以排除表处理。

补充层（非权威）：`cli.run` 已支持 `review_safe_sample`（`ecra/cli.py:51-72`），可把 SAFE 抽样送 OpenCode 交叉复核；结果只用于发现可疑样本，不作为 SAFE 依据。

### 16.3 变更控制流程

```text
冻结输入（worker parts + semantics + 引擎摘要）
  → 实现一个 OPT（附单元测试、GR/GP 样例）
  → 全量单元测试（含 GR/GP）
  → 4 个验证工程回放（§20.2）→ 翻转矩阵 + 翻转报告
  → 分层审计（§16.2 第 3、4 层）
  → 记录到 docs/classifier_progress.md（目标、修改、测试、基准变化、审计结论）
  → 合入
```

一次只合入一个 OPT 或一组互相依赖的 OPT，保证每项收益可归因（与既有“每步重跑基准、证明来自更精确静态分析”的工作方式一致）。

### 16.4 影子模式适用范围

以下精化默认先以影子模式运行，审计通过后再生效：OPT-50（B）逐对 HB 排除、OPT-43 句柄身份路径裁剪、OPT-42 类型过滤、OPT-41 分派点界定、OPT-61 全部 Stage B 精化器、OPT-80。

### 16.5 已知残留风险（必须写入报告限制说明）

现有限制说明在 `ecra/analysis.py:1182-1196`，需补充：跨对象的语义耦合（一致性只按同一 root 判断）；运行期配置的分派（运行期下标的描述符表）；未启用 OPT-80 时 HAL 内部协议字段；Cortex-M7 D-Cache 与 DMA 的一致性（只作为 DMA 生命周期缺口）；RTOS 任务优先级未建模（TASK 按可交错 / 可重入处理）；只出现在链接脚本中的入口；所有证明码依赖的 C 未定义行为假设；非 volatile 变量的编译器重排只由 NR-08 部分覆盖。

---

## 17. 需要新增或调整的数据结构、模块与算法（需求 19）

### 17.1 数据结构

| 名称 | 位置 | 新增 / 调整字段 | 用途 | OPT |
|---|---|---|---|---|
| 变量 / 成员记录 | `extract.py:167-178`；`analysis.py:328-341` | `canonical_kind`、`element_canonical_kind`、`element_size`、`bit_offset`、`bit_width`、`byte_offset`、`effective_alignment`、`is_union`、`record_attributes`（packed/aligned）、`section_attribute`、`storage_unit_id`（位域组）、`layout_range` | 宽度、对齐、重叠、位域组 | 15、21、22、23 |
| 访问行 | `extract.py:332-336`；`points_to.py:67-78` | `site_function_id`、`attribution{call_site, handle_binding, derived_contexts}`、`path_steps`、`range`、`fallback_reason`、`origin_access_id`（稳定）、`asm_operand`、`provenance_layer`（extract / points_to / libc / asm / hw） | 正确归属与保护、追溯 | 03、14、20、21、32 |
| 域记录 `Domain` | 新增（`ecra/mhp.py` 或扩展 `interrupts.py`） | 见 §7.2 | MHP、保护、方向规则 | 48 |
| 上下文绑定 | `analysis.py:175-186` | `edges[{kind, fanout}]`、`weakest_link`、`dispatch_bound` | 见证与精化 | 40、41、60 |
| `EnableEvent` / HB 事实 | 新增 `ecra/phase.py` | 见 §9.2；`hb[(write_site, domain)]` | 相位证明 | 13、50 |
| `FunctionSummary` | 新增 `ecra/summaries.py` | `MOD`、`REF`、`mask_effect`、`may_enable`、`calls_opaque`、`retains_param_pointer`、`store_counts`、`returned_members` | 摘要驱动的各项分析 | 53 |
| `HWPublication` | 新增 | `object`、`mmio_target`、`site`、`direction`、`length` | 寄存器级 DMA / 外设主机 | 18 |
| `DmaInterval` | 新增 | `domain`、`start_sites`、`stop_sites`、`circular` | DMA 生命周期 | 52 |
| `Witness` | 新增 `ecra/witness.py` | `id`、`pattern(D-xx)`、`access_ids`、`domains`、`mhp_basis`、`edges`、`refinable_by` | 结构化原因、反事实、Stage B | 02、60 |
| `ProofRecord` | 新增 `ecra/witness.py` | `refiner`、`version`、`target(witness / NR 项)`、`premises`、`assumptions`、`checks` | 证明可审计 | 61 |
| `GapRecord` | 调整 `gap_evidence` | `code`、`slice_path`、`relevance`、`evidence`、`recovery_action` | 变量局部 UNKNOWN | 17、40 |
| 分类结果 | `classify.py:740-935` 返回值 | `destructive_codes`、`witnesses`、`gate_results`、`proof_records`、`stage_b_shadow` | 输出与审计 | 02、60 |
| 覆盖 / 质量统计 | `analysis.py:1123-1167` | `rr_build`、`rr_all`、`variant_inventory`、`reason_codes`、`refinement_stats`、`soundness_fix_delta`、`review_items` | 指标 | 01、02 |

数据量控制：betaflight 的 facts dump 已达 15 GB【基准】。见证只引用访问 ID、不复制调用链；OPT-21 用区间查询替代继承行复制（blackmagic 的 3339 行继承访问可省去）；ProofRecord 只存事实 ID。

### 17.2 模块调整

| 模块 | 调整内容 | OPT |
|---|---|---|
| `ecra/extract.py` | 路径拼接修正、指针成员解引用截断、别名基路径、布局 / 规范类型 / 变量属性提取、汇编操作数、DMA 名称启发收紧 | 14、15、18、20、21、22 |
| `ecra/pointer_extract.py` | `mmio:` 抽象位置、常量下标 `elem[k]`、designator 下标、汇编地址操作数、函数地址的外层强转类型、`mode()` 解引用截断 | 14、18、20、42、44 |
| `ecra/controlflow.py` | for / switch / goto / label / `__cleanup__`；局部未知节点；导出循环信息 | 25、30 |
| `ecra/points_to.py` | 差分工作表求解；经形参存储按调用点求值；类型过滤；统一库语义；地址发布；DMA 域按流 / 发布点；保留站点函数；限额局部化 | 18、19、32、42、44、45 |
| `ecra/analysis.py` | 区间重叠查询替代继承复制；一致性迁出；Stage A / B 三步结构；归账；新指标 | 01、21、24、60 |
| `ecra/classify.py` | §4.6 裁决顺序；NR v2；UNK 上下文；缺口相关性；见证生成；不变式断言 | 10、16、17、40、60 |
| `ecra/protection.py` | 摘要驱动的屏蔽转移；汇编指令语义；逐对判定；站点函数 | 31、32、33 |
| `ecra/interrupts.py` | 优先级恢复 v2；MHP 方向格 | 48、51 |
| `ecra/common.py` | 结构化库语义表（方向、是否保留指针、长度参数） | 19 |
| `ecra/report.py`、`ecra/html_report.py` | RR_build / RR_all；见证与证明展示；翻转报告；根因 v2 | 01、02、62 |
| 新增 `ecra/layout.py` | 存储布局、区间树、位域组 | 21、23 |
| 新增 `ecra/summaries.py` | 函数摘要（SCC 自底向上） | 53 |
| 新增 `ecra/phase.py` | 使能事件、HB 数据流（取代 `_build_phase_model`） | 13、50 |
| 新增 `ecra/vectors.py` | 启动文件 / C 向量表 / VTOR 解析 | 46 |
| 新增 `ecra/handles.py` | 句柄形参识别、克隆、路径裁剪 | 43 |
| 新增 `ecra/coherence.py` | 一致性 v2 | 12、24 |
| 新增 `ecra/witness.py` | 见证、ProofRecord、聚类 | 02、60 |
| 新增 `ecra/refine.py` | Stage B 调度与精化器 | 61 |
| 新增 `ecra/diagnostics.py` | 根因 v2、反事实统计、热点聚类 | 02 |
| `ecra/workflow.py` | `engine_digest` 加入新模块（`ecra/workflow.py:24-26`），使旧结论和复核缓存随引擎变化失效 | 全部 |

### 17.3 算法规格

| 编号 | 算法 | 输入 → 输出 | 复杂度 | 健全性要点 |
|---|---|---|---|---|
| A1 | 访问路径构造与别名基路径组合 | AST 祖先链 → `path_steps` | 线性 | 解引用截断；无法解析即回退并记录 |
| A2 | 布局区间与重叠查询 | 记录布局 → 每个根一棵区间树；查询 A(r) | O(log n + k) | union / 位域组 / 整对象按字节或位区间相交 |
| A3 | 函数摘要 | 调用图 SCC 自底向上 | 近线性 × 迭代 | 递归 SCC 取不动点；不透明调用置未知 |
| A4 | 使能事件数据流与 HB | 前台过程间 CFG → `hb(w, X)` | O(CFG 节点数 × IRQ 数 / 字长) | 未识别机制 = ANY；无使能证据的 IRQ 视为复位即可能使能 |
| A5 | 屏蔽抽象解释 v2 | CFG + 摘要 + 汇编语义 → 每访问屏蔽状态与窗口 | 现有格不变 | 未知节点局部化；调用用摘要转移函数 |
| A6 | 逐对保护 | 见证对 + 窗口 + 优先级 → 排除 / 保留 | 每对线性 | NMI / HardFault / DMA 不可屏蔽 |
| A7 | 一致性 v2 | 写组 / 读组（含访问器摘要）+ MHP + 方向 → D-07 见证 | 每 root 成对 | 条件 C1–C7（§14.2） |
| A8 | NR 门槛 v2 | 资源 + 访问 + 布局 + 摘要 → NR 逐项结果 | 线性 | 缺口优先；守门失败即 SUSPECT |
| A9 | UNK 上下文与分派点界定 | 种子 + 未解析调用点 + 向量证据 → 上下文集合 | 线性 | 闭包不完整或地址逃逸时不界定 |
| A10 | 类型过滤的间接调用解析 | 指向集 + 规范函数类型 → 目标集合 | 线性 | 出现强转 / `void*` 中转 / 无原型即不过滤 |
| A11 | 句柄敏感传播 | 句柄形参 + 调用点绑定 → 克隆上下文 | 受克隆上限约束 | 绑定非单元素或逃逸即合并 |
| A12 | 见证聚类与反事实 | 全部见证 → 热点元素排名、去掉某类近似后的翻转数 | 线性 | 只用于诊断与调度，不参与裁决 |

### 17.4 性能约束

- Stage A 耗时 ≤ 当前 1.3 倍（betaflight 基准约 780 s）；A2 区间查询减少行数，可部分抵消新增分析的开销。
- A11 的克隆数、A5 的过程间求值深度、Stage B 的预算都可配置，超限一律退回保守结果并计数报告。
- 每个阶段在三工程上记录分阶段耗时与峰值内存（沿用此前 `ECRA_TIMING` 计时方法，完成后移除临时代码）。

---

## 18. 单元测试、黄金风险样例与回归测试（需求 20）

### 18.1 必须保持的现有测试

`tests/test_preclassification.py` 的 T01–T18、G1–G11 与其它用例；`tests/test_design_acceptance.py` 的屏蔽与优先级用例（嵌套禁用、两端屏蔽但窗口打开、分支汇合、提前返回、条件解除屏蔽、保存恢复、覆盖保存键、局部指针改写保存键、memset 改写保存键、辅助函数继承屏蔽、辅助函数先解除屏蔽、分离辅助函数不能掩盖窗口、无序表达式、循环出口、循环内 RMW、独立辅助函数 RMW、goto、更高优先级 IRQ 未被屏蔽、未调用 / 条件优先级设置不是证据）；`tests/test_serial_regressions.py`、`tests/test_large_project.py`、`tests/test_ecra.py` 全部用例；`examples/stm32_demo/cases` D01–D20（`scripts/verify_design.py --all`）。

预期需要随设计调整断言的测试（调整须附设计理由并经评审，不得为“让测试通过”而改）：`test_unsupported_goto_preserves_uncertainty`（OPT-30 支持 goto 后改为“间接 goto / 未知汇编保持不确定”）；依赖“位域无条件 SUSPECT”的用例（G7 的结论不变，但依据改为位域组）。

### 18.2 新增单元测试（按模块）

| 模块 | 测试要点 |
|---|---|
| `extract` / `pointer_extract` | 嵌套路径顺序（`a.b.c`、`a.arr[i]`、`a.b.arr[i].c`）；别名基路径；指针成员解引用截断（P33）；汇编操作数方向；规范类型种类与尺寸；位偏移与 packed；变量段属性；`mmio:` 位置；常量下标 |
| `layout` | union 视图重叠；位域组边界（`:0`、非位域成员）；结构体数组字段；memcpy/memset 范围；类型双关回退 |
| `controlflow` | for / switch（fallthrough、default、嵌套 break）/ goto / label / `__cleanup__`；未知汇编局部化 |
| `summaries` | 访问器返回成员、setter、递归 SCC、不透明调用、保留指针、存储次数 |
| `phase` | 各类使能识别；`UNKNOWN_MAY_ENABLE`；循环内使能；多调用点入口状态并集；无使能证据的 IRQ |
| `protection` | 汇编指令语义；摘要驱动的无序表达式；站点函数；逐对判定 |
| `interrupts` / `mhp` | SPL / libopencm3 / 直接寄存器优先级；相同值多次设置；使能后重设放弃；方向格 |
| `handles` | 句柄形参识别；克隆上限；指针相等与字段常量裁剪；非单元素绑定退回 |
| `coherence` | C1–C7 每条件的正反例 |
| `classify` | §4.6 顺序；不变式 I-1–I-3 的断言（构造违例必须抛错） |
| `witness` / `refine` | ProofRecord 完整性；Stage B 不改变 SAFE/NR；预算耗尽返回无法排除 |
| `report` | RR_build / RR_all 分子分母一致；翻转矩阵 |

### 18.3 黄金风险样例集（GR，必须永远不是 SAFE / NO_REVIEW）

| ID | 对应 HR | 内容 | 来源 |
|---|---|---|---|
| GR-01…GR-11 | HR-01…HR-11 | 现有 G1–G11、T06、T11、T14、T16、D04–D07、D09、D17–D19 迁入统一目录 | 现有 |
| GR-09b | HR-09 | value+valid 经访问器读取 | P6 |
| GR-11b | HR-11 | 同优先级多写者 + 前台 64 位读者 | P28 |
| GR-12 | HR-12 | union 重叠视图跨域写 | P1 |
| GR-13 | HR-13 | packed 不对齐成员 | P27 |
| GR-14 | HR-14 | 内联汇编输出操作数 / 汇编文本写 | P23 |
| GR-15 | HR-15 | libopencm3 / SPL / `NVIC->ISER` / 无源码 BSP 四种未识别使能之后的初始化写 | P9 |
| GR-16 | HR-16 | 单写者 + 地址逃逸 | P25 |
| GR-17 | HR-17 | NMI / HardFault 竞争者 | 新 |
| GR-18 | HR-18 | BASEPRI 阈值不足 | 现有 |
| GR-21 | HR-21 | 中间值暴露（前台 `idx++; if (idx>=N) idx=0;` + ISR 以 idx 为下标读） | 新 |
| GR-22 | HR-22 | 非 volatile 轮询 | 新 |
| GR-23 | HR-23 | 可重入任务写者 | 现有 |
| GR-24 | HR-24 | 寄存器级 DMA 缓冲（M0AR / SPL 初始化结构 / LL / libopencm3 四种） | P31 |
| GR-25 | HR-25 | 句柄分支依赖运行期可变字段，不得裁剪 | 新 |
| GR-26 | HR-26 | 未知上下文读 64 位（回调地址交给无源码注册函数，无法界定）；`SCB->VTOR` 发布后表内函数成为 ISR | P30 变体 |
| GR-27 | HR-27 | 库函数经指针写 | P29 |
| GR-28 | HR-28 | 逆序路径同名误归属 | 新 |
| GR-29 | HR-29 | 同一处理函数挂在不同优先级的两个向量 | 新 |
| GR-30 | HR-30 | SysTick / PendSV 与外部 IRQ 冲突且系统异常优先级未证明 | 新 |
| GR-31 | HR-04 | ISR 置位 / 前台读后清零的错误标志（§3.6 `cli.uart_error` 同构） | §3.6 |
| GR-32 | HR-06 | DMA 循环 / 双缓冲模式下 CPU 读写 | 新 |
| GR-33 | HR-01 | 前台在运行期复位环形缓冲索引（错误恢复路径），ISR 同时入队写索引（§3.6 `cli.rx_head` 同构） | §3.6 |

### 18.4 黄金精度样例集（GP，修复后必须得到指定的非队列结论）

| ID | 内容 | 期望 | 来源 |
|---|---|---|---|
| GP-01 | typedef 标量单写者 | SHARED_NO_REVIEW | P10 |
| GP-02 | 枚举单写者（含 `-fshort-enums`） | SHARED_NO_REVIEW | P10 |
| GP-03 | 嵌套成员写不污染兄弟成员 | `s.x` SAFE_READ_ONLY | P2 |
| GP-04 | 结构体内数组写不污染兄弟成员 | `r.tail` 不因 ISR 写 `r.buf[]` 成为双写者 | P32 |
| GP-05 | 单域位域 | SAFE_SINGLE_FOREGROUND | P3 |
| GP-06 | 结构体数组不同字段 | 不因 D-01 SUSPECT | P16 |
| GP-07 | `:0` 分隔的两个位域组 | 互不影响 | 新 |
| GP-08 | 临界区内含 for 循环 | SAFE_EFFECTIVE_PROTECTION | P4 |
| GP-09 | 函数其它位置存在 `g = f()` | 独立临界区仍 EFFECTIVE | P21 |
| GP-10 | 临界区内调用 `__NOP()` | EFFECTIVE | P22 |
| GP-11 | 被调函数内屏蔽的经形参访问 | EFFECTIVE | P8 |
| GP-12 | 注册式句柄回调 | 各实例单 IRQ | P13 |
| GP-13 | 弱回调中按句柄指针相等分支 | 各实例单 IRQ | P14 |
| GP-14 | 同优先级 ISR 的成对读 | 不因 D-07 SUSPECT | P7 |
| GP-15 | 互斥分支中的读 | 不因 D-07 SUSPECT | P12 |
| GP-16 | 从未分派的函数指针表（闭包完整、无向量证据） | SAFE_SINGLE_FOREGROUND | P5 |
| GP-17 | DMA 启动前填充、之后只读 | 不因 D-03 SUSPECT | P18 |
| GP-18 | 在 IRQ 使能前写入、ISR 只读的配置 | SAFE_ORDERED_INIT | P24 变体 |
| GP-19 | SPL `NVIC_Init` 设置同优先级的两个 ISR 双写 | SAFE_NON_INTERLEAVING | 新 |
| GP-20 | libopencm3 `nvic_set_priority` 同优先级 | SAFE_NON_INTERLEAVING | 新 |
| GP-21 | 以 `cpsid i` 汇编实现的屏蔽封装 | EFFECTIVE（无需配置） | 新 |
| GP-22 | `for` + `__cleanup__` 实现的 BASEPRI 临界区（优先级可证） | EFFECTIVE | 新 |
| GP-23 | 前台屏蔽 RMW、两个 ISR 只读 | EFFECTIVE | 新 |
| GP-24 | `strcmp` 只读实参 | 不产生逃逸 | 新 |
| GP-25 | 按值传给名字含 DMA 的函数 | 不产生 DMA 缺口 | P26 |
| GP-26 | HAL 句柄 `Init.*` 在 `MX_*_Init` 中写、ISR 读 | SAFE_ORDERED_INIT | §3.6 |
| GP-27 | `h->Instance->CR1 \|= x` | `Instance` 不因 ISR 成为写者 | P33 |

### 18.5 回归测试

- **基准快照测试**：每个验证工程保存一份期望分类摘要（四类计数、按原因码计数、全部 S/U 的 symbol_id 列表）；任何变化都必须附已审批的翻转报告才能更新快照。
- **确定性**：同一输入连续两次运行，四类结论、见证、ProofRecord 完全一致。
- **性能**：Stage A / Stage B 耗时、峰值内存超出预算即失败。
- **事实规模**：facts 行数与 JSON 体积超出上一版本 20% 时必须说明原因。

### 18.6 注入式测试

新增脚本（建议 `scripts/inject_races.py`，与 `D:/ecra-bench` 回放链路配合）：在验证工程的副本中，于真实存在的 ISR 处理函数与前台函数里插入 HR 模式片段（新全局变量或已有全局的额外访问，标识符随机生成），生成变体工程并运行；断言注入变量为 SUSPECT / UNKNOWN、见证指向注入行。每工程每类 HR 至少 1 个注入点，结果计入 §20 的 recall 指标。

### 18.7 遗留损坏处理（OPT-1A，P0，阶段 1）

`tests/test_acceptance.py` 引用仓库中不存在的 `validation/stm32_concurrency/verify_acceptance.py`，全量套件恒有 1 个 error。测试套件要作为合入门禁，必须是全绿：从版本历史恢复该文件，或在记录理由后移除该测试【需进一步确认该文件的来源】。

### 18.8 测试矩阵

| 阶段 | 单元测试 | GR | GP | 基准快照 | 注入 | 抽样审计 |
|---|---|---|---|---|---|---|
| 0 | 指标、原因码 | 全部 | — | 建立 | 建立脚本 | — |
| 1 | 健全性修复 | 全部 + GR-12…GR-27 | — | 更新（翻转报告：上升） | 运行 | 翻转审计 |
| 2 | 路径、布局、宽度、位域、一致性 | 全部 | GP-01…GP-07、GP-14、GP-15、GP-27 | 更新 | 运行 | 翻转审计 |
| 3 | CFG、摘要、保护 | 全部 | GP-08…GP-11、GP-21…GP-23 | 更新 | 运行 | 翻转审计 |
| 4 | 上下文精度 | 全部 | GP-12、GP-13、GP-16 | 更新 | 运行 | 翻转审计 |
| 5 | 时序与硬件 | 全部 | GP-17…GP-20、GP-26 | 更新 | 运行 | 翻转审计 |
| 6 | Stage B | 全部（两种模式） | 全部 | 更新 | 运行 | 翻转审计 + 影子审计 |
| 7 | — | 全部 | 全部 | 冻结 | 全部工程 | 最终分层审计 |

---

## 19. 大型真实 STM32 裸机项目验证规划（需求 21）

### 19.1 验证工程集

| 编号 | 工程 | 平台 / 框架 | 规模 | 覆盖的模式 | 状态 |
|---|---|---|---|---|---|
| V1 | klipper | STM32F405；CMSIS + 自有驱动；协作调度 + IRQ；`irq_save/irq_restore` | 58 TU，889 变量 | 内联汇编屏蔽封装（RC-4）、函数指针表分派、汇编尾跳转 reset 链 | 已有（`D:/ecra-bench/klipper`） |
| V2 | blackmagic | STM32F103；libopencm3；USB 设备栈 | 192 TU，691 变量 | 局部别名与嵌套路径（RC-3）、命令表 / 目标驱动回调（RC-6）、libopencm3 使能 / 优先级（RC-5、RC-7） | 已有 |
| V3 | betaflight | STM32F405；SPL + 自有驱动；任务表调度；大量 DMA 流 ISR；ELRS ISR 驱动 | 497 TU，7630 变量 | 描述符表 / 段回调合并（RC-1）、`ATOMIC_BLOCK`（RC-4）、SPL `NVIC_Init`（RC-5）、寄存器级 DMA（FS-9） | 已有 |
| V4 | 大型 CubeMX HAL 裸机工程 | STM32Cube HAL / LL | 目标 ≥150 TU 或 ≥1500 变量 | HAL 句柄与回调（RC-1 H1–H3）、`MX_*_Init` 初始化次序（RC-7）、HAL DMA | **需用户提供**：用户报告 >50% 的大型工程【需进一步确认工程身份与可用性】；备选为开源 HAL 裸机工程（如 candleLight_fw 一类 USB-CAN 固件【需进一步确认其构建方式与规模】）或 STM32Cube 官方例程集合（规模较小，只作模式补充） |
| V0 | `serial - opencode` | STM32F103；CubeMX HAL | 20 TU，44 变量 | 小型 HAL 对照样本（§3.6） | 已有，只读重放 |

V1–V3 满足“至少 3 个大型真实 STM32 裸机工程”的要求；三者都不使用 STM32 HAL，所以 V4 是验证 HAL 相关设计（§9、§11）的必要补充。

### 19.2 每个工程的验证流程

1. 固定 commit 与 `compile_commands.json`；`semantics-ecra.yaml` 只包含构建目标、目录范围、上下文入口声明（与现有基准约定一致），不得包含任何为降低比例而写的条目。
2. 冻结提取产物（worker parts），修改提取器的阶段按既有 `reextract_compiled.py` 流程重新提取并重新冻结。
3. 每个阶段回放：四类计数、RR_build / RR_all、原因码分布、翻转矩阵、分阶段耗时与内存。
4. 每个阶段的翻转审计；阶段 7 做最终分层抽样（每工程 ≥60）。
5. 注入式竞态（每类 HR ≥1 个注入点）。
6. 对剩余 S/U 做 §21 的根因定位，区分“精度缺口 / 真实风险 / 证据缺失”，形成诚实残留报告。

### 19.3 各工程的关注点与预期（预期均为估计，必须以回放为准）

| 工程 | 当前 RR_build | 主要预期变化 | 风险 |
|---|---|---|---|
| V1 klipper | 5.4% | 健全性修复可能小幅上升；OPT-31 识别 `cpsid` 封装后，38 个 PARTIAL 中真实受保护者转为 EFFECTIVE（数量【需进一步确认】） | 唤醒标志等真实双写必须保持 |
| V2 blackmagic | 21.0% | OPT-20 上界 −19 个 SUSPECT；一致性成员 67 → ≤42（上界）；OPT-40/41 处理 47 个 UEC；libopencm3 使能 / 优先级识别 | `st_usbfs_dev.*` 初始化写 + USB ISR 的处理取决于 §9.4 决策 |
| V3 betaflight | 32.6% | OPT-18 可能**增加** DMA 相关 S/U；RC-1 只能消除上下文倍数，MSP 经 ELRS 在 ISR 中处理是真实路径；OPT-51 识别 SPL 优先级 | 可能无法靠精度降到 10%，须按 §23.4 出具诚实残留报告 |
| V4 HAL | 未知 | HSCP、路径修复、HB（A）对句柄字段影响最大；HAL 内部协议字段需 OPT-80 | 工程身份待定 |
| V0 | 68.2% | 估计 P0/P1 后 41%–45%，OPT-80 后 30%–34%（§3.6） | 小工程共享状态密度高且含真实缺陷，不作 10% 考核 |

### 19.4 交付物

每个工程一份 `docs/validation_<工程>.md`：工程信息与固定 commit、各阶段数字、翻转报告摘要、抽样审计表、注入结果、残留 S/U 的根因构成与典型源码证据、仍无法静态解决的边界。

---

## 20. 优化前后需要统计的指标与 Benchmark 方法（需求 22）

### 20.1 指标定义

| 指标 | 定义 | 用途 |
|---|---|---|
| TOTAL_BUILD | `coverage_source == compile_database`、非结构体容器、非 DEPENDENCY_DECLARATION 的资源数 | 主分母 |
| VARIANT_INVENTORY | `coverage_source ∈ {supplemental, inactive_branch}` 的声明数（ACCESS_NOT_ANALYZED） | 单列展示，不隐藏；补救方式是把每个交付变体作为独立构建扫描 |
| DEPENDENCY_DECLARATION | 定义不在构建闭包内的声明数（现有） | 盘点 |
| SAFE / NR / S / U | TOTAL_BUILD 上的四类计数 | — |
| **RR_build** | (S + U) / TOTAL_BUILD | **10% 目标的建议分母**（需用户确认，§24 Q-07） |
| RR_all | (S + U + VARIANT_INVENTORY) / (TOTAL_BUILD + VARIANT_INVENTORY) | 与 RR_build 并列展示，替代当前 `review_rate` 的混合口径 |
| Review Items（辅助） | 按“同一 root + 同一见证签名”聚类后的复核项数 | 衡量人工投入；**不用于 10% 考核** |
| 原因分布 | 按破坏性模式码 D-xx、缺口码、NR 失败项统计；多原因各计一次；另给反事实“最小充分原因” | 根因排序 |
| `refinable_by` 分布 | §15.2 的标记计数 | Stage B 调度 |
| 精化贡献 | 每个 OPT / 精化器的消融结果（开启与关闭时 S/U → SAFE/NR 的变量数） | 证明收益来自哪项分析 |
| 健全性修复增量 | 阶段 1 引起的 SAFE/NR → S/U 变量数 | 如实披露 |
| false-safe 指标 | GR 通过率（必须 100%）、注入检出率（必须 100%）、抽样数 n、发现的 false-safe 数（必须 0）、95% 上界 3/n | G1 |
| SUSPECT 确认率 | OpenCode / 人工复核中“确认风险”的比例 | 衡量 SUSPECT 的精度（非安全依据） |
| UNKNOWN 局部性 | 单一缺口码占比、每个 UNK 种子影响的变量数（沿用 `blocker_fanout`，`ecra/classify.py:966-977`） | 发现过度传播 |
| 稳定性 | 同一输入两次运行的结论差异数（必须 0） | 确定性 |
| 性能 | 分阶段耗时、峰值内存、facts 体积 | G4 |

### 20.2 Benchmark 方法

1. **冻结输入**：每个工程的 worker parts（`<project>/.ecra/workers/*.response.json`）、`semantics-ecra.yaml`、引擎摘要（`ecra/workflow.py:24-26`）。修改提取器的阶段重新提取并重新冻结（`D:/ecra-bench/reextract_compiled.py`）。
2. **回放**：沿用 `D:/ecra-bench/bench_one.py` 的进程内 merge + analyze 链路；betaflight 采用内存内重建（其 dump 无法整体载入）。
3. **消融**：开发期每个 OPT 设引擎内部开关（不进入用户配置），用于测量单项贡献；验收时全部开启，开关随后移除。
4. **输出格式**：每次回放输出统一 JSON：`{project, commit, engine_digest, totals, rr_build, rr_all, variant_inventory, reasons, refinable_by, flips{from→to: [symbol_id…]}, proof_codes, timings, peak_memory, facts_size}`。
5. **翻转矩阵**：4×4 类别转移矩阵（上一快照 → 本次），每格附变量列表；S/U → SAFE/NR 附证明码与 ProofRecord。
6. **记录**：每个阶段把目标、修改文件、测试结果、各工程数字、审计结论写入 `docs/classifier_progress.md`（延续既有格式）。
7. **合入门禁**：单元测试全绿；GR 100%；GP 达到该阶段要求；快照变化均有已审批的翻转报告；性能在预算内。

### 20.3 报告模板（每阶段）

| 工程 | TOTAL_BUILD | SAFE | NR | S | U | RR_build | RR_all | 本阶段 S/U→SAFE/NR | 本阶段 SAFE/NR→S/U | 抽样 n / false-safe | 耗时 |
|---|---|---|---|---|---|---|---|---|---|---|---|

### 20.4 用户大型工程的口径核对步骤

1. 读取该工程 `.ecra/facts.json`（或 `facts.db`），按 `coverage_source` 与 `static_classification` 交叉计数；
2. 分别计算 RR_build 与 RR_all，确认 >50% 中补充盘点声明所占份额；
3. 对编译变量部分按 §21 的流程定位根因。

（§3.6 的 CubeMX 工程按此核对：补充盘点为 0，68.2% 全部来自编译变量。）

---

## 21. Review Rate > 10% 时继续定位 Top 根因的流程（需求 23）

### 21.1 定位流程

| 步骤 | 动作 | 产出 | 判定 |
|---|---|---|---|
| 0 | 口径核对：RR_build、RR_all、VARIANT_INVENTORY、DEPENDENCY_DECLARATION | 口径表 | 若主要是补充盘点 → 扫描各构建变体，不属于精度问题 |
| 1 | 结构化原因分布：D-xx、缺口码、NR 失败项；按资源种类、root、目录分层 | 原因表 | 找出占比最大的模式 |
| 2 | 反事实统计（§21.3）：对每类可精化近似，计算“若该近似被排除，会有多少变量离开队列” | 反事实表 | 排出精化收益上界 |
| 3 | 见证聚类：按边、上下文、函数、root 聚类，输出 Top-20 热点元素（例如“某间接调用点 → 影响 N 个变量”“某上下文 → 出现在 N 个见证中”） | 热点表 | 定位“一处精化影响多变量”的位置 |
| 4 | 抽样分诊：每个热点抽 10–20 个变量，人工判定为“真实风险 / 静态精度缺口 / 证据缺失” | 分诊表 | — |
| 5 | 决策：精度缺口 → 设计通用规则（新增 OPT，走 §16.3 流程）；真实风险 → 诚实保留并记录证据；证据缺失 → 给出恢复动作（补 TU、补入口声明），只能增加证据 | 决策记录 | 禁止名单排除、禁止放宽检测器 |
| 6 | 实施、回放、翻转审计，更新根因报告 | 新一轮数字 | — |
| 7 | 若剩余队列主要是真实风险，按 §23.4 出具诚实残留报告 | 残留报告 | 用户签核 |

### 21.2 工具（OPT-02，P0，阶段 0）

新增 `ecra/diagnostics.py`，每次运行生成：

- `reports/classification_root_causes.md`（v2）：基于分类器输出的结构化原因码，替代字符串匹配；多原因与“最小充分原因”分开统计；补正 §3.1 的 DMA 桶误归类。
- `reports/root_cause_v2.json`：机器可读的原因、反事实与热点数据。
- `classification_quality.html` 增加“热点元素”与“反事实收益”两张表。

同时把 `D:/ecra-bench/baseline_roots.py` 的桶逻辑改为直接读取上述结构化输出，避免两套口径。

### 21.3 反事实统计的定义

对变量 v 的见证集合 W(v) 与缺口集合 G(v)，以及一类近似 X（如“扇出 > 1 的 may-target 边”“路径回退继承行”“UNKNOWN_PREEMPTION”“CFG 不完整导致的保护未证明”“UNK 上下文”）：

```text
flip_X(v) = 1  当且仅当  W(v) 中每个见证都依赖 X（去掉 X 后该见证不成立）
                      且 G(v) 中每个相关缺口都依赖 X
CF(X) = Σ_v flip_X(v)        # 若 X 被完全精化，最多可离开队列的变量数（上界）
```

`CF(X)` 只用于排序与调度，**从不**直接改变任何变量的结论。§3.3 中 blackmagic “19 个 SUSPECT 去掉回退继承行后不再有跨域写”就是这一统计的手工版本。

### 21.4 “真实风险 / 精度缺口 / 证据缺失”的判定准则

| 类别 | 判定依据 | 本次分析中的实例 |
|---|---|---|
| 真实风险 | 见证中的每条访问、每个上下文推导都是可达的真实路径，且不存在保护 / 次序 | `cli.uart_error`（ISR 置位、前台清零）、`cli.rx_head`（前台运行期复位、ISR 入队），见 §3.6；betaflight 经 ELRS 在 ISR 中执行的 MSP 配置写（§3.3 RC-1） |
| 精度缺口 | 见证依赖某个可以被更精确分析证伪的近似 | `huart2.Init.*` 的回退继承写（RC-3）；`huart2.Instance` 的解引用误判（M-40）；同优先级 ISR 的一致性（P7） |
| 证据缺失 | 结论依赖工具看不到的信息 | 无源码的库、缺失 TU、未声明的动态入口——恢复动作只能补证据 |
| 静态边界 | 需要运行期信息或语义意图 | HAL 内部协议字段（未启用 OPT-80 时）、运行期配置的分派、跨对象语义耦合 |

---

## 22. 实施阶段、优先级与里程碑

### 22.1 P0 强制要求清单

| OPT | 内容 | 章节 |
|---|---|---|
| OPT-00 | 冻结基线与回放链（三工程 + V0；V4 到位后加入） | §20.2 |
| OPT-01 | 指标口径修正（RR_build / RR_all，报告分子分母一致） | §1.3、§20.1 |
| OPT-02 | 结构化原因码、最小见证、反事实与热点工具 | §21.2 |
| OPT-03 | 证据 ID 稳定化（修复 `inherited_from_access_id` 断链） | §3.3 RC-3 |
| OPT-10 | NO_REVIEW 前检查相关缺口（FS-4） | §8.2 |
| OPT-11 | union 重叠最小修复（FS-1） | §13.2 |
| OPT-12 | 一致性读组纳入访问器（FS-2） | §14.2 |
| OPT-13 | 健全的使能事件模型（FS-3） | §9.2 |
| OPT-14 | 内联汇编操作数与文本引用（FS-5） | §10.4 |
| OPT-15 | 有效对齐（FS-6） | §8.3 |
| OPT-16 | SAFE_NON_INTERLEAVING 读者撕裂检查（FS-7） | §8.4 |
| OPT-17 | 未知上下文读参与判定（FS-8） | §6.3 |
| OPT-18 | 地址发布到外设寄存器 / 寄存器级 DMA（FS-9） | §7.4 |
| OPT-19 | 标准库语义统一（FS-10） | §10.3 |
| OPT-1A | 修复或记录移除 `test_acceptance` 遗留损坏 | §18.7 |
| OPT-20 | 访问路径代数与解引用截断（RC-3、M-40、FS-11） | §10.2 |
| GR 集 | §5.2 / §18.3 全部硬守门测试 | §18.3 |

### 22.2 阶段计划

| 阶段 | 内容（OPT） | 优先级 | 依赖 | 退出条件 | 预期影响（估计） |
|---|---|---|---|---|---|
| 0 度量与基线 | 00、01、02、03 | P0 | — | 四工程（V1–V3、V0）基线与根因 v2 可复现；`classifier_progress.md` 记录 | RR 不变（只改度量） |
| 1 健全性修复 | 10–19、1A | P0 | 0 | GR 全部通过；P1/P6/P9/P23/P25/P27/P28/P30/P31 达到附录 A 的期望；翻转报告 | RR **可能上升**（betaflight 的寄存器级 DMA 影响【需进一步确认】） |
| 2 资源粒度与证据精度 | 20（P0）、21、22、23、24、25 | P0/P1 | 1 | 回退行只剩真实类型双关；GP-01…07、14、15、27 通过 | blackmagic 上界 −19 个 SUSPECT，一致性成员 67 → ≤42；V0 约 −3（另 7 个 `huart2.Init.*` 要到阶段 5 的 HB(A) 才能离开队列，§3.6）；betaflight【需进一步确认】；OPT-25 可能增加 S |
| 3 控制流与保护 | 30、31、32、33、34、53 | P1 | 2 | CFG 完整率（不计间接 goto / 未知汇编）≥95%；GP-08…11、21…23 通过 | klipper 38 个 PARTIAL 中真实受保护者转出【需进一步确认】 |
| 4 上下文精度 | 40、41、42、43、44、45、46、47、48 | P1（45、47 为 P2） | 2、3 | GP-12、13、16 通过；影子审计通过 | blackmagic 47 个 UEC 的转换【需进一步确认】；HAL 多实例回调；betaflight 上下文倍数 |
| 5 时序与硬件 | 50（A 默认；B 待确认）、51、52 | P1 | 3、4 | GP-17…20、26 通过 | HAL 句柄初始化字段（V0 约 −7）；blackmagic `st_usbfs_dev.*`（取决于 §9.4）；betaflight 优先级 |
| 6 两阶段精化 | 60（Stage A 见证与 `refinable_by`）、61（Stage B 精化器 B1–B8 + ProofRecord + 预算）、62（影子模式与翻转报告） | P1 | 2–5 | 差分不变式成立；影子审计通过 | 剩余队列中可精化部分 |
| 7 验证与验收 | 70：V1–V4 全流程、注入、最终分层抽样、诚实残留报告 | P0 | 全部 | §23.1 验收标准 | — |
| 可选 | 80 外设中断源级次序；81 发布-订阅（SPSC）协议证明（需用户签核）；82 链接 map / ELF 证据；83 Review Items 聚类展示 | P2 | 5、6 | 各自影子审计 | HAL 工程的协议字段与初始化次序（80） |

### 22.3 关键依赖

- OPT-20 必须先于一致性 v2（OPT-24）与全部一致性统计，否则统计被回退放大污染。
- OPT-53（函数摘要）是 OPT-30/31（无序表达式）、OPT-12/24（访问器、写事务）、OPT-13/50（使能效果）的共同基础，放在阶段 3 开始时完成；阶段 1 的 OPT-12、OPT-13 先用“一层访问器 / 保守的函数级使能标记”实现，阶段 3 换成摘要。
- OPT-18（`mmio:` 位置）是 OPT-46（VTOR）、OPT-52（DMA 生命周期）、OPT-80 的前提。
- OPT-43（HSCP）依赖 OPT-44（经形参存储按调用点求值）与 OPT-32（站点函数）。

---

## 23. 最终验收标准、失败条件与不可接受的实现方式（需求 24）

### 23.1 验收标准

| 编号 | 标准 |
|---|---|
| A-1 | 黄金风险样例集（§18.3）100% 不是 SAFE / NO_REVIEW；两种模式（仅 Stage A、Stage A+B）都满足 |
| A-2 | 注入式竞态在 V1–V4 上检出率 100%，见证指向注入点 |
| A-3 | V1–V4 最终分层抽样（每工程 ≥60，每证明码 ≥10，新证明码 ≥20）发现 0 例 false-safe，报告 95% 上界 |
| A-4 | 每个阶段的翻转审计完成且无 false-safe；健全性修复引起的上升已单列披露 |
| A-5 | 不变式 I-1…I-8 以运行期断言形式存在，三工程运行无违例 |
| A-6 | 每个 SAFE 有证明码 + 证据 + 假设；每个 NO_REVIEW 有 NR 逐项结果；每个 SUSPECT 有最小见证；每个 UNKNOWN 有精准缺口码 + 阻塞证据 + 恢复动作 |
| A-7 | 大型工程（V1–V4）RR_build ≤ 10%；对未达标的工程，按 §23.4 提交诚实残留报告并经用户签核，视为有条件通过 |
| A-8 | RR_build 与 RR_all 同时展示，补充盘点声明未被隐藏 |
| A-9 | 全部收益可归因：每个 OPT 有消融数据，证明降噪来自更精确的静态证明 |
| A-10 | 没有任何项目名、变量名、函数名、目录名特例；`semantics-ecra.yaml` 只含构建目标、目录范围、入口声明 |
| A-11 | Stage A 耗时 ≤ 当前 1.3 倍；Stage B 在预算内；同输入结果确定 |
| A-12 | 全量单元测试全绿（含 `test_acceptance` 遗留问题的处理），D01–D20 全部符合期望 |

### 23.2 失败条件（任一出现即判定失败，须回退或返工）

| 编号 | 失败条件 |
|---|---|
| F-1 | 任一 GR 样例被判为 SAFE / NO_REVIEW |
| F-2 | 抽样或翻转审计中发现 false-safe，且根因未以通用规则修复 |
| F-3 | 注入式竞态有任何一例未检出 |
| F-4 | 某个 S/U → SAFE/NR 的变化没有 ProofRecord，或其证据切片中存在相关缺口 |
| F-5 | Review Rate 下降不能归因到具体 OPT 的消融数据 |
| F-6 | 出现名称 / 路径 / 项目特例，或配置中出现删除风险的条目 |
| F-7 | 为了比例删除访问事实、上下文事实，或修改检测器条件而无风险语义论证 |
| F-8 | 补充盘点声明被移出展示，或 RR 口径在报告中不一致 |
| F-9 | 性能超出预算导致大型工程不可用 |
| F-10 | 结论不确定（同输入两次结果不同） |

### 23.3 不可接受的实现方式

| 编号 | 不可接受的做法 |
|---|---|
| X-1 | 按变量名、函数名、文件名、目录、项目名排除或降级 |
| X-2 | 提高阈值或放宽检测器条件来减少 SUSPECT（例如把多字段一致性改为“≥3 个成员”） |
| X-3 | 把 UNKNOWN 直接改判为 SAFE / NO_REVIEW 而不消除缺口 |
| X-4 | 把 `volatile`、访问宽度、单写者本身当作 SAFE 依据 |
| X-5 | 用 `known_safe`、`protection`、`resources` 等配置声明消除风险 |
| X-6 | 用 OpenCode 或人工复核结论回写静态分类 |
| X-7 | 隐藏或不计入补充盘点声明、依赖声明、GAP 发现 |
| X-8 | 扩大审计排除范围（`exclude_dirs` 等）来降低比例 |
| X-9 | 截断分析（调用链、指向集、冲突对）后把未分析部分视为安全 |
| X-10 | 精化器预算耗尽、遇到未建模语句时默认“可以排除” |
| X-11 | 把 may-target 边或上下文直接删除而没有证伪证明 |
| X-12 | 假设“ISR 不会在某时刻之前运行”而没有健全的使能模型 |
| X-13 | 在测试中修改 GR 期望结论以通过测试 |
| X-14 | 单独修正库函数名比较（FS-10）而不补齐 points-to 语义 |
| X-15 | 用“库可信”替代证明（例如把 HAL 内部字段直接视为安全），除非用户明确做出审计范围决策（§24 Q-18） |
| X-16 | 用 Review Items 聚类数冒充 RR 达标 |

### 23.4 诚实残留规则（RR_build 仍 > 10% 时）

1. 残留 S/U 全部具备 A-6 要求的证据；
2. 按 §21 完成定位，给出“真实风险 / 精度缺口 / 证据缺失 / 静态边界”的构成与样例源码；
3. 对“精度缺口”部分给出后续 OPT 计划，对“证据缺失”部分给出恢复动作；
4. 对残留 SUSPECT 抽样复核，报告确认为真实风险的比例；
5. 由用户签核后，该工程的 10% 目标视为“已证明在当前静态能力下不可在不牺牲健全性的前提下达到”。

---

## 24. 风险与需进一步确认事项

### 24.1 需进一步确认 / 需用户决策

| 编号 | 事项 | 确认方法 / 决策内容 |
|---|---|---|
| Q-01 | 用户 >50% 的大型工程中补充盘点声明所占比例 | §20.4 |
| Q-02 | betaflight RC-1 中“仅由上下文倍数造成”的 SUSPECT 数 | §21.3 反事实（may-target 扇出 > 1） |
| Q-03 | betaflight RC-3 的规模 | 内存内重放统计回退行与继承行 |
| Q-04 | betaflight 中“无复核门槛失败”的 SUSPECT 数 | 结构化原因码（OPT-02） |
| Q-05 | 一致性主桶与双写者的重叠 | 结构化多原因统计 |
| Q-06 | **HR-01 的解释**：HB 有序的初始化写是否允许不计入运行期写者（§9.4 选项 B） | **用户决策** |
| Q-07 | **10% 目标的分母**：建议 RR_build，RR_all 并列展示 | **用户决策** |
| Q-08 | `validation/stm32_concurrency/verify_acceptance.py` 的来源 | 查版本历史 / 询问用户 |
| Q-09 | 寄存器级 DMA 修复（FS-9）对 betaflight 的影响规模 | 阶段 1 回放 |
| Q-10 | blackmagic 9 个 NO_REVIEW 中带原始 ADDRESS_ESCAPE 的 4 个是否落在未解析区间 | 阶段 1 回放 |
| Q-11 | klipper / blackmagic 中 UNKNOWN_ENTRY 函数对审计变量的访问数 | 统计 |
| Q-12 | `atomic=True` 访问标记在直接访问路径上是否存在 | 代码确认（OPT-34 前） |
| Q-13 | 提取器能否记录变量的 `section` 属性（E-10 假设、OPT-46） | 代码确认 |
| Q-14 | Arm 架构手册中单拷贝原子性条文 | 实现 §8.7 前逐条复核 |
| Q-15 | V4 大型 HAL 工程的身份、规模与可用性 | 用户提供 |
| Q-16 | betaflight 在新指标下的统计路径（dump 15 GB 无法载入） | 扩展内存内重建脚本 |
| Q-17 | 此前会话“任务书”（P0-HARD-RISK-01 等）原文不在仓库中 | 用户提供或确认现有引用（`ecra/classify.py:830-831`、`docs/classifier_progress.md:118`）的准确性 |
| Q-18 | **只被审计范围外库代码访问的句柄内部字段**是否需要单独处理（审计范围语义变更） | **用户决策**；默认不做 |
| Q-19 | 当前安装的 libclang Python 绑定是否提供 `get_field_offsetof`、`get_bitfield_width`、`is_anonymous` 等接口 | 环境确认（OPT-15、OPT-21 前） |
| Q-20 | （已确认，保留记录）V0 的初始化顺序与前台写来源 | 本次阅读源码确认：`Cli_Init` 位于 `MX_USART2_UART_Init` 之后、`Cli_Start` 之前；`DebugCliStats` 的前台写只有 `Cli_Init` 中的 `memset`；`Cli_ResetInputState` 另在运行期被 `Cli_Process` 调用（§3.6） |

### 24.2 实施风险

| 编号 | 风险 | 缓解 |
|---|---|---|
| R-1 | HSCP 克隆、Stage B 导致大型工程耗时上升 | 克隆上限、预算、缓存；超限退回保守结果 |
| R-2 | 规则增多带来回归 | 每次只合入一个 OPT；GR / GP / 快照门禁 |
| R-3 | 阶段 1 后 RR 上升引起误解 | 报告中单列“健全性修复引起的上升”及原因 |
| R-4 | libclang 绑定接口缺失 | Q-19 先确认；缺失时用 `clang_Type_getOffsetOf` 等 C API（ctypes，与现有 `constant_value` 同样方式） |
| R-5 | HAL / SPL / libopencm3 版本差异影响 API 语义识别 | 识别器只依赖 API 签名与标准语义；不确定时按 `UNKNOWN_MAY_ENABLE` 等保守处理 |
| R-6 | facts 体积继续膨胀 | 区间查询替代继承复制；见证只引用 ID |
| R-7 | 影子期延长交付 | 影子审计与下一阶段开发并行 |

---

## 附录 A 探针验证记录

环境：本仓库工作区代码（含未提交的 Phase 2 修改）；Python 3.12 + libclang Python 绑定；编译参数 `arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb`；上下文配置只有 `main`（其余由命名约定自动发现）；P7、P28 设置 `nvic_priority_bits: 4`。每个用例在系统临时目录中独立建工程，跑完整的 `prepare → Extractor → merge → analyze`。编号沿用临时脚本，P11、P15、P17、P19、P20 为预留未执行的编号，不作为证据。

| 编号 | 用例要点 | 当前输出 | 修复后期望 | 关联 |
|---|---|---|---|---|
| P1 | union：ISR 写 `u.w`，前台写 `u.h.lo` | `u.h.lo/u.h.hi` SAFE_SINGLE_FOREGROUND；`u.h.lo` 的路径记为 `lo.h` | 三者 SUSPECT（D-05） | FS-1、RC-3；OPT-11/20/21 |
| P2 | ISR：`s.inner.x = 5; p = &s.inner; p->y = 3;` 前台只读 `s.x` | `s.x` SHARED_NO_REVIEW；路径 `x.inner`、`y` | `s.x` SAFE_READ_ONLY | RC-3；OPT-20 |
| P3 | 位域 `f.a/f.b` 只在前台写 | 两者 SUSPECT（位域） | SAFE_SINGLE_FOREGROUND | RC-9；OPT-23 |
| P4 | PRIMASK 窗口内含 `for` 循环 | `cnt` UNRESOLVED → SUSPECT；无循环的 `cnt2` EFFECTIVE | `cnt` EFFECTIVE | RC-4；OPT-30 |
| P5 | 从未分派的函数指针表项 `cb` 调用公共 `log_write`（也被 main 调用） | `shared_log_idx` UNKNOWN_EXECUTION_CONTEXT | OPT-41 条件满足时 SAFE_SINGLE_FOREGROUND | RC-6；OPT-40/41 |
| P6 | ISR 写 value/valid；前台经访问器成对读 | 两成员 SHARED_NO_REVIEW | SUSPECT（D-07） | FS-2；OPT-12 |
| P7 | 同抢占优先级的两个 ISR：一写 value/valid、一成对读 | 两成员 SUSPECT（一致性） | 不因 D-07 SUSPECT | RC-2；OPT-24 |
| P8 | `q_add(&q1)` 在被调函数内完整屏蔽；对照组直接访问全局 | `q1.count` NOT_FOUND → SUSPECT；`q2.count` EFFECTIVE | `q1.count` EFFECTIVE | RC-4；OPT-32 |
| P9 | `nvic_enable_irq(30)` → 写 64 位 `stamp` → `SysTick_Config()`；TIM4 ISR 读 | SAFE_INIT_ONLY_WRITE | 不得 SAFE | FS-3；OPT-13 |
| P10 | ISR 单写 `timeUs_t`、`mode_e`、`unsigned int`；前台读 | 前两者 SUSPECT（宽度不可证），后者 NO_REVIEW | 三者 NO_REVIEW | RC-10；OPT-22 |
| P12 | ISR 写 `c.a/c.b`；前台在 if/else 互斥分支中分别读 | 两成员 SUSPECT（一致性） | 不因 D-07 SUSPECT | RC-2；OPT-24 |
| P13 | `reg(&h1, cb1); reg(&h2, cb2);` USART1/2 ISR 经 `h->cb(h)` 分派 | `d1/d2` 各带两个 UART 上下文 → SUSPECT | 各自单 IRQ | RC-1；OPT-43/44 |
| P14 | 弱回调按 `huart == &huart1/&huart2` 分支 | `rx1/rx2` 各带两个上下文 → SUSPECT | 各自单 IRQ | RC-1；OPT-43 |
| P16 | ISR 写 `arr[i].a`，前台写 `arr[j].b` | `arr` SUSPECT（双写者） | 不因 D-01 SUSPECT | RC-9；OPT-21 |
| P18 | 前台先填 `txbuf` 再 `HAL_UART_Transmit_DMA` | SUSPECT（CPU↔DMA） | 不因 D-03 SUSPECT | RC-8；OPT-52 |
| P21 | 函数内 `g = f();` 及其后独立临界区中的 `k++` | `g`、`k` UNRESOLVED → SUSPECT | EFFECTIVE | RC-4；OPT-30/31/53 |
| P22 | 临界区内调用 `__NOP()`（内联汇编） | `h` UNRESOLVED → SUSPECT | EFFECTIVE | RC-4；OPT-31 |
| P23 | ISR：`asm("" : "=m"(g_op))`、`asm("ldr r1, =g_txt; str r0, [r1]")` | `g_op` SAFE_MULTI_CONTEXT_READ_ONLY；`g_txt` SAFE_READ_ONLY | 不得 SAFE | FS-5；OPT-14 |
| P24 | `SysTick_Config` → 写 `cfg_mode` → `HAL_NVIC_EnableIRQ(USART1)`；USART1 ISR 写 | SUSPECT | （A）保持；（B）SHARED_NO_REVIEW | RC-7；OPT-50 |
| P25 | ISR 单写 `value`；前台 `External_Process(&value)` | SHARED_NO_REVIEW（原因文本称“无地址逃逸”） | UNKNOWN（ADDRESS_ESCAPE） | FS-4；OPT-10 |
| P26 | 按值把 `cfg_word` 传给 `dmaSetHandler` | SHARED_NO_REVIEW（DMA 缺口存在但被忽略） | SHARED_NO_REVIEW（不再产生缺口） | RC-8；OPT-10/18 |
| P27 | packed 结构偏移 1 的 `uint32_t` 单写者 | SHARED_NO_REVIEW | SUSPECT（D-08） | FS-6；OPT-15 |
| P28 | 两个同优先级 ISR 写 64 位 `stamp`，前台读 | SAFE_NON_INTERLEAVING | SUSPECT（D-08） | FS-7；OPT-16 |
| P29 | ISR 中 `strcpy(gp, "x")`，`gp = buf` | UNKNOWN_ADDRESS_ESCAPE | ISR 写被建模；不得 SAFE | FS-10；OPT-19 |
| P30 | 未知入口 `cb` 读 64 位 `stamp`，前台写 | SAFE_SINGLE_FOREGROUND | OPT-17 后 UNKNOWN；OPT-41 证明 `cb` 无任何可能调用者后可为 SAFE；回调地址交给无源码注册函数的变体必须保持 UNKNOWN | FS-8；OPT-17/41 |
| P31 | `DMA2_Stream2->M0AR = (uint32_t)rxbuf` 寄存器级配置；前台读 | SAFE_READ_ONLY | 不得 SAFE（D-03 或 UNKNOWN_DMA_LIFETIME） | FS-9；OPT-18 |
| P32 | 环形缓冲结构：ISR 写 `r.buf[...]`、`r.head`，前台写 `r.tail` | 三成员 SUSPECT；`r.tail` 的双写者来自回退继承写；路径 `[].buf` | `r.tail` 不再是双写者；一致性按 v2 判断 | RC-3；OPT-20/24 |
| P33 | ISR：`h->Instance->CR1 \|= 0x20`；前台初始化 `huart2.Instance` | `huart2.Instance` SUSPECT（ISR 侧 RMW 记在 `Instance` 上） | `Instance` 在 ISR 中只有 READ；写记在 `fake_usart.CR1` | M-40；OPT-20 |

基准 dump 统计（§3.3 中【基准】数据）使用的临时脚本只读取 `facts-final-klipper.json`、`facts-final-blackmagic.json`；§3.6 的 HAL 工程重放只读取该工程源码与编译数据库。上述脚本未进入仓库，OPT-02 会把同类统计产品化。

## 附录 B 代码位置索引

| 模块 | 位置 | 内容 | 相关 OPT |
|---|---|---|---|
| `ecra/classify.py` | 30-47 | `context_domains` | 48 |
| | 98-136 | `ENTRY_UNCERTAIN_KINDS`、`SYMBOL_UNKNOWN_CODES`、`ASYNC_ENABLE_APIS` | 13、40 |
| | 189-212 | 域对关系聚合与可交错判断 | 48、51 |
| | 231-263 | 未解析调用区间 | 19、45 |
| | 296-353 | 指针 / 取址逃逸（315：LIBC 名称比较） | 19、45 |
| | 357-389 | 入口不确定性前向传播 | 40、41 |
| | 402-440 | 死函数证明（424-427：不透明代码使外部函数全为根） | 47 |
| | 444-462 | 汇编符号引用（449：条件写反） | 14 |
| | 482-707 | main 初始化写证明与传递式相位模型 | 13、50 |
| | 712-738 | 宽度判定 | 22 |
| | 740-935 | 四类裁决（792：POINTS_TO_LIMIT；806-813：未知写者；855：位域；857：一致性；887-924：NO_REVIEW） | 10、16、17、23、24、40 |
| | 937-963 | `_safe_rule`（962-963：NON_INTERLEAVING） | 16 |
| `ecra/analysis.py` | 63-265 | `context_graph`（106-125：命名约定；175-186：BFS 传播） | 40、43、46、48 |
| | 298-416 | 成员资源化（377-391：回退与继承；413-414：ID 重编号） | 03、11、20、21 |
| | 706-739 | const 写剔除 | — |
| | 838-870 | 多字段一致性 | 12、24 |
| | 903-1055 | 逐变量分类循环 | 60 |
| | 1139-1167 | 分类质量统计（1155：review_rate） | 01 |
| `ecra/extract.py` | 201-231 | `record_members`（220：类型对齐） | 15、21 |
| | 266-330 | `access_mode`（279-288、330：路径拼接） | 20 |
| | 397-421、515-533 | 局部别名 | 20 |
| | 461-468 | 优先级事件 | 51 |
| | 469-499 | 库函数语义与 DMA 名称启发 | 18、19 |
| | 540-543 | INLINE_ASSEMBLY 事实 | 14 |
| `ecra/pointer_extract.py` | 47-49 | 数组下标合并 | 44 |
| | 52-77 | 值表达式（整数常量 → empty） | 18 |
| | 83-126 | 初始化器与 designator | 44 |
| | 128-145 | `mode()`（M-40） | 20 |
| | 179-193 | 原子访问 | 34 |
| `ecra/points_to.py` | 93-162 | 求解主流程（105-117：迭代；140-145：间接边；148-152：旧库语义表） | 19、42、44、45 |
| | 245-281 | 对象敏感归属（277：改挂调用者） | 32、43 |
| | 300-340 | 注册入口 | 43 |
| | 342-369 | HAL DMA 契约（360：共用上下文 ID） | 18、52 |
| `ecra/controlflow.py` | 58-67 | 无序表达式 | 30、31 |
| | 153-160、169 | 不支持语句与 `complete` | 30 |
| `ecra/protection.py` | 23-225 | `MaskAnalysis`（102-111：被调函数；124-135：不完整 CFG） | 31、32 |
| | 243-315 | `assess`（276：只看 MAIN；292-293：participants） | 33 |
| `ecra/interrupts.py` | 15-80 | 优先级模型 | 51 |
| | 94-125 | 关系矩阵 | 48 |
| | 128-152 | BASEPRI 阈值 | 33、51 |
| `ecra/report.py` | 31-88 | 根因与质量报告（37-62：口径） | 01、02 |
| `ecra/cli.py` | 197-201 | 补充盘点 | 01 |
| `ecra/common.py` | 88-107 | 标准库参数语义表 | 19 |
| `ecra/workflow.py` | 24-26 | 引擎摘要 | 全部 |

## 附录 C 需求覆盖矩阵

| 需求 | 内容 | 章节 |
|---|---|---|
| 1 | 当前完整分类流程和数据流 | §2 |
| 2 | “疑似 / 无法判断”比例过高的 Top 根因 | §3.2、§3.3、§3.6 |
| 3 | 每个根因对应的代码模块、函数、数据结构 | §3.3 各 RC、§3.4、§3.7、附录 B |
| 4 | 过度保守、误传播、误判的具体机制 | §3.4（M-01…M-40）、§3.5 |
| 5 | SAFE / 无需复核 / SUSPECT / UNKNOWN 严格定义 | §4 |
| 6 | 可安全自动排除的变量及证明条件 | §5.1 |
| 7 | 必须始终保留的明显风险 | §5.2、§18.3 |
| 8 | Variable-local UNKNOWN | §6 |
| 9 | FOREGROUND / ISR / DMA 等物理执行上下文建模 | §7 |
| 10 | Single Writer + Reader 精确降噪 | §8 |
| 11 | Init / Runtime 阶段分析 | §9 |
| 12 | Alias / Pointer / Function Pointer / Mod-Ref / NoEscape | §10 |
| 13 | HAL Callback / Handle 对象敏感上下文传播 | §11 |
| 14 | MHP / NVIC 优先级 / PRIMASK / BASEPRI / 临界区 | §12 |
| 15 | 字段、数组、whole-object、位域、union 存储重叠 | §13 |
| 16 | 一致性 / 旧快照 / RMW / 多 Writer 守门 | §14 |
| 17 | 两阶段静态分析 | §15 |
| 18 | 减少 S/U 同时 false-safe ≈ 0 | §16 |
| 19 | 新增或调整的数据结构、模块、算法 | §17 |
| 20 | 单元测试、黄金风险样例、回归测试 | §18 |
| 21 | 至少 3 个大型真实 STM32 裸机项目的验证规划 | §19 |
| 22 | 优化前后指标与 Benchmark 方法 | §20 |
| 23 | Review Rate > 10% 时的根因定位 | §21 |
| 24 | 最终验收标准、失败条件、不可接受的实现方式 | §23 |
| 附加 | 每个优化点的“为什么 / 现状问题 / 方案 / 验证” | §6–§15 各 OPT |
| 附加 | 优先级、实施阶段、P0 强制项 | §22 |
| 附加 | 禁止特例、禁止牺牲检出、保护机制不遗漏 | §1.5、§5.2、§16、§23.3 |
| 附加 | 信息不足处标注“需进一步确认” | 全文【需进一步确认】标注、§24 |

