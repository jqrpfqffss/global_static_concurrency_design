# 分类器优化进度日志（classifier_progress）

本文件按 Phase 记录每阶段的目标、修改、测试与基准变化。基线（修改前）=
commit `3fb7ef7`（分类优化四）在 2026-10-07 用三工程缓存提取 parts 重放确认，
数字与 `docs/pre_opencode_classification_benchmark.md` 当前表一致。

## Phase 0 —— 当前版本基线统计

**目标**：在不修改任何代码的前提下，对当前实现重放三工程基准，固定"修改前"数字。

**修改文件**：无（只读统计）。

**基准结果（2026-10-07 重放，HEAD=3fb7ef7）**：

| 工程 | TOTAL | SAFE_PROVEN | SHARED_NO_REVIEW | SUSPECT | UNKNOWN | OpenCode 队列 | Review Rate |
|---|---|---|---|---|---|---|---|
| klipper | 889 | 841 | 0 | 38 | 10 | 48 | **5.4%** |
| blackmagic | 691 | 493 | 9 | 121 | 68 | 189 | **27.4%** |
| betaflight | 7630 | 5041 | 68 | 2380 | 141 | 2521 | **33.0%** |

（TOTAL 口径：编译变量扣除定义不在构建闭包内的依赖声明——klipper 12、
blackmagic 25、betaflight 306。）

**测试结果**：`python -m unittest discover -s tests -q` 全量回归 = 通过（除已知
遗留损坏 test_acceptance 引用缺失的 verify_acceptance.py，先于本轮存在）。

**剩余问题**：klipper 已达标；blackmagic / betaflight 远超 10% 目标，
根因统计见 Phase 1。

## Phase 1 —— SUSPECT / UNKNOWN 根因报告

**目标**：对三工程全部 SUSPECT/UNKNOWN 变量按任务书 taxonomy 逐变量归因
（每变量一个主根因，桶和 = S+U），输出
`docs/classification_root_causes_before.md`。

**方法**：`D:/ecra-bench/baseline_roots.py`（klipper/blackmagic 用当日重放
dump，betaflight 内存内重建后统计；典型变量附源码摘录）。

**主根因分布（变量数，占 S+U %）**：

| 桶 | klipper | blackmagic | betaflight |
|---|---|---|---|
| SUSPECT:MULTI_FIELD_COHERENCY | 16 (33%) | 93 (49%) | 1528 (61%) |
| SUSPECT:DMA_CONFLICT | 0 | 0 | 531 (21%) |
| SUSPECT:MULTI_WRITER | 22 (46%) | 28 (15%) | 301 (12%) |
| SUSPECT:WHOLE_OBJECT_ACCESS | 0 | 0 | 18 (0.7%) |
| SUSPECT:STALE_SNAPSHOT / BITFIELD | 0 | 0 | 1 + 1 |
| UNKNOWN:UNKNOWN_CONTEXT | 6 (12.5%) | 47 (25%) | 56 (2.2%) |
| UNKNOWN:ADDRESS_ESCAPE | 4 (8%) | 20 (11%) | 78 (3.1%) |
| UNKNOWN:DMA_LIFETIME | 0 | 1 | 7 |

次要标记（一变量可带多个）：betaflight 2334 个候选带"抢占优先级未证明"、
1829 带"保护待确认"；blackmagic 60 带 RMW。

**已实证的通用精度缺口（根因抽查逐条验证，均可通用修复，无项目特例）**：

1. **const 对象幻影写（blackmagic 28 个、betaflight 待量化）**：
   `memcpy(buf, cfg, …)` 中 `uint8_t **buf` 的指向集在互斥 switch 分支间
   流不敏感并集（`*buf = (uint8_t*)usbd_dev->desc` 与 `*buf = usbd_dev->ctrl_buf`），
   把写目标并入了 const 描述符（dev_desc 等）。Cortex-M 上 const 静态存储
   位于 flash（.rodata），运行期写物理上不可能成功（写入即 bus fault）。
   → 对 const 非 volatile 对象的 WRITE/RMW 是不可达访问；其地址流入不透明
   代码也不构成"可写逃逸"。
