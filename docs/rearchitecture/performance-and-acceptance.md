# 续轮验收：真实实现与未通过门禁（2026-11-01）

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
