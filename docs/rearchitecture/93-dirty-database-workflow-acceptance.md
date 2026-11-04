# 显式编译数据库：未提交版本对比、恢复与复核来源验收

> 后续干净提交daacc1f的完整1497项已完成1495PASS/2联网SKIP，包含本页功能及已有结果刷新消费者，见[95号最终回归](95-runtime-refresh-memory-acceptance.md)。以下较早“执行中”为当时阶段记录。Packet新读取器仍在内部验收，不将其未通过项并入本页PASS。

本阶段实现[91号合同](91-dirty-input-workflow-contract.md)的**显式编译数据库模式**，不是全部构建模式或整体重构完成。按用户顺序先交付必要功能，再进入[94号后续读取内存工作](94-later-consumer-memory-contract.md)。CMake/自动配置/补充扫描、模块/PCH/自带VFS/插件等未证明模式仍明确阻断，不回退到实时输入。

## 实现与证据

| 实现 | 文件 | 实测 / 结果 |
|---|---|---|
| HEAD/index/工作字节、目录和完整实际编译输入自动固定 | `dirty_inputs.py`、`working_snapshot.py`、`working_compiler_view.py` | 包括暂存和未暂存差异、被消费的忽略/未跟踪头、重命名/删除、完整SDK命名空间、Git/Clang/编译器、配置/DB/RSP及外部闭包；真实SDK盘点先导完整0/0见[92号](92-automatic-native-input-acceptance.md) |
| 普通CLI与受监督GUI共用V2固定描述 | `scan_persistence.py`、`workspace.py`、`cli.py`、Studio `task_worker/preflight/tasks/git_versions/server` | 预检查、实际Worker、缓存、Diff、独立全量和最终重验共用同一描述；真正安全停止/重试，原有效结果保留 |
| 原生检查点/后续配置与固定源码重放 | `frozen_scan.py`、`workflow.py` | 原源码/索引变化、损坏捕获拒绝；复核配置原路径或新任务副本可变模型选项，分析参数变化拒绝。新路径配置+真实刷新单项47.457秒PASS |
| 归档源码MCP、并行引用和独立收据 | `evidence_mcp.py`、`review_sources.py`、`review.py`、`review_contract.py` | 模型源码权限仅归档source工具；分页/UTF8/完整文本及原SHA；引用收集、线程和独立历史收据均读取同一归档，无实时回退。模拟执行器只证明协议/传输，不证明真实模型推理 |
| 既有Git控件与真实阶段计数 | `GitVersions.vue`、`App.vue`、`TaskCenter.vue`及构建资产 | 不改冻结导航/布局；明确真实HEAD、方向、未提交覆盖、数据库支持边界；盘点/预检查不冒充TU提取，未知分母不造百分比 |
| 专项回归 | `test_dirty_inputs/test_frozen_dirty_diff/test_frozen_parent_inputs/test_git_versions/test_build_preflight/test_review_sources/test_evidence_mcp/test_review_integrity/test_review_contract` | 冻结v47的67项全部PASS，400.390秒；额外新路径配置单项PASS与67项有重叠，不相加。此前40项全部PASS，145.638秒，亦有重叠 |

v47源清单：父提交`68793f3edbae00af17f7764ccfdeec8342eac6ff`加记录的工作区覆盖，3724文件，清单SHA256 `10668594d4cad176fb23ac67fbffd93126b7993877e44492f9fcfbb779509e40`。原目录`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/frozen-engine-studio-v47`；后续验收脚本修正有独立文件，未改冻结产品源码。

## 真实浏览器成功流程：明确为自建原生测试工程

[v3完整收据](acceptance/dirty-workflow-controlled-v47-v3.json)，耗时140.766秒。4个实际Clang TU，真实ARM参数；四步保存、Git预览、安全停止、重试、打开完整变量详情、原生检查点刷新、完整包独立导入全部实际执行。实际工作头为值2、暂存头为值1，归档SHA匹配值2，另一未跟踪头实际被消费；原始测试输入/私有Git/冻结引擎前后差异为空。完整Diff与独立全量facts逐字段差异0；原算法重新计算的base→current影响结果差异0；`verify_against_full`实际无缓存重新提取4TU，分类/语义差异均0。没有页面异常或外部请求。

