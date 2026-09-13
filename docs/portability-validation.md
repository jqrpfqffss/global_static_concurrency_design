# 跨 STM32 项目接入与功能验收

日期：2026-09-13。对应当前工作区代码；设计基线见[并发工具设计](concurrency-tool-design.md)。本文区分“工具流程正常”和“固件已证明安全”，不把两者混同。

验证环境：Windows、Python 3.10.11、libclang 18.1.1、PyYAML 6.0.3、CMake 3.31.10、Ninja 1.13.2、GNU Arm Embedded 10.3-2021.10（GCC 10.3.1）。这是实际验证组合，不代表其它版本组合已全部验收。

## 1. 本轮主动修复

| 方面 | 修复与可验证行为 |
|---|---|
| 工具侧配置 | `init` 集中创建并登记；旧 `.ecra/semantics.yaml` 原样迁移、备份保留；同名工程隔离；不借用未登记的同名配置。 |
| 快速启动 | `projects` 查看 ID，`--profile` 一条命令运行；`doctor/status/report/review` 保留分步入口；两类模板默认不调用模型。 |
| 工程结构 | 默认包含 `.` 并排除常见第三方/产物目录，避免遗漏 User/BSP 等业务代码；嵌套 Debug/Release 数据库自动发现，冲突要求选择。 |
| 首次 CMake | 自动识别唯一 Arm GCC 工具链，支持显式指定；验证真实 ARM 对象而非宿主机目标。 |
| 构建变体 | `expected_defines` 支持存在性及 `NAME=value` 精确校验，处理 `-D`、`-U` 和参数顺序，避免裸机/RTOS 变体混用。 |
| 原子头文件兼容 | 自动发现的 GCC 私有头目录作为后备，优先运行库兼容头；修复 H747 原子操作文件误用 GCC 私有 stdatomic 实现的失败。保留所有诊断，不删除原子语义。 |
| 中断注册 | 恢复跨文件多层包装、`&Callback`、`(*slot)()`、指定字段回调表和 `NVIC_SetVector` 的可恢复函数地址。 |
| 注册歧义 | API 无匹配、目标不可恢复、规则重叠保留明确缺口；同一上下文的可能重入按逻辑或合并，不按配置顺序覆盖。 |
| 安全筛除 | 单一读写位置不再替代执行上下文检查；上游回调逃逸沿调用图传播，漏编译单元和关键覆盖缺口阻止错误安全结论。 |
| 报告 | 安全计数跳转到全量变量表并筛选；显示安全筛除原因和阻断项；已有候选优先于不一致的旧安全标签。 |
| 配置可靠性 | YAML 重复键、错误格式、入口类型冲突、非法正则/超时提前报错；索引加锁、原子更新；测试使用隔离配置目录。 |

## 2. 自动回归

从工具根目录运行：

```powershell
py -3.10 -m unittest discover -s tests -v
```

本轮最终全量结果：**141 项测试通过，0 失败**。日志：[`regression.log`](../output/portability-audit/regression.log)。其中新增移植专项 [`tests/test_portability.py`](../tests/test_portability.py) 含 20 项测试；部分测试以多个 CPU/参数组合运行子用例。

- Cortex-M0/M3/M4/M7 参数分别完整执行初始化、按 ID 扫描、状态恢复检查、报告再生成；路径含空格，业务代码位于 `User/DriversCustom`，默认不使用模型。
- 跨翻译单元多层回调、取址和解引用调用、乱序指定字段初始化、动态向量包装均使用真实 Clang 提取，不用手工伪造调用边代替。
- 反例包含一个写点被两个 IRQ 使用、已知 main 路径同时存在未知注册入口、漏掉写入变量的翻译单元、重叠注册规则；必须保留风险或缺口。
- 实际 CMake/Ninja/Arm GCC 构建包含 `<stdint.h>`、`<stdatomic.h>`、原子 fetch-add/store，检查全部解析成功及 ELF 标识和 `e_machine=40`（ARM）。这项测试在缺少工具链的机器会明确跳过；本次环境具备依赖，实际执行并通过。
- 既有回归继续检查 static 身份、头文件/条件分支盘点、DMA、模型协议正常/失败/中断、缓存与扫描过期保护、SQLite 和双 HTML 交付。

全量通过表示已覆盖用例满足断言，不是对任意 MCU、任意 C 扩展或任意运行时调度的数学完备证明。

## 3. 真实项目与可重复交付验收

工具侧已登记三个配置：

```powershell
py -3.10 run_ecra.py projects
py -3.10 run_ecra.py --profile serial-continue
py -3.10 run_ecra.py --profile h747-bare
py -3.10 run_ecra.py --profile stm32-demo
```

前三个运行命令分别是不同工程的独立完整排查，不是扫描同一工程所需的三个步骤。日常只需选一条。示例首次接入可运行 `py -3.10 examples/stm32_demo/setup_demo.py`；它现在也将语义配置登记在工具侧。

F103 与 H747 使用原工程 CMake 配置和真实增量构建，不修改固件源码、不烧录目标板；示例使用 Cortex-M7 Clang 解析夹具，不作为实际硬件验证。H747 配置显式选择 `APP_RTOS=0`，但该验证工程含副核共享场景，因此保留 `dual_core` 限制，不能声明整个芯片无风险。

