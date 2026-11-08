# 续验：真实固件构建与 Windows MinGW

本记录延续上一轮，不重跑已经通过的41项包内核心回归或三个原数据库全量扫描。开始时仍为`optimize_ccc@fe27afe73596d98e1a21e3f28a2125d38d7272d0`加上一轮本地修复，静态引擎为`74c0b1c0f3fa204088534ad90f5bcefaf4bccb5a00ce42bce4cfb878eea509b2`。本项不修改正式分析模块、原固件、原候选目录或ZIP。

## 当前基线及执行范围

使用上一轮实际解压并完整后验的`H:/ECRA-quality-20261108-delivery/解压 终验/ECRA-Portable`工具。数据与源码副本使用新的`H:/ECRA-quality-20261108-continuation-build`；原始日志、命令、输入清单及构建收据保存`output/quality-20261108/continuation/build`。

| 工程 | 实际构建入口 | 预先确认的条件 | 本轮检查 |
|---|---|---|---|
| STM32CubeF4 CDC p00 | CMake、40条C/ASM输入、完整firmware.elf与linker script | 单一真实USB CDC固件，原工具链文件使用arm-none-eabi-gcc；含HAL/CMSIS及既有验收扩展 | 中文空格源码副本、外置build、包内CMake+MinGW Make+ARM GCC，实际configure/compile/link；核对CDB与ELF |
| STM32F411RE CLI | 原GNU Make，`EXAMPLE=cli_simple PROFILE=standalone` | 原根Make目标即使standalone也依赖keys；还需POSIX shell/coreutils、python3及cryptography。包有Git sh/coreutils，未承诺固件专用Python依赖 | 先以显式包内工具及受限PATH执行原目标，保留真实失败，再区分外部工程依赖与ECRA集成问题 |
| STM32F030 | 原build.sh，4个C文件直接编译并完整链接main.elf | 原脚本在不存在旧ELF时先rm会报错，不能借末尾size成功掩盖编译失败 | 按原完整gcc链接参数运行并独立检查每个返回码及新ELF；不伪造或复用旧产物 |

F411的CLAUDE.md已读取；本次只验证隔离副本，不开发其功能，不创建远程Issue、推送、PR、烧录或HIL。上层用户明确要求不切历史分支、直接本地执行，优先于该第三方开发流程模板。

上表是开始执行时的基线，不是通过结论。以下结果来自新建副本的实际编译和链接，不复用原工程ELF或对象文件。

## 实际结果

| 工程及配置 | 实际构建结果 | 新产物与数据库 | 输入及来源校验 |
|---|---|---|---|
| CDC p00，Debug，MinGW Makefiles，Cortex-M4硬浮点 | configure退出0、4.234秒；完整compile/link退出0、7.625秒 | 新firmware.elf 1,768,960字节、ARM EXEC、入口`0x080053fd`，完整MAP；CMake真实生成CDB40条（39C+1ASM） | 全部CDB输出对象存在，编译器均解析到当前候选Arm GCC；全部源码来自中文空格隔离副本，原源和副本源码均未变 |
| F411 CLI，standalone，FPU=1，O2/LTO | 原GNU Make完整目标成功；真实调用采集轮17.375秒，无GCC采集器的新副本独立复验12.579秒；均退出0 | 47次实际GCC调用全部成功，46次编译+1次完整链接；新ELF/MAP/BIN；真实调用生成CDB46条 | 原Makefile与源码未改，链接脚本、静态库、libc/libm/libgcc检查保留；独立两轮原始BIN逐SHA相同 |
| F030，Cortex-M0，原build.sh旗标 | 原4C一条完整编译链接退出0、0.797秒；另从新副本逐TU编译并完整链接，全部5个命令退出0 | 新main.elf 153,388字节、ARM EXEC、入口`0x080000bd`，完整MAP；实际4个编译调用生成CDB4条、对象全部存在 | 没有执行原脚本的无旧ELF时rm错误，也没有借size命令掩盖编译失败；原源及副本哈希/mtime均不变 |

CDC的真实源码目录是`round1/中文 空格 CDC 源码`，构建位于独立的`round1/外置 MinGW 构建`。实际调用复用产品`build_path`生成的同一物理目录ASCII别名，经过`resolve()`核对；没有替换源码、使用相似演示目录或缩小源文件列表。

F411没有CMake配置阶段，按其原Make变量选择真实standalone布局，不冒充CMake流程。根Make还构建了部分未进入CLI链接的库，CDB46条是实际构建调用集合；后续分析应结合真实ELF/MAP缩到所选固件闭包，不能把全部编译库都说成最终链接输入。两轮ELF因不同目录的调试路径而字节不同，实际flash BIN均为SHA256 `129bfa45ea79b2802ccb976ed7452a3c9ceaf94557546332a08f2d04fb779b5b`，没有放宽二进制对照。

