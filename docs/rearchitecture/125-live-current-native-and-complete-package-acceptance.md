# 最新INAV当前侧实测与完整包验收补齐

2026-11-07核对真实`optimize_ccc@0e082fa`。直接由Codex执行，没有外部编码代理。本轮只新增验收控制程序、文档和回执，不改分析器、配置、比较器、正式应用或正在运行的冻结v78；在新目录补齐[124号完整包合同](124-latest-native-complete-package-contract.md)的实际控制程序和验收。完整重构仍未完成。

## 已完成与在途范围

| 阶段 | 实现的核心功能 | 变更文件 | 测试/场景ID | 状态 | 对应证据 |
|---|---|---|---|---|---|
| Phase 2/3/6 最新冷原生及当前活数据 | 原4123固定输入、388TU、0缓存命中；完整facts/report驻留时实际执行生产外存双摘要比较，报告原样返回并正式发布 | 冻结v78，manifest `11346522…`；本轮只归档原控制器结果 | G1/G3局部，实际完整有序/类型敏感facts与报告0/0，原输入及全部引擎SHA不变 | PASS_SCOPED，不是有源码改动的整轮Diff | [最终控制器](acceptance/native-v78-final-controller.json)、[原生资源](acceptance/native-v78-final-execution.json)、[完整G1](acceptance/native-v78-final-ordered-comparison.json)、[完整执行包络](acceptance/native-v78-final-ordered-envelope.jsonl)、[原件后验](acceptance/native-v78-final-postflight.json) |
| Phase 3 保存后继续使用 | 新生产者实际报告刷新；读取、构建、写盘和验证最大完整OpenCode Packet | 同一v78、同一新权威库；各自2GiB Job | 615590601字节规范Packet，15216相关访问；无真实模型调用 | PASS_SCOPED，原权威库SHA不变 | [报告资源](acceptance/native-v78-final-report-job.json)、[Packet资源及完整结果](acceptance/native-v78-final-packet-job.json)、[Packet原回执](acceptance/native-v78-final-packet.json) |
| Phase 5/6 完整包后处理 | 生产完整导出、包内3.10.9严格独立导入、所有原始图根/全部人工与AI表、原完整比较器、稳定保留量盘点 | [R2控制器](acceptance/final-package-v78-controller-r2.py.txt)、[真实Worker](acceptance/final-package-v78-worker.py.txt)；正式API不改 | 真实F030 v78：119个原扫描文件不变，事实/报告0/0；6条AI事件及1份快照保留；96.594秒 | PASS_SCOPED，小工程，不冒称大型或人工UAT | [最终回执](acceptance/final-package-v78-f030-r2-final.json)、[严格导入](acceptance/final-package-v78-f030-r2-import.json)、[有序比较](acceptance/final-package-v78-f030-r2-comparison.json)、[保留量](acceptance/final-package-v78-f030-r2-retention.json) |
| Phase 5/6 非空人工历史 | 真实F030归档的独立副本中加入待补证自动化声明及撤销，原静态库不变；再次完整包往返 | [副本准备](acceptance/final-package-v78-human-copy-setup.py.txt)，同一R2控制器 | 2条原事件、1条前驱关系、6条AI事件、1份快照逐字段保留；当前人工状态PENDING；98.563秒 | PASS_SCOPED，不是新原生或真实人员结论 | [原始准备与事件身份](acceptance/final-package-v78-human-copy-input.json)、[最终回执](acceptance/final-package-v78-human-f030-r2-final.json)、[严格导入](acceptance/final-package-v78-human-f030-r2-import.json) |
| Phase 5/6 后处理前置门禁 | 失败原生前提、已通过回执与所请求扫描路径不符，都在启动Worker前拒绝 | [实际负例控制器](acceptance/final-package-v78-negative-gate-controller.py.txt) | 两个预期拒绝，未生成包/Viewer，两个真实源结果均未变 | PASS_EXPECTED_REJECTION，不是原生扫描失败 | [验收](acceptance/final-package-v78-negative-gates.json)、[失败前提原回执](acceptance/final-package-v78-negative-failed-prerequisite-raw.json)、[路径不符原回执](acceptance/final-package-v78-negative-scan-binding-raw.json) |
| Phase 2/6 整轮Diff恢复 | 完整真实基准后，两个实际当前TU提交后中断；旧基准及原私有固件/Git不变；新scan_id实际恢复中 | 原v78全链路，真实IRQ计数器改动、完整ELF/MAP | 首段exit130，未发布当前结果；随后恢复重新验证输入并运行全局分析 | 首段受控中断已验证；最终恢复/独立全量仍NOT_VERIFIED | [首段资源](acceptance/whole-v78-stop-execution.json)、[明确中断点](acceptance/whole-v78-stop-marker.json)、[恢复过程快照](acceptance/whole-v78-stop-recovery-in-progress.json) |
| Phase 5/6 最新大型完整包 | 对新当前侧和整轮结果分别追加完整包、内嵌严格导入、完整比较、保留集合计量 | [后处理队列](acceptance/final-package-v78-queued.json)、[启动控制器](acceptance/final-package-v78-queue-controller.py.txt) | 只有各自最终原生PASS后执行；当前侧已进入实际导出，整轮仍等待 | RUNNING / NOT_VERIFIED | 工作根`native-final-package-inav-v78-r2/acceptance.json`、`native-final-package-whole-v78-r2/acceptance.json` |

## 当前侧真实大型资源