2. **libc 语义未建模 → 假逃逸（blackmagic 13/20 个 ADDRESS_ESCAPE）**：
   地址传给 memcpy/strcmp/strncasecmp 等标准库函数（闭包内无定义）被判
   "流入未解析函数"。但提取器本身已有 memcpy 参数语义表（arg0 WRITE、
   arg1 READ）——语义已知就不是不透明代码；strcmp/strncasecmp/snprintf
   等只读参数更不可能产生写逃逸。
3. **数组元素读被误记为 ADDRESS_TAKEN（blackmagic gdb_reg_*_strings 等）**：
   `f(tbl[i])` 中基址 decay 已被下标消费，但外层包装（vararg 隐式转换，
   类型为元素指针）再次把 decay 置位 → 元素读翻成 ADDRESS_TAKEN → 传给
   不透明函数 → 假 UNKNOWN_ADDRESS_ESCAPE。
4. **两级回调链未收敛（blackmagic 47 个 UNKNOWN_CONTEXT 的主因）**：
   `t->tc->destroy_callback(...)`：堆对象 target_s 的 tc 字段 → 静态
   const target_controller_s 表 → 函数指针。流不敏感 points-to 在
   堆对象字段处断链，分发调用点保持 INDIRECT 未解析 → 表内回调函数
   （gdb_target_destroy_callback、remote_packet_process_swd、jtagtap_init…）
   成为入口不确定种子，其写入全部 UNKNOWN。
5. **Init/Runtime 混合写者被 G5 一刀切（blackmagic st_usbfs_dev 等）**：
   G5 规定 PRE 写者不得与任何运行期写者组合降噪。但 Cortex-M 复位时
   NVIC 全部禁用、使能事件可传递证明在 PRE 写之后；不可屏蔽异常
   （NMI/HardFault）才是真正需要 G5 保守的场景。可屏蔽 ISR 的运行期写者
   不应阻止 init 写者归入有序序列。
6. **真实风险桶（诚实保留，不得强行降噪）**：klipper 的 wake flag
   MAIN↔IRQ 双写、move_free_list 主循环/步进 ISR 双管理；betaflight 的
   飞控 ISR↔任务共享、USB VCP 环形缓冲；多字段撕裂协议（value+valid、
   head/tail）等。这些是工程真实设计中的破坏性模式。

**结论**：>50%（对 blackmagic/betaflight 而言 >25%/33%）的来源既有
分类器可证明修复的精度缺口（1–5，全部通用），也有工程真实风险密度（6）。
Phase 2 起按 1→5 顺序实施通用修复，每步重跑基准记录候选下降量。

## Phase 2 —— 通用精度修复（const 幻影写 / libc 语义 / 元素读误判）

**修改文件**：ecra/common.py（新增 LIBC_ARG_SEMANTICS 共享表）、
ecra/extract.py、ecra/classify.py、ecra/analysis.py。

1. **const 不可运行期写（C11 §6.7.3 UB + Cortex-M flash 事实）**：
   points-to 流不敏感指向集并集给 const 对象制造的幻影 WRITE/RMW 访问行
   在 access 聚合前剔除；const 对象的地址逃逸不再产生
   UNKNOWN_ADDRESS_ESCAPE 缺口（不可写对象无写逃逸路径）。
   诊断计数入 `coverage.classification_quality.impossible_const_writes`。
2. **定长标准 C 库语义表**（memcpy/memmove/memset/memcmp/strcpy/…/
   strncasecmp/strchr/strstr 共 16 个）：参数方向由 C 标准确定——
   提取器按方向记访问；这些函数的调用点不再是"不透明代码"；
   地址流入其 READ 参数不再构成写逃逸。可变参数（printf 家族，%n 危险）
   保守不入表。
3. **数组元素读误判修复**：`f(tbl[i])` 中基址 decay 被下标消费后，
   外层 vararg 隐式转换包装不再把元素读翻成 ADDRESS_TAKEN。

