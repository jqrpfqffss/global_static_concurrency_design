# Pre-OpenCode 静态分类基准报告

本文档记录“OpenCode 之前先使用确定性静态分析完成大规模筛选”目标的实现、验证与边界。
三个真实开源 STM32 工程使用同一套分类器（无任何项目名/变量名/路径特例）验证。

## 0. 四类分类与第二轮降噪（当前版本）

在第一轮（SAFE/SUSPECT/UNKNOWN 三类）基础上，分类输出改为四类并完成系统性降噪：

| 类别 | 中文 | 进入 OpenCode |
|---|---|---|
| SAFE_PROVEN | 静态已判安全 | 否 |
| SHARED_NO_REVIEW | 共享访问，无需复核 | 否 |
| SUSPECT | 疑似并发风险 | 是 |
| UNKNOWN | 无法判断 | 是 |

SHARED_NO_REVIEW 的严格门槛（全部满足才允许）：唯一写者物理域 + 其余域只读 +
写者域无独立读站点限制放宽为"唯一写者域内先读后写无丢失更新（守门 G3 的双写者
stale snapshot 模式仍由 MULTI_WRITER 拦截）"+ 可证明单指令原子宽度与对齐 +
无 DMA / 地址逃逸 / 未知写者 / 多字段一致性 / 位域 / 结构体整体。

破坏性冲突保持 SUSPECT（即使优先级/保护未解析）：双写 / RMW 交叉 / CPU↔DMA
至少一方写 / 位域并发写 / 多字段一致性（同 root 多字段被一个域修改、另一域
在同一函数内成对读取）/ 可重入写者。

前台入口修正：libopencm3 的 `reset_handler`（整个引导链 = 前台串行域）此前被
`*_handler` 小写约定误判为 ISR，制造大量虚假跨域冲突；`__disable_irq` 等
编译器内建同理排除。修正后 reset 链正确并入 FOREGROUND。

| 工程（四类，修复后提取输入） | TOTAL | SAFE_PROVEN | SHARED_NO_REVIEW | SUSPECT | UNKNOWN | OpenCode 队列 |
|---|---|---|---|---|---|---|
| klipper | 901 | 841 (93.3%) | 1 | 37 (4.1%) | 22 (2.4%) | **59 (6.5%)** |
| blackmagic | 716 | 498 (69.6%) | 9 | 121 (16.9%) | 88 (12.3%) | **209 (29.2%)** |
| betaflight | 7936 | 4630 (58.3%) | 180 | 2693 (33.9%) | 433 (5.5%) | **3126 (39.4%)** |

真实风险密度说明（按用户规则如实保留，不强行达标）：

- klipper 达到 ≤10% 目标。
- blackmagic 剩余 29%：93 个多字段一致性（USB 协议结构 `_mass_storage`、
  `st_usbfs_dev`、`dev_desc`——同 root 多字段被 USB IRQ 修改、主循环成对读取，
  value+valid 撕裂模式真实存在）+ 28 个双写者 + 88 UNKNOWN（其中 51 个是
  `hostio_unlink` 等结构体存储回调的执行上下文无法恢复——points-to 对
  `t->tc->unlink` 两级堆指针链未收敛，其写者上下文诚实保留为未知）。
- betaflight 剩余 39%：飞行栈的 ISR↔任务共享是设计核心（陀螺仪 EXTI→PID 任务、
  USB VCP 双指针环形缓冲、串口 DMA 缓冲），2264 个双写者 + 318 个 CPU↔DMA
  写重叠 + 一致性对为真实破坏性模式。

## 1. 修改前的问题

大型裸机工程迁移后，绝大多数变量落入“无法判断”：

| 工程（旧引擎） | 编译变量 | SAFE | SUSPECT | UNKNOWN | OpenCode 队列 |
|---|---|---|---|---|---|
| klipper | 901 | 518 (57.5%) | 0 | 383 (42.5%) | 383 |
| blackmagic | 716 | 51 (7.1%) | 0 | 665 (92.9%) | 665 |
| betaflight | 7936 | — | — | — | 未能完成（超时） |

## 2. UNKNOWN 过度扩散根因

对旧引擎逐项复核，确认了任务书指出的“工程级全局 blocker”错误模型，共六类：

