# 续轮验收：真实实现与未通过门禁（2026-11-01）

## 2026-11-01 最新阶段记录（早期状态按时间保留）

配置往返同步与首屏固定操作已实际实现：17专项、7项真实Chrome，见ui/10-profile-roundtrip-contract.md。阶段Portable v11为H:/ECRAStudio-build-20261101-studio-v11/ECRA-Portable.zip，535,693,209B，SHA-256 de815af2529068f3f470387de4fb53abf092b67b18b8ea06a7c59c7122bd0b96；运行时4e6fe06，109文件匹配冻结源码。目录/中文ZIP解压各26命令与包内15项主流程、7项配置浏览器通过。v11不含后续Job启动/整机提交保护修复；不能把旧v10的其他浏览器收据算成本包实际复验。

冻结4e6/733文件完整回归结束：1205测试、4个失败断言、2 opt-in跳过，1845.984秒，所有冻结文件SHA未变。3个受控OOM子场景因venv真实PID未受限而失败，另PE夹具把venv启动器当成实际Python；源/失败已保留（full-regression-roundtrip-4e6.json）。没有将这些失败宣称通过。修复后49项专项、3项实际venv启动/后代归属测试、11项canonical/背压和当前源码15项浏览器通过，集合有重叠，不相加为全套数。须另冻结完整复跑。真实受控OOM内层128/192MiB、外层512MiB保护，不是G3大型工程性能证据。

INAV原版完整12542.188秒/Job29,805,875,200B/最终逻辑46,427,649,982B，仍INCOMPLETE；新版v2与原版图编码/备份在整机提交压力下失败。v3严格复验输入后从真实TU缓存继续，原版独立备份/流式编码重试进行中。详见07-inav-large-baseline.md。未取得成功的新旧大型完整对照，不提供伪造的收益比例或70%达标结论；物理32GB、完整实盘峰值与冷扫描耗时均未验。

用户已明确其余G2工程暂缓；只继续INAV/F030，其他保持NOT_VERIFIED_USER_DEFERRED。G1–G8整体未关闭，完整重构未完成。

## 最新局部验收与可用包 v10

| 范围 | 实测 | 边界/收据 |
|---|---|---|
| 发布/校验存储 | 60项PASS；真实小型原生结果三个根原样重新入库 | graph-identity-regression-v1.json、graph-publication-f030-v1.json；不是大型G1/G4 |
| 受保护冲突函数分配 | 4项PASS；48,000路径临时分配10,032,993→5,013,433B；实际4TU全字段事实/规范报告差异0 | ADR-009、conflict-allocation-v1.json、native-parsed-allocation-v1.json；不是全工程RAM降幅 |
| Windows写保护 | 3项PASS，Low子进程实际ARM链接与单TU解析PARSED | windows-write-guard-v1.json；尚未接入正式扫描，不关闭H2/U03 |
| 资源采集 | 3项PASS，真实4TU23.954s、46有效分页样本、Job142,188,544B、采样分配14,262,384B | native-resource-observer-probe-v3.json；分配仅采样下界、排除元数据/ADS，分页为整机 |
| Portable v10 | 目录/中文解压各26命令PASS；106运行时文件SHA一致 | portable-studio-v10.json；535,435,337B，SHA1354e5c8...；非干净离线机 |
| 真实Chrome | 主流程15、覆盖8、容量/排序9、旧迁移6、双origin协作7分别PASS | browser-portable-v10-*.json；不合并冒充完整U01–U24或全套单测 |
| 冻结全套 | 1189项：1187PASS、2 opt-in联网模型跳过，1753.598秒；686文件SHA未变 | full-regression-allocation-1b5.json；运行时与v10相同，后续临时目录修复单独验证 |
| 独占任务临时目录 | 38项PASS、真实4TU与旧版全字段差异0、真实Chrome15项 | worker-temporary-v2.json；尚未重打包，不当作完整H2或全套重跑 |
| INAV原版388TU | 12542.188秒；analysis_valid=true，状态INCOMPLETE；Job峰值29805875200B；最终/采样逻辑峰值46427649982B | inav-original-native-v1.json；32GiB受控上限、64GiB物理机；原版物理分配峰值/分页早期数据未采集 |

