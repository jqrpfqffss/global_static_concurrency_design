# serial - opencode 差异并发扫描验收

这是首轮验收记录；其中 95/96 行展示属于当时尚未修复的范围扩散。最新实现已将默认清单收敛为 33 行（含 5 个容器汇总），仍保持 21/21 项命中，详见[差异清单收敛验收](git-diff-focused-validation.md)。原始数据保留以便追溯。

目标工程：`H:/stm32_RAG/code/serial - opencode`。Codex 直接修改与验证，未调用 Claude Code、OpenCode 或其他编码代理。只进行 CMake/ARM GCC 构建、静态分析和测试，没有烧录、复位或串口操作。

## 已提交的固件分支

| 用途 | 分支 | 提交 |
|---|---|---|
| 保留的原工程 | `main` | `00b16f75d8edeeb2cbc02b600b2719eb686a314c` |
| 包含休眠深层访问的测试基准 | `ecra/diff-baseline-20261030` | `399e68a45b57d36d894bb9273ab7735ae57e4077` |
| 注入并发风险的差异版本 | `ecra/diff-stress-20261030` | `c7faf3b9b33c629c7d5158b5c8bfeb7c57af7e52` |

基准增加真实构建的四个夹具文件，并接入现有主循环与 USART2 IRQ。差异提交仅修改三个 C 文件，不修改头文件、构建配置和深层访问函数。`Probe_IrqBody()` 在两版均编译，差异版本通过远端新增调用使它可从真实 USART2 向量到达。

风险是**有意保留的测试代码**。日常产品开发应切回原 `main`；正式扫描时同时更新 `git_diff.base_ref`，或使用 `--scan-mode full`。当前配置指向测试基准，默认启用差异扫描，并关闭外部自动复核。

## 独立预期矩阵

完整机器断言见 [`expectations.json`](../tests/fixtures/serial_diff/expectations.json)。每项同时检查双版本分类、差异选中、具体访问/冲突证据、深层见证或安全反例；不能仅凭“已显示全部变量”判为通过。

| 编号 | 场景 | 当前预期 |
|---|---|---|
| D01 | 新增 `probe_added`，主循环和 IRQ 均 RMW | SUSPECT，基准不存在 |
| D02 | `probe_rmw` 从 store 变为 RMW | SUSPECT，保留 RMW 证据 |
| D03 | 移除 `probe_lock_removed` 的完整 PRIMASK 保护 | SAFE_PROVEN → SUSPECT |
| D04 | 移除 `probe_race_removed` 的 IRQ 写入 | SUSPECT → SAFE_PROVEN，仍在差异清单 |
| D05 | 删除 `probe_deleted` | 基准删除清单可追溯 |
| H01 | 跨 TU、多层转发、返回双重指针，间接递增 | `probe_indirect` 为 SUSPECT |
| H02 | getter 返回函数内 static 地址，再经双重指针修改 | `Probe_LocalSlot::hidden_epoch` 为 SUSPECT |
| H03 | const 描述符中的 callback 和 `void*` payload，经多层分发 | `probe_callback` 为 SUSPECT |
| H04 | 未修改函数内 static 从前台私有变为 IRQ 可重入 | `Probe_Reentrant::hidden_scratch` 为 SUSPECT |
| H05 | getter 读取快照，另一函数仅屏蔽写回，写回 `old+1` | SUSPECT，必须含 READ_THEN_WRITEBACK 提示 |
| H06 | `memcpy` 隐含读取结构体，IRQ 更新两个成员 | `probe_frame.sequence/value` 均为 SUSPECT |
| H07 | 动态字节视图读取 64 位计数，IRQ 递增 | `probe_wide` 为 SUSPECT |
| H08 | 动态下标与 IRQ 固定元素重叠 | `probe_array[2]` 为 SUSPECT |
| H09 | union 整字 RMW 与字节 cast 写入重叠 | `probe_overlay.word` 为 SUSPECT |
| H10 | 相邻位域在同一存储单元内的 RMW | `probe_bits.low/high` 均为 SUSPECT |
| S01 | 完整屏蔽窗口内的前台 RMW | `probe_masked` 保持 SAFE_PROVEN |
| S02 | 前台与 IRQ 分别写不重叠成员 | 两个成员均 SAFE_PROVEN |
| S03 | 头文件 static 的独立 TU 实例，其中两个有运行访问 | 不合并实例，均 SAFE_PROVEN |
| S04 | 两个 TU 的同名 static | 两个独立对象，均 SAFE_PROVEN |
| S05 | 跨上下文只读常量 | SAFE_PROVEN |
| S06 | 独立 EXTI4 向量内未变化的私有变量 | SAFE_PROVEN，排除出差异选择 |

## 发现与修复

第一次真实扫描为 19/21 项通过，失败项为 H05、S06。风险变量本身已判 SUSPECT，但 H05 未恢复 getter 返回与常量运算后的旧值写回关系；S06 被全局保守回退一并选择。

