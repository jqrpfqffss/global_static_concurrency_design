# R3a大型真实报告摘要：完整校验与原值相同

冻结v42 / `5c4281b`的只读消费者已对既有冷原生INAV v13数据库实际完成运行。数据生产者仍为冻结v32 / `49960e0`，没有把一次读取重新称为新扫描。**完整重构和整个R3仍未完成。**

| 实际校验 | 结果 | 证据 |
|---|---|---|
| 完整数据库输入 | `H:/ECRA-NATIVE-A13-SEED0/scans/native-golden/scan.db`，12,590,489,600B；开始时完整SHA等于原manifest，结束后完整SHA相同 | PASS_SCOPED：[完整结果](evidence/inav-v13-native-report-digest-v1.json) |
| 原报告摘要协议 | 逐节点计算原`logical_digest(clean_report(report)) / ECRA_MERKLE_V1`，与原scan_state完整值相同 | PASS；非新规范化规则，未用原生ordered hash替换 |
| 不恢复整图 | 实际禁用`EvidenceProvider.load`，完整摘要计算仍结束；没有候选/访问/路径/字段topN | 完整重建调用0 |
| 真实受控资源 | 2GiB OwnedProcess；最终Job提交峰值**34,557,952B**、RSS峰值47,693,824B、树Private峰值34,549,760B | PASS_SCOPED：[完整进程/资源收据](evidence/inav-v13-native-report-digest-execution-v1.json) |
| 时间与来源保护 | 摘要正文700.297秒；含两次整库SHA和控制/源码后验978.547秒；原state、manifest字节不变，3688冻结代码文件SHA差异0 | PASS_SCOPED；不以不同操作作提速对照 |

原检查点期望值与本次计算值均为：

```text
b8b2d88b0e0f76d592e95f418c96fee98e0dfdf1989577f84f0ee34a80e8821b
```

它是现有检查点的完整clean-report摘要，包含其原协议规定的全部静态字段及顺序/类型，不是[79号](79-r2b-regression-and-v13-package-final.md)中去除既有执行包络后的26af…语义对照摘要。原独立语义对照0/0保持原范围；不能把本次700秒当作完整全量扫描耗时，或与69103秒的另一完整对照实验相减计算“提速”。

实际实现及38项回归见[83号](83-native-status-and-checkpoint-consumer.md)。同批原路径F030新扫描仍完整0/0，实际包内Python3.10.9纯codec7项通过，见[85号](85-v42-validation-status.md)。新1459完整回归仍执行中，尚未取得最终计数/全SHA前不得称通过。

本次没有运行大型`status`的完整源码/预处理重验，也没有运行大型`saved_run/review/Packet`或大型Diff恢复。那些入口剩余的初始整图恢复仍需迁移，R2c正式dirty/CMake/恢复及R4–R7仍有代码缺口；物理32GiB/独立PC/真实模型/UAT未验证。完整G4历史峰值也不由本次只读摘要关闭，最终完整包大小子门限的71.64935%实际PASS另见[84号](84-seed0-v13-complete-compact-retention.md)。`all_gates_passed=false`。
