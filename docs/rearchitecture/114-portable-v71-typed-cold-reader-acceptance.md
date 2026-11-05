# v71修正版候选：实际封存验收

本候选包含`feceb2736dcd410feeef19e58f0fb74f86e76dd6`的原生冷基准读取及严格字典键修补，144个应用/依赖声明文件与干净冻结v71逐字节一致。冻结manifest SHA为`a662801c4592a6fca1f997f7411b9cae6a2b7ff2456ac4022a89543ef28b4d04`。原摘要、规范化和影响判断未改，见[113号](113-typed-native-cold-reader-acceptance.md)。这是可实际使用的开发候选，完整重构及G1–G8总门禁仍未通过。

实际双击入口：`H:/ECRAStudio-build-20261106-studio-v71/ECRA-Portable/ECRA.cmd`。完整ZIP：`H:/ECRAStudio-build-20261106-studio-v71/ECRA-Portable.zip`，771,065,448B，SHA256 **5093b8dbfbf76d494384fd15d44af8ad10468933a3cceda2180072e18b0fd768**。原v67和未推广v70均保留；v70未进入运行验收的原因及原记录见[113号](113-typed-native-cold-reader-acceptance.md)。

| 阶段 | 核心功能 | 文件/实际版本 | 测试/场景ID | 结果 | 对应证据 |
|---|---|---|---|---|---|
| 打包及工具 | 新目录和中文路径ZIP解压各自执行原验证器，锁定Python/PE/ARM/CMake/Ninja/CLI；144应用源一致 | `ecra/native_diff_summary.py`、原打包/依赖清单、冻结feceb27 | G8限定本机，各27条命令 | PASS；不替代干净离线机 | [组装](acceptance/portable-v71-assembly.json)、[目录](acceptance/portable-v71-directory.json)、[中文ZIP](acceptance/portable-v71-zip-chinese.json)、[实际配方](acceptance/portable-v71-assembly-recipe.py.txt) |
| 包内专项 | 原完整摘要全部字段、嵌套顺序/重复/类型、指针编码/非法引用、真实原生冷读/缓存/CMake宏4→8、独立无缓存对照、旧库保留及恢复门禁 | 包内Python3.10.9、包内ECRA模块 | 17项，非G2；不是包内完整1534全套 | PASS/0跳过 | [最终收据](acceptance/portable-native-reader-v71.json)、[包内测试控制器](acceptance/portable-v71-embedded-test-controller.py.txt) |
| 实际启动 | ECRA.cmd在Windows-only PATH/private LOCALAPPDATA启动，使用包内解释器；真实首次使用三动作和完整内置原生包导入 | 实际CMD启动器/真实服务/Chrome | U01，G8限定本机；4组 | PASS | [收据](acceptance/portable-startup-v71.json)、[初次页面](ui/screenshots/portable-v71/startup-01-actual-launcher-first-use.png) |
| 数据库Diff界面 | 可见按钮两次发起原生扫描，第二轮验证摘要命中，旧库/归档不变，打开shared访问证据，完整包独立导入后核对双根和基准摘要 | 包内Python/原Vue界面、实际自建2TU | U04/U06/U12/U19/U22限定1366×768；profile由真实API预置 | 5组PASS，124.782s | [收据](acceptance/portable-database-ui-v71.json)、[截图](ui/screenshots/portable-v71/database-03-shared-evidence.png) |
| CMake Diff界面 | 实际外置构建；配置宏1→2、两次按钮扫描；基准数组4→8、两版独立无缓存全量核对、旧库/完整包保护 | 同一包、真实CMake/Ninja/ARM、实际自建2TU | U04/U06/U08/U19限定；不计G2或未提交CMake | 5组PASS，152.422s | [收据](acceptance/portable-cmake-ui-v71.json)、[截图](ui/screenshots/portable-v71/cmake-03-shared-evidence.png)、[控制器](acceptance/portable-cmake-ui-v71-controller.py.txt) |
| 获准F030 | 原数据库/原绝对工具链参数不动，私有profile显式allow_external_toolchain=true；原43文件不变，原2 PARSED/2 PARTIAL保持 | 包内Python3.10.9、原工程 | G1事实完整对照；内置工具另由27项/CMake实测 | 原生PASS，24.797s；跨环境事实0差、严格报告FAIL保留 | [原生](acceptance/portable-native-f030-v71.json)、[完整严格对照](acceptance/portable-native-f030-v71-strict-comparison.json)、[全部差异审计](acceptance/portable-report-envelope-v71.json) |
| 完整封存 | 17专项及实际所有操作后，32,033个载荷文件SHA和清单自身SHA复验；实际共32,034文件，无清单外文件；ZIP SHA仍与组装相同 | 本次实际解压/原目录、FILES.sha256.json | G6/G8限定本机；前后完整性 | PASS | [最终收据](acceptance/portable-studio-v71.json)、[完整文件计数](acceptance/portable-v71-complete-file-count.json) |
| 当前全套与大型 | 前版1533已1531PASS/2联网SKIP/0失败，3889.461s；干净本版1534接续执行；大库原完整方法与首版新读对照在运行，修正版独立测量排队，最新冷扫描v68/冻结v66在运行 | 多份冻结源分开记账 | G1/G2/G3/G4/G5全范围 | 前版完整回归PASS；本版全套及大型NOT_VERIFIED | [前版收据](acceptance/full-regression-studio-v69-final.json)、[113号基准与任务](113-typed-native-cold-reader-acceptance.md)、外部各自最终收据待生成 |