1. **per-access 全量扫描与平方级域对枚举**（性能，非分类）：`_domain_relations`
   逐对枚举全部物理域（betaflight 2028 个上下文 → 205 万域对，单独耗时 321 秒）；
   per-access 循环对全量 calls/unknowns 做线性过滤（3 万访问 × 14.6 万 unknowns ≈ 44 亿次
   迭代）；`variable_relations` 每变量重新过滤全量抢占关系矩阵（205 万行 × 每变量）。
   三者叠加使 betaflight 分析超过 3600 秒超时，旧引擎同样无法完成。
2. **不透明代码按“存在性”污染**：工程任何位置存在未解析间接调用 / 外部被调函数 /
   内联汇编（`opaque_code`），即把“存入外部链接对象的地址”全部视为逃逸。betaflight
   有 648 个未解析间接调用，导致所有存入外部全局的函数地址全部进入
   `fn_address_escape`，前向传播淹没调用子树（blackmagic 1244 个函数入口不确定）。
3. **提取器把驱动层诊断当作解析失败**：clang 对 `-fuse-linker-plugin`、
   `-Wunsafe-loop-optimizations` 等命令行选项发出（无源码位置的）error 级诊断，
   且工程 `-Werror` 会把带 `[-W...]` 类别的警告提升为 error。旧判定“任一
   severity>=3 即 FAILED”使 betaflight **497 个编译单元全部标记解析失败**，
   全部变量背上 PARSE_FAILED 缺口 → 0 个 SAFE。
4. **已解析的间接调用点仍被当作不透明区间**：调用点被指针求解恢复为具体目标后，
   原始 INDIRECT 调用行仍参与“未解析调用区间”计算，落在区间内的取地址表达式
   被误判为地址逃逸。
5. **裸机前台入口识别不完整**：无 `main` 函数的工程（reset handler 直接进入调度器）
   前台无上下文根，整个前台调用树入口不确定；小写 `*_handler`（libopencm3 向量表
   惯例）不被自动 ISR 规则覆盖。
6. **内联汇编操作数中的函数地址丢失调用边**：`asm volatile("bx %0" :: "r"(next))`
   形式的尾跳转（reset 链）没有 C 调用边，引导链之后的整个前台断链。
7. **数组下标 designated initializer 提取为空**：`[TASK_X] = DEFINE_TASK(..., func, ...)`
   形态在 AST 中呈现为 UNEXPOSED_EXPR（下标 + 值）包装，`unwrap` 不剥（多个表达式
   子节点）、`value()` 返回 empty——整个任务表的函数指针丢失（betaflight 1486 个
   变量因此 UNKNOWN_EXECUTION_CONTEXT）。

## 3. 新分类算法

分类最高层公式保持任务书要求（`ecra/classify.py`）：

```
已知冲突候选（同一存储对象 + 至少一方 WRITE/RMW + 不同物理执行域或可重入
               + 可能交错 + 未被已证明有效的保护阻断）
    => SUSPECT（即使抢占优先级或保护细节尚未恢复）

无已知冲突 + 该变量证据切片内存在可能隐藏冲突的关键缺口
    => UNKNOWN（精准 reason code，禁止宽泛兜底）

无已知冲突 + 变量相关证据足够证明不存在其它冲突
    => SAFE（必须携带 safe_reason_code + safe_evidence）
```

物理执行上下文模型（FOREGROUND / IRQ:<vector> / DMA / EXTERNAL_ASYNC）与
变量证据切片（Variable Evidence Slice）维持任务书语义；本次在其上修正：

- **逃逸判定变量本地化**：地址存入外部链接对象只在**构建闭包不完整**
  （缺失编译单元 / 解析失败 / 未展开汇编）时构成逃逸证据；闭包完整时，
  地址必须实际流入不透明代码（未定义函数参数、未解析间接调用、汇编名引用）
  才算逃逸。地址已逃逸（或被汇编按名引用）的对象中存放的函数指针单独传播。
- **已解析调用点不再是不透明代码**：被指针求解恢复目标的间接调用，其参数中
  的地址只流向已知被调函数。
- **ASSEMBLY 调用边**：函数地址作为内联汇编操作数（语句区间由 extent 提供）
  恢复为可达边，上下文沿汇编尾调用传播；方向保守（只增加可达上下文），
  同一地址若另流入真正的异步代码，仍由间接解析 / 逃逸机制独立标记。
- **前台入口惯例**：`main`、`ResetHandler`、`Reset_Handler`（ARM 裸机 reset 链）
  为 MAIN 根；`*_IRQHandler`/`SysTick_Handler` 等维持原规则，新增全小写
  `*_handler`（libopencm3 向量表惯例）。
