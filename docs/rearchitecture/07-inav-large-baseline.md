# INAV 388TU 新黄金输入与原生测量（进行中）

## 16GiB预算实际FAIL（覆盖此前进行中状态）

恢复v3确实触及16GiB Job额度，在“并发风险分类与保护证据”发生MemoryError并受控退出3；结果analysis_valid=false/FAILED，未取得完整权威结果，G1仍未验。1472.438秒为恢复段（不含589.125秒缓存复制与158.765秒输入复验，不是冷扫描耗时）；388个PARSED TU缓存命中、0重新提取/0损坏。原始Job峰值17,179,934,720B，private采样17,179,660,288B，工作集17,097,158,656B；不裁剪峰值到配置上限。故障诊断时整机提交50,646,466,560B、额度85,825,454,080B、可用物理33,745,141,760B，与v2整机耗尽不同，这次应记**16GiB预算FAIL**。见inav-canonical-native-v3-failed.json。

保留全部v3现场，另在I:/ECRA-N4用相同冻结717文件/配置和已验证TU缓存运行32GiB诊断，名称inav-canonical-diagnostic32-v4。目的为获取完整结果、逐字段对照及定位分配热点；32GiB成功也不能改写16GiB FAIL，且仍非物理32GB机验收。当前原版流式图编码/完整独立备份仍在运行。

## 整机提交耗尽与可验证恢复（最新）

候选v2完成388TU后在归并阶段因观察器MemoryError被终止，观察到Job峰值7,925,542,912B，尚不是16GiB预算触顶的证据；原版图编码遇SQLite I/O error，独立备份也发生MemoryError。所有失败收据/部分目录保留：inav-canonical-native-v2-failed.json、inav-original-graph-v1-failed.json、inav-original-backup-v1-failed.json。同期Windows2004事件显示系统提交接近103GB额度；61.1GB Python进程创建时间在故障前8秒，**不是早已运行的备份进程**，此前归因已纠正。其消失后的完整命令行未捕获；并行venv故障测试的PID错误由源审计与独立无分配等待程序复现，见10-process-job-ownership.md，不能将未知归因写成已证实的备份内存收益。

备份工具改用固定readinto缓冲及外层256MiB Job；显式引用旧失败收据，在全新观察目录inav-original-backup-v2逐一重验现存字节，错误副本拒绝覆盖，旧日志/manifest保留。原版完整JSON以2GiB预算在inav-original-graph-v2重新编码。两者仍进行中，不能提前称完整备份/全字段对照通过。

恢复候选v3启动前4,123个源/Git/构建文件与717个冻结引擎文件全SHA复验无变化（inav-inputs-before-recovery-v3.json）。从失败v2独立复制776个TU缓存文件、5,371,819,011B，589.125秒；在I:/ECRA-N3重新执行原生预处理/输入/编译器/引擎/缓存哈希门禁并继续完整求解。不是旧报告/JSON回放，但也不是一次新的冷启动提取计时。前置真实F030故障后恢复验证2个PARSED缓存命中、2个PARTIAL重新提取、完整facts/report差异0；见native-recovery-resume-probe-v1.json。冷扫描性能、INAV语义等价和G3/G4继续未验，不以恢复时间冒充全量耗时。

## 2026-11-01 当前对照工作（覆盖下述较早的启动计划）

原始I:/ECRA-O1的57,773文件已设置只读文件属性（不是ACL/只读挂载），独立I:/ECRA-GOLDEN-O1仍逐文件复制/复验，未完成前不称备份完成。见inav-original-file-attributes.json。

首次候选inav-canonical-native-v1启动与冻结副本收尾发生重叠，已明确作废为REJECTED_STARTUP_ORDER；仅停止核验过身份的本任务进程，保留I:/ECRA-N1部分产物与失败收据，不计任何G门禁。新候选inav-canonical-native-v2在717个冻结工作文件逐一校验完成后顺序启动，使用frozen-engine-temporary-7d5、独立I:/ECRA-N2、同一6b27a1b0…配置、16GiB Job上限，临时目录归属该独立根。当前仍在原生388TU提取/分析，未宣布完成/等价/资源达标。

