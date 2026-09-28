# Pre-OpenCode 静态分类真实工程基准

本报告正在执行最终验证。下列构建闭包和历史分类统计已有真实产物；新的分类结果、修改前后比较和每工程 30 个 SAFE 的独立源码审计尚待完成，不能据此宣称最终验收通过。未运行 OpenCode。

## 固定源码与真实固件目标

| 工程 | 固定 commit | 选择的固件目标 | 实际链接编译项 |
|---|---|---|---:|
| Betaflight 4.5.2 | `024f8e13d4e642eb6a380308685b9ea3aa3ef1a2` | 官方 `STM32F405`，Cortex-M4F，默认固件功能 | 418（416 C TU + 2 汇编） |
| Klipper v0.13.0 | `61c0c8d2ef40340781835dd53fb04cc7a454e37a` | STM32F103xE、Cortex-M3、8 KiB bootloader、8 MHz 晶振、USB PA11/PA12 | 50 |
| Black Magic Debug | `07184d19e64db602251bf8dcf41bac76808e6a83` | 官方 `cross-file/native.ini`，STM32F1 native probe、BMD bootloader | 104 |

三个目标均实际编译、链接成功，验证了 ELF magic 与 `e_machine=40`（ARM）。数据库没有从仓库源码列表拼造：Betaflight/Klipper 由透明编译包装器记录成功的真实 GCC 调用，再与成功链接命令中的对象交集；Blackmagic 使用 Meson 数据库、Ninja native ELF 依赖图及真实 link map 中选中的 libopencm3 thin-archive 成员。宿主 BMDA、独立 bootloader、生成 flashstub 的其它 MCU 编译项均不进入 native 固件并发分析。

构建依据：[Betaflight 固定版 Makefile](https://github.com/betaflight/betaflight/blob/024f8e13d4e642eb6a380308685b9ea3aa3ef1a2/Makefile)、[Klipper 固定版 STM32F103 配置](https://github.com/Klipper3d/klipper/blob/61c0c8d2ef40340781835dd53fb04cc7a454e37a/test/configs/stm32f103.config)、[Blackmagic 固定版 native 配置](https://github.com/blackmagic-debug/blackmagic/blob/07184d19e64db602251bf8dcf41bac76808e6a83/cross-file/native.ini)。

机器可读构建证据：`output/preopencode-benchmark/{project}/build-closure.json`、`compile_commands.json`、`firmware.map`、根目录的 `*-build.log` 与 `build-closure-verification.json`。三项目所有记录的 source/object 均存在，ELF SHA-256 与记录一致。

## 环境与比较方法

固件构建使用 GNU Arm Embedded 10.3-2021.10、官方 Make/Meson 构建系统。Windows 宿主的兼容处理只涉及工具 `--version` 输出 CRLF 和 GCC 自动 LTO 并行度：Klipper 链接明确使用 `-flto=4`；固件源码未修改。包装器保存的是实际执行的编译参数。

Clang 解析统一保留真实架构、宏、include 与 ABI 参数；移除不影响 C 语义的 GCC 专用优化/链接开关，并追加 `-Wno-error`，避免将 GCC 与 Clang 不同的警告政策混同于 AST 解析失败。所有 warning 仍保存在诊断中，真正 Clang error 仍计入解析失败。该配置对 baseline 与 after 完全相同。

baseline 在本次修改开始时冻结于 `output/preopencode-benchmark/baseline/ecra/`，仓库 HEAD 为 `6e998c788b8651fcff3cdebe1c3c1c40c3b1a9c3`。使用同一实际构建闭包，只比较生产提取器、points-to、调用图与分类器的差异；不把 off-target 补充盘点计入任何一侧的运行变量。canonical member/array 拆分可能改变分类项分母，因此另报告相同根 storage 的汇总比较。

旧 Betaflight 首轮 416 个 C TU 全部因 warning-as-error 失败，其结果无效，不计入基准；已在统一策略下重新执行 `before-verified`。

## 已确认的 baseline 现象

| 工程 | 分类项 | Global | File static | Function static | Struct member | SAFE | SUSPECT | UNKNOWN | UNKNOWN % | 逐变量复核队列 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Klipper | 686 | 21 | 221 | 93 | 351 | 341 | 0 | 345 | 50.29% | 345 |
| Blackmagic native | 682 | 107 | 86 | 13 | 476 | 8 | 0 | 674 | 98.83% | 674 |
| Betaflight | 待有效重跑 | — | — | — | — | — | — | — | — | — |

Klipper baseline SAFE 为 `NO_RUNTIME_ACCESSES` 340、`ONLY_READS` 1；Blackmagic 为 `NO_RUNTIME_ACCESSES` 1、`ONLY_READS` 7。它们是旧引擎输出，不等同于完成 SAFE 源码审计。基准只以有明确证据的最终新规则判断 false-safe。

Blackmagic 中 `FUNCTION_ADDRESS` 影响 481 项、`INDIRECT_CALL` 469 项、`POINTER_SUBSCRIPT` 460 项，展示了需要变量相关性切片检查的高 fanout。一个变量可同时有多个 blocker，原因计数不可相加作为变量总数。更详细根因聚类见 [unknown_root_causes.md](unknown_root_causes.md)。

## 最终结果与独立审计

新分类器结果、前后 UNKNOWN/队列变化、SAFE proof 分布、UNKNOWN Top 原因及每工程 30 项源码审计待最终扫描完成后更新。抽样脚本只生成分层候选，所有条目初始为 `PENDING_INDEPENDENT_SOURCE_REVIEW`，不会把自动检查输出冒充人工或独立源码审计。

当前尚不能宣称：三个工程已满足最终验收、UNKNOWN 已主要来自真正静态边界、SAFE 没有错误扩大，或 OpenCode 队列已经显著缩减。