- **classification 与 coverage 分离**：SUSPECT + PARTIAL coverage 合法；
  已知冲突不因优先级/保护未解析降级为 UNKNOWN。

### SAFE 证明规则（safe_reason_code）

`SAFE_NO_RUNTIME_ACCESS` / `SAFE_READ_ONLY` / `SAFE_MULTI_CONTEXT_READ_ONLY` /
`SAFE_SINGLE_FOREGROUND` / `SAFE_SINGLE_IRQ` / `SAFE_SINGLE_CONTEXT` /
`SAFE_NON_INTERLEAVING` / `SAFE_EFFECTIVE_PROTECTION` / `SAFE_INIT_ONLY_WRITE`。
禁止 volatile、位宽、单写者、“没发现问题”等作为 SAFE 依据；每个 SAFE 附
safe_evidence（证明代码、访问 ID、上下文、保护状态、覆盖状态）。

### UNKNOWN 精准 reason code

`UNKNOWN_ADDRESS_ESCAPE` / `UNKNOWN_RELEVANT_ALIAS` / `UNKNOWN_RELEVANT_INDIRECT_CALL` /
`UNKNOWN_RELEVANT_MISSING_TU` / `UNKNOWN_EXECUTION_CONTEXT` / `UNKNOWN_DMA_LIFETIME` /
`UNKNOWN_INLINE_ASM` / `UNKNOWN_SCAN_INVALID` / `UNKNOWN_UNMODELED_CONCURRENCY` /
`ACCESS_NOT_ANALYZED`（补充盘点）。禁止宽泛兜底；`blocker_fanout` 报告
（`analysis.max_unknown_fanout_debug`）标记疑似过度传播。

### 性能（大工程可用性前提）

| 阶段 | 修复前 | 修复后 |
|---|---|---|
| `_domain_relations` 域对聚合 | 321 s（205 万域对逐对枚举） | <1 s（仅聚合存在证据的域对） |
| per-access 边证据 | >20 min（每访问全量扫描） | ~5 min（按函数缓存 + 索引） |
| per-variable 抢占关系 | >60 min（每变量过滤 205 万行） | ~2 min（按上下文对索引生成） |
| `protection.assess` | 每变量重走全部调用路径 + 全量扫描 | 索引化（route_ancestors / windows / unmaskable） |
| betaflight `analyze()` 总计 | >3600 s（超时） | **~780 s** |

`analysis.max_conflict_paths`（默认 2000，0 不限）限制单变量展示层冲突组合数，
超限时按写冲突优先保留并显式记录 `CONFLICT_PAIR_CAPPED`；分类不依赖该展示枚举。
SAFE 变量不再生成展示层冲突组合（其证明即结论，组合全部为非冲突行）。

## 4. 提取器修复（影响所有引擎输入）

- **位置感知 parse 判定**：无源码位置的驱动层诊断（不支持的优化参数、未知警告
  选项）不参与失败判定——它们不影响 AST 恢复。
- **-Werror 类别豁免**：带 `[-W...]` 类别的 error 级诊断是警告提升，clang 已完整
  恢复 AST；不带类别的源码级错误（`expected ';'`、未声明标识符、fatal）仍判 FAILED。
- **非 UTF-8 源文件容错**：libclang token 解码对非 UTF-8 字节抛 UnicodeDecodeError
  并导致整个编译单元提取失败；逐 token 降级为占位文本（受影响参数不按字面量解析，
  保守处理）。
- **INLINE_ASSEMBLY 记录语句 extent**（end_offset），支撑 ASSEMBLY 调用边。

修复后提取覆盖率：klipper 58/58、blackmagic 192/192、betaflight 497/497 PARSED
（此前 betaflight 为 0/497 全部 FAILED）。

- **数组下标 designator 支持**：`[idx] = value` 的 UNEXPOSED 包装剥到实际值；
  数组元素共享抽象位置，忽略下标、保留值（含函数指针）。

## 5. 三个真实工程验证

同一套分类器；checkout 固定 commit；真实 `compile_commands.json` 构建闭包；
不扫描未参与当前 target 的源码；无项目专用规则（项目差异只进入各自的
semantics-ecra.yaml：build target、目录范围、上下文入口声明）。

### 5.1 klipper（Klipper3d/klipper，STM32F405 target，58 TU）

| | 旧引擎 | 新引擎 |
|---|---|---|
| SAFE | 518 (57.5%) | **841 (93.3%)** |
| SUSPECT | 0 | 38 (4.2%) |
| UNKNOWN | 383 (42.5%) | **22 (2.4%)** |
| OpenCode 队列 | 383 (42.5%) | **60 (6.7%)** |

