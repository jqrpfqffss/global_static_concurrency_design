# 分类根因基线报告（修改前 / classification_root_causes_before）

**口径**：commit `3fb7ef7`（分类优化四）当前实现，2026-10-07 用三工程缓存
提取 parts 重放（`D:/ecra-bench/bench_one.py` 链路；betaflight 内存内重建）。
TOTAL = 编译变量（`coverage_source == compile_database`、非结构体容器），
扣除定义不在构建闭包内的依赖声明（klipper 12 / blackmagic 25 / betaflight 306）。

## 0. 基线汇总

| 工程 | TOTAL | SAFE_PROVEN | SHARED_NO_REVIEW | SUSPECT | UNKNOWN | 队列(S+U) | Review Rate | 10% 目标 |
|---|---|---|---|---|---|---|---|---|
| klipper（STM32F405, 58 TU） | 889 | 841 (94.6%) | 0 | 38 (4.3%) | 10 (1.1%) | 48 | **5.4%** | ✅ 已达标 |
| blackmagic（STM32F103, 192 TU） | 691 | 493 (71.3%) | 9 (1.3%) | 121 (17.5%) | 68 (9.8%) | 189 | **27.4%** | ❌ |
| betaflight（STM32F405, 497 TU） | 7630 | 5041 (66.1%) | 68 (0.9%) | 2380 (31.2%) | 141 (1.8%) | 2521 | **33.0%** | ❌ |

## 1. SUSPECT / UNKNOWN 主根因分布（每变量恰好一个主根因，桶和 = S+U）

统计脚本：`D:/ecra-bench/baseline_roots.py`；结果 JSON：
`D:/ecra-bench/baseline-roots-{klipper,blackmagic,betaflight}.json`。

### SUSPECT

| taxonomy 根因 | klipper | blackmagic | betaflight | 说明 |
|---|---|---|---|---|
| MULTI_WRITER（双写者，含 RMW 交叉） | 22 (46.0%) | 28 (14.8%) | 301 (11.9%) | ≥2 个物理域写/RMW |
| MULTI_FIELD_COHERENCY（多字段一致性） | 16 (33.3%) | 93 (49.2%) | 1528 (60.6%) | 同 root 多字段被一个域改、另一域同函数成对读 |
| DMA_CONFLICT（CPU↔DMA 至少一方写） | 0 | 0 | 531 (21.1%) | DMA 域与 CPU 域重叠访问 |
| WHOLE_OBJECT_ACCESS（整体写↔成员访问） | 0 | 0 | 18 (0.7%) | 整体 WRITE 继承到成员后成对冲突 |
| STALE_SNAPSHOT（旧值回写） | 0 | 0 | 1 (0.04%) | 提取器快照事实 |
| BITFIELD（位域并发写） | 0 | 0 | 1 (0.04%) | 位域容器跨上下文写 |
| INIT_RUNTIME_MIX（init 写者+运行期写者混合） | （含于 MULTI_WRITER；未单独成桶） | | | 见 §2-E G5 精化机会 |
| 其它 | 0 | 0 | 0 | |

### UNKNOWN（全部为变量局部精准 reason，无宽泛兜底）

| taxonomy 根因 | klipper | blackmagic | betaflight | 对应 reason code |
|---|---|---|---|---|
| UNKNOWN_CONTEXT / FUNCTION_POINTER / CALLBACK_EXPANSION | 6 (12.5%) | 47 (24.9%) | 56 (2.2%) | UNKNOWN_EXECUTION_CONTEXT |
| ADDRESS_ESCAPE / INDIRECT_CALL | 4 (8.3%) | 20 (10.6%) | 78 (3.1%) | UNKNOWN_ADDRESS_ESCAPE |
| DMA_LIFETIME | 0 | 1 (0.5%) | 7 (0.3%) | UNKNOWN_DMA_LIFETIME |
| MISSING_SOURCE / MISSING_CALLER / ALIAS_UNKNOWN / POINTER_SUBSCRIPT | 0 | 0 | 0 | — |
| UNKNOWN_PREEMPTION（次要标记，主根因为 SUSPECT） | 1 | 19 | 2334 | pending_confirmation |
| PROTECTION_UNRESOLVED（次要标记） | 38 | 60 | 1829 | pending_confirmation |
| RMW（次要标记，主根因多为双写者/一致性） | 4 | 60 | 960 | — |

## 2. 根因解释、典型变量与源码、修复机会

### A. MULTI_FIELD_COHERENCY —— 最大的桶（betaflight 1528 / blackmagic 93）

**机制**：同一 root struct 的 ≥2 个成员被一个物理域写，另一域在**同一函数内**
成对读取其中 ≥2 个 → 可能撕裂读取（value+valid、data+length 协议模式）。

**典型（真实风险，保留）**：`_mass_storage`、`st_usbfs_dev`（blackmagic USB
协议结构）；betaflight 的 USB VCP `APP_Rx_Buffer` 系列、串口 DMA 缓冲长度对。

**已实证的过宽子集（可通用修复）**：
- **const 幻影写制造的一致性**：blackmagic `dev_desc`（dfucore.c:67，
  `const usb_device_descriptor_s`）的 28 个成员全部因
  `memcpy(buf, cfg, …)` 的 `uint8_t **buf` 指向集在互斥 switch 分支
  （`*buf = (uint8_t*)usbd_dev->desc` vs `*buf = usbd_dev->ctrl_buf`）间
  流不敏感并集而背上幻影 WRITE，随后与真实 READ 配成"撕裂对"。
  Cortex-M 上 const 静态存储在 flash，运行期写物理不可能 → 这些写不可达。
