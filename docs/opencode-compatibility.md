# OpenCode 集成与兼容边界

ECRA 的版本号解析、启动入口、存储、模型事件和会话删除分别验证。版本探测成功不代表授权有效，也不代表可以删除会话。当前实现使用 `local-jsonl-v1` 适配器；没有把固定版本门槛换成另一个固定版本。

## 配置与入口

CLI、Studio 工程配置、Portable 均使用 `review.*`。旧配置无需新增字段。`review.command` 始终是参数数组，第一项为实际入口；后续项保持完整前缀。自动发现使用 PATH，解析后的完整入口显示在复核日志和能力报告中。不会通过 npm/企业脚本旁的二进制替换用户入口。

支持原生程序、显式 `[node.exe, 入口脚本]`、Windows `.cmd/.bat/.ps1`。批处理使用关闭延迟展开的受控 cmd，参数经环境槽传递，覆盖中文、空格、`& | < > ^ % !`、空值和末尾反斜杠。任意批处理不能可靠转发内嵌双引号/换行，因此明确拒绝这类参数；应使用直接 Node 或正式 PowerShell 入口。优先 PowerShell 7；Windows PowerShell 5 的空值/引号转发也明确受限。复核提示词统一使用 stdin，不拼进 shell 代码。任意自定义脚本仍需实际协议验证，参数单测不代表其完整行为已验证。

所有启动均纳入本次 Job Object，仍在执行前挂入 Job。停止只回收本次进程树，不按名称终止其他 OpenCode。外部服务不能借 CLI 的 Job 获得归属。主版本 2 或声明后台服务的运行模型目前标记为“归属尚未验证”，不启动用户库命令；这不是断言该发行版本身不支持此能力。

## 授权输入与写入位置

版本/协议预检、正式复核、清理和恢复共享准备好的配置 scope、认证数据位置及环境继承规则。临时 cwd 可各自不同。维护预检不再清空所有 `OPENCODE_*` 或丢弃准备好的认证副本。

默认从实际 USERPROFILE/HOME、XDG 配置、OPENCODE_CONFIG、OPENCODE_CONFIG_DIR、OPENCODE_CONFIG_CONTENT 读取模型设置。只导入 provider/model/small_model/enabled_providers/disabled_providers；不自动加载项目 MCP、命令或外部插件。代理和 provider 凭据环境保留；已知写入路径、服务连接和权限覆盖变量由 ECRA 重建。默认不强制 pure，也不无条件禁用内置认证插件。

可选高级配置：

```yaml
review:
  command: [opencode]
  maintenance_timeout_seconds: 60
  runtime:
    auth_file: /absolute/path/to/standard/auth.json
    config_file: /absolute/path/to/model-config.json
    auth_plugins: []
  # finding_ids: [真实候选项ID1, 真实候选项ID2]
  session_cleanup:
    enabled: false
```

`auth_file` 仅适用于标准 OpenCode auth.json；不是企业域登录文件的通用替代。文件只读导入 workspace 中按来源区分的持久认证位置；源摘要未变时保留工具侧 OAuth 刷新，不在每个 Worker 重新复制。`auth_plugins` 只应列出发行版正式支持、明确授权的认证插件，其缓存/运行行为仍须实测。没有复制整个用户目录，也没有改写系统或用户环境。

ECRA 产物和托管 OpenCode 写入跟随实际工具根目录的 workspace。显式 OPENCODE_DB 保持原路径，可位于工作区外。不会偷偷换库、删除历史库、改迁移记录，或对共享库执行 VACUUM/checkpoint。标准 auth.json 是否包含企业域凭据不能靠推测；不能满足合法认证及写入隔离的发行版必须保留为未验证状态。

维护与正式调用的临时 cwd 使用工具 workspace 下的短专用目录，诊断仍按原扫描/运行归档。Windows CreateProcess 的 cwd 长度限制与文件 API 的长路径能力不同；此分离避免 Portable 深层清理恢复返回 WinError 267。它不改变数据库绑定或认证 scope。

## 检查、存储和能力状态

`run_ecra.py opencode-check --json` 和 Studio 复核配置中的“检查 OpenCode（不调用模型）”使用同一检查函数。该检查只启动版本、帮助、测试库命令；现有共享库仅做只读结构比对。不会发起模型请求。