**测试结果**：全量 267 测试通过（唯一 error 为先于本轮存在的
test_acceptance 加载错误）。

### G5 豁免尝试（已回滚，记录教训）

曾实现"PRE 写者 + 可屏蔽 ISR 运行期写者 + 无 DMA 参与 ⇒ PRE 写不参与
冲突枚举"。**7 个 PRIMASK/守门测试失败**（T13、G5、D08 等）证明该方向
违反任务书 P0-HARD-RISK-01 的字面硬守门（MAIN WRITE + ISR WRITE ⇒
SUSPECT，"任何优化都不能绕过"），且 SHARED_NO_REVIEW 的门槛
（NR-01/NR-02）要求"其它 Context 只有 READ"。已完整回滚。结论：
blackmagic `st_usbfs_dev.*` 等 init 写者 + ISR 运行期写者组合按规范
保持 SUSPECT，属诚实保留，不是精度缺口。

### 新发现：betaflight 上下文归属污染（Phase 2c，进行中）

探针实证：前台 4way 协议函数 `esc4wayProcess` 的访问行被挂上
**全部 ~45 个自动 ISR 上下文**（含 TIM8、ADC、全部 DMA stream、EXTI…），
其唯一赋值点为 `*mspPostProcessFn = esc4wayProcess`（msp.c:325，前台
MSP 路径）。上下文集爆炸使多字段一致性守门（需要 reader_domain !=
writer_domain）在纯前台配置数据（rateProfile、devInstance、
beeperConfig_System…147 个 root、1528 个成员）上大量误触发。
这是 betaflight 60.6% 队列的最大单根因，正在溯源修复。

## Phase 3 —— 规划阶段 0：度量口径、结构化原因码与证据 ID（OPT-1A/01/02/03）

**依据**：`docs/pre_opencode_precision_optimization_plan.md` §22.2 阶段 0（只改度量，
不改分类）+ §18.7。

**修改文件**：ecra/analysis.py、ecra/classify.py、ecra/report.py、ecra/common.py（无）、
ecra/workflow.py、ecra/diagnostics.py（新增）、validation/stm32_concurrency/
verify_acceptance.py（恢复）、tests/test_phase0_metrics.py（新增）。

1. **OPT-1A**：`tests/test_acceptance.py` 引用的
   `validation/stm32_concurrency/verify_acceptance.py` 从未进入本仓库版本历史；
   在同工程副本 `H:/global_static_concurrency_design`（doctor.json 记录的旧副本）中
   找到该文件（208 行，仅标准库依赖，含测试所需的 identify/chain_matches），
   原样恢复。遗留 error 消除，无需删除测试。**顺带解开 Q-08**：该文件从未
   进入版本历史的原因是 `.gitignore` 整目录排除 `validation/`（36 行）；由于
   tests/test_acceptance.py 直接依赖该源文件，用 `git add -f` 单独纳入
   （仅此一个源文件，validation/ 其余产物仍被忽略），保证任何检出全绿。
2. **OPT-01 指标口径**：`coverage.static_classification_build` 新增编译变量口径
   （TOTAL_BUILD / RR_build）与全盘点口径（RR_all = (S+U+VARIANT_INVENTORY)/
   (TOTAL_BUILD+VARIANT_INVENTORY)）并列；补充盘点声明单列 variant_inventory，
   不再与编译变量混在同一分母。`classification_quality.review_rate`（历史键）
   确认与 rr_all 同口径保留。`report.write_classification_diagnostics` 的
   分子分母口径统一为编译变量。