该v78生产者使用原黄金源码、配置/工具闭包和388个TU，在16GiB自有Windows Job完成；额外观察只在真实`analyze`返回时调用未改的完整`compare_spooled`消费者，随后原报告不变。其完整比较输出仍是892字节，SHA256 `8c5a97824be8442b8a8d05f35d6f88761dadde2bc5ae6d187289e575260506c4`，与原完整方法相同。输入未改，不能把此项算作有实际变更的整轮Git Diff。

| 指标 | 原版e69同输入原生历史控制 | 本次冻结v78冷原生及额外当前侧比较 |
|---|---:|---:|
| Job提交峰值 | 29811765248 B | 10700746752 B（9.96585GiB） |
| 进程树RSS采样峰值 | 29559390208 B | 10635071488 B |
| 主进程peak_pagefile | 29805244416 B | 10694295552 B |
| 生产者输出根采样分配峰值 | 46538663768 B | 18793679792 B |
| 生产者观察耗时 | 15454.922秒 | 20812.985秒（5.7814小时） |
| 本次发布后数据根分配量 | 完整历史策略另含共享构建，不能混作单根 | 9229677624 B，尚未计本次完整包及共享构建 |
| 本次新标准完整包及最终保留量 | 原完整保留策略47665101856 B，范围见旧收据 | NOT_VERIFIED，真实新包正在导出 |
| 全字段语义 | 原完整黄金来源 | 对A13完整有序/类型敏感事实、原规范化报告0/0 |

原版控制及其与A13的固定输入等价链见[65号](65-complete-compact-archive-retention.md)和[84号](84-seed0-v13-complete-compact-retention.md)，本次没有重跑e69。两列各自范围保留；v78包含额外完整当前侧消费者，且共享主机存在其它任务，不能据此宣称净扫描提速或独占性能。原v66的15975.640秒/10694561792字节Job峰值仍是[115号](115-final-large-read-and-cold-acceptance.md)那个生产者，不改标成v78。

本次完整事实hash为`43153000056630428dd91c4af9787cda65c107f4690814e36b607e21de4696aa`，原规范化报告hash为`26af6df2f8a675ef2be0a25f2be4b45c807f1ba2a8cd21a4d7af72aa53ed52db`。新权威库为`H:/ECRA-NATIVE-L78-SEED0/scans/native-golden/scan.db`，报告刷新/Packet后SHA仍为`d5349eebc74464a4c5343f901806c7340372f7160fc76ce03fe48214847b9e16`。原生CLI的实际退出码2保留；结构化结果已发布、输入VERIFIED且全字段相同，不把它解释为全工程安全。

报告刷新2354.016秒，Job提交峰值673697792 B；完整G1比较2751.625秒，614608896 B；最大Packet整段457.000秒，1443037184 B。Packet规范内容SHA为`05d4c3711269c7ba80946884d39220b58041952158f2de135c86530e267d5ee8`，实际文件另有物理SHA和收据验证，原始字节全部留在工作根。原输入4123项及整个冻结引擎末次核对差异均0。该结果支持64GiB主机受限Job中的当前侧内存目标，不能关闭32GB物理机G3。

## 完整包实际验证与磁盘范围

F030 R2标准完整包3490137字节，SHA `2e229b87cd53f80b1fd93ad34ce0e0d7741a699a0ae999aabc00a6b10089d173`。带两条自动化声明/撤销的独立副本包3490737字节，SHA `de1f6a62b48b19dc0dd9fb4d0b2688b2ff6eb35db380735e013770e1d476f75a`。最大单段Job提交分别33767424 B与34725888 B。原F030仍为原2 PARSED/2 PARTIAL、code2，不改源码、不重新分析或改分类。第二个副本的事件均明示为自动化验收，不是用户确认或工程风险结论。

首次控制器的[101.782秒功能成功回执](acceptance/final-package-v78-f030-v1-final.json)保持原样；其30秒磁盘样本会漏掉短操作结束前的新文件，不能当完整峰值。R2加入必需退出样本，实际F030导出段工作目录观测已包含3596536 B，后续计量分别包含完整数据根和一份完整包。原回执、控制程序及两份有效包均保留，没有为了峰值或70%门限删数据。原完整比较器未改；对原始图根和所有人工/AI表的补充核对比仅比较规范化报告更严格。

本批原始回执、脚本与日志见[逐文件SHA清单](acceptance/native-v78-final-evidence-index.json)。已结束的当前侧及整轮首段全部周期资源样本以无损ZIP保留于工作根，完整文件SHA/ZIP地址见[原始样本归档证明](acceptance/native-v78-final-raw-metrics.json)。不把该观察ZIP称作标准完整结果包。恢复中的样本仍由原观察器继续写入，不制作假最终收据。

整轮恢复日志显示，实际刷新外置CMake后，`CMakeCache.txt`使旧基准输入验证失效，因此重新生成新基准并保留旧权威库。这是实际恢复代价，不会恢复旧mtime、改状态指纹、放宽校验或声称跳过基准/任意求解器内部继续。首段缓存统计的10次尝试含Worker预取，不代表10个TU已提交；实际中断点只确认2个已提交，最终缓存命中必须以后续真实回执为准。

现有v79 Portable入口、真实界面截图及操作复验见[122号](122-portable-v79-and-source-target-acceptance.md)；完整1568项已1566 PASS/2联网SKIP见[123号](123-v78-full-regression-and-native-start.md)。本轮没有改正式应用，因此不重复这套已通过回归或重新封装包。最新大型完整包/保留量、整轮Diff最终恢复/资源仍待最终证据；其它G2、32GB真机、第二台干净离线电脑、系统DPI、真实模型及人工UAT保持NOT_VERIFIED，原跨环境严格报告FAIL和逐字段审计保留。
