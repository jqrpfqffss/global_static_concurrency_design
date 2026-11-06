# CMake未提交输入、停止与恢复：逐版验收

当前起点为`optimize_ccc@a76a180`，实现由Codex直接完成。没有改`config/semantics.yaml`、分析器、原摘要/比较及影响传播规则。冻结v76清单SHA为`0c69be750c09044dc93c3c383a37193d8c2ecac11bac84c186c682b5df5bfbca`；后续v77修补包内CMake 3.29内建Ninja版本探测并加入无基准完整扫描测试，4022文件清单SHA为`f7f3d0582fe429b515a4640e148223a92d70af471ef70ac906a55783b4a3e97d`。这份记录承接[117号准入合同](117-cmake-working-input-contract.md)，不等于全部CMake脚本均可安全固定。

| 阶段 | 实现的核心功能 | 变更文件 | 场景/测试 | 结果 | 证据 |
|---|---|---|---|---|---|
| Phase 2/4 | 真实Windows/Ninja双构建，保留原逻辑路径与全部编译参数；固定当前工作字节、生成头/C文件及SDK | `working_cmake.py`、`guarded_cmake.py`、`dirty_inputs.py`、`working_compiler_view.py` | U03/U04限定；真实ARM三个TU，基准WIDTH=1、索引=2、工作区=3 | v74实际流程PASS；当前全套待最终收据 | [v74原日志](acceptance/working-cmake-v74-failed.log)、[Chrome收据](acceptance/browser-working-cmake-v74.json) |
| Phase 2/4 | 两个实际TU提交后中断，恢复复用旧配置/生成目录/SDK，完整核对原输入；不重新配置当前侧 | `working_checkpoint.py`、`task_worker.py`、`tasks.py`、`frozen_scan.py` | U08；实际缓存2命中/1重新提取，独立无缓存三TU全量核对；保存后刷新不改静态库 | v74该实际用例PASS，不把整组102项称PASS | 同上；`test_working_cmake.py`、`test_working_checkpoint.py` |
| Phase 4 | 真实GUI开始、安全停止、恢复、打开shared访问证据；完整包独立导入 | `App.vue`、`GitVersions.vue`、`TaskCenter.vue`、构建后静态资源 | U04/U08/U12/U19限定1366×768和1600×900；profile通过真实API预置，不计四步向导 | v74八组PASS，794.015秒；39个原文件内容/大小/mtime不变，0外部请求/控制台错误 | [收据](acceptance/browser-working-cmake-v74.json)、[停止截图](ui/screenshots/working-cmake-v74/00-safe-stopped.png)、[证据截图](ui/screenshots/working-cmake-v74/02-working-diff-evidence-1366.png) |
| Phase 2/4 | 拒绝写原源码、ABA变化、目录替换、未证明命令/网络/显式闭包；审计由父进程管道写Medium目录，Low进程不能擦除 | `guarded_cmake.py`、`working_cmake.py`、`write_guard.py`、`scan_stop.py` | H1/H2/H6、G5限定；真实低完整性进程负例及输入污染/SDK/准备结果损坏 | 专项实际用例PASS；完整G5不据此关闭 | 上述原日志、`tests/test_working_cmake.py` |
| 修复回归 | 无关的旧构建别名失效不阻断本轮；实际用到的已替换别名仍必须拒绝 | `portable.py`、`working_cmake.py`及相关断言 | v76独立冻结9项，源与副本SHA不变 | PASS，11.214秒 | [收据](acceptance/working-cmake-regressions-v76.json)、[日志](acceptance/working-cmake-regressions-v76.log) |
| 完整扫描补验 | 无比较基准，使用同一封存当前构建完成三个TU全量及保存后刷新；禁止重新配置 | `tests/test_working_cmake_full.py`、冻结v76运行时 | U04/U06局部；实际生成头WIDTH=3、marker=12字节，原件不变 | PASS，889.333秒，独立1项；不混计进v76的1562项 | [补充收据](acceptance/cmake-working-full-v76-supplement.json)、[日志](acceptance/cmake-working-full-v76-supplement.log) |
| Phase 6 已收齐 | 冻结v76完整1562项，独立源与测试副本3995文件SHA不变 | v76修改集，尚不含包内Ninja探测修补或121号路径绑定 | 1560 PASS/2联网opt-in SKIP，5049.975秒，0失败/错误 | PASS_SCOPED | [最终收据](acceptance/full-regression-studio-v76-final.json)、[原日志](acceptance/full-regression-studio-v76.log) |
| 包内真实GUI | v77内嵌解释器/工具/离线Git，安全停止后恢复及完整包导入 | 实际Chrome，原源/Git内容/大小/mtime不变；不计向导或人工UAT | 8组PASS，包内全部29专项及总载荷后验仍在运行 | PASS_SCOPED，不能称整个包验收通过 | [收据](acceptance/browser-working-cmake-v77.json)、[截图](ui/screenshots/working-cmake-v77/02-working-diff-evidence-1366.png) |
| 无原件Viewer | 暂时移走原固件根及原构建/SDK/任务数据根，仅导入的独立完整包可用；真实Chrome查看归档main.c | U12/U19限定本机，源命名空间最终恢复、导入静态库SHA不变、0外部请求 | 3组PASS；首两轮控制器API名称/ARIA角色错误保留，不是产品故障 | PASS_SCOPED，不计物理离线电脑 | [最终收据](acceptance/offline-cmake-viewer-v77.json)、[原控制器错误1](acceptance/offline-cmake-viewer-v77-controller-first-failed.json)、[错误2](acceptance/offline-cmake-viewer-v77-controller-second-failed.json)、[截图](ui/screenshots/working-cmake-v77/04-imported-source-without-originals.png) |
| Phase 6 在途 | v77完整1563项、v78完整1568项；包内29/34专项及完整载荷后验 | 独立冻结副本；121号路径绑定另有14专项、原F030全部字段0差及INAV 388TU预检查 | RUNNING / NOT_VERIFIED，尚未收齐 | 对应工作根`full-regression-studio-v77.json`、`full-regression-studio-v78.json`及`portable-working-v77/acceptance.json`、`portable-working-v78/acceptance.json`须实际最终PASS后更新 |

