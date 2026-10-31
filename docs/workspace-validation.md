# ECRA 工作区重构交付与验收

本轮起点为 optimize_ccc 的 `1d60fc6`。开始前已 fetch origin/optimize_ccc，领先/落后均为 0，工作树干净。修改直接在该分支完成，没有从其他分支覆盖实现，没有调用外部编码代理。运行数据保存在被工具仓库忽略的 workspace，不随源码提交；远程交付分支为 optimize_ccc，实际提交以 Git 远程记录为准。

## 根因

原 run 先在 `project.root/.ecra` 写日志、run.json 和状态，再调用 pin。pin 对整个固件仓库执行 status；HEAD 即使声明不包含未提交修改，仍使用原工作区分析，因此自身未跟踪产物也触发拒绝。CLI/workflow 又限制 output_dir 必须在工程内；CMake、基准事实、恢复命令分别推算目录，只改一个输出字符串不能解决问题。

原基准在 worktree 内写 `.ecra-diff-base`；当前任意引用会重写 worktree 中的编译数据库；构建也默认在源码内。迁移只改 HTML 会留下构建污染、错误版本数据库和恢复路径不一致。

## 最终结构与安全边界

详见 [工作区与迁移说明](workspace-migration.md)。统一 WorkspaceResolver 以仓库真实绝对路径及工程相对路径生成完整 SHA-256 身份，目录取前 20 位，project.json 验证完整身份。分支不参与身份。工具移动保留历史可追溯信息；工程移动或绝对路径相关输入改变时拒绝旧检查点，重新分析，不伪造缓存命中。

默认结果、缓存、历史、Patch、事实归档和源码工作树均在工程独立 workspace；构建在该 workspace/builds。原工程路径、实际分析路径与数据目录分别传递。HEAD 的已提交比较与其他引用统一使用独立工作树；源码树采用短 trees 层级和 16 位目录名以适配 Windows Git，完整 SHA 校验不变；包含未提交修改时继续分析原工作区。没有关闭 assert_pin、输入闭包或发布后校验。

同工程扫描/复核共享项目锁，基准子扫描有独立 artifact 锁。目录归属、完整身份、链接/Junction、构建所有权、写权限及工程/数据边界均检查。显式 project 模式也不能接管未知用户目录或身份不符的旧数据。

历史迁移使用流式复制、逐文件大小/哈希校验、源数据集合复核及整目录发布。中断后保留 pending 和原件；不删除旧数据。原 HTML、review 收据、状态、备注与历史全部保留，旧结论需重新校验。当前分支没有独立 HTML 人工确认持久化接口；没有编造新的变量绑定或将失效结论当作当前确认。

完整检查点绑定源/头文件、生成头文件、编译数据库、CMake 输入及工具二进制。运行环境变化也使检查点失效。实际编译参数、文件内容和缓存键使用真实路径；仅在存在当轮构建数据库证据时，版本比较将各自构建路径规范化，避免外置构建地址导致假语义变化。

## 源码修改清单

