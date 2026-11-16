# ECRA 工具数据目录

将源码仓库或完整便携包放在非 C 盘的可写目录。双击 `ECRA.cmd` 打开 Studio。命令行可从其他目录运行 `py -3.10 D:/ECRA/run_ecra.py run --config D:/ECRA/config/semantics.yaml`。便携包自带嵌入式 Python，直接在解压目录运行。启动窗口显示工具根、数据根和回环浏览器地址。Studio 的“设置与验收状态 → 工具数据目录”可查看和打开当前目录。

默认数据根是实际工具目录的 `workspace/`。扫描及数据库位于 `scans/`，项目配置和专用构建位于 `projects/`，任务、临时上传和日志保存在归属明确的工作目录中。报告包、人工确认增量和诊断 ZIP 保存到当前数据根的 `exports/`，可从 Studio 打开所在目录。工具级的启动偏好、配置编辑、暂存、迁移收据和 OpenCode 凭据副本在 `workspace/.ecra/`。Git 与 CMake 的 Windows Junction 别名在 `workspace/a/`。

旧 YAML 中的 `location: user` 和 `output_dir: .ecra` 继续使用工具数据目录。主动选择其他数据根时，`--data-root`、`ECRA_DATA_ROOT` 和 `analysis.output.custom_dir` 仅接受当前工具的 `workspace` 或 `workspace/data-roots/` 下的绝对路径。清除指向旧目录的启动覆盖后再使用迁移功能。需要通过 `--config` 或 `ECRA_CONFIG_HOME` 读取原工程配置时，配置可留在原位置。Studio 的案例和背景编辑及 CLI 的默认 `init` 保存到工具工作区。

工具在 C 盘时，移动整个目录后再启动。若窗口提示 Junction、路径长度或编码限制，优先使用类似 `D:\ECRA` 的非 C 盘短英文目录。Windows 工具链在部分中文、空格或深路径下需要 8.3 短名称，或需要工具内有足够短的英文别名路径。不可写、磁盘已满或活动目录损坏时，应按错误中显示的实际路径处理。

## 迁移旧 Studio 数据

1. 退出旧版 Studio，等所有旧扫描、复核、导入和整理任务停止。保留旧数据和现有数据库伴随文件。
2. 在新版 Studio 打开“设置与验收状态”，切换到“整套迁移与恢复”标签页。选择旧的 `ECRAStudio` 目录或实际含有 `scans`、`projects`、`settings` 的数据根。常见旧路径为 `%LOCALAPPDATA%\ECRAStudio\data`。
3. 确认来源已停止写入。目标使用工具下的新空目录，例如 `workspace/data-roots/legacy`。检查复制计划，再开始。校验、迁移日志和中间文件均位于新版工具。迁移复制 SQLite 主库及现存 WAL 等文件，并在目标副本中校验数据库、结果绑定、归档和人工历史。来源在复制期间变化时会中止。
4. 完成后选择新副本作为启动数据目录并保存，退出后重开。核对工程列表、历史扫描、复核队列和人工确认。迁移中断且存在收据时，使用“重新校验并恢复复制”继续。目标已有数据时选择新的空目录。
5. 界面显示校验完成的源路径与已复制文件的逻辑字节数。核对新副本后，通过文件资源管理器手动清理界面列出的那个旧数据目录。若旧副本仍需保留，其磁盘占用也会继续保留。清理范围仅限已验证的旧 ECRA 数据目录。

## 移动、升级与复核

关闭 ECRA 后移动或升级整套工具时，保留完整的 `workspace/`，包括隐藏的 `.ecra/` 和 `data-roots/`。升级到另一份干净包时，先完全解压新版，再把旧 `workspace/` 放入新版工具根目录。扫描的历史路径和摘要是档案的一部分。工具移动后会重新建立 CMake 构建和 Git 工作树。若活动配置仍引用旧构建生成的编译数据库，重新导出当前数据库或用工作区构建重新生成。

搬迁后的已发布扫描可读取历史结果。对通过原扫描库、归档和检查点校验的结果，复核续跑使用归档证据。需要验证移动后固件的最新状态时，发起新扫描。没有提交静态检查点的构建或扫描需要重新检查输入。

自动复核使用已验证的原生 OpenCode 1.18.35。未设置 `OPENCODE_DB` 或值为空时，ECRA 在当前 `workspace` 内为本轮复核创建独立会话库。设置为本地数据库的绝对路径时，预检查、复核和清理都使用该文件，允许路径位于 `workspace` 外并包含中文或空格。外部路径的写入范围限于数据库及其 SQLite 伴随文件。任务日志会显示实际确认的数据库路径。

ECRA 只读获取现有 OpenCode 模型、提供商配置和 `auth.json`，兼容模型 API 环境变量。复核归档、配置及登录副本、缓存、日志和临时目录都保存在 `workspace`。外部插件及用户配置中的 MCP 程序不参与自动复核。数据库路径、权限、锁或版本问题会记录为技术失败，处理后可以重试。共享时使用 Studio 导出的结果包，整套工作区可能含提供商凭据。 [OpenCode 会话清理](opencode-session-cleanup.md)

若旧版因外部会话库启动失败，保留 `OPENCODE_DB`，退出 ECRA 后用新版重新启动。在原扫描的「OpenCode 复核」页点「仅重试技术失败」，或运行 `.\ECRA.cmd review-failed --config <原配置路径>`。源码更新后使用新源码中的启动器。便携版需要从更新后的源码重新执行 `build_portable.ps1 -OutputDir <新的输出目录>`，核对生成包的 `VERSION.txt` 包含修复提交，再按上述升级步骤使用新版解压目录中的 `ECRA.cmd`。

## 复现 Windows 落盘验收

用 Process Monitor 开启 File System 和 Process/Thread 事件。以 `ECRA.cmd` 或 `run_ecra.py` 的进程为根纳入所有子进程。记录启动、实际全量构建/扫描、固定提交差异、OpenCode 并行复核及清理、停止和重试、只读旧数据迁移、导入导出和故障退出。检查 `WriteFile`、创建和覆盖文件、改名、删除和新增目录事件的真实物理路径。检查旧 ECRAStudio、AppData、Downloads 及 TEMP，并记录命令、OpenCode 版本、事件数量和收据位置。对于迁移，另外对旧源目录做前后文件清单及摘要核对。Windows 11 干净机器与真实模型登录的验收，使用目标机的实际 Python、工具链和提供商配置执行。
