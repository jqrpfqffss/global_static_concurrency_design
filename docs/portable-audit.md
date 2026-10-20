# Windows Full Portable 审计与实现说明

审计基于本地工作区，未改动固件源码或并发分析、变量分类、证据提取算法。

## 原流程及风险

1. `config/portable_sources.psd1` 原来固定 Python 3.12.10、CMake 3.31.10、Ninja 1.12.1；`requirements.txt` 为 libclang 18.1.1、PyYAML >=6.0.2,<7。
2. `prepare_portable_cache.ps1` 联网下载归档和 wheels；`build_portable.ps1` 离线读取解压缓存、归档或显式来源，复制工具、配置和 Python 包，再生成 ZIP。普通缓存主要按目录结构验收，只有 ARM GCC 额外检查了版本号；缺少完整的逐文件缓存校验。
3. 原包不包含 MinGW。`ecra.cmd` 将 CMake、Ninja、ARM GCC 前置到宿主 PATH；`configure_cmake` 使用裸 `cmake` 命令，没有固定 Make。MinGW Makefiles 因此可能使用系统 Make 或旧缓存中的绝对路径。
4. 原 ZIP 自检在恢复宿主 PATH 后运行导入、版本和帮助命令，没有真实配置/构建，也未检查全部 PE 依赖。开发机 System32 中的 MSVCP140.dll 会掩盖 libclang 的缺失依赖。
5. 原脚本在验证输入前删除上次输出包和 ZIP，会损失包内用户配置。原 CMake 清理只要求目录位于工程内部，不能区分 IDE 正式目录和 ECRA 专用目录。
6. 原 `doctor` 会配置并读取编译数据库，但不会构建或扫描；仅凭 doctor/help 成功，不能证明完整构建能力。

## 本机发现与选源

PATH 首项实际为 MSYS2 GCC 15.2.0、Python 3.12.12、CMake 3.31.10；另有 GCC 8.1.0、Python 3.10.11。均未作为指定版本替代品。

检查了 `D:/CLion/CLion 2024.3.5/bin`：CMake 是 3.30.5（JetBrains build 22），GCC 是 13.1.0、posix，Make 是 4.4。所需的 JetBrains CMake 3.29.6 build 1 在该安装中不存在。

因此使用官方 Kitware CMake 3.29.6，保留完整 bin/share/doc。其 `doc/cmake/Copyright.txt` 允许附带版权和许可声明的二进制再分发，文件随包保留。发行构建标识与 JetBrains build 1 的差异记入 `portable-lock.json`、`VERSION.txt`。

其他选源：Python.org 官方 3.10.9 amd64 embeddable；Ninja 1.13.2 来自本地 WinGet 原始安装目录；MinGW-Builds 官方 14.2.0 mcf/seh/ucrt rt_v12 rev0 归档；ARM 来自本地完整 `D:/gcc-arm-none-eabi-10.3-2021.10`。版本通过运行二进制取得，同时检查 GCC target、thread model、内部程序和库的真实解析路径。

## 改动清单

| 文件 | 改动与原因 |
|---|---|
| `config/portable_sources.psd1` | 单一版本清单、准确发行变体、归档/来源和 SHA256；锁定 Python wheels 及 MSVC 必需运行库。 |
| `scripts/portable_common.ps1` | 共用发现、目录完整性、实际版本、内部路径、复制、归档及树哈希验证；安全清理和有限重试；下载支持受控断点续传。 |
| `prepare_portable_cache.ps1` | 增加完整 MinGW、配套 Make、VC runtime；按版本隔离缓存；从 PyPI 验证兼容 cp310 win_amd64 wheel；严格离线检查。 |
| `build_portable.ps1` | 增加 MinGWSource/MinGWMakeSource/VcRuntimeSource；完整工具目录复制；原配置按字节保留；拒绝覆盖旧包；先验收候选 ZIP，再发布最终名称。 |
| `scripts/extract_vc_runtime.py` | 从已验证的微软安装包中读取 Burn/CAB 清单，提取 x64 runtime 和原许可证，不安装到系统。 |
| `scripts/enable_make_utf8.py` | 只增加同源 Make 的 Windows UTF-8 manifest；校验原件 SHA256 和非资源段不变，保存可复现配方和产物哈希。 |
| `ecra/portable.py` | 按当前包位置选择工具，隔离构建 PATH，读取缓存及生成的编译器元数据，诊断外部路径与实际版本。 |
| `ecra/compilation.py` | 固定 Portable CMake/Make/Ninja；保留 Generator；构建前审计编译器；拒绝旧路径/Generator；只清理有所有权标记的目录；保留 build:false。 |
| `ecra/config.py` | 校验显式 `allow_external_toolchain` 选项，默认拒绝外部工具。 |
| `ecra/cli.py` | doctor 输出工具、库、实际 Make/编译器/数据库/外部依赖及独立验收状态；提取子进程加 -B。 |
| `scripts/validate_portable.py` | 逐文件 SHA256、正常及延迟 PE 导入依赖检查；隔离 PATH 下真实 MinGW/Ninja 本机构建、ARM ELF 构建、AST/CLI 回归。原目录和 ZIP 解压目录使用同一验收器。 |
| `tests/test_portable_build.py` | 缓存冲突、非缓存编译器、外部路径、目录保护、build:false、隔离 PATH、缺少实际 Python DLL 的负向用例。 |
| `tests/test_scope_cmake.py` | 清理用例增加真实的 ECRA 所有权标记，匹配收紧的安全契约。 |
| `docs/portable-usage.txt` | 打包、离线使用、迁移、故障处理、OpenCode 独立安装和许可说明；同时作为包内 README。 |

