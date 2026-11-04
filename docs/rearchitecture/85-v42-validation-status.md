# v42源码与验收状态：明确区分完成、运行中及代码缺口

> 后续大型报告摘要已经实际结束，原摘要完全相同、数据库/state/manifest/冻结源SHA不变，2GiB Job最终峰值34,557,952B，见[86号](86-inav-native-report-digest-acceptance.md)。下方“执行中”与观察收据保留原时间，不冒充完整status/复核/Packet已迁移；1459全套仍待最终结果。

代码提交`5c4281bf1245c23885329990864cd845e04ee87b`已正常推送到`optimize_ccc`并核对远端。随后精确冻结v42：**3688文件**，完整清单SHA **`a946b562162f9fba28e9ac1cebe4b223765ce41723c111ca064f2972f3762033`**。本页是后续验收记录，不改写旧收据，完整重构仍未完成。

| 交付 / 实现 | 实际验证 | 判定 |
|---|---|---|
| R2c内部冻结完整扫描 / dirty HEAD Diff | [80号](80-frozen-full-scan-integration.md)、[81号](81-frozen-dirty-diff-integration.md)代码；冻结74ebb5f完整1449项1447PASS/2联网SKIP，2281.791秒；23项联合及原路径黄金0/0 | PASS_SCOPED，正式dirty/CMake/恢复仍未开放 |
| R3a `native_consumers.py/workflow.py` 状态/后置校验 | 最终38项101.804秒PASS，含10新消费者检查、真实192MiB Job、大共享DAG、1203完整候选、源码变化拒绝与旧固件不写；实际既有原路径F030检查点1.922秒重验通过 | PASS_SCOPED：[83号](83-native-status-and-checkpoint-consumer.md) |
| 当前精确代码的原路径原配置F030新扫描 | 完整有序有类型事实、既有规范化报告0/0；2 PARSED / 2 PARTIAL不变，原输入及引擎SHA差异0 | PASS_SCOPED：[本批收据](evidence/native-exact-f030-v42-v1.json) |
| 包内Python3.10.9兼容 | 实际v37的runtime执行新冻结42源码中7项纯codec/状态身份/junction检查，7PASS，61.670秒；两项受检runtime文件SHA不变 | PASS_SCOPED：[运行时收据](evidence/native-consumers-portable-runtime-v1.json)；**不是已更新Portable** |
| 新1459全套 | 独立冻结副本已启动，必须以最终统计、2个预期联网opt-in跳过及完整前后SHA验收 | NOT_VERIFIED，执行中 |
| INAV v13真实报告完整摘要 | 冻结42代码，2GiB OwnedProcess；原DB完整SHA前后、原ECRA_MERKLE_V1摘要、禁完整重建及源代码SHA均须通过 | NOT_VERIFIED，执行中；过程内存不是最终峰值 |
| INAV v13完整紧凑包 | 全载荷字节/manifest与原包相同、实际包内严格导入通过；完整明示保留策略47,665,101,856B → 13,513,363,864B，降低71.64935489947146% | **最终大小子门限PASS**：[84号](84-seed0-v13-complete-compact-retention.md)；完整G4未关闭 |

运行中快照：[source-v42-validation-observation-v1.json](evidence/source-v42-validation-observation-v1.json)。该观察收据不在任务结束后覆盖；完成时另发实际结果。两个长任务不得在结束前称通过，也不能把旧1449结果当新1459。

所有控制器/结果位于`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/`：

- `run-full-regression-studio-v42.py`，日志`full-regression-studio-v42.log`，最终`full-regression-studio-v42.json`，独立测试副本`frozen-tests-studio-v42`。
- `run-native-exact-f030-v42-v1.py`，结果`native-exact-f030-v42-v1/acceptance.json`，已实际结束。
- `run-inav-v13-native-report-digest-v1.py`，结果/阶段/完整资源序列在`inav-v13-native-report-digest-v1/`。它只验证已有完整报告摘要，不冒充原生新扫描、完整saved_run或完整消费者迁移。

可复验38项命令：

```powershell
py -3.10 -B -X utf8 -c "import sys,unittest;sys.path.insert(0,'tests');unittest.main(module=None)" tests.test_native_consumers tests.test_canonical_scan tests.test_review_integrity tests.test_large_report_scope -v
```

**仍需代码完成**：R2c真实外置构建/完整模式证明、正式dirty与恢复/UI；R3的saved_run初始全图、源码变化回退、Packet、大型Diff/恢复；R4证明不变后的人工确认继承；R5整根一致迁移及中断恢复；R6全故障/UAT；R7统一验收。**外部待验**：用户延期的其他G2工程、物理32GiB、独立/干净离线PC、原生DPI、真实联网模型和工程师盲测。两类不能混淆为“只剩环境问题”。按[68号方案](68-remaining-refactor-execution-plan.md)继续，H1–H6/U01–U24/G1–G8没有全部关闭。

最新版完整封存软件仍是[v37](77-frozen-v37-acceptance.md)：`H:/ECRAStudio-build-20261104-studio-v37/ECRA-Portable/ECRA.cmd`，ZIP SHA `96826c586243dc648c726ba5495a884434ba650efc1f4634e0e778312d65bb89`。真实截图`ui/screenshots/portable-v37/`。本轮保持既有界面合同，没有任意重画页面；当前源码未重新封装为新的全验Portable。完整大工程的原始/冷v12/冷v13内存、扫描输出采样分配峰值、时间及0/0对照见[79号](79-r2b-regression-and-v13-package-final.md)，耗时不能称提速，全政策历史峰值/物理机仍待验。`all_gates_passed=false`。
