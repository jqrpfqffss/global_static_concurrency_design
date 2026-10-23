# 大型 STM32 扫描验证记录

> **新版执行入口**：冻结引擎 `1c389878f932dff3695e7badf987d0054242715a69ee5fc6f33894867c47632c`，Full Portable 副本 `H:/ecra_stm32_validation/portable-unmodeled-storage/ECRA-Portable`。实际 Portable Python 3.10.9 的新增 4 项回归通过。自动验收入口为 `H:/ecra_stm32_validation/run-unmodeled-storage-acceptance.py`；全量比较入口为 `compare-unmodeled-storage-acceptance.py`。当前正在进行 Portable 验收，后续完整 771 TU 回放、原生 Prusa 和新版 INAV 三轮均尚不能标记 PASS。

> **最新进展（2026-10-23T19:34，尚未完成验收）**：在 Prusa 完整 771 TU 真实 IR 的实时栈中确认，`storage_base()` 为 `None` 的 C++ 模板引用位置反复产生 `/$overlap/$overlap/...`。现场位置为 `local:src/common/hwio_buddy_2209_02.cpp:c:adc.hpp@660`；`patched-global-locals.json` 与连续运行时规模采样保存在 `H:/ecra_stm32_validation/prusa-dependency-replay-40g/`。这是已实测的非收敛触发机制，前述位图与依赖名称共享只降低放大成本，不能单独消除此根因。3948 开发版已经主动停止，12 个自有进程全部退出；停止凭据为 `dependency-names-nonconvergence-operator-stop.json`，不得统计为自然 OOM 或扫描成功。
>
> 当前代码增加了无布局存储投影的有限保守表示：重叠位置吸收后续投影，保留原始地址、全部已存已知目标、回调目标及显式 `unknown:storage-layout`；读取订阅根和后代写入，工作表与全方程重扫得到相同不动点。没有添加深度上限、删除访问或限制 TU。新增测试先在旧版实际失败，修复后专项 **69 passed /8 subtests**；完整套件 **858 passed /2 skipped /608 subtests，549.55 s**，见 `tests-unmodeled-storage-before.log`、`tests-unmodeled-storage-targeted.log`、`tests-unmodeled-storage-all.log`。三个旧精度测试补齐显式存储布局，原字段/数组目标断言保持不变。
>
> 新版 Full Portable、完整 771 TU 回放、原生扫描与新版连续三轮验收仍待完成。历史 fbc INAV 三轮及保存报告检查保持有效，但不能作为本次新版本的验收结果。历史 fbc 保存命令最终成功的证据为 `inav-archive-saved-isolated3/acceptance.json`，保存后完整审计为 `inav-archive-guard-acceptance/run3/artifact-audit-after-saved.json`（14 项检查通过）。


> **当前冻结版本与实际进度（2026-10-23 09:17）**：`3948abe93f1a6de0d023d3cbb3e2a1ba7fbc0780edae2414dc4231773ebf798a` /52 模块，Full Portable 为 `portable-dependency-names/ECRA-Portable`。完整回归 **845 passed /2 skipped /592 subtests，602.72 s，实际退出 0**；实际 Python 3.10.9 Full Portable **22 项命令/构建检查 PASS，退出 0**；同批真实 12 TU 的完整 23 表与 fbc 相同。`dependency-names-candidate-receipt.json` 绑定全部模块与配置哈希。

> 新 Prusa 原生证据：`prusa-dependency-names-full`，完整 771 TU、相同固件 commit/构建、无 Job 上限、无 tracemalloc/cProfile，已启动输入快照。新受控证据计划：`prusa-dependency-replay-40g`，完整 771 IR、40 GiB Job、两个指针阶段必须实际完成才释放原生重型分析；等待前一大报告重试退出。后续新版 INAV 三连及产物审计尚未开始，不能继承旧 fbc 的三连。当前整个任务仍未完成。

> fbc 受控分配剖析 `prusa-allocation-replay-28g` 在保存 100k/200k/300k/402,116 目标的四个完整 tracemalloc 快照后，因已确认重复路径来源而主动停止，实际终止退出 1，`operator-stop.json` 明确标为主动停止、未完成指针阶段、非自然 OOM、非成功验收。此前 fbc **原生** Prusa 的 MemoryError/退出 3/54,084,014,080 B 峰值证据原样保留；两者不能混淆。

| 当前项目 | 原生状态 | 解析与覆盖结论 |
|---|---|---|
| 新 3948 Prusa 771 TU | 输入快照运行中 | 尚无完整扫描结论 |
| 新 3948 INAV 374 TU | 尚未开始 | 新版 0/3，待 Prusa 与完整指针回放结果 |
| 历史 fbc INAV 374 TU | 三轮完整通过，两个相邻 39 表比较通过 | 各 374 PARSED /0 PARTIAL /0 FAILED，不计入新 3948 三连 |
| 历史 fbc Prusa 771 TU | 全部提取后全局指针求解自然 OOM | 502 PARSED /269 PARTIAL /0 FAILED，不能认作全流程成功 |

> **最新更正（2026-10-23 09:00）**：4edb 开发候选的原生扫描因取得新的实测根因证据而被明确停止，未完成验收，也不是自然 OOM；`bitmap-sharing-operator-reschedule.json` 记录经 PID/创建时间/命令校验后终止的本任务进程，旧 fbc 剖析和 INAV 报告进程保持运行。新工作区候选为 **3948abe93f1a6de0d023d3cbb3e2a1ba7fbc0780edae2414dc4231773ebf798a /52 模块**，相对 fbc 增加位图块共享和依赖图节点名称共享两项修复，完整测试正在执行，暂无新版原生成功结果。

> 确认证据：fbc 完整 771 IR 的 402,116 目标快照中，tracemalloc 指向 `points_to.py:484` 的 `ancestor.rpartition('/')[0]`，**3,369,415 个活字符串 /2,421,127,414 B**；完整依赖图只有 **262,904 个顶点**。变量内容没有变化，重复的是被各加载依赖集合保留的相同不可变路径。新 `_DependencyIndex` 让现有图顶点持有唯一名称，所有依赖边/读者/缓存值均保留，没有新增独立无限缓存。对应分配回归修复前同一个长祖先有 800 个实例而失败，修复后相关 41 项及 4 subtests 通过。这个测量确认了一项真实内存放大来源；尚不能把它写成全部 54 GB 的唯一来源或已完成 771 验收。

> **截至 2026-10-23 08:43 的最新执行状态**：工作区和新冻结 Full Portable 包 `portable-bitmap-sharing/ECRA-Portable` 均为 **4edba35ca4a4c6cfad829c71db6d8100c8b9f1123c26f41ef63cedc09cf0d453 /52 模块**。完整回归 **843 passed /2 skipped /592 subtests，691.06 s**，实际包内 Python 3.10.9 Full Portable **22 项检查 PASS**，保存命令前后静态 facts 哈希不变。新版真实 Prusa 全量扫描已开始输入快照，771 TU 编译数据库原样保留；重型阶段等待旧分配剖析、大报告重试退出及新版完整指针受控回放完成。新版尚无原生成功或连续三次验收结果。旧 fbc 的 INAV 三连继续归属旧版；旧 fbc Prusa 自然 OOM 不因新候选测试而消失。

> 新版执行器 `run-bitmap-sharing-acceptance.py`、收据 `bitmap-sharing-candidate-receipt.json`、状态 `bitmap-sharing-suite-execution.json`。新版受控实验为 `prusa-sharing-replay-40g`（40 GiB Job，完整真实 IR，没有新 Clang 提取，不计原生验收）；只有两个指针求解阶段真实完成才释放新原生扫描的重型阶段。随后按真实原生结果决定后续 INAV 三连和审计。所有门控均保留明确的资源调度身份，不冒充固件扫描验收。

> 当前状态：**执行中，未完成最终验收**。本文以执行证据为准。历史版本、受控回放、故障注入和当前原生扫描分别归账，不能拼接为连续成功。



> **工作区新候选（未验收）**：`4edba35ca4a4c6cfad829c71db6d8100c8b9f1123c26f41ef63cedc09cf0d453`，仍为 52 模块。相对旧冻结 fbc 仅改 BlockBitmap 并集的不可变块共享/完整已有结果复用，新增分配回归。修复前 2 项分配测试失败，修复后相关 41 项、4 subtests 通过；其中 240 次单块变化的历史位图，块对象由 38,560 降为 400 上限，全部数学位图逐次对照整数并集。该结果属于明确标注的合成分配测试；真实 771 效果及新的同版三连尚未验证。fbc Portable 包保持原样，用于正在运行的原版分配剖析及大型保存命令；不能把 fbc 的三连自动继承给新候选。

## 2026-10-23 08:25 状态更正：Prusa 当前候选仍自然 OOM

