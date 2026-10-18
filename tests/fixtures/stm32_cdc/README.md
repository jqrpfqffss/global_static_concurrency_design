# STM32CubeF4 CDC 裸机实工程验证用例

实际构建基于 STMicroelectronics/STM32CubeF4 v1.28.3 的 STM324xG_EVAL
USB_Device/CDC_Standalone，提交固定为
`94cae6e83f00e276a11957e7833c01ac3d0bd7af`。
这是厂商维护的 USB CDC / USART3 / DMA / TIM3 桥接应用，不是 RTOS 工程。
保留原应用、HAL、USB 中间件、启动文件和链接脚本，每个场景生成独立 ARM ELF。

`p00.c` 是未注入风险的基线。`p01.c` 到 `p20.c` 在原工程中增加 TIM6/TIM7
或 DMA2 stream0 的受控场景；这些资源与应用使用的 TIM3/DMA1 stream3 分开。
用例均故意保持小型，背景工程及调用、IRQ、外设配置是真实构建输入。

| 场景 | 独立预期 | 核心机制 |
|---|---|---|
| p01/p02 | 风险 | 直接 / 四层函数旧值写回 |
| p03/p04 | 风险 | 只保护最终写 / BASEPRI 阈值不足 |
| p05/p06 | 风险 | 字段不变式 / memcpy 对象快照写回 |
| p07/p08 | 风险 | 函数指针共用 Setter / 不同锁保护同一全局量 |
| p09/p10 | 风险 | 代际复用 / CPU 关中断仍与 DMA 争用 |
| p11/p12 | 风险 | IRQ 等待不能抢占的 tick / 长度 double-fetch |
| p13/p14/p15 | 安全对照 | 完整 PRIMASK / 同抢占级 / 有效 BASEPRI |
| p16 | 安全对照 | DMA 完成及 EN 清零后才复用源 |
| p17/p18 | 证据不足 | 二进制板级策略 / 二进制回调调用者 |
| p19 | 安全对照 | 有意覆盖的单字命令，无读改写事务 |
| p20 | 风险 | IRQ 先使能，回调对象后初始化 |

`expectations.json` 在首轮模型调用前写成。它与 `private_board.c` 留在验证仓库，
不复制到模型可读的固件目录。p17/p18 仅复制编译后的 `policy.o`，因此评估的是
**源码复核在证据缺失时能否保留不确定性**，不能将预期理解为二进制实际有缺陷。
模型只看到中性的项目编号、`App/lab.c`、正常 Clang Packet 与案例库。

```powershell
py -3.10 scripts/validate_stm32_cdc.py prepare
py -3.10 scripts/validate_stm32_cdc.py scan
py -3.10 scripts/validate_stm32_cdc.py review --round replay --workers 3
py -3.10 scripts/validate_stm32_cdc.py summary --round replay
py -3.10 scripts/replay_stm32_interleavings.py
```

需要 git、CMake、Ninja、GNU Arm Embedded GCC、libclang 和已经配置好模型的 OpenCode。
默认模型为 `kimi/kimi-k2.7-code`，可用 `--model` 指定现有模型。
脚本不登录、不设置密钥，不修改中央 `config/semantics.yaml`，不烧录目标板。
`prepare` 把案例库复制到每个独立工程；要验证更新后的库，可更新这些副本，另开
`--round` 保存结果。OpenCode 的职责始终是只读复核，Codex 直接实施工具修改。

扫描复用按引擎内容、编译请求和源文件哈希区分的真实 Clang 提取响应，并逐一验证
包含头文件与响应内容哈希。各变体的 `lab.c` 单独解析；合并、调用恢复、分析、队列、
报告仍运行原有 ECRA 流程。不得用这一复用宣称做了 21 次完全独立的冷扫描。
验证过程中不得同时修改 `ecra` 实现；原流程的版本一致性保护会拒绝混用版本。

只复核矩阵指定的变量，完整扫描清单保存在各项目 `.ecra` 中。安全样本通过现有
抽查接口选出并使用 `run` 模式显式送审，原静态分类与正常候选队列不变。
其余变量留待复核，整个真实项目不能因此宣称“全部无风险”。

宿主机回放在原用例源码的副本中插入明确的一次性抢占点，用简化的
PRIMASK/BASEPRI/NVIC 调度模型检查数据结果。它验证给定交错和安全反证，
不模拟 STM32 外设、真实时间或总线，不属于板上复现。

详细结果见 `docs/stm32_cube_cdc_validation.md`；原始 ELF、日志、事实、
模型事件、Packet、收据与回放保存在忽略的 `validation/stm32_cube_cdc_20261018`。