| 文件 | 关键位置与原因 | 兼容性 |
|---|---|---|
| `.gitignore` | `/workspace/` | 不改固件忽略规则 |
| `ecra/workspace.py` | WorkspaceResolver、output_settings、lock_path、build_path、migrate_legacy、generated_untracked、validate_analysis_inputs、validate_analysis_inputs | 新统一解析、完整身份、外置默认、旧目录校验迁移；不按目录名忽略源码 |
| `ecra/cli.py` | run | 统一初始化、迁移、锁、实际分析根、终端边界、二进制输入和报告项目元数据 |
| `ecra/config.py` | load_config、两种模板 | 接受 output/location，验证冲突；运行时所有权不能由 YAML 注入 |
| `ecra/compilation.py` | cmake_build_directory、configure_cmake、prepare | 外置隔离构建；旧扁平 CMake 也走同一实现；保留参数、显式 project 兼容和所有权清理 |
| `ecra/scope.py` | AuditScope、select_facts | 外置生成文件按原 build_dir 执行范围规则，原始事实保留真实路径 |
| `ecra/supplemental.py` | selected_files | 工程内输出兼容模式下，保留嵌套 worktree 的非构建文件库存 |
| `ecra/git_diff.py` | pin/assert_pin、prepare_base/current、current_context、check_isolated_tree、build_arguments | HEAD 固定提交；外置 worktree/事实/数据库；拒绝隔离源码污染；保留 Patch、摘要、索引和输入完整性 |
| `ecra/input_snapshot.py` | runtime_environment、seal、verify_disk | 环境进入闭包并在扫描期间校验；与二进制内容一起保护完整基准缓存 |
| `ecra/workflow.py` | analysis_config、output_path、status、saved_run、verify_saved_input_closure | 所有恢复命令定位同一结果/锁；不把输出位置当作静态语义；旧环境检查点明确失效 |
| `ecra/tu_cache.py` | TUCache.__init__ | 使用统一的语义配置指纹；保留实际输入、编译器、LibClang、环境和引擎绑定 |
| `ecra/portable.py` | build_path | 修复 ASCII 工具目录下中文工作区后缀未被别名覆盖的问题；真实 ARM ar/CMake 验收复现后修复，别名仍验证真实目标 |
| `ecra/html_report.py` | page | 保留原页面；展示原工程、结果目录、固定提交与未提交覆盖边界 |
| `ecra/multicore.py` | combine | 各输入变体通过统一层定位结果，保留 ELF 证据逻辑 |
| `build_portable.ps1` | 打包白名单、发布门禁 | 运行数据不入包；自测后发现包内 workspace 就拒绝发布，不自动删除数据 |
| `scripts/validate_portable.py` | Acceptance.builds | 独立真实固件夹具、外置自测数据、迁移的源码副本默认输出、命令/事实不变性 |
| `scripts/validate_portable_diff_target.py` | scan | 在包内解释器解析实际结果目录，保留目标闭包及独立全量对照 |
| `scripts/benchmark_project_scan.py` | main/基准审计 | 统一结果/锁和外置基准 artifact 定位 |
| `scripts/validate_git_diff_stm32.py` | scan | 真实 ARM/CMSIS 矩阵统一读取结果 |
| `scripts/validate_cdc_git_diff.py` | main | 真实 CDC 矩阵读取相同项目工作区 |
| `scripts/large_stm32_scan.py` | validate | 大工程验收通过统一解析层读结果 |
| `scripts/validate_stm32_cdc.py` | result_path、扫描与复核入口 | 全部 facts/队列/轮次路径统一 |
| `scripts/audit_github_stm32_inventory.py` | main | 审计统一定位完整 facts |
| `scripts/export_github_stm32_review.py` | main | 复核导出定位同一工程，收据地址指向真实文件 |
| `scripts/validate_review_failed.py` | 夹具配置 | 显式选择 project 模式，继续验证旧式 CLI 容错流程 |
| `scripts/probe_diagnostic_memory.py`、`scripts/probe_worker_memory.py` | 内存故障夹具 | 显式 project 模式，保留真实内存失败记录与恢复断言 |
| `scripts/validate_workspace_migration.py` | 新增实际集成脚本 | 冻结旧引擎/当前引擎同源事实、分类、ECAT SP、缓存与性能对照 |
| `scripts/validate_workspace_matrix.py` | 新增留证执行器 | 保存配置、Git 输入 bundle、发布物、日志、预期和实际断言结果 |
| `tests/test_workspace.py` | 新增真实 Git/CMake/多进程测试 | 覆盖新默认、项目隔离、迁移、权限、Junction、生成输入、环境、锁和归属 |
| `tests/test_git_diff.py` | Git 集成断言 | 提交比较忽略原工作区脏字节；include=true 仍检测变化；构建产物断言移到真实外置路径 |
| `tests/test_ecra.py` | ProjectTest.project | 原功能夹具显式 project 模式，保留原有路径断言；新默认由独立集成测试覆盖 |
| `tests/test_complete_inventory.py` | scan 夹具 | 同上，不改变量/证据断言 |
| `tests/test_scope_cmake.py` | fixture/managed | 显式兼容模式验证旧目录所有权、清理、参数及越界拒绝 |
| `tests/test_portable_build.py` | setUp | 继续测试显式工程内构建的兼容所有权行为 |
| `tests/test_onboarding.py` | 自动配置断言 | 验证实际 -B 外置且重复使用同一目录，每次刷新数据库 |
| `tests/test_real_classification_repair.py` | 构造器 map 夹具 | 明确声明其测试使用源码内构建，不改变分类证明断言 |
| `tests/test_portability.py` | 输出及 ARM 对象定位 | 统一解析实际产物，保留四种 Cortex 和真实工具链断言 |
| `tests/test_second_pass.py`、`tests/test_variable_inventory.py` | 原功能夹具 | 显式 project 模式，保留变量与二遍提取断言 |
| `README.md` | 使用入口/输出说明 | 一条命令，默认路径更新并链接迁移说明 |
| `config/semantics.yaml` | 配置注释 | 保留原项目、Git 引用和分析参数，仅说明新路径规则 |
| `docs/git-diff-concurrency-validation.md` | 当前工作区语义说明 | HEAD 语义、结果及 worktree 路径更新；历史验收记录仍保留其版本范围 |
| `docs/portable-usage.txt` | 构建/默认输出/升级说明 | 外置构建、写权限与历史保留 |
| `docs/workspace-migration.md` | 新增使用与恢复文档 | 新旧配置优先级、所有权、迁移与手动恢复 |
| 本文及 `workspace-validation-results.json` | 交付记录 | 实际结果、未执行项与证据索引 |

