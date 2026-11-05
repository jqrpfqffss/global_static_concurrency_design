# 冷读取器严格类型：当前阶段验收

实现提交`feceb2736dcd410feeef19e58f0fb74f86e76dd6`，在`optimize_ccc`直接执行并推送；未调用外部编码代理。实施前真实HEAD/工作区核对与首段见[110–111号](111-native-cold-diff-reader-stage.md)，类型差异的实际复现及修补合同见[112号](112-native-dictionary-key-type-contract.md)。没有改原摘要schema、缓存键、扫描策略、影响闭包或界面布局。本阶段不是完整重构完成声明。

| 阶段 | 实现的核心功能 | 变更文件 | 测试/场景ID | 结果 | 对应证据 |
|---|---|---|---|---|---|
| 原生冷基准 | 避免同时恢复完整facts/report；原函数/调用所需字段及逐对象完整散列字段按权威ordinal读取 | `ecra/native_diff_summary.py`、`ecra/git_diff.py` | 首次冷读、损坏重建、完整原摘要/原键、同名身份/构建根/CFG、重复/有序/类型、指针3种编码、私有隔离 | 实现及限定专项PASS；整轮Diff内存NOT_VERIFIED | [前阶段](111-native-cold-diff-reader-stage.md)、[17项](acceptance/native-cold-diff-reader-v71-focused.json) |
| 类型拒绝语义 | 避免SQLite TEXT亲和性放行原dict拒绝的非字符串引用；保留不可哈希键TypeError | 同读取器、`tests/test_native_diff_reader.py` | 1/true/1.0/null/list/dict；原算法逐项对照 | PASS | [17项完整日志](acceptance/native-cold-diff-reader-v71-focused.log)、[31函数AST不变](acceptance/native-reader-v71-algorithm-proof.json) |
| 实际原生Diff | 冷读/损坏重建禁止完整baseline load，CMake宏4→8、双版独立无缓存全量核对、断点TU缓存复验、新库发布及旧库/归档保留 | `tests/test_native_diff_summary_cache.py` | 真实2TU的8项，联合读取器9项 | 17项PASS/0跳过，268.636s | [最终收据](acceptance/native-cold-diff-reader-v71-focused.json) |
| 冻结及完整回归 | 干净feceb27冻结、独立测试副本全文件SHA复验；完整回归按版本串行执行 | 开发验收控制器 | 本版冻结源/专项副本各3925文件无差异；前版1533已1531PASS/2联网SKIP/0失败，3889.461s；本版1534接续执行 | 冻结专项PASS；本版完整回归NOT_VERIFIED | [前版完整收据](acceptance/full-regression-studio-v69-final.json)、[完整日志](acceptance/full-regression-studio-v69.log)；本版manifest SHA `a662801c4592a6fca1f997f7411b9cae6a2b7ff2456ac4022a89543ef28b4d04` |
| 原生F030/界面前证据 | 原43文件不变、完整事实/报告0差；真实Chrome两次扫描/复用/访问证据/标准包独立导入 | 冻结v69，修补前版本 | 实际F030；Chrome5组、33源文件/114 Python文件不变、258本地/0外部请求 | 前版限定PASS，未改标为v71复跑 | [F030](acceptance/native-reader-f030-v69.json)、[Chrome](acceptance/native-cold-diff-ui-v69.json)、[截图](ui/screenshots/native-cold-diff-v69/03-shared-evidence.png) |
| v70组装 | 目录及中文ZIP各27项工具链检查、144应用文件匹配；发现类型问题后不进入运行验收 | 独立v70组装器 | 等待控制器在启动任何运行命令前停止，旧目录/日志/队列全部保留 | 工具检查PASS；候选SUPERSEDED | [工具范围](acceptance/portable-v70-toolchain-only.json)、[未推广记录](acceptance/portable-v70-superseded.json) |
| 修正版Portable | 新建v71目录，源来自干净冻结feceb27；包内17专项、F030、数据库/CMake真实Chrome及Windows-only PATH启动，再做全文件封存 | 新候选及实际原生消费者 | 按前置收据自动串行执行，不改v67/v70；144应用源及全部32,034程序文件后验 | 限定范围PASS；不是完整发布 | [114号实际封存](114-portable-v71-typed-cold-reader-acceptance.md)、[最终收据](acceptance/portable-studio-v71.json) |
| 首版大库冷摘要 | 旧INAV原库上完整生成778,008,324B摘要，原库前后SHA不变；8GiB Job | 冻结v69，不含严格键修补 | 全量16566变量/491011函数；不能以数量作等价标准 | 构建PASS；与原完整算法全字节对照仍待验 | [构建及资源](acceptance/native-cold-diff-inav-v69-selected.json)，3045.609s，Job峰值1,629,368,320B；原32GiB控制仍运行 |
| 修正版大库 | 独立运行v71读取器；仅在原完整oracle完成及其原库SHA/最终收据通过后，才复用该不可变oracle全字节对照 | 冻结v71、独立测量脚本 | 两版31个Git Diff函数AST一致，原输入SHA相同；不替换旧state/原件指纹 | 已排队，NOT_VERIFIED | 外部`native-cold-diff-v71-queue.json`；最终实际Job及全部摘要对照待生成 |

