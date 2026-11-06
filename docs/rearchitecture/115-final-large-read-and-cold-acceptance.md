# 已结束的大型验收与下一段边界

执行起点为`optimize_ccc@b09ca1a`，工作区干净。补齐113/114号当时仍在运行的最终收据，原失败和过程快照均保留。当前应用源仍为feceb27；新工作开始前先固化这些实际结果。

| 阶段 | 核心功能/实际版本 | 场景 | 结果 | 证据 |
|---|---|---|---|---|
| 完整回归 | 干净冻结v71及独立副本各3925文件 | 实际1534项，源码无变化 | 1532 PASS、2真实联网opt-in SKIP、0失败；2990.140s | [最终收据](acceptance/full-regression-studio-v71-final.json)、[完整日志](acceptance/full-regression-studio-v71.log) |
| 原大库摘要控制 | 原INAV不可变权威库，冻结v69完整恢复facts/report后调用原summarize | 32GiB Job，原库前后SHA | PASS；3300.047s，Job峰值25,012,469,760B，RSS24,871,727,104B | [完整原方法](acceptance/native-cold-diff-inav-v69-full.json) |
| 当前大库冷摘要 | 干净v71按关系/字段读原同库，原31个Git Diff方法未变 | 8GiB Job；与独立原方法778,008,324B摘要逐字节比较 | PASS；1953.359s，Job峰值1,627,127,808B，RSS1,628,733,440B；全部摘要字节相同 | [资源及原件保护](acceptance/native-cold-diff-inav-v71-selected.json)、[最终全部字节对照](acceptance/native-cold-diff-v71-final.json) |
| 最新冷原生 | 冻结v66公开run_canonical，原始INAV388TU/4123输入，空数据根 | 0命中/388提取，原配置/工具/源码闭包复验，完整有序typed事实和报告 | PASS；15975.640s，Job峰值10,694,561,792B，RSS10,631,004,160B，输出根采样分配峰值18,791,186,432B | [实际生产](acceptance/inav-cold-v68-native.json)、[完整G1](acceptance/inav-cold-v68-full-comparison.json)、[输入后验及最终控制器](acceptance/inav-cold-v68-final.json) |
| 冷结果后续 | 该v68结果真实报告刷新及最大完整Packet写盘/收据验证 | 各自2GiB Job，原库SHA不变；不使用真实模型 | PASS_SCOPED | [报告](acceptance/inav-cold-v68-report.json)、[Packet资源](acceptance/inav-cold-v68-packet-job.json)、[完整Packet](acceptance/inav-cold-v68-packet.json) |

全部摘要SHA为`001c02b85c0953787057ee3a8a6b110ec447e0e22f944cd28966164d2540f108`。这是完整字段/顺序/重复的字节对照，不是数量或分类统计。原权威库SHA仍为`4549110d23bfb9ed3c78d5ea686fbeeb94e9e140eac4b88974288c25bd4e7913`。源v69控制与v71均有各自Job和源码清单后验，不能混用耗时、把旧运行改标当前生产者。

本次完成的是**基准冷摘要读取**及上述冻结生产者的原生/后续操作证明，尚未完成当前侧活事实与摘要共存、双版比较及整个Diff/恢复的联合资源证明。当前`cli.run`仍直接执行`compare(read_json(base_summary_file), summarize(facts, report), pin)`，双版大摘要与当前事实可能共存。下一段应将比较输入按记录外存，保留原比较/传播方法、完整输出与所有失败门禁，随后实际测量。

CMake未提交流程仍被`dirty_inputs.supported`、`frozen_scan.check_mode/replay_files`阻断。不能只删除判断：真实CMake需要受监督且不能写原固件的构建、原HEAD/索引/全部工作字节、生成文件/编译参数/SDK及配置读取的固定、后续prepare禁止偷偷重构建、归档/复核/恢复复验。适用模式的实际宏和完整事实必须与独立全量一致；无法证明的生成器不得静默准入。

主机为64GiB Windows，共享资源下耗时不作独占速度结论；目录分配采样不含MFT/ADS、未观测瞬时/删除后打开文件，不关闭完整G4。标准完整包/最终保留集合及旧e69/冷v13数据见113号，不能拿旧归档大小替代本次新原生的未测归档。32GB物理机、干净离线机、真实模型、DPI、盲UAT及用户延期的其它G2保持NOT_VERIFIED，完整重构仍未完成。v71入口/ZIP/截图和跨环境严格报告FAIL原审计见[114号](114-portable-v71-typed-cold-reader-acceptance.md)。
