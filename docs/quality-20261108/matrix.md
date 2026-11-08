# 功能覆盖矩阵

状态：已通过 / 已失败 / 尚未验证 / 环境阻塞 / 不适用。这里的通过只对应所列输入和场景，不表示任意工程安全。

下表保留各轮真实输入的覆盖范围；新旧冻结版本不合并计数。当前主区engine2b9e，最终GUI及正式便携包V9。最新状态以[当前交付记录](continuation-final-v9.md)和下方“V9当前覆盖”为准；后面的历史“进行中/待合入”只记录发现时状态。运行中和环境缺口不记通过。

## V9当前覆盖（2026-11-08 14:43 UTC）

| 功能或模块 | 用户目标 | 实际入口 | 关键场景 | 预期依据 | 验证方式 | 实际结果 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 工作区与修复身份 | 使用本次代码 | optimize_ccc/当前HEAD/冻结V9 | 保留用户原件、不切历史分支、备份preimage | 初始干净基线与当前已接受需求 | SHA、Git状态及无暂存核对 | 全部修复在主区；最后core2b9e、GUIhDrZQigI；无提交推送 | continuation-final-v9、final-worktree-v9 | 已通过（本地身份） |
| 首次启动与CLI | 解压/安装后找到入口 | ECRA.cmd、run_ecra.py ui/init/doctor/run/status/report | 无.git、中文空格、工具/固件分离、不同cwd、外置config | README/实际help/包内说明 | 原生WinPS5.1、双27实际命令、真实页面 | 包Python3.10.9可启动，默认SQLite/Studio；外置后续命令保留config | delivery、continuation-offline-build-v9 | 已通过（所列路径） |
| 配置与预检查 | 正确导入真实工程 | 工程配置/CLI init/doctor | 新旧配置、错误路径/未知字段、系统头、相对toolchain | 当前schema与实际CMake读取 | 原场景/37配置回归/真实ARM与页面 | 新配置可解析标准头；旧显式配置保留；失败有下一步 | delivery、continuation-headers | 已通过 |
| 真实构建与CDB | 编译信息对应目标 | CMake/Ninja/GCC/MinGW/真实Makefile | C+ASM、已存在build、增量/再配置、真实链接 | 原项目固定commit/ELF/MAP/归档闭包 | F411/CDC/F030实际原生构建 | 三独立工程链接；F411实际24C闭包与原CDB46区别明确；不伪造库 | continuation-build、continuation-final-projects-v4 | 已通过（限定闭包） |
| 身份/变量/访问 | 跟踪真实存储及证据 | libclang→facts→候选→详情 | global/static/字段/同名作用域/多次访问/读改写/旧值覆盖 | 已知代码推理与canonical身份 | 真实ARM小样/独立语义回归/353对象JSON比对 | 身份与访问保留；24nested容器正确，叶项风险无丢弃 | analysis、continuation-q109、continuation-final-projects-v4 | 已通过（支持范围） |
| 物理上下文与保护 | 避免漏掉可行竞争 | vector/alias/context→protection | slot2/3、配置碰撞、NMI/HF、PRIMASK/BASEPRI/FAULTMASK | 实际GCC/ELF/objdump与架构契约 | 独立正反例与联合26、真实CLI发布 | 严重错误SAFE已修；不支持ABI明确失败，保留worker事实 | continuation-q205-independent-review、continuation-q206 | 已通过（所列语义） |
| 支持边界 | 明白未知影响 | 覆盖/诊断/分析状态 | 指针/回调/DMA/RTOS/双核/部分TU | 当前声明的建模范围 | 真实未知项、覆盖统计、错误样例 | PARTIAL/UNKNOWN/INCOMPLETE保留，volatile不作同步证明 | analysis、delivery、continuation-final-projects-v4 | 已通过（边界表达）；未实现机制不适用完整支持 |
| 静态/AI/人工分离 | 不让复核掩盖原冲突 | current_results/review/review-failed/人工页 | 关闭AI、超时/坏输出/重试/部分DONE/证据不足 | 冲突完整覆盖与独立来源合同 | 受控传输、账本、30格聚合与排列矩阵 | NEED_MORE_CONTEXT回退静态SUSPECT；技术失败不当安全 | analysis、state | 已通过（受控契约）；真实联网尚未验证 |
| 自动批次与任务恢复 | 不漏项/重复/假完成 | TaskManager/stop/重试 | workers/max_items、坏登记/日志、停止130、缓存继续 | 当前队列/终态与输入验证合同 | 实际页面停止恢复、状态回归、故障隔离 | 完成TU合理保留；恢复重用2TU/重提取2TU后发布；坏邻项隔离 | state、ui、continuation-regression | 已通过（所列真实流程） |
| SQLite长检查停止 | 中途退出而不损坏旧结果 | 正式stop文件/ScanDiagnostics | 真实大库读检查、busy与publish停止 | 停止应响应，完整性和原子发布不降级 | 真实SQL进入/真实stop/原断言 | 请求后约0.3–0.5s退出，旧库保留无假发布；最终时钟夹具另证 | continuation-regression、test_sqlite_scan_stop | 已通过（所列场景） |
| 固定提交Diff与缓存 | 理解真实比较和重用 | CDC cold/warm/full与独立full | 头宏/保护改变、规则版本、完整并发上下文 | 独立full等价与严格来源失效 | V4 cold/warm、最终包V8 ARM full→Diff→full | warm39TU复用；最终5对象仅impact外证据一致；未列出不等于安全 | continuation-diff-v4、continuation-diff-v8 | 已通过（记录的版本） |
| 真实工作字节与Git | 分析未提交输入且不修改工程 | V6 fresh clone/strict snapshot | Git2.37/2.56 stat-only、ACL通知、目录ABA/身份竞态 | 源/index不变，真实变更仍拒绝 | 25/18、独立32case、原失败、CDC2350.391s/39TU+独立full | 245对象、分类/语义0差异；568文件/HEAD/index/config原件不变 | continuation-diff-v6、regression/main-v8-git-smoke | 已通过；不自动改include_uncommitted策略 |
| 人工持久化/项目隔离 | 连续复核、保存、退出继续 | 真ECRA.cmd/Chrome持久profile/历史 | 筛选搜索、签署撤销、浏览器重开/服务重启、三项目 | append-only事件/静态AI独立 | 实际操作与API/只读SQLite/SHA | 三实际事件保持；NMI风险1、F411待办38、教学待办6不串；最终V9未新增签署 | package-ui-v4、q405-v9 | 已通过（实际保存由V4执行，V9复核保留） |
| 坏数据/保存失败/恢复 | 知道失败位置并继续 | 锁库409、坏manifest/summary/历史/Retry | 写入失败保留草稿、数组清单/部分坏文件 | 不虚假saved，不把缺证据当完成 | 真服务故障/实际画面/重试/共享校验回归 | 错误路径/阶段/下一步明确；修复自有坏文件后正常Retry，未注入人工状态 | ui、continuation-q108-ui、continuation-regression | 已通过（不宣称自动修坏文件） |
| 长证据与确认界面 | 阅读且确认正确对象 | 列表/详情/源码/调用树/共同确认栏 | 16访问42关系/alias/深链、长源码、F411/NMI切换 | 实际数据与可操作按钮/身份合同 | V8两渲染视口+native；V9最终包native两项目及1366/1920渲染视口 | Q405动作旁项目/变量/文件行/人工状态可读，按钮同屏无横溢；静态/三事件不变 | package-ui-final-v8、q405-v9、evidence/final-v9-ui | 已通过（所列窗口）；渲染与原生分别记录 |
| 最终Diff阅读 | 读清影响及剩余工作 | 实际V9包读取已有原生Diff | 默认影响3/潜在2、sharedRMW、清空筛选全部5 | 全量底层证据/明确范围合同 | 正常浏览器操作、真实窗口截图/只读数据核对 | 3SAFE+1容器+1SUSPECT/1待办；5对象静态SHA和0事件保持 | continuation-native-diff-ui-v9 | 已通过（读取同引擎V8结果） |
| 导出与重新打开 | 保存可携带结果 | 浏览器标准报告包导出/导入 | 成员CRC/SHA、静态/人工事件及parents | 当前报告包合同 | 真下载94838B、26成员/三事件逐字段比对及导入测试 | 静态原库一致，历史人工有效保留；坏ZIP明确报错 | package-ui-v4/browser-export、state、continuation-regression | 已通过 |
| 输出/命令安全 | 特殊输入不变可执行代码 | HTML renderer/路径/受控CMake命令 | 特殊字符、源码/模型文本转义、工具参数/清理边界 | 当前实际暴露输入与最小受控协议 | HTML/参数回归、拒绝自定义执行、路径隔离核对 | ASM --version及标准头二进制协议精确许可；任意execute仍拒绝 | analysis、legacy、continuation-headers | 已通过（自动契约）；新版file视觉受阻 |
| 最终便携交付/文档 | 不依赖开发机偶然PATH | 正式PS5.1 OfflineCheck/build/解压ECRA.cmd | 无.git、中文空格、全组件/8说明59链接、外部OpenCode | 当前发布边界 | V9双全SHA/双27命令/原件后验、最终UI | 4370源/27921缓存输入/4旧ZIP不变；ZIP7a0e…，154生产匹配；无开发浏览器依赖 | continuation-offline-build-v9 | 已通过（本机离线构建运行）；干净离线物理机尚未验证 |
| 大型资源与尾部发布 | 完成大工程并合理等待 | INAV388TU/16GiB Job/8workers | 无缓存NEW、百万facts/单次发布/最终完整性 | 实际有效发布和总耗时/资源证据 | 原控制器持续观察+独立有界CPU/I/O/文件metadata | 提取/分类完毕；14:31 pending约10.02GB，尚未正式发布；峰值约10GB、host无压力 | new-upgrade-v4、inav-publication-bounded-observation | 尚未验证（运行中）；不能仅凭活动判性能通过 |
| 环境与兼容入口 | 知道目标环境缺口 | OpenCode/legacy file/原生显示/新机器 | 禁用外部代理、file工具拒绝、屏幕可用范围 | 不绕过访问限制，不用模拟冒充目标 | 实际工具结果与环境记录 | 真联网、当前file视觉、OS DPI/zoom、原生1920/1366、物理32GB/干净机均未验证 | continuation-final-v9、package-ui-final-v8 | 尚未验证或环境阻塞 |

