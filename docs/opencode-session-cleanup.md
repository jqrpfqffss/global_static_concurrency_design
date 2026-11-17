# OpenCode 复核会话清理

在 Studio 的“工程配置 → OpenCode复核”中启用“归档后清理 OpenCode 会话”，或在 `config/semantics.yaml` 设置：

```yaml
review:
  session_cleanup:
    enabled: true
```

默认关闭，仅接受 YAML 布尔值。正常复核直接执行配置的 OpenCode run，不查询版本，也不依赖清理接口能力。版本字段为空或任意文本不影响复核和会话归属判断。

未设置 `OPENCODE_DB` 或值为空时，实际 run 在扫描目录的 `opencode/` 下创建本轮独立会话库。显式设置时沿用指定路径。基础准备不打开或比对数据库结构，不建立探测库。新库身份待绑定，实际 run 创建后再绑定；无法确认时保留会话。只有可靠归档后按需清理才使用 `db path` 和 `PRAGMA database_list` 核对维护服务所用的库。

ECRA 为每次调用复制子进程环境。配置、日志、缓存、维护进程的工作目录和输出留在 `workspace`。显式指定外部库时，SQLite 在数据库旁管理所需的伴随文件。开启清理后，账本绑定实际库的路径和文件身份，并登记复核请求、变量、阶段和调用序号。Session ID 取自对应进程的 JSONL 事件。事件缺失、冲突或身份不完整时保留该会话。

变量结论、收据和原始输出可靠归档后，清理队列才处理该变量。清理核对 OpenCode 程序、会话库、调用身份、归档哈希和进程退出状态。若查询到子会话，会保留整棵树并记录原因。清理范围限于已归档的当前调用。自动压缩和强制 WAL 写回仅用于 ECRA 创建的默认独立库。

清理失败时已归档结论保持 `DONE`，其他变量继续复核。用「继续复核剩余项」或 `review-resume` 会按账本绑定的原库和归档补偿清理，即使已无变量待复核。`OPENCODE_DB` 的新配置仅用于新调用。技术失败保留会话和原件，可以用 `review-failed` 重试。清理状态位于扫描目录的 `opencode-session-cleanup/`。Studio 和导出报告使用 `workspace` 内的 ECRA 归档。

## 接口与验证

已核对 [OpenCode 1.18.35 的 run 源码](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/cli/cmd/run.ts)、[存储路径实现](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/database/database.ts)、[会话 API 声明](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/server/routes/instance/httpapi/groups/session.ts)和[递归删除实现](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/session/session.ts)。该版本普通 `run` 通过进程内服务新建会话；`--attach` 则连接指定的服务，`--session` 和 `--continue` 会复用会话。普通进程仍可能共用默认磁盘库。ECRA 清理不使用这些复用选项。维护服务由 ECRA 启动并绑定本机随机回环端口；验证健康状态及公开的 API 后查询身份、状态和子会话，再删除和复查。

```powershell
py -3.10 -m pytest -q tests/test_review_session_cleanup.py
$env:ECRA_TEST_OPENCODE_EXE = 'C:\path\to\opencode.exe'
py -3.10 -m pytest -q -s tests/test_review_session_cleanup_live.py
```

真实运行使用临时配置、测试专用会话库和本地模型响应。测试检查实际 DELETE 请求和对应的已归档 Session ID、历史会话及消息、独立库压缩前后的磁盘占用，并通过 Studio 重新读取归档。共享库测试覆盖含中文和空格的外部路径、三变量并行、清理开关、启动失败重试和暂停后继续。

以下为历史测试记录，不是当前企业版验收。Windows 10 x64（19044）实测：3 个 Worker、4 个变量均已归档，精确删除 4 个会话，保留 1 个独立手动测试会话；OpenCode 库及 WAL 的 NTFS 分配由 5,455,872 字节降至 282,624 字节。用 ECRA Portable 内置 Python 重复测试，实际分配由 5,910,528 字节降至 282,624 字节。两次重新启动 Studio 后，归档答复和原始文件接口均通过读取校验。

## 维护启动诊断与任务失败

`review.maintenance_timeout_seconds` 默认 60 秒，分别约束每条本地维护命令和
回环维护服务的就绪等待；模型调用仍使用 `review.timeout_seconds`。Studio 的
OpenCode 高级选项可编辑该值。等待每 50ms 检查任务停止信号，超时/暂停关闭
当前调用的 Windows Job（或 POSIX 进程组），不按进程名称结束其他会话。

维护输出和 `invocation.json` 在临时目录释放前写入当前工具 workspace：
基础初始化不启动维护。归档后清理位于
`opencode-session-cleanup/<运行ID>/maintenance-logs/`。记录包含阶段、参数数组、
原生程序及摘要、PID、cwd、数据库、预算、首个输出时间、结束时间和退出码。
不记录环境变量；日志会隐藏继承的密钥、认证值及代理 URL 凭据。

必要初始化失败只产生任务级错误“OpenCode 初始化失败，复核尚未启动”，详情在
`review/initialization-error.json`。未调用模型的项保持 PENDING，已有 DONE 归档
保留；使用“继续复核”恢复。历史 launch/TECH_FAILED 仍支持“仅重试失败项”；
若该重试又在初始化阶段失败，其 PENDING 队列保留失败重试标识。

所有入口均不执行版本查询、help 或临时库探测。恢复只核对已有账本、归档和库身份，不要求旧能力缓存。维护层不会发起或重试模型请求，正式复核仍沿用原有的请求重试策略。
外部 `OPENCODE_DB` 继续按用户设置使用，禁止对共享库自动 VACUUM、强制 checkpoint
或删除数据库。可选清理失败保留会话、具体原因及已成功归档的答案。
