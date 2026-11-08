# 运行入口、便携交付与真实工程验证

本页保留首轮local补丁包与当时工程结果。当前正式V9包使用原脚本完整离线构建；最新位置、组件身份及工程复验见[当前 V9 验收](continuation-final-v9.md)。不把本页local包或74c0结果改标为当前版本。

本轮直接在 `optimize_ccc@fe27afe73596d98e1a21e3f28a2125d38d7272d0` 上检查，初始工作区干净。原 `dist/`、封存 v91、固件与黄金配置保留；没有发布或推送。

## 当前入口及交付边界

- 源码工作台：`py -3.10 -m pip install -r requirements-studio.txt`，然后 `py -3.10 run_ecra.py ui`；`requirements.txt` 仅覆盖静态 CLI。
- 便携工作台：解压完整目录后双击 `ECRA.cmd`，包内 Python 3.10.9、后端、离线页面和 CMake/Ninja/MinGW/Arm GCC；OpenCode 仍为外部安装项，不加入 Node、npm 或界面测试依赖。
- 默认结果是独立数据根 `scans/<扫描ID>/scan.db` 与独立 `reviews.db`；两个 HTML 仅属于显式 `--legacy-output`。浏览器标签关闭不会关闭服务。
- 当前旧 `dist/ECRA-Portable` 是 2026-10-20 / `4bca45d…`，不能代表本轮源码。原封存 v91 在 `H:/ECRAStudio-build-20261108-studio-v91`，程序绑定 `154f302…`；本轮候选另行复制补丁，不覆盖原件。

## 当前确认的问题

| 编号 | 影响及复现 | 根因与修复 | 复验 |
|---|---|---|---|
| Q001 | README 同段先称 Python3.10.9、后要求3.12.10，可能准备错误运行时 | 统一为实际 psd1/cp310/portable-lock 契约，说明新输出目录和拒绝覆盖 | Windows `prepare_portable_cache.ps1 -OfflineCheck` 真实退出0；CLI/UI帮助收据 |
| Q301 | 真实 ST CDC 工程已有数据库，合法 `CMAKE_TOOLCHAIN_FILE=cmake/arm.cmake` 却错误解析到工具目录，报输入变化退出3 | `cli.py` 快照遗漏 CMake 的 build 优先/source 后备相对基准；`compilation.cmake_toolchain_input` 统一解析，预检查相邻入口由主检查者同步修复 | 实际 CMake configure 在中文空格目录验证两种选取；真实修改选中 toolchain 仍使 InputSnapshot 拒绝；CDC 最终重扫结果见下表 |
| Q302 | 非 CMake 的 init 模板未启用系统头探测，真实 ARM GCC 数据库的 `stdint.h` 缺失；旧 F030 配置4/4 TU FAILED，仍有部分AST对象 | 只对新生成模板加入 `auto_system_includes:true`；保留已有配置的读取语义；向导新建默认由主检查者同步，旧导入配置不静默修改 | 实际 ARM GCC 编译含stdint全局变量→init外置配置→prepare→Clang PARSED；真实工程隔离配置显式启用后重扫 |
| Q303 | `init --config` 成功后给出的下一步命令丢失配置路径，照抄会选回默认工程 | 成功输出保留显式 `--config`，PowerShell路径单引号转义 | 外置路径含空格与单引号的真实init回归，两个后续命令均保留路径 |
| Q304 | README `--profile` 示例当前CLI实际退出2 | 按真实help改为已支持的 `--config`，说明init不覆盖已存在配置 | 原错误命令退出2收据保留；README本地链接检查通过 |
| Q305 | README及配置注释多处仍把默认结果说成旧HTML，用户会寻找不存在文件；示例脚本会覆盖活动配置 | 同步默认SQLite、旧SQL/HTML适用范围、Studio依赖与启动；示例先用独立配置目录并恢复环境 | 同三工程的status/report收据；未运行会覆盖原配置的示例命令 |