SAFE 分布：NO_RUNTIME_ACCESS 677、READ_ONLY 61、SINGLE_FOREGROUND 103。
UNKNOWN 分布：RELEVANT_MISSING_TU 12、ADDRESS_ESCAPE 4、EXECUTION_CONTEXT 6。
修复生效点：`ResetHandler` 前台根 + 内联汇编尾跳边接通 `sched_main` 协作调度
前台链（此前整个前台入口不确定）。

### 5.2 blackmagic（blackmagic-debug/blackmagic，STM32F103 native target，192 TU）

| | 旧引擎 | 新引擎 |
|---|---|---|
| SAFE | 51 (7.1%) | **497 (69.4%)** |
| SUSPECT | 0 | 176 (24.6%) |
| UNKNOWN | 665 (92.9%) | **43 (6.0%)** |
| OpenCode 队列 | 665 (92.9%) | **219 (30.6%)** |

SAFE 分布：MULTI_CONTEXT_READ_ONLY 239、NO_RUNTIME_ACCESS 225、READ_ONLY 23、
SINGLE_IRQ 10。UNKNOWN 分布：RELEVANT_MISSING_TU 25、ADDRESS_ESCAPE 11、
EXECUTION_CONTEXT 5、DMA_LIFETIME 2。
修复生效点：逃逸判定变量本地化（1244 个入口不确定函数 → 5 个变量的缺口）、
小写 `*_handler` ISR 根（`sys_tick_handler`）。

### 5.3 betaflight（betaflight/betaflight，STM32F405 target，497 TU）

| | 旧引擎 | 新引擎 |
|---|---|---|
| SAFE | 未能完成（MemoryError） | **4619 (58.2%)** |
| SUSPECT | — | 2846 (35.9%) |
| UNKNOWN | — | **471 (5.9%)** |
| OpenCode 队列 | — | 3317 (41.8%) |

旧引擎在 betaflight 规模上于调用链无上限枚举处确定性内存耗尽（MemoryError），
不是超时问题。新引擎 `analyze()` 约 780 秒完成。

SAFE 分布：NO_RUNTIME_ACCESS 1998、SINGLE_FOREGROUND 1322、
MULTI_CONTEXT_READ_ONLY 629、READ_ONLY 639、SINGLE_IRQ 31。
UNKNOWN 分布：RELEVANT_MISSING_TU 297、EXECUTION_CONTEXT 127、
ADDRESS_ESCAPE 80、DMA_LIFETIME 22。
修复生效点：任务表 `[TASK_X] = DEFINE_TASK(..., taskFunc, ...)` 数组下标
designator 初始化此前整体提取为空（函数指针表丢失 → 任务子系统入口不确定，
1486 个变量 UNKNOWN_EXECUTION_CONTEXT）；修复后任务子系统整体进入前台串行域，
UNKNOWN_EXECUTION_CONTEXT 降至 127（-91%）。

## 6. 修改前后对比汇总

| 工程 | UNKNOWN 数 | OpenCode 队列 | 队列缩减 |
|---|---|---|---|
| klipper | 383 → 22 | 383 → 60 | **-84.3%** |
| blackmagic | 665 → 43 | 665 → 219 | **-67.1%** |
| betaflight | （MemoryError）→ 471 | （不可用）→ 3317 | 从不可用变为可用 |

三工程 UNKNOWN 占比均低于 10% 诊断目标（klipper 2.4%、blackmagic 6.0%、
betaflight 5.9%）；SAFE 成为最大分类（58.2%–93.3%），且全部携带显式证明代码
与证据。对比是在同一份（修复后）提取输入上进行的：提取修复同样喂给旧引擎。

## 7. SAFE 抽样审计（每工程 ≥30 个）

分层（变量种类 × safe_reason）随机抽样，逐个核对访问是否找全、执行上下文是否
正确、地址是否逃逸、是否存在遗漏 ISR/DMA、safe_reason 是否成立。

- **klipper**（30 个，`D:/ecra-bench/klipper-safe-sample.txt`）：抽查
  `alloc_end`、`stats_send_time` 等 SAFE_SINGLE_FOREGROUND 样本——全部访问位于
  `main` 前台调度域（`ctr_run_taskfuncs` 串行调度的任务函数），RMW/READ/WRITE
  混合但单一串行域成立；无地址逃逸、无 ISR/DMA 访问。**未发现 false-safe**。
