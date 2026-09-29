# UNKNOWN 根因聚类（验证进行中）

下方第一张表为冻结 baseline 的同构建闭包结果。新增中间结果与修复状态见后文；最终统一快照仍在重跑。所有 fanout 按唯一 canonical variable 计数，同一变量重复的路径或 gap 不重复计数，多个原因之间仍可能重叠。

| 原因 | Klipper（345 UNKNOWN） | Blackmagic native（674 UNKNOWN） |
|---|---:|---:|
| FUNCTION_ADDRESS | 132 | 481 |
| INDIRECT_CALL | 131 | 469 |
| POINTER_SUBSCRIPT | 132 | 460 |
| POINTER_DEREFERENCE | 104 | 434 |
| UNRESOLVED_POINTEE | 110 | 434 |
| EXTERNAL_CALLEE | 110 | 433 |
| STATIC_INITIALIZER_REFERENCE | 139 | 224 |
| ADDRESS_ESCAPE | 181 | 217 |
| INLINE_ASSEMBLY | 132 | 202 |
| DMA_SHARED_REVIEW | 0 | 3 |

两项目都超过 10% 诊断阈值，必须继续分析；该阈值不用于强行判 SAFE。优先排查静态函数表/注册表关联性、指针间接访问目标、物理上下文继承与无关调用的跨变量传播。具体比例变化需等新引擎跑完，不能把 baseline 高 fanout 本身当作“所有相关 blocker 都无关”的证明。

Betaflight 的冻结 baseline 在 `context_graph()` 的 `all_paths[child][cid].append(child_route)` 发生内存耗尽，因此不存在可用于分类降幅的 baseline 数量。新引擎把显式路径族换成完整调用图存储，避免把分析资源耗尽混成变量 UNKNOWN；这属于分析可完成性的修复，不是降低安全标准。

## 2026-09-30：Klipper 中间结果

`after-assembly-entry` 共 221 UNKNOWN / 733 分类项（30.15%）。原因分布：ADDRESS_ESCAPE 142、RELEVANT_ALIAS 131、EXECUTION_CONTEXT 62、RELEVANT_MISSING_TU 25、INLINE_ASM 1。这些是重叠计数，不能相加。该运行仍存在 extern 合并丢 section 的缺陷，不作为最终验收结果。

| 源码位置与事实 | 影响 UNKNOWN 变量数 | 当前判断 / 后续动作 |
|---|---:|---|
| `src/command.c:178`，pointer store 的目标未收敛 | 135 | 与可变参数 payload、byte buffer 和 allocation may-set 有关；需要继续收窄传递关系，不能直接清 blocker |
| `src/command.c:168`，已知与 opaque pointee 混合 | 113 | 保留变量级 may-target 缺口，继续核对变参位置和对象布局 |
| `out/compile_time_request.c:259`，ResetHandler 向量引用 | 62 | 宏 section 与跨 TU extern 合并丢失属性；已新增通用修复和测试，等待完整重跑 |
| `src/stm32/stm32f1.c:265`，向量表地址写入寄存器 | 62 | 实际硬件向量重定位，不能简单当普通 callback 逃逸；需恢复目标寄存器和实际槽位语义 |
| `src/command.c:181 / 183`，untyped memcpy 的指针内容 | 各 33 | 需要按 buffer 内容来源与拷贝范围继续精化；保留真实未决项 |

此前 `usb_cdc.c:349` 的 87 项逃逸来自编译期恒假的 `NEED_PROGMEM` 分支，现由通用常量条件证明消除。条件求值本身的副作用仍保留。启动阶段 literal ARM branch 已恢复调用边；它本身不提供中断屏蔽证明。

生成命令：`python scripts/preopencode_unknown_causes.py output/preopencode-benchmark/klipper/after-assembly-entry`。原始去重结果保存在该目录的 `unknown-top-sites.json`。

## SUSPECT 与分析资源问题

当前串口工程 d769cb5860fc：154 项中 SAFE 54、SUSPECT 97、UNKNOWN 3；23/23 TU 解析成功。`command_image.sequence`、`reply_bank` 已通过向量入口与 callback 句柄条件恢复单 IRQ 证明。剩余候选应按实际冲突或初始化/保护缺口检查，不能按目标 SAFE 比例降级。

Betaflight 的别名扩散诊断发现全局结构体嵌套数组被误归入 whole-object overlap；已恢复声明布局与逐维边界，仍待完整求解。Blackmagic 曾在证据递归复制阶段 OOM，已取消这类重复深拷贝。内存耗尽不是 UNKNOWN 根因占比中的一个变量分类；这些失败运行没有可用分类总数。