截图：[版本/未提交](ui/screenshots/dirty-inputs-v47-v3/01-real-git-working-preview.png)、[实际任务](ui/screenshots/dirty-inputs-v47-v3/02-real-capture-progress.png)、[加载完成的真实变量详情](ui/screenshots/dirty-inputs-v47-v3/03-real-diff-workbench.png)。v2较早[收据](acceptance/dirty-workflow-controlled-v47-v2.json)和加载中截图保留；v3增加等待真实列表与详情断言，不能用v2加载中截图证明详情完成。

此工程在收据中标为`CONTROLLED_NATIVE_FIXTURE_NOT_G2`。它证明GUI/业务链路，**不替代G2真实大型工程或原始F030同输入验收**。

### 已修复真实Diff详情的结论裁切

v3截图仍在详情请求期间拍摄；随后等待全部请求结束的独立复查发现：1366×768时既有摘要区高85px、内容94px，结论末行底部437.172超出容器底432.812。不能把DOM存在当成完整可见。现仅调整既有摘要区的flex收缩与高度上限，保留布局和配色；`npm run build`通过。

[最终实际浏览器收据](acceptance/dirty-detail-layout-current-v1.json)覆盖1366×768、1600×900、1920×1080及浏览器1.25/1.5/2倍采样：六组均等待加载结束后断言整句结论处于摘要区内、四个确认按钮在视口内、无横向溢出、无页面异常/外部请求、原authority SHA不变。摘要实际94px，结论底437.172位于容器底441.172以内。[修复后1366截图](ui/screenshots/dirty-detail-layout-current-v1/diff-detail-1366-768-1.png)。这是在v47真实结果上的当前前端修复验收，不能标为原v47资产；浏览器采样仍不等于物理Windows DPI/UAT。

## 获准真实F030：门禁失败保留，未改判为成功

[原成功流程控制器FAIL收据](acceptance/dirty-workflow-f030-v47-v1-failed.json)保留，耗时497.844秒。已真实完成配置保存、预览、停止/重试及SDK/编译预检查；随后基准完整分析发现既有2 PARTIAL，按原规则报“基准版本存在解析失败/部分解析，不能将缺失事实当作无变化”，没有发布新有效归档。关闭`verify_against_full`也不能取消基准完整性门禁。

[独立反例复验收据](acceptance/dirty-workflow-f030-v47-v1-negative.json)再次完整核对1717个固定输入及原Git/索引/目录，原有效authority深校验通过、失败scan无manifest、3724冻结源文件无变化。该反例的“正确拒绝”通过，**原始F030的完整Diff成功验收仍未通过**。真实[HEAD及状态截图](ui/screenshots/dirty-inputs-v47/04-f030-head-and-counts.png)。没有删失败TU、改naked函数、取消门禁或把PARTIAL冒充PARSED。

v46真实流程还发现自动清单漏了Git可执行文件；原产品安全拒绝，失败目录保留。已补Git及外部闭包输入，并以实际dirty预检查专项重验。只读属性复制、STOP_REQUESTED等待、测试种子version及观察器数据根/scan_id等控制器失败亦保留在各原始工作目录，未覆盖失败收据。

## 复现与仍未完成

```powershell
py -3.10 -B -X utf8 -m unittest tests.test_dirty_inputs tests.test_frozen_dirty_diff tests.test_frozen_parent_inputs tests.test_git_versions tests.test_build_preflight tests.test_review_sources tests.test_evidence_mcp tests.test_review_integrity tests.test_review_contract -q
py -3.10 -B -X utf8 scripts/validate_dirty_workflow_ui.py --config <已获准的完整可解析显式数据库配置> --work <全新独立目录>
# 自建输入必须追加 --controlled-fixture，不计G2。
```

未完成：CMake未提交构建等价、真实完整F030 Diff成功、INAV新链路大型Diff/恢复/复核、dirty旧绝对视图搬迁后的重放。整根复制后归档查看仍可用，但没有重定位证明时不能宣称旧dirty检查点可重新证明。当前完整回归v46仍执行中；v44的1480PASS/2SKIP只覆盖前两项，不冒充本阶段回归。最新封存Portable仍v37，未包含本阶段。其他G2工程用户延期，物理32GB/第二PC/干净离线/原生DPI/联网OpenCode/UAT继续NOT_VERIFIED。完整重构、G1–G8未宣告通过。
