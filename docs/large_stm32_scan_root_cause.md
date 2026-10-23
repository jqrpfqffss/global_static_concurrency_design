# 大型 STM32 扫描故障根因与修复记录

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

> 验收仍在执行。本文只把已有运行证据支持的结论标为确认；大型工程最终状态以配套验证报告为准。

> 版本说明：当前冻结为 52 模块 **fbc2518dc88ce67744872e3a55d7f7d49ee42c2b5b392ebfc51cb5c31f881adc**（portable-archive-guard）。841 passed /2 skipped /592 subtests，593.15 s，实际 Python 3.10.9 Full Portable PASS。同一引擎/配置/目标的三次原生扫描均已完整通过，每轮各 13 项检查通过；均为 374 PARSED、0 PARTIAL、0 FAILED，发布后 VERIFIED，完成字段/指纹/分类相同。1→2、2→3 两组完整 39/39 表严格比较均 PASS，正式三连 complete=true；首轮及第三轮原生完整产物审计 PASS。Prusa 当前候选已自然 OOM，实际大型保存命令等最终验收未完成，详见首节状态更正。首轮提交峰值 11,216,306,176 B、6629.594 s（含资源等待 1206.250 s）；第二轮提交峰值 11,217,571,840 B、5369.453 s（无资源等待）。此前 b148 两轮完整通过、完整性字段/指纹/分类相同，首轮 39 表语义一致，均保留为历史；因归档质量页漏拷的实证修复改变 CLI 摘要，不能混计当前版本。下文中分阶段取得的测试数字及回放结果均属于对应历史引擎；最终状态以本段及验证报告的当前验收表为准。



> **工作区新候选（未验收）**：`4edba35ca4a4c6cfad829c71db6d8100c8b9f1123c26f41ef63cedc09cf0d453`，仍为 52 模块。相对旧冻结 fbc 仅改 BlockBitmap 并集的不可变块共享/完整已有结果复用，新增分配回归。修复前 2 项分配测试失败，修复后相关 41 项、4 subtests 通过；其中 240 次单块变化的历史位图，块对象由 38,560 降为 400 上限，全部数学位图逐次对照整数并集。该结果属于明确标注的合成分配测试；真实 771 效果及新的同版三连尚未验证。fbc Portable 包保持原样，用于正在运行的原版分配剖析及大型保存命令；不能把 fbc 的三连自动继承给新候选。

## 2026-10-23 08:25 状态更正：Prusa 当前候选仍自然 OOM

当前 fbc 候选不是最终完成版本。`prusa-archive-guard-full` 原生不设限扫描的 771 个 TU 全部提取，502 PARSED /269 PARTIAL /0 FAILED，随后主进程在 `Solver.compute_load()` 的祖先路径处理处自然 MemoryError，实际进程退出 3，总耗时 23224.438 s（包含显式资源等待）。完整堆栈及阶段内存位于 `Prusa-Firmware-Buddy/.ecra-archive-final/diagnostics/exception.log`；主进程 OS 提交峰值 54,084,014,080 B，异常时 Private Bytes 54,075,613,184 B、工作集 48,894,894,080 B，系统提交 102,997,327,872 /103,007,559,680 B。已经确认异常在全部 Worker 结束后的全局指针求解，不是最后一个 Clang Worker。当前 771 原始关系与历史完整提取严格相同，但没有完成指针分析、分类和报告，不能算全流程成功。

同一 fbc INAV 三轮原生扫描和两组 39 表比较通过的证据继续有效。后续大型保存命令测试控制器异常结束，原收据无 finished/子进程退出码，留有 PID 32284 的锁；不能推定该次命令成功或将原因直接归为 OOM。确认该 PID 已不存在后，已记录 `inav-archive-saved-lock-recovery.json` 并移除本任务生成的过期锁，按实际 Portable 3.10.9 重跑至 `inav-archive-saved-isolated3`。首次两次人工重试因过期锁直接拒绝，单独留存，不计成功。

正在进行 `prusa-allocation-replay-28g`：完整不可变 771 TU 合并 IR、实际包内 Python、Windows Job 28 GiB 上限、Solver 阶段 tracemalloc 与容器测量。该实验明确是受控资源剖析，不属于原生成功验收；尚未取得新修复结论。

## 可重复基线