已完成的大型生产者前后记录如下，全部保持各自冻结源和实际范围，不能把旧结果改标为本版。原标准紧凑包和最终保留政策来自[79号](79-r2b-regression-and-v13-package-final.md)、[84号](84-seed0-v13-complete-compact-retention.md)。v63的完整事实/报告差异0依据[完整对照](acceptance/inav-recovery-v63-full-comparison.json)和[4123输入/引擎后验](acceptance/inav-recovery-v63-postflight.json)。

| 生产者与范围 | 实际扫描秒 | Job提交峰值B / 采样RSS峰值B | 输出根采样分配峰值B | 完整标准包B / 最终保留集合B | 完整事实/报告差异 |
|---|---:|---|---:|---|---|
| 原e69固定seed0冷基准 | 15454.922 | 29,811,765,248 / 29,559,390,208 | 46,538,663,768 | 标准包待验 / 47,665,101,856（既定政策） | 黄金基准 |
| 冷v13，冻结v32/49960e | 55454.500 | 10,692,485,120 / 10,625,884,160 | 18,795,702,152 | 3,157,552,641 / 13,513,363,864（84号政策） | 0/0 |
| v63同根恢复，冻结v62，273命中+115重提取 | 13750.547 | 10,687,455,232 / 10,624,204,800 | 19,700,047,008（含保留旧尝试） | NOT_VERIFIED / NOT_VERIFIED | 0/0 |
| 本版消费者v71及最新冷生产者v68/冻结v66 | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED / NOT_VERIFIED | NOT_VERIFIED |

上述主机为64GiB Windows及共享磁盘，存在并行扫描/回归/组装；恢复时间不等于冷扫描时间，不作速度改善结论。采样文件分配不含MFT/目录/ADS和未捕获瞬时峰值，不是完整G4。旧v13最终保留子门限不能用于认定v63或本版G4通过。冷摘要文件也不是完整结果包。v69大库构建成绩只属于v69，原完整摘要对照结束前不宣称其完整语义通过。

开发复现使用新建独立验收目录，不能覆盖旧收据：

```powershell
py -3.10 -B -X utf8 -m unittest tests.test_native_diff_reader tests.test_native_diff_summary_cache -v
py -3.10 -B -X utf8 scripts/validate_native_diff_cache_ui.py --engine <冻结源码> --work <新的独立目录>
py -3.10 -B -X utf8 scripts/validate_native_diff_reader.py --source <只读scan.db> --engine <冻结源码> --work <新目录A> --mode selected --job-gib 8
py -3.10 -B -X utf8 scripts/validate_native_diff_reader.py --source <同一只读scan.db> --engine <同一冻结源码> --work <新目录B> --mode full --job-gib 32
```

普通使用入口现为`H:/ECRAStudio-build-20261106-studio-v71/ECRA-Portable/ECRA.cmd`，完整ZIP及SHA和包内实测见[114号](114-portable-v71-typed-cold-reader-acceptance.md)。旧v67保留。GUI自动化通过不等于盲UAT通过；静态结论和复核收据不等于目标板硬件复现。

剩余：当前侧及双版compare/整轮Diff恢复的实际内存证明；CMake未提交构建完整流程；当前完整回归、修正版包和最新大库验收收据。其它G2工程按用户要求待验，32GB物理机、第二台干净离线PC、真实模型联网、原生DPI及5–8人盲UAT均NOT_VERIFIED。完整重构及G1–G8总门禁仍未完成。
