# STM32F4 MinGW 定向构建修复

起始分支为 `optimize_ccc`，HEAD 为 `f9b65a3968f4000486b3ac37fc3ccb3af9b43b4a`，与远端一致。验证使用独立 Workspace。

## 根因

- 固件的 `app_M2` 是 `ALL` 后处理目标。它依赖负责链接的 `app_elf`，并在 Windows 的 `cmd.exe` 中运行 `mkdir -p` 和 `cp` 等命令。打包命令报错发生在 ELF 链接成功之后。
- ECRA 原先默认构建 `ALL`，MinGW Makefiles 又无法使用 `analysis.cmake.target`。单独在 `build_args` 中传入 `--target app_elf` 可以避开打包，但仍会分析全量编译数据库中的其他固件变体。

## 修复方式

| 文件与入口 | 原行为 | 修复后 |
|---|---|---|
| `ecra/config.py` 的 `load_config`，`ecra/compilation.py` 的 `configure_cmake` 和 `prepare` | `target` 仅支持 Ninja | MinGW Makefiles 也可用 `target` 同时选择构建目标和编译闭包。缺省仍构建 `ALL`。显式 `build_args` 保留原来的构建参数语义 |
| `ecra/make_target.py` 的 `target_entries` | MinGW 只读取全量数据库 | 根据生成的 Makefiles 遍历实际目标依赖，用 CMake File API 和对象输出逐项核对编译命令。保留原始宏、ABI、包含目录及同源多命令。构建后复核闭包并检查实际产物，再写入 `ecra-target-compile_commands.json` |
| `ecra/build_execution.py` 的 `save_logs`，`ecra/guarded_cmake.py` 的 `BuildExecutor` | CMake 输出按 UTF-8 替换解码 | 配置和构建分开保存原始 stdout、stderr 及 SHA-256。文本日志优先按 UTF-8 解码，再尝试 Windows 实际代码页。受保护配置的 trace 使用独立证据字段和真实文件路径，编译器头文件探测保留原协议 |
| `ecra/studio/preflight.py`、`ecra/studio/profile_options.py`、`studio/src/App.vue` | 提示精确目标需 Ninja | 向导提示目标与变量范围分别设置，预检查与正式扫描共用 `prepare`。任务显示配置目标、真实命令与构建结果 |