`review.py`、`review_integrity.py`、`html_evidence.py`、`history_archive.py` 已审查。它们继续使用调用方传入的实际源码/输出根，既有引用、收据、摘要校验和原子归档协议保留。静态提取、并发分类、NVIC/PRIMASK/BASEPRI、指针与调用链算法没有修改。

## 测试与证据

最终机器结果以 [workspace-validation-results.json](workspace-validation-results.json) 为准，包含 T01–T30 的输入、命令、预期、实际与留证位置。开发过程中被引擎变化门禁拒绝的轮次和被主动停止的混合版本轮次不计通过。

源码中的检查在引擎文件变化时正确拒绝发布。因此最终冻结之后重新执行回归；旧版本日志不能代替最后一版源码的通过记录。测试过程中没有执行 reset/clean/stash，没有修改原固件忽略配置，没有用降低分类或删断言解决问题。

固定代码后的最终命令记录：

| 命令 | 实际结果 | 日志 |
|---|---|---|
| `py -3.10 -m unittest discover -s tests -q` | 1,068 项；1,066 通过、2 跳过；0 失败、0 错误；2228.199 秒 | `workspace-release2-complete-unittest.log` |
| `py -3.10 -m unittest tests.test_git_diff -v` | 49 通过；800.345 秒 | `workspace-release2-complete-git.log` |
| `py -3.10 -m unittest tests.test_git_diff_patch -v` | 4 通过 | `workspace-release2-complete-patch.log` |
| `py -3.10 -m unittest tests.test_relative_worktree_gitdir -v` | 4 通过 | `workspace-release2-complete-gitdir.log` |
| `py -3.10 scripts/validate_workspace_matrix.py --evidence workspace/acceptance/retained-release2-code` | 20 通过；0 跳过 | `workspace/acceptance/retained-release2-code/unittest.log` |

这些分组有覆盖重叠，不把它们相加伪造独立测试总数。两项跳过为需显式启用的真实 OpenCode/提供商连接验收，未记为通过。完整回归日志含原有 subprocess ResourceWarning，测试最终结果仍为 OK；该警告没有作为失败屏蔽或删改测试。

已保存的同源对照包括完整事实表（只排除 root、translation_units 等明确的路径/构建元数据）、规范化全量证据摘要、SQLite 迁移逐表逐行一致性、ECAT SP 影响选择和 TIM4 复核包证据。独立全量与差异缓存复扫的完整摘要也作相等比较。

真实串口工程还执行了默认命令、差异复扫、status 和 report。report 按既有协议原子重建 SQLite 的 findings/复核视图，因此不要求整个 facts.db 的二进制哈希相同；facts.json 保持逐字节不变，并逐表逐行验证 SQLite 中的全部静态事实与该 JSON 一致，PRAGMA integrity_check 通过。旧数据迁移本身仍要求所有文件（包括 facts.db）逐字节哈希一致，两种验收约束不混淆。

真实 Windows ACL 拒写测试使用独立的测试目录，结束后恢复 ACL；正确返回 code 3 并给出完整工作区路径和 custom_dir 配置方法。迁移中断/磁盘失败还有受控故障注入测试，两者不混为一类证据。

## 性能与空间

