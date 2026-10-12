# GitHub STM32 裸机工程端到端验证

## 工程与构建范围

- 上游：[ViniBR01/stm32-bare-metal](https://github.com/ViniBR01/stm32-bare-metal)，主仓库提交 `065875948326eab4d82cdaca59dd8bbd96d3516e`。验证目标为 STM32F411 的 `cli_simple`、`PROFILE=standalone`。
- 固件根目录：`validation/github_stm32_bare_metal`。实际 ARM GCC 构建产物为 `build/apps/cli/cli_simple_standalone/cli_simple_standalone.elf` 与同目录的 `.map`。
- 主 Makefile 的 `keys` 前置任务在本机缺少 Python `cryptography` 时失败；驱动与依赖库已构建，随后直接运行 `mingw32-make -C apps/cli EXAMPLE=cli_simple PROFILE=standalone`，ELF 链接成功。没有烧录开发板。
- `scripts/prepare_github_stm32_bare_metal.py` 从这次真实 Make 命令日志与 linker map 生成 `build/compile_commands.json`，仅保留最终链接闭包的 24 个 C 编译单元。构建命令的芯片宏为 `STM32F411xE`，架构为 Cortex-M4，硬浮点，`gnu11`。
- 排查范围为本固件实际参与链接的 `apps/cli`、`drivers`、`utils`、`lib`、`startup` 和 `3rd_party/printf/printf.c`，包括第三方函数内 static；`build_closure_only: true` 排除未编译的演示程序。配置与产物保存在验证工程的 `ecra_semantics.yaml` 和 `.ecra/`，没有修改仓库原有的 `config/semantics.yaml`。

## 变量盘点核对

`scripts/audit_github_stm32_inventory.py` 独立重新解析 24 个真实编译单元，以 Clang AST 的 `VAR_DECL`、定义位置和静态存储属性建立清单，再按文件、行、名称、函数所有者与 ECRA 根变量逐项对照。对整个工程根目录独立核对的结果是 **51/51 对应，漏扫 0，额外 0，解析失败 0**。函数内 static 定义包括 `uart_init::default_cfg`、`uart_print_hex32::hex`、`compute_apb_prescaler::table`，以及第三方 `printf.c` 的 `_ftoa::pow10`。ECRA 清单还包括数组元素、结构体成员、容器及链接地址符号；这些派生行不能当作独立源代码声明计数。

全部 24 个编译单元为 `PARSED`。完整范围有 171 行变量清单、123 个可分类存储单元：`SAFE_PROVEN` 82、`SHARED_NO_REVIEW` 1、`SUSPECT` 36、`UNKNOWN` 4。静态复核队列为 40 项，RR_build 为 32.52%。另外 6 个链接脚本地址边界和 1 个未定义弱地址符号在清单中保留证据，分类为 `NON_STORAGE`，不进入存储风险分母。

| 指标 | 首轮扫描 | 完整范围及规则修复后 |
| --- | ---: | ---: |
| 编译单元 `PARSED` | 24/24 | 24/24 |
| 清单行 | 169 | 171 |
| 可分类存储单元 | 129 | 123 |
| 已证明安全 | 81 | 82 |
| 共享但无需复核 | 0 | 1 |
| 疑似风险 | 37 | 36 |
| 无法判断 | 11 | 4 |
| 待 OpenCode 复核 | 48 | 40 |

变化有具体证据：`_sbss/_ebss/_sdata/_edata/_etext/_estack` 是 ELF 与 map 一致的零尺寸链接地址边界；`_app_vector_base` 是本 standalone 镜像未定义的弱符号，源码仅取址。`s_tick_ms` 为 4 字节对齐的 volatile 标量，SysTick 是唯一写者，主循环只读；写者的 `++` 不会与另一写者发生丢更新，因此进入严格的单写者只读者自动筛除类。相应代码改动和正反例在 `ecra/extract.py`、`ecra/analysis.py`、`ecra/evidence.py` 与测试中。

在真实编译 AST 中，CMSIS 宏 `NVIC_EnableIRQ` 等展开为 `__NVIC_EnableIRQ`，旧扫描没有记录这些 IRQ 启停和优先级事件。现在扫描会保留原始调用名，并将这组 CMSIS API 归一化用于事件和初始化 CFG。重扫记录到 3 次 `NVIC_EnableIRQ`、3 次 `NVIC_DisableIRQ` 和 21 次 `NVIC_SetPriority`（含重复解析的 CMSIS 头文件内联调用）；`hw->irqn` 等动态 IRQ 实参仍为未解析，不能以归一化后的名称推断具体通道已经安全停用。

保留的风险不能按比例硬压低。例如 `apps/cli/cli_simple.c` 的 USART2 接收回调在中断中修改 `g_cli.buffer_pos`，主循环的 `process_pending_command` 末尾将其复位并清 `command_pending`，有可成立的丢字符/丢命令路径。

## OpenCode 逐项复核

40 个 `SUSPECT`/`UNKNOWN` 项均取得终态：**31 个 `REVIEWED_SAFE`、5 个 `FALSE_POSITIVE`、4 个 `CONFIRMED`**，失败、待处理、过期、重复和遗漏均为 0，`NEED_MORE_CONTEXT`/`LIKELY` 也为 0。每项的输入包、提示词、原始 JSONL、反证审计和结果收据都保存在 `.ecra/review/`。`scripts/export_github_stm32_review.py` 再次检查队列/收据一致性、扫描指纹及输入输出 SHA-256，并导出 [逐变量结果](github_stm32_bare_metal_review_results.json)。

四个确认风险对应两组可成立的交错：

| 变量 | 具体场景 |
| --- | --- |
| `g_cli.buffer_pos` | USART2 接收中断递增位置后，主循环处理旧命令时复位位置，可能覆盖新字符的位置。 |
| `command_pending` | USART2 中断为新命令置位后，主循环处理旧命令的末尾清零，可能丢失新命令。 |
| `g_cmd_buffer[*]` | USART2 中断写输入字符时，主循环读取并处理同一缓冲区，缺少稳定快照或所有权切换。 |
| `g_cli.history[*]` | 历史环满且浏览最旧条目时，主循环写入 `history[head]` 可与 USART2 中断读取该槽交错，形成混合字符串。 |

审计曾退回 `g_cli.history[*]` 的首轮回答，因为它引用的源码行内容不匹配；第二次读取源码并通过反证审计后才保存 `CONFIRMED`。这两次模型输出均留在对应收据的尝试记录中。

**报告状态仍为 `INCOMPLETE`。** 这是静态覆盖状态，不是 OpenCode 队列状态：事实文件保留 532 条保守未知事件（主要为指针解引用/未解析指向，另有内联汇编、外部调用等）及 14 条未知访问。它们不支持“整个固件已无其他风险”的声明；本次结论只覆盖该真实链接变体及已经盘点的存储单元。`.ecra/index.html` 与 `.ecra/opencode_review.html` 保留这一状态和全部候选记录。

## 验证门槛

- 完整回归：`python -m unittest discover -s tests -p 'test_*.py' -q`，执行 608 项，607 通过、1 项按原条件跳过，日志在 `output/github_stm32_regression_tests.log`；新增 CMSIS 宏展开、优先级事件和启停屏障的回归用例也单独通过。
- 独立盘点：`validation/github_stm32_bare_metal/inventory_audit_final.json`，24 TU，期望根变量 51，实际 51，差集均为空。
- 复核收据：`python scripts/export_github_stm32_review.py validation/github_stm32_bare_metal docs/github_stm32_bare_metal_review_results.json`，40/40 收据、扫描指纹和 SHA-256 校验通过。
- 固件 ELF 链接成功；未做板上运行验证，因此这里的并发结论来自源码、编译参数、ELF/map 与 OpenCode 复核，不代表硬件复现。