当前 fbc 候选不是最终完成版本。`prusa-archive-guard-full` 原生不设限扫描的 771 个 TU 全部提取，502 PARSED /269 PARTIAL /0 FAILED，随后主进程在 `Solver.compute_load()` 的祖先路径处理处自然 MemoryError，实际进程退出 3，总耗时 23224.438 s（包含显式资源等待）。完整堆栈及阶段内存位于 `Prusa-Firmware-Buddy/.ecra-archive-final/diagnostics/exception.log`；主进程 OS 提交峰值 54,084,014,080 B，异常时 Private Bytes 54,075,613,184 B、工作集 48,894,894,080 B，系统提交 102,997,327,872 /103,007,559,680 B。已经确认异常在全部 Worker 结束后的全局指针求解，不是最后一个 Clang Worker。当前 771 原始关系与历史完整提取严格相同，但没有完成指针分析、分类和报告，不能算全流程成功。

同一 fbc INAV 三轮原生扫描和两组 39 表比较通过的证据继续有效。后续大型保存命令测试控制器异常结束，原收据无 finished/子进程退出码，留有 PID 32284 的锁；不能推定该次命令成功或将原因直接归为 OOM。确认该 PID 已不存在后，已记录 `inav-archive-saved-lock-recovery.json` 并移除本任务生成的过期锁，按实际 Portable 3.10.9 重跑至 `inav-archive-saved-isolated3`。首次两次人工重试因过期锁直接拒绝，单独留存，不计成功。

正在进行 `prusa-allocation-replay-28g`：完整不可变 771 TU 合并 IR、实际包内 Python、Windows Job 28 GiB 上限、Solver 阶段 tracemalloc 与容器测量。该实验明确是受控资源剖析，不属于原生成功验收；尚未取得新修复结论。

## 当前冻结版本与验收口径

最近完成三连验收的冻结包 **`portable-archive-guard/ECRA-Portable`** 为 **`fbc2518dc88ce67744872e3a55d7f7d49ee42c2b5b392ebfc51cb5c31f881adc`、52 模块**，逐模块清单 `portable-archive-guard/engine-files.json`，收据 `archive-guard-engine-receipt.json`。完整回归 **841 passed /2 skipped /592 subtests，593.15 s，退出 0**；包内 Python 3.10.9 Full Portable 及扩展 22 项命令/构建检查 PASS。**INAV 同一引擎/配置/目标的三次原生完整扫描及两组轮间 39/39 表严格比较全部 PASS**，正式 `inav-archive-guard-acceptance/acceptance.json` 标记 complete=true。每轮 374/374 PARSED、各 13 项外部检查通过，完成字段/指纹/分类一致；首轮及第三轮原生产物完整静态审计 PASS。Prusa 当前候选已自然 OOM（详见首节状态更正），实际大型保存命令重试及最终审计仍待完成，整个任务未验收完成。

前一版 b148 **两轮原生全流程均已通过**，完整性字段、指纹、事实数量和分类逐项相同；首轮完整 39 表与历史结果相同。独立归档审计发现漏拷分类质量页，已确证并修复，因此不把 b148 成功计入当前版本三连。旧第三轮及旧排队 Prusa 被明确停止；两类停止均为操作安排，不是自然故障。

前一版 `32f0777f…` 的 828 passed /2 skipped /586 subtests（748.77 s）和 Portable PASS 仅为历史结果；其 INAV 已完成 374 TU 提取后因新快照缺陷确认而主动结束，不能混计新版连续验收。旧 `8df72adf…` 的完整 Prusa 原生扫描在 771 TU 提取后自然 OOM，见本报告新增记录。

- 历史 51 模块 Prusa 配置：`semantics-prusa-blocks-final.yaml`，SHA-256 `d4d0d826f16db3892559ba8a962962a73ec2cac42bee7f825f4b1930305394a7`。
- 历史 51 模块 INAV 配置：`semantics-inav-blocks-final.yaml`，SHA-256 `109fe76991b639a7d2d2ef22839c62726a176e56744a15ee6f1af3f056a4b038`。
- 旧版原生证据：`prusa-blocks-full` 已自然 OOM；`inav-blocks-acceptance/run1` 完整提取及原始关系比较通过后，因已确认诊断缺陷而被显式门控中止，退出 3，不算全流程成功；`operator-reschedule.json` 说明原因。
- 当前配置仅改独立输出目录：Prusa `semantics-prusa-archive-final.yaml` / SHA `03209096d627f0f892f2a90ab14a52e855d5a369a746a7d5a9efebd7fac45f49`，INAV `semantics-inav-archive-final.yaml` / SHA `393c4f6feba3218d6a70ac7cd81967022c861a125b6f67bee5f5409c51e91ae8`。原生证据 `prusa-archive-guard-full` / `inav-archive-guard-acceptance`，控制器 `run-archive-guard-acceptance.py` 在完整测试和 Portable PASS 后启动。历史阶段记录（2026-10-23 02:34，已被当前三连及 Prusa 失败结果更新）：INAV 374/374 PARSED，正在写完整产物；Prusa 771/771 已提取，502 PARSED /269 PARTIAL /0 FAILED；完整扫描完成数 **0/3**。
- 原生扫描不设 Windows Job 内存上限，不开 tracemalloc/cProfile；保存操作系统进程内存采样、阶段、退出码、快照与产物验证。INAV 重型阶段等待旧实验进程退出；新版 Prusa 可并行提取，但重型阶段等待三轮 INAV 完成。资源等待单列，两者均完整提取全部 TU。
- 连续三轮要求同一引擎、配置、目标，独立完整 Clang 提取与分析，并严格比较持久事实。report/status 刷新、缓存 IR 回放和历史版本都不计次数。

证据根目录统一为 **`H:/ecra_stm32_validation`**。原始 ECRA 为 `optimize_cc` / `ac96abc39ffc66de53e57df82ca0ee791907bce6`，保存在 `baseline`；用户原有 `.gitignore` 两行修改保留。未创建虚拟环境、未调用 Claude/OpenCode、未推送，未修改真实固件的受 Git 跟踪源码。

## 固定环境与真实构建