## 原始失败与修复边界

v73专项79项为76 PASS/3 FAIL：捕获父目录被合法基准消费者修改而误报、目录锁的访问权限不足以阻止重命名、旧提示断言。浏览器另因WinGet Ninja链接未解析而失败，原记录见[118号](118-memory-comparison-final-acceptance.md)。监视范围改为不可变编译副本，原源码/Git仍在每屏障完整复验，发布末次SDK/副本完整复验没有取消；目录锁改为实际阻止重命名的读取句柄，工具路径解析只用于身份校验，没有改编译ARGV。

v74专项102项为101 PASS/1 FAIL，唯一失败是旧测试匹配大写`CMake`，实际准入错误字段为`analysis.cmake.target`；已精确匹配该字段并[单独复跑通过](acceptance/working-cmake-assertion-v75.json)。原[FAIL收据](acceptance/working-cmake-v74-failed.json)不覆盖。v74→v75核心运行时文件相同的[补充核对](acceptance/working-cmake-v74-v75-runtime.json)不能代替全量测试。

v75完整1561项为1556 PASS/2联网opt-in SKIP/2 FAIL/1 ERROR，2949.744秒，[原收据](acceptance/full-regression-studio-v75-failed.json)及[原日志](acceptance/full-regression-studio-v75-failed.log)保留。其中真实代码缺陷是进程内无关旧别名残留导致新CMake固定失败；另两项仍断言所有CMake都应阻断，现仅对未准入的混合显式数据库/自动配置/补充模式检查准确错误。没有删除测试、放宽实际输入校验或比较器。

