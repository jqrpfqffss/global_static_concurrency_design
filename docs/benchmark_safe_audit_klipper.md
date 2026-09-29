# Klipper SAFE 源码抽样审计

固定 commit：`61c0c8d2ef40340781835dd53fb04cc7a454e37a`，STM32F103xE USB target，50 个实际编译单元。2026-09-29 直接阅读源码完成 36 项检查；覆盖 global、file-static、function-static、struct member 及本轮两个 SAFE 主 proof。未调用 OpenCode。

本记录绑定中间快照 `d27fa6fd9847`，不是三个工程的最终验收结论。新快照必须核对相同 canonical storage 与 proof。旧抽样暴露的 GNU statement expression / va_arg 漏访问已转成通用回归测试；本次候选已排除旧的编码器 NO_RUNTIME 假证明。

2026-09-30 复核：这 36 个 symbol_id 在 `after-exact-sets`（7ae924af26ba）、`after-branch-context`（6f42cff9308a）、`after-vector-guards`（4e89188edbdf）的分类均仍为 SAFE，且主 proof 均相同。当前 d769cb5860fc 正在全新提取，完成后必须再次核对；此处不把中间分类一致当作新增样本的源码审计。

核对范围包括生成的 `out/compile_time_request.c`、`src/command.c/.h`、`src/ctr.h`、`basecmd.c`、`adccmds.c`、`buttons.c`、`generic/armcm_boot.c`、`initial_pins.c`、CMSIS system 文件以及实际 compile database。对系统时钟符号另搜索全部 50 个链接 TU，确认没有遗漏当前目标调用。