- ECRA：`optimize_cc`，原始提交 `ac96abc39ffc66de53e57df82ca0ee791907bce6`。原有 `.gitignore` 两行修改保留，未推送。
- 原始代码归档：`H:/ecra_stm32_validation/baseline`。未改动其分析实现。
- 首选固件：[Prusa-Firmware-Buddy](https://github.com/prusa3d/Prusa-Firmware-Buddy)，`v4.4.1` / `570e86d56f6ca5ad36f5df984e52f2f20d542907`。
- 目标：MINI / BUDDY / STM32F407VG / Cortex-M4F / Release / BOOTLOADER=NO。
- 真实数据库：334 C + 437 C++ + 2 汇编，共 773 条；Ninja `firmware` 命令闭包逐条匹配 773/773，没有拼接板型。
- 两套真实构建均已成功：本机 CMake 3.31.10 + ARM GCC 10.3.1；Portable CMake 3.29.6 + 同版本 ARM GCC。`firmware.bin` 打包前 SHA-256 均为 `46b39eb8ea5e2685df0d2bbacc795e4bc5c85bb1430f0d4972b6172d3a5087c1`。
- 构建使用公开选项 `PRESET_COMPILE_OPTIONS=-D_DEFAULT_SOURCE`，使 newlib 在严格 C++17 模式下提供固件所用的 BSD/POSIX 声明。没有修改固件源码。

编译闭包不等同于链接器实际选取对象。`scripts/inspect_link_map.py` 使用 Ninja 原生 query 关联对象与静态库，再对照 GNU ld map 的 LOAD 与 archive-member 记录：Prusa 773 个对象中 413 个直接 LOAD，198 个库成员被选取，162 个库成员未被选取。全量分析仍保留 771 个 C/C++ TU，不删除那 162 个构建闭包成员。对象被选取也不保证每个节都通过 `--gc-sections` 保留。预编译的 GCC/newlib/libstdc++ 运行库成员不在源码数据库中，其外部调用继续按现有未知证据处理；不能声称已解析这些库的源码实现。逐对象证据在 `prusa-link-selection.json`。

官方构建依据：[固定版本 README](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/570e86d56f6ca5ad36f5df984e52f2f20d542907/README.md)。构建日志、编译数据库、链接命令、ELF/BIN/map 哈希位于外部证据目录的 `build_inventory.json`、`configure*.log`、`build*.log`、`link-closure-*.txt`。

## 一、快照一致性

### 确认的实现缺陷

旧 `ecra.cli.file_hashes()` 遍历工程根目录及额外排查目录，收入未被当前固件包含的源码、头文件和 CMake 文件。`run()` 使用两个不同的文件集合：开始时依赖尚未发现，结束时再增加 Clang includes；比较只遍历开始集合，无法对新增依赖建立相同的内容基线。

另一个独立判断是 `Path(include).stat().st_mtime_ns >= started_ns`。它不检查内容是否改变，所以纯 touch 会产生 `HEADER_CHANGED_DURING_SCAN`。随后 `analyze()` 原先先执行指针求解、上下文与调用图分析，再检查这两个 unknown kind 并抛出用户所见 ValueError。这解释了最后一个 Clang 进度之后才失败，以及大范围扫描更容易碰到无关生成文件的原因。

精确代码位置以原始归档为准：`baseline/ecra/cli.py:22` 遍历输入树，`:254` 产生 SOURCE_CHANGED，`:257` 用 mtime 产生 HEADER_CHANGED，`baseline/ecra/analysis.py:887–888` 在分析后段抛出 ValueError。注入日志保存实际异常。原始归档 SHA 和文件保持固定。

### 实测证据

`scripts/reproduce_snapshot.py` 在独立的可丢弃夹具中运行真实 Clang Worker，在提取返回后执行指定操作；不改动真实固件。原版和修复版的完整记录分别在：

- `H:/ecra_stm32_validation/snapshot-before/results.json`
- `H:/ecra_stm32_validation/snapshot-final/results.json`

| 条件 | 原版 | 修复版 |
|---|---|---|
| 稳定输入 | 完成静态扫描 | 完成静态扫描 |
| 修改真实源码 | 拒绝 | 拒绝，并记录路径与 SHA-256 |
| 修改被包含头文件 | 拒绝 | 拒绝，并记录路径与 SHA-256 |
| 只 touch 被包含头文件 | **错误拒绝** | 接受，内容哈希相同 |
| 修改未被包含的头文件 | **错误拒绝** | 接受，不属于输入闭包 |
| 修改报告 JSON | 接受 | 接受 |
| 修改编译数据库内容 | 拒绝 | 拒绝 |
| 删除被包含头文件 | 拒绝 | 拒绝，并保留缺失/集合差异 |

另有真实 Clang 回归：新建优先搜索目录中的遮蔽头文件、`__has_include("feature.flag")` 从不存在变为存在但没有实际 `#include`、嵌套 response 文件修改、不可读文件及 Windows 独占文件锁。不能只验证正向 include 列表；预处理跳过区间签名用来识别负向存在探测导致的活动分支变化。

### 修复设计

`ecra/input_snapshot.py` 建立真正的分析输入清单。配置、完整编译数据库、源文件、汇编输入、嵌套 response、实际使用的 CMake 缓存/工具链，以及配置用于证明的 ELF/map 明确入表。使用与提取相同的 libclang 参数预先发现包括系统及生成头文件在内的依赖。

SHA-256 来自两种证据：磁盘文件的前后内容，以及 Clang 当前 TU 中实际保留的文件缓冲区。提取和最终依赖发现必须匹配初始文件集合、内容及预处理分支签名。发布前再次验证，启用复核时复核结束后再验证。真实变化保留失败机制，输出 `diagnostics/source_changes.json`；不再凭时间戳拒绝扫描。提取中的源码片段也从相同 Clang 缓冲区读取，避免 AST 与后续磁盘文本混用。

进一步的确定性审计发现了独立的时间窗口：`load_config/prepare/expand_response` 已消费参数后，才建立磁盘快照。若此时文件改变并保持到扫描结束，原实现及最初修复版会把新内容收入快照，却按旧参数分析。`configuration-consumption-gap-before.log` 的三个实际 CLI/Clang 子用例（数据库、response、semantics）均证明错误返回了静态扫描成功状态 2，而预期应为拒绝 3。此结论是受控注入证实的漏检，不是自然发生的源变化。

最终 `read_consumed_text()` 直接对解析所用字节计算 SHA-256，记录消费时间；`read_yaml/load_config`、数据库读取和递归 response 展开共用该记录。`InputSnapshot` 把消费内容作为初始配置证据，立即对照当前磁盘，不再把随后内容当成已使用参数的基线。同一个 response 在两个 TU 之间变化后又还原，也保留多次读取哈希和 unstable 标记并拒绝，不依赖最终内容恰好不同。对应正反回归已加入 `test_scan_stability.py`，配置/Portable 集合实测 65 passed、12 subtests（43.85 s，`configuration-consumption-gap-after.log`）。没有把记录读取时间用于拒绝纯时间戳变化。

旧 broad `file_hashes()` 保留给旧检查点及兼容 API；新扫描和恢复使用实际输入清单。未参与构建的新源码不被宣称已解析；修改数据库以纳入它会使检查点失效。显式补充声明模式仍单独标识，不能把声明盘点当作当前固件访问覆盖。

### 恢复命令的闭包及发布窗口补充修复

实际 Clang 回归又证实，只有当前文件清单的 SHA 还不够：一次扫描完成后，新增位于更早搜索目录的头文件，或使 `__has_include("feature.h")` 从 false 变为 true，旧 `status` 仍返回 resumable=true。原先已知输入文件的内容均未改变，但实际解析输入/活动分支已经改变。两例实测失败在 `resume-input-closure-before.log`，不能写成已自然复现的用户现场故障。

`InputSnapshot.seal()` 现在另存不可变的 `input_closure.json`，包含实际已规范化的每个 TU 参数、依赖集合与预处理签名。检查点绑定该文件 SHA，诊断文件的存在与否不再能把精确模式降回 broad 模式。`verify_saved_input_closure()` 只用真实 Clang 做依赖/预处理重验证，不运行 CMake、不重新提取事实或改变分类；同时重新核对全部已知输入 SHA、当前分析配置和静态引擎。无关新头/报告和纯 touch 仍接受。缺少闭包的新式旧检查点要求重新扫描；原有 broad 检查点保持其原验证政策。

另外两个真实 CLI 用例证明，`saved_run(render_only=True)` 在最终 generate 内发生真实头内容变化或分析 contexts 配置变化后，原先仍返回成功状态（`saved-publication-window-before.log`，2 failed）。新增 `verify_saved_publication()` 在最终导出后验证事实/清单哈希和实际输入闭包；失败清除检查点、写无效性标记及无效 HTML/JSON，并保存完整 traceback、内存和变化明细。多 GB 的已生成报告通过同一输出树中的文件重命名保留到 diagnostics，而非为失败诊断再复制整个对象或文件；文件锁阻止重命名时保留原文件并记录归档错误，当前有效性仍置 false。

直接相关的首次回归实测为 39 passed /16 subtests；补充发布、兼容性和复核事实复用后的集合为 **87 passed /16 subtests，113.50 s**（`resume-final-targeted.log`），整套回归另行重跑。复核回归已从“禁止任何 Clang 调用”细化为“仅允许 dependencies_only，并断言完整 facts.json 字节未变”，保留事实复用和重复复核的原验证目标，同时允许必要的输入一致性检查。没有用减少 TU、关闭分析或跳过新输入来让测试通过。

上一版 `4e1aa03d…` 的实际完整 INAV 扫描和 771 TU Prusa 提取全部保留，其准确源码/包清单在 `pre-input-closure-engine`；新版本必须重新完成独立的连续三轮，不能将两个版本拼接验收。

上述恢复闭包与发布修复的最新整套测试已实际通过：**804 passed、2 skipped、270 subtests，600.64 s**，记录 `tests-input-closure-clean-all.log`。上一轮全套的唯一失败是旧测试禁止任何 Clang 调用，与必要的依赖复验冲突；未计 PASS，原始记录 `tests-input-closure-all.log`（803 passed /1 failed）。更新的两个复核复用测试均明确禁止构建与重新提取事实，并逐字节检查完整 facts.json 未变；专门回归 38 passed /8 subtests（`resume-policy-regression.log`），随后整套干净通过。

当时静态摘要为 `96a792af7da474ddf18f438c8131ed92bf93dc729740b171737106a26ae192a7`；实际包 50 模块和工作区一致，见 `portable-bounded/engine-files-input-closure.json`。INAV 配置 SHA `e39a3bf30ad7efa34e3a4076d0ed89e89856071e6978dca8fc71cfc497029501`，Prusa 配置 SHA `f7ff3c9ba6f0a3ea90c13228455b51e8b1afaa1ca1c553e4c0eb909a730979c3`，见 `input-closure-engine-config-receipt.json`。`portable-input-closure-validation/acceptance.json` 确认实际 Python 3.10.9、ARM 构建和各命令通过，不只是开发解释器测试。

### 自然复现边界

目前确认的是确定性故障注入，不能据此声称自然复现了用户现场。自动化准备脚本复用时实际更新过 `build/ecra-mini/CMakeCache.txt`：旧哈希 `c6e39875557633f32869f568ba57f0161c8da9aba70d11c050e3fa618cf6bd4d`，新哈希 `7d5249c5cdfe208be9b70012c2864dd35b025c843db4c69e78510d174b0bfac1`。该探索轮被明确作废并保存 `candidate1-run1/interruption.json`，没有计作稳定验收。

## 二、MemoryError

### 已确认的主进程路径

旧 `run()` 在每个 Worker 结束后 `read_json(response)`，把全部反序列化事实放入 `parts`，到最后才 `merge(parts)`。Worker 已完成并不代表归并、指针求解、分类或输出已完成。因此最后一个 Clang 进度不能定位异常进程或阶段。

对应原始位置为 `baseline/ecra/cli.py:220` 反序列化、`:232` 累积 parts、`baseline/ecra/points_to.py:36` 整 TU deepcopy，以及受控堆栈中的 `baseline/ecra/common.py:72`。这些位置应与本轮阶段记录和 traceback 一起解读，不能只依据进度文字推定异常在最后一个 Worker 内。

原版归并还存在额外峰值：`resolve_linkage()` 对含被强定义覆盖的 weak 函数的整个 TU `deepcopy()`，再建立结果列表；`merge()` 先拼接所有行后才按 digest 去重。SQLite 输出原先为整张表构造序列化 values 列表。重复扫描还会把上一轮完整报告常驻在 `previous`，但实际只需要 finding IDs。

这些是不同分配路径。本次实验后来取得了真实全量运行中的主进程 MemoryError，分别发生在单 TU JSON 读取、指针求解和 HTML 生成。它们不能合并成同一个堆栈，也不能据此反推没有现场 traceback 的用户原始运行必然失败在相同位置。

特别注意：当前 AuditScope 的目录设置主要筛选变量，依赖 TU 仍参与提取和调用链恢复。因此“小范围成功、全变量失败”不能仅由 parts 累积这一处解释。下面的 INAV HTML 故障直接证实，全变量输出的展示层也能成为主要分配来源；并非最后一个 Worker 失败。

### 真实全量运行取得的异常

| 运行 | 实际处理与快照 | 异常链路 | 主进程提交峰值 | 实验边界 |
|---|---|---|---:|---|
| `final-run1`，Prusa 中间候选版 | 771/771，VERIFIED | `cli.run → merge → resolve_linkage → FactParts.__iter__ → json.load → fp.read`，UTF-8 解码 MemoryError | 22,980,943,872 B | 未施加 Job 上限；其他压力实验同时运行，系统提交接近上限 |
| `portable-full-run1`，Prusa 中间候选版 | 771/771，VERIFIED | `points_to.Solver.solve → update → value → target_set.bitmap_values`，`bits & -bits` 分配失败 | 32,342,077,440 B | 未施加 Job 上限；同样受整机提交压力影响，不能独立归因为该位运算算法 |
| `inav-acceptance-run1`，INAV 中间候选版 | 374/374；分析、JSON、SQLite 已完成；VERIFIED | `cli.py:470 → report.py:298 → html_report.py:1280 → page():579`，整页字符串拼接 MemoryError | **46,808,616,960 B（43.60 GiB）** | 未施加 Job 上限；报告开始前主进程约 6.0 GiB，输出阶段大幅增加；系统提交上限约 95.4 GiB |
| `inav-baseline-run1`，未修改原版 | 374/374，事实已落盘 | `report.py:298 → html_report.py:1256 → table():277 → "".join(rows)` | 精确最终峰值缺失 | 原监控因整机 OOM 中断后，报告阶段明确施加 20 GiB Job 上限；属于**受控失败** |

完整证据分别位于各运行目录的 `merge-exception.log` / `analyze-exception.log` / `generate-exception.log`、固件对应输出目录的 `diagnostics/exception.log` 与 `scan_stages.json`。上述代码行号属于各自固定归档引擎，不是当前修改后行号。

INAV 失败前写出了 12,283,820,722 B 的 `facts.json` 和 11,960,528,896 B 的 `facts.db`。旧 HTML 虽把详情放在 `<template>` 中延迟加入 DOM，但 Python 仍在 `inventory_rows`、表格 body、content、完整 page 中同时构造并拼接所有访问和调用链字符串。模板并不降低生成阶段的总字符串体积。该实现缺陷已被实际堆栈和阶段内存增量确认，和全变量范围扩大有直接关系。

对该失败轮 SQLite 的全部 variables 列使用 `SUM/MAX(length(CAST(column AS BLOB)))` 进一步量化：accesses 共 2,209,654,674 B（最大单元格 23,585,529 B），variable_evidence_slice 共 792,778,917 B，conflict_pairs 共 563,446,725 B，multi_field_coherence 共 254,313,547 B，blocking_evidence 共 210,656,282 B。它们是**序列化字段体积，不是 Python 堆内存**，也不能相加冒充进程峰值。证据为 `inav-variable-column-sizes.json`；本机标准 SQLite 3.40.1 没有 dbstat，未安装或替换 SQLite，改用上述实际可执行的只读查询。

原版 INAV 后期限制依据为 `inav-baseline-run1/controlled-html-limit.json`（UTC 2026-10-21 14:19:40，21,474,836,480 B）。原版早期测得峰值约 6.99 GiB，但监控缺口覆盖最终 HTML 阶段；不得将早期峰值当作最终峰值，亦不得把受控失败写成原版无限制自然失败。

### 真实数据、受控限制的复现

使用 Prusa 同一真实构建目标前 12 个实际提取文件，Windows Job Object 限制主进程提交内存为 1 GiB。原版在以下调用链失败：

```text
scripts/benchmark_fact_merge.py: parts = [read_json(path) for path in files]
baseline/ecra/common.py: json.loads(Path(path).read_text(...))
json/decoder.py: JSONDecoder.raw_decode -> scan_once
MemoryError
```

完整堆栈：`H:/ecra_stm32_validation/merge-before-limited.log`；限制依据：对应 `.limit.json`。同样 1 GiB 限制下，最初逐 TU 共享布局的修复版峰值为 988,782,592 B，最终逐行读取版为 **833,384,448 B**（`merge-row-limited-12.json`），19 类事实表的数量与内容指纹全部相同。原版未限制的同批回放峰值为 1,501,921,280 B；最终版下降约 **44.5%**。数据没有扩增，也不是伪造 Worker 异常。

12 / 24 / 48 个真实 TU 事实回放均已执行，修复前后每个事实表的指纹一致。相应 `merge-before-*.json` / `merge-after-*.json` 和 `.prof` 保留完整指标。剖析启用 tracemalloc 和 cProfile，有测量开销；其耗时不能当作未剖析全量扫描耗时。

最终还完成了 **INAV 全部 374 个真实 TU 的同文件回放**，没有合成或扩增。原版与最终归并器的 19 个事实表逐项数量及内容指纹全部一致（包括 3 条 TYPE_VARIANT）；见 `comparison-inav-merge-374.json`。两次均显式设 12 GiB Job 上限，未触及上限，未启用 tracemalloc/cProfile。原版 OS 提交峰值 3,525,136,384 B，最终版 2,503,208,960 B，下降约 29.0%。代价是纯 merge 从 29.765 s 增到 111.250 s，含加载及完整事实指纹的回放总时间从 191.437 s 增到 238.328 s。逐行解码与有界规范化以额外 CPU 换取更低峰值，不能宣传成所有阶段都提速。这仍是事实回放，不能代替真实全流程验收。

### 已有大型产物读取的额外受控故障

全量候选轮实际写出的无缩进 `facts.json` 仍有 **8,040,593,223 B**。必须检查 report/review/status 能否重新使用它，而非只让第一次写出成功。使用实际 Portable Python 3.10.9，在明确的 12 GiB Job 限制下调用原 `common.read_json()`，5.0 s 内在 `Path.read_text → utf_8_sig.decode` 发生 MemoryError。完整记录在 `saved-facts-whole-12g/result.json`、`exception.log`、`limit.json`。这是**真实全量产物、受控资源限制的失败**，不冒充无上限自然故障；失败前已分配峰值 8,065,970,176 B 不能当作成功读取所需峰值，因为后续大块分配已被拒绝。

旧恢复路径还会 `clean_report()` 深拷贝整份报告，再调用 `digest()` 构造完整排序 JSON 字符串和 UTF-8 副本；status 验证检查点后，把解码的完整 facts 立即丢弃。这些是已存在的大文件分配路径。修复集中于 `workflow.py`：`read_saved_json()` 按顶层数组逐事实读取，保留空数组、重复值、嵌套顺序和全部标量类型，只对等值不可变字符串作有界共享；`saved_report_digest()` 流式产生与旧摘要完全相同的字节；`clean_report()` 只复制要修改的字典；status 及复核后的二次验证仍验证事实/清单哈希和静态指纹，省掉随后丢弃的 facts 反序列化。

`workflow.py` **原本就在** `REVIEW_REPORT_MODULES` 内，不参与静态分析指纹。本次没有添加排除项、改变 ENGINE_SCOPE 或跳过已有哈希校验。修改前后静态引擎摘要均为 `d5d767266566464ef75c95d5752708e998af5588a1e8eb68b95f31dce8c93bb2`，证据 `analysis-engine-before-artifact-loader.json`。全部模块版本仍另用文件 SHA 固定，最终连续三轮将按含此读取修复的完整包重新验收。

第一次仅共享字符串的流式读取仍在同一 12 GiB 限制下失败（`saved-facts-stream-12g`，643.078 s，提交峰值 12,884,697,088 B）。不能把逐行读取本身等同于解决全部内存问题。最终读取器对完整 AccessRow 建立有界规范化索引：只有全部字段、标量类型、嵌套顺序和字典键顺序都相同才共享同一个只读实体，数组条目和重复证据仍完整保留。索引淘汰只降低共享率，不删除事实。True/1、负零/零及不同嵌套顺序不会合并。

最终真实大文件验证已完成：`saved-facts-canonical-12g/result.json` 记录 successful=true、lossless_roundtrip=true；605.641 s 完整载入，1085.188 s 完成载入及全文件重编码校验，OS 提交峰值 **9,584,472,064 B（8.93 GiB）**。原文件与重新编码的 8,040,593,223 B 全文件 SHA-256 均为 `eb84f8472443c183b86c04e6885030e23e85a0813612e3fa8e6a5342dd489f92`。这比仅检查行数更严格，证明没有截断、删行或改变值。实际 Portable `status` 随后成功验证旧检查点并返回 resumable=true，记录在 `large-status-artifact-reader.json`；它仍有 3,106 个 PENDING，未伪装成已复核安全。

最终整套测试为 **796 passed、2 skipped、270 subtests，515.45 s**（`tests-final-complete-all.log`）。两个跳过项是可选 OpenCode 联机测试。报告读取器、旧摘要兼容、全部 JSON 类型、损坏输入、原报告不被修改以及 status 不加载 facts 但拒绝损坏事实均有实际回归。

### 最终报告发布窗口与重复导出的修复

进一步使用实际 CLI/Clang 注入，在最终 `generate()` 内修改被使用头文件，或创建影响 `__has_include` 的负向依赖，修复前两例均错误返回状态 2（`post-publication-snapshot-before.log`，2 failed）。原逻辑只在最终导出之前验证，长时间 HTML/JSON/SQLite 导出后没有再次检查，存在独立的一致性窗口。

最终 `run()` 在报告及检查点持久化之后增加“报告发布后输入一致性验证”：再次验证静态引擎摘要、所有 TU 的实际依赖集合/预处理分支和磁盘 SHA，然后才发布有效性与 completion 收据。真实变化使本轮失败、撤销检查点并生成无效页面；纯 touch 与无关输出仍接受。四类回归及原 CLI 流程的实测为 79 passed、16 subtests（`tests-final-publication-targeted.log`）。

对于 review.enabled=false 且 prepare_packets=false 的明确配置，省去原来的预复核报告导出，只完整导出一次；完整 review 队列仍保留 PENDING 和原因，`save_scan(initialize_queue=False)` 不重置它。启用复核或准备复核包时保持原来的两次发布流程。此改动不减少静态分析或证据，单次/双次路径全事实等价有测试。候选完整 INAV 轮 `inav-closure-acceptance/run1` 曾在旧检查点深拷贝/摘要路径达到 28,344,254,464 B；该轮是成功候选，不能计作包含最终发布保护的连续三轮。

最终完整包 50 模块固定于 `portable-bounded/engine-files-final.json`，静态引擎摘要为 `4e1aa03d3bd4de5e58e68eb016520a5b385622e086a46e0e96545bfe3e3a517a`。CLI 的发布流程改变使摘要正常改变；没有重写旧收据来冒充新版本运行。新连续验收目录为 `inav-final-consecutive`，Prusa 为 `prusa-final-canonical-full`，配置及摘要另存 `final-engine-config-receipt.json`。

原版 Prusa 大型扫描运行后主进程私有内存持续增加；为保护整机，运行期间明确施加 12 GiB 上限。到 234/771 时进程私有内存为 12,856,512,512 B，历史进程提交峰值 12,873,314,304 B，明确停止该受控实验以释放资源。`baseline-run1/interruption.json` 保存原因和进程身份；不是自然 OOM，也不是全量完成。

### 修复设计

- `ecra/fact_parts.py`、`ecra/json_rows.py`：Worker 完整事实保留在磁盘，主进程只读小型元数据；归并时以标准 JSONDecoder 逐个事实读取，避免连单个大 TU 都必须整文件解码。单个事实的缓冲区按需增长；空表、Unicode、跨块数字、截断、重复顶层键和尾部垃圾均有回归。等值字符串和只读类型布局有界共享，保留每条路径和调用点。
- `ecra/points_to.py::resolve_linkage`：以完整 strong 定义索引解析 weak 覆盖，逐项 yield；只过滤列表，不复制嵌套 CFG、表达式及变量对象。
- `ecra/analysis.py::merge`：归并时逐行去重，保持原来的首个位置/最后内容规则，保留自动产生的 PARSE_FAILED 与 TYPE_VARIANT 阻塞证据。开发中曾发现新归并器覆盖自动 unknowns 的回归，已修复并加入跨 TU 实际 Clang 测试；不能把那个中间版本当作最终语义等价版。
- `ecra/report.py::write_database`：使用迭代器逐行绑定 SQLite，连接在异常时也关闭，临时数据库仍原子替换。
- `ecra/cli.py`：不再常驻上一轮完整报告，只读取 finding IDs；Worker 结果按数据库顺序处理。有界并行仅改变调度，默认仍为 1，允许 1–8。
- `ecra/storage.py::propagate_overlapping_members`：INAV 真实运行堆栈确认正在逐访问遍历所有兄弟成员。15 秒 py-spy 采样中，443 个叶样本位于 overlaps、203 个位于 flexible_overlap。新增按 union、位域及重叠组建立的精确候选索引；柔性数组仍遍历全部成员做区间判定，原来的成员顺序和全部传播关系保留。该证据确认 CPU 热点，不能把它直接写成已发生的 OOM。
- `ecra/nvic.py::copy_state`：真实 NVIC 解释阶段栈反复进入分支状态的 deepcopy。新实现复制可变表容器，共享不可变标量；扩展值、嵌套退出状态及别名/循环仍使用同一个 deepcopy memo。未减少解释步数、函数、路径或分析证据。分支隔离和现有 NVIC 恢复测试已执行，完整工程前后比较待验收。
- `ecra/html_evidence.py`、`ecra/html_report.py::write_html`：大型报告保留每个变量的首页行；完整详情和大原始 JSON 流式写入本地、内容寻址的文件。展开详情才载入对应离线 iframe，图谱数据与锚点表仍完整保存。文件清单记录 SHA-256、字节数、指纹和 complete 标记，失败不会写为完成。不是只展示前 N 个冲突，也不把压缩展示用于安全证明。小型报告保持原内联形式。
- `ecra/report.py::generate`：事实、清单、报告和根因 JSON 改为无缩进序列化，仅移除无意义空白；字段和值不变，避免十几 GiB 的重复格式化输出。

共享头文件布局和 weak 过滤使用同一归属字段映射；函数指针、跨 TU 指针、上下文图、NVIC 解释、成员和冲突关系仍执行。没有修改固件、减少 TU、排除 vendor、关闭别名分析或将 UNKNOWN 改为 SAFE。

### 771 TU 真实事实压力回放确认的另一处分配峰值

`prusa-pointer-replay-24g` 使用同一 MINI 目标全部 771 个实际 Worker 输出（16,246,770,455 B），逐 TU 比对 source、directory、原始及规范化参数，使用真实 CLI 的归并/分析准备。只有提取响应被已捕获的完整事实替代，不拼接或扩增。Windows Job 限制明确为 25,769,803,776 B；这是**受控真实数据回放，不计全量扫描验收，也不称为用户现场自然故障**。

这次归并完成，随后在 `points_to.Solver.__init__` 原第 116 行重建 storage_definitions 时 MemoryError，尚未进入 solve 迭代。`allocation-frames.json` 给出 functions=75,081、variables=123,567、storage_definitions=**4,574,932**，points=0，读写/偏移缓存均为空。完整 traceback、阶段、输入 VERIFIED、退出码 3 和明确无效结果保存在回放目录及 `.ecra-analysis-replay/diagnostics`。系统当时仍有约 8.5 GiB 提交余量；异常触及的是已记录的单进程 24 GiB 限制，不能归为全机自然 OOM。

旧构造先为每个位置复制完整 row、路径 set 和数组边界 dict，再用整张字典推导式同时建立第二份 row/前缀 set。457 万个位置使元数据派生索引本身成为额外峰值；这与此前 `bitmap_values(bits & -bits)` 的后期堆栈是不同路径，不能混称为已确认的同一根因。

新增 `points_to.storage_definition_index()` 保留原始 pointer_storage 表全部行、位置和 owner，只让派生查询索引保存其实际读取的 paths/array_extents/array_size。相同布局通过有界 8192 项构造缓存共享不可变投影，全部路径前缀仍存在；同一位置的多份声明按原顺序合并，后来的不完整 extern 不擦掉已知边界。索引一次建立，不再同时保留整张旧/新 row 副本。没有删除 IR、函数、指针位置或目标关系。

`test_storage_definition_index.py` 使用原构造作为独立查询 oracle，对 600 条随机声明/路径/边界组合逐项比较，并检查原事实不变、2000 个位置共享布局但位置数不减、不可变性与 bool/int 类型区分。实际指针回归为 **49 passed，3.60 s**（`storage-index-targeted.log`）。同一完整 771 TU 数据的修复后受控回放为 `prusa-storage-index-replay-24g`，尚在执行；它明确标识 captured-dependencies，只验证已捕获依赖内容，不伪称重新 Clang 提取。原 `96a792af…` 引擎归档于 `pre-storage-index-engine`。

### 产物校验发现并修复的展示问题

增加 `scripts/validate_large_report.py` 后，实际 1001 变量夹具发现 HTML 详情的 `facts.json` 根目录链接漏加 `../`。这属于新展示层的相对路径缺陷，已补充 facts/inventory 链接转换和测试。正在执行的两个候选轮被明确停止，保存各自 `interruption.json`，不计入连续成功次数；随后重新冻结引擎并启动新验收。该夹具是合成 UI 测试，不替代真实 STM32 全量验收。

静态产物审计逐块解析 HTML、逐文件核验 sidecar SHA-256、检查全部变量行及本地链接，并可用 Node `--check` 验证脚本语法；JSON 按事实逐行检查并与 SQLite 逐表数量对账。这些检查不等同于浏览器实际渲染。

### 普通事实字典的重复键表

完整 771 TU 缓存包含 9,689,781,291 B 的全部 19 类事实。`bfb9e1bf…` 的共享存储索引已经成功构建：4,574,932 个位置对应 724 种共享布局，索引浅层 167,772,256 B，初始化后 Private Bytes 为 24,161,853,440 B。此后人为 24 GiB Job 上限使第一次指针求解失败在 `target_set.bitmap_values:49`；这次失败不再发生于索引构建。位运算请求本身约 18 KB，不能把最后一次失败分配直接等同于根因。受控失败时 points / unknown_points 所引用的位图字节数约 318 MB /306 MB（包含别名重复计数），另有 278 万任务及 232 万个待处理任务索引。完整 IR 本身已接近上限，证据见 `prusa-storage-index-replay-24g`。

`RecordDicts` 为至多 16 字段的重复有序 schema 使用 CPython 的共享键表，返回的仍是独立的普通 `dict`，不共享记录值，不改变键顺序、标量类型或 JSON 编码。构造器缓存仅保存至多 512 种 schema，不保存事实对象；较大 schema 使用原普通字典。它由 `FactParts._object` 使用，原来已存在的字符串及只读布局共享仍保留。真实 Portable Python 3.10.9 的同类五字段记录从 232 B 降至 104 B；完整缓存读取实际命中 46,170,693 次，仅 151 种 schema。

严格的同批真实 12 TU 受控对照使用相同 1 GiB 上限，未触达该上限，均关闭 tracemalloc/cProfile：峰值从 **411,803,648 B 降为 368,443,392 B（10.53%）**；归并 20.484→16.703 s，总计 31.312→27.578 s。全部 19 类事实数量和指纹一致。记录 `comparison-record-dicts-12.json`、`merge-pre-record-dicts-12.json`、`merge-record-dicts-12.json`。这不是 771 单元原生扫描结果，也不把短运行时间差外推为全项目性能提升。

更新后的完整 IR 受控读取端点为 20,647,518,208 B，索引后为 20,869,373,952 B。相较前一轮原生归并端点，其读取/字符串缓存边界不同，不作严格的全 IR 内存降幅基准。随后求解仍触及明确的 24 GiB 上限：71,157 个 points 集合所引用位图约 1.16 GB，unknown_points 约 1.14 GB，同样可能包含共享 int 的重复计数。这是受控资源不足，不能宣称完整求解通过，更不能作为用户现场自然根因的唯一证据。当前以未设进程内存上限的真实 Prusa 全流程判断最终资源需求，结果另见验证报告。

本轮还修正了事实计数的诊断口径：提取阶段明确标记 `translation_unit_rows_including_duplicates`；归并及分析入口重新计算实际表长度，标记 `merged_facts`，避免在求解故障时把全部 TU 的重复声明总数误当作归并后实体数。真实两文件 Clang + 分析入口 MemoryError 注入已验证该口径和失败有效性。压力脚本最终结果改用流式 JSON，释放诊断预留空间并在 CLI 返回后收集缓存环，防止已记录主异常后写 replay-result 自身再次 OOM；原发生二次 OOM 的记录保留，未改写成正常结束。

该开发阶段的完整回归实测 **813 passed、2 skipped、570 subtests，552.60 s**；对应 Full Portable 复验 PASS。后续完整套件已增加至本文顶部记录的数量，历史成功轮不计当前版本的连续三轮。

### 全局整数位图的稀疏宽度增长：完整 771 TU 的实证

`prusa-pointer-cardinality-probe/pointer-cardinality-probe.json` 使用同一份完整 771 TU 事实缓存，只在指定规模收集集合基数后明确停止；`full_scan_acceptance=false`、`pointer_stages_complete=false`，未生成安全结论。全局池达到 150,000 个原子时的实际数据：

| 集合 | 总数 | 仅一个目标 | 引用整数位图字节数 | 宽且不超过 128 个目标的位图字节数 |
|---|---:|---:|---:|---:|
| points | 33,596 | 31,289 | 463,080,148 | 439,493,152 |
| unknown_points | 33,596 | 29,958 | 449,908,832 | 426,598,976 |

按对象身份去重后，65,389 个整数实际占 912,945,708 B。约 94.9% 的上述引用位图字节用于宽而稀疏的集合，points 中 93.1% 只有一个目标。Python 全局整数位图的空间取决于最高编号，即使只有一个高编号目标也要保存其前面全部零位；当集合数和全局编号范围一起增长时，可近似产生二次增长。原有大集合字节迭代只降低遍历分配，不能降低这些常驻整数的宽度。此前 `bitmap_values:49` 是申请临时整数失败的实际位置，集合表示及缓存中保留的宽整数才是本条证据链确认的增长原因。此结论来自受控的真实完整数据，不冒称已唯一还原用户现场。

`ecra/block_bitmap.py` 以排序的非零 4096 位块表示同一个有限集合：每块最多 512 B 的位载荷，编号不限，零块省略，全部非零目标保留。并、交、异或、差、子集判断、基数、升序迭代及缓存键哈希均与原整数等价；哈希按 Python 整数模数计算，避免为哈希再构造全宽整数。现有求解任务、依赖唤醒、函数指针、别名及上下文算法没有关闭或减少。

小池仍使用旧 V1 证据格式；大池使用完整的 `INTERNED_BLOCK_BITMAP_V2`。`evidence_identifier()` 流式生成旧十六进制的哈希输入，**保留原 PTS 证据 ID**，避免保存大量零填充字符串。`point_targets()` 同时读取旧 V1 与新 V2。SQLite 在出现池化引用时保存全部原子与集合定义，防止引用表脱离定义后无法独立还原。此处没有把展示压缩当作安全证明依据。

实际 Portable 3.10.9 的隔离原型完成 16,000 项整数操作等价检查；1000 个约 900,000 编号的单目标位图，旧整数浅层合计 120,092,680 B，分块原型引用存储合计 649,472 B。该数字是**合成的对象布局实验**，不是原生扫描进程峰值。正式模块另有随机操作、稠密块、边界、旧 ID、V1/V2 解码及 SQLite 120,000 个逻辑目标往返测试。

同批真实 12 TU 的完整指针求解对照（开发 Python 3.10.11，固定 PYTHONHASHSEED=0）中，全部 **23 类归并/求解事实指纹一致**，目标原子顺序也严格比较。本批没有触发池压缩，V2 完整性由上面的单元测试另证。峰值 433,975,296→420,679,680 B；求解耗时 **1.593→2.797 s**，说明小规模存在 Python 分块运算的 CPU 开销，不能宣称所有规模更快。记录 `comparison-pointer-blocks-12.json`。大规模资源改善以正在执行的完整 771 TU 受控复测和最终原生扫描为准。

该阶段冻结静态摘要（历史）`8df72adf5a40a43ca27c29da911e68a6d8edb9b3308f6f406462ff9afbfc11aa`，51 模块清单见 `portable-bounded/engine-files-blocks.json`。实测整套 **817 passed、2 skipped、570 subtests，570.68 s**；实际 Full Portable 的 Python 3.10.9、ARM 构建及命令复验 PASS。最新原生目录为 `prusa-blocks-full`、`inav-blocks-acceptance`。旧 e395 原生 Prusa 在提取 385/771 后主动停止以实施此修复，INAV 的 374 TU 提取及原始关系比较完成后因资源前置中断被拒绝；均未计作本版成功，不能拼接连续验收。

### 实例缓存生命周期与字段键表的进一步实证

求解器实例上的 `lru_cache(self.storage_base)` 会通过绑定方法反向持有求解器。关闭循环 GC 的弱引用实验中，删除实例后仍存活（`solver-cache-lifetime-before.json`）；这确认了所有权环，不能单独证明用户原现场就是该环造成 OOM。修复以弱引用调用相同未绑定方法，缓存大小、参数、返回值和求解规则不变；调试回调也使用弱引用。修复后无需循环 GC 即释放实例（`solver-cache-lifetime-after.json`），真实 12 TU 完整全局求解的 23 类事实相同（`comparison-pointer-cache-lifetime-12.json`）。大型跨上下文峰值影响仍须实测。

第一版共享字典只创建空类，然后直接写返回的 `__dict__`，且跳过超过 16 字段的记录。实际 Portable Python 3.10.9 中，这不能扩展类的缓存字段表：12 字段实例字典仍为 640 B，与普通 dict 相同。通过一个仅含 None 的临时实例，属性写入预建全部字段名后，同样 12 字段为 232 B、24 /40 字段为 400 B，仍是普通独立 dict。证据 `record-dict-schema-limit-probe.json` / `record-dict-seeded-schema-probe.json` 为合成布局实验，不能当作扫描峰值。

`RecordDicts._make_class()` 在有界 512 个字段表缓存内完成预建，最多 128 字段；特殊名称 `__dict__` / `__class__` / `__weakref__` 及不适用情况返回普通 dict。仅共享字段名，不共享记录值；保留键顺序、嵌套值和类型。旧实现 5 个尺寸子用例失败，修复后相关集合 **22 passed /331 subtests，12.96 s**。同批真实 12 TU 合并及完整全局求解的 23 类事实指纹相同，提交峰值 **420,896,768 →323,600,384 B，下降 23.12%**，见 `comparison-pointer-record-seeding-12.json`。完整 771 IR 与原生峰值独立验证，不能用本批替代。

### 真实资源耗尽后的诊断验收

完整 771 TU /24 GiB 的旧分块回放在主异常后，保存分配现场及 exception.log 再次 MemoryError。128 KiB bytearray 不能确保 Python 小对象池及 Windows 私有提交同时有空间；仅抛出模拟异常覆盖不了真实耗尽。`emergency_memory.py` 提供 Python 尺寸池和 `VirtualAlloc` 的 8 MiB 私有提交；调用者先释放 Python 储备，处理器立即 `VirtualFree`。匿名 mmap 的共享提交不能代替 Windows Job 计量的私有提交。失败时不再为 tracemalloc 复制全部分配跟踪。

实际 3.10.9 的 128 /192 /256 MiB 硬额度探针及真实 Clang 夹具“先成功、再耗尽并拒绝旧报告”通过。完整大工程证据 **`prusa-lifetime-replay-24g`** 更进一步：771 IR 仍在设定的 24 GiB 额度下于 `points_to.load_location():459` 的 `load_dependencies[dependency].add(key)` 失败，但原始 traceback、实时事实数量、分配现场、内存/阶段、无效标记和退出 3 全部保存，`escaped_error=null`。耗时 1405.750 s、实测提交峰值 25,769,603,072 B（上限为 25,769,803,776 B）；`pointer_stages_complete=false` / `analysis_valid=false`，没有伪造成功。现场为 194,900 个 points 槽、140,628 个加载缓存、226,448 个加载依赖键、2,785,222 个任务，确认错误在主求解进程。字段表预建版继续独立验证资源改善，不能把这次预算失败记为扫描通过。

## 三、诊断与失败发布

`ecra/scan_diagnostics.py` 使用 Python 标准库记录阶段、操作、TU 进度、事实数量、快照状态、异常类型、完整 traceback、当前及峰值内存。Worker 分别保存诊断，父进程不再把 Worker MemoryError 当作普通 PARTIAL 结果继续发布。可选 Python 分配统计与进程原生内存相互补充。

输出包括 `exception.log/json`、`scan_stages.json`、`memory_profile.json`、`source_changes.json` 和成功时的 `completion.json`。Windows 数据分别保存 PrivateUsage、WorkingSet、PeakWorkingSet、PeakPagefileUsage 和系统 CommitTotal/Limit。系统 CommitPeak 是系统历史峰值，不能当成本轮扫描峰值；本轮系统提交峰值取采样期间 CommitTotal 最大值。

开始新扫描即清除恢复检查点并标记结果无效，旧成功结果先归档。失败或中断清除检查点、发布无效 HTML/JSON，`result_validity.json` 明确无效；不捕获 MemoryError 后伪造成功。SQLite 失败不替换旧数据库，旧数据库须结合当前有效性标记解释。

额外 Portable 实测启动在扫描前拒绝 INAV 数据库中的包外生成器与原 ARM GCC，完整 traceback 位于 `inav-portable-consecutive/run1/diagnostics`。这不是全量解析失败，也未计入三轮验收。增加布尔选项 `analysis.allow_external_toolchain`，使直接数据库模式可以显式使用已核实的原工具链而不触发 CMake 重配置；默认拒绝策略及旧 `analysis.cmake.allow_external_toolchain` 保留，编译器原始路径和外部工具审计记录完整保留。测试配置显式启用，未替换真实编译器。

## 四、额外发现与准确性

原 `system_includes()` 固定以 C 探测标准头文件，且没有使用 ARM 多库选择参数。C++ 的 `bits/c++config.h` 在默认 ARM 与 Cortex-M4F hard-float 目录中实际不同，涉及 `_GLIBCXX_HAVE_ATOMIC_LOCK_POLICY`、`_GLIBCXX_ATOMIC_BUILTINS`。已改为按语言与 MCU/ABI 参数探测，并将这些参数加入缓存键。最早的 Prusa 探索轮手动补充了默认 C++ 路径，其准确性结果不能混入采用正确多库配置的最终验收。

INAV 首轮 374/374 个 TU 提取完成，全部为 PARTIAL；唯一 error 是 `unsupported argument '1' to option '-flto='`，另有不影响解析状态的警告。`inav-parser-diagnostics.json` 保留每类错误的计数。不能把这些单元计作完整解析。

GCC 的 `-flto=N` 中 N 控制链接期并行作业数，[GCC 10.3 官方手册](https://gcc.gnu.org/onlinedocs/gcc-10.3.0/gcc.pdf)给出该语义。对真实 `bus_spi.c` 使用原工具链、原宏/包含/ABI 参数，`-flto=1` 与 `-flto` 的 526,855 字节宏清单完全相同，SHA-256 均为 `a160ceffde0d78a7458fac46b8497124bd8a47295f920af3bc1351b77929074e`。只映射这一参数后的真实完整提取为 PARSED；19 类关系事实中，函数、访问、调用、指针约束、存储、CFG、保护等相同，变量只差 `parse_status`。证据为 `inav-lto-macro-comparison.json`、`inav-lto-fact-comparison.json`。参数适配及最终三轮重新固定版本验收尚在执行，适配前轮次单独保留。

该历史首轮全部 374 个 TU 已实际完成提取：374 PARSED、0 PARTIAL、0 FAILED，输出 773,877,425 B，最大单 TU 为 51,346,710 B。全部 TU 的 18 类原始事实逐项比较，在显式记录变量 parse_status 从 PARTIAL→PARSED 后，其他字段与关系完全相同；恰好移除 374 条 unsupported `-flto=` error，未新增诊断。最初按数组位置比较发现 37 个 TU 有差异，实际是独立表行的置换（36 个 snapshots、2 个 accesses，存在交集）；改用保留重复行的多重集合比较，**没有规范化嵌套列表、访问类型、类型或证据内容**。完整记录在 `comparison-inav-raw-all374-normalized.json` 与 `comparison-inav-raw-summary.json`；原始严格顺序差异亦保留，不能把解析状态变化静默删除后称为完全相同。

完整并发语义回归覆盖全局/static、字段、数组、函数指针、跨 TU、MAIN/ISR/TASK、NVIC、PRIMASK/BASEPRI、旧值写回及不完整证据。结果和尚未完成的真实工程验收项见 `large_stm32_scan_validation.md`。

完整基线与中间候选的数据库均有 12,315 个变量，没有新增或遗漏身份；39 个持久事实表中 37 个严格一致（包含访问、函数、调用、上下文绑定、指针目标与 NVIC）。另外两表差异已逐项归因：中间归并器漏掉了 `USB_Tx_State`（`uint8_t` / `volatile uint8_t`）、`cliMode`（`_Bool` / `uint8_t`）、`jetiExBusPort`（`serialPort_t *` / `struct serialPort_s *`）三条 TYPE_VARIANT，影响相应变量阻塞证据；前两者分类未变，最后一项错误从 UNKNOWN 变成 SAFE_PROVEN。此问题不是原版缺陷，而是开发中增量归并引入的回归，已在最终实现中恢复，最终全量结果必须再次验证其仍为保守分类。`variables-baseline-initial-fixed.json` 保留全部变化字段及原始数据库行定位，不能用“变量数量相同”掩盖该分类差异。

后续完整成功候选 `inav-closure-acceptance/run1-facts.db` 已与原版逐表实测比较：39 表中 **36 表严格相同**，包括 unknowns、函数、访问、调用、指针、上下文及 NVIC。其余 3 表的全部变化已逐行解释：variables 的 12,315 行仅 parse_status PARTIAL→PARSED；struct_containers 的 782 行也仅此字段；translation_units 的 374 行仅 arguments 将 `-flto=1` 映射为 `-flto`、removed_arguments 增加原参数、移除对应唯一 error、parse_status 改为 PARSED。没有新增诊断，没有其他参数变化。变量身份新增/删除和静态分类变化均为 0，三条 TYPE_VARIANT 完整恢复。原始严格比较没有忽略这些字段，仍正确返回 identical=false；单独的解释记录为 `comparison-inav-baseline-candidate-metadata.json`、`variables-baseline-candidate-complete.json`。这证明该完整候选的静态语义保持；包含最后 CLI 发布保护的最终包仍须另行完成同等比较。

## 五、第二个真实目标：INAV

为同时验证大型裸机 C 工程，准备了 [INAV 7.1.2](https://github.com/iNavFlight/inav/tree/ed7fb3bb3216f8215150b42b52cb7b724e1dfae8)，固定 `ed7fb3bb3216f8215150b42b52cb7b724e1dfae8`，目标 MATEKF405 / STM32F405RG / Cortex-M4F / Release。官方工具链检查要求 ARM GCC 10.3.1，与本机一致；[固定版本构建说明](https://github.com/iNavFlight/inav/blob/7.1.2/docs/development/Building%20in%20Linux.md)明确支持 Ninja 按目标构建。

CMake 默认生成 219 个板型，原始全板型数据库约 396 MB，**未用于混合扫描**。使用 `ninja -C build/ecra -t compdb-targets MATEKF405` 原生导出一个真实目标的完整命令闭包：379 条记录中有 374 个 C 单元、2 个汇编输入，另有 Ruby 生成、链接及 objcopy 构建步骤。没有人工删除 C/C++ 条目。所有 374 个 C 对象实际完成编译并传给同一次链接，ELF 链接成功（FLASH 590,416 bytes，RAM 101,024 bytes，CCM 18,312 bytes）。

原生 Windows 下，官方 CMake 生成命令把 PATH 的分隔符和引号展开错误，settings Ruby 生成和聚合目标的 objcopy 因而失败。没有改仓库源码；仅把生成目录中的 settings `.bat` 调用替换为 `scripts/run_inav_settings.py` 环境适配器，CFLAGS 原样来自原生成命令，仍执行官方 Ruby 生成器。原始 `.bat`、生成请求和失败日志保存在外部证据目录。使用同一 objcopy 的相同 `-Oihex --set-start 0x08000000` 参数生成 HEX；`cmake --build build/ecra --target MATEKF405.elf` 再次确认 no work to do。这里没有把原聚合目标失败写成成功。

INAV 使用 MAIN 与自动发现的真实 IRQ 入口；其协作调度函数沿真实调用图继承 MAIN，没有因函数名含 task 而伪造并发 RTOS TASK。RTOS TASK 语义另由现有回归测试验证。原版与修复版全量范围均为空过滤列表，使用同一目标数据库，两个工程的 TU 数不相加充数。

GNU ld map 进一步确认 INAV 的 376 个编译对象（374 C + 2 汇编）全部直接 LOAD，见 `inav-link-selection.json`。额外预编译运行库对象单列，不计入 374 个已解析源 TU。

Prusa 前一轮完整提取的 502 PARSED /269 PARTIAL /0 FAILED 必须单列。实际错误包括 Arduino/newlib `utoa` 声明类型冲突（归并路径后 187 次）、constexpr 函数不能产生常量表达式（164 次）、不同语言链接声明、TMC2208/2209 构造函数不匹配（各 33 次）以及 naked 函数内非汇编语句等，不能笼统全部归为同一种 GCC 扩展。`prusa-closure-extraction-inventory.json` 保留逐 TU 完整诊断，`prusa-parser-errors-summary.json` 对完整错误文本归类；没有修改固件、吞掉这些 error 或计入完整解析率。最终重跑仍须按实际结果复核。

目标 ELF SHA-256 为 `bb1dc9ed6fa354246f7fa27b420c07ef8f78ccdd5f4a00ae75533ad216ab2ed1`，HEX 为 `8592cb100ed25dd585cc8dc0e5b72c19ca7d6041c897b618802bae821c682538`。仓库共 1,400 个受版本管理的 C/C++ 源文件；其余板型/未编译源码不能算作本目标完整解析。实际首轮 374 个 TU 输出 773,940,332 bytes，最大单 TU JSON 为 51,347,098 bytes，原始声明/关系计数见 `inav-extraction-inventory.json`，归并后去重计数须另报。

## 六、修改文件与设计依据

| 文件 / 主要函数 | 改动与依据 |
|---|---|
| `ecra/input_snapshot.py`（新增） | `file_record`、`read_consumed_text`、Clang 缓冲/预处理签名、`InputSnapshot`；实际消费内容和输入集合一致性，具体变化证据及安全拒绝 |
| `ecra/config.py` | `read_yaml/load_config` 可选记录实际消费字节；校验 Worker 数量与外部工具链显式开关，保持原调用兼容 |
| `ecra/compilation.py` | `prepare/normalize/expand_response` 捕获有效参数消费哈希；按语言/ARM ABI 探测系统头；精确适配 GCC 数字 LTO 作业选项 |
| `ecra/cli.py` | `dependency_inputs/results`、`extraction_responses`、`run`；输入预检、磁盘事实元数据、有界调度、阶段日志、归档和失败有效性；归档白名单包含 `QUALITY_PAGE`，防止下一轮运行中页面覆盖后历史质量页丢失 |
| `ecra/extract.py` | `Extractor.source_lines/run/main`；使用实际 Clang 源缓冲，依赖预检，小元数据，Worker 原生峰值和完整异常；MemoryError 不作为可忽略绑定错误 |
| `ecra/fact_parts.py`、`ecra/json_rows.py`（新增） | 可重放事实流、共享布局和有界缓存；`RecordDicts` 仅共享普通字典键表、保留独立值及 JSON 顺序；逐行标准 JSON 解码，完整 weak/strong 归属过滤 |
| `ecra/emergency_memory.py`（新增）、`ecra/scan_diagnostics.py`、`ecra/cli.py`、`ecra/extract.py` | 真正归还私有提交和 Python 尺寸池；进入故障处理前释放；完整异常及无效报告保留，失败清理不复制全部 tracemalloc 跟踪 |
| `ecra/points_to.py` | `resolve_linkage` 和统一 `WEAK_BODY_OWNERS`；去掉整 TU 深拷贝；`storage_definition_index` 保留全部位置及精确路径/数组边界，以共享不可变布局代替两轮完整行复制；`instance_cache/weak_callback` 不持有旧 Solver，禁止依赖循环 GC 才释放整轮事实；不关闭指针求解 |
| `ecra/block_bitmap.py`（新增）、`ecra/target_set.py` | 精确非零块集合、整数等价运算/哈希/顺序；完整 V1/V2 解码及旧证据 ID 的有界流式哈希，不减少任何目标 |
| `ecra/analysis.py` | `merge` 逐行去重并保留合成阻塞证据；`analyze` 在重型分析前拒绝不一致输入并标记真实阶段 |
| `ecra/storage.py` | `propagate_overlapping_members` 精确候选索引，仍传播全部 union/位域/柔性数组可能重叠访问 |
| `ecra/nvic.py` | `copy_state` 与解释分支调用；容器隔离和 deepcopy memo 语义不变，减少标量表重复深拷贝 |
| `ecra/report.py` | `write_database/generate` 逐行 SQLite、异常关闭、原子替换；池化目标的全部原子和集合定义也写入 SQLite，JSON 无缩进但值完整 |
| `ecra/html_evidence.py`（新增）、`ecra/html_report.py` | `HtmlEvidence`、`raw/deferred_detail/page/write_html/write_failure`；离线完整详情分文件，哈希清单、完整变量索引和图谱，失败页面明确无效 |
| `ecra/scan_diagnostics.py`（新增） | 阶段/完整 traceback/原生 OS 指标/可选 Python 分配统计；区分重复 TU 行总数与归并后事实计数；预留异常记录内存 |
| `ecra/portable.py` | `diagnostics` 审计显式允许的包外实际工具；`read_cache` 捕获最终 CMakeCache 及生成编译器元数据的实际消费哈希；默认隔离及工具版本保留 |
| `ecra/supplemental.py`、`ecra/initialization.py`、`ecra/linker_symbols.py` | `supplement` 可选 source_reader；汇编/ELF/map 消费字节与初始 SHA 绑定，实际使用的 map 集合进入闭包；普通解析失败不能吞掉输入完整性异常；Worker 诊断传播、补充声明边界保留 |
| `ecra/workflow.py` | `checked_scan/saved_run` 精确清单；`verify_saved_input_closure/verify_saved_publication` 复验已签名的实际参数、依赖集合及预处理签名并封闭最终导出窗口；`read_saved_json` 完整事实逐行解码及有界等值共享；`saved_report_digest` 与旧摘要逐字节兼容；`clean_report` 只复制修改的字典；status 避免解码随后丢弃的 facts，保持全部完整性检查 |
| `tests/test_scan_stability.py` 等新增测试 | 内容、集合、参数消费竞态、原生锁/生成、主/子进程 OOM、归档/SQLite/中断、静态语义等价 |
| `tests/test_json_rows.py`、`test_html_evidence.py`、`test_overlap_index.py`、`test_nvic_state_copy.py` | 流式边界、完整离线证据、精确存储传播、别名/循环拷贝语义 |
| `tests/test_ecra.py`、`tests/test_engine_digest_coverage.py` | 恢复检查点按真实闭包验收；复核仅允许依赖探测，禁止重新提取/构建并验证事实字节未变；hash-seed 子进程用例允许大型并行测试环境下的正常启动耗时 |
| `tests/test_storage_definition_index.py` | 独立旧算法逐项对照、重复声明边界合并、完整位置保留及共享布局不可变性；不把内部布局压缩当作删除原始事实 |
| `tests/test_record_dicts.py` | 普通 dict 类型、完整键值和顺序、逐字节 JSON、独立修改及 schema 缓存有界性 |
| `tests/test_block_bitmap.py` | 整数运算/哈希/顺序、稠密边界、高编号单目标空间、旧证据 ID、完整 V2 与 SQLite 往返 |
| `tests/test_emergency_memory.py`、`tests/test_solver_lifetime.py`、`tests/test_record_dict_seeding.py` | 硬额度实际耗尽、前次报告/锁/检查点失效、无 GC 的实例释放、字段表共享和特殊名称回归 |
| `tests/test_parent_source_reads.py`、`tests/test_report_archive.py` | 父进程实际消费字节、map 选择集合；连续两次真实 Clang CLI 运行后历史质量页内容完整保留 |
| `tests/test_large_scan_monitor.py`、`tests/test_large_scan_metrics.py`、`tests/test_worker_commit.py` | 系统提交不足时外部监控继续等待实际子进程；资源等待与内存指标口径；实际 Worker 内存耗尽后父进程明确失败和旧产物失效 |
| `tests/test_large_scan_acceptance.py`、`tests/test_large_report_pool_audit.py`、`tests/test_scan_comparison.py`、`tests/test_saved_json.py` | 验收器拒绝遗漏/无效输入；完整指针池及引用审计；比较保留重复及嵌套顺序；已保存完整事实的有界读取和损坏拒绝 |
| `scripts/validate_portable.py::Acceptance.builds` | 实际 `review-failed` 命令纳入 Full Portable 自动验收，review/review-failed/report 前后完整静态 facts SHA 不变；实际 Python 3.10.9 的 22 项验收 PASS |

新增脚本均不属于运行时依赖：`prepare_large_stm32.py` 复用固定工程构建；`inspect_stm32_target.py` 验证单目标数据库；`inspect_link_map.py` 区分链接选择；`large_stm32_scan.py` / `repeat_large_scan.py` 保存完整运行和连续验收；`benchmark_fact_merge.py` / `benchmark_pointer_solver.py` / `benchmark_saved_facts.py` / `replay_large_analysis.py` / `windows_memory_limit.py` 实施有明确标签的受控回放；`commit_reserve.py` 保护测试监控的诊断空间；`reproduce_snapshot.py` / `reproduce_parent_input.py` 执行独立夹具注入；`probe_diagnostic_memory.py` / `probe_worker_memory.py` 以真实额度耗尽检查主/子进程错误链；`compare_extracted_facts.py` / `compare_scan_facts.py` / `compare_variable_evidence.py` 比较完整原始关系、持久化事实与逐项分类；`validate_large_report.py` 审计完整产物；`validate_saved_commands.py` 实际执行大型已保存事实的 report/status；`large_scan_status.py` / `summarize_large_scan.py` 有界读取进度和归账指标；`run_inav_settings.py` 仅适配生成目录中的官方 Ruby 调用环境。

没有新增 ECRA Python 依赖、没有创建 venv。Full Portable 离线构建会复制完整 `ecra/*.py`，新模块均在包内并登记文件哈希；本次使用真实 Python 3.10.9 包执行，而非仅在开发解释器中导入测试。

逐文件 SHA、逐函数 AST 变更及当前行号另存 `H:/ecra_stm32_validation/workspace-change-index.json`，以原始 HEAD 为基准；它包含测试及脚本，不将原有 `.gitignore` 用户修改归因于本次修复。冻结核心另以 `archive-guard-engine-receipt.json` 的 52 模块逐项哈希验收。


## 补充确认：非 Clang 输入消费窗口（2026-10-22 晚间）

这是独立于“无关目录”和 mtime 误报的第三种完整性缺陷。确定性夹具实际在主进程读取 `startup.S` 时换成不同字节、读后恢复原文件。32f 包返回 2，未发现其消费的字节已不同，见 `snapshot-assembly-consumption-before/result.json` 和永久测试的修复前失败日志 `tests-parent-source-read-before.log`。这是受控注入证据，不能称为用户现场自然根因。

修复位于 `input_snapshot.InputSnapshot.read_bytes/read_text`，以已封存初始 SHA 核对真实消费字节，分别记录前后哈希和 PARENT_READ 阶段，失败即撤销安全结果；`SOURCE_READS` 将该保护传到汇编、初始化分析、补充源码及链接符号读取，错误不会被普通解析器回退吞掉。map 目录在扫描初始登记文件集合，只激活实际使用的输入，集合新增/删除在扫描和保存报告恢复时都检查。最终 CMakeCache 和 CMake 编译器元数据从 `prepare` 最后一次消费起绑定，不把合法先前配置生成误判为扫描变化。修复后保留原 UTF-8/换行读取语义；对没有内容变化的输入不改变分析事实。

对应新冻结包为 b148f056a58491f00c104add0599bf6cb17724060bd3296899d362c7d97950dc（52 模块）。主进程全部读取针对性回归 84 passed /8 subtests，最终补充 20 passed /2 subtests；全量测试及新原生连续验收另行记录，不能引用旧包原生结果作为本版本完成证明。

## 补充自然 OOM 与监控失败证据

旧 8df 包真实 771 TU Prusa 在全部 Clang 提取后，自然失败于 `points_to.Solver.load_location` 的 `load_dependencies[dependency].add(key)`，完整 traceback 在 `prusa-blocks-full/analyze-exception.log` 和原生 diagnostics。最后记录主进程 Private Bytes 51,806,322,688 B，系统提交接近上限；tracemalloc/cProfile 为关闭，故此证据独立于剖析器额外开销。依赖集合继续增长导致的分配失败仍是大型求解阶段风险；不能把前述位图/记录共享的局部降低宣称为该完整 Prusa 已修复。

外部监控器当时也遇到 WinError 1455，未取得实际 OS 退出码。恢复记录保留 exit_code=null、CLI 失败码 3 和最后采样边界，验收为 false；未补造完整退出数据。受控 32f 重放的监控器也退出，子进程仍在等待，恢复监控有明确空档。监控工具新增资源错误回归及继续等待原子进程的处理，不改变核心安全判断。新的最终原生扫描仍待完成。

实际 Worker 入口的真实额度耗尽与父进程传播也已单独验证：`diagnostic-input-read-real-worker-verified`（包内 Python 3.10.9、192 MiB Job），真实 Clang 提取完成后分配耗尽发生在被测 `Extractor.run` 路径，原生产调用方释放储备并保存 WORKER 诊断，父 CLI 拒绝 FAILED 响应并使旧报告失效。测试脚本 `probe_worker_memory.py` 及永久测试 `test_worker_commit.py` 不改变静态分析事实，也未加入新运行时依赖。

新 b148 原生第一轮已经完成变量/访问的持久化初步比较：全部 12,315 变量完整记录和 825,691 访问行与 4e 历史结果相同，保留重复及嵌套列表顺序，仅规范化表行/字典键顺序；原始 8.04 GB JSON 字节 SHA 不同，首差异为同一源码位置不同访问行的排列。证据 `comparison-inav-input-read-accesses-variables-preliminary.json`、`comparison-inav-gold-input-read-first-byte-diff.json`。最终全部事实表和三轮原生验收尚未完成，仍不宣布整体通过。

b148 原生 INAV 首轮真正完成并通过外部全量验收：374 PARSED /0 PARTIAL /0 FAILED，12,315 变量、69,680 函数、825,691 访问，分类 6,838 SAFE /814 SUSPECT /2,292 UNKNOWN；快照 VERIFIED、analysis_valid=true，归账无漏项/重复。总 5567.063 s（资源等待 505.360 s），主进程提交峰值 11,211,063,296 B、工作集峰值 10,272,362,496 B。随后同版第二轮也通过，6896.734 s、提交峰值 11,216,187,392 B，完整性字段、指纹与分类均相同。`inav-input-read-acceptance/run1`、`run2` 和 `two-historical-native-summary.json` 保存证据。这两轮属于历史版本，不能计为当前 fbc 三连或整个任务完成。

完整回归现进一步确认：b148 原生 INAV 首轮与 4e 的全部 39/39 持久化事实表严格相同，`comparison-inav-gold-input-read-native.json`。所有表行、重复数和嵌套列表保留，仅表行顺序和 JSON 字典键顺序规范化；当前未观察到变量身份、访问、调用/绑定、指针目标、NVIC 或安全证明分类的退化。该结论属于当前真实 374 TU 整轮结果，不替代连续三次完成、Prusa 完成或真实硬件验证。


## 独立归档缺陷的确认与修复

真实首轮归档报告的完整审计在质量页链接处失败，其余所有 12,501 sidecar、12,315 变量、JSON/SQLite、JS 检查通过。根因是 `cli.run` 只归档首页与 REVIEW_PAGE，漏了 QUALITY_PAGE，而 `write_failure` 会覆盖全部三页，原生质量页随后不再可从活跃输出恢复。修复仅将既有 QUALITY_PAGE 加入归档名单；两轮真实 Clang 回归先失败后通过，完整新套件 841 项通过。该缺陷独立于源码变化误报和 MemoryError，不能将归档审计 FAIL 混作自然扫描异常。

历史遗漏页从原生内容寻址质量 JSON 和同版本渲染器重建；全部 163 相关 sidecar 的内容哈希与原生 manifest 完全一致，分类未重算、未改变，原始失败审计未覆盖。新 CLI 冻结版本 fbc2518d 的三次验收重新开始，旧 b148 完整扫描仅保留为历史。详见验证报告“真实归档审计发现的漏页”。

fbc 的首轮完整原生扫描通过后，由第二轮真实 CLI 归档的大型报告已实际核对通过：`inav-archive-guard-acceptance/run1/native-archive-copy-validation.json`，四份质量页/首页/复核页/完整附件清单与首轮原件的完整 SHA 和字节数全部一致。质量页正常存在，未从其他报告拷贝或重新生成。该实测直接针对归档根因，不只依赖小型夹具；三轮及最终完整附件审计仍另行验收。

当前 fbc 首轮完整静态语义也已实际核对：`comparison-inav-gold-archive-guard-native.json` 全 39/39 表严格相同；原版逐变量直接比较无新增、删除或分类变化，唯一字段差异为 12,315 个 `parse_status`，见 `comparison-inav-baseline-archive-guard-variables.json`。完整变量/访问/调用/绑定/指针目标/NVIC/证明关系保留，不以只比较数量代替证据等价。

当前 fbc 首轮原生归档完整静态审计同样实际 PASS：1074.797 s，`inav-archive-guard-acceptance/run1/artifact-audit.json`。全部 12,501 sidecar SHA、1,508 HTML 的本地链接、12,315 变量、6 个 JS 语法、完整 JSON/SQLite 对账、指针池与 SQLite 完整性共 13 项检查通过。人工 GUI 的已有明确确认仍属于历史指定目录；此项未冒充新的人工渲染。

### 不可变位图共享候选：已执行的有限证据

`4edba35ca4a4c6cfad829c71db6d8100c8b9f1123c26f41ef63cedc09cf0d453` 的真实 12 TU 受控完整求解与 fbc 对照：23 张完整事实表指纹全部相同，差异 0（`comparison-pointer-sharing-12.json`）。这不是 771 TU 验收，小批数据也没有显示可据以外推的大幅进程峰值改善。

包内实际 Python 3.10.9 的合成分配实验保留全部 241 个完整历史位图、每步对照独立整数并集，最终 82,320 个目标不变：旧实现 38,560 个不同块对象，新实现 400 个；tracemalloc 峰值 27,248,866 →955,134 B；OS 进程私有提交峰值 50,696,192 →10,313,728 B。证据 `bitmap-sharing-allocation-before.json`、`bitmap-sharing-allocation-after.json` 和可重复外部脚本 `measure-bitmap-persistence.py`。这是合成分配证据，不能写成真实 Prusa 降幅或原现场根因已彻底修复。包内解释器下新增两项分配测试实际通过；初次 `-m unittest tests...` 因嵌入解释器 `_pth` 不含工作区导致导入失败，保留日志，改为显式工作区导入和 run_path 后通过，没有更换解释器。完整测试已通过 843 项及 592 subtests；该候选实际 Full Portable 22 项检查 PASS，详见最新执行状态。

### 依赖图名称共享：真实分配来源与有限回归

- 新候选 `3948abe93f1a6de0d023d3cbb3e2a1ba7fbc0780edae2414dc4231773ebf798a` 与冻结 fbc 的同批真实 12 TU 完整求解，23 张事实表指纹全部相同，`comparison-pointer-dependency-12.json`。这不替代真实全量验收。
- 包内 Python 3.10.9 合成分配实测：800 个完整加载结果、808 个完整依赖节点以及所有依赖关系 SHA 均相同（`876c5ae2de4ec830272f2a32bf853b5cfe5ec0ebdd39bd3db571f4b3ee08aecb`）；同一长祖先由 800 实例变为 1 实例。tracemalloc 峰值 **12,825,825 →3,455,686 B**，OS 进程提交峰值 **24,801,280 →13,946,880 B**，证据 `dependency-allocation-before.json` /`dependency-allocation-after.json`、外部可重复脚本 `measure-dependency-persistence.py`。没有删除缓存结果、依赖边或读者。
- 新增两项回归在实际包内解释器下通过；Full Portable 22 项实际命令/构建检查 PASS，`portable-dependency-names-validation/acceptance.json`，静态 facts SHA 保持不变。完整回归仍执行中；没有宣布当前候选原生成功。
