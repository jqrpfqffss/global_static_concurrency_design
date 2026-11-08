# 分析正确性、差异与复核聚合验收

本页保留首轮的分析与回归证据；后续Q205/Q206/Q207等修复、各引擎真实适用范围和剩余门禁见[当前 V9 验收](continuation-final-v9.md)。本页旧“最终”仅指当时冻结版本。

本轮直接使用 Windows `py -3.10`（CPython 3.10.11）、libclang 18.1.1。初始分支 `optimize_ccc`，提交 `fe27afe73596d98e1a21e3f28a2125d38d7272d0`。所有写入来自隔离临时工程、SQLite 测试库及 `output/quality-20261108/analysis/`；没有修改客户工程和原人工记录，没有调用联网 OpenCode。

## 当前数据链

`compilation.prepare` 处理真实编译信息；`Extractor` 生成 TU facts；`analysis.merge/analyze` 合并存储身份、调用/上下文与冲突；`EvidenceIndex` 将缺口关联至实际变量，`evidence.classify` 确定静态分类；复核账本独立保存 AI 状态与答案；`decisions` 用于报告最终分类，Studio 通过 `current_results` 对相同静态事实与已提交 AI 水位进行只读投影。

现行实现已经保留：头文件 static/局部 static 的 TU 与作用域身份、宏/别名访问、读改写及旧值写回、变量相关解析缺口、完整保护窗口、NMI/HardFault 及 NVIC 证据。`volatile`、单 writer 或字长本身不自动构成安全证明。当前 `SHARED_NO_REVIEW` 是另列的共享访问免复核状态，有宽度/对齐、物理 writer、可见性及协议等门禁，不能将其描述为完整的安全证明。

历史描述仅用于定位；以下两项有当前运行证据。

## 问题与修复