3. **OPT-02 结构化原因码**：classify() 的 SUSPECT/SAFE(EFFECTIVE) 结果新增
   `destructive_codes`（D-01 双写 / D-02 可重入 / D-03 DMA / D-04 位域 /
   D-05 union / D-07 一致性 / D-08 撕裂 / D-11 所有权）与 `witnesses`（域对 +
   代表访问的稳定 evidence id）；单写者门槛新增 `gate_results`（NR-03 失败码
   NR-03_WIDTH_EXCEEDS_WORD / NR-03_ALIGNMENT_MISSING / NR-03_ALIGNMENT_INSUFFICIENT）。
   analysis.py 的 GS-* 展示规则与 report.py 的根因统计改为按结构化码，不再对
   reason 文本做字符串匹配——根因桶中"DMA"只包含真实硬件 DMA 域（kind=DMA）
   产生的 D-03，修复了按上下文名含 DMA 归桶的统计误判（规划 §3.1）。
   新增 `ecra/diagnostics.py`：root_cause_v2.json（多原因并列 + 最小充分原因 +
   热点聚类 + RC-3 回退继承写反事实上界）。
4. **OPT-03 证据 ID 稳定化**：access_id 改为内容稳定（生成后不再改变）；
   `canonicalize_member_resources` 废除全表重编号（旧实现先记录
   inherited_from_access_id、后按全表下标重编号，继承行证据链必然断裂）。
   继承行的 inherited_from_access_id 现在长期可追溯（tests 验证）。

**测试**：新增 tests/test_phase0_metrics.py 6 项（口径拆分、结构化码与见证、
门槛结果、root_cause_v2.json、继承链可追溯）；全量 `discover -s tests` 274 项通过。

**基准变化（klipper 重放 vs Phase 2 基线）**：889 变量、SAFE 841、SUSPECT 38、
UNKNOWN 10、队列 48 —— **逐项一致，零分类漂移**（符合"阶段 0 只改度量"）。
blackmagic 回放在 OPT-10 改动落盘后启动（4 个带地址逃逸的 NO_REVIEW → UNKNOWN，
即规划 Q-10 预测的 4 个变量），队列 145→149；该数字并入 Phase 4 基线对照。

## Phase 4 —— 规划阶段 1：健全性修复（FS-1…FS-8、FS-10）+ GR 黄金样例

**依据**：规划 §22.2 阶段 1；§4.6 裁决顺序；§5.2/§18.3 硬守门。方向承诺：
健全性修复可能使 S/U 上升，以下如实记录，不以精度收益抵消披露。

**修改文件**：ecra/classify.py、ecra/analysis.py、ecra/extract.py、ecra/points_to.py、
ecra/common.py、tests/test_phase1_soundness.py（新增，27 项）、
tests/test_serial_regressions.py（1 处断言按新设计语义更新）。

1. **OPT-10（FS-4）**：相关缺口检查移到单写者 SHARED_NO_REVIEW 分支之前
   （§4.6 顺序）；地址逃逸的单写者不再 NO_REVIEW（P25 → UNKNOWN）。
2. **OPT-11（FS-1）**：提取器记录每个成员所属 union 层的 (union 路径, section
   路径) 与 is_union；分析期对同 union 不同 section 的成员生成 OVERLAP_ACCESS
   副本行（同 section 内兄弟叶子不复制，避免嵌套 struct 假重叠）；union 重叠
   写标注 D-05。GR-12：u.w / u.h.lo / u.h.hi 全部 SUSPECT。
3. **OPT-12（FS-2）**：提取器记录 return 语句直接读取的成员（returned_members
   新事实表）；分析期把访问器函数每个调用者按这些成员计入一致性读组（一层）。
   GR-09b：value+valid 经访问器成对读 → SUSPECT（D-07）。
4. **OPT-13（FS-3）**：fail-closed 使能事件——无定义外部函数调用、未解析间接
   调用、内联汇编均视为 UNKNOWN_MAY_ENABLE，阻断其后的 PRE 证明（is_pre_write
   与 init_only_write_proof 同步收紧）；已识别使能 API 与定长 libc 不受影响。
   GR-15：libopencm3 式 `nvic_enable_irq(30)` 之后的写不再 SAFE_INIT_ONLY_WRITE。
   （NVIC->ISER 直接寄存器写变体需 OPT-18 的 mmio 位置，见下"遗留"。）