原版已完成最终验证、独立原始备份继续逐文件复制核验；候选尚无最终同输入对照，不能填写真实大型工程“之后”的最终峰值/耗时/差异，更不能宣称16GB或70%达标。历史.ecra虽有5.86GB JSON/7.67GB DB，其有效性仍为RUNNING/false，不替代本次原生黄金；inav-historical-validity.json明确记录。用户指定其他G2工程待验，仅继续已获准INAV/F030。此前1161项全套属于3590227，本轮1189项属于冻结1b573a1，不自动扩大到后续当前源码。

**完整重构未完成，Phase 0–6 和 G1–G8 不标全部通过。** 下方早期预览收据属于旧版本，不能当作当前源码/包的验收；当前实现入口为04-canonical-pipeline-progress.md。

当前封存候选v8对应运行时代码3590227：1161项完整回归，1159通过、2项实际模型测试跳过，1802.796s；104个模块/前端/许可文件与包逐字节相同。目录及长中文ZIP各26命令通过；包内Python3.10.9真实Chrome主流程14、旧迁移6、容量/精度8项通过。包SHA与文件见`evidence/portable-legacy-v8.json`，完整回归见`full-regression-legacy-wire.json`。首轮v7因GitSource目录层级配置错误停止，未删除失败现场；v8使用完整MinGit目录，包含离线Git。

补充成功解析黄金：原e69引擎在另一个明确配置中启用auto_system_includes，4TU里2PARSED/2PARTIAL，INCOMPLETE及6候选保留；候选使用同一配置文件字节、源码、编译库和工具，完整facts/report差异0，原结果/源码/.git不变，正式旧副本不存在。见`evidence/native-parsed-golden-v2.json`。旧黄金4FAILED/13UNKNOWN继续保留验证失败语义；不能把两份不同输入配置拼成优化前后收益，或把部分覆盖称完整解析。

| 当前实测 | 结果 | 范围/收据 |
|---|---|---|
| 原引擎语义保护区 | 无代码差异 | analysis/points_to/context_points/solver/call_graph/protection/nvic/interrupts/physical/decisions |
| 同输入独立原生4TU | facts/report全字段、类型、顺序差异0；原黄金不变；旧产物不存在 | continuation-h3/identical-native-v4/acceptance.json；不替代全部G1 |
| 原生固定两提交Diff | SQLite基准、输入固定、保存恢复通过 | test_canonical_scan；不替代完整大工程Diff |
| 真实Chrome | 14项通过，含原生停止/恢复、13项TECH_FAILED、调用树/源码行/组合筛选、人工和清理 | evidence/browser-canonical-v3.json；后续包内测试独立记录 |
| 20007行容量 | 最大API响应16,656B，首页0.266s，最后身份检索/打开0.218s，确认重开持久 | output/playwright/studio-capacity-20007-20261101/acceptance.json；显式容量夹具，不是原生固件 |
| 50GiB回收 | 实际释放53,687,025,664B，原包/静态库/人工历史不变 | evidence/gc-capacity-50gib.json；真实写入的无引用缓存，不是G4扫描收益 |
| 意外退出/PID复用/路径布局 | 17项专项通过；过期锁保留原收据，活锁/未知不删除 | continuation-h3/locks-tool-alias-regression.log |
| 原Portable回归 | 20项通过，42.390s | continuation-h3/portable-alias-tests-v4.log |
| 新性能脚本迁移 | 原生SQLite审计/保存测量恢复及真实ARM外置CMake，2项通过 | continuation-h3/native-benchmark-migration-2.log |
| 完整回归 | frozen-engine-v3：1129项/1127通过/2实际模型跳过，1631.320s；之后6个引擎文件修改有68项当前模块及20项原Portable回归 | continuation-h3/full-regression-v3.log；不得预报PASS |
| Portable | v6目录及长中文ZIP各26命令通过，包内Chrome十四项通过 | v6目录与长中文ZIP各26条命令PASS，包内14项Chrome PASS，100个源码/资源文件与包相同；不冒充干净机G8 |