scripts/measure_baseline_graph.py对已完成原生原版的两个完整JSON进行流式图编码，供逐字段对照；不重新提取、不整图恢复、不改原JSON，不是第三个原生工程或标准完整归档。真实4TU原版探针通过深度关系/投影校验与前后源SHA检查，Job峰值27,922,432B；见baseline-graph-probe-v2.json。INAV原版编码在独立目录进行中，尚未和新扫描比较，G1仍未关闭。

## 原版完成与候选前置核验（最新）

原版实际388TU完整运行已经结束：12,542.188秒，退出码2，analysis_valid=true、STATIC_SCAN_SAVED、输入快照VERIFIED；报告仍为INCOMPLETE，不能解释为全工程安全。进程树Job提交峰值29,805,875,200B，工作集峰值29,537,386,496B，主树private采样峰值29,735,292,928B；显式32GiB安全上限未触及。目录最终/采样逻辑峰值均46,427,649,982B、57,773文件。见evidence/inav-original-native-v1.json及完整console/resources日志。原版早期没有分配字节/分页采集，不事后补造物理峰值；64GiB主机也不代替G3物理32GB。

原版结束后逐一复验源树（含独立.git）3,545文件和实际构建578文件，SHA/大小/mtime全部不变，共4,123文件，差异0（inav-inputs-after-original.json）。完整原始数据正独立复制到I:/ECRA-GOLDEN-O1，逐文件哈希验证后设置只读文件属性；复制验证尚未完成前不称完整只读备份通过。候选须使用相同配置/源码路径/命令/ELF/map，从独立I:/ECRA-N1重新原生提取，预算16GiB，不共用原版TU缓存。原始备份与比较器中间格式不计入日常扫描磁盘收益。

冻结1b573a1全套1189测试已结束：1187PASS、2项联网OpenCode opt-in跳过，1753.598秒；686冻结文件全部SHA未变，106运行时文件与Portablev10逐字节相同。见full-regression-allocation-1b5.json。后续3项Windows指标、3项备份专项是单独范围，不改写全套计数。

用户回复“先继续已获准工程，其余标记待验”：仅继续已获准INAV/F030。其余G2工程保持NOT_VERIFIED_USER_DEFERRED。回复前ST公开资料目录/版本和独立Git下载已经完成，但没有构建/扫描，后续不推进；没有访问客户固件。见g2-user-scope-20261101.json。

## 观察器后续版本与当前长任务范围

当前长任务inav-original-native-v1继续使用启动时的旧观察器；没有事后为它补造早期分页/分配峰值。新版scripts/native_metrics.py为以后运行增加[FileStandardInfo分配字节](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_standard_info)、[同句柄卷号与128位文件身份](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info)以避免硬链接重复计算；这不是os.stat的逻辑文件大小。遍历是每15秒采样的下界，排除目录/MFT元数据和备用数据流；消失/无法读取的文件显式记录partial。不能据此宣布完整G4或70%收益。