## 历史终验覆盖（下表为当时版本）

| 功能或模块 | 用户目标 | 实际入口 | 关键场景 | 预期依据 | 验证方式 | 实际结果 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 主区最终修复 | 使用已验证代码 | 本地工作区 | 完整基线EOF、无覆盖用户修改、备份与逐文件校验 | 当前分支/原479文件 | 精确SHA合入45操作、154生产文件对照 | 主engine65；65方法相关smoke运行中 | main-apply-v6-receipt、main-v6-smoke | 代码已合入；主区复验中 |
| 语义与证据 | 不误判NMI/alias安全 | 实际ARM编译→提取→分类→发布 | slot2/3、配置冲突、强覆盖、不支持alias ABI | 架构/真实ELF与独立推理 | 定向+独立+联合26/真实10例 | SUSPECT正确发布；不支持明确失败，旧事实保留 | continuation-q205-independent-review、continuation-q206 | 已通过（所列语义） |
| 三独立真实工程 | 完成实际扫描与查看 | F411/CDC/F030 run/status/report/status | 原生链接、真实CDB、部分覆盖/完整报告 | 固定提交与实际构建 | V4新全扫、事实对比及输入SHA | 67C/65PARSED/2PARTIAL/0FAILED，430对象244待办；非全安全 | continuation-final-projects-v4 | 已通过（对应V4未变路径） |
| 固定提交Diff/缓存 | 可信增量与复用 | CDC cold/warm/独立full | 宏/保护变化、完整基准复用、来源失效 | 独立代码语义与full | 实际两轮及55类关系对照 | 全部证据/分类一致；warm39TU复用，严格版本失效仍拒绝 | continuation-diff-v4、cross-engine-q207 | 已通过（所列范围） |
| 工作字节扫描 | 含真实未提交修改 | V6 fresh clone/C+ASM/true策略 | 只读Git、目录身份、ACL双准入、ABA | 不改源/index、不弱化监控 | 71定向+19独立；真实CDC整轮 | 小例/竞态复验通过；真实整轮运行中 | continuation-q207-independent-review、diff-final-v6 | 已通过（局部）；整轮尚未验证 |
| 人工与项目隔离 | 保存、退出、继续 | 实际ECRA.cmd/Chrome持久profile | 签署/撤销/重开/服务重启/三项目 | 独立append-only事件 | 真实UI操作与只读API/SHA | 风险1/待办0保留，邻项目未变；真实F411叶风险仍需复核 | continuation-final-v7、package-ui-v4 | 已通过（所列真实流程） |
| 失败与恢复 | 明确失败、保留有效工作 | 坏manifest、重试、历史 | 清单数组、文件恢复、跨项目记录 | 当前清单/就绪合同 | 隔离故障、实际画面/重试 | 非空白、错误路径/下一步明确；仅修复故障文件后恢复5搜索项，三库/人工计数不变 | ui_manifest_fault、截图ui-r2-* | 已通过（不声称自动修坏文件） |
| 阅读与状态标签 | 连续复核长证据 | 调用树/访问/身份/表单 | 16访问/42关系、四层链、alias、容器、已知枚举 | 实际产品字段合同 | 1366×768/1920×1080视口与截图 | pinned对象/确认按钮可见；末个ADDRESS_TAKEN标签V7构建已过 | continuation-final-v7 | 已通过（前述画面）；最终GUI成品待验 |
| 新便携交付 | 解压即用 | WinPS5.1正式离线脚本 | 无.git、中文空格、仅系统PATH、27命令双门禁 | 原脚本完整验收 | V4全包及真实F030/MinGit；新V6/V7完整重打 | V4完整通过；最终V7排队，不能当成品通过 | continuation-portable-v4-native、offline-build-v7 | V4已通过；最终包尚未验证 |
| 大型INAV | 大型完整分析/发布 | V4真实Studio NEW任务 | 388TU/16GiB Job/8workers | 实际任务与完整发布 | 真实API/资源/日志持续观察 | 388/388提取，风险分类中；版本63a5独立记录 | new-upgrade-v4 | 尚未验证（仍运行） |
| 目标环境边界 | 了解未证范围 | OpenCode/缩放/新机器/legacy file | 真实联网、DPI、物理32GB、干净离线机、最终file页面 | 不能模拟冒充 | 用户禁用/工具受阻/缺目标环境 | 明确保留限制 | continuation-final-v7 | 尚未验证或环境阻塞 |

