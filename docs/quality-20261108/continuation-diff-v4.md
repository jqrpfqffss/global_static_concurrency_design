# 最终v4真实CDC差异、缓存与恢复验收

状态持续更新，运行中或未开始不计通过。前轮及失败记录完整保留于 [continuation-diff.md](continuation-diff.md)。本轮证据独立放在 `output/quality-20261108/continuation/diff-final-v4/`。

## 冻结输入与真实入口

- 引擎：`H:/ECRA-quality-20261108/continuation-final-engine-v4`，摘要 `63a5cff7e9babcf0a4982726f68ca8390ad5f840b92d31d41e511a859d857710`；只读使用，不修改生产代码。
- 新数据/源码根：`H:/ECRA-quality-20261108/continuation-diff-v4`。source-cdc来自本轮已有真实CDC验收仓库的无hardlink本地clone，移除remote；上游STM32CubeF4 v1.28.3 / `94cae6e83f00e276a11957e7833c01ac3d0bd7af`、许可证和来源文件均保留。原工程、原Git及人工记录不写。
- 独立基准A `3dd83d1ee84aaa51b0ca6e0e0d555b8ca5a1653f`（quality-protected-base）；当前B `b2da0c5fdfac7349b0569deb4f5765dbaf1e3c34`。同一个真实工程保留39个C TU、启动ASM、HAL/CMSIS/USB栈，没有用微型工程替代。
- Windows CPython 3.10.11显式`-B`、`PYTHONHASHSEED=0`，候选源码配原封存包CMake/GCC/Ninja；实际libclang由主机Python安装目录加载，准确路径与输入SHA见`runtime-tools.json`及产品`input_manifest.json`。不是重打包后最终ZIP的双击入口测试，后者由交付职责单独验证。
- 固定提交配置SHA `47964ae4155d15a61f4ce319040f015acad13d04a2062e73e7e6d7bfb681b559`；工作字节配置SHA `1e2833b9a41b829047b8a81c8364b9810982d4525c3d674e9507c3f9dacde54f`。
- 两配置都用正式Ninja外置构建、真实CMake CDB、`auto_system_includes:true`、完整构建/链接及`verify_against_full:true`。仅前者显式`include_uncommitted:false`，后者true；不会为排除失败静默切换该策略。

真实执行由证据目录的 `run_acceptance.py` 串行控制，调用 `run_phase.py <phase> --scenario fixed|dirty`，实际产品命令为固定Python绝对路径、候选`run_ecra.py --config <对应配置> --no-review --scan-mode diff`。每阶段保存完整argv、配置SHA、引擎摘要、原始产品退出码、日志、独立全量比较、目标证据及SQLite校验。`controller-status.json`与`controller-events.jsonl`仅为外部QA进度，不是产品恢复状态。

初始冻结651个引擎内容文件、568个源码文件（SHA/大小/mtime）及Git索引；冷/暖扫描后复查不变。`setup.json`、`source-freeze-inventory.json`、`engine-freeze-inventory.json`和逐阶段`*-freeze.json`保留明细。

## 预期与当前覆盖

| 阶段 | 独立预期及门禁 | 状态 |
|---|---|---|
| 固定提交cold | 基准计数器完整PRIMASK窗口SAFE；B移除屏蔽后SUSPECT，差异纳入；基准39+当前39+独立full39；分类/完整语义不一致0 | 已通过限定合同：2077.891s，产品原退出2/INCOMPLETE；245变量，独立full分类/语义mismatch各0，归档valid/SQLite ok，源码/索引/引擎/配置均未变 |
| 同根同配置warm | 相同源/配置/引擎；完整基准authority与summary有效复用；当前39 TU缓存全命中；独立full仍真实重提取39 | 已通过限定合同：1185.188s，产品原退出2/INCOMPLETE；首次warm完整基准summary hit/authority SHA相同，当前39 hit/0 extracted/0 corrupt；独立full39 TU/245变量mismatch各0 |
| 全事实/风险对照 | 全部facts关系、每条变量/完整finding字段及顺序作无损Merkle比较；只独立列明impact中的归档路径/SHA；基准authority SHA另须相同 | 已通过：55个facts顶级关系、每条变量与finding、impact语义、风险摘要与selected IDs均一致，未增加排除字段 |
| 真实过期恢复 | 原始B可恢复；按固定提交契约忽略真实未提交头宏；本隔离Git提交头宏后旧结果应拒绝恢复/report；旧DB字节保留 | 已通过：真实CLI clean/忽略未提交均resumable true；本轮clone实际提交后false，report原退出3拒绝，旧DB SHA不变 |
| Guarded工作字节 | 明确true策略，实际头宏变更、C+ASM受监督两次真实构建、原始/封存输入等价；独立full核对及最终原输入验证；数据不注入 | 首次已失败/后续未完成：45.484s，原退出3；捕获568工作文件后，首次CMake因目录变化通知拒绝。原策略、检查和现场均保留，具体事件来源调查中 |

预设whole-facts比较脚本 `compare_warm.py` 在结果出来前建立门禁：逐ordinal比较全部记录，不按symbol合并丢掉多finding；除了变量impact中的`base_facts_path`、`base_facts_sha256`、`base_summary_path`、`diff_patch_path`四个明确溯源字段，不忽略其他事实。基准SHA同时单独要求一致，且检查真实复用日志、summary hit、当前TU的39 hit/0提取/0损坏。任何差异均写明，不根据本次数字反向调整预期。