机器记录包含首次/重复全量、首次/缓存差异、worktree 数量、构建字节数、facts JSON/SQLite 大小和报告大小。小夹具观测不能外推为大型 STM32 性能保证；并行执行回归和构建也会影响耗时。新增编译器/LibClang 二进制与环境完整性校验有实际成本，应与纯目录迁移成本区分。

同一提交的工作树和有效基准检查点复用；不重复复制固件仓库。迁移为一次性复制旧历史，保留原件导致相应额外占用。开发验收使用的新夹具目录单独留证，不属于日常重复扫描自动创建重复工程。

原真实工程迁移前的 `.ecra` 为 3,624 个文件、2,161,350,556 字节。逐文件哈希审计确认原文件集合和内容没有变化，原 HEAD、Git 状态及索引 SHA-256 均不变。最终工作区路径见机器结果；旧文件不删除，不自动清理引用中的历史。

## 使用与验收边界

修改 semantics.yaml 的 project.root 后，正常执行：

```powershell
py -3.10 run_ecra.py
py -3.10 run_ecra.py --scan-mode diff
py -3.10 run_ecra.py status
py -3.10 run_ecra.py report
```

默认会输出工程独立的 `workspace/projects/<名称_摘要>/results/index.html` 和 facts.db。review/review-failed 使用相同解析层和项目锁；不会写回旧固件报告目录。

未连接目标板，不声称硬件时序验收。真实模型复核与模型提供商连接不在本轮无复核扫描中执行；原有模拟协议/收据/失败恢复测试与实际模型测试分别统计。用户报错所述 D: 盘 HX_MFX_PRJ 工程不在当前机器，不能将其他真实 STM32 工程的结果冒充该特定工程通过。

## 最终实测记录

静态引擎指纹：`ced093b7e00328e533e38d4166f4e6eb11cc3f82849ec452ea39d9f9a6121378`。全部 ecra 模块在最后回归期间保持同一内容；解压后 Portable 的对应源码也逐文件相同。

H743/CMSIS 完成 7 轮；真实 STM32 CDC 完成 7 轮。两者均包含全量、首次/缓存差异、头文件、NVIC 和独立全量对照，分类/语义不一致为 0。

独占性能测量在其余验收进程结束后执行，使用同一 ARM/Git/ECAT SP 小工程和相同工具链。秒数包含命令及完整事实/摘要读取；空间为逻辑字节数，硬链接历史不等于重复物理占用。

| 阶段 | 旧版秒 | 新版秒 | 旧/新构建字节 | 旧/新报告字节 |
|---|---:|---:|---:|---:|
| 首次全量 | 4.765 | 11.016 | 101,508 / 102,178 | 197,342 / 201,078 |
| 重复全量 | 3.875 | 7.031 | 92,408 / 93,078 | 197,258 / 200,994 |
| 首次差异 | 10.391 | 18.891 | 196,436 / 298,704 | 245,546 / 247,007 |
| 缓存差异 | 5.750 | 15.594 | 196,457 / 280,212 | 245,545 / 246,923 |

新版差异首次/缓存复扫：受管源码工作树 2 → 2；Git 总登记 4 → 4（包括为保留历史而未删除的旧版工作树和原工作区）。缓存复扫 TU 命中 1/1，重新提取 0。

新版缓存差异后，项目工作区逻辑量 9,896,823 字节，历史逻辑量 5,741,748 字节；facts.json 111,087、facts.db 307,200 字节。旧历史保留与新输入门禁会增加占用和耗时；不以删除历史或关闭校验来掩盖成本，也不把小工程结果外推为大型工程性能保证。

实际串口工程结果：

```text
H:/global_static_concurrency_design/workspace/projects/serial_-_opencode_0449959e93b3e63a3025/results/
  index.html
  facts.json
  facts.db
```

Portable 成品：`H:\global_static_concurrency_design\workspace\acceptance\ECRA-Portable-release2-verified.zip`；522,952,176 字节；SHA-256 `29b4791357da89ad59544e95411309bf048886c58bcabf87ab0f7265d26fb715`。已验证跨盘符、中文路径、包内 Git/ARM/CMake、保存命令、目标闭包、响应文件及 Patch 独立应用；没有把 workspace 打入包。

补充输入门禁使用真实 Git 用例先复现旧行为，再验证拒绝原工作区绝对兄弟目录输入。该限制及可执行修复方式见工作区迁移文档；没有静默忽略输入或缩小 Clang 排查范围。