Q301 原失败保留在 `output/quality-20261108/delivery/final-engine-v1/cdc-scan.log` 与对应 `diagnostics/source_changes.json`。它记录 before/after 都为MISSING的错误工具路径，实际源文件457项哈希/大小/mtime没有变化。没有通过改数据库、移除检查或忽略返回码使其通过。

新增回归为 `tests/test_cmake_toolchain_snapshot.py`（4项）和 `tests/test_cli_init_arm_headers.py`（1项，真实编译/解析）。最终专项5项全部通过，3.747秒。第一次测试控制器曾错误使用GBK解码CMake中文路径输出、另一次误把解析成功枚举写为OK；原失败日志保留，按工具正式PARSED合同纠正测试，没有修改产品预期来放行错误。

## 独立真实工程

最终核心引擎指纹为 `74c0b1c0f3fa204088534ad90f5bcefaf4bccb5a00ce42bce4cfb878eea509b2`。扫描必须在此指纹冻结后重新执行，不能用中途修改引擎时的结果证明最终版本。既有数据库保留真实编译参数，本轮全扫没有重新构建固件；输入来源、编译数据库与扫描有效性分别核对。未烧录或进行板级竞争验证。

| 工程 | 独立来源、固定提交及许可 | 本轮输入与范围 | 最终结果 |
|---|---|---|---|
| STM32F030 / Cortex-M0 | `hemashushu/practice-mcu-bare-metal-stm32f030`，`55bbd6a1ffddfd4acb20b62aabb3c0eb060e2eb3`，MPL2.0 | 既有黄金42文件副本，4个真实TU，原编译数据库；只在隔离配置启用系统头 | 最终v3全扫32.219秒；2 PARSED/2 PARTIAL/0 FAILED，15对象/6复核项；run2/status0/report2，INCOMPLETE保留 |
| STM32F411RE / Cortex-M4 | `ViniBR01/stm32-bare-metal`，`065875948326eab4d82cdaca59dd8bbd96d3516e`，MIT | 真实CLI/UART/DMA/启动和驱动项目，24个数据库TU，225项源码输入哈希/mtime核对 | 最终v3全扫157.109秒；24 PARSED/0 PARTIAL/0 FAILED，171对象/38复核项；run2/status0/report2，INCOMPLETE保留 |
| STM32F407IG USB CDC / Cortex-M4 | `STMicroelectronics/STM32CubeF4` v1.28.3，`94cae6e83f00e276a11957e7833c01ac3d0bd7af`；原许可证与组件许可保留 | `CDC_Standalone` 真实工程及已有验收扩展p00，40数据库条目/39个C TU，HAL/CMSIS/USB依赖参与；457项源码输入核对 | Q301原场景最终重扫407.235秒；39 PARSED/0 PARTIAL/0 FAILED，244对象/205复核项；run2/status0/report2，INCOMPLETE及未解决风险保留 |
| INAV MATEKH743 / Cortex-M7，大型裸机 | `iNavFlight/inav` 7.1.2，原上游 `ed7fb3bb3216f8215150b42b52cb7b724e1dfae8`，GPL3；既有差异派生工作树实际HEAD为`a040c6bef605f929fa017b7089c5b7976a2b2bba` | 真实162016条多目标数据库，MATEKH743闭包相关390条；本轮选取time.c/fc_core.c实际提取，仅代表TU验收 | 最终74c0指纹两TU均PARSED，分别45.156/83.218秒，源文件哈希/mtime不变；只属PASS_SCOPED，不等于整工程全量/差异/恢复通过 |

F030旧配置未启用系统头的4/4失败没有被计为通过。F411在中途引擎变化时一次 `report` 返回3；另一轮扫描被发布后指纹校验明确拒绝。全部原日志保留，最终轮另开新数据根，不回填扫描状态。

本轮数据根为 `H:/ECRA-quality-20261108-delivery`，工程执行证据在 `output/quality-20261108/delivery/`。最终轮位于其 `final-engine-v3/`，对应运行数据在外部同名目录。复跑请选择新轮次目录，不覆盖既有收据。