`config/semantics.yaml`、`requirements.txt`、`run_ecra.py` 原样保留。特别是 project.root、扫描范围、上下文、复核参数均未修改。

## 工具与运行时边界

- ECRA 始终使用 runtime/python.exe 3.10.9。完整保留官方 python310.zip、标准扩展与 DLL；_pth 只列标准库、runtime、site-packages 和工具根，不导入用户 site/注册表路径。
- CMake 构建子进程只获得内置工具和必要 Windows 系统目录。MinGW 的 `opt/bin` 是其 GDB/Python 支撑 DLL 的实际位置，也必须加入 DLL 搜索 PATH。该 MinGW 原始支撑 Python 与 ECRA runtime 分开保存；没有复用旧 Python 3.12 缓存。
- 启动器保留宿主 PATH 以支持独立安装的 OpenCode；构建进程另行隔离。CMake 和 Make/Ninja 使用包内绝对路径。ARM 编译器由真实工具链和编译命令解析，不改写芯片宏、架构选项或工程编译器。
- 即使工具链没有把编译器写入 CMakeCache，也检查 `CMakeFiles/<version>/CMake*Compiler.cmake` 中的字面量路径，以及编译数据库中的真实命令，然后才允许构建。
- ZIP 中文路径实测发现 GNU Make 4.4.1 将 UTF-8 命令按系统 ANSI 代码页读取。为保持指定二进制，优先使用同目录的 8.3 名称；无短文件名时，在用户 ASCII TEMP/ECRA-paths 中创建确定性 junction，核对目标确为原目录。缓存中的路径可以在后续命令重建；不会把别名当成外部工具，诊断同时提供真实路径。既有冲突别名不会被覆盖。测试同时使用含中文和空格的工具根及项目根。
- CMake 3.29.6 会解析自己的 junction/subst 并把真实目录重新写入生成文件，因此目录别名本身不足以解决中文包根。对配套 GNU Make 4.4.1 仅增加 Windows `activeCodePage=UTF-8` 进程 manifest，并验证所有非资源 PE 段与原件相同。版本和实现代码不变，原件/产物 SHA256、原 manifest、适配源代码均随包记录。此机制要求 Windows 10 1903+；没有全局代码页、注册表或宿主开发工具变更。微软机制说明：https://learn.microsoft.com/windows/apps/design/globalizing/use-utf8-code-page 。
- 外部工具链只有显式 `analysis.cmake.allow_external_toolchain: true` 才可使用，并在诊断中标记。默认不会因为本机有其他编译器而静默切换。
- Unix Makefiles 在兼容 make 环境存在时保留支持；本包默认提供的生成器环境是 MinGW Makefiles 和 Ninja，不伪装成提供完整 Unix shell。

## 必需 DLL 与可选组件

libclang Windows wheel 实际导入 MSVCP140.dll。使用微软官方签名的 VC++ x64 Redistributable 14.44.35211.0，按固定 SHA256 提取匹配的 MSVCP140、VCRUNTIME140、VCRUNTIME140_1，应用目录部署，目标电脑无需安装。原许可证随包提供。向第三方再分发需具备微软 Visual Studio 条款规定的相应权利，参见 https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files 。

ARM 上游的可选 `arm-none-eabi-gdb-py.exe` 依赖外部 32 位 Python 2.7，本任务不需要该调试器。它及配套 `gdb-add-index-py` 明确排除并记入清单；标准 GDB、全部编译器、binutils、头文件、库、多架构运行库保持完整。所有实际随包的 EXE/DLL/PYD 继续接受依赖校验，不把缺失的非系统运行库视为 Windows 自带文件。

## 安全和验收约定

- 既有输出包不会被删除或覆盖；重打包选择新 OutputDir。只有本次创建的候选包通过解压后的实际验收，才得到 `ECRA-Portable.zip` 名称。
- 只有 ECRA 创建并带工程所有权标记的构建目录才可清理；正式/未标记目录不会自动采用或删除。拒绝越界、链接/junction 清理；Windows 占用只有限重试。
- doctor 的 `cmake_build`、`arm_cross_compile`、`static_scan` 为 NOT_RUN 时就是没有做对应工作，不因导入或配置成功改成 PASS。
- 静态测试产生真实并发候选，`run --no-review`、禁用复核的 review/report 预期退出码是 2（待复核/未完成结论），不能把这个语义误判为构建失败；配置/构建错误退出码 3 仍使验收失败。
- OpenCode 不随包分发。本机查到独立 OpenCode 1.18.35；模型/提供商的真实复核不计为已实测，独立接口及禁用复核路径另行验收。

实际命令、退出码、日志、ZIP 大小与 SHA256 见最终 `portable-delivery-report.md` 和 `dist` 中的验收证据。
