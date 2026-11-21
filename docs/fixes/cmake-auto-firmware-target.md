# CMake 固件目标自动选择

在已有 CMake 配置中省略 `analysis.cmake.target` 即可尝试自动选择，无需增加配置项。保留原工具链、生成器、编译范围和 `build_closure`。显式 `target` 始终优先，必须使用 CMake 逻辑目标名；它可以与磁盘上的文件名不同。显式目标无效仍会失败。

每轮 configure 完成后，ECRA 从当前构建配置的 File API 读取逻辑目标、依赖 ID、编译组和产物。根工程的 executable 可以自己编译源码，也可以直接链接对象库的产物。ECRA 对照编译记录、对象路径、裸机交叉编译器和链接参数验证候选。单纯的构建顺序依赖不能证明对象参与了固件链接。

存在唯一合格目标时，ECRA 向 CMake 显式传入 `--target`。MinGW Makefiles 使用 File API 和编译数据库核对依赖闭包，Ninja 使用 `compdb-targets`。自动和显式选择使用同一目标编译数据库，保留同一源码在不同对象和参数下的记录。生成代码、所需库和目标自身的 `POST_BUILD` 仍由 CMake 执行。差异扫描继续检验隔离源码中的已跟踪、未跟踪和 ignored 文件。

合格候选为零、多个候选无法区分或证据损坏时，本次固件构建在配置阶段结束。填写 `target` 时请使用精确的 CMake 逻辑名称。如果填写的是产物名，错误信息会列出当前配置中可确认的所属目标。独立编译数据库、只配置、显式库目标、受保护的未提交输入和多核专用流程沿用各自的入口。

Studio 预检查、正式扫描和 CLI 使用同一解析流程，Git Diff 两侧分别配置。构建步骤记录目标、配置、实际命令和目标闭包行数，预检查计划另列实际 C/C++ TU。对象与链接产物的数量可以从 target-closure 步骤的 `outputs` 查看。

本轮在 Windows 上使用 CMake 3.29.6、MinGW Makefiles 和 Ninja 验证了两种纯对象库写法。测试工程的 `app_elf` 自身没有编译组，`app_M2 ALL` 会写入 ignored 目录。自动和显式选择都构建 `app_elf`，并保留相同的对象和编译参数。目标自身的后处理向隔离源码写入 ignored 或 untracked 文件时，预检查会报告目标和路径。现场私有 `tmfc` 工程仍需用原 profile 复测。

此前的 Windows 工程验证使用 CMake 3.31.10、Ninja 1.13.2、MinGW Makefiles 和 Arm GCC 10.3.1。F103 和 H7 以 `0b28543` 为基线，使用相同配置比较真实 C/ASM 命令和规范化静态证据：

| 工程 | 结果 |
|---|---|
| F4 独立回归工程 | MinGW 自动与显式扫描的 3 个 TU、5 个变量和风险证据一致；生成源码、头文件、对象库及 ELF/MAP 正常产出，独立打包未执行。私有 VacuumGauge 未取得，待验。 |
| H7：STM32CubeH7 NUCLEO-H743ZI GPIO_EXTI（`8ec3113`） | 使用原工程源码与固定版本 HAL、CMSIS、BSP，通过隔离 CMake 适配实现前后对照。22 个 C TU、1 个汇编输入、5 个变量、85 条访问记录、2,119 条调用记录和分类一致。另一个 H743 回归工程也验证了 129 个 TU 的证据一致。 |
| F103：serial（`00b16f7`） | 自动识别 `serial`。20 个 C TU、1 个汇编输入、58 个变量、796 条访问记录、503 条调用记录和分类一致。目标自带的 HEX、BIN 后处理也正常完成。 |

版本回归在不修改 YAML 的情况下重新解析目标，Git Diff 在两个独立工作树分别产生对应版本的产物。Studio 受监督任务验证预检查和正式扫描的选择一致；Portable 的 `ECRA.cmd` 用内置 CMake 3.29.6 和 Arm GCC 自动构建 F4 样例并发布 3 个 TU 的归档。

回归入口：`py -3.10 -X utf8 -m pytest -q tests/test_object_firmware_target.py tests/test_cmake_target.py tests/test_mingw_cmake_target.py tests/test_managed_build_closure.py tests/test_build_preflight.py tests/test_portable_build.py`。
