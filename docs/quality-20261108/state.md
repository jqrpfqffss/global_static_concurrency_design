# 状态、恢复与人工持久化检查（2026-11-08）

本页保留首轮的真实检查及当时版本。最新主区、最终包与未完成门禁见[当前 V9 验收](continuation-final-v9.md)；本页的“最终”仅指当时冻结轮次。

检查基线：`optimize_ccc` / `fe27afe73596d98e1a21e3f28a2125d38d7272d0`。直接 Codex 修改；未调用外部 AI、未改真实客户数据、未切分支。隔离数据位于 `H:/ECRA-quality-20261108/state/actual-service/data`。

## 已确认及已修复问题

| 编号 | 级别 / 影响 | 复现与根因 | 修复与复验 |
|---|---|---|---|
| Q101 | 重要：单条坏任务记录阻断全部 Studio 启动或任务列表，无法访问有效结果 | `work/tasks/<id>/task.json` 截断时 `TaskManager.__init__` 直接抛 JSONDecodeError；合法 JSON 缺 mode/scan_id 仍会令详情 KeyError。复制 job 登记同类问题。初始复现见 corrupt-task-baseline.json | task_records.py 为显示提供显式 UNREADABLE 诊断；tasks.py、root_transfers.py 使用专用字段校验。损坏原件不改、不伪造恢复数据；有效邻居照常恢复和浏览；前端明确标签，禁止以损坏登记停止/重试。针对测试及实际 Windows 服务启动/重开通过。 |
| Q102 | 重要：工作进程已退出但页面仍显示 RUNNING；也可能误认矛盾完成收据 | monitor 最后读取 worker-result/preflight JSON 直接异常，finally 只释放活动租约，不持久化终态 | 严格验证完成收据类型、退出码、完成标记与错误的一致性，坏/缺收据记 FAILED，130 记 INTERRUPTED；保留已有发布结果、原始收据与下一步。完成/失败、错码、畸形/缺字段、停止相邻路径已回归。 |
| Q103 | 重要：日志或任意诊断坏一处，整条失败任务详情不可读 | detail 对 console.log、preflight、scan_stages 等逐项读取均无错误隔离；用户失去可用日志和恢复入口 | 文件级读取错误明确展示，其他有效状态/日志/诊断继续提供；不把失败诊断改成通过。缺日志、坏 preflight、坏 stages 与有效 exception 共存已验证，原件字节保留。 |
| Q104 | 重要：复制监督器崩溃后外层 PUBLISHING 一直显示正在发布 | RootTransfers 启动检查仅转换 RUNNING/COPYING/VALIDATING；UI 将 PUBLISHING 视为活动状态并持续轮询 | 将无所有者的外层 PUBLISHING job 标 INTERRUPTED，保留原 journal 路径。底层 journal 的 PUBLISHING / rename 后恢复语义未变。新增监督器恢复测试 + 既有真实原子发布后恢复测试通过。 |

## 关键合同与覆盖

| 功能 | 当前真实入口与合同 | 验证结果及边界 |
|---|---|---|
| 服务启动 | `run_ecra.py ui` / `python -m ecra.studio` 为本机 FastAPI+uvicorn，独立数据根 | 实际 Windows 服务启动三次；坏任务/复制历史共存仍启动，当前最终源码重开亦通过。 |
| 扫描任务 | TaskManager start → 独立 owned worker → preflight → canonical scan；同数据根共享预算 | 原有资源/跨监督器租约测试通过。此子任务没有新增真实固件扫描；真实工程由协调者统一验收。 |
| 停止/恢复 | 扫描缓存经输入核验后复用；review 与 review-failed 保持原模式和冻结资料；无有效收据不宣称成功 | native_review_workflow、任务故障测试通过；外部模型由受控传输夹具替代，因此不宣称实际 OpenCode 推理通过。 |
| 复核批处理 | `review.workers` 为 1–8；ThreadPool 自动推进全部选中候选；当前代码未发现 max_items 契约 | 并行单项技术失败、failed-only只重试失败、KeyboardInterrupt后重跑保留原静态字节等基线测试通过。 |
| 人工确认 | `/api/scans/<id>/human` 以项目/scan、canonical symbol_id、完整证据 fingerprint 绑定；append-only事件、expected_heads冲突校验 | 原有人工/继承/当前结果投影测试通过；真实 HTTP 保存两个确认、保存位置，终止再重开服务后事件 ID 与结论、位置、pending统计、静态库hash均保留。此项为 API 实际操作，不能替代浏览器交互验收。 |
| 导出/导入与跨来源隔离 | 原有 report package、人工增量与继承校验 | 基线 tests 验证单项失败不丢有效结果、包往返、跨项目绑定拒绝、并发确认冲突与撤销留历史。 |
| 写入/读取失败 | 人工SQLite事务回滚，元数据JSON原子替换；损坏记录只提供诊断 | atomic_output 与相关基线测试通过。没有模拟断电、硬盘故障或系统重启；磁盘满/写锁实际GUI验证由协调者另验。 |

## 证据与命令

- 初始基线：`baseline-tests.log`，66 passed + 51 subtests，覆盖 human_reviews / studio_current_results / task_metadata_reads / studio_workspace / studio_api / native_review_workflow / review_inheritance / atomic_output / effective_decisions。
- 最终定向回归：`task-recovery-regression-final-v3.log`，29 passed + 22 subtests；命令为 `py -3.10 -m pytest tests/test_task_recovery_failures.py tests/test_task_metadata_reads.py tests/test_studio_resource_policy.py tests/test_data_transfer.py -q`。
- 实际前置故障：`corrupt-task-baseline.json`；在独立临时根制造任务 JSON 截断，初始 Studio 启动抛 JSONDecodeError，原字节未改。首次将数据根放工具安装目录被正确拒绝，随后按真实合同改为独立临时根，并未放宽数据目录限制。
- 实际当前源码服务：`actual-service-reopen.json`，包含两次原生服务进程与最终源码再次重开结果、两个确认事件ID、静态hash和隔离数据根。服务全部停止，未留监听端口。
- 保留首轮回归日志：`task-recovery-regression.log` 中五个子场景失败来自 Windows TEMP 8.3短名与长路径等价但字符串不同；按 `Path.resolve()` 统一路径后通过，未修改产品预期或降低验证。
- 前端由协调者统一构建与视觉复验，本子任务未构建或改生成资产；需重启服务加载 Python 修复。

不把测试数量、API通过或窗口能打开等同于全部用户流程已通过；真实工程、浏览器操作、不同缩放和便携成品的结论均须采用协调者对应证据。