新CDB和ELF/MAP保留在外部工作目录：

- CDC：`round1/外置 MinGW 构建/compile_commands.json`、`firmware.elf`、`firmware.map`。
- F411：`round3-f411/compile_commands.json`；ELF/MAP/BIN在`round3-f411/firmware/build/apps/cli/cli_simple_standalone/`；原入口无GCC采集器复验在`round4-f411-native/`。
- F030：`round5-f030-objects/compile_commands.json`、4个对象、`main.elf`、`main.map`；先前原式完整链接产物在`round1/f030.elf`。

以上相对目录均以`H:/ECRA-quality-20261108-continuation-build`为根。统一收据为`output/quality-20261108/continuation/build/final-build-and-databases.json`；原命令、PATH、返回码、各阶段耗时、完整编译/链接日志与输入清单位于同一证据目录。CDB来自实际成功命令的原参数，不是为扫描手填的成功替身。

## F411的外部工程依赖

原项目`tools/keygen.py`明确要求cryptography，原CI使用`pip3 install cryptography`，没有固定版本。包内原GNU Make首次执行因缺该依赖退出2，日志`f411-native-bundle-only.log`完整保留；没有跳过keys或编造旧密钥使它通过。

包内MinGW自带的`python3`实际为Python3.11.6，与ECRA主运行时Python3.10.9分开。续验在独立`firmware-deps`安装cryptography **46.0.3**，并显式以包内主Python3.10.9启动固件脚本；依赖只通过本次构建的`python3`入口提供。没有装入候选目录、没有改主机默认Python或默认PATH。

从官方PyPI下载的依赖为cryptography46.0.3、cffi2.1.1、pycparser3.11、typing_extensions4.16.0，wheel均与对应官方metadata SHA256逐项相同。来源、所需Python版本、下载URL、版本和完整hash见`firmware-external-dependencies.json`，下载及安装日志保留。它们只满足该公开固件的keygen步骤，不扩展ECRA Portable运行时依赖合同。已有真实CDB的静态扫描不需要这套keygen依赖。

## 原始失败与验证控制器修正

1. F411包-only缺cryptography：真实工程外部构建依赖缺失，保留退出2和已完成对象。
2. 首次GCC调用采集器放在PATH最前，会使原GNU Make直接调用真exe时，GCC据PATH错误定位cc1；该轮返回2、没有有效CDB，收据`f411-final-result.json`仍为失败。改用Make显式CC调用包内Python采集器，再用完整真实GCC路径转发原参数；随后额外验证不启用采集器的原命令，不能以采集器自称成功替代原生构建。
3. 完整后验曾发现30个清单外`__pycache__/*.pyc`，原清单文件与原ZIP均未变。来源为MinGW隔离Python忽略环境字节码设置，以及并行host验证控制器在导入包前未禁用缓存。这属于验证控制器/外部工程构建副作用，不列作正常`ECRA.cmd -B`启动污染缺陷，也不算产品恢复能力验证。

第3项原始失败收据保留在`final-build-acceptance.json`及`final-build-audit.log`。仅将已经核对、位于解压候选绝对边界内、清单外的30个pyc逐文件迁移到`validation-bytecode-quarantine`，逐个保留SHA、大小与mtime；没有递归删除/移动目录，也没有触及原清单文件。空的字节码目录只逐个rmdir。记录为`bytecode-quarantine.json`。后续Python均显式`-B`，host导入先设置`sys.dont_write_bytecode=True`。

迁移后完整复核为`final-build-acceptance-restored.json`：全部32,988个原内容文件逐SHA完全一致，差异为空；原ZIP仍为SHA256 `b02a9e30a9270bfa35c558bc3191d3305c7f02624d789ea24a48f8d6399272ab`，没有重打包或修改封存版本。

## 结论与边界

本项为**PASS_SCOPED：三个独立真实固件的新编译、完整链接及新数据库来源已验证，实际Windows MinGW中文空格路径的CDC构建通过**。静态引擎74c0…保持冻结，没有修改正式分析代码。没有烧录、HIL、板级并发或硬件通信验证；本项不能替代新的数据库上全量/Diff/缓存分析、真实OpenCode复核、干净离线物理机或大型INAV整轮门禁。

后续已用这些不变的实际构建产物完成[最终v4三工程全量复验](continuation-final-projects-v4.md)，引擎为63a5…，67C重新提取而非沿用本构建阶段74c0…的缓存。全量发布、status/report/status、静态库/输入不变、容器与人工待办口径均通过；65PARSED/2PARTIAL/0FAILED及另1ASM、74未知和244待办仍真实保留。这里保留原构建阶段身份，不将74c0的记录改名成最终版本。