- **blackmagic**（30 个，`D:/ecra-bench/blackmagic-safe-sample.txt`）：抽查
  `morse_tick`（SAFE_SINGLE_IRQ，全部访问位于 `sys_tick_handler` 单一 IRQ 上下文）、
  `q_commands`（SAFE_MULTI_CONTEXT_READ_ONLY，boot 链 + main 多上下文全部只读，
  ADDRESS_TAKEN 但无写逃逸）。**未发现 false-safe**。
- **betaflight**（30 个，`D:/ecra-bench/betaflight-safe-sample.txt`）：抽查
  `blackboxConditionCache`、`AccInflightCalibrationActive`（SAFE_SINGLE_FOREGROUND，
  跨文件读写但全部位于任务表前台调度域）、`baroUpdate::baroStateDurationUs`
  （LOCAL_STATIC，仅气压计任务访问）、`SET_TEST_MODE.b.Reserved`
  （SAFE_SINGLE_IRQ，仅 `OTG_FS_IRQHandler` 单一 IRQ 上下文）。逐项核对中特别
  复查了带取地址事实的样本（如 `adcTempsensorAverageState.pos`：地址传入同文件
  已解析 static 函数，points-to 完整追踪其内部访问，未流入不透明代码，非逃逸）。
  **未发现 false-safe**。

## 8. UNKNOWN Top 原因（修复后）

| 工程 | UNKNOWN 总数 | Top 原因 |
|---|---|---|
| klipper | 22 (2.4%) | RELEVANT_MISSING_TU 12（构建闭包内无定义的声明）、ADDRESS_ESCAPE 4、EXECUTION_CONTEXT 6 |
| blackmagic | 43 (6.0%) | RELEVANT_MISSING_TU 25、ADDRESS_ESCAPE 11、EXECUTION_CONTEXT 5、DMA_LIFETIME 2 |
| betaflight | 471 (5.9%) | RELEVANT_MISSING_TU 297、EXECUTION_CONTEXT 127、ADDRESS_ESCAPE 80、DMA_LIFETIME 22 |

betaflight 剩余 127 个 UNKNOWN_EXECUTION_CONTEXT 的访问函数集中在经
**堆分配设备结构 / 驱动 vtable 多层指针链**分发的函数（传感器补偿、遥协议
处理）：`dev->read(...)` 的 dev 来自运行时分配，抽象位置与静态表汇合前丢失
目标集合。这属于当前流不敏感 points-to 的表达能力边界，不是全局污染
（每个缺口都绑定具体函数与变量）。

## 9. 当前仍无法解决的静态分析边界

1. **堆分配对象的字段敏感追踪**：`calloc` 返回值经参数传递后与静态注册表
   汇合时，目标集合在链路中途丢失（betaflight 剩余 EXECUTION_CONTEXT 的主因）。
2. **DMA 生命周期 / Cache 一致性**：HAL DMA 契约只能恢复方向与缓冲区，
   所有权交接与 Cache 协议仍需人工复核（UNKNOWN_DMA_LIFETIME）。
3. **构建闭包内无定义的 extern 声明**（UNKNOWN_RELEVANT_MISSING_TU）：链接库
   /汇编提供定义而源码不在编译数据库时，无法证明其不访问该变量。
4. **真正的地址逃逸**：地址流入无实现函数（UNKNOWN_ADDRESS_ESCAPE）。
5. **内联汇编语义**：文本级扫描可恢复名字引用；任意指令序列的读写效果
   无法恢复（ASM 语句 extent 只用于恢复“汇编可调用”这一事实）。
6. **多核 / 非单核抢占模型**：按工程配置 fail-closed（UNKNOWN_UNMODELED_CONCURRENCY）。

## 10. 复现方式

```powershell
# 全量单元/验收测试（含 T01–T18 分类测试与 Demo cases D01–D20）
python -m unittest discover -s tests -q

# 基准（对缓存的提取 worker parts 重放新旧引擎）
py -3.10 D:\ecra-bench\bench_one.py <project-dir> <out.json>
py -3.10 D:\ecra-bench\bench_new_only.py <project-dir>   # 仅新引擎
py -3.10 D:\ecra-bench\bench_old_only.py <project-dir>   # 仅旧引擎

# SAFE 抽样审计表
py -3.10 D:\ecra-bench\safe_sample.py <project-dir> 30
```

工程 checkout：`D:\ecra-bench\{betaflight,klipper,blackmagic}`，各自
`semantics-ecra.yaml` 只声明 build target / 目录范围 / 上下文入口。
