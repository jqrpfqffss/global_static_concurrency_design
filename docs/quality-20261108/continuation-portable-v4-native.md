# 离线重建包：真实F030链路与可选MinGit差异检查

本记录验证已正式离线构建、压缩、中文空格解压后的v4包的后端及工具链，不把旧包源码覆盖副本称为新构建。包为 `H:/ECRA-quality-20261108-offline-build-v4/解压 终验/ECRA-Portable`，ZIP 785,690,591字节，SHA `f91fa403252d1ff2eb533c83eb5d6558f6f3f2fe55835d977869a80b28003586`，core `63a5cff7e9babcf0a4982726f68ca8390ad5f840b92d31d41e511a859d857710`。正式构建和首次解压验收见根收据 `output/quality-20261108/continuation/extracted-v4-receipt.json`；本检查没有重新下载、安装开发依赖或修改包内容。

**交付状态边界：** 根浏览器实测另发现旧v4 CallNode把GNU alias关系标成普通调用，显示修复进入UI-only v5；本记录不把旧v4界面称为最终界面，也不代表大型/工作区sourceguard等全部发布门禁通过。根负责最新界面实操、重新封包及字节继承核对。

## 真正包内运行与F030完整构建

初始PATH只有 `C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem`。控制器实际由新包的 `runtime/python.exe -B` 启动，Python为3.10.9；编译器、标准库、libclang、API服务和CLI均从该包解析，realpath核对在同一解压根内。未调用host Python/GCC/Git，也未沿用旧包compiler或libclang路径。

复用已固定来源的真实STM32F030工程，在新的中文空格源码副本逐对象编译4C，按原build.sh旗标和真实linker.ld完整链接ELF/MAP，再把实际成功命令写为CDB；未手填一个替代真实构建的数据库。4次compile、1次完整link、两次新包objcopy均退出0，ARM EXEC头有效；新flash BIN与此前完整真实固件逐SHA相同（ELF调试路径可不同）。原工程文件、源码副本和包Python源均保持原SHA，包文件清单无新增。

通过实际 `ECRA.cmd run → status --json → report → status --json`，返回2/0/2/0；run约67.766秒，后续约3.906/11.297/4.219秒。4TU仍为2PARSED/2PARTIAL/0FAILED，原Clang GNU naked等能力诊断保留；15盘点=7SAFE+1SUSPECT+2CONTAINER+5NON_STORAGE，待办1。systicks共享风险保持SUSPECT，报告刷新前后静态scan.db字节不变，manifest为STATIC_VALIDATED。

同一包内uvicorn与stdlib urllib启动实际loopback HTTP服务，扫描列表/summary/systicks请求均HTTP200，风险及发布状态与CLI一致；不需要把TestClient/httpx等开发依赖装入用户包。服务线程已正常退出。这是实际API检查，不代替根的浏览器视觉验收。

原生工作根 `H:/ECRA-quality-20261108/continuation-packaged-f030-v4-v2`，数据在真正工程外的独立根 `H:/ECRA-quality-20261108/continuation-packaged-f030-v4-v2-data`，扫描ID `5756fef0f3a64058a37100350fcaa642`。完整日志/返回码/工具SHA/CDB/ELF/MAP/API响应在 `output/quality-20261108/continuation/portable-v4-f030-native-v2/receipt.json` 及同目录文件。

## 有界MinGit差异样例

此项只验证新包可选Git组件、路径和公开Diff链路，不计作第四个独立公开固件工程。包内Git为2.56.0.windows.3，exe和exec-path均核对位于该包tools/git/ucrt64内，关闭测试进程对host Git配置/路径的继承；没有修改主机全局设置。

在独立中文空格目录由本包MinGit init并建立两个真实提交，由真实CMake/Ninja生成两C的ARM ELF/MAP/CDB。基础版在所有foreground `shared++` 读改写窗口前后执行真实 `cpsid i` / `cpsie i`；普通IRQ的实际C向量槽为21。当前版只删除这两个屏蔽调用。独立代码判断是：在该IRQ可能发生的模型下，基础版完整PRIMASK窗口可证明安全；当前版IRQ可介入读旧值/写回窗口，volatile与32位字长均不消除丢更新风险。

| 项目 | 实际结果 |
|---|---|
| 固定base | `43c005eae2705ff79b9b9873016d44ef7f45293d` |
| 固定current/HEAD | `54f5da318c1c90424146918135d010391dbc22bb` |
| 基础版公开full | shared为SAFE_PROVEN/EFFECTIVE，真实反汇编有cpsid/cpsie；约37.906秒 |
| 当前版公开 `--scan-mode diff` | shared为SUSPECT/NOT_FOUND，确实选中c:@shared；pin的base/head SHA和来源正确；约106.485秒 |
| 产品verify_against_full | PASSED，重新提取2TU、比较5变量，分类/语义差异0 |
| 额外独立当前full | shared为SUSPECT/NOT_FOUND，除Diff展示字段impact外整个变量证据对象相同；约35.875秒 |
| 工作区策略 | include_uncommitted始终false，未改成包含未提交修改；固定current提交之后源码字节、HEAD和Git工作区干净状态保持 |

三个公开run都真实返回2/INCOMPLETE，其他覆盖边界没有隐藏；没有把单变量SAFE称作全工程完整分析。每次正式TU缓存均0命中/2重新提取，未以历史状态注入或手工CDB代替冷提取。源码和Git工作根 `H:/ECRA-quality-20261108/continuation-packaged-diff-v4`，外部数据根 `H:/ECRA-quality-20261108/continuation-packaged-diff-v4-data`。实际所有Git/CLI命令、源码位置和提交身份、真实CDB/ELF/MAP、反汇编、保护变化、selected证据及独立full对照见 `output/quality-20261108/continuation/portable-v4-diff-smoke/receipt.json` 和同目录文件。

## 原始失败与后验

F030首轮原生编译/链接已全部成功，但QA控制器将数据根放在含实际CDB/ELF的构建目录下面，产品正确拒绝为exit3，并给出“请选择工程外独立目录”的可执行提示。原 `portable-v4-f030-native/receipt.json`、原配置和0-run日志均保留；第二轮只修控制器目录布局，在全新隔离根重跑，没有改产品边界或放宽期望。根另发现外层cmd/Popen嵌套quoting会把引号传成字面内容，本控制器在第一次启动前已改为cwd=package并调用相对ECRA.cmd；该修正只属于QA启动方式。

最终只针对本轮风险做后验：原ZIP对应全部32,692文件（32,691内容条目加FILES.sha256.json自身）名字/大小完全相同，无新增、缺失或尺寸变化；实际使用的Git/CMake/Ninja/ARM GCC SHA不变。4个新静态库在操作后SHA完全不变，deep图/投影完整性通过，缓存冷提取成立。root正式打包器已在构建与解压两份做过完整全文件SHA，本处未重复第三次全工具链哈希。后验收据 `output/quality-20261108/continuation/portable-v4-native-postflight.json`；不可变数据库内UNVERIFIED与清单STATIC_VALIDATED分别属于存储/发布协议，不混为未发布。
