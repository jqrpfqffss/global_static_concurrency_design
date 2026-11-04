# v41源码实际验收与尚未关闭门禁

2026-11-04。运行代码已提交并正常推送到`optimize_ccc`，代码提交`74ebb5f5e369296370bc8bc9a12dddcd8b904768`，远端SHA实际一致；没有reset/强推。它包含[80号完整扫描](80-frozen-full-scan-integration.md)和[81号内部dirty Diff](81-frozen-dirty-diff-integration.md)，不是正式dirty入口已开放。**完整重构未完成，all_gates_passed=false。**

精确冻结源3665文件，清单SHA `77335c0b15366bba6329c799aefde2f33e897ce12745d0a48a005c170d95b1d5`；运行源与独立测试副本的所有文件SHA前后差异0。此次没有把上一轮失败计数或旧完整回归当新结果。

| 实现 / 文件 | 测试与实际结果 | 状态 / 证据 |
|---|---|---|
| `cli.py/frozen_scan.py`：完整及内部HEAD工作区Diff的固定Worker、父读取和发布门禁 | 冻结23项联合检查，23 PASS / 0 SKIP，354.165秒；包含4 dirty Diff、5完整扫描、10父读取和4有界Worker检查 | PASS_SCOPED：[完整收据](evidence/frozen-related-studio-v41.json) |
| `git_diff.py`：基准前后pin重验、uncached全量也绑定视图、捕获Git生成patch | 基准之后index变化阻断；原源码只在patch读取时改变再恢复，patch仍与捕获Git生成的完整字节相同；冷/热/实际损坏缓存全事实核对和每轮uncached PASSED | PASS_SCOPED；[阶段81及原FAIL](81-frozen-dirty-diff-integration.md) |
| `compilation.py/working_compiler_view.py`：固定准备阶段命名空间 | 真实新增未编译源后仍枚举原捕获目录/文件，使用原逻辑路径，保留目录剪枝、所有原参数和Partial/Failed语义 | PASS_SCOPED；同23项 |
| 当前代码、原路径原配置F030黄金对照 | 4 TU / 2 PARSED / 2 PARTIAL，完整有序有类型事实、既有规范化报告0/0；CLI27.297秒、含校验29.672秒；原输入与引擎SHA不变 | PASS_SCOPED：[原路径收据](evidence/native-exact-f030-v41-v1.json) |
| 获准F030独立副本完整普通/冻结执行 | 绑定上一批`f2dca32`；4 TU、1714固定文件，完整事实/报告0/0和完整包严格独立导入0/0；原始/私有Git/SDK/build/引擎全SHA不变，736.750秒 | PASS_SCOPED：[收据](evidence/frozen-full-approved-f030-v1.json)；不改标为本批代码/真实dirty Diff |
| v40完整1444回归及原路径F030 | 绑定`f2dca32`，1442 PASS / 2真实联网opt-in SKIP，2195.600秒；3651冻结源及独立副本文件全部SHA差异0；随后原路径F030也已完整事实/报告0/0，原输入/引擎不变 | PASS_SCOPED：[完整回归](evidence/full-regression-studio-v40.json)、[随后黄金对照](evidence/native-exact-f030-v40-v1.json) |
| 本批v41完整1449回归 | v40实际成功后已启动；预计2个真实联网opt-in跳过，最终必须按实际计数验收，不能借用旧1444充数 | NOT_VERIFIED：[新观察](evidence/source-v41-gates-observation-v2.json)；[最初排队观察](evidence/source-v41-gates-observation-v1.json)保留 |
| INAV v13完整标准包 | 完整语义0/0、标准完整包严格导入、原库保护通过；含标准DEFLATE包的稳定保留策略降低69.8648%，没有达到70% | 语义/包PASS，70% **FAIL**：[阶段79](79-r2b-regression-and-v13-package-final.md) |
| INAV v13无损compact容器 | 3,157,552,641B；每个解压载荷/完整manifest字节和SHA与原包一致，原完整包保留；严格独立导入及最终保留测量仍在执行 | 仅编码PASS：[收据](evidence/inav-seed0-v13-compact-encoding-v1.json)；导入/70%/完整G4仍待验 |

compact包SHA为`f3ad33322b79a28e4ca74634137be08f8d2bd65c10f8c50f58e6200585985042`。本次重新编码不是新原生扫描，不改变[79号](79-r2b-regression-and-v13-package-final.md)的真实三组时间/内存/磁盘峰值，也不能提前把69.8648%改成通过。独立512MiB读取实验已实际结束、完整0/0，但69103.422秒不支持宣称提速。

## 可复验命令与软件

保持运行源稳定，在PowerShell执行本次23项检查（这些是开发验收，不是普通用户流程）：

```powershell
py -3.10 -B -X utf8 -c "import sys,unittest;sys.path.insert(0,'tests');unittest.main(module=None)" tests.test_frozen_dirty_diff tests.test_frozen_scan_pipeline tests.test_frozen_parent_inputs tests.test_bounded_extraction -v
```

完整回归命令为`py -3.10 -B -X utf8 -m unittest discover -s tests -v`，应在独立冻结副本执行并核对前后完整SHA。大型完整比较使用既有`py -3.10 -B -X utf8 scripts/compare_native_graphs.py --help`所列接口，不增删规范化字段。获准源的独立副本控制器为`py -3.10 -B -X utf8 scripts/validate_frozen_scan_pipeline.py --help`，工作目录必须新建且在固件外；不要覆盖上次成功或失败的结果。

正在运行的精确控制器/收据位于`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/`：

- `run-full-and-native-v40-v1.py` / `full-and-native-v40-v1-queue.json`；最终`full-regression-studio-v40.json`。
- `run-full-regression-studio-v41-queue.py` / `full-regression-studio-v41-queue.json`；最终`full-regression-studio-v41.json`。
- `inav-v13-compact-import-retention-v1/execution.json`；严格导入后才执行稳定保留测量。

普通用户最新完整封存软件仍为[v37](77-frozen-v37-acceptance.md)：`H:/ECRAStudio-build-20261104-studio-v37/ECRA-Portable/ECRA.cmd`，ZIP SHA `96826c586243dc648c726ba5495a884434ba650efc1f4634e0e778312d65bb89`。真实截图在`ui/screenshots/portable-v37/`。它绑定`7066dea`，不能宣称包含本批内部接口；本批没有任意改动页面设计，也没有用模拟界面替代功能。

## 仍须实际完成

R2c还需要真实构建模式的捕获时点/工具/Git生成语义、原工作区与冻结输入的完整真实Diff、只读/停止/故障、恢复及正式UI操作，才能逐模式开放普通入口；目前`formal_workspace`仍拒绝未提交模式，冻结检查点仍明确拒绝恢复。F030冻结执行474.375秒对照普通26.891秒，验证开销很大，性能目标未交付。

R3全消费者/大型Diff和恢复、R4证明不变的确认继承、R5整数据根迁移、R6全故障/UAT、R7统一验收依然有代码或验证缺口，按[68号方案](68-remaining-refactor-execution-plan.md)继续。其他G2真实工程用户已延期，物理32GiB、独立第二PC/干净离线PC、原生DPI、真实联网模型和工程师盲测保持NOT_VERIFIED，不借用fixture或自动化通过代替。U01–U24/G1–G8均不能宣称全部通过。
