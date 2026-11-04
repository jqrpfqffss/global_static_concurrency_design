# R1：固定多核归档输入与真实用户操作验收

2026-11-04。在 `190b8baa1c689c4ac6f258f5837a2d8b740d33cd`（已推送 `origin/optimize_ccc`）之后实施。对应原任务 H1/H2/H3/H4/H5、§1/6/7.4 的已有多核功能；执行顺序见[剩余重构方案](68-remaining-refactor-execution-plan.md)。本页不是完整重构完成声明。

## 实现与证据

原发布层以工程级 `latest-scan.json` 定位各配置结果，同一工程的两个 profile 会指向同一最新扫描。现在 CLI 可显式传 `--scan 别名=scan_id`、`--profile-id 别名=profile_id`；完整输入集合必须一致，不允许缺项退回 latest。隐式选择两个相同目录会拒绝。固定输入须同时通过工程/profile/binding、归档配置原始 SHA、manifest/scan.db/ELF 全 SHA 和深完整性检查，发布前复核；变化时新结果不发布。

归档选择器只读取所选扫描内 gzip CAS 的原始配置，流式限额解压并核对完整字节，不以预览文本或后来修改的 profile 替代。原配置不改。上传 ELF 流式写独立数据根，预检只声明固定选择；ELF 全解析与静态图完整校验在已有预算/Job/OwnedProcess 受控 worker 中执行。复用任务中心的停止、资源监督、日志和失败重试；重试明确从固定输入重新校验，不冒充 TU 恢复。结果仍是链接地址派生合并，保留原有 INCOMPLETE/未知语义。

普通界面按[冻结交互合同](ui/37-multicore-existing-scans-contract.md)落地：在“数据与共享”页点击“合并已有多核结果”，依次选择确切归档批次与 ELF、填写真实共享区域与预算、核对后提交。历史按 50 项显式翻页；名称、core、target、profile/scan 身份直接显示，原文和完整 SHA 可展开。错误新 ELF 会立即清掉旧上传身份和计划，不能误用旧文件。向导第 2 步增加可选核心标识，空值保持旧配置语义；高级 YAML、未知字段、注释及原备份机制保持。

| 范围 | 文件 | 实测结果 / 证据 | 状态 |
|---|---|---|---|
| 显式选择、陈旧 latest、错 profile/配置/清单、发布前变化、CLI 重复参数 | `ecra/multicore.py`；`tests/test_multicore_pinned_inputs.py` | 7 个针对性反例；组合器 `_assemble` / `elf_objects` AST 与冻结 v36 一致 | PASS |
| 上传/计划、真实 owned worker、失败后真实重试、共享预算、压缩对象读取限额、旧人工不变 | `ecra/studio/multicore_inputs.py`、`server.py`、`tasks.py`、`task_worker.py`；`tests/test_multicore_workflow.py` | 6 个完整 API/worker 场景；不是 mock 页面或 fake worker | PASS |
| 核心表单、任务/构建/资源/现有多核相关回归 | `profile_forms.py`、`tests/test_profile_forms.py` 及相关既有测试 | 65/65，43.146s；精确日志 SHA 见[源码验收收据](evidence/multicore-workflow-source-acceptance-v1.json) | PASS |
| 同一获准 F030 的两个独立真实扫描 | 不修改获准源工程、编译命令和 Cortex-M0 目标；私有别名 F030_A/B | 各 4TU，2 PARSED / 2 PARTIAL；59.969s；45 项源/配置/DB/ELF 输入哈希/大小/mtime 及 102 模块无改动；[原生产者](evidence/multicore-approved-f030-native-inputs-v1.json) | PASS，非真实双核 G2 |
| 原 e69 组合器对照 | 真实旧进程 + 原比较器；只外移旧对照的 `analysis.output`，其余有效配置逐项核对 | 8.593s；完整事实 SHA `2afe91f3835ac989138e656dae3acdc73d026f52b033c111703297014be3f8c4`，规范化报告 SHA `18ef60a4efe767607068a801ac491783f3c7afa61140b0830bd238425d99c134`；差异 0/0；[完整收据](evidence/multicore-workflow-original-e69-equivalence-v1.json) | PASS，限该真实输入 |
| 三步真实 Chrome 操作 | `studio/src/MulticoreCenter.vue`、`App.vue`、`TaskCenter.vue`；`scripts/validate_multicore_workflow_ui.py` | 8/8，83.844s：真实文件选择/上传、缺区域失败、旧配置原文、错误重选、精确输入 worker、真实证据/确认/刷新/原生下载/严格独立导入；固件/ELF/原输入人工/静态/运行时不变，无页异常或外网请求；[收据](evidence/multicore-workflow-ui-v1.json) | PASS，源码运行 |
| 1366×768 / 1600×900 核对页 | DOM 实际提交按钮边界；没有固定高度模拟截图 | 按钮 y=623.6875 / 624.546875、高=39.6875，均位于实际视口；[真实核对页](ui/screenshots/multicore-workflow-v1/01-real-archived-config-and-explicit-scan-plan.png) | PASS，非原生 DPI/UAT |
| 四步表单真实核心往返 | `scripts/validate_profile_roundtrip.py --core-acceptance` | 8/8：高级配置/回退/修改/原备份/恢复/保存/刷新/新建默认；[收据](evidence/multicore-core-profile-ui-v1.json) | PASS |
| 前端构建与冻结合同 | `npm --prefix studio run build`；`scripts/validate_ui_contract.py` | vue-tsc + Vite PASS；静态合同 12/12；[合同收据](evidence/multicore-workflow-static-ui-v1.json) | PASS |
| 统一新源码完整回归 / Portable | 独立冻结副本；预期发现 1423 项 | 本阶段专项通过尚不能替代全套重跑与新包内真实操作 | NOT_VERIFIED，待下一候选 |