| 项目 | 实际配置、规模与边界 |
|---|---|
| 首选固件 | [Prusa-Firmware-Buddy](https://github.com/prusa3d/Prusa-Firmware-Buddy)，v4.4.1 / `570e86d56f6ca5ad36f5df984e52f2f20d542907` |
| Prusa 硬件 | MINI / BUDDY / STM32F407VG / Cortex-M4F / Release / BOOTLOADER=NO |
| Prusa 目标数据库 | 334 C +437 C++ +2 汇编；771 个 Clang TU；Ninja firmware 命令闭包 773/773 匹配，没有拼接板型 |
| Prusa 实际链接 | 413 直接 LOAD +198 被选取库成员；另 162 个构建闭包库成员未被选取，仍全部扫描；`prusa-link-selection.json` |
| Prusa 构建 | 本机及 Portable 均实际生成固件，打包前 BIN SHA `46b39eb8ea5e2685df0d2bbacc795e4bc5c85bb1430f0d4972b6172d3a5087c1`；公开 CMake 选项 `PRESET_COMPILE_OPTIONS=-D_DEFAULT_SOURCE`，未改固件源码 |
| 第二固件 | [INAV](https://github.com/iNavFlight/inav)，7.1.2 / `ed7fb3bb3216f8215150b42b52cb7b724e1dfae8` |
| INAV 硬件与数据库 | MATEKF405 / STM32F405RG / Cortex-M4F / Release；Ninja 原生 `compdb-targets MATEKF405` 的 379 条未删减记录含 374 C +2 汇编及生成/链接/转换命令；不用全 219 板型数据库 |
| INAV 实际链接 | 全部 376 对象直接 LOAD；真实 ELF 与相同 objcopy 生成 HEX 成功；FLASH 590416、RAM 101024、CCM 18312 B；`inav-link-selection.json` |
| INAV Windows 适配 | 仅生成的 settings.bat 因 Windows PATH 引号问题使用外部 `run_inav_settings.py` 运行官方 Ruby 生成器；原 bat 保留，CFLAGS 不变。聚合目标的后置 objcopy PATH 命令失败，不能把聚合命令记为 PASS；ELF 及显式相同 objcopy 单独实测成功 |
| 分析范围 | 两工程 include_dirs / exclude_dirs / exclude_files / exclude 均为空，build_closure_only=true；全部当前目标数据库保留，不把未编译的其他源码或二进制运行库算作已解析源码 |
| 源码库存 | Prusa 1894 C/C++、2409 头；INAV 1400 C/C++、1353 头。库存不等于当前目标 TU 数 |
| Windows / 资源 | Windows 10 Pro 10.0.19044 x64，12 逻辑处理器，物理内存 68,647,821,312 B；已有 16,384 MiB 页面文件，未改系统设置；`environment-host-os.json` |
| Python / Clang | 本机 Python 3.10.11；实际 Portable Python 3.10.9 x64；libclang 18.1.1、PyYAML 6.0.3 |
| 构建工具 | ARM GCC 10.3.1；本机 CMake 3.31.10，Portable CMake 3.29.6；Ninja 1.13.2；Portable MinGW 14.2.0、make 4.4.1 |
| 安装记录 | PyPI 构建依赖 polib 1.2.0、ecdsa 0.19.2、littlefs-python 0.19.0；监控 psutil 7.2.2、剖析 py-spy 0.4.2 仅测试使用。ECRA / Portable 无新增 Python 依赖 |
| Ruby | 官方 RubyInstaller 2.7.8-1 x64 7z，SHA `6958f62524da23d5956851a4e4488a5184c605e96aab3c8f9526cd2fae7cb8c1`；既有 7-Zip 26.01 解压至外部 tools，未改全局 PATH |

编译参数、宏、包含路径、依赖与链接证据见 `build_inventory.json`、各 configure/build 日志、两个 link-selection 清单。Prusa 数据库引用最初 Portable 工具链绝对路径，因此保留 `portable-final`，不静默换编译器；显式允许该外部工具链路径。

两份独立配置仅显式声明真实 `main` 为 MAIN，不靠名称把协作函数标成并发 TASK；IRQ/源码注册及指针入口恢复按原引擎启用。当前 Prusa 完整原始提取包含 3 条直接 TASK 注册：业务 `EspTask`、FreeRTOS `prvIdleTask` 和 `prvTimerTask`，来源为实际 `xTaskCreate` /`xTaskCreateStatic` 调用，见 `prusa-archive-guard-full/raw-direct-registration-inventory.json`。该记录不包括后续指针恢复入口；CMSIS 包装及其他动态入口的最终上下文/不确定性仍待全流程产物核实，不能宣称已完整识别全部 RTOS 任务。

## 验收表：当前版本与历史证据分开

| 验收项目 | 修复前 / 已确认历史失败 | 当前修复与实际执行结果 | 测试结果 | 证据位置 |
|---|---|---|---|---|
| 全量 Clang 提取 | 原版 INAV 374/374 PARTIAL；原版 Prusa 受控 12 GiB 中止于 234/771 | fbc INAV 三轮各 374 PARSED /0 PARTIAL /0 FAILED；Prusa 771 全提取，502 PARSED（65.110%）/269 PARTIAL（34.890%）/0 FAILED | **INAV 三轮 PASS**；Prusa 提取完成但整体 OOM，PARTIAL 不计完整解析 | inav-archive-guard-acceptance/acceptance.json；prusa-archive-guard-full/validation.json |
| 快照一致性 | 纯 touch 与无关头内容变化可确定性触发误拒绝；配置消费窗口、新遮蔽头与负向探测存在实测漏检 | 内容 SHA、实际依赖闭包、Clang 缓冲区及预处理签名、消费参数和发布后校验；正反故障注入通过 | **故障注入 PASS**；用户原现场自然源变化未确认 | snapshot-before/results.json、snapshot-final/results.json、tests-block-bitmap-all.log |
| MemoryError | 原版受控 HTML join OOM；中间版自然 HTML OOM；8df Prusa 原生指针求解 OOM | fbc INAV 三轮无 OOM；同版 Prusa 771 全提取后主进程全局指针求解再次自然 OOM，退出 3 | **未彻底解决**；不可将 INAV 成功扩写为任意规模成功 | prusa-archive-guard-full/metrics.json；Prusa-Firmware-Buddy/.ecra-archive-final/diagnostics/exception.log |
| 内存峰值 | 同批 374 TU merge 原版 3,525,136,384 B；中间版自然 HTML 46,808,616,960 B | 同批 merge 2,503,208,960 B；fbc INAV 三轮 OS 提交峰值 11,216,306,176 /11,217,571,840 /11,216,429,056 B；Prusa 自然 OOM 峰值 54,084,014,080 B | 有已测改善；**771 后续求解仍超资源**，不同剖析/排队条件不作严格速度比 | 两目标原生 metrics.json 与原始 memory.jsonl |
| 变量识别完整性 | 原版完整 INAV 12,315 变量 | fbc 三轮全 12,315；直接原版逐变量比较仅 parse_status 变化，新增/删除/分类变化均 0 | **INAV PASS**；Prusa 123,567 为归并后、分类前数量，尚无最终库存验收 | comparison-inav-baseline-archive-guard-variables.json；两组轮间全 SQL 比较；Prusa exception.json |
| 跨文件调用链 | 原版完整 374 TU 事实和 SQLite 已保存 | 原版→历史候选 36/39 表相同，3 表仅已解释解析元数据；候选→4e→fbc 及 fbc 两组相邻轮次均 39/39 相同 | **INAV 全量证据 PASS**；Prusa 后续求解未完成 | comparison-inav-gold-archive-guard-native.json；comparison-1-2.json；comparison-2-3.json |
| 并发风险分类 | 开发中曾丢 3 条 TYPE_VARIANT，造成一变量 UNKNOWN→SAFE，已修复并保留记录 | fbc 三轮全部 39 表相同，直接原版分类变化 0；9,944 适用变量中 SAFE 6,838 /SUSPECT 814 /UNKNOWN 2,292 | **INAV 与核心回归 PASS**；不能对未完成的 Prusa 作最终分类承诺 | comparison-inav-baseline-archive-guard-variables.json；three-native-summary.json；tests-quality-archive-all.log |
| 报告生成 | 原 HTML 整页 join OOM；b148 归档漏质量页实测 FAIL | fbc 首轮归档四文件 SHA 相同；首轮和第三轮全部附件/链接/变量/指针池静态审计 PASS | **原生 INAV 完整产物 PASS**；大型保存命令重试中，Prusa 未生成完整报告；GUI 人工 PASS 仅属历史目录 | run1/artifact-audit.json；run3/artifact-audit-native-before-saved.json；inav-archive-saved-isolated3 |
| 多次重复扫描 | 历史版本未取得最终同版三次成功 | fbc 同一配置三轮完整通过，指纹/事实数量/归账/分类相同；1→2、2→3 均全 39 表严格相同 | **完整三连与轮间全事实比较 PASS** | inav-archive-guard-acceptance/acceptance.json、three-native-summary.json、comparison-1-2.json、comparison-2-3.json |
| Portable 兼容性 | 原 Full Portable Python 3.10.9 | 当前 52 模块与工作区冻结版本相同；实际包内解释器、ARM 构建、22 项命令检查和 INAV 三轮原生全量通过 | **包运行时及 INAV PASS**；Prusa 在相同包内原生 OOM，不得记整体 PASS | portable-archive-guard-complete-commands/acceptance.json；inav-archive-guard-acceptance/acceptance.json |

ECRA 状态 `INCOMPLETE`/退出 2 可能表示有风险或盲区待复核，不能直接当作进程故障，也不等于安全证明通过。验收须同时检查 analysis_valid、快照 VERIFIED、产物完整性及 PARSED/PARTIAL/FAILED 三类比例。关闭 OpenCode 复核不会把待复核风险伪装为安全。

## 当前已实际通过的回归

| 范围 | 实际结果与边界 | 证据 |
|---|---|---|
| 当前引擎完整 tests/ | **841 passed、2 skipped、592 subtests，593.15 s**；跳过项为可选 OpenCode 联机测试 | tests-quality-archive-all.log |
| 完整字段键表与普通 dict 兼容 | 旧实现 5 个尺寸子用例失败；修复后 22 passed /331 subtests；字段名共享，值、嵌套关系及特殊键独立 | tests-record-dict-seeding-before.log、tests-record-seeding-targeted.log |
| 求解器缓存生命周期 | 无循环 GC 也立即释放；保留的外部缓存不持有 Solver；调试回调同样验证 | solver-cache-lifetime-before/after.json、tests/test_solver_lifetime.py |
| 分块位图 / 指针 / 存储 / workflow | 99 passed、16 subtests，71.38 s；整数运算/哈希/顺序、极高编号、小/稠密集合、完整 V2 JSON/SQLite 往返 | tests-block-bitmap-pointer-regression.log |
| 发布前补充回归 | 18 passed、8 subtests，10.30 s；已冻结后未更改分析引擎 | tests-block-bitmap-format-check.log |
| 大型产物池独立审计 | **4 passed、7 subtests，0.95 s**；篡改原子、池内容、引用数量、丢表、非法/重复块均拒绝；审计脚本逐条读取池，不构造完整池副本 | tests-large-report-pool-audit.log |
| 实际源码 / 头 / 数据库 / response 变化 | 正向变化拒绝；touch 与无关报告接受；消费参数变化、修改后还原、真实生成器、Windows 独占锁、缺失和不可读均保留失败证据 | test_scan_stability.py 及当前全套日志；snapshot-final/results.json |
| 恢复与发布窗口 | 新遮蔽头、负向 __has_include、saved report 导出时头/配置变化均拒绝；只允许依赖复验、不重新提取 facts；事实字节不变 | resume-input-closure-before.log、saved-publication-window-before.log、resume-final-targeted.log、当前全套日志 |
| OOM / 中断 / 旧产物 | 主进程与 Worker 分别保存完整异常；SQLite 原子写入；失败清除检查点并标记无效，不把上次安全报告标作本次有效 | test_scan_stability.py、当前全套日志 |
| review 开关与并行 | 实际两文件 MAIN/ISR/TASK Clang 夹具；复核提供者 mock，无 OpenCode 调用；静态事实和风险不变 | test_parallel_workers_and_review_toggle_preserve_static_evidence |
| 比较器自身守卫 | 表行顺序可变；重复行数、嵌套证据顺序、变量类型、访问模式变化必须失败；解析状态必须显式列出 | tests/test_scan_comparison.py、当前全套日志 |

最终 fbc 包另用实际 Python 3.10.9 完成确定性补验，`archive-guard-final-controlled-validation.json`：MAIN 128 MiB 真实提交耗尽完整诊断 PASS；实际 Clang CLI 的 MAIN 192 MiB 耗尽正确退出 3，旧报告无效、检查点/锁移除；真正 Worker 在完成 Clang 提取后实际耗尽 192 MiB、明确 WORKER/MemoryError/FAILED，并使父进程退出 3、结果无效。没有启用实验额外储备。八项快照用例完整符合预期（稳定/touch/无关头/报告正常 2；源码/使用头/数据库/删使用头拒绝 3）；读取不同汇编内容后恢复磁盘也退出 3。分别见 `diagnostic-archive-guard-main`、`diagnostic-archive-guard-cli`、`diagnostic-archive-guard-real-worker`、`snapshot-archive-guard-final`、`snapshot-parent-archive-guard-final`。全部标明 controlled/full_scan_acceptance=false，不计为自然复现或三轮完整扫描。

Portable 验收脚本 `scripts/validate_portable.py::Acceptance.builds` 补入 `review-failed` 实际命令和 review/review-failed/report 前后完整静态 facts SHA 不变检查；没有修改冻结的 52 个引擎模块。针对性 `tests/test_portable_build.py` **24 passed /3.80 s**（属于完整套件的子集，不另加总）。新验收脚本在实际包内 Python 3.10.9 下重新完成 **22 项命令/构建检查 PASS**，`portable-archive-guard-complete-commands/acceptance.json`，`saved_commands_static_facts_unchanged=true`。其包完整文件清单仍原样通过；脚本来自当前工作区，冻结包本身未改动，后续既有打包流程会复制更新的验收脚本。

## 当前 fbc 原生扫描验收明细

第一轮使用实际 Portable Python 3.10.9，未设 Job 内存上限、未开 tracemalloc/cProfile；全部 374 TU 重新提取和完整分析。`inav-archive-guard-acceptance/run1/validation.json` 的 13 项检查全部 true：产物、进程完成/退出状态、结果和完成状态、指纹、变量归账、全部 TU、覆盖归账、无 FAILED、快照、SQLite 完整性、HTML。`INCOMPLETE` /退出 2 表示保留待复核风险，不等于安全结论全部通过。

| 指标 | 第 1 轮实测 | 第 2 轮实测 | 第 3 轮 |
|---|---:|---:|---|
| 完整扫描验收 | PASS | PASS | PASS |
| 总墙钟秒 | 6629.594 | 5369.453 | 5175.937 |
| 显式资源等待秒 | 1206.250 | 0 | 0 |
| 扣除等待的墙钟秒（非 CPU 时间） | 5423.344 | 5369.453 | 5175.937 |
| 最大已采样 Private Bytes | 11,216,302,080 B | 11,217,563,648 B | 11,216,404,480 B |
| OS 进程私有提交峰值 | 11,216,306,176 B | 11,217,571,840 B | 11,216,429,056 B |
| OS 工作集峰值 | 10,271,768,576 B | 10,270,797,824 B | 10,272,399,360 B |
| PARSED /PARTIAL /FAILED | 374 /0 /0 | 374 /0 /0 | 374 /0 /0 |
| 变量 /函数 /访问 /调用 | 12,315 /69,680 /825,691 /17,804 | 相同 | 相同 |
| 独立分类 SAFE /SUSPECT /UNKNOWN | 6,838 /814 /2,292 | 相同 | 相同 |
| 漏项 /重复变量 ID | 0 /0 | 0 /0 | 0 /0 |
| 发布后快照 | VERIFIED | VERIFIED | VERIFIED |
| facts JSON /SQLite | 8,040,593,223 /11,961,520,128 B | 8,040,593,223 /11,961,450,496 B | 8,040,593,223 /11,961,528,320 B |
| 首页 /报告 JSON | 253,119,244 /3,729,039,818 B | 253,119,222 /3,729,039,818 B | 253,119,209 /3,729,039,818 B |
| 完整证据附件 | 12,501 文件 /3,754,603,312 B，完整审计 PASS | 基本生成验收 PASS，独立全量审计未另执行 | 完整原生产物静态审计 PASS，571.078 s |

首轮指纹 `6faa017728cdf1192cc333eb2255f82830ace81793c7a53f9f5553befe64aae3`；`first-native-summary.json`、`metrics.json/md` 保存上述实测。全部 374 TU 原始关系已与原版相同；当前完整 39 表及逐变量最终证据比较等待首轮数据库复制完毕后执行。附件 manifest 已标记 complete，但完整附件 SHA/链接/指针池审计和真实大型 saved report/status 仍以各自最终实际结果为准。首轮原始质量页、首页、复核页及附件清单 SHA 另存 `native-prearchive-pages.json`，用于第二轮实际归档后的字节核对。

第二轮实际归档已完成，`native-archive-copy-validation.json` **PASS**：`snapshots/20261023-025428-050378` 的四份文件与首轮原件完整 SHA/字节数全部相同，未重新生成页面或重算分类。质量页为 1,548,652 B /SHA `511765f9cfe1200d48a8863318460e8be8671f0c0becd8d5cafd52609ff6748d`。该项直接验证大型真实归档修复，但仅覆盖所列四份文件，不冒充全部 12,501 sidecar 的完整重审或三轮验收。

首轮最终语义比较现已实际 **PASS**：`comparison-inav-gold-archive-guard-native.json` 的 **39/39 表严格相同**，涵盖全部变量、访问、跨文件绑定、已求解指针目标、NVIC 和构建元数据，仅排除复核收据；规范化顶层表行与字典键顺序，保留重复数、类型及嵌套列表顺序。`comparison-inav-baseline-archive-guard-variables.json` 直接对原版的 12,315 个变量比较，新增/删除/静态分类变化全部 0；唯一差异是已解释的全部变量 `parse_status`。归纳收据 `run1/semantic-comparison-summary.json`。这证明当前首轮完整分析关系未退化，不代替三轮或 Prusa 全流程。

当前 Prusa 全部 **771 TU 原始事实关系及解析状态比较 PASS**：`comparison-prusa-4e-archive-guard-raw.json`，无缺失/新增单元，未设置任何字段规范化例外；与 4e 历史完整提取逐单元比较全部原始关系。归纳收据 `prusa-archive-guard-full/raw-semantic-comparison-summary.json`。此处对照为历史完整提取，不冒充原版完整全局求解/分类对照，后者此前没有完成；最终指针、上下文、分类与报告仍待当前原生 Prusa 后续阶段。fbc 首轮 INAV 原生归档的独立完整产物审计已启动，输出为 `run1/artifact-audit.json`，结果以实际完成收据为准。

fbc 首轮真实归档的独立完整产物审计现已实际 **PASS**（1074.797 s）：`run1/artifact-audit.json` 的 13 项检查全部 true。12,501 个 sidecar /3,754,603,312 B 全部 SHA 一致；1,508 个 HTML 的文档和本地资源无遗漏；12,315 变量全部存在、无额外变量；6 个 JS 语法检查通过；完整 JSON/SQLite 行数、SQLite 完整性及全部指针池原子/集合/引用检查通过。此项为静态文件/数据审计，没有声称执行新的浏览器人工渲染验证；第三轮的最终产物仍将独立审计。

第二轮同一 fbc 引擎/配置也已完整通过 13 项验收，`run2/validation.json` /`metrics.json/md`。`two-native-summary.json` 与主重复控制器的 `completion_comparisons` 均确认完成字段、指纹、全部事实计数、变量归账、分类和快照状态相同。总 5369.453 s 包含历史归档 596.515 s；提取 1061.000 s、归并 132.125 s、分类 938.079 s、报告生成存储 2183.125 s、发布后复验 71.437 s。第一轮资源等待和不同并行 I/O 条件单列，不作受控加速比。两轮 SQLite 文件字节数不同不直接判语义变化，仍须全部 39 表严格比较；该比较在执行，第三轮尚未开始。

随后轮间完整证据比较实际 **PASS**：`inav-archive-guard-acceptance/comparison-1-2.json` 的 39/39 表严格相同，所有完整行、重复数和嵌套顺序保留。主控制器在该比较通过后才启动第三轮；`two-native-summary.json` 已登记比较结果。这与只核对指纹/数量不同，当前没有观察到两轮实质证据差异。

第三轮也已实际完成：5175.937 s、各 13 项检查全部通过，374 PARSED /0 PARTIAL /0 FAILED，发布后 VERIFIED，变量/函数/访问/调用/指针目标/上下文/分类及指纹均与前两轮相同。`comparison-2-3.json` 随后完成全部 39 表严格比较 PASS，正式 `inav-archive-guard-acceptance/acceptance.json` **complete=true**；`three-native-summary.json` 同步记录三轮及两组完整比较。第三轮未经 saved report 刷新的原生产物独立全量审计 **PASS**，571.078 s，`run3/artifact-audit-native-before-saved.json`：13 项检查全部 true，12,501 sidecar /3,754,603,312 B 全部哈希一致，1,508 HTML 本地资源/链接无遗漏，12,315 变量无缺失/额外，6 个 JS 语法通过，完整 JSON/SQLite/指针池及数据库完整性通过。

2026-10-23 06:13 核对冻结引擎全部 52 模块仍与包一致；资源释放收据只表示调度许可（`full_scan_acceptance=false`），没有把它当作 Prusa 扫描成功。Prusa 已获准进入完整 771 TU 的实际归并，后续全局/上下文分析及报告仍待实际结果。三轮完整成功不包括任何受控回放或故障注入。

Prusa 随后实际完成归并并进入全局求解：`native-merge-pointer-transition.json`。归并阶段总 14300.203 s 中显式资源等待 12868.672 s；实际 merge 包装计时 1360.140 s，阶段还包括其他实际操作，不将两者混称 CPU 时间。归并端点 Private Bytes 为 **14,638,018,560 B**、当时 OS 提交峰值 14,924,042,240 B；旧 8df 自然失败版本同名阶段端点为 **21,200,703,488 B**，端点降低 30.96%，`comparison-prusa-native-merge-endpoints.json`。这是同固定项目/目标的不同版本、不同并行负载端点，不是纯单因素速度基准；当前完整 raw 已对 4e 严格比较，但此处不冒充另外新跑了旧 8df 对当前的全部 raw 直接比较，也不将归并结束当作全局求解/全扫描成功。

当前 Prusa 原生全局求解另做一次外部 py-spy 0.4.2 采样，15 s /100 Hz，**1,522 样本、0 错误**，实际目标 PID/创建时间/命令经核对，`native-global-solver-profile-receipt.json`、`native-global-solver-profile.speedscope.json` 和 `native-global-solver-profile-summary.json`。调用栈明确位于主进程 `Solver.solve→update/value→load_location/BlockBitmap.__or__`，不是最后一个 Clang Worker。该采样只支持此 15 秒 CPU 热点定位，不是 tracemalloc/原生堆分配统计，也不等同整个求解阶段的比例；原生仍无进程内存上限，保留实际 OS 峰值与系统提交测量。

## 已完成资源对照：不得替代原生全流程

| 实验 | 修复前 | 修复后 | 结论与边界 |
|---|---|---|---|
| 相同 374 TU 事实 merge，12 GiB Job，未碰上限 | 峰值 3,525,136,384 B；merge 29.765 s；总 191.437 s | 峰值 2,503,208,960 B；merge 111.250 s；总 238.328 s | 全 19 类事实相同；省约 29% 内存，归并更慢；非端到端速度比较 |
| 早期真实 12 TU JSON 装载 | 无上限旧峰值 1,501,921,280 B；同 1 GiB 限制失败 | 同 1 GiB 限制峰值 833,384,448 B | 19 类事实相同；与下面的 12 TU 批次不同，不能串联百分比 |
| 后续同批真实 12 TU merge，1 GiB Job，未碰上限 | 峰值 411,803,648 B；merge 20.484 s；总 31.312 s | 共享 dict 键表峰值 368,443,392 B；merge 16.703 s；总 27.578 s | 19 类事实相同，峰值降低 10.53%；comparison-record-dicts-12.json |
| 同批真实 12 TU 完整全局指针求解 | 全局整数位图峰值 433,975,296 B；solver 1.593 s | 分块位图峰值 420,679,680 B；solver 2.797 s | 23 类事实严格相同，**小规模 CPU 有开销**；此批未启用池压缩，V2 由 120,000 目标协议测试另证 |
| 同批真实 12 TU 完整求解，字段键表预建 | 提交峰值 420,896,768 B | 提交峰值 323,600,384 B，下降 **23.12%** | 23 类事实严格相同；comparison-pointer-record-seeding-12.json；有其他原生提取运行，不作严格速度比 |
| 8.04 GB 真实已保存事实读取，12 GiB Job | 整文件读取失败；仅共享字符串的流式中间版仍失败 | 完整 AccessRow 规范化成功，峰值 9,584,472,064 B；加载 605.641 s，含全量重编码 1085.188 s | 全 8,040,593,223 B 往返 SHA 一致；saved-facts-canonical-12g/result.json；不是新 Clang 扫描 |
| 完整 771 TU 布局索引构造，24 GiB Job | 4,574,932 个位置重复建立 full dict/set，Solver 构造 OOM | 共享 724 种精确布局后构造成功；随后全局求解触及预算 | 构造根因得到实证；不能把整个扫描判 PASS |
| 完整 771 TU 稀疏位图基数探针，24 GiB Job | 150,000 目标时 65,389 个独立位图占 912,945,708 B，约 94.9% 用于宽而稀疏集合 | 分块精确表示已实施；后续回放仍有预算失败，32f 附加回放被主动停止 | 探针主动停止不是解完成；pointer-cardinality-probe.json 保留完整统计 |

完整 771 TU 缓存为 `prusa-merged-ir-cache.json`，9,689,781,291 B；元数据记录源 771 文件 SHA、19 表数量及完整缓存 SHA。`prusa-block-bitmap-replay-24g` 使用该缓存、捕获的依赖与包内解释器，在明确 24 GiB Job 下执行；没有新 Clang 发现，故与原生扫描分开。**实际失败**：2034.734 s，进程提交峰值 25,769,803,776 B（24 GiB），主异常为 `points_to.compute_load():457` 的 `rpartition` 分配，随后测试分配现场及核心异常日志写入也 MemoryError；控制台完整保留三个异常链，外层退出 1，未发布安全报告。此结果证明预算内仍不能完成，不能宣称分块后全局求解已通过。进一步的周期基数回放为 `prusa-blocks-diagnostic-replay-24g`，仍属受控实验。

### 实际内存耗尽后的诊断修复

128 KiB bytearray 储备不能保证 Python 小对象池及 Windows 私有提交都能重新分配。仅 `raise MemoryError()` 或只堆积大 bytearray 的测试能够通过，覆盖不了上述真实失败。新增 `probe_diagnostic_memory.py` 使用 Windows Job、真实 Python 3.10.9，先耗尽大块，再耗尽不同 Python 小对象尺寸；全过程明确不是扫描验收。

最终相同探针的旧调用路径失败，见 `diagnostic-hard-limit-old-caller-verified`；候选原生处理成功，见 `diagnostic-hard-limit-candidate-verified`。候选在 128 /192 /256 MiB 上限下分别保存 MAIN /WORKER 完整诊断，见 `diagnostic-candidate-main-128m`、`diagnostic-candidate-worker-192m`、`diagnostic-candidate-main-256m`。实验性额外储备已关闭，使用候选引擎自身储备，结果中 `experimental_private_and_python_reserves=false`。早期探针迭代日志全部保留，不能把不同探针版本混作严格前后对照。

修复为 Python 各尺寸对象池及 `VirtualAlloc` 的 8 MiB 私有提交储备；调用者先释放 Python 储备再进入异常处理，处理器立即 `VirtualFree`，为 traceback/JSON/状态提供空间。普通匿名 mmap 的 Windows 共享提交不等于 Job 限制的私有提交，不能替代该机制。失败清理不再为 tracemalloc 复制全部分配快照，保留当前/峰值计量及省略原因。

该历史 Full Portable 的实际命令、ARM 构建与依赖/PE 检查 PASS：`portable-reserve-validation/acceptance.json`。原生 MAIN /WORKER 的真实提交耗尽成功诊断见 `diagnostic-full-portable-native-main` / `diagnostic-full-portable-native-worker`。真实 Clang 小工程先正常发布、再在实际额度耗尽下返回 3，撤销检查点、释放锁、旧报告不冒充本轮有效结果，见 `diagnostic-cli-after-utf8/result.json`。同一 CLI 夹具的旧版路径也可能成功处理，不能声称每一个旧版受控用例均失败；旧版完整 771 IR 和旧调用直接探针确有实测失败。永久测试 `test_emergency_memory.py` 的 4 tests /2 subtests 已通过（`tests-emergency-reserve-cli-verified.log`）。早期新增 CLI 测试因 Windows TEMP 的 8.3 路径未 resolve 而失败，修正的是测试入口，失败日志保留。最终大型全量仍须使用该修复后版本重验。

## 历史自然运行与语义证据

中间候选 INAV 完整分析后在整页 HTML join **自然 MemoryError**：13,531.282 s，退出 3，主进程提交峰值 46,808,616,960 B、工作集峰值 35,570,307,072 B；`inav-html-oom-metrics.json/md`。该轮开 cProfile 且有其他实验共享系统提交，不能与无剖析轮作严格速度比。原版 INAV 的完整失败另有明确后期 20 GiB 限制，属于受控异常，不能混称未修改原版的自然故障。

历史 `4e1aa03d…` 原生 INAV 一轮完整通过：`inav-final-consecutive/run1`，5,357.219 s，退出 2 / INCOMPLETE，374 PARSED、0 PARTIAL、0 FAILED，发布后 VERIFIED，变量 missing=0 / duplicate_ids=0，SQLite 完整。主进程提交峰值 12,162,478,080 B，工作集峰值 11,222,794,240 B。facts JSON 8,040,593,223 B，DB 11,961,544,704 B，首页 253,119,080 B，report JSON 3,729,038,904 B。指纹 `5be397496269675e26b57b202da5c1bad7ffc286212034aabd83a6f092728ef2`。后续恢复闭包等修复改变了版本，**该轮不计当前连续三轮**。

该历史轮有 12,315 库存变量、69,680 函数、825,691 访问、17,804 调用、51 上下文、5,623 绑定、9,241 指针目标。9,944 独立分类目标为 6,838 SAFE_PROVEN +814 SUSPECT +2,292 UNKNOWN；另 1,287 容器及 1,084 非独立分类项仍在完整库存。原版→候选 36/39 表严格相同，另 3 表只为显式解释的 parse_status / -flto jobs 解析元数据；候选→4e **39/39 表相同**，`comparison-inav-candidate-final-native.json`。12,315 变量逐字段比较只有 parse_status 不同，分类变化 0，三条 TYPE_VARIANT 完整保留。facts SHA 有行顺序差异，未冒充字节相同；所有比较保留重复记录和嵌套列表顺序。

更早 `inav-closure-acceptance/run1` 的 7,009.687 s /28,344,254,464 B 首轮以及各次主动中止记录同样只作历史证据。`e3957f75…` Prusa 提取 385/771 后因完整 IR 的稀疏位图证据而主动停止；对应 INAV 虽提取 374/374，资源门随后拒绝归并。`operator-interruption.json` 与失败 gate 均保留，未计成功。每次版本冻结均要求重新开始，未通过拼接历史轮次满足三次要求。

历史真实 HTML 静态审计：12,315 变量全部存在；12,501 sidecar 共 3,754,602,398 B 全部 SHA 一致；1,508 HTML 的本地链接/资源通过，6 个 JS 语法检查通过，JSON/SQLite 行数全部对账，605.656 s；`inav-closure-acceptance/run1/artifact-audit.json`。**历史产物 GUI 人工验证 PASS**：用户明确回复“首页和完整证据均能正常打开”，对应 `inav/.ecra-closure/index.html`，收据 `manual-gui-closure-confirmation.json`。此前浏览器 file:// 请求被策略拒绝，未绕过。此人工结果仅适用于该历史产物，新最终目录仍需独立验证。

## 自动化与复用命令

```powershell
# 复用固定 Prusa 工程，在扫描前准备/构建，不与扫描竞态运行
py -3.10 scripts/prepare_large_stm32.py --workspace H:/ecra_stm32_validation --arm-toolchain D:/gcc-arm-none-eabi-10.3-2021.10

# 实际完整 Portable、真实 771 TU 数据库；evidence 必须使用新目录
py -3.10 scripts/large_stm32_scan.py --engine H:/ecra_stm32_validation/portable-archive-guard/ECRA-Portable --python H:/ecra_stm32_validation/portable-archive-guard/ECRA-Portable/runtime/python.exe --project H:/ecra_stm32_validation/Prusa-Firmware-Buddy --config H:/ecra_stm32_validation/semantics-prusa-archive-final.yaml --evidence H:/ecra_stm32_validation/new-prusa-native --no-profile --no-cprofile

# 三轮相同目标/版本/配置，保存每轮完整数据库及诊断后再覆盖项目输出
py -3.10 scripts/repeat_large_scan.py --engine H:/ecra_stm32_validation/portable-archive-guard/ECRA-Portable --python H:/ecra_stm32_validation/portable-archive-guard/ECRA-Portable/runtime/python.exe --project H:/ecra_stm32_validation/inav --config H:/ecra_stm32_validation/semantics-inav-archive-final.yaml --evidence H:/ecra_stm32_validation/new-inav-three --runs 3 --no-cprofile

# 故障注入只使用独立夹具；完整 ECRA 测试明确限定 tests/
py -3.10 scripts/reproduce_snapshot.py --engine H:/global_static_concurrency_design --evidence H:/ecra_stm32_validation/new-snapshot-fixture
py -3.10 -m pytest tests -q

# 完整证据比较与大型产物审计，内存有界
py -3.10 scripts/compare_extracted_facts.py BEFORE/workers AFTER/workers --output raw-comparison.json
py -3.10 scripts/compare_scan_facts.py BEFORE/facts.db AFTER/facts.db --output comparison.json
py -3.10 scripts/compare_variable_evidence.py BEFORE/facts.db AFTER/facts.db --output variable-differences.json
py -3.10 scripts/validate_large_report.py FIRMWARE/OUTPUT --output artifact-audit.json --javascript

# 实际 saved report/status 及前后输入/事实/版本检查，不计作全量扫描
py -3.10 scripts/validate_saved_commands.py --help

# 真实 IR 受控 merge / pointer 资源实验，不计原生验收
py -3.10 scripts/benchmark_fact_merge.py --help
py -3.10 scripts/benchmark_pointer_solver.py --help
py -3.10 scripts/replay_large_analysis.py --help

# 不装载大型事实文件的进度及实测指标
py -3.10 scripts/large_scan_status.py H:/ecra_stm32_validation/prusa-archive-guard-full H:/ecra_stm32_validation/inav-archive-guard-acceptance/run1
py -3.10 scripts/summarize_large_scan.py --evidence RUN_EVIDENCE --output-dir FIRMWARE/OUTPUT --json metrics.json --markdown metrics.md
```

默认测试监控开启 tracemalloc/cProfile；`--no-profile` 只关闭前者，`--no-cprofile` 关闭后者。进程 OS 采样单列 Private Bytes、工作集、各 PID 生命周期峰值及系统提交。tracemalloc 不替代 libclang 原生内存计量。主进程和每个 Worker 各有独立诊断，不从最后一条 Clang 进度推断异常归属。

`summarize_large_scan.py` 另列显式资源等待及扣除等待的墙钟时间，保留原始阶段秒数；扣除等待后仍含 I/O 和系统调度，不能称为 CPU 时间。相关指标回归 1 passed（`tests-large-metrics-resource-wait.log`），未改变冻结引擎。新原生产物与重复数据库目录在创建时启用 NTFS 透明压缩，所有逻辑文件和证据保留，操作收据 `reserve-native-inherited-compression.json`；因此也不能把不同存储条件下的耗时直接作加速比。

早期误用仓库根 pytest 导致收集本地 output/validation 第三方工程、61 个 collection errors 的失败日志保留，未计 PASS；后续使用仓库既有 tests/。各开发失败/中止日志保留，不把测试失败写成全绿。

历史大型产物已用 NTFS 透明压缩节省磁盘，完整文件与路径保留，事实 JSON/DB 压缩前后 SHA 相同。一次删除历史目录的操作被自动审批拒绝后没有重试删除，也没有删除任何原始证据；相应 archive/compression 收据保留。

另一次已完成的历史 Prusa Worker 证据透明压缩：9 个明确列出的旧目录，逻辑大小 89,025,893,539 B 保持不变，实际占用降至 25,108,046,560 B；目录清单、文件数/大小及各最大文件压缩前后 SHA 均保留，全部 compact 退出 0。收据 `retired-worker-compression.json` 明确 `source_removed=false`；没有操作当前输出目录或固件源码，没有将有限抽样哈希冒充全部文件逐字节复核。

## 当前未完成与限制

1. 当前 fbc 的 INAV 三次完整扫描及两组轮间全部事实比较均通过；Prusa 原生全流程、实际大型保存命令及刷新后的最终产物审计仍待完成，不能宣告整个任务完成。b148 两轮只作历史证据，不混计。
2. 完整 771 IR 的 32f 附加 24 GiB 回放已明确主动中止（退出 15），不计通过或自然 OOM；同位置内存实证保留，最终资源需求须由 fbc 新鲜原生全流程验证。
3. 当前 fbc 首轮原始关系、完整 39/39 表、原版逐变量比较、三次完整扫描、两组轮间全事实比较及首/第三轮原生附件审计均通过。剩余实际大型 saved report/status 及刷新后的最终产物审计仍须完成。
4. Prusa 既有 269 PARTIAL 为真实解析不完整，包含冲突声明、constexpr、构造调用及裸汇编等不同诊断；不能统称无害 GCC 扩展、改固件或弱化错误来抬高完整解析率。
5. 静态证据与不确定性必须保守保留；预编译运行库源码、其他板型、未编译文件及硬件实际行为不在已解析范围。历史 `.ecra-closure` GUI 已获用户人工确认；新最终报告尚未取得该确认。


## 主进程输入消费回归与原生资源故障补充（2026-10-22 晚间）

确定性故障注入实际改变并读取 `startup.S`，随后恢复原字节。前一版返回 2 接受了不同内容（`snapshot-assembly-consumption-before/result.json`，非自然故障）。当前版本在实际读取时核对 SHA，保留初始及消费哈希；ASM、补充/词法源码、实际使用的 ELF/map、最终 CMake 缓存及生成编译器元数据均接入验证。仅使用的 map 文件集合进入已签名输入闭包，未使用的 map 不误报；保存命令也重新检查该集合。针对性实际回归：84 passed /8 subtests（71.91 s）、20 passed /2 subtests（16.15 s），见 `tests-parent-inputs-complete-targeted.log` 和 `tests-parent-source-final-targeted.log`。新的全量回归仍以独立日志为准。

旧 8df 版本 Prusa：771/771 完整提取后，`points_to.Solver.load_location → load_dependencies[dependency].add(key)` 发生自然 `MemoryError`；主进程最后记录私有内存 51,806,322,688 B，系统提交接近 103,007,559,680 B 上限。该数值为最后可用样本，不伪称精确终止瞬时峰值。主 CLI `run.json` 记录失败码 3，但外部监控器也因 Windows 1455 退出，实际 OS 退出码没有被监控器保存；恢复收据明确为 null，验收失败，见 `prusa-blocks-full/execution.json`、`validation.json`、`analyze-exception.log`。32f 受控重放的外部监控器同时退出，子进程仍处等待阶段，后以 PID+创建时间及 Windows 进程句柄恢复监控，存在测量空档，不能视为完整监控的自然扫描。

自动化监控现区分 Windows 8/14/1455 资源错误与其他 OSError，释放预留后继续等待原子进程并明确记录缺失样本；不把监控异常当成扫描成功。2 tests /4 subtests 实测通过，见 `tests-large-monitor-resources.log`。第一次新 Portable 验收错误地从开发解释器启动，被验证器主动拒绝（保留 `portable-input-read-validation`）；改为实际包内解释器后的执行写入独立 `portable-input-read-runtime-validation`，不能把前次失败改成 PASS。


当前 b148 包实际 Python 3.10.9 的新增注入结果：`snapshot-parent-consumption-final/result.json` 明确读取不同汇编内容后恢复磁盘，退出 3、analysis_valid=false、旧检查点移除；稳定基线退出 2。`snapshot-input-read-final/results.json` 八条件全部符合预期：稳定/touch/无关头/报告正常完成，源码/使用头/数据库/使用头删除退出 3。真实 Job 耗尽的 MAIN /WORKER /实际 Clang CLI 诊断均 PASS，分别见 `diagnostic-input-read-main`、`diagnostic-input-read-worker`、`diagnostic-input-read-cli`；没有实验性额外储备，CLI 撤销上轮有效性并释放锁。

完整 771 TU、同一 IR 缓存的 32f 受控比较：在 100,002 /200,000 /300,000 目标三个已记录位置，集合数量、基数分布和位图对象统计逐项一致；Private Bytes 分别减少 29.92% /29.69% /29.48%。300,000 位置为 22,052,773,888 →15,552,245,760 B。证据 `comparison-record-seeding-full-samples.json`。这是对应位置的内存差，不能当作最终峰值降低比例或完整求解语义证明。

Prusa 受控求解另有 py-spy 0.4.2 外部 30 秒实采样，3049 次、0 错误；`prusa-seeded-replay-24g/solver-live-profile.speedscope.json` 和 `solver-live-profile-summary.json`。该窗口热点为精确分块位图 OR 和 load 依赖计算；这是时间采样，不是分配统计或整轮 CPU 时间，不作为完成求解证据。

32f 的附加 24 GiB 重放在保存匹配位置、400,816 目标增长样本及外部采样后，由操作明确中止，释放资源给新的原生全量验收，见 `prusa-seeded-replay-24g/operator-stop.json`。实际退出码 15，完整求解未完成，analysis_valid=false；不是自然 OOM，也不是受控求解通过。它仍保留全部 771 IR 与所有输出，未替代后续 b148 的 771 TU 新鲜原生扫描。外部恢复监控的测量空档及系统采样也明确保留。


补充真实 Worker 全链路：`scripts/probe_worker_memory.py` 在独立小工程先正常发布，第二轮实际运行 `ecra.extract.main`，完成真实 Clang 提取后在 `Extractor.run` 内执行分配直至 Windows 192 MiB Job 额度真正耗尽，未用 `raise MemoryError` 模拟。Full Portable Python 3.10.9 实测成功：Worker 完整异常为 WORKER/MemoryError、响应 FAILED，父 CLI 返回 3，旧有效性 false、检查点及锁清理，见 `diagnostic-input-read-real-worker-verified/result.json`。Worker 进程提交峰值 201,326,592 B，异常保存后工作集 43,876,352 B，显示提交和工作集不能混用。永久回归 `test_worker_commit.py` 1 passed（5.62 s），`tests-worker-commit-final.log`。较早 `diagnostic-input-read-worker` 仅直接验证同一诊断处理器的 WORKER 标签；此新增试验另验证真实入口及父进程传播。第一次新增探针因嵌入解释器隔离路径找不到测试辅助模块而失败，保留 `diagnostic-input-read-real-worker`，修正的是测试脚本路径，不是核心分析代码。

最终新增监控、指标及真实 Worker 全链路测试已全部并入完整套件重新执行：**840 passed /2 skipped /592 subtests，673.01 s，退出 0**，`tests-input-read-final-all.log`；核心仍为冻结 b148 的 52 模块。先前 836 项日志继续保留，不作为独立额外通过数累加。


b148 第一轮 INAV 的中间证据（不是整轮验收）：374/374 均 PARSED，提取 JSON 773,877,425 B、最大 51,346,710 B；`inav-input-read-acceptance/run1/extraction-accounting.json`。全部 374 TU 原始关系与原版相同，parse_status 的已解释变化单列，`comparison-inav-baseline-input-read-raw.json`。

完整 facts JSON 为 8,040,593,223 B，但原始字节 SHA 与 4e 历史结果不同：`comparison-inav-gold-input-read-facts-json.json`。首个差异在字节 4,382,903,077，同一源码位置的访问记录排列不同，`comparison-inav-gold-input-read-first-byte-diff.json`。随后对已经原子写完的 SQLite 进行完整初步比较：12,315 个变量完整记录及 825,691 个访问记录逐项相同，保留重复记录和嵌套列表顺序，仅规范化顶层表行及 JSON 字典键顺序，445.953 s；`comparison-inav-input-read-accesses-variables-preliminary.json`。变量包含完整分类、访问及证明字段，故该初步比较没有变量分类变化；当时其余全部事实表、最终报告有效性与三轮连续验收尚未完成；之后首轮全部产物验收通过，三轮及全部事实比较继续执行。


## 历史 b148 原生全量成功（不计 fbc 三连）

`inav-input-read-acceptance/run1/validation.json` 全部 14 项检查为 true：完整产物、CLI 状态及退出码、有效性、completion、fingerprint、变量归账、全部 TU、解析归账、无 FAILED、快照、SQLite integrity_check、HTML 基础结构。退出码 **2** 对应 `--no-review` 保留待复核，不是解析/分析失败。输入指纹 **6a9a71cc5751aace11a6b55e69817333e7792872bf948fb6468d8c5634d75b87**，`analysis_valid=true`，快照 VERIFIED。

| 首轮指标 | 实测 |
|---|---:|
| C/C++ TU | 374 PARSED /0 PARTIAL /0 FAILED |
| 变量 /函数 /访问 /调用 | 12,315 /69,680 /825,691 /17,804 |
| 上下文 /绑定 /求解目标行 | 51 /5,623 /9,241 |
| 参与分类 | 9,944；SAFE 6,838，SUSPECT 814，UNKNOWN 2,292 |
| 漏项 /重复 ID | 0 /0 |
| 总墙钟时间 | 5567.063 s |
| 显式资源等待 | 505.360 s |
| 扣除等待的墙钟时间（非 CPU 时间） | 5061.703 s |
| 主进程提交峰值 | 11,211,063,296 B（约 10.44 GiB） |
| 主进程工作集峰值 | 10,272,362,496 B |

详细阶段、各 Worker、系统提交及产物大小见 `run1/metrics.json` / `metrics.md`、`first-native-summary.json`。JSON、SQLite、HTML 完整发布；逐项 sidecar /JS 审计、新最终 GUI、实际大型 saved report/status、其余两轮以及 Prusa 未完成，不把基础 HTML 检查当作上述额外检查。与历史原版/中间版峰值对比须保留版本、剖析开关、并行负载和 NTFS 压缩差异，不能直接宣称严格加速比。


当前 INAV 首轮对 4e 历史完整结果的**全部 39/39 持久化事实表严格比较 PASS**，见 `comparison-inav-gold-input-read-native.json`。比较包括全部变量字段、访问、函数、调用、上下文绑定、已求解目标、NVIC 和构建元数据，保留重复及嵌套列表顺序；仅顶层表行和 JSON 字典键顺序规范化。此次是完整原生大型结果比较，不是 12 TU 回放或抽样。原始 JSON SHA 不同不能直接当作证据丢失，也不能跳过这些实测比较；当前全部持久化关系确认相同。第二轮与第三轮仍在执行；新的 b148 首轮归档 HTML 已向用户提出独立人工显示确认，结果尚未收到：`inav/.ecra-input-read-final/snapshots/20261022-235417-087587/index.html`。


当前 b148 的 Prusa 新鲜原生提取也已完成全部 771 TU：**502 PARSED（65.110%）/269 PARTIAL（34.890%）/0 FAILED**，事实 JSON **16,246,770,455 B**，最大 **69,550,693 B**；`prusa-input-read-full/extraction-accounting.json`。输入复验/全部原始关系比较继续执行，重型归并与分析受资源门控等待 INAV 三轮完成，尚未计作全流程 PASS。部分解析不能计作完全解析，也未排除任一数据库 TU。

当前对原始完整 INAV 的逐变量直接比较完成：`comparison-inav-baseline-input-read-variables.json` 共 12,315 个变量，新增/删除/静态分类变化均 0，变化字段仅 12,315 个 `parse_status`（已解释的 Clang 数字 LTO 参数适配）。当前对 4e 的完整 39 表全同结果与该直接比较互相支持，未观察到静态分类退化；INAV 连续三轮仍未完成。


## 真实归档审计发现的漏页及新冻结版本

b148 第一轮原生目录内的质量页存在；但下一轮 `cli.run` 的归档白名单没有 `QUALITY_PAGE`，随后 `write_failure` 把当前质量页替换为运行中占位页。归档报告因此缺失 `classification_quality.html`。首次独立审计 **FAIL**（882.796 s），`inav-input-read-acceptance/run1/artifact-audit.json` 保留原结果：12,501 sidecar /3,754,603,312 B 全部哈希一致、全部 12,315 变量存在、全部 JSON/SQLite 对账及指针池检查通过；失败仅为缺失质量页及两条对应链接，5 个已有 JS 检查正常。不能把该失败改写为原生分析失败或审计通过。

永久修复：`ecra.cli` 引入既有 `QUALITY_PAGE` 常量，并在写运行中页之前与首页/复核页一起复制。`tests/test_report_archive.py` 的实际两轮 Clang 测试先失败（`tests-quality-archive-before.log`），修复后 1 passed /4.42 s（`tests-quality-archive-after.log`），检查旧质量页逐字节保留。完整套件重跑 841 passed /2 skipped /592 subtests /593.15 s。没有修改风险分类、分析方程或扫描范围；因 CLI 摘要改变，使用新独立包和配置重新执行三次全量，旧记录不混计。

历史归档的漏页通过保存的真实质量 JSON（SHA `1111f6ef5d5216291e79aa867b7d17945a48f2e3f5f06a324061489451b47358`）和同一 b148 渲染器恢复。时间/工程/版本/指纹从原生首页 header/footer 及 run.json 提取；163 个重新生成的 sidecar 全部与原始完整 manifest 的 SHA/字节数相同，未重跑分析、未修改分类、未改原始 FAIL 审计。恢复质量页 1,548,633 B /SHA `606bdfbe904e12209194ef2c443512461d19db78cd5bf2a9f18a4f63071f63e9`，收据 `quality-page-restoration.json`；完整复审另写 `artifact-audit-after-quality-restoration.json`，尚以实际结果为准。此前人工核对请求仍指向同一归档首页，首页和证据内容未更改。

当前新配置：`semantics-inav-archive-final.yaml` /SHA `393c4f6feba3218d6a70ac7cd81967022c861a125b6f67bee5f5409c51e91ae8`，`semantics-prusa-archive-final.yaml` /SHA `03209096d627f0f892f2a90ab14a52e855d5a369a746a7d5a9efebd7fac45f49`，仅改独立输出目录 `.ecra-archive-final`；include/exclude 数组仍全空，真实完整数据库不变。控制器 `run-archive-guard-acceptance.py`，证据 `inav-archive-guard-acceptance` / `prusa-archive-guard-full`；新提取可并行，重型阶段严格串行等待。旧版操作安排见 `inav-input-read-acceptance/operator-reschedule.json`。

历史 b148 首轮遗漏质量页恢复后的**完整复审实际 PASS**：1923.969 s，`inav-input-read-acceptance/run1/artifact-audit-after-quality-restoration.json`；全部 12,501 sidecar /3,754,603,312 B、1508 HTML、6 个 JS 语法、全部变量、JSON/SQLite、指针池及本地链接检查通过。原始 FAIL 的 `artifact-audit.json` 仍保留。该复审属于历史归档修复，不计 fbc 新版本的三次原生成功；人工渲染确认仍未收到新答复。

旧 b148 第二轮也已真正完成并通过全部外部检查，随后操作明确停止旧第三轮及排队 Prusa（不混计自然故障）：`inav-input-read-acceptance/run2/validation.json`、`operator-reschedule.json`、`two-historical-native-summary.json`。两轮完整性字段、指纹、事实数量、分类和快照状态逐项相同；这是完成数 2 的历史版本，不计当前 fbc 新版本三连。旧排队 Prusa 771 TU 全部原始关系和解析状态与 4e 相同，停止发生在重型归并前。
当前归档永久回归另用实际包内 Python 3.10.9 执行通过，1 test /6.837 s，`tests-quality-archive-portable3109.log`。

### 不可变位图共享候选：已执行的有限证据

`4edba35ca4a4c6cfad829c71db6d8100c8b9f1123c26f41ef63cedc09cf0d453` 的真实 12 TU 受控完整求解与 fbc 对照：23 张完整事实表指纹全部相同，差异 0（`comparison-pointer-sharing-12.json`）。这不是 771 TU 验收，小批数据也没有显示可据以外推的大幅进程峰值改善。

包内实际 Python 3.10.9 的合成分配实验保留全部 241 个完整历史位图、每步对照独立整数并集，最终 82,320 个目标不变：旧实现 38,560 个不同块对象，新实现 400 个；tracemalloc 峰值 27,248,866 →955,134 B；OS 进程私有提交峰值 50,696,192 →10,313,728 B。证据 `bitmap-sharing-allocation-before.json`、`bitmap-sharing-allocation-after.json` 和可重复外部脚本 `measure-bitmap-persistence.py`。这是合成分配证据，不能写成真实 Prusa 降幅或原现场根因已彻底修复。包内解释器下新增两项分配测试实际通过；初次 `-m unittest tests...` 因嵌入解释器 `_pth` 不含工作区导致导入失败，保留日志，改为显式工作区导入和 run_path 后通过，没有更换解释器。完整测试已通过 843 项及 592 subtests；该候选实际 Full Portable 22 项检查 PASS，详见最新执行状态。

### 依赖图名称共享：真实分配来源与有限回归

- 新候选 `3948abe93f1a6de0d023d3cbb3e2a1ba7fbc0780edae2414dc4231773ebf798a` 与冻结 fbc 的同批真实 12 TU 完整求解，23 张事实表指纹全部相同，`comparison-pointer-dependency-12.json`。这不替代真实全量验收。
- 包内 Python 3.10.9 合成分配实测：800 个完整加载结果、808 个完整依赖节点以及所有依赖关系 SHA 均相同（`876c5ae2de4ec830272f2a32bf853b5cfe5ec0ebdd39bd3db571f4b3ee08aecb`）；同一长祖先由 800 实例变为 1 实例。tracemalloc 峰值 **12,825,825 →3,455,686 B**，OS 进程提交峰值 **24,801,280 →13,946,880 B**，证据 `dependency-allocation-before.json` /`dependency-allocation-after.json`、外部可重复脚本 `measure-dependency-persistence.py`。没有删除缓存结果、依赖边或读者。
- 新增两项回归在实际包内解释器下通过；Full Portable 22 项实际命令/构建检查 PASS，`portable-dependency-names-validation/acceptance.json`，静态 facts SHA 保持不变。完整回归仍执行中；没有宣布当前候选原生成功。
