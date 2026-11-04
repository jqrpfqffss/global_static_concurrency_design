# 当前功能阶段包 v60：源码、真实流程及未完成门禁

2026-11-05，当前可审核的**功能阶段候选包**为v60，替代v37作为最近实际验证的功能交付；不是完整发布/G1–G8全通过声明。程序对应干净`c374ebc94cb1bc6818b6002c311531c9e0b2be5d`，包含确认继承、整根搬迁、显式数据库未提交Diff、原生复核逐对象读取、正确任务计数及100号初始化停止修复。

- 启动：`H:/ECRAStudio-build-20261105-studio-v60/ECRA-Portable/ECRA.cmd`
- 完整ZIP：`H:/ECRAStudio-build-20261105-studio-v60/ECRA-Portable.zip`，771,044,698B。
- ZIP SHA256：`f7e7b20c00512a1f9199ac0a44ecd4b0a079a67a20eeb1e7f12da4bc743cd868`。
- [总封存收据](acceptance/portable-studio-v60.json)：143个应用/前端/样例/依赖声明与干净源码逐字节一致；全部32,031个分发文件在真实操作后与完整manifest一致，ZIP SHA未变。

## 实际验证

| 场景 | 结果及明确范围 | 证据 |
|---|---|---|
| Full Portable原目录与中文ZIP解压 | 各27条实际版本/依赖/PE DLL/MinGW C++/Ninja/真实ARM CMake与扫描/CLI命令，通过各自原验收。预期INCOMPLETE退出2仍保留，不刷成0；包含完整MinGit及许可证，产品无Node/OpenCode | [目录](acceptance/portable-v60-uncompressed.json)、[ZIP](acceptance/portable-v60-zip-extracted.json) |
| 来源/构建 | 从原v58完整验证的锁定运行库/工具独立复制到新目录，只替换本阶段已验证的`workspace.py`，重建完整manifest，再执行两次全部原Portable检查。旧包不修改。总构建512.453秒，不作提速比较 | [构建](acceptance/portable-v60-assembly.json)、[实际重建脚本](acceptance/portable-v60-assembly-recipe.py.txt) |
| 实际ECRA.cmd | Windows-only PATH、无关中文CWD、独立LOCALAPPDATA；服务实际运行包内Python3.10.9；真实Chrome教学样例、源码/确认及资源不变，4组通过，无外部页面请求 | [启动](acceptance/portable-v60-startup.json)、[截图](ui/screenshots/portable-v60/startup) |
| 真正F030原生 | 包内Python3.10.9新扫描，22.985秒；43个原文件内容/大小/mtime不变；保留原2PARSED/2PARTIAL及INCOMPLETE。为保持原实际编译参数，**仅本次私有验证profile明确允许原已获准外部ARM编译器**；内置编译器由前述27条另验，不冒称这次F030完全脱离原工具链 | [原生](acceptance/portable-v60-f030-native.json) |
| 原生复核/停止/重试 | 真实包内服务/受监督worker与1366×768 Chrome：停止→重试→6/6 TECH_FAILED→仅失败重试保留历史→完整Packet→完整包往返，静态/人工/原件/程序资产不变。模型命令明确不存在，未进行模型推理 | [复核](acceptance/portable-v60-review-ui.json)、[计数截图](ui/screenshots/portable-v60/review/02-real-review-failures-count.png) |
| 确认可靠继承 | 包内两次真正F030原生完整事实相同；GUI沿用原来源/零本轮伪造事件、撤销/重载、独立全包+增量幂等，3组通过 | [继承](acceptance/portable-v60-inheritance-ui.json)、[原来源](ui/screenshots/portable-v60/inheritance/01-inherited-source.png) |
| 整套数据复制与恢复 | 包内F030→真实GUI完整复制→旧私有根离线→新根确认/包往返/输入重验→真实停止任务重试，4组通过。此次同一机器H盘两个中文根；不能称物理第二电脑或再次H/I跨盘实测 | [搬迁](acceptance/portable-v60-transfer-ui.json)、[截图](ui/screenshots/portable-v60/transfer) |
| 未提交版本对比 | **自建4TU真实ARM/Clang测试工程，非G2**；包内四步保存/Git版本核对、捕获中安全停止、重试、工作字节含实际未跟踪头、完整Diff/独立全量facts0差、真正无缓存4TU verify_against_full、检查点刷新及全包，4组通过 | [未提交Diff](acceptance/portable-v60-dirty-ui.json)、[工作字节](ui/screenshots/portable-v60/dirty/01-real-git-working-preview.png) |