## 续轮独立覆盖

| 功能或模块 | 用户目标 | 实际入口 | 关键场景 | 预期依据 | 验证方式 | 实际结果 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 完整基线 | 发现遗漏回归 | unittest discover -s tests -v | 原1646方法、故障/原生矩阵 | 当前74c0原字节 | 真整套运行、2秒资源与前后SHA | 仍运行，已出现异步10/40秒等待及删除活锁失败；真实语义/候选控制器另验；live opt-in明确跳过 | continuation-regression.md | 已失败（局部）、其余未完成 |
| 真固件构建 | 编译并链接实际目标 | 包内CMake/Ninja/GCC/MinGW、原Makefile | CDC/F030/F411、中文空格、外部签名依赖 | 真ELF/MAP/原编译和归档参数 | 原生Windows实际构建 | 三独立项目完整链接；F411真实闭包24TU，CDB46原件保留 | continuation-build.md、final-projects/f411-real-link-closure.json | 已通过（构建范围） |
| 工作字节与标准头 | 不因合法ASM或编码阻断 | guarded capture_inputs→Clang | C+ASM、中文GCC、stdint | 内置CMake协议及真实存在目录 | 原场景+拒绝边界、实际只读捕获 | Q203/Q306联合4项通过，整工程dirty另在运行 | continuation-headers.md、continuation-diff.md | 小场景已通过；整轮尚未验证 |
| 固定提交Diff | 信任影响范围 | CDC两真实提交、verify_against_full | 保护失效/头宏变化、独立full、warm | 独立SAFE→SUSPECT代码语义 | 74c0 cold/warm各39TU及无缓存39TU | 两轮analysis_valid，分类/语义0差异，INCOMPLETE保留；新引擎继续 | continuation-diff.md | 原74范围已通过；新引擎尚未验证 |
| 路径及完整基准缓存 | 多次运行避免重复工作 | portable.build_path、基准摘要 | 注册顺序和首次缺失build目录 | 同物理目录稳定路径、严格失效 | 实际junction/CMake、真实重复 | Q204 v1局部通过，cold发现相邻遗漏，v2复验中 | continuation-diff.md | 已失败；修复进行中 |
| 坏结果与导入 | 保留有效结果并解释失败 | /scans、summary、产品上传 | 数组清单/坏ZIP/坏合并目标 | 当前发布和原子导入合同 | 真服务+49项、原始数据hash | Q105/106候选通过，联合版另跑 | continuation-regression.md | 候选已通过 |
| SQLite停止 | 退出长完整检查 | 正式stop文件+ScanDiagnostics | 实际12.6GB只读库 | 请求后合理响应，检查不降级 | 同原件前后产品validate、真实publish回归 | 原15秒不响应；最终请求后约0.312秒退出 | continuation.md、product-sqlite-stop-candidate-final.json | 候选已通过 |
| 失败后恢复界面 | 继续有效归档与人工确认 | Chrome/产品导航 | 空白页复现、重试、历史切换、保存、关闭重开 | 独立静态/人工、就绪前提 | 真实1366视口并查看截图 | Q108已复验；真实CDC244项/24访问/多层树和源码亦操作 | continuation-q108-ui.md、q108-*.png | 候选已通过 |
| nested容器一致性 | 不重复确认父项 | 原F411/CDC库、最终新扫描、兼容HTML | 缺标签与显式UNKNOWN、叶风险/成员关系、原件/包往返 | 原容器仅汇总合同 | 旧库deep及派生、实际UI、v3三全量/353对象逐JSON对照 | F41142→38、CDC225→205；新facts显式CONTAINER，未知/疑似叶完整保留；HTML文件视觉受阻 | continuation-q109.md、continuation-final-projects-v3.md | 候选范围已通过；最终待Q205 |
| 物理上下文覆盖 | 不误证NMI/HF安全或丢入口 | context_graph→physical→protection | 配置与自动同id、真实slot2/3、后续split碰撞 | ARM ABI及真实编译/重定位、来源证据不被抹去 | 原10例、共同producer/normalize回归与独立review | Q205已实证错误SAFE，正在最小修复；旧v3不能替代修复后验收 | 问题台账、q201-real-vector-manual-override.json | 已失败，严重阻断 |
| 大型完整扫描 | 完整目标分析及发布 | INAV MATEKH743 canonical-published | 388TU闭包、构建/依赖/最终SQLite | 当前完整扫描和发布合同 | 真16GiB Windows Job、无缓存新根 | 74与1b两轮为协调引擎修复正式停止130；未发布 | continuation.md、两观察器execution.json | 尚未验证 |
| 原生缩放 | 常用页面及系统缩放 | Computer Use | Windows实际浏览器缩放 | 必须真原生操作 | 工具无法可靠确定URL自动停止 | 未绕过；视口变化不能替代缩放 | continuation-ui.md | 环境阻塞 |

