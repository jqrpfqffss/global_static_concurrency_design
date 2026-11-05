# 冷 Diff 读取与 INAV 恢复：阶段收据

起点为 `optimize_ccc@3f0d25b`，执行前工作区干净。本阶段合同见[110号](110-native-cold-diff-reader-contract.md)。原产品界面、静态扫描及风险判定没有变更。下表区分已完成的实际验收与仍在运行的任务，不表示整项重构完成。

| 阶段 | 核心功能 | 文件 | 测试场景 | 结果 | 证据 |
|---|---|---|---|---|---|
| 冷摘要读取实现 | 首次缓存缺失时按权威有序关系/字段读入，沿用原摘要算法，不再同时恢复完整基准facts/report | `ecra/native_diff_summary.py`、`ecra/git_diff.py` | 普通完整字段、全局关系、重复/顺序/标量类型、指针3种编码、CFG/构建根/重命名、私有隔离及解析失败 | 冻结专项PASS；完整回归正在运行 | [合同](110-native-cold-diff-reader-contract.md)、[原算法AST对照](acceptance/native-cold-diff-reader-v69-algorithm-proof.json)、`tests/test_native_diff_reader.py` |
| 实际原生Diff消费者 | 冷读及损坏重建禁止完整baseline load；跨扫描共享缓存、原摘要全字段/原键、CMake宏4→8、旧库/索引不可变及失败/断点门禁 | `tests/test_native_diff_summary_cache.py` | 真实2TU提取/分析/发布，不替代G2 | 冻结专项16项PASS，345.987s，0跳过；冻结源及独立副本各3902文件SHA不变 | [收据](acceptance/native-cold-diff-reader-v69-focused.json)、[完整日志](acceptance/native-cold-diff-reader-v69-focused.log) |
| 获准F030 | 原工程/配置/工具链保持，完整原生事实和报告对照原v48 | 冻结v69、原F030 | 原2 PARSED/2 PARTIAL保持，原43文件内容/时间戳不变 | PASS，37.781s，完整事实/报告0差 | [收据](acceptance/native-reader-f030-v69.json) |
| 实际界面及完整包 | 真实按钮发起两次扫描、第二轮复用；打开shared访问证据，完整包独立导入后校验facts/report根及基准摘要 | 现有Vue界面/真实服务、原生2TU | 1366×768 Chrome；profile由真实API预置；非G2/原生DPI/UAT | 5组PASS，163.547s；原33文件/114程序文件不变，258本地请求、0外部请求、0浏览器错误/警告 | [收据](acceptance/native-cold-diff-ui-v69.json)、[截图](ui/screenshots/native-cold-diff-v69/03-shared-evidence.png)、`scripts/validate_native_diff_cache_ui.py` |
| 首次冷摘要大型测量 | 相同原INAV权威库，新读取8GiB Job与原完整恢复32GiB Job分别运行；独立生成的完整摘要文件逐字节对照 | `scripts/validate_native_diff_reader.py` | 原始完整摘要作为标准；原库前后SHA；Job/RSS/系统/分页/临时输出实际采样 | 正在运行，NOT_VERIFIED | 外部`native-cold-diff-inav-v69-{selected,full}/execution.json`及comparison最终收据待生成 |
| 已结束的v63恢复 | 同数据根已有273 TU经原门禁复验，重新提取115，共388 TU；重跑全局求解并原生发布 | 冻结v62生产者，独立v63观察器 | 4123原始输入、原配置/工具链、完整类型/顺序/重复关系及报告比较 | PASS，恢复用时13750.547s；不是冷扫描计时 | [生产](acceptance/inav-recovery-v63-native.json)、[完整G1对照](acceptance/inav-recovery-v63-full-comparison.json)、[输入/引擎后验](acceptance/inav-recovery-v63-postflight.json)、[最终控制器](acceptance/inav-recovery-v63-final.json) |
| v63后续操作 | 真实报告刷新、最大候选完整Packet写盘与收据投影 | 原v63结果、原消费者 | 各自2GiB Job，原库前后SHA不变；不调用真实模型 | PASS；刷新1846.5s，Packet控制器435.187s | [报告刷新](acceptance/inav-recovery-v63-report.json)、[Packet Job](acceptance/inav-recovery-v63-packet-job.json)、[完整Packet收据](acceptance/inav-recovery-v63-packet.json) |
| 最新固定生产者冷扫描 | 冻结v66，从空数据根H:/ECRA-NATIVE-C68-SEED0经公开run_canonical扫描原INAV | v68实际控制器，冻结v66未改 | 没有复制缓存、改旧state或替换旧指纹；16GiB Job | 正在运行，NOT_VERIFIED；不包含本阶段新读取器 | 外部`inav-current-published-native-v68/execution.json`及queue收据 |