先在独立 HOME/XDG/APPDATA/数据库的测试目录验证参数与真实主库路径，默认数据目录也同时隔离。再比较测试库和共享库的完整 schema/迁移身份。比较不一致时保留共享库并阻止正式调用，不自动迁移。共享库正式调用前还会重检结构。相同 schema 的兼容判断仍有外部进程在检查与打开之间改变数据库的固有竞争窗口；ECRA 不声称能够锁定其他软件的运行行为。

版本解析接受纯版本、v/产品/Version 前缀、已知 xOpenCode banner、企业后缀、ANSI、BOM 和 stderr；冲突版本、登录提示、非零退出、不退出均不能算成功。路径、完整 JSON 文档、JSONL 和服务启动信息使用各自解析规则。不从混杂输出截取第一个 JSON。用于身份判断的数据必须为有效 UTF-8。诊断可容错显示并脱敏。

能力报告为 `review/opencode-capabilities.json`。`AWAITING_FIRST_RUN` 表示尚需实际模型调用验证事件及完成状态；首次真实输出必须具有唯一会话身份和完成的最终 step_finish，结构化错误不会作为结论。清理另查受控回环服务的认证、版本、接口、会话标题/目录/项目/父子关系、调用归属和已提交归档。清理失败只保留会话，不覆盖 DONE 结论。

没有跨任务永久信任缓存。任务内探测绑定入口/脚本/二进制内容、配置和授权环境；发生变化重新核验。身份缓存不是授权长期有效证明。未知版本可以进入测试库探测，但不会仅因能打印版本获得全部能力。

## 队列、诊断和恢复

初始化失败保持未派发项 PENDING、已完成项 DONE，记录模型调用为 0。实际调用后的认证/公共配置/明确额度耗尽故障停止后续派发；已发生调用不能算 0。每项结果先归档，再调度清理。可选 `review.finding_ids` 定义真实候选批次，其他候选保持原状；批次完成不等于整个工程完成。

公共故障会将本次基础复核标记为 BLOCKED_COMMON_FAILURE，并在 Studio 显示具体故障；认证或存储错误另更新对应能力。重试成功完成初始化后清除旧公共故障提示。命令参数中的常见凭据标记在进度、调用收据、模型配置摘要和超时诊断中脱敏。

版本或维护阶段出现已知完整域账号提示会立即结束本次启动，不等待完整预算。诊断记录入口、实际文件摘要、产品版本、适配器、有限目录环境、首输出、自然退出和回收前后状态；回收后的退出码不代表命令成功。文件位于运行目录的 `maintenance-logs`，原始认证内容、密钥和代理凭据不写入诊断。

静态引擎仍逐文件校验。本次仅对精确的 review 配置/CLI 变更建立兼容映射，并保留既有合法复核收据的输入身份；未删除静态指纹或源码闭包校验。

## 验证方法与限制

- A：`tests/test_opencode_protocol.py`、维护/归档/队列异常测试，明确使用模拟协议。
- B：设置 `ECRA_TEST_OPENCODE_EXE` 后执行 `tests/test_review_session_cleanup_live.py`，真实 CLI、测试专用库及本地模型服务，检查历史会话/消息前后不变。
- C：`scripts/validate_opencode_project.py` 必须显式指定实际 exe、model、工具根目录、Python、真实扫描检查点及共享库（如使用）。该入口经过正式 Studio 任务、输入验证和归档路径，不替换模型返回。
- `scripts/validate_opencode_ui.py` 仅验证真实浏览器、读取和无模型预检，不能当成 C。
- Portable 自检仍明确记录 OpenCode 模型验收 NOT_TESTED；应对最终包另外执行真实项目验收。

官方 1.18.35 与 1.19.5 的本次 Windows B 层结果、xOpenCode 缺失资源及模型额度阻塞见[本机报告](opencode-windows-acceptance-20261117.md)。本次没有现场 xOpenCode 文件/凭据路径证据，不能宣称已经找到或消除了企业域登录的具体触发项。

源码核对依据：[官方 1.19.5 的本地 run 实现](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/run.ts)、[全局目录解析](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/global.ts)、[数据库打开与迁移](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/database/database.ts)。这些源码不等同于企业定制版的实现证明。
