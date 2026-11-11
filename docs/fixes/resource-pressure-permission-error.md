# Windows 资源调度文件读取故障修复

## 已确认的故障链

现场在“Clang 翻译单元提取”阶段已处理 178/220 个 TU。主流程在补发任务时先调用 `is_file()`，再打开 `resource-pressure.json`。打开操作抛出 `PermissionError(errno=13)`，异常直接退出调度器。现场记录未提供 `winerror`。文件共享冲突、替换时序和权限变化仍是可能的触发条件，现场是否存在独占句柄及其来源仍待确认。

现场可用物理内存约 8.67 GiB，提交额度余量约 15.45 GiB，现有证据仅确认文件访问异常。主进程内存记录的范围是主进程本身。输入快照当时为 `VERIFIED`，结果为 `analysis_valid=false`。178 是主流程已处理量，可能含解析失败。待处理的 42 个也可能包含在途或等待消费的结果。

源码基线是 `optimize_ccc` 的 `d19758dcbe584c84cc552bbc1f434a4020833e00`。现场 `D:\code\AI\global21\global_static_concurrency_design-optimize_ccc` 在本机不存在，使用同分支、同提交且初始干净的 `H:\global_static_concurrency_design`。直接执行规则来自用户提供的 AGENTS.md。

## 实现

| 文件 | 修改 |
|---|---|
| `ecra/resource_control.py`、`ecra/scan_stop.py` | 按用途读取资源控制 JSON。对访问拒绝和暂时缺失使用单调时钟计时，最多 5 次尝试，间隔 50、100、200、400 ms，重试期限 0.8 秒。等待每 20 ms 检查一次已有停止标记。严格要求 JSON 对象包含 1–8 的整数限制，并按任务预算封顶。 |
| `ecra/cli.py`、`ecra/git_diff.py` | 仅在还有 TU 可发放时读取限制。重试暂停补发，成功后继续按编译数据库顺序消费，全部发出后无需再读取。退出提取时关闭生成器并回收所属 worker。 |
| `ecra/common.py` | 提取进程支持取消。取消和超时时回收所属进程树，清理等待有上限，清理错误保留为备用日志。通用 JSON 读取与原子发布接口保持原有语义。 |
| `ecra/scan_diagnostics.py` | 记录重试、恢复、失败和取消事件。提取期间由调度器轮询停止信号，避免诊断采样线程在 worker 回收时重复打断。 |
| `ecra/studio/tasks.py`、`ecra/studio/resource_policy.py` | 初始化先写入单并行限制，再创建进程、分配预算并开放启动门禁。初始化失败记录任务并释放租约。各项资源采样和停止判断独立于控制文件发布，保留 Windows Job 硬限制及原阈值。停止标记写失败时记录实际错误并通过所属 Job 停止任务。 |
| `studio/src/TaskCenter.vue`、`ecra/studio/web/` | 任务详情保留当前阶段、故障时已处理量和实际状态，任务日志保留短暂状态，打包界面使用相同文案。 |
| `tests/test_resource_pressure.py`、`tests/test_studio_resource_policy.py` | 实际调度、异常注入、Windows 共享句柄、初始化门禁、资源停止、失败发布边界与诊断备用日志回归。 |

未配置 `ECRA_RESOURCE_PRESSURE_FILE` 的 CLI 继续使用原配置。配置后若持续不可读或内容无效，扫描走失败退出，结果保持无效。取消仍使用中断状态和退出码 130。任务保留已写入的数据。已有控制文件的写者在门禁前是任务启动器，门禁后是同一监督器的监控线程，二者没有重叠写入。沿用先完整写入临时文件、关闭后原子替换及 Windows 替换的有限重试。

读取故障事件写入 `diagnostics/resource_control.jsonl`。终止时的阶段、异常链和原始栈见 `diagnostics/exception.json` 与 `exception.log`。诊断包含操作、路径、异常类型、`errno`、可空的 `winerror`、尝试和重试次数、耗时及已处理/总 TU。诊断文件写入失败时使用标准错误日志。发布和停止标记写入故障记录在任务的 `supervisor.log`，资源采样继续写入 `resources.jsonl`。

## 验证

环境为 Windows 10 专业版 19044、Python 3.10.11、libclang 18.1.1、GNU Arm Embedded GCC 10.3.1。

在修改生产代码前运行 `py -3.10 -m unittest tests.test_resource_pressure -v`。唯一用例在旧 `replenish()` 的 `Path.open()` 处报 `PermissionError(13)`，无 `winerror`。修复后，同一用例在 178/220 注入连续三次拒绝，四次打开期间提交数始终为 181，最终 220 个 TU 各提交并消费一次，顺序与数据库一致。

以下命令在修复后通过 67 项测试。