| # | canonical storage | 类型 / proof | 定义位置 | 源码检查结论 |
|---:|---|---|---|---|
| 1 | `_DECLS_119` | FILE_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/adccmds.c:119` | DECL_COMMAND 宏只在 .compile_time_request 定义编译期描述串；没有运行访问或地址传递。 |
| 2 | `command_parameters21[*]` | FILE_STATIC / SAFE_READ_ONLY | `out/compile_time_request.c:339` | 生成的 const 参数类型数组通过 parser.param_types 进入 command_parsef；只执行 READP(*param_types)，递增局部指针，不修改数组或传给 DMA。 |
| 3 | `AHBPrescTable[*]` | GLOBAL / SAFE_NO_RUNTIME_ACCESS | `lib/stm32f1/system_stm32f1xx.c:124` | 只有 SystemCoreClockUpdate 读取；当前 50 TU 闭包没有调用或注册该函数，启动 SystemInit 不调用它。 |
| 4 | `command_identify_size` | GLOBAL / SAFE_READ_ONLY | `out/compile_time_request.c:1874` | basecmd.c command_identify 仅 READP 读取大小；未取址、无运行写或 DMA 使用。 |
| 5 | `alloc_chunk::_DECLS_34` | LOCAL_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/basecmd.c:34` | alloc_chunk 内 shutdown 宏产生局部 static 描述串；运行传递的是 ctr_lookup_static_string 的数值结果。 |
| 6 | `command_index[*].encoded_msgid` | STRUCT_MEMBER / SAFE_NO_RUNTIME_ACCESS | `out/compile_time_request.c:724` | command_parser.encoded_msgid 有初始化，路由按数组索引，不读取此字段；实际读取的 encoded_msgid 属于 command_encoder。 |
| 7 | `command_index[*].flags` | STRUCT_MEMBER / SAFE_READ_ONLY | `out/compile_time_request.c:724` | command_dispatch 只读取 parser.flags；整个表只由生成的静态初始化写入。 |
| 8 | `_DECLS_136` | FILE_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/adccmds.c:136` | DECL_SHUTDOWN 宏只生成编译期描述串；运行调用来自生成的 C 调度函数，不读取此串。 |
| 9 | `command_parameters22[*]` | FILE_STATIC / SAFE_READ_ONLY | `out/compile_time_request.c:341` | 生成的 const 参数类型数组通过 parser.param_types 进入 command_parsef；只执行 READP(*param_types)，递增局部指针，不修改数组或传给 DMA。 |
| 10 | `APBPrescTable` | GLOBAL / SAFE_NO_RUNTIME_ACCESS | `lib/stm32f1/system_stm32f1xx.c:125` | 只有定义；当前 STM32F103 闭包没有名称引用或取址。 |
| 11 | `command_index_size` | GLOBAL / SAFE_READ_ONLY | `out/compile_time_request.c:1481` | command.c command_lookup_parser 仅读取上界；未取址、无运行写或 DMA 使用。 |
| 12 | `analog_in_task::_DECLS_116` | LOCAL_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/adccmds.c:115` | analog_in_task 内 sendf 宏的局部 static 描述串；实际运行参数是 ctr_lookup_encoder 返回的编码器对象。 |
| 13 | `_DECLI_303._end_of_line` | STRUCT_MEMBER / SAFE_NO_RUNTIME_ACCESS | `src/basecmd.c:303` | DECL_CTR_INT 生成的 .compile_time_request 记录成员；构建脚本读取目标文件生成 C 源码，固件不读取、写入或传播该成员地址。 |
| 14 | `command_index[*].func` | STRUCT_MEMBER / SAFE_READ_ONLY | `out/compile_time_request.c:724` | command_dispatch 只读取 parser.func 并调用其目标；函数目标写其它存储不会写回该指针槽。 |
| 15 | `_DECLS_71` | FILE_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/adccmds.c:71` | DECL_COMMAND 配置描述串，只供构建阶段提取；未进入运行时指针表。 |
| 16 | `command_parameters23[*]` | FILE_STATIC / SAFE_READ_ONLY | `out/compile_time_request.c:343` | 生成的 const 参数类型数组通过 parser.param_types 进入 command_parsef；只执行 READP(*param_types)，递增局部指针，不修改数组或传给 DMA。 |
| 17 | `SystemCoreClock` | GLOBAL / SAFE_NO_RUNTIME_ACCESS | `lib/stm32f1/system_stm32f1xx.c:123` | 所有读写均位于无调用/无注册的 SystemCoreClockUpdate；其它 MCU 和未链接的 sdio.c 引用不属于当前目标。 |
| 18 | `initial_pins_size` | GLOBAL / SAFE_READ_ONLY | `out/compile_time_request.c:249` | initial_pins_setup 只读取循环上界；无写入、取址或 DMA 使用。 |
| 19 | `buttons_task::_DECLS_160` | LOCAL_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/buttons.c:159` | buttons_task 内 sendf 描述串；运行发送的数据 b->reports 与这个局部描述串是不同存储。 |
| 20 | `_DECLI_303._request` | STRUCT_MEMBER / SAFE_NO_RUNTIME_ACCESS | `src/basecmd.c:303` | DECL_CTR_INT 生成的 .compile_time_request 记录成员；构建脚本读取目标文件生成 C 源码，固件不读取、写入或传播该成员地址。 |
| 21 | `command_index[*].num_args` | STRUCT_MEMBER / SAFE_READ_ONLY | `out/compile_time_request.c:724` | command_dispatch 只读取 parser.num_args 确定参数栈数组长度；无整表写入。 |
| 22 | `_DECLS_94` | FILE_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/adccmds.c:92` | 跨行 DECL_COMMAND 描述串；名称行号来自宏展开，无运行读取或地址逃逸。 |
| 23 | `command_parameters24[*]` | FILE_STATIC / SAFE_READ_ONLY | `out/compile_time_request.c:345` | 生成的 const 参数类型数组通过 parser.param_types 进入 command_parsef；只执行 READP(*param_types)，递增局部指针，不修改数组或传给 DMA。 |
| 24 | `command_allocate_oids::_DECLS_230` | LOCAL_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/basecmd.c:230` | command_allocate_oids 内 shutdown 描述串；不传其地址给 IRQ 或外部函数。 |
| 25 | `_DECLI_303._values` | STRUCT_MEMBER / SAFE_NO_RUNTIME_ACCESS | `src/basecmd.c:303` | DECL_CTR_INT 生成的 .compile_time_request 记录成员；构建脚本读取目标文件生成 C 源码，固件不读取、写入或传播该成员地址。 |
| 26 | `command_index[*].num_params` | STRUCT_MEMBER / SAFE_READ_ONLY | `out/compile_time_request.c:724` | command_parsef 只读取 parser.num_params；相邻参数数据写入 args，不写 parser。 |
| 27 | `_DECLS_167` | FILE_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/basecmd.c:167` | DECL_COMMAND 描述串；构建生成的函数调用不会引用原描述串存储。 |
| 28 | `command_parameters25[*]` | FILE_STATIC / SAFE_READ_ONLY | `out/compile_time_request.c:347` | 生成的 const 参数类型数组通过 parser.param_types 进入 command_parsef；只执行 READP(*param_types)，递增局部指针，不修改数组或传给 DMA。 |
| 29 | `command_buttons_add::_DECLS_92` | LOCAL_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/buttons.c:92` | command_buttons_add 内 shutdown 描述串；作用域局部、只有编译阶段消费者。 |
| 30 | `_DECLI_121._end_of_line` | STRUCT_MEMBER / SAFE_NO_RUNTIME_ACCESS | `src/generic/armcm_boot.c:121` | DECL_CTR_INT 生成的 .compile_time_request 记录成员；构建脚本读取目标文件生成 C 源码，固件不读取、写入或传播该成员地址。 |
| 31 | `command_index[*].param_types` | STRUCT_MEMBER / SAFE_READ_ONLY | `out/compile_time_request.c:724` | command_parsef 只读取 parser.param_types，递增的是局部指针副本，不是指针槽。 |
| 32 | `_DECLS_235` | FILE_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/basecmd.c:235` | command_allocate_oids 的 DECL_COMMAND 描述串，未被运行代码访问。 |
| 33 | `command_parameters26[*]` | FILE_STATIC / SAFE_READ_ONLY | `out/compile_time_request.c:349` | 生成的 const 参数类型数组通过 parser.param_types 进入 command_parsef；只执行 READP(*param_types)，递增局部指针，不修改数组或传给 DMA。 |
| 34 | `command_buttons_query::_DECLS_110` | LOCAL_STATIC / SAFE_NO_RUNTIME_ACCESS | `src/buttons.c:110` | command_buttons_query 内 shutdown 描述串；运行调用使用生成的消息编号。 |
| 35 | `_DECLI_121._request` | STRUCT_MEMBER / SAFE_NO_RUNTIME_ACCESS | `src/generic/armcm_boot.c:121` | DECL_CTR_INT 生成的 .compile_time_request 记录成员；构建脚本读取目标文件生成 C 源码，固件不读取、写入或传播该成员地址。 |
| 36 | `encode_acknak.encoded_msgid` | STRUCT_MEMBER / SAFE_READ_ONLY | `src/command.c:260` | command_encodef 仅 READP 读取 encoded_msgid；encode_acknak 的短消息分支可能提前返回，不会产生写访问。 |

逐项访问事实、定义源码 SHA-256、旧 proof 和审计说明保存在 `output/preopencode-benchmark/klipper/after-statement-expr/safe-source-audit.json`。样本未发现会改变 SAFE 分类的遗漏写者，但这不证明所有未抽样 SAFE 均正确，也不覆盖后续更改的分类快照。