- **DMA 上下文污染制造的一致性**：betaflight `DeviceInfo`（serial_4way.c:100，
  `uint8_32_u` union，前台 4way 协议使用）的冲突对中出现
  `FOREGROUND ↔ auto:DMA1_Stream0_IRQHandler` 等 DMA 上下文——前台协议
  代码被挂上 DMA ISR 上下文（上下文归属污染，见 §2-D）。

### B. DMA_CONFLICT（betaflight 531）

**机制**：CPU↔DMA 重叠且至少一方写。HAL DMA 契约恢复的缓冲区（串口
TX/RX DMA、ADC、USB）被 CPU 在 DMA 活动期写。双缓冲/半缓冲协议需要
运行期事实，静态保守保留是正确语义。
**待精化**：缓冲区"CPU 先写满 → 再 Start_DMA"的同函数程序序（写发生在
启动 API 之前 → 有序、无冲突）当前未建模，属通用 DMA 生命周期精化机会。

### C. MULTI_WRITER（klipper 22 / blackmagic 28 / betaflight 301）

**典型（真实风险，保留）**：klipper `analog_wake.wake`、`buttons_wake.wake`
（主任务 set / 定时器 IRQ clear，P0-HARD-RISK-04 模式）、`move_free_list`
（主循环分配 / 步进 ISR 归还）；betaflight 飞控双写者。
**已实证的过宽子集**：blackmagic `st_usbfs_dev.*`（libopencm3 USB 设备
结构）——初始化函数（前台、USB IRQ 使能前）+ USB ISR 运行期写的组合，
被 G5 一刀切计为双写者（§2-E）。

### D. UNKNOWN_CONTEXT（blackmagic 47 / betaflight 56 / klipper 6）

**机制**：写入函数 ∈ entry_uncertain（入口不确定性沿调用图前向传播）。
blackmagic 种子函数全部带 FUNCTION_ADDRESS 事实（地址被存入表/注册结构）
但其分发调用点未被 points-to 恢复：
- `gdb_target_destroy_callback`（gdb_main.c:101 存入 `target_controller_s`
  静态表，经堆对象 `t->tc->destroy_callback(...)` 两级链分发）；
- `remote_packet_process_swd`、`jtagtap_init`、`dwc_poll` 等。
这是当前流不敏感 points-to 对"堆对象字段 → 静态回调表 → 函数指针"
两级链的表达能力边界（Tier 2 精化目标）。

### E. G5 过保守（Init/Runtime 混合）

现状：全部写者 PRE（初始化链、异步源使能前）→ SAFE_INIT_ONLY_WRITE；
但只要存在任一运行期写者，PRE 写者照常计入冲突候选。
Cortex-M 复位时 NVIC 全禁用，可屏蔽 ISR 的使能事件（NVIC_EnableIRQ、
HAL_*_Start_IT…）可传递证明发生在 PRE 写之后 → PRE 写与该 ISR 的
运行期写有序、不可交错。不可屏蔽异常（NMI/HardFault）才必须保持 G5 保守。

### F. ADDRESS_ESCAPE（blackmagic 20 / betaflight 78 / klipper 4）

三个已实证的过宽子集（全部通用）：
1. **libc 语义未建模**：地址传给 memcpy（8 个）/strcmp（3 个）/
   strncasecmp（2 个）等闭包外标准库函数 → "流入未解析函数"。但参数语义
   已知（memcpy dst WRITE/src READ；strcmp/strncasecmp 只读），不应算
   不透明代码。blackmagic 13/20 由此产生。
2. **元素读误判 ADDRESS_TAKEN**：`f(tbl[i])`（tbl 为指针数组）——基址
   decay 已被下标消费，外层 vararg 隐式转换包装（类型=元素指针）再次置
   decay 位 → 元素读翻成 ADDRESS_TAKEN（gdb_reg_save_restore_strings、
   gdb_reg_type_strings、cortex_a_spr_names、cortexm_driver_str 等）。
   被调函数拿到的是元素值（const char* 指向 .rodata 字符串），既拿不到
   数组存储也无法写。
3. **const 点目标逃逸**：地址（指向 const 对象）流入不透明代码 → 逃逸。
   const 对象运行期不可写，逃逸不构成可写路径（与 §2-A 同一硬件事实）。

### G. 真实风险密度（按用户规则如实保留）

klipper 5.4% 中：wake flag 主任务/IRQ 双写、move 队列双管理、定时器
wrap 字段对一致性——均为真实破坏性模式。
betaflight/blackmagic 剩余候选中的飞控 ISR↔任务共享、USB 协议结构、
DMA 缓冲等属于工程真实设计，静态分析只能证明串行化或保护有效才能降噪。

## 3. 结论

- >10% 的来源不是单一机制：多字段一致性守门被幻影写/上下文污染放大
  （betaflight 1528 中至少 const/DMA 污染两支），UNKNOWN 全部为变量局部
  精准缺口但仍有三类系统性过宽（libc 语义、元素读、两级回调链）。
- Phase 2 起实施五项通用修复（const 幻影写、libc 语义表、元素读 decay、
  两级回调链 Tier2、G5 使能事件门控），每步重跑三工程基准并记录
  Candidate 下降量；全部为静态分析精度提升，无任何阈值放宽或项目特例。