```powershell
py -3.10 -m unittest tests.test_resource_pressure tests.test_studio_resource_policy tests.test_bounded_extraction tests.test_task_recovery_failures tests.test_studio_api tests.test_working_checkpoint tests.test_engine_digest_coverage tests.test_extraction_runtime_cache tests.test_sqlite_scan_stop -v
```

以下扩展回归通过 69 项，覆盖真实 CMake/ARM 构建、Git Diff、独立全量对照、worker 提交、Job 进程所有权及原子发布。

```powershell
py -3.10 -m unittest tests.test_canonical_scan tests.test_git_diff tests.test_native_sequential_verification tests.test_worker_commit tests.test_owned_process tests.test_atomic_output -v
```

- 实际调度覆盖首次拒绝、连续拒绝、单并行和多并行、在途 worker 保留和回收、缺失后恢复、持续缺失、非法 JSON、目录路径、重试中取消、无末尾读取及普通 CLI。实际持久化测试断言失败扫描无发布清单，上一份有效结果和指针保持原值。
- Windows 共享验证在临时目录中由独立进程用 `CreateFileW` 持有句柄，通过跨进程事件确认就绪及释放。实际读取在期限内释放时恢复，持续持有时受控失败。允许共享读但禁止删除的句柄阻挡实际原子替换，验证旧 JSON 仍完整可读，释放后新 JSON 完整发布。
- Studio 在本地 Uvicorn、实际 Windows Job 和独立测试数据根上运行。使用 Playwright CLI 打开“扫描任务”并点击“检查并扫描”，以 6 个 ARM TU 的测试工程验证。恢复任务在约 0.08 秒恢复并发布 6/6。持续持有在约 0.80 秒进入失败，退出码 3。实际页面“安全停止”在重试期间提交，约 0.12 秒退出重试，终态为中断，退出码 130。后两轮均无成功收据、无发布且 `analysis_valid=false`，有效指针仍指向第一轮。此项注入使用真实 Windows 句柄，现场触发原因仍未查明。

Vue 源码用 `vue-tsc --noEmit` 检查，使用 `vite build --outDir <临时目录> --emptyOutDir` 构建后更新随包 JS 和入口 HTML。`node --test studio/tests/investigation-state.test.mjs` 通过 8 项。浏览器验证用 `npx.cmd --package @playwright/cli playwright-cli -s=ecra-pressure open <本机会话入口>`，再通过 `click`、`snapshot` 和 `run-code --filename studio-cancel.js` 检查实际任务和取消按钮。临时 Studio 验证脚本只在测试数据目录引入真实共享冲突，扫描使用生产路径。

### STM32CubeF4 CDC 实工程

使用仓库已有 `validation/stm32_cube_cdc_20261018/projects/p00`。同一编译数据库与配置分别由基线和修复版运行 `run_canonical(..., no_review=True)`。两轮使用独立临时数据根，基线使用原 CLI 调度，修复版启用资源控制并设置双并行。执行命令如下，`$audit` 为临时目录。

```powershell
py -3.10 -B "$audit/golden.py" $audit "$audit/baseline" original
py -3.10 -B "$audit/golden.py" $audit "$audit/fixed-tool" fixed
py -3.10 -B "$audit/compare.py"
```

两轮均完整消费并成功解析 39 个 TU，数据库顺序和内容逐项相同。覆盖 8 个目标 TU 和 31 个依赖 TU，盘点 244 个变量，得到 205 个候选或盲区复核项。两轮完成输入复验，`snapshot_status=VERIFIED`、`analysis_valid=true`，发布清单均为 `STATIC_VALIDATED`。关闭 OpenCode 时，两轮均保留原有报告状态 `INCOMPLETE` 和退出码 2。

比较 SQLite 权威事实和报告，候选结论及其顺序一致。事实字段只有 `unknowns` 摘要不同，其中 6,314 条记录逐值及出现次数一致，有 27 个列表位置发生换序。覆盖内容在排除输入收据读取时间后相同，报告其余差异为输出路径、运行时间和包含引擎摘要的扫描指纹。比较脚本直接核对两份已发布归档。

## 升级后的入口

保留原任务、诊断和缓存。同版本重试仍以引擎、配置、编译器、依赖输入和缓存内容均通过校验为复用条件。此次修改包含在 `engine_digest()` 的现有覆盖范围内，因此升级会产生新的 TU 缓存键。从 Studio 的“工程配置”选择已保存配置并发起新扫描。旧 CMake 冻结输入检查点遇到引擎不同时仍会提示从工程配置启动新扫描。重新扫描的 TU 数量由完整输入校验和当前可用缓存决定。

原私有 220 TU 工程未提供，尚需在该工程上验证升级后的完整扫描和现场触发条件。
