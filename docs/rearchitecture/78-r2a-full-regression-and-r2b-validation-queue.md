# R2a统一回归实际结束；R2b新源码整体验证排队

2026-11-04。R2a冻结提交`4967b7dfdcd6a80e22f267af5f8fd20f809a8e4c`的统一回归已经实际完成：**1430项、1428PASS/2联网opt-in SKIP，2161.818s**，冻结源和独立测试副本全部SHA0变化；[完整收据](evidence/full-regression-studio-v38.json)。随后真实原路径/原配置F0304TU再次扫描，2PARSED/2PARTIAL、INCOMPLETE保持，原e69全字段有序有类型事实和既有规范化报告差异0/0，原输入及引擎不变；[原生对照](evidence/native-exact-f030-v38-v1.json)。它们对应R2a，不冒充后续R2b完整回归。

R2b源码已提交推送为`35883edff4c2402b480778f3620c57ba091eaab3`，后续纯v37封存文档提交`0aa9363629a1b67b6eed4d04eafd1c51b2eca990`也已推送并核对远端。新冻结v39绑定后者，3631文件，清单SHA **`28d310087dda7463f09d7a6167f378920f65b3a80fc8994935169ca7297f89f9`**。新1439完整回归正在独立副本执行，之后才进行原路径F030对照，当前**NOT_VERIFIED**，不能据65专项或旧1430结果写成新1439已通过；[观察收据](evidence/frozen-v39-validation-observation-v1.json)。

| 实施 / 门禁 | 当前实证 | 状态 |
|---|---|---|
| R1多核固定归档输入、三步界面、受控任务及核心表单 | 65专项、原e69完整0/0、v37/1423完整及23组183包内断言、31700文件SHA、130运行时匹配 | PASS_SCOPED，[阶段70](70-pinned-multicore-workflow-acceptance.md)/[阶段77](77-frozen-v37-acceptance.md) |
| R2a编译Worker固定视图 | 56专项、修正编排后冻结118全部通过、原生独立副本4TU/8进程0/0、1430完整及原路径F0300/0 | PASS_SCOPED，[阶段72](72-frozen-compiler-worker-acceptance.md) |
| R2b同一身份的父读取/单文件元数据/目录证明与恢复拒绝 | 最终65专项、独立副本真实8Worker+父读取384.703s、完整0/0，原输入不变 | PASS_SCOPED，[阶段74](74-frozen-parent-input-acceptance.md) |
| R2b新统一1439/原路径对照 | 精确3631源文件已冻结，独立测试副本执行中 | NOT_VERIFIED，不能封为最终候选 |
| R2c正式dirty/构建-Diff-缓存-恢复 | 调用点/配置摘要/时序/模式证明缺口已逐项审计；正式门禁保留 | NOT_IMPLEMENTED_FULL_PATH，[阶段76](76-dirty-production-integration-audit.md) |
| R3/R4/R5/R6/R7 | 全消费者与大型恢复、证明不变继承、整根搬迁、全故障/UAT和总门禁仍有代码或验收缺口 | BLOCKED_COMPLETE_REFACTOR，[方案68](68-remaining-refactor-execution-plan.md) |
| 新大型writer64/v13 | 独立原生388TU/4123输入已结束、完整事实/报告0/0；完整包/保留测量继续，运行15.404h | PASS语义子范围，其他NOT_VERIFIED，[阶段75](75-seed0-v13-native-and-comparison-progress.md) |
| 外部真实验收 | 其他G2输入用户延期；物理32GiB、第二/干净离线PC、原生DPI、联网模型、工程师盲测未开展 | NOT_VERIFIED / USER_DEFERRED |

新控制器为`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/run-full-and-native-v39-v2.py`，独立测试源在同目录的`frozen-tests-studio-v39`，实时队列为`full-and-native-v39-v2-queue.json`，结束回归收据为`full-regression-studio-v39.json`，原生收据为`native-exact-f030-v39-v1/acceptance.json`。控制器拒绝覆盖既有路径；不要重复启动相同实验。完整源及测试文件全SHA在前后复核。当前观察收据不在结束后覆盖，后续另发实际验收。

本轮真实可打开的软件为[阶段77](77-frozen-v37-acceptance.md)的v37：`H:/ECRAStudio-build-20261104-studio-v37/ECRA-Portable/ECRA.cmd`，ZIP SHA `96826c586243dc648c726ba5495a884434ba650efc1f4634e0e778312d65bb89`。软件绑定R1/7066dea，不能说它包含R2a/b新内部接口。实际截图见`ui/screenshots/portable-v37/`；失败记录和修复验证保留，自动化操作通过不等于工程师满意度。`all_gates_passed=false`，完整重构没有交付完成。