`target` 需要用户显式选择。CMake 可以提供目标名与依赖，但工程可能同时包含多个板型、Bootloader 或不同核心，目标名无法证明用户意图。构建失败、编译数据库未刷新、对象映射不唯一或闭包发生变化时，ECRA 停止该轮扫描。MinGW 精确闭包需要 CMake 导出的 `output` 字段。无法将外部链接对象对应到编译命令时，该模式会报错。[CMake File API](https://cmake.org/cmake/help/v3.31/manual/cmake-file-api.7.html)

Workspace 继续按源版本和 CMake 配置选择物理目录，清理前仍校验 `.ecra-build-owner`。ELF/MAP 继续走已有显式 `build_closure` 及其归属、路径和 SHA-256 校验。MinGW 构建图和编译数据库也纳入输入快照。未提交 CMake 扫描仍要求受保护的 Windows/Ninja 路径。

## 一键扫描配置

在已有 `semantics.yaml` 的 `analysis.cmake` 中增加 `target: app_elf`。如原先在 `build_args` 中传入了 `--target` 或 `-t`，移除该目标选项及其值。原有构建变体和变量范围沿用工程配置。

```yaml
analysis:
  cmake:
    generator: MinGW Makefiles
    build_dir: build/manual
    toolchain_file: cmake/toolchain.cmake
    clean_before_configure: true
    build: true
    target: app_elf
```

保存后运行 `py -3.10 run_ecra.py`。在 Studio 第 2 步填写目标 `app_elf`，展开“构建细节”选择 `MinGW Makefiles`，然后保存并检查真实构建。已有 `build_closure.elf` 和 `build_closure.map` 路径应继续指向 `app_elf` 生成的链接产物。

## 本轮验证

独立复现使用 Windows、CMake 3.31.10、MinGW Makefiles、Arm GCC 10.3.1 和 LibClang 18.1.1。样例的 `app_M2` 先创建名为 `-p` 的文件，使 Windows CMD 的 `mkdir -p` 能稳定复现错误。Portable 验证使用隔离副本的 `ECRA.cmd`、内置 Python 3.10.9 与 CMake 3.29.6。公开 STM32F030 使用提交 `55bbd6a1ffddfd4acb20b62aabb3c0eb060e2eb3` 的源码副本及对应 ARM GCC 编译与链接选项。

| 验证项目 | 修改前 | 修改后 | 结论 |
|---|---|---|---|
| STM32F4 `app_elf` | 独立样例的原生 `cmake --build … --target app_elf` 返回 0 | ECRA 使用 `target: app_elf`，完成生成、编译与 ARM AXF 链接，ELF/MAP 实际路径及 SHA-256 可核对 | 独立样例 PASS。私有 VacuumGauge `NOT_VERIFIED` |
| STM32F4 `app_M2` | 独立样例 `ALL` 在 `app_elf` 成功后因 `mkdir -p` 失败，CLI 返回 3 | 默认 `ALL` 仍按真实失败返回 3，GBK 中文可读并保留原始字节。定向构建未创建打包标记 | 独立样例 PASS。私有工程 `NOT_VERIFIED` |
| ECRA 完整扫描 | 仅用 `build_args` 避开打包后，4 个 C TU 进入 AST，包括另一硬件变体 | 原生 CLI 和 Portable 都发布通过深度校验的 `scan.db`，静态范围状态为 `MODELED_SCOPE_COMPLETE`。各 5 个变量、10 条读写记录、3 条调用边，三类事实逐项相等。两个高风险项待复核 | 独立样例 PASS。私有工程 `NOT_VERIFIED` |
| 目标 TU 覆盖 | 全量数据库 4 条。同一 `dispatch.c` 以不同宏编译两次 | 目标数据库保留原命令的精确子集，3 个 C TU 全部解析，0 部分、0 失败。恢复范围外 `dispatch` 到 HAL DMA 回调的调用边，保留 DMA 缓冲区、静态局部变量和结构体字段证据 | 样例 PASS。私有 205 条基线 `NOT_VERIFIED` |
| Ninja 兼容、公开 STM32F030 | 默认构建完成，4 TU 中 2 完整、2 部分、0 失败，15 个变量、98 条调用记录、56 条访问记录 | 同配置重新构建和分析，完整规范事实逐项相等，分类与完整性标记一致，ELF/MAP 哈希相同。`startup.c` 和 `main.c` 仍显示部分解析 | 公开工程 PASS |
| MinGW 兼容 | 无精确目标闭包 | 独立样例验证中文和空格路径、子目录对象库、生成 `.c`/`.h`、汇编和同源不同宏。必要编译和链接失败均阻断 | PASS |
| Studio 上位机 | MinGW 精确目标被配置校验拒绝 | 在 Chrome 四步向导填写、保存、预检查、点击一键扫描并打开结果。任务中心为 `COMPLETE`，预检查与正式扫描的构建命令和 3 个 TU 的原始参数逐项相等 | 独立样例 PASS。私有工程 `NOT_VERIFIED` |
| Git Diff | Ninja 已有双版本链接产物绑定 | Ninja 与 MinGW 各执行一次真实 ARM 双版本差异扫描。两侧 ELF/MAP 位于独立构建目录并保留 SHA-256。无缓存全量对照 `PASSED` | PASS |
| 原有回归测试 | 使用原始 HEAD 复现 `ALL` 故障并重跑 F030 基线 | 定向 21 项通过，关联回归 56 项通过、1 项跳过。最终版受保护日志专项 11 项通过、1 项跳过。218 个模块共 1,751 项，1,747 项通过、3 项跳过、1 项失败 | 唯一失败发生在受保护 Windows/Ninja 未提交 Diff 的保存结果刷新。原始 HEAD 和最终版分别独立复跑该用例，均通过 |

回归入口为 `py -3.10 -X utf8 -m pytest -q tests/test_mingw_cmake_target.py tests/test_cmake_target.py tests/test_managed_build_closure.py tests/test_build_preflight.py`。回归覆盖构建失败阶段、变体隔离、生成输入、旧数据库拒绝、停止后重试及混合 UTF-8/GBK 原始字节证据。

样例的实际 `app_M2` stderr 为 264 字节，原 UTF-8 替换解码产生 22 个替换字符。修复版识别了 CP936 中文诊断和同一流中的 UTF-8 行。文本日志为 `cmake-build.log`，原始流存于相邻的 `cmake-build.stdout.bin`、`cmake-build.stderr.bin`。普通 MinGW 在配置和构建命令的边界响应停止，命令运行期间沿用已有超时机制。

全量回归的跳过项包括两个需显式启用的联网 OpenCode 用例及一个要求 ARM GCC 安装在中文路径的用例。唯一失败为 `WorkingCMakeTests.test_actual_generated_inputs_staging_and_complete_native_diff`。当次扫描已经完成中断、续跑及无缓存全量对照，随后 Windows 目录监控在 `saved_run` 刷新时拒绝操作。原始 HEAD 独立复跑通过。最终版加独立文件系统观察器复跑，原守卫和原断言照常执行，用例通过且观察器未收到文件事件。

## 未验证项

- `D:/code/AI/STM32f4/HX_SDC_VACUU_PLATFORM/vacuumgauge` 在本机不存在。VacuumGauge2.22.1 的原始 205 条命令、链接产物、变量及调用链的前后对照，以及该私有工程的 Studio 操作均为 `NOT_VERIFIED`。
- 私有工程的 NVIC 优先级、硬件运行及物理板验证为 `NOT_VERIFIED`。
- 全量回归中一次冻结视图目录通知的具体来源为 `NOT_VERIFIED`。独立复跑未重现该通知。
