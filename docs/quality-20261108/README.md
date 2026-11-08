# ECRA 全流程质量检查（2026-11-08）

本记录持续更新，未完成项不能视为验收通过。原始运行证据位于工具工作区 `output/quality-20261108/`，浏览器截图位于 `output/playwright/quality-20261108/`；历史验收仅作线索，不继承为本次实际通过。

后续授权：2026-11-08，用户明确要求将当前修改推送远程分支，目标为 `origin/optimize_ccc`。下文及冻结收据中的“未提交/未推送”保留其验收时点事实；本次提交推送见 Git 历史。此授权不表示完整交付门禁已通过，不上传本地便携 ZIP、运行数据或原始私有会话文件。

最新状态见[最终 V9 验收](continuation-final-v9.md)。全部已确认修复已在本地主区，engine2b9e875…；主区55项相关回归、V9正式离线构建/实际解压运行、最终确认入口与原生Diff结果阅读均完成。三个独立真实STM32工程、固定提交cold/warm与真实C+ASM工作字节整轮保留各自实际版本证据。大型INAV尚在单次正式发布，未计通过。原1646整套保留3个等待失败/各自清理错误和2联网跳过，不能写成最终版本全套通过。下列首轮和旧候选只属于其真实冻结版本。

## 执行计划

1. 核实当前源码、运行环境、启动入口和交付边界，建立功能矩阵及隔离基线。
2. 按分析与证据、任务与持久化、实际用户界面、便携交付四个职责排查；先复现，再修复共同根因。
3. 复验已修问题和相邻入口，运行有针对性的语义及数据契约回归，并走通真实浏览器流程。
4. 在现有获准资产上验证独立真实工程，检查解压交付、中文空格路径和依赖边界。
5. 汇总证据、未验证项和使用方式；不推送、合并或发布。

## 初始基线

- 仓库：`H:/global_static_concurrency_design`；分支 `optimize_ccc`；提交 `fe27afe73596d98e1a21e3f28a2125d38d7272d0`。执行前 `git status --porcelain=v1` 为空。未发现仓库内 AGENTS.md；遵循用户提供的 Direct Codex Execution 指令，不调用外部编码代理。
- 本机：Windows 10 build 19044 x64；`py -3.10` 为 CPython 3.10.11；libclang 18.1.1、PyYAML 6.0.3、FastAPI 0.136.3、uvicorn 0.49.0；SQLite 3.40.1。PATH 上的 `python` 来自 MSYS2，因此开发验证明确使用 `py -3.10`。
- 正式交互入口：`ECRA.cmd`（无参数启动 Studio）或 `py -3.10 run_ecra.py ui`；本地 `127.0.0.1` 服务，动态端口和会话凭据；Vue 构建产物由 Python 服务提供。CLI `run/init/doctor/review/review-failed/report/status` 仍存在。`--legacy-output` 是离线 HTML 的显式兼容入口，不能替代 Studio 检查。
- 当前源码命令帮助原文：`output/quality-20261108/cli-help.txt` 和 `ui-help.txt`。README 中的 `--profile` 示例不出现在该 CLI 帮助中，待核对调用分派及实际行为。
- 默认数据根为 Windows `%LOCALAPPDATA%/ECRAStudio/data`，支持 `ECRA_DATA_ROOT`/Studio `--data-root`；测试显式使用隔离数据根。原用户库、确认记录、既有 dist、历史报告不直接修改。
- 扫描基于真实编译数据库与 libclang，canonical SQLite 保存事实/报告/归档源码；AI 复核有独立任务账本，人工确认有独立事件存储。当前界面使用有效 AI 结论只读投影，静态、AI 和人工来源分开。
- Python 包声明 >=3.10；Portable 配置当前固定 Python 3.10.9 / CMake 3.29.6 / Ninja 1.13.2 / Arm GCC 10.3.1，OpenCode 是可选外部安装。README 中仍出现 3.12.10 打包说明，属于需复核的文档矛盾。
- 当前产品自己声明完整重构及发布门禁未全部通过，不能将历史包验收、已有大工程归档或本轮自动测试等同于完整交付。

## 记录索引

- [功能覆盖矩阵](matrix.md)
- [问题、修复与复验](issues.md)
- [分析、证据与AI聚合](analysis.md)
- [任务、恢复与人工持久化](state.md)
- [实际界面与真实扫描流程](ui.md)、[独立浏览器检查](independent-ui.md)
- [便携交付与独立真实工程](delivery.md)
- [兼容HTML实际离线检查](legacy.md)
- [最终验证与明确限制](validation.md)
- [封包后的最终收据与候选ZIP](postflight.md)
- [续轮执行与引擎冻结](continuation.md)、[真实完整构建](continuation-build.md)、[完整回归进度](continuation-regression.md)、[真实差异与缓存](continuation-diff.md)、[报告失败界面恢复](continuation-q108-ui.md)
- [最终 V9 正式便携包](continuation-offline-build-v9.md)、[确认时保持对象身份 Q405](q405-v9.md)、[最终包原生Diff阅读](continuation-native-diff-ui-v9.md)、[最终关键截图和SHA](evidence/final-v9-ui/index.md)

## 本轮结论与继续使用

已修复当前确认的严重误安全、AI证据不足掩盖静态冲突、坏任务阻断启动、失败终态/日志读取、相对toolchain、新配置标准头及外置配置命令、填写区按钮和错误提示等问题；完整台账和证据见上。

源码：安装 `requirements-studio.txt` 后运行 `py -3.10 run_ecra.py ui`；当前便携候选为 [V9 ZIP](H:/ECRA-quality-20261108-offline-build-v9/ECRA-Portable.zip)，解压后双击 `ECRA.cmd`。旧 `dist/` 不是本轮产物。工程配置→确认真实构建→开始扫描；结果从项目概览/变量与风险查看，人工确认保存后可关闭浏览器，下次用同一数据根从历史批次/继续人工确认进入。后台窗口关闭会结束服务，下一次从启动器重新打开。CLI外置配置后续命令始终保留 `--config <文件>`。

Q201改变静态引擎，旧报告继续作为历史保留，但需重新扫描才能采用保护修复；单独刷新旧报告不能验证新引擎。静态、AI、人工记录独立，不自动删除旧人工结论。

本轮不宣称完整发布门禁通过：大型INAV正常full正式发布/性能尚未完成，该规模Diff/恢复、新联网OpenCode推理、干净离线物理电脑、32GB物理机、原生缩放及当前legacy file视觉仍有缺口。真实工程仍有PARTIAL/UNKNOWN与待复核项，详见各记录。没有推送、合并、发布、覆盖原dist或修改真实客户确认。