v76首次打包漏传`-GitSource`，基础目录/中文ZIP各27项虽PASS，包内28专项却为25 PASS/2 FAIL/1 ERROR，真实Chrome在任务准入失败。此包不作为功能候选；原目录`H:/ECRAStudio-build-20261106-studio-v76`及[失败收据](acceptance/portable-working-v76-no-git-failed.json)保留。补上完整MinGit后的独立`H:/ECRAStudio-build-20261106-studio-v76-git`仍有真实兼容问题：CMake 3.29的内建GNU模块调用Ninja查询版本，被原审计阻断，包内28项为27 PASS/1 ERROR，Chrome也失败，[原收据](acceptance/portable-working-v76-builtin-probe-failed.json)与[日志](acceptance/portable-working-v76-builtin-probe-failed.log)保留。v77只放行该准确内建文件、已配置Ninja路径及完整固定`--version`查询；其它来源、多COMMAND、额外目标参数仍拒绝。新包输出`H:/ECRAStudio-build-20261106-studio-v77`，不覆盖失败包；最终流程以新收据为准。

## 界面与证据范围

沿用已有九导航、核心页面、布局和设计规格，仅更新CMake能力说明、复用原检查点的来源提示，以及Diff“全部存储对象”为分母、“列表按当前筛选”的文字。没有添加演示页面或新判定规则。较早截图中的3个总影响项和1个shared项来自不同筛选范围，当前增加口径说明；旧截图保持原样，不改成新版本证据。

v74浏览器原收据的`traces`为空，是收集器只找ZIP而Playwright输出原始trace/network/resources造成。原收据未改；[独立补充](acceptance/browser-working-cmake-v74-trace.json)逐个校验并打包了2280个实际文件。原ZIP为工作根下`browser-working-cmake-v74/browser-trace.zip`，56,571,446字节，SHA256为`39a913d3a6f1d6804e59bf9b335aa81b5958abda6da10e44926dbdde898dc2b2`。大ZIP留在独立验收目录，仓库保留全部清单及哈希。新收集器记录所有真实trace文件。

准入仍限Windows/Ninja、`compile_database: auto`、外置构建和`build_closure_only`。未证明的自定义生成进程、下载、try_run、外部GLOB/复制、显式ELF/MAP混合闭包明确失败，不能为了接受配置而省略输入。停止后若原源码/索引、SDK、配置或实现变化，旧完整检查点不能静默换成新构建；用户需从工程配置发起新扫描。

其它G2工程按用户要求延期；32GB物理机、第二台干净离线电脑、真实Windows DPI、人工UAT、当前活数据与整轮大型Diff/恢复内存仍分别待验。跨环境严格报告FAIL及其全部字段审计沿用[114号](114-portable-v71-typed-cold-reader-acceptance.md)，没有改比较规则。自动化GUI通过不等于真实工程师满意度或硬件验证。

本轮手动审计曾误用允许刷新索引的`git status`，改变黄金副本`.git/index`缓存字节/时间，首次4123项核对因此FAIL；这不是产品扫描写入，也不能隐去或称“从未改变”。[偏差记录](acceptance/inav-manual-git-index-refresh-v76.json)与[首次失败](acceptance/inav-manual-git-index-refresh-v76-failed-postflight.json)保留。随后在完全独立仓库只读引用原对象，以`read-tree`重建索引，候选字节SHA严格匹配原冻结清单`2dc9337150c18eab6c83d52bab9a2f931e801c8fa31788ddc359c5952b673325`后才恢复原字节和时间，[恢复证明](acceptance/inav-manual-git-index-refresh-v76-exact-recovery.json)及[4123项完整后验](acceptance/inav-manual-git-index-refresh-v76-input-postflight.json)均PASS。原清单/state/比较器未修改，没有靠重置指纹掩盖差异；后续原仓库查询均禁用可选写锁。

本机工作根：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`。复跑开发脚本：`py -3.10 -B -X utf8 scripts/validate_working_cmake_ui.py --engine <独立冻结引擎或完整Portable> --work <新的外置验收目录> --exercise-retry`；Portable验收必须以包内`runtime/python.exe`执行，并提供完整离线Git。开发控制机的Chrome/npx已缓存，产品运行端不需要Node。