1. `extract.py` 记录标量 getter 的直接返回来源、直接调用返回值作为实参、不可变参数的常量加减/异或来源。`stale_writeback.py` 跨函数解析返回来源，再关联同一 canonical storage 的读取与写回，保存返回路径和派生值标记。未知 getter、读了但没有返回的值、不同对象、参数被重写或取址的情况不猜测关联；循环与递归有 visited 集合。
2. 真实基准工作树经 Git 检出为 CRLF，当前库中部分 HAL 头文件是 LF。libclang 的多行宏 token 保留了 `\\\r\n`/`\\\n` 的区别，导致没有修改任何宏时也触发构建语义回退。宏签名仅规范化 CRLF/LF；真实宏值变化仍会失效。
3. 在非构建语义回退下，仅当两版都有完整的未逃逸私有标量直接访问证明、上下文/调用子图/证据全部不变，且普通语义影响闭包没有选中它时，允许免于全局扩大。指针、数组、结构体、取址、别名、未知覆盖或真正构建变化不适用。报告保存 `fallback_exemptions`，完整后台分析不做过滤。摘要 schema 从 4 升为 5，使旧摘要缓存失效。

上述改进不把“无 getter 提示”解释为安全，也不把所有 C 表达式视为已建模。复杂标量数据流、硬件真实时序和未解析依赖仍按扫描器的覆盖限制处理。

## 复现

在扫描器目录运行当前测试工程：

```powershell
py -3.10 run_ecra.py --scan-mode diff --no-review
```

执行三轮独立验收（证据目录必须尚不存在）：

```powershell
py -3.10 scripts/validate_serial_diff.py `
  --project 'H:/stm32_RAG/code/serial - opencode' `
  --evidence output/serial-diff-new-validation
```

脚本冻结引擎、配置、固件 HEAD/基准和断言文件，顺序运行首次差异、独立全量、热缓存差异，检查 21 项预期和三轮完整规范化摘要一致；两轮差异都逐项验收，并归档可独立读取的事实、报告、日志与输入有效性。

要在另一份干净的同源串口工程创建相同分支，可使用 `scripts/prepare_serial_diff.py --project <工程> --receipt <新路径>`。它拒绝覆盖已有分支/夹具文件，保留原始分支，并分别提交基准和差异。不要对已生成过这些测试分支的仓库再次运行。

## 实测结果

完整机器记录见 [`serial-diff-stress-validation-results.json`](serial-diff-stress-validation-results.json)。冻结的静态引擎摘要为 `7a7927e5e2b6e8030695ac3d4a3039f2162919acd738b37f155d24b6c2104ab5`。

| 轮次 | 耗时（秒） | 解析 | TU 缓存 | 验收 |
|---|---:|---|---|---|
| 首次差异（含完整独立基准） | 142.578 | 23/23 PARSED | 0/23 命中 | 21/21 项通过 |
| 当前版独立全量 | 70.500 | 23/23 PARSED | 独立重新提取 23 TU | 完整规范化语义摘要与首次差异相等 |
| 热缓存差异 | 48.656 | 23/23 PARSED | 23/23 命中，提取 0 TU | 21/21 项再次通过，完整摘要仍与独立全量相等 |

三轮 ARM GCC 真实构建及输入快照均有效，`analysis_valid=true`、`snapshot_status=VERIFIED`。退出码 2 表示保留静态疑似与待复核项，不是构建或输入验证失败。当前 81 个实际分类对象中，SAFE_PROVEN 41、SUSPECT 40；另有 11 个容器汇总，归账 missing=0、duplicate_ids=0。这些总数包含原有串口业务代码，不能当作本次新增缺陷数量。

构造项全部命中并保留真实冲突证据：H01 保留了 10 个函数的深层调用见证；H03 可追溯 USART2 → Probe_Irq → Probe_IrqBody → Dispatch1/2/3 → CallbackBody → Increment 的八函数回调路径与 payload 别名。H05 已包含 getter 返回来源与 `READ_THEN_WRITEBACK` 提示。S01–S06 均满足安全预期，S06 的独立私有变量不进入差异选择。

工程仍因执行/别名全局语义变化和未解析依赖触发两项 L1 保守扩大，95/96 个原始存储证据行进入差异范围。**这不是精确缩小整个真实工程差异范围的证明，也不是原工程所有风险均已排查完成的承诺。** 宏换行造成的伪构建变化已经消失；唯一有独立完整隔离证明的 S06 被排除，其余保守范围如实保留。

测试耗时来自同机并行执行回归期间，不用于承诺固定提速比例。

`py -3.10 -m unittest discover -s tests -v` 执行 1030 项，882.741 秒；发现 1 处旧测试写死 schema=4 的断言，0 错误，2 项须显式启用的真实 OpenCode 复核测试跳过。该测试已改为引用 `SUMMARY_SCHEMA`，其两项专项在修正后全部通过。最终对所有改动相关测试组再执行 23 项，全部通过。**不能把旧断言修正前的整轮日志描述为单轮全绿**；当前失败项已修正并复测，没有剩余失败。另有 96 项首次专项执行记录，其中同样仅该旧版本断言失败。

`git diff --cached --check` 与改动 Python 模块编译检查通过。回归日志分别位于 `full-regression.log`、`schema-regression.log` 和 `final-targeted.log`，保留初始失败记录以便审计。

运行产物保存在 `output/serial-diff-20261030/`，最终报告位于固件 `.ecra/index.html`。分类 SUSPECT 表示静态疑似冲突证据，不冒充模型复核或硬件实测确认。