恢复步骤只修改本轮自己的Git clone与头文件，旧报告/数据库/队列不手工改写。Guarded阶段另用相同内核事件过滤器只读观察目录事件，保留首轮异常及重试边界；观察者不重置或放宽产品保护。未经完成的步骤不视为已具备产品恢复能力。

## cold已完成证据

`v4-fixed-cold-audit.json`记录正式归档`data-fixed/scans/aef9f9dfb3334f25ab0e7624b0847d3d/scan.db`。`c:@ecra_quality_diff_counter`的基准静态SAFE_PROVEN/保护EFFECTIVE，当前SUSPECT/保护UNRESOLVED，差异实际纳入；传播原因包含访问、构建语义、冲突、覆盖、保护、语义影响及静态分类变化。当前39 TU为0 hit/39 extracted/0 corrupt；独立full重新提取39 TU，245变量分类和完整语义mismatch均为0。`v4-fixed-cold-freeze.json`保存完成后的输入冻结复核。

产品状态仍为INCOMPLETE，206个候选/盲区复核项未因验收通过而丢弃。这里的“通过”仅指上述已执行合同与数据一致性，不代表245变量均安全或已完成人工复核。

## warm与完整基准复用已完成证据

`v4-fixed-warm-audit.json`记录`data-fixed/scans/22d0b545b69d488f8174a0c976e343e7/scan.db`。首次warm沿用相同根、配置、引擎、源码提交；实际刷新CMake并构建后，完整基准通过源码、预处理闭包及引擎校验，summary hit为true、corrupt为false。基准权威SHA与cold同为`b69f4c259ac103f5fa4d75cb3c85c88498ce383c9dc6a0c3c636516be5d7ff46`；不是仅TU缓存命中。

`warm-comparison.json`中全部门禁为true，55个facts顶级关系、逐ordinal完整变量/finding及impact语义的差异映射均为空，风险摘要与实际selected IDs均一致。当前TU缓存39 hit、0提取、0损坏，独立full仍真实重提取39 TU并核对245变量，分类/语义mismatch各0。`v4-fixed-warm-freeze.json`复核源码字节、mtime及索引、651引擎内容文件和配置均未变。

两正式归档的产品manifest为STATIC_VALIDATED、run_state为INCOMPLETE；原始native绑定标签UNVERIFIED不等于未执行发布后的静态完整性验收。产品在最终manifest发布前实际执行deep节点/投影校验及输入复核，归档中的`manifest.json`保留权威SHA和审计证书。本轮没有把INCOMPLETE改作COMPLETE。

## 真实过期恢复已完成证据

`v4-recovery-receipt.json`与对应status/report原始stdout/stderr记录65.328s的真实CLI操作。clean的B可恢复；头宏3u→7u未提交时，显式false策略仍可恢复，证明实际遵守固定提交契约。随后只在本轮clone真实提交3u→5u，生成HEAD`3c632672a3076998477e36e2e2db1bb126240aa5`；旧status返回resumable false并提示“Git引用或工作区快照已变化；差异结果失效，请重新扫描”，report原退出3拒绝，旧warm数据库SHA前后均为`35cac3cda858c6f0952cb21fcd850f3261e9cf875fbf82d074c630ed78f93d85`。

此后实际工作头宏5u→7u未提交，用独立true策略配置进行后续Guarded扫描。新的HEAD、索引、全部568源文件及mtime在dirty开始前再次冻结。未手改产品数据库、检查点、队列或恢复状态，也未改原始工程/Git。

## dirty首次真实失败及保留现场

`v4-dirty-execution.json`保留产品原退出3、45.484s与完整argv、固定配置SHA、HEAD及前后仅`M App/lab.h`的Git状态。产品成功捕获568工作文件，随后第一次受监督CMake配置因“CMake输入目录在固定期间发生变化（即使已恢复也不接受）”拒绝，串行控制器按原退出码3结束；没有自动重跑、改策略、过滤通知、重置watch或注入恢复状态。

`v4-dirty-kernel-events.json`独立内核观察记录唯一通知：观察开始epoch1794133454.261806，1794133455.382416收到action3/MODIFIED，路径`.git\\logs\\refs`；没有overflow/error。通知本身不说明是last-write、attribute还是security，也不识别写入者，不能据此认定应忽略`.git`。旧1b首次同类失败仍保留，但本轮新增了具体路径证据。

`v4-dirty-failure-retention.json`逐项复核568工作源码的SHA/大小/mtime，差异为空；产品capture.db为COMPLETE，捕获HEAD正确，当前索引、capture索引摘要与保存的original-index均为`6349a89f4a3bca895f3a7f75cc57257549ccf838fb02de9d720c1a1f4e5679ce`。外部控制器在内存持有的dirty前索引摘要未在失败前持久化，因此这里仅声称与产品捕获时一致，不伪造独立更早索引基线。

`v4-post-failure-freeze-and-archives.json`继续验证651引擎内容文件、两配置字节均未变；cold/warm正式数据库SHA仍与原audit和manifest相同，均STATIC_VALIDATED/source_reverification true/run_state INCOMPLETE。首次dirty失败没有损坏已完成的固定提交报告。Guarded两次完整构建、dirty独立full与最终发布尚未完成，不计通过。

后续已确认两个不同原因并准备独立最小修复，详见[Q207准入边界与只读Git记录](continuation-diff-q207.md)。此处v4失败状态不改成通过；新组合版须用其真实引擎字节单独复验。

原始CDC输入的566文件已在本轮重新逐项核对SHA、大小及mtime，差异与新增均为0；见`original-source-retained.json`。

这些原始耗时受同机并行任务影响，不用于宣称受控的性能提升。无联网OpenCode推理；原始用户数据与确认记录不写。