三工程最终统一审计 `output/quality-20261108/delivery/real-projects-final.json` 为 PASS_SCOPED：三者均实际全量扫描、status、report完成，`analysis_valid=true`、SQLite integrity_check=`ok`、检查点可继续、源码输入未变、全部复核项有账本且仍处于真实pending。此通过表示扫描/持久化/恢复合同通过，不能把INCOMPLETE与pending解释为风险已经复核或整个固件安全。

三份最终静态库分别为8,957,952、62,476,288、273,031,168字节。本轮未连续记录进程峰值RAM，不作新的峰值内存或性能提升验收结论；耗时受本机同时进行的界面与磁盘校验影响，不是性能保证。

## 便携候选与限制

本轮离线缓存完整检查真实通过，日志 `output/quality-20261108/delivery/offline-cache-baseline.log`。新便携候选以原封存 v91 的32973文件/1.895GiB完整独立复制为基底，随后精确更新本轮源码、页面和说明；这不称为重新运行 `build_portable.ps1` 的全新工具链构建。基包及原dist保留。源码补丁清单、完整文件哈希、ZIP及中文空格路径解压复核会单独形成收据。

本轮补丁目录为 `H:/ECRA-quality-20261108-delivery/便携 中文/ECRA-Portable`。包内Python3.10.9实际从该副本import产品模块，运行源码路径的41项核心回归，0失败/0错误/0跳过，16.290秒；覆盖异常屏蔽、当前AI结论投影、配置表单、真实CMake及真实ARM标准头初始化。没有为此把新测试或开发依赖加入分发目录。实际运行收据为 `output/quality-20261108/delivery/packaged-core-tests.json`；这不替代真实界面操作。

在无`.git`的中文空格候选目录，另从无关当前目录`H:/`、仅Windows系统PATH实际运行`ECRA.cmd --help`，退出0，包内Python版本实际为3.10.9，原始帮助保存在`output/quality-20261108/delivery/packaged-cmd-help.txt`。最终ZIP解压后还需单独复验，不能用此目录提前替代。

干净离线物理电脑、32GB物理机、Windows系统DPI、三个工程的板级运行和OpenCode新的联网轮次不由本记录证明。INAV既有整轮执行记录已超过29644秒仍未完成，本轮不把两个代表TU或旧大型结果包装成最终整轮验收。

## 封包后的外部收据

最终本地候选为 `H:/ECRA-quality-20261108-delivery/ECRA-Quality-20261108-local.zip`，787,798,791字节，SHA256 `b02a9e30a9270bfa35c558bc3191d3305c7f02624d789ea24a48f8d6399272ab`。它是v91完整独立复制后的精确源码补丁候选，未重新构建工具链，不替换原v91或dist。

ZIP解压到 `H:/ECRA-quality-20261108-delivery/解压 终验/ECRA-Portable`，全部32,988个内容文件逐SHA相同（另有FILES清单自身），所有成员解压CRC校验通过，没有`.git`。压缩、解压和完整校验共184.047秒；收据 `output/quality-20261108/delivery/portable-patch-zip.json`。

在该解压目录实际以仅Windows系统PATH、无关当前目录`H:/`运行 `ECRA.cmd --help` 退出0；包内Python实际import解压目录的ecra，静态指纹仍为74c0…，全部生产文件与冻结源码一致。收据 `extracted-cmd-help.txt` 与 `extracted-cli-import.json`。

主检查者随后通过解压后的真实ECRA.cmd启动、查看及“继续上次位置”，核对待办5/独立人工风险1、选中g_msgSP、三个原事件ID及静态库哈希；实际查看截图后关闭浏览器和服务。该实际操作记录见`ui.md`及封包后收据。关闭之后再次由解压包Python运行完整后验：全部32,988内容文件无变化，151个生产文件仍与冻结源码逐SHA一致，差异列表为空，静态指纹74c0…不变。最终收据 `output/quality-20261108/delivery/extracted-final-postflight.json` 为 PASS_SCOPED。

包内文档冻结在本次压ZIP开始时；封包后的`validation.md`、索引补充和最终后验保留在仓库，依照既有封存约定不回写ZIP。所有生产Python、前端字节与静态指纹保持冻结，不因补充验收记录变更。
