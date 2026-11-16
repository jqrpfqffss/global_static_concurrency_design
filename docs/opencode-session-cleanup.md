# OpenCode 复核会话清理

在 Studio 的“工程配置 → OpenCode复核”中启用“归档后清理 OpenCode 会话”，或在 `config/semantics.yaml` 设置：

```yaml
review:
  session_cleanup:
    enabled: true
```

默认关闭。仅接受 YAML 布尔值。当前支持 ECRA 实际调用的原生 OpenCode 1.18.35（含 ECRA 能解析到原生 exe 的 Windows npm 启动入口）。其他版本、带额外参数的启动命令、或无法验证的环境继续原有复核并保留会话；不会切换到另一套 OpenCode 或清理默认会话库。

一轮任务使用自己创建的独立会话库，保留原有工作目录、提供商认证、模型、提示词和复核工具权限。每次实际调用有独立登记，含扫描、复核请求、变量、阶段和调用序号。Session ID 只从对应进程的 JSONL 事件获得；事件缺失、冲突或身份不完整时保留该会话。技术重试和格式、语言、摘要、事实挑战阶段都按实际调用登记。

变量结论通过原有验证、原始输出和收据进入归档、SQLite 完成单变量提交后，独立清理队列才会处理该变量。清理验证同一个 OpenCode 程序、会话库、会话身份、原始日志和进程终止状态。若查询到子会话，会保留整棵树。默认库、其他任务的库、缓存命中和显式重新复核的历史会话不在清理范围。各次调用结束后，ECRA 通过 OpenCode 官方 `db` 命令压缩自己的库并写回 WAL，释放已删除会话占用的空闲页。

清理失败不改变 `DONE`。停止后，“继续复核剩余项”或同一配置的 `review-resume` 会重新核对仍与已归档结果相符的归属记录并补偿清理，即使已无变量待复核。技术失败保留其会话和原件，仍用 `review-failed` 重试分析。无法证明归属的旧记录会保留。清理状态与独立会话库位于扫描目录的 `opencode-session-cleanup/`，不会作为不可变证据打包。Studio 和导出的报告继续使用 ECRA 自己的归档，人工确认及已有完整性校验不受影响。

## 接口与验证

已核对 [OpenCode 1.18.35 的 run 源码](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/cli/cmd/run.ts)、[存储路径实现](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/database/database.ts)、[会话 API 声明](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/server/routes/instance/httpapi/groups/session.ts)和[递归删除实现](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/session/session.ts)。该版本普通 `run` 通过进程内服务新建会话；`--attach` 则连接指定的服务，`--session` 和 `--continue` 会复用会话。普通进程仍可能共用默认磁盘库。ECRA 清理不使用这些复用选项。维护服务由 ECRA 启动并绑定本机随机回环端口；验证版本及公开的 API 后查询身份、状态和子会话，再删除和复查。

```powershell
py -3.10 -m pytest -q tests/test_review_session_cleanup.py
$env:ECRA_TEST_OPENCODE_EXE = 'C:\path\to\opencode.exe'
py -3.10 -m pytest -q -s tests/test_review_session_cleanup_live.py
```

真实运行用临时配置、临时会话库和本地测试模型响应：检查实际 DELETE 请求的精确集合，确认独立测试会话未变，比较压缩前后的文件分配字节，并重新通过 Studio 读取归档。无需真实 API 凭据，也不会打开用户已有的会话库。

Windows 10 x64（19044）实测：3 个 Worker、4 个变量均已归档，精确删除 4 个会话，保留 1 个独立手动测试会话；OpenCode 库及 WAL 的 NTFS 分配由 5,455,872 字节降至 282,624 字节。用 ECRA Portable 内置 Python 重复测试，实际分配由 5,910,528 字节降至 282,624 字节。两次重新启动 Studio 后，归档答复和原始文件接口均通过读取校验。