本机实际64GB RAM，不是32GB目标电脑。没有执行真实联网OpenCode判定、目标板采集、5–8名独立工程师盲测或干净离线Windows验收。

本轮新增：旧目录GUI只读流式迁移，原生4TU旧facts/report全字段差异0、原64文件不变；50,000节点shared池与普通JSON完整根相同、工作集约29/31MB，SQLite约84MB大于11MB输入（不是G4收益）。六项真实迁移操作、更新后十四项主流程、62项模块回归和八项20007行浏览/精度操作通过。证据见`evidence/legacy-stream-v5.json`、`browser-legacy-v3.json`、`browser-wire-v1.json`、`regression-legacy-wire.json`和`browser-capacity-wire-v2.json`。这不是当前全源码的完整回归或最新Portable验收。

尚未完成的代码：全局工作集外存化、保存复核时全量facts重建消除、dirty生产构建/解析隔离、巨型/双来源历史合并/缺证据降级、完整专业覆盖/Diff对照与全部交互场景。独立dirty字节/索引捕获及七项Clang/GCC测试不意味着完整H2通过，正式入口仍拒绝include_uncommitted。新扫描停止旧副本已实现，不能把低内存消费者迁移也宣称完成。

G2的三类大型原生工程、G3的32GB 12/16GB实测、G4同输入峰值/最终物理占用降低70%、G5完整故障矩阵、G6完整大历史/包引用、G7所有U场景、G8干净机继续NOT_VERIFIED/FAIL。当前能力可验证，发布不通过。

---

## 2026-10-31 早期预览历史记录

**整体验收：BLOCKED，未完成完整重构。** 独立模块通过不代表Phase或G门禁通过。这里列出真实执行，不将历史版本、fixture、回放、浏览器自动化和真人满意度混用。

最终记录：冻结候选全套1100项，1098通过、2实际模型测试跳过；另有53项冻结workspace/模块回归、最终37项修改模块回归通过。最终包内Python3.10.9的9项真实浏览器流程通过，目录及ZIP解压包各25条命令验收通过。它们是不同范围/版本的验证，不能相加为“最终源码全部测试数”。详情见evidence/final-tests.json和portable-result.json。

最终预览包：`H:/ECRAStudio-build-20261031-delivery-preview/ECRA-Studio-Preview-verified.zip`，496272732字节，SHA-256 `f4e37cb2912fc03a32749b952606726cb3ef19e12bd234e306628a8d135b187a`。入口为解压后的ECRA-Portable/ECRA.cmd。该早期目录包与当时ecra模块/前端逐字节相同，已不代表续轮源码；没有在包内产生用户workspace。仍未在干净离线电脑完成G8。

Portable前两次长路径构建实际失败：CMake TryCompile在ASCII构建根上追加超过100字符，旧别名阈值180不够。修复为请求构建别名时始终使用已验证目标的紧凑Junction，在原长路径重跑真实ARM构建、扫描和保存命令通过。失败目录和收据保留，没有靠缩短验收路径掩盖问题。包内UI还复现初始化读取与“继续确认”竞态，修复串行恢复/控件启用条件后重跑9项通过。临时目录消失导致空间统计覆盖导入错误的问题也有专项回归。

## 实际证据