先前完整长表单实际操作 v1/v2 均 8/8，但目视发现提交过深；故先修订合同再实现三步。最终以三步 v3 操作的源码 SHA、真实任务/归档及截图为准。完整脚本和日志路径/摘要见源码收据，不把旧布局成功记录移作新布局验收。

准备 v3 数据副本时，控制器曾误将 SQLite 导入前后的物理 SHA 一致当作必要条件，因此中断，未执行 GUI。保留[该失败](evidence/multicore-input-copy-controller-failure-v1.json)及原驱动；新私有 v4 输入通过原比较器完整事实/报告、绑定身份和全部人工事件核验，原输入的物理 SHA 仍核对不变（[A](evidence/multicore-approved-f030-copy-comparison-a-v1.json)、[B](evidence/multicore-approved-f030-copy-comparison-b-v1.json)）。另一次专项命令误写不存在的测试模块，命令错误记录保留，修正后完整 65 项通过。

## 重复执行命令

```powershell
py -3.10 -B -X utf8 -m unittest tests.test_multicore_workflow tests.test_multicore_pinned_inputs tests.test_multicore_publication tests.test_multicore tests.test_profile_forms tests.test_studio_api tests.test_build_preflight tests.test_owned_process tests.test_studio_resource_policy -v
npm --prefix studio run build
py -3.10 -B -X utf8 scripts/validate_ui_contract.py --output <新收据路径>
py -3.10 -B -X utf8 scripts/validate_multicore_workflow_ui.py --case <全新独立输入副本> --work <全新工作目录> --evidence <全新证据目录>
py -3.10 -B -X utf8 scripts/validate_profile_roundtrip.py --help
```

GUI 输入必须来自获准原生生产者或完整标准包的独立严格导入，不能清空旧人工记录后重跑。`--engine/--python` 可在冻结 Portable 中原样验证；新包内验证尚待执行。旧已封存 v36 入口、ZIP/SHA 见[上一阶段](69-frozen-v36-acceptance.md)，不能将其写为本次新功能的分发包。

## 仍未关闭

R1 的固定输入及普通用户派生流程已实现并通过上述范围验收；真实独立双核仍按用户决定延期。R2 正式 dirty 隔离、R3 全消费者与大型 Diff/恢复、R4 不变确认继承、R5 整体数据根搬迁、R6 全故障/工程师 UAT、R7 全门禁仍按方案推进。大型固定 seed0 的 64MiB writer v13 已结束，完整原事实/报告 0/0，但归档及最终保留峰值测量未全部完成；约 55454.5s 的共享机械盘实测不能称性能达标，也不能标作当前 R1 原生扫描。H1–H6/G1–G8/Phase1–5 总体仍 BLOCKED，`all_gates_passed=false`。