系统分页由[PDH语言无关计数器](https://learn.microsoft.com/en-us/windows/win32/api/pdh/nf-pdh-pdhaddenglishcounterw)采集Memory Pages Input/sec及Pages Output/sec，使用[格式化浮点值与有效状态](https://learn.microsoft.com/en-us/windows/win32/api/pdh/nf-pdh-pdhgetformattedcountervalue)。这是整机采样，不能归因于单个ECRA；计数器失败时保留错误，禁止补0。物理32GB与系统非ECRA负载仍需独立记录。

3项真实Windows专项通过：硬链接两路径只算一个物理文件；256MiB稀疏文件实际分配远小于逻辑长度；真实PDH预热后有效。新观察器实际4TU原生canonical运行23.954秒完成，analysis_valid=true且仍INCOMPLETE，46个有效分页样本，Job峰值142,188,544B、采样分配峰值14,262,384B；见evidence/native-resource-observer-probe-v3.json。这是采集链验证，不是INAV/32GB/70%门禁。

候选1b573a1已按实际工作字节冻结在continuation-h3/frozen-engine-allocation-1b5，共686文件及旁置逐文件SHA清单；包含权威图文件身份缓存、投影小工作集验证、ADR-009精确冲突分配优化。全套回归正在该冻结目录运行；原版长任务结束后再单独运行候选。v9包早于这些运行时变更，不能继续宣称v9与当前源码逐字节一致。

仅使用任务书获准的公开INAV副本 `I:/ecra_stm32_validation/inav-h743-20261026`。实际HEAD为f25434a9e2e58db1ad2ce3b87529a78393cad139，存在一处既有未提交改动 `src/main/drivers/serial_uart_stm32h7xx.c`；未执行原仓库checkout/reset/clean或修改原索引。旧配置含已废弃target_ref/compare_mode，另存改为当前base_ref/current_ref语法；本次全量关闭Diff。没有修改工具工作区中的用户config/semantics.yaml。

只读元数据盘点见evidence/inav-input-inventory.json：原.ecra共115,696个文件、106,941,865,853逻辑字节，原build约1.865GB；这些历史数据完整保留，没有以其删除量计算新格式收益。不是当前引擎磁盘峰值测量。

补查历史归档有效性：虽然原.ecra存在5,855,058,999B facts.json和7,674,376,192B facts.db，result_validity仍为analysis_valid=false/RUNNING、开始于2026-10-29。不能仅凭大文件存在就把它作为完整黄金或G2成功；本轮没有复用它替代正在运行的原生基线，也没有删除/修复原目录。见evidence/inav-historical-validity.json。

`scripts/prepare_inav_golden.py`在独立Git对象库捕获3,533个实际源码输入、225,726,022B及原始working/staged补丁、索引条目、Git状态和SQLite逐文件哈希。原索引/HEAD/工作状态与捕获后源码字节复验相同；原ignored构建/旧报告未复制，必须通过重新构建和实际消费闭包证明输入，不能叫作生产dirty完整快照。发生staged变化/子模块/链接/冲突时拒绝，不把未知输入跳过。2项真实Git专项通过，包含删除/未跟踪/忽略历史与staged拒绝。

准备目录：`I:/ECRAStudio-data/rearchitecture-20261101/inav-golden-f254-v1`。首次no-checkout克隆在完成源码复制后，另对私有副本明确执行read-tree HEAD，核对全部索引条目和porcelain状态与原输入相同；该步骤只写私有.git。见inav-golden-index-check.json，脚本已将此步骤纳入默认流程。

原引擎e69首次外置构建实际失败：GNU GCC无法创建长路径的.dep文件，日志/配置/目录保留，见inav-build-long-path-failure.json。另存 `semantics-build-short.yaml`，只更换独立输出根为I:/ECRA-B1后，原引擎真实CMake/Ninja/ARM GCC10.3.1完成392个构建步骤及MATEKH743.elf链接，目标闭包388TU。未改变固件字节、目标、优化参数或诊断策略；详情inav-native-build-v2.json。

为两个引擎的独立提取固定同一命令与路径，最终 `semantics-native-golden.yaml`引用刚刚生成的target compile database、ELF及map；两边均使用该文件的完全相同字节，不在对照时再次配置CMake。构建阶段与原生提取/分析阶段分别测量，不伪称全量CMake工作流等价。源码含独立Git元数据共3,545个文件、332,710,534B，实际构建578个文件、1,125,157,293B；逐文件SHA/大小/mtime记录于frozen-inputs.db，输入文件置只读。还不是只读挂载/ACL的完整U03证明。

测量器 `scripts/measure_native_golden.py`先在真实4TU旧CLI运行验证：10秒左右实际完成、analysis_valid=true、INCOMPLETE，捕获全部Job子进程、主进程内存、系统RAM/提交及目录逻辑字节；见native-resource-observer-probe-v2.json。首版短任务没有中间磁盘样本，现将最终大小纳入采样下界，失败/旧收据保留。它不重新装入完整facts/report，不把一个指标采集器当成语义对照。

388TU原版原生全量已启动，日志为 `H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/inav-original-native-v1/console.log`，资源逐样本为同目录resources.jsonl；完整性仅由执行结束后的execution.json确定。原版运行显式施加32GiB进程树安全提交上限，低于4GiB系统可用或8GiB工作盘空闲会只停止本任务；触及限制是受控失败，不叫作自然OOM。主机物理64GiB，不是32GiB电脑测试；目录大小只是采样逻辑下界，物理分配峰值和系统分页速率尚未测量，不关闭G3/G4。当前尚无本次388TU完整黄金事实、候选逐字段对照或完整Diff收据，G1/G2保持NOT_VERIFIED。
# 2026-11-01 18时续轮核验（覆盖早期“正在运行”描述）

见[evidence/long-task-interruption-20261101.json](evidence/long-task-interruption-20261101.json)：原版独立备份v2、原版JSON流式图v2和canonical diagnostic32 v4的原PID均不存在，原观察器没有最终收据。没有证据确认终止原因，不把中断称作受控完成或自然OOM。所有原日志/收据/部分文件保持原样。

备份已复制57,773文件/46,427,649,982B，之后只复验到部分源文件，状态仍VERIFYING_ORIGINAL、passed=false；因此**完整独立只读黄金备份未通过**。可用另存的中断恢复凭据重试，每个已有文件仍须SHA核验，不覆盖不一致字节。

32GiB诊断已完成分类并进入单次发布，观察到Job峰值22,429,601,792B、主树private22,423,830,528B，未生成最终scan.db或有效发布；这既不满足16GiB目标，也没有关闭G1/G4。它复用了逐文件复验的388TU缓存，不是冷扫描。原版图转换保留pending库，未完成深度校验，不供正式对照。先前受控16GiB v3的FAIL继续有效。

固定388TU归并的分配诊断另行测量，明确CONTROLLED_REPLAY_NOT_NATIVE_G2_OR_G3；不将其当作新的原生项目或成功发布。仅继续用户获准INAV/F030，其余真实工程仍NOT_VERIFIED_USER_DEFERRED。



## 2026-11-01 黄金独立副本已完成，候选 v5 继续运行

`evidence/inav-original-backup-v3.json`：源 I:/ECRA-O1 与独立 I:/ECRA-GOLDEN-O1 的57,773文件、46,427,649,982B全部逐文件SHA校验通过，源再次全量复验不变，清单SHA为bed35ca978b234f4afc04b6b0ced4949ddb3abc992f307d8a45e6689f2991875。复用中断副本前每个文件均已验证，未改写原版数据。只读仅指文件属性；H/I为同一物理HDD的两个分区，不是异机灾备或只读挂载。此前v2中断收据继续保留，不能改写为成功。

候选 v5 使用冻结selectors引擎、原6b27配置，从H:/ECRA-NATIVE-S5独立冷提取388TU，Windows Job上限16GiB。启动前4123输入和779引擎文件核验通过，见inav-selectors-native-v5-preflight.json。当前完成提取、正在事实合并，没有最终成功收据；此前v3在16GiB下的MemoryError仍是实际FAIL，不能由提取阶段低内存覆盖。原版完整图转码排在候选之后，使用明确隔离的64MiB SQLite写缓存试验，不作为生产引擎或原生G2证明，见codec-cache64-diagnostic-v1.json。大型全字段对照与G1/G3/G4仍未关闭。