5. **OPT-14（FS-5）**：GCC 扩展汇编操作数约束从 token 流恢复（'='→WRITE、
   '+'→RMW、输入→READ），操作数方向覆盖默认 READ；汇编文本符号扫描条件
   修复（旧条件 `opaque_code is False` 写反，扫描从未执行）；操作数语义已
   恢复的变量不再按文本重报（modeled_operand_sids）。GR-14：`"=m"(g_op)`
   成为 ISR 写；文本间接写 → UNKNOWN_INLINE_ASM。
6. **OPT-15（FS-6）**：提取器记录成员根相对 bit_offset（get_field_offsetof，
   Q-19 确认绑定可用）；有效对齐 = min(类型对齐, 偏移整除性, 根对象对齐)，
   成员资源携带 effective_alignment_bytes；单写者门槛与写者组撕裂检查改用
   有效对齐。GR-13（P27）：packed 偏移 1 的 uint32_t → SUSPECT（D-08）。
   test_serial_regressions 中 packed 成员旧断言（SHARED_NO_REVIEW）按规划
   FS-6 的新语义更新为 SUSPECT（规划 §18.1 允许：附设计依据的断言调整）。
7. **OPT-16（FS-7）**：多写者域两两 SERIAL 时构造"写者组"，组与可交错读者域
   之间套用 NR-03：失败 → SUSPECT（D-08），通过 → SHARED_NO_REVIEW
   （writer_group_serial 证据）；全部域对不可交错才保持 SAFE_NON_INTERLEAVING。
   GR-11b（P28）：同优先级双 ISR 写 64 位 + 前台读 → SUSPECT。
8. **OPT-17（FS-8）**：未知上下文的读在"变量有写者且非原子"或"一致性候选组"
   时成为 UNKNOWN_EXECUTION_CONTEXT 相关缺口；原子宽度且无一致性时结论从
   SAFE_SINGLE_* 改为 SHARED_NO_REVIEW（证据注明 unknown_context_readers）。
   GR-26：未知入口读 64 位 → UNKNOWN；读 32 位 → NO_REVIEW；回调地址交给
   无源码注册函数 → UNKNOWN。
9. **OPT-19（FS-10）**：points_to 弃用旧 4 函数表，与提取器共用
   ecra.common.LIBC_ARG_SEMANTICS（16 函数参数方向）；逃逸豁免按"被调函数名"
   归一（libc_function_name，USR c:@F@strcpy 与裸名统一），修名同时补齐
   points-to 语义（禁 X-14）。GR-27：ISR 中 strcpy(gp,"x") 建模为 ISR 写、
   无假逃逸；strcmp 只读实参不产生逃逸。

**测试**：tests/test_phase1_soundness.py 27 项（GR-09b/11b/12/14/15/16/26/27
正反例）；全量 301 项通过。注：宏 `#define TIM2_IRQn 0` 做 IRQn 实参时
detailed processing record 会污染参数 token 串（真实工程用 CMSIS 枚举不受
影响），GR-11b 用例改用 enum。

**基准变化（重提取 + 重放，2026-10-07）**：

| 工程 | TOTAL_BUILD | SAFE | NO_REVIEW | SUSPECT | UNKNOWN | 队列 | RR_build | 变化 |
|---|---|---|---|---|---|---|---|---|
| klipper | 889 | 843 | 0 | 38 | 8 | 46 | **5.2%** | −2（UNKNOWN_ADDRESS_ESCAPE 4→2，libc 假逃逸消除） |
| blackmagic | 691 | 540 | 10 | 93 | 48 | 141 | **20.4%** | −8（UNKNOWN_ADDRESS_ESCAPE 10→1 假逃逸消除；NO_REVIEW 5→10 为豁免后如实通过 NR 门槛；SUSPECT 93 不变） |
| betaflight | 7630 | （重提取 + 内存内回放进行中，见 Phase 4 续记） | | | | | | |

**审计结论**：S/U → SAFE/NR 的翻转全部来自 libc 语义统一（假逃逸消除，规划
RC-11/M-38 的预期收益），无放宽检测器；SUSPECT 集合在两工程上逐项不变。
OPT-18（mmio/寄存器级 DMA，FS-9/GR-24）未在本轮实施，属阶段 1 遗留，随后
单独实施并回放。