扫描完成后可执行只读交付验收：

```powershell
py -3.10 validation/verify_portability_reports.py
py -3.10 run_ecra.py status --profile serial-continue --json
py -3.10 run_ecra.py report --profile serial-continue
```

验收脚本校验当前实现/源码/配置指纹、主构建解析完整性、CMake 步骤、产物存在性、变量身份、分类数量、SQLite 完整性及 JSON 一致性、安全标签与风险/缺口矛盾，并输出统计。它不会修改固件或扫描状态。可传入一个或多个配置 ID 检查自己的已生成报告。

日志与统计位于 `output/portability-audit/`：`serial-run.log`、`h747-run.log`、`demo-run.log` 和 `verification.json`。这些是当次运行证据；修改实现、源码或配置后应重扫再验收，不能沿用旧统计。

最终只读验收返回 **0**，三个项目均通过；机器可读证据见 [`verification.json`](../output/portability-audit/verification.json)。实际结果如下：

| 配置 ID | 主构建解析成功/总数 | 目标变量 | 疑似风险变量 | 无法判断变量 | 静态筛除无风险 | 候选及独立缺口项 |
|---|---:|---:|---:|---:|---:|---:|
| `serial-continue` | 23/23 | 45 | 38 | 5 | 2 | 72 |
| `h747-bare` | 34/34 | 69 | 27 | 41 | 0 | 98 |
| `stm32-demo` | 2/2 | 13 | 7 | 3 | 2 | 12 |

H747 另有 1 个补充声明，示例另有 1 个普通台账项，未计入风险/安全列。候选及独立缺口的数量不是风险变量数量。F103/H747 的 CMake configure、build 均返回 0，主构建解析失败均为 0；`report --profile` 分步刷新也正常执行。三个项目的扫描均返回 `2 / INCOMPLETE`，因为仍保留未解决的上下文、别名、条件分支等证据缺口和待复核项；这与交付验收通过不矛盾。H747 明确保留非单核约束，没有把 69 个变量统称为无风险。

真实 HTML：[F103](../serial%20-%20continue/.ecra/index.html)、[H747 CM7 裸机变体](../validation/stm32_concurrency/.ecra/portability-cm7-bare/index.html)、[示例](../examples/stm32_demo/.ecra/index.html)。

## 4. 页面实测

通过本机 HTTP 服务加载自包含 HTML（自动化浏览器限制直接打开 `file:`，服务仅绑定 `127.0.0.1`，未对外发布）：

1. 示例安全卡片显示 2 个变量，点击后切到全量变量栏目，恰好显示 2 行。
2. 搜索 `header_state` 后显示 1 行，展开后可以看到实际读写、上下文和调用链。
3. 第二个 HTML 正确展示“本地静态排查已生成；模型复核未启用”，没有把零模型确认数显示为零风险。
4. F103 报告可以正常加载；所检查页面浏览器控制台错误与警告均为 0。

F103 的安全筛选还实测显示 `ring_tail` 与 `consumed_checksum` 两行：前者所有读写均来自同一 TIM3 IRQ，后者唯一访问位于 main；不是因为变量名、volatile 或“访问次数少”直接放行。从工具目录之外执行绝对入口路径加 `--profile serial-continue`，状态仍正确定位同一配置，并返回 `resumable: true`。

截图：[安全筛选及证据](../output/playwright/portability-safe-filter.png)、[F103 报告](../output/playwright/portability-serial.png)、[F103 两个安全筛除项](../output/playwright/portability-serial-safe.png)、[H747 报告](../output/playwright/portability-h747.png)。页面检查使用 Playwright，覆盖了仅检查 HTML 文本无法确认的点击、搜索与展开行为。H747 最终页面同样正常显示 34/34 解析覆盖，控制台错误与警告为 0。

## 5. 仍需明确的边界

- 返回 `2 / INCOMPLETE` 且产物完整不是崩溃：它表示仍有未完成复核或覆盖缺口。应读取具体证据，不能为了“通过”删掉缺口。
- 一条命令不代表几秒钟完成。包含大量 HAL/CMSIS 依赖和条件分支的工程会执行多次真实解析，可通过输出目录的 `run.log` 查看当前编译单元/补充分支；不应为了缩短时间删减实际编译参数或跳过关键依赖。
- 本轮没有调用真实付费模型，没有做目标板抢占/中断压力测试或 DMA Cache 一致性试验；模型协议由可控本地测试覆盖。
- Keil/IAR 专有参数、汇编入口、二进制库、复杂运行时回调表及双核共享协议仍需适配。当前没有“一条命令自动转换所有工程格式”的承诺。
- 配置的入口身份和业务目录归属必须真实。不同 IRQ 合并同一 ID、把自有 BSP 误排除，都会降低证据质量。
- “只有一处写”只有在已知单一不可重入上下文、无逃逸/覆盖缺口且无其它规则时才可筛除。严格筛除项与模型复核安全项分开计数，均受其证据范围限制。

新工程推荐按[接入教程](one-command-tutorial.md)完成一次配置，随后使用 `--profile` 日常扫描；发现新入口或不支持语法时先保留缺口并补真实最小反例，再扩展分析器。