包内全部ECRA模块路径由测试控制器核对，未用外部仓库模块代替。源码17专项与包内17专项是两份解释器环境的收据，不合算为34项完整回归。32,033载荷及清单SHA均在实际操作后核对，清单SHA为`2f67f2ca9d9806bd5433cae32c036ec9ee3e5b35f87e5df4e33aee11d86ecfb0`；总文件数包含这份清单。

跨环境F030严格报告FAIL保持原值。完整字段遍历差异恰为原bundle审计的compiler/external_tools两数组和既有执行信封4项，未解释差异0；原/包内ARM编译器二进制SHA相同。没有新增归一化/忽略规则，也没有替换原权威库或旧状态指纹。相同global环境的原生F030完整0/0见[111号](111-native-cold-diff-reader-stage.md)，不能把不同解释器/工具许可配置说成同一环境的原始报告全等。

确认继承、整根搬迁及未提交显式数据库流程沿用[101号v60](101-portable-v60-functional-acceptance.md)实机证明，相关程序文件本次逐字节保持；没有冒称在v71重新执行这些完整操作。v71另验了与冷摘要读取直接相关的标准完整包导入/旧归档保护。CMake配置由真实API预置和修改，不冒称验证了四步向导或未提交CMake构建等价性。

开发复跑：在新独立目录执行`scripts/validate_native_diff_cache_ui.py --engine <本包> --work <新目录>`（需以包内`runtime/python.exe -B -X utf8`启动；开发控制机需已缓存Playwright CLI/Chrome）；CMake控制器保存为.py后同样运行。包内17专项控制器保存为.py，在有对应冻结测试源的独立验收目录运行。普通用户双击ECRA.cmd即可，不需要这些开发命令/Node。

大型真实前/后Job/RSS/磁盘/标准包/耗时及完整事实差异在[113号](113-typed-native-cold-reader-acceptance.md)逐版本列出。首版大库冷摘要已完整生成778,008,324B，Job峰值1,629,368,320B，但原完整方法对照未结束；不提前给完整语义PASS，也不将它改标为本版feceb27。当前侧/双版compare/整轮Diff恢复资源、CMake未提交完整流程仍待继续；其它G2按用户要求待验，32GB物理机、第二台干净离线PC、真实模型联网、原生DPI与5–8人盲UAT未验。GUI自动化不是工程师满意度或目标板硬件复现证明。