## 首轮覆盖记录

| 功能或模块 | 用户目标 | 实际入口 | 关键场景 | 预期依据 | 验证方式 | 实际结果 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 启动与 CLI | 找到入口并启动 | ECRA.cmd、run_ecra.py ui、CLI help | 独立数据根、无.git、中文空格、仅系统PATH | README、实际help | 原生Windows源码与候选包启动 | 实际服务、页面均运行；包内Python3.10.9 | ui.md、delivery.md、cli-help.txt | 已通过 |
| 配置 | 配置工程和参数 | 工程向导、init、semantics.yaml | 新建/旧配置、相对路径、无效字段、外置配置 | 当前配置合同 | 四步页面+真实ARM init及表单回归 | Q302/Q303已修；旧配置不被静默改写 | ui.md、delivery.md；37项配置/预检查回归 | 已通过 |
| 构建与数据库 | 使用真实固件配置 | 预检查、scan | 相对toolchain、已有数据库、失败、实际ARM对象构建 | CMake实际选取、完整输入快照 | 真实CMake/ARM回归、页面已有库预检查 | Q301已修；新全扫重用既有真实数据库，未重建整固件 | delivery.md；test_build_preflight.py | 已通过 |
| 变量与存储身份 | 避免同名串项和漏项 | extractor→facts→详情 | global/static/field、作用域、alias | 已知代码语义 | AST样例、冲突与身份回归 | 83项基线、最终相关回归；不推导任意C++完整语义 | analysis.md | 已通过 |
| 上下文与风险 | 保留可行冲突 | static classification | 主循环/IRQ/旧值写回/NVIC/完整保护 | 架构事实与独立推理 | 原场景复现、真实向量表、邻接回归 | Q201严重误安全已修；未知/DMA等边界保留 | analysis.md；exception-mask-before/after.json | 已通过 |
| 分析覆盖 | 理解部分结果 | 覆盖与诊断、报告、任务页 | 失败TU、PARTIAL、容器与分类分母 | 独立覆盖合同 | 真实旧/新向导、工程与回归 | 旧F030四FAILED明确记录；新结果不宣称全安全；Q403已修 | ui-initial-db-coverage.json、ui.md、delivery.md | 已通过 |
| OpenCode传输与聚合 | 不丢静态证据或混淆技术失败 | review/review-failed、复核页 | 关闭、单项失败、超时、坏输出、自动推进、重试 | 已有核心决策合同 | 受控传输/SQLite账本/聚合矩阵 | Q202已修；技术失败不计安全，DONE证据不足保留原冲突 | analysis.md、state.md、final-integration-tests.log | 已通过 |
| 本轮真实联网OpenCode推理 | 核对实际模型判断 | 外部OpenCode | 真实源码/案例读取、完整冲突论证 | 需实际联网收据 | 本轮未调用外部执行器 | 合成响应与历史收据不作本轮推理通过 | analysis.md、限制记录 | 尚未验证 |
| 任务与恢复 | 停止后继续 | TaskManager、扫描任务 | 真停止/重试、坏JSON/日志/收据、复制崩溃 | 真实终态与输入验证 | 页面停止130→恢复、API重开、29项状态回归 | Q101–104已修；恢复命中2TU、重提取2TU、发布有效结果 | ui.md、state.md、11/12截图 | 已通过 |
| Diff与缓存关键合同 | 只看可信变化 | git_diff、full/diff、TU cache | 变量/宏/布局/调用变化、引擎失效、旧值写回 | 当前影响范围与版本绑定 | 小工程full/diff/缓存回归 | 56项执行，1项联网跳过；不继承大型Diff验收 | analysis.md、diff-stale-regression.log | 已通过 |
| 大型原生Diff/恢复整轮 | 确认大工程完整流程 | INAV全量/Diff/恢复 | 完整目标闭包、完整证据对照 | 原发布门禁 | 当前代表TU和历史门禁核对 | 本轮仅两TU，整轮仍缺；历史长耗时不冒充通过 | delivery.md | 尚未验证 |
| 人工确认 | 签署、更正、继续 | 人工页/历史 | 连续处理、写锁失败/重试、退出继续、撤销/并发 | append-only事件、expected_heads | 真实浏览器+服务重启+数据回归 | 签署后统计一致、草稿不丢、无状态注入；撤销/冲突有自动回归 | ui.md、independent-ui.md、state.md | 已通过 |
| 项目与证据隔离 | 不误继承结论 | 结果选择、历史、绑定 | 同名/跨项目、证据改变、旧报告 | Project/Scan/Symbol/fingerprint | 多项目实际扫描与绑定/继承回归 | 新旧扫描独立、原工程/原确认保留 | delivery.md、state.md、final-integration-tests.log | 已通过 |
| 结果与导出 | 查看和交接 | 概览/详情/标准包/增量 | 统计一致、包往返、绑定拒绝 | 同一投影和原子归档 | 实际查询与包/人工回归；包内导出见ui.md | 原始静态/AI/人工来源分开；导入失败保留原件 | analysis.md、ui.md、最终联合回归 | 已通过 |
| 界面阅读与导航 | 顺畅阅读证据 | Studio真实界面 | 搜索、链路、源码、多证据、表单/保存/继续 | 业务目标+真实画面 | 两名检查者、1366×768/1920×1080视口 | Q401已修；独立操作未确认新增遮挡/状态缺陷 | independent-ui.md、ui.md、视口截图 | 已通过 |
| 输入及输出边界 | 特殊输入不破坏数据 | 参数、Vue/HTML、SQLite/JSON | 中文/空格/引号、HTML转义、写锁/磁盘满映射、损坏收据 | 原子保存与安全转义合同 | 真实路径/写锁+相关回归 | Q402指引已修；不声称模拟了断电或硬件损坏 | state.md、ui.md、API/包回归 | 已通过 |
| 性能稳定性（本轮规模） | 多次运行可完成 | 三工程及查询 | 资源采样、连续扫描/停止、长列表 | 相同输入实际记录 | 实际耗时/资源与任务资源记录 | 只报告实测；未实施或宣称性能优化 | delivery.md、任务日志 | 已通过 |
| 便携候选 | 无开发环境启动 | 新候选ECRA.cmd | 完整v91独立复制补丁、无.git、中文空格、仅系统PATH | 实际包和依赖清单 | 全哈希、包内41测试、真实页面；ZIP另单列 | 阶段目录真实启动；不冒充新跑完整build_portable | delivery.md、包收据、ui.md | 已通过 |
| ZIP解压后最终后验 | 验证成品一致 | 本轮独立ZIP | CRC、逐文件hash、解压后启动 | 最终候选清单 | 封包后实际校验和GUI继续 | 32,988内容文件校验一致，无.git；仅系统PATH启动、原3事件保留、继续5项正常 | postflight.md及最终后验收据 | 已通过 |
| 文档与升级 | 命令/入口与配置一致 | README、config注释、操作指南 | Python、--config、依赖、独立配置/数据保留 | 当前实现及真实帮助 | 链接核对、命令和配置回归 | Q001/Q303–305修正；历史报告和原dist未覆盖 | delivery.md、issues.md | 已通过 |
| 独立真实工程全扫 | 验证集成与边界 | F030/F411/STM32CubeF4 CDC | 三独立来源、不同CPU与构建输入 | 固定提交/许可证/真实数据库 | 最终引擎74c0…分别重扫 | 三项已完成，run2/status0/report2，输入不变、库完整；保留INCOMPLETE及待办 | delivery.md、real-projects-final.json | 已通过 |
| 兼容HTML离线阅读 | 无服务查看旧格式 | --legacy-output、file://index.html | 搜索/空结果、展开调用/访问、重开 | 当前显式兼容合同 | 真实F030生成、两尺寸实际file://操作 | 离线阅读与未启用模型提示正常 | legacy.md及其截图 | 已通过 |
| 兼容HTML人工签署 | 在旧页保存确认 | 当前无此接口 | 不属于现有承诺 | workspace-migration.md明确合同 | 实际界面与文档核对 | 无签署持久化，使用Studio | legacy.md | 不适用 |
| 大型裸机代表TU | 检查大型实际输入 | INAV MATEKH743 | 390条目标闭包、time.c/fc_core.c | 固定源码/真实参数 | 最终引擎实际提取与原输入不变检查 | 两个TU均PARSED；不是全工程通过 | delivery.md、INAV限定范围收据 | 已通过 |
| 原生缩放/新物理电脑 | 验证其它显示/运行环境 | Windows DPI、浏览器缩放、干净离线电脑 | 实际OS与页面缩放、32GB机器 | 不能用视口/开发机替代 | 本轮未改变系统设置或新电脑 | 只验证实际Windows当前缩放下的两种视口 | independent-ui.md、delivery.md | 尚未验证 |
