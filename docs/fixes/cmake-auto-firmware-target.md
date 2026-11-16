# CMake 固件目标自动选择

在已有 CMake 配置中省略 `analysis.cmake.target` 即可尝试自动选择，无需增加配置项。保留原工具链、生成器、编译范围和 `build_closure`。显式 `target` 始终优先，必须使用 CMake 逻辑目标名；它可以与磁盘上的文件名不同。显式目标无效仍会失败。

ECRA 在受控清理后创建 File API 查询，用本轮 configure 的结果确认当前构建变体、逻辑目标、链接产物和真实裸机交叉编译器。Ninja 使用 `compdb-targets`；MinGW Makefiles 使用 File API 与 Makefiles 的对象映射。候选必须已经属于默认构建，且依赖闭包要覆盖原有效编译命令。校验比较源码、工作目录、编译参数和输出对象，保留同一源码以不同宏编译的变体。自动模式仍按原数据库顺序和已有范围约束分析。

只有确认是固件下游的独立任务才会随定向构建跳过。生成头文件、生成源码、对象库和目标自身的 `POST_BUILD` 仍按原依赖执行。原 `build_closure` 声明的 ELF/MAP 仍须校验；如果配置明确写了带版本的产物路径，该路径仍由配置决定，工具不会猜测或改写。

发现多个可执行目标、范围不等价、生成器不支持或有无法判断的独立规则时，日志会说明原因并沿用原构建计划。`build_args` 中已有目标、原生参数或可能改变范围的选项时也沿用原计划。只配置模式、受保护的未提交输入和多核流程保持原语义。构建失败、构建树归属错误、证据越界或输入变化会阻断扫描。

CLI、Portable、Studio 预检查和正式扫描使用同一套选择逻辑。自动选择只在本轮生效，不回写 YAML。Git Diff 两侧各自配置、选择并校验产物。Studio 重试会验证原目标和选择证据；已保存结果的复核续跑仍使用原输入快照。

Windows 实测使用 CMake 3.31.10、Ninja 1.13.2、MinGW Makefiles 和 Arm GCC 10.3.1。F103 和 H7 以 `0b28543` 为基线，使用相同配置比较真实 C/ASM 命令和规范化静态证据：

| 工程 | 结果 |
|---|---|
| F4 独立回归工程 | MinGW 自动与显式扫描的 3 个 TU、5 个变量和风险证据一致；生成源码、头文件、对象库及 ELF/MAP 正常产出，独立打包未执行。私有 VacuumGauge 未取得，待验。 |
| H7：STM32CubeH7 NUCLEO-H743ZI GPIO_EXTI（`8ec3113`） | 使用原工程源码与固定版本 HAL、CMSIS、BSP，通过隔离 CMake 适配实现前后对照。22 个 C TU、1 个汇编输入、5 个变量、85 条访问记录、2,119 条调用记录和分类一致。另一个 H743 回归工程也验证了 129 个 TU 的证据一致。 |
| F103：serial（`00b16f7`） | 自动识别 `serial`。20 个 C TU、1 个汇编输入、58 个变量、796 条访问记录、503 条调用记录和分类一致。目标自带的 HEX、BIN 后处理也正常完成。 |

版本回归在不修改 YAML 的情况下重新解析目标，Git Diff 在两个独立工作树分别产生对应版本的产物。Studio 受监督任务验证预检查和正式扫描的选择一致；Portable 的 `ECRA.cmd` 用内置 CMake 3.29.6 和 Arm GCC 自动构建 F4 样例并发布 3 个 TU 的归档。

回归入口：`py -3.10 -X utf8 -m pytest -q tests/test_cmake_target.py tests/test_mingw_cmake_target.py tests/test_managed_build_closure.py tests/test_build_preflight.py tests/test_portable_build.py`。