新读法仅跳过**原算法未读取的字段**。函数8个字段和调用4个字段组成可反复遍历的普通记录；变量和finding按需恢复其完整字段，每个变量复用自己的解码memo，进入下一对象后释放。原算法参与散列的嵌套值仍是普通dict/list，保留原类型、顺序和重复，完整指针集合继续交给原解码器。31个顶层Git Diff函数只有`prepare_base`接线变更，其余30个（包含全部摘要、规范化、比较及影响判定）AST完全相同；AST证据与实际结果对照分别保留。

冻结v69的manifest SHA为`c78f0337f61f7220abe4b2de3339b59898a27890031e28057cc45504569fc6f7`，父提交3f0d25b，带本阶段实现覆盖层。大型观察器另保留完整原库前/后SHA。仓库观察脚本随后补强了“后验SHA不同时抛错”的退出状态；真实小库worker的正常通过和仅父进程后验返回值故障注入另验，见[观察器门禁收据](acceptance/native-reader-observer-v69-guards.json)。该故障注入不修改任何原库；不计入冻结16项或完整回归数量，也不改正在运行的冻结观察器。大型最终对照还需独立审核两个Job最终PASS、原库前后SHA及完整摘要字节，不能只读控制器退出码。

仍保留完整上下文绑定/图、TU/NVIC，以及原摘要需要的函数索引、全部图、变量摘要和散列列表。单个完整变量字段也可能很大。因此这是**移除整份基准事实/报告同时恢复**的一段实现，不是全程严格有界；当前侧`cli.run`和最后双版`compare`、整轮Diff恢复尚需继续。8GiB预算是受控试验，不是32GB物理机证明。大型测试与冷扫描/回归共用本机资源，时间仅记录观察值，不据此声称速度提升或独占磁盘成绩。

v63恢复的Job提交峰值10,687,455,232B、采样工作集10,624,204,800B、private10,686,406,656B；报告刷新Job峰值671,604,736B；最大Packet Job峰值1,442,209,792B，完整Packet序列化615,590,622B且实际写盘/收据投影通过。这些范围分开计量，不能相加为新版本冷Diff或G3最终成绩。v63与原始INAV的完整事实/报告逻辑根分别完全一致；比较器保持既有clean_report和执行信封合同，没有新增忽略项。

保留两次非PASS：首次开发树专项实际8项中7 PASS、CMake项FAIL，见[原日志](acceptance/native-cold-diff-reader-v69-exploratory-failure.log)。执行期间仍修改了源码注释，CMake第二轮被既有“静态分析实现已变化”门禁阻断；没有修改门禁，改为冻结v69及独立副本重跑。旧v66冷任务因等待v63最终证明超过3小时而未启动，见[原失败](acceptance/inav-cold-v66-wait-timeout.json)；新v68在前置证明完成后从空目录启动，不覆盖该失败记录。

程序入口仍为已封存的[109号v67候选包](109-portable-v67-baseline-fix-acceptance.md)，新读取器尚未打入该包。本阶段没有冒称重新验收全部UI/Portable流程。CMake未提交构建输入的完整等价流程仍未支持；显式数据库工作字节的实际通过范围维持既有收据。其它G2工程按用户要求待验，32GB物理机、第二台干净离线电脑、真实联网复核、Windows原生DPI及5–8人盲UAT均NOT_VERIFIED。G1–G8总门禁及完整重构保持未完成。