| 编号 | 级别/影响 | 当前复现 | 独立预期依据 | 根因与修复 | 复验 |
|---|---|---|---|---|---|
| Q201 | 严重：不可屏蔽异常被错误判为完整保护，漏入安全 | 配置 `contexts.vector` 为 `NMI_Handler`、`HardFault_Handler`、`slot:2` 或 `slot:3`，入口 C 函数名为 `ExceptionRoute`；该函数与 main 均修改 `shared`，main 使用 PRIMASK。四种情况全部为 `SAFE_PROVEN / EFFECTIVE` | PRIMASK 不屏蔽 NMI/HardFault；物理异常身份不由 C 函数拼写决定。[CMSIS Core Register Access](https://arm-software.github.io/CMSIS_6/main/Core/group__Core__Register__gr.html) | `protection.assess` 原只查根函数名称或显式 `unmaskable`。新增 `_fixed_exception_slots` 按物理向量、ABI 槽位及 IRQn 识别固定异常，复用到 PRIMASK/BASEPRI 参与者检查和 FAULTMASK 的 NMI 检查 | 四种原复现均变为 `SUSPECT`；新增 7 个测试方法覆盖名字、slot、负 IRQn、普通正 IRQ2/3、FAULTMASK/BASEPRI、显式不可屏蔽约束与实际 C 向量表 |
| Q202 | 重要：启用 AI 后已有静态冲突从风险筛选消失，报告与 Studio 不一致 | 同一 `SUSPECT` finding、同一已提交 `DONE / NEED_MORE_CONTEXT`：`decisions.effective_decision` 为 `likely`，Studio 为 `UNKNOWN` | 原决策契约及现存 `test_effective_decisions`：证据不足不能证伪静态冲突，只有有效风险/安全语义结论可以改变它 | `current_results.finding_results` 曾将 NEED_MORE_CONTEXT 固定为 UNKNOWN，绕过静态回退。移除此覆盖；AI 完成数量与有决策作用的答案数量分别统计，保留原答复且正确显示结论来源 | 原复现变为 `LIKELY`，原始 AI 仍为 NEED_MORE_CONTEXT；30 格状态矩阵及 10 种多 finding/排列与已有 `variable_decisions` 一致，列表/汇总/人工待办仍一致 |

Q202 中原 Studio 测试的两处 `SUSPECT → UNKNOWN` 预期已修改，并在测试内注明上述独立依据；并非根据新实现反向制造预期。未修改 `tests/protection_reference.py` 等冻结旧算法对照，既有索引等价性测试继续通过。

## 验证范围与证据

| 验证组 | 命令中的 unittest 模块 | 实际结果 | 证据（仓库相对路径） |
|---|---|---|---|
| 初始高风险基线 | `test_effective_decisions test_interrupt_priorities test_ecra test_conflict_instances test_conflict_allocation test_byte_alias_overlap test_review_contract` | 83 项通过，162.007s；包括实际 AST 小工程、身份/别名/冲突、导出及 AI 合成协议 | `output/quality-20261108/analysis/baseline-unit.log` |
| Q201 与邻接保护门禁 | `test_exception_masks test_interrupt_priorities test_shared_no_review test_design_acceptance` | 当时新增 6 方法，共 68 项通过，18.247s | `output/quality-20261108/analysis/exception-mask-regression.log` |
| Q201 完整新增测试及架构入口 | `test_exception_masks test_protection_index test_vector_contexts test_nvic_recovery` | 57 项通过，16.445s；含后来新增的真实 C 向量表方法和 5000 组索引旧算法对照 | `output/quality-20261108/analysis/exception-architecture-regression.log` |
| diff/cache 与旧值写回 | `test_diff_focus test_diff_build_paths test_git_diff_storage_shape test_diff_graph_index test_engine_digest_coverage test_stale_writeback test_stale_return_values` | 56 项运行，通过；1 项 opt-in 联网 OpenCode 跳过，43.915s | `output/quality-20261108/analysis/diff-stale-regression.log` |
| Q202 与相邻 API/AI/导出 | `test_studio_current_results test_studio_ai_results test_studio_api test_effective_decisions` | 46 项通过，76.174s；含真实 SQLite 提交水位、人工记录不被覆盖、未提交事件不进入结果、旧账本投影 | `output/quality-20261108/analysis/studio-decision-regression.log` |

上述组存在重叠，不相加宣称独立测试总数；合成 AI 响应仅验证传输、错误、状态和聚合契约，不证明模型推理质量。Starlette 对开发依赖 httpx 发出弃用提示，未导致测试失败；没有因此升级运行依赖。

原始可重跑问题探针与前后结果：

- `output/quality-20261108/analysis/probe_exception_masks.py`；`exception-mask-before.json` / `exception-mask-after.json`（原四场景）。修后探针退出 0，收据 `exception-mask-after-run.json`。
- `output/quality-20261108/analysis/probe_studio_inconclusive.py`；`studio-inconclusive-before.json` / `studio-inconclusive-after.json`（同一静态/AI 输入与既有决策函数对照）。修前退出 1，修后退出 0；同名 `*-run.json` 保存退出状态。
- `git diff --check` 对本职责修改通过。

Q201 修改了静态引擎文件，旧扫描需要重新扫描才能采用修复；不可只刷新旧报告后声称新引擎已验证。Q202 仅改 Studio 只读查询，不更改静态事实或其摘要，重启 Studio 服务即可采用。生产文件在本轮上述回归完成后未再修改。

## 明确限制

- 本职责没有重新调用联网 OpenCode，也没有把历史真实答复当成本轮模型正确性通过。安全/误报的实质论证仍需要检查源码、完整相关冲突及运行条件。
- 本职责的小工程不是三个独立真实 STM32 工程验收的替代；真实工程、便携 Windows 成品、浏览器画面与退出恢复由本轮主验收记录分别给出。
- diff/cache 回归覆盖变量/宏/布局/调用图及引擎失效等既有关键契约，不能推出所有固件的所有差异组合已验证。
- 对当前复杂 DMA、动态回调、RTOS/双核边界，保持现有证据缺口与复核语义；没有扩展为完整支持或减少必要分析。
