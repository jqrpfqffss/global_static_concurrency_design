# GitHub STM32 裸机工程端到端验证

## 工程与构建范围

- 上游：[ViniBR01/stm32-bare-metal](https://github.com/ViniBR01/stm32-bare-metal)，主仓库提交 `065875948326eab4d82cdaca59dd8bbd96d3516e`。验证目标为 STM32F411 的 `cli_simple`、`PROFILE=standalone`。
- 固件根目录：`validation/github_stm32_bare_metal`。实际 ARM GCC 构建产物为 `build/apps/cli/cli_simple_standalone/cli_simple_standalone.elf` 与同目录的 `.map`。
- 主 Makefile 的 `keys` 前置任务在本机缺少 Python `cryptography` 时失败；驱动与依赖库已构建，随后直接运行 `mingw32-make -C apps/cli EXAMPLE=cli_simple PROFILE=standalone`，ELF 链接成功。没有烧录开发板。
- `scripts/prepare_github_stm32_bare_metal.py` 从这次真实 Make 命令日志与 linker map 生成 `build/compile_commands.json`，仅保留最终链接闭包的 24 个 C 编译单元。构建命令的芯片宏为 `STM32F411xE`，架构为 Cortex-M4，硬浮点，`gnu11`。
- 排查范围为本固件实际参与链接的 `apps/cli`、`drivers`、`utils`、`lib`、`startup` 和 `3rd_party/printf/printf.c`，包括第三方函数内 static；`build_closure_only: true` 排除未编译的演示程序。配置与产物保存在验证工程的 `ecra_semantics.yaml` 和 `.ecra/`，没有修改仓库原有的 `config/semantics.yaml`。

## 变量盘点核对

`scripts/audit_github_stm32_inventory.py` 独立重新解析 24 个真实编译单元，以 Clang AST 的 `VAR_DECL`、定义位置和静态存储属性建立清单，再按文件、行、名称、函数所有者与 ECRA 根变量逐项对照。对整个工程根目录独立核对的结果是 **51/51 对应，漏扫 0，额外 0，解析失败 0**。函数内 static 定义包括 `uart_init::default_cfg`、`uart_print_hex32::hex`、`compute_apb_prescaler::table`，以及第三方 `printf.c` 的 `_ftoa::pow10`。ECRA 清单还包括数组元素、结构体成员、容器及链接地址符号；这些派生行不能当作独立源代码声明计数。

全部 24 个编译单元为 `PARSED`。完整范围有 171 行变量清单、123 个可分类存储单元：`SAFE_PROVEN` 84、`SHARED_NO_REVIEW` 1、`SUSPECT` 34、`UNKNOWN` 4。静态复核队列为 38 项，RR_build 为 30.89%。另外 6 个链接脚本地址边界和 1 个未定义弱地址符号在清单中保留证据，分类为 `NON_STORAGE`，不进入存储风险分母。当前扫描指纹为 `6f675698a8e112ba42dc3169f94f4a19498c830109a6ea3ba92ad3ab88376d9a`。

| 指标 | 首轮扫描 | 完整范围及规则修复后 |
| --- | ---: | ---: |
| 编译单元 `PARSED` | 24/24 | 24/24 |
| 清单行 | 169 | 171 |
| 可分类存储单元 | 129 | 123 |
| 已证明安全 | 81 | 84 |
| 共享但无需复核 | 0 | 1 |
| 疑似风险 | 37 | 34 |
| 无法判断 | 11 | 4 |
| 待 OpenCode 复核 | 48 | 38 |

变化有具体证据：`_sbss/_ebss/_sdata/_edata/_etext/_estack` 是 ELF 与 map 一致的零尺寸链接地址边界；`_app_vector_base` 是本 standalone 镜像未定义的弱符号，源码仅取址。`s_tick_ms` 为 4 字节对齐的 volatile 标量，SysTick 是唯一写者，主循环只读；写者的 `++` 不会与另一写者发生丢更新，因此进入严格的单写者只读者自动筛除类。相应代码改动和正反例在 `ecra/extract.py`、`ecra/analysis.py`、`ecra/evidence.py` 与测试中。

本轮再将 `g_cli.history_stash_len` 与 `spi_dma_active[*]` 从候选移至 `SAFE_PROVEN`：两者为内部普通存储，已解析的运行期访问仅有赋值，没有读取、DMA 访问、重叠别名或相关证据缺口。新规则仅用于主循环与 IRQ 间确有候选冲突的单核裸机存储；`volatile`、RMW、任务线程、双 IRQ、位域和不透明地址逃逸仍保留复核。对应正反例已纳入回归。

在真实编译 AST 中，CMSIS 宏 `NVIC_EnableIRQ` 等展开为 `__NVIC_EnableIRQ`，旧扫描没有记录这些 IRQ 启停和优先级事件。现在扫描会保留原始调用名，并将这组 CMSIS API 归一化用于事件和初始化 CFG。重扫记录到 3 次 `NVIC_EnableIRQ`、3 次 `NVIC_DisableIRQ` 和 21 次 `NVIC_SetPriority`（含重复解析的 CMSIS 头文件内联调用）；`hw->irqn` 等动态 IRQ 实参仍为未解析，不能以归一化后的名称推断具体通道已经安全停用。

保留的风险不能按比例硬压低。例如 `apps/cli/cli_simple.c` 的 USART2 接收回调在中断中修改 `g_cli.buffer_pos`，主循环的 `process_pending_command` 末尾将其复位并清 `command_pending`，有可成立的丢字符/丢命令路径。

本轮还[直接核对了初始化时序](github_stm32_bare_metal_direct_review.md)：UART IRQ 与 RX 回调均在 `cli_init` 之前可用；可打印字节在两者之间到来时，零值 `buffer_size` 的无符号减一使条件误通过，随后通过空 `buffer` 指针写入。旧版模型将这两个成员判为安全，遗漏了此窗口；当前静态分类仍把它们留在 `SUSPECT` 队列。复核包现要求逐项核对异步入口、注册和初始化顺序。

## 历史 OpenCode 复核与当前状态

先前扫描指纹 `66f5db39b53d75f9853ce57f3e956604a1c11d4ee069443fcbb46c9c159e1490` 的 40 项曾取得终态：31 个 `REVIEWED_SAFE`、5 个 `FALSE_POSITIVE`、4 个 `CONFIRMED`，当时的队列/收据、扫描指纹及输入输出 SHA-256 已通过导出检查，留有[历史逐变量结果](github_stm32_bare_metal_review_results.json)。这些结果不能充当当前扫描指纹的复核收据；其中 `g_cli.buffer`、`g_cli.buffer_size` 的安全结论已被上述初始化窗口反证。

**当前 38 项均为 `PENDING`，没有新的 OpenCode 终态。** 本轮尝试调用 OpenCode 时，自动审批因当前 `AGENTS.md` 禁用外部代理委派及源码外传风险而拒绝；没有改用间接调用。38/38 个当前指纹的证据包已在 `output/github_stm32_review_packet_check_final/review/` 独立生成，34 项含初始化时序必查项。待用户明确重新启用 OpenCode 只读复核后，才能生成当前指纹下的收据。Codex 直接审查的初始化发现与模型收据分开记录。

历史 OpenCode 复核的四个确认风险对应两组可成立的交错：

| 变量 | 具体场景 |
| --- | --- |
| `g_cli.buffer_pos` | USART2 接收中断递增位置后，主循环处理旧命令时复位位置，可能覆盖新字符的位置。 |
| `command_pending` | USART2 中断为新命令置位后，主循环处理旧命令的末尾清零，可能丢失新命令。 |
| `g_cmd_buffer[*]` | USART2 中断写输入字符时，主循环读取并处理同一缓冲区，缺少稳定快照或所有权切换。 |
| `g_cli.history[*]` | 历史环满且浏览最旧条目时，主循环写入 `history[head]` 可与 USART2 中断读取该槽交错，形成混合字符串。 |

审计曾退回 `g_cli.history[*]` 的首轮回答，因为它引用的源码行内容不匹配；第二次读取源码并通过反证审计后才保存 `CONFIRMED`。这两次模型输出均留在对应收据的尝试记录中。

**报告状态仍为 `INCOMPLETE`。** 事实文件保留 532 条保守未知事件（主要为指针解引用/未解析指向，另有内联汇编、外部调用等）。旧报告中的 14 条“未知入口访问”均指向 ELF/map 证实为 `NON_STORAGE` 的链接边界或未定义弱地址符号；当前统计将它们单列为 `non_storage_unknown_entry_accesses=14`，真实存储的 `unknown_accesses=0`。这不消除指针与汇编未知事实，也不支持“整个固件已无其他风险”的声明。`.ecra/index.html` 与 `.ecra/opencode_review.html` 保留当前待复核队列。

## 验证门槛

- 完整回归：`python -m unittest discover -s tests -p 'test_*.py' -q`，执行 620 项，619 通过、1 项按原条件跳过，日志在 `output/github_stm32_regression_tests.log`；新增非存储未知入口统计、初始化时序复核、纯写存储正反例、收据真实性及扫描中引擎变化用例通过。
- 独立盘点：`validation/github_stm32_bare_metal/inventory_audit_final.json`，24 TU，期望根变量 51，实际 51，差集均为空。
- 复核收据：[历史导出](github_stm32_bare_metal_review_results.json)只对应旧指纹；当前指纹下 38/38 项仍待 OpenCode 复核。当前 `status --json` 报告 `review_complete: false`、`unresolved: 38`。
- 固件 ELF 链接成功；未做板上运行验证。历史四项模型结论和本轮初始化时序直接审查均基于源码、编译参数及 ELF/map，不代表硬件复现。