| 检查 | 范围与结果 | 收据 |
|---|---|---|
| 原引擎全套 | HEAD e69a10b冻结副本；1068项，1066通过、2实际模型测试跳过，1554.850秒 | evidence/original-regression.json；外部完整log及SHA |
| 存储全字段往返 | 真STM32F030原生4TU黄金facts/report/provenance；类型、字段、顺序、重复均相同；原文件哈希不变 | evidence/golden-roundtrip.json |
| 独立原生前后提取 | 同一4TU ARM/GCC/源码/编译数据库；facts及静态report语义差异0 | evidence/native-equivalence.json |
| 首次严比失败 | 工具读取输入的read_completed_ns不同；原失败保留，明确运行信封后重新原生执行比较 | evidence/native-equivalence-before-runtime-envelope.json；等价合同 |
| 新库/人工/API/路径专项 | 20007行分页、1000事件、冲突/撤销/幂等、恶意包、API同源门禁等；详细命令/收据随最终测试记录更新 | tests/test_scan_store.py 等；evidence/final-tests.json |
| 浏览器预览流程 | 真实Chrome、真实API与SQLite断言；导入/下钻/确认/重开/撤销/恶意包/配置/三视口 | output/playwright/studio-portable-20261031-verified/acceptance.json |
| 前端依赖 | TypeScript+Vite构建通过；升级后npm audit为0 | evidence/npm-audit.json；studio/package-lock.json |

浏览器前两轮失败保留在attempt1/attempt2：后台读占用写忙碌状态、select缺少准确可访问名称。修复后重跑，不计失败轮为通过。第三轮旧布局虽功能通过，人工动作位于长证据下方；根据截图再次改为证据分组滚动+稳定人工操作区，保留前后截图。

## 原生大工程必须另测

| 本轮真实大工程指标 | 前 | 后 | 门禁 |
|---|---|---|---|
| INAV 388TU 进程树RSS/主进程Commit/系统可用/分页 | NOT_VERIFIED | NOT_VERIFIED | G2/G3未通过 |
| 同输入磁盘峰值、WAL、缓存/build/worktree | NOT_VERIFIED | NOT_VERIFIED | G4未通过 |
| 最终标准完整归档大小与耗时 | NOT_VERIFIED | NOT_VERIFIED | 不能宣称降低≥70% |
| 全字段/全关系/全部Diff影响对照 | NOT_VERIFIED | NOT_VERIFIED | G1未关闭 |
| 另外两类真实工程（H747/回调/DMA/RTOS） | NOT_VERIFIED | NOT_VERIFIED | G2未通过 |

历史INAV数据只见00审计和原文，不用于本轮收益计算。小项目往返记录：旧最终目录5510061 B；新SQLite7507968 B（包含额外归档来源）、标准包3156947 B；这是4TU输入、不同载体的实际大小，**不构成G4的70%磁盘优化通过**。本轮没有采集该原生扫描的完整进程树/磁盘峰值，不补造数字。

## 阶段判定

| 阶段 | 已实现 | 尚未满足/状态 |
|---|---|---|
| Phase0 | 审计、353处旧路径引用起点、真实黄金全量与原生对照、冻结UI | 缺完整Diff黄金与三类大工程，NOT_VERIFIED/BLOCKED |
| Phase1 | 独立根、无损权威树、查询投影、原子发布、原workspace迁移复用 | 全部专门关系/CAS与正式消费者未完成，FAIL/BLOCKED |
| Phase2 | 提取提交有界，保持DB消费顺序/独立进程；Worker失败不降为成功 | 全局外存求解/资源预算/完整检查点状态机与G3/G5未实现，FAIL/BLOCKED |
| Phase3 | 可分页EvidenceProvider及QueryService | review/status/diff/report全消费者尚未迁移；旧CLI仍写旧HTML/JSON/MD，**H3 FAIL** |
| Phase4 | Vue中文真实归档界面、配置、独立人工事件/撤销/继续位置 | 无GUI正式扫描；图形调用树、全面组合筛选/状态/DPI/UAT未齐，FAIL/BLOCKED |
| Phase5 | 完整包/人工增量/严格导入/幂等/冲突后端与可见界面 | 旧数据流式GUI迁移、跨版本继承、50GB引用回收、物理两机未测，FAIL/BLOCKED |
| Phase6 | 原版/候选回归、浏览器、Portable构建及收据 | 三大工程、32GB、系统DPI、干净机、真人/目标板未测，NOT_VERIFIED/BLOCKED |

## 未完成工作的最小顺序

