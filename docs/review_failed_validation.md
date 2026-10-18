# review-failed 故障注入实测

2026-10-18，结论：当前 `py -3.10 run_ecra.py review-failed` 符合预期，无需修改生产复核逻辑。

测试使用独立 Cortex-M3 C 工程，真实 Arm GCC 编译、Clang 扫描，然后以真实 `py -3.10 run_ecra.py ...` 子进程执行命令。额外的 `--project`、`--config` 只用于隔离测试工程。没有 monkeypatch，也没有手改 queue 的状态制造结果。正式工程配置、复核队列、扫描检查点的前后 SHA-256 相同。

配置为 workers=1、retries=0、max_items=1；关闭单次内部技术重试，是为了让注入故障确定地留在失败集合，观察多次显式 `review-failed` 的行为。失败项超过一批时仍自动处理全部批次。

## 真实进程故障：10 个候选

执行器是明确标注的外部进程测试替身，其成功答案仅验证机制，不表示模型分析能力。它实际退出、阻塞或输出错误；ECRA 经真实进程管理、解析、持久化和 CLI 路由处理这些故障。

| 步骤 | 命令 | 本次目标 | 执行器调用数 | 结果 |
|---|---|---:|---:|---|
| 尚未复核 | review-failed | 0 | 0 | 10 PENDING |
| 初次复核，注入 exit=17 和超时 | review | 10 | 10 | 8 DONE + 2 TECH_FAILED |
| 恢复一项，另一项继续返回 provider error | review-failed | 2 | 2 | 9 DONE + 1 TECH_FAILED |
| 剩余项返回坏 JSON，包含两次格式修正 | review-failed | 1 | 3 | 9 DONE + 1 TECH_FAILED |
| 清除剩余故障 | review-failed | 1 | 1 | 10 DONE |
| 全部完成后再执行 | review-failed | 0 | 0 | 10 DONE |

超时阈值为 2 秒；执行器实际等待 30 秒，由 ECRA 超时终止，原始 stdout 和 stderr 中的部分内容均被保留。provider error 使用退出码 0 的 JSONL error 事件，仍识别为技术失败，没有进行 FORMAT_FIX。坏 JSON 在两次格式修正仍失败后保持 TECH_FAILED，之后可以继续重试；该项累计到第 6 次调用成功，没有永久放弃阈值。

最终十项中五种合法语义状态各两项，包括 LIKELY 和 NEED_MORE_CONTEXT，均为 DONE。最初八项成功收据在后续各轮逐字节相同；新成功项也退出失败集合。

## 接入真实 OpenCode：3 个候选

同一适配器在放行时直接启动本机真实 OpenCode，将原始参数、标准输入和 ECRA 的只读权限环境传给它，不生成替身答案。故障控制文件及测试计划放在模型工程目录之外，没有作为源码附件发送给模型。

| 步骤 | 命令 | 本次目标 | 执行器调用数 | 结果 |
|---|---|---:|---:|---|
| 一项真实复核；另两项注入进程退出/provider 错误 | review | 3 | 3 | 1 DONE + 2 TECH_FAILED |
| 放行一项，另一项继续失败 | review-failed | 2 | 2 | 2 DONE + 1 TECH_FAILED |
| 放行最后一项 | review-failed | 1 | 1 | 3 DONE |
| 全部完成后再执行 | review-failed | 0 | 0 | 3 DONE |

共 3 次真实 OpenCode 成功复核、3 次注入失败。真实输出保留独立 sessionID、源码 read 工具记录及最终 JSON；最终收据均通过原始日志、Packet、提示词和引用源码的完整性校验。第一项 DONE 后的两轮不再调用它；第二项 DONE 后，下一轮只调用最后一项。

两层测试都逐轮校验：未选中记录内容不变、DONE 收据文件不变、全部旧 attempt 日志内容不变、失败日志及错误信息完整、静态事实/输入清单/扫描检查点内容不变、源文件不变、结束后无遗留扫描锁。另运行 3 项现有重试相关回归测试，全部通过。

## 复现与证据

```powershell
# 无模型调用：真实子进程故障注入
py -3.10 scripts/validate_review_failed.py

# 同时接入本机已配置的真实 OpenCode，只读复核
py -3.10 scripts/validate_review_failed.py --live
```

每次创建新的时间戳目录，不覆盖既有结果。本次证据位于 [validation.json](../output/review-failed-20261018-221046/validation.json)，包括所有实际命令、逐轮选择的变量、调用日志、退出码与状态统计。该目录下 `fixture/`、`live/` 另存逐轮 queue 快照、CLI 日志、故障计划以及各工程 `.ecra/review/` 的原始归档。

适配器：[fault_cli.py](../tests/fixtures/review_failed/fault_cli.py)；驱动：[validate_review_failed.py](../scripts/validate_review_failed.py)。

本测试验证失败筛选、恢复和归档行为，不验证竞态语义准确率，也没有烧录目标板。`INCOMPLETE` 或退出码 2 仍可能来自静态覆盖缺口、LIKELY 或 NEED_MORE_CONTEXT；应通过 DONE/TECH_FAILED 统计判断模型执行是否完成，不能仅凭总状态认为重试失败。
