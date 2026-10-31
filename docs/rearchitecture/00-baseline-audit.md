# Phase 0：真实基线审计

2026-10-31，工作目录 `H:/global_static_concurrency_design`。本文件记录实际观察；不把历史报告当作本轮验收。

后续执行结果：本文件的冻结条目保留起点状态；真实4TU原生黄金、独立前后提取、存储全字段往返已运行并留证，见 `evidence/native-equivalence.json` / `golden-roundtrip.json`。完整Diff黄金与三类大型项目仍未完成。当前消费者引用清单另见 `legacy-consumers-current.txt` / `consumer-migration.json`，不能把SPA程序资源误算为旧扫描报告。

覆盖边界补充：原四TU黄金虽然已实际ARM编译/链接，Clang阶段为4FAILED、13UNKNOWN，不能用来覆盖成功解析路径。另一明确输入配置保留同一固件/真实数据库并开启编译器系统头搜索，在原e69引擎得到2PARSED/2PARTIAL、6候选；候选同输入全字段对照差异0，原源码/.git及输出不变。见evidence/native-parsed-golden-v2.json；两份黄金分别保留，不将配置变化称算法优化，不称全部TU完整覆盖。

## 起点与冻结

- 分支 `optimize_ccc`；HEAD `e69a10bbcb870dfc19a7d69cf2267774d08b3342`。
- 起始唯一未跟踪文件为用户任务书 `docs/ECRA_optimize_ccc_Codex.md`，保留原字节。无已修改代码。
- 原引擎与测试/脚本/配置已通过 `git archive HEAD` 冻结在 `H:/ECRAStudio-data/rearchitecture-20261031/baseline/engine.zip`，解压执行目录 `engine/`。哈希与起点收据见 [initial-state.json](evidence/initial-state.json)。基线只在独立目录运行，不受开发代码修改影响。
- 已冻结仓库内公开 STM32F030 真工程（不是合成 fixture）：`hemashushu/practice-mcu-bare-metal-stm32f030`，SHA `55bbd6a1ffddfd4acb20b62aabb3c0eb060e2eb3`，原工作区干净。`firmware.zip` 与 `firmware/` 位于同一独立基线目录。其原生构建、全量与 Diff 黄金收据待运行，**冻结源码不等于黄金扫描已通过**。
- 历史 INAV v23 `acceptance.json` 实读为 `complete=false`、`runs=[]`。不能作为本轮黄金等价或大型 Diff 通过证据。

## 实际调用链与迁移边界

```text
cli.main → config.load_config → cli.run
  → WorkspaceResolver.resolve/initialize/bind → migrate_legacy → scan.lock
  → git_diff.pin/prepare_base/prepare_current（Diff）
  → compilation.prepare → 实际 CMake/编译闭包
  → dependency_results → input_snapshot
  → extraction_responses → 独立 ecra.extract 子进程 → response + metadata
  → FactParts.append_metadata/iter_linked_parts → analysis.merge
  → analysis.analyze → 全局 points_to/context_points/完整调用与保护判定
  → git_diff.summarize/compare/verify_full（Diff）
  → report.generate → facts.json + facts.db + inventory/reports + HTML/MD
  → workflow.save_scan → review_all → generate → 发布后输入再验证
workflow.status/saved_run → checked_scan → 输入/引擎/报告摘要复验
  → review/review-failed/report → 旧事实/报告 → 再发布
```

逐行消费者盘点：[legacy-consumers.txt](evidence/legacy-consumers.txt)。该文件由 `rg` 从 `ecra/scripts/tests` 实际生成，含路径与行号；新增消费者须重跑盘点，不能仅靠下表宣称全部完成。

| 消费者 | 当前依赖/危险 | 目标接口与验收 |
|---|---|---|
| `cli.run` | 历史 finding IDs、generate/save_scan、失败页、发布哈希 | 不可变 scan 发布；失败不替换旧快照；G1/G5 |
| `workflow.checked_scan/verify_saved_publication` | facts.json 哈希、静态 report、输入闭包；不能绕过已有校验 | 权威库完整摘要 + 原输入/引擎校验；G1/G6 |
| `workflow.status/saved_run` | queue、完整 report、HTML 路径 | QueryService；review 与 report 不再派生巨型文件 |
| `git_diff.prepare_base/current/verify_full` | 基准 facts.json 硬链接、摘要缓存、固定 worktree | 版本化 scan 引用；保留直接 base→current 与全量验证 |
| `review.build_variable_review_packet/review_all` | facts_path/shared_path/report_path、源码与八步合同 | EvidenceProvider 分段取证；完整收据/修复/失败逻辑回归 |
| `multicore.combine` | 子变体旧 facts 与 ELF | 同一证据协议；尚未迁移 |
| `history_archive/workspace.migrate_legacy` | 旧字节复制/身份/哈希 | 复用身份与边界；源数据永不自动删除 |
| `scripts/*.py`、旧测试 | 详见逐行清单；部分是刻意旧格式审计器 | 显式开发期 legacy 导出；每个正式消费者逐项迁移 |

## 实测前的瓶颈判断（代码证据）

- `cli.dependency_results` 已用 deque 限制提交数；`cli.extraction_responses` 使用独立进程，但 `futures = [pool.submit(...) for unit in units]` 一次提交全部任务。更换调度只能保留编译数据库消费顺序、异常和关闭语义。
- `FactParts` 已逐行读取 TU、保留弱/强链接选择、共享类型布局；不能删掉这些优化。
- `analysis.merge/analyze` 仍持有全局工作集；仅优化 Worker 提交不能声称全局分析已降至 16GB。
- `report._generate` 为相同事实分别建立 shared_json.Plan、JSON、SQLite 与 HTML/MD；`write_database` 动态列中嵌套证据仍是 JSON 字段，不能当作本次规范化数据库的完成实现。
- `git_diff.prepare_current(include_uncommitted=true)` 当前直接返回原 root。只改输出目录不足以证明 H2：必须再固定 dirty 字节并验证真实构建闭包，未完成前该路径是发布阻断。
- 当前 `WorkspaceResolver` 已处理完整项目身份、Junction、外置 CMake 和迁移，不另建第二套解析器。默认 `<tool>/workspace` 与 `location: project` 不满足本次正式流程。

## 历史性能的适用范围

`docs/inav-h743-git-diff-validation.md` 记录 0f3f 引擎 388 TU：12050.609 秒、进程树 RSS 29510447104 字节，报告阶段 7766.500 秒；与 6e3b 完整规范化摘要一致。另有早期 66GB JSON/92GB DB/约55GiB 峰值记录。它们属于不同版本，不与本轮测量拼接计算收益。SmartFarm 的 62 TU/4081975296 B 等数据见 `docs/real-project-optimization-validation.md`，同样仅作历史证据。

本机可用 Python 3.10、libclang、ARM GCC、CMake、Node 与浏览器测试依赖。32GB 专用 Windows、三类真实大工程原生前后扫描、真实模型联网、干净离线机和工程师盲测均 **NOT_VERIFIED**。不得据此关闭 Phase 0/2/6 门禁。