这些是分组真实操作，不与全套单元测试或其他重复组相加。Playwright/Chrome为外部测试控制器，未装入程序。额外嵌入式控制器检查全部已加载`ecra.*`都来自实际包内；各服务和worker独立从包内解释器启动，没有用仓库引擎代替打包程序。

## 保留的拒绝、差异与解释

首次v57构建漏传可选MinGit，已[停止并保留](acceptance/portable-v57-omitted-git-stopped.json)，未提升为当前包。v58目录/ZIP工具链均通过，但真实停止暴露归属pending缺陷，按100号修复，原失败保留。

直接复核开发环境检查点被[包内环境门禁正确拒绝](acceptance/portable-v60-old-environment-rejected.json)，没有篡改指纹。第一次用原显式数据库在Portable新扫描时，[原外部编译器未声明允许而拒绝](acceptance/portable-v60-unapproved-external-driver-rejected.json)，没有自动替换编译器/参数或放宽产品门禁。随后只给私有测试profile明确设置既有`analysis.allow_external_toolchain: true`，用同一获准原始编译器生成包内自己的新检查点后才复核。原编译器与内置同版本二进制SHA均为`76aef3a90269c5dd0b2940f5cdf9b387e8ba114a3213c335ff4535665d4b29ac`。

[原严格跨环境比较](acceptance/portable-v60-f030-strict-cross-runtime-report-different.json)事实根0差，**报告严格比较FAIL保留**：Portable沿用原`compilation.py:553–561,621–622`，额外记录实际编译器和external_tools，两组从空数组变为真实审计记录。[完整逐字段审计](acceptance/portable-v60-report-metadata-audit.json)列出这两组，以及既有比较合同已声明的4项时间/指纹/输出位置运行信封差异；无其他差异。没有修改比较器、过滤掉真实静态证据或把原FAIL改成PASS。100号同运行环境新旧F030的完整facts/report0差仍为独立依据，不能把这个不同权限/运行环境的包内比较称为“全部报告字段相同”。

## 回归与未完成

修复前读路径完整冻结v54：1508项为1506PASS/2联网SKIP，2714.123秒；任务进度v55专项172项为171PASS/1联网SKIP；停止修复v59的23/32两组全部PASS，真实原路径F030完整0/0和上述包内操作另验。**干净c374ebc完整冻结v61（3792文件，清单SHA256 `2f84ee1ae5a1aa0965472e737dbef5060cd8015873939faa6f767ccb1ae07dd4`）的当前1512项全套正在运行，尚无最终结果，不能宣称已通过。**其日志在`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/full-regression-studio-v61.log`，最终收据为同目录`full-regression-studio-v61.json`。

仍未完成：大Diff基准/全量校验及全局恢复的全图读取；可选AI与新扫描生产者联合峰值；CMake未提交构建；dirty绝对视图跨根重放。旧schema兼容收据仍可能整包解码。其他G2用户延期；新本版INAV原生全量/完整Diff、物理32GB、干净离线/第二电脑、原生系统DPI、真实联网模型、工程师UAT及G1–G8整体均未通过，不把自动化GUI等同真人体验或硬件复现。

库存/目录/原固件持续保留。若升级后旧检查点绑定的引擎或运行环境变化，应按真实错误重新扫描；旧归档仍可查看和继续人工确认，不手工替换检查点摘要。