1. 根据legacy-consumers逐个迁移checked_scan、save_scan、Git基准/缓存、review/Packet/收据、status/report/审计消费者，保留原输入安全门禁；完成后才停写旧产物。
2. 补齐语义关系索引/CAS与无损旧数据导入，冻结真工程full+Diff黄金；对全局工作集测峰值，再实现等价外存/紧凑表示。不得改保护区算法换取性能。
3. 完成受监督扫描状态、TU提交检查点、资源预算和故障注入后接入GUI扫描按钮。dirty输入先完整固定到外部快照，不继续使用原源码工作区。
4. 完成调用图/变量证据专业导航、全组合筛选、跨扫描RECHECK_REQUIRED与冲突GUI全流程、引用可达性回收；补齐U01–U24。
5. 冻结最终源代码，在授权的三类真实项目与32GB机做G1–G8、离线干净机、Windows系统DPI及独立工程师盲测。任何失败继续保留BLOCKED。

当前阶段包收据为[evidence/portable-canonical-v6.json](evidence/portable-canonical-v6.json)。v6完整ZIP SHA-256：419432b2931549436c20594053a40d8dedef850002a232b4ae1d4b395f6f873c；完整重构未完成。


## 2026-11-01 覆盖诊断续轮

已将覆盖页由通用树入口扩展为真实阻断、缺口分组、全部TU、构建范围四类查询，完整根索引继续保留。位置存入独立人工库，规范身份精确下钻，不靠名称前缀选择同名对象；返回/关闭重开恢复筛选、页码与当前证据。诊断/命令/头文件及源码使用归档完整证据。集合缺失、未知类型、非对象原条目和无法证明零关联分别提示。

专项17项通过（evidence/regression-coverage-v3.json），F030浏览器8项通过（evidence/browser-coverage-v4.json），原生黄金2PARSED/2PARTIAL、236条原始缺口、5个覆盖阻断和成功零关联TU保持原值；最大API响应25,274B，scan.db SHA不变。另主流程11项与20007行容量/排序9项通过；这些范围不能相加为全源码回归。截图见ui/screenshots/coverage-v4。

封存v8的1161项冻结回归、目录/解压各26条命令与包内14+6+8浏览器流程属于3590227运行时代码；排序45d8a56及本轮覆盖不在该包中。v8 ZIP为H:/ECRAStudio-build-20261101-legacy-v8/ECRA-Portable.zip，535,418,600B，SHA-256 ba72a7907a3a9a09de690174ac3289059ac4ee745e8ee345329cb8a55afdd178。必须重建才能交付本轮功能。旧v6/v8收据不能证明当前源码完整通过。

完整重构仍未完成。生产dirty字节隔离、原.git/worktrees写入、全局外存求解、三类大型full/Diff逐字段对照、32GB资源/70%实盘收益、完整故障矩阵、干净离线机和工程师盲测继续未通过；U14是本轮已覆盖范围的部分验收，不标全场景PASS。


## 2026-11-01 当前阶段包 v9

[evidence/portable-studio-v9.json](evidence/portable-studio-v9.json)：实现e7521e9，包含服务器排序、覆盖诊断和向导/首页真实重扫。H:/ECRAStudio-build-20261101-studio-v9/ECRA-Portable.zip，535,430,890B；SHA-256 f6c27e191e893673da6d8b72a45c1fa279abfddcd0f3c7a281822796f554ae51。105个运行时代码/前端/许可文件与源码逐字节匹配。目录与长中文路径ZIP解压各26条真实命令通过；包内Python3.10.9真实Chrome主流程15项、覆盖8项、容量/排序9项、旧迁移6项分别通过。完整视频/trace保留，不合算为全套回归数。

主流程原生扫描明确使用冻结黄金数据库中的外部ARM编译器；包内ARM/GCC/C++/CMake/Ninja独立由两组26命令验证。没有干净离线物理机/系统DPI/工程师UAT；v9仍是阶段候选，G1–G8总门禁未关闭。1161项全回归属于3590227，当前新增覆盖有17项专项及真实浏览器验证；不宣称当前树已重跑完整全套。
