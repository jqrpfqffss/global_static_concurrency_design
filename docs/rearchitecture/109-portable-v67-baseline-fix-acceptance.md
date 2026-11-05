# v67原生Diff基准修复候选：实际包内验收

可双击入口：`H:/ECRAStudio-build-20261105-studio-v67/ECRA-Portable/ECRA.cmd`。

完整ZIP：`H:/ECRAStudio-build-20261105-studio-v67/ECRA-Portable.zip`，771,054,354字节，SHA-256 `747d7d2b70301e997b36330ce106a80bfa02a07bba41fdf807890cea89085998`。

这是**功能修复候选，完整重构/发布门禁仍未完成**。核心程序来自`b9858efb483b52f737de64831b543e640a8a3aec`，与冻结v66的143个核心文件逐一匹配；其余工具/依赖沿用已验证的v60锁定资产。完整32,032个分发文件在本页全部真实测试结束后再次比对，SHA全部不变。原包未覆盖，数据根继续独立。[封存收据](acceptance/portable-studio-v67.json)。

| 阶段 | 核心实现/范围 | 文件或入口 | 测试/场景 | 结果 | 证据 |
|---|---|---|---|---|---|
| 包与工具链 | 新目录及中文路径ZIP解压版，各27项原验证器检查；143核心文件匹配，全部文件测试后不变 | 新v67入口、原`validate_portable.py` | G8本机限定范围；PE/Python/ARM/CMake/资源/CLI | PASS | [目录](acceptance/portable-v67-uncompressed.json)、[中文ZIP](acceptance/portable-v67-zip-extracted.json) |
| 包内原生 | 包内Python **3.10.9**，所有ecra模块来自包；失效基准新库、原完整键/摘要、共享TU恢复、旧库/索引保留、损坏/非法索引/PARTIAL门禁 | `ecra/git_diff.py`、冻结8专项 | U04/U08、G1/G5/G6，真实ARM/CMake数组4→8及独立全量核对 | PASS，8项/0跳过；与源码8项为同组不同环境，不相加 | [收据](acceptance/portable-native-baseline-v67.json)、[日志](acceptance/portable-native-baseline-v67.log) |
| 实际启动 | 真ECRA.cmd、无关中文cwd、仅Windows系统PATH、私有LOCALAPPDATA、服务实际来自包内Python | `ECRA.cmd` | U01/G8；真实Chrome首屏/教学档案等4组；未做物理桌面双击 | PASS | [启动收据](acceptance/portable-startup-v67.json) |
| 包内数据库Diff界面 | 两次可见按钮发起扫描、第二轮摘要命中、打开shared访问证据，标准完整包独立导入 | 原Vue界面，包内服务 | U04/U06/U12/U19/U22限定1366×768；真实profile API预置 | PASS，5组/177.891s | [收据](acceptance/portable-database-ui-v67.json)、[截图](ui/screenshots/portable-v67/database-03-shared-evidence.png) |
| 包内CMake界面 | 实际CMake/Ninja/ARM外置构建，真实profile宏1→2，两次可见按钮扫描；基准数组4→8，两个版本均独立无缓存全量校验，旧库/归档不变及完整包导入 | 同一实际界面/服务；构建配置通过真实API准备和更新 | U04/U06/U08/U19，G1/G5/G6限定自建2TU | PASS，5组/213.687s；不计G2或配置编辑向导 | [收据](acceptance/portable-cmake-ui-v67.json)、[截图](ui/screenshots/portable-v67/cmake-03-shared-evidence.png)、[可复跑控制器](acceptance/portable-cmake-ui-v67-controller.py.txt) |
| 包内获准F030 | 原路径/原数据库/原工具链参数不动，私有验收profile显式allow_external_toolchain=true；原43文件不变，原2 PARSED/2 PARTIAL保持 | 包内Python、原F030源 | G1跨环境事实完整比较0差；内置工具另有27项及CMake原生验证 | 原生PASS；跨环境报告严格比较FAIL保留 | [原生](acceptance/portable-native-f030-v67.json)、[严格比较](acceptance/portable-native-f030-v67-strict-comparison.json)、[完整差异审计](acceptance/portable-report-envelope-v67.json) |
| 当前核心全套 | 冻结v66及独立副本各3855文件SHA不变，global Python3.10.11 | b9858ef相同核心代码；独立控制器另验 | 实际1525测试：1523 PASS / 2真实联网SKIP / 0 FAIL | PASS，3079.258s；不是包内1525全套 | [最终收据](acceptance/full-regression-studio-v66-final.json)、[完整日志](acceptance/full-regression-studio-v66.log) |
| 大型及完整发布 | 前轮冻结v62恢复已完成388 TU及全局分析，16566变量/3540候选，正在发布；完整G1/刷新/Packet尚待收据。v66最新冷原生等待该前轮证明 | 两份不同冻结源分开计量 | G1/G2/G3/G4 | NOT_VERIFIED | [当前状态](acceptance/current-validation-v67-progress.json) |

本页未改UI版式/颜色/导航。开发验收控制器在刷新后遇到Playwright的`f1e…`引用，原正则只接受`e…`；保留[首轮失败](acceptance/portable-cmake-ui-v67-first-failure.json)及[第二次失败](acceptance/portable-cmake-ui-v67-second-failure.json)，修正控制器为读取当前快照的完整引用后整套复跑通过。没有改软件/门禁/构建证据来让测试通过；此修正也同步到`scripts/validate_native_diff_cache_ui.py`。

跨环境F030严格报告FAIL没有改成PASS：原完整比较器及归一化规则未变。遍历全部报告字段，差异恰为原`bundle_root`条件分支新增的**compiler/external_tools两个审计数组**，另有既定执行信封4项；两份编译器二进制SHA相同，未解释差异0。当前global同环境F030完整事实/报告0差见[108号](108-immutable-native-baseline-acceptance.md)。不能将不同Python环境和私有工具许可配置称为同输入同环境的原始报告全等。

确认继承、整根搬迁和未提交显式数据库完整流程的上一版完整包实机验收仍见[101号v60](101-portable-v60-functional-acceptance.md)；相应程序文件本次逐字节保持，未冒称在v67重新执行全部这些流程。v67另行执行了与本次修改直接相关的标准完整包导入和档案摘要/事实/报告根校验。

剩余必须继续：**首次冷Diff摘要、当前侧及完整大工程后续操作的有界读取；CMake未提交修改完整流程；最新大型原生及G1–G8最终验收。** 其它G2工程按用户要求待验；32GB物理机、第二台干净离线电脑、真实联网模型、Windows原生DPI、5–8人盲UAT未验证。本机Windows-only PATH启动与真实GUI自动化不替代这些门禁。大型前后性能仅按[108号所引原范围](108-immutable-native-baseline-acceptance.md)保留，不把旧Packet成绩或本轮恢复计时称为最新整轮扫描/冷Diff成绩。

源码专项复现及冻结标识见108号。打包按[实际配方](acceptance/portable-v67-assembly-recipe.py.txt)从已验证v60独立复制，替换已验证git_diff文件、核对全部核心源、重新生成完整manifest并对目录/中文ZIP执行原验证器。CMake界面控制器保存为`.py`后用包内`runtime/python.exe -B -X utf8 <控制器.py> --engine <ECRA-Portable> --work <新的独立验收目录>`运行；开发控制机需要已缓存的Playwright CLI/Chrome，不进入用户产品依赖。普通用户直接运行ECRA.cmd。
