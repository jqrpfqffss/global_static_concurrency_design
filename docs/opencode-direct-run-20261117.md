# OpenCode 直接运行修复与 Windows 验证（2026-11-17）

当前结论：代码修复和相关回归已完成；企业版真实模型验收未完成。当前机器缺少指定的企业程序、会话库和原始维护诊断目录。未查询 OpenCode 版本，未安装或使用官方替代程序冒充企业版验收，未创建替代历史库。

## 代码与范围

仓库 `H:/global_static_concurrency_design`，分支 `optimize_ccc`，基准 HEAD `5a277b760696759620b256a1a894023fef24d32d`。开始时工作区干净。修改直接由 Codex 实施，没有调用外部编码代理。修改保留在工作区，未提交或推送。

静态引擎摘要仍为 `907d802c427ea267219b984409a57b35d2cd678a34138958295304d76472dc9d`。静态算法、模型提示词、答案契约及人工确认语义未改动。本次确切的复核实现摘要映射到原有收据身份；对未来答案契约改动仍正常失效。

| 文件 | 最终行为 |
|---|---|
| `ecra/review.py` | 初始化只准备本地上下文，下一次外部调用是实际 run；进度显示版本未查询；记录运行诊断和输出校验阶段 |
| `ecra/opencode_storage.py` | prepare 不调用维护；删除调用前 schema 检查；保留当前用户登录环境，运行/维护共用配置及认证数据；数据库身份只服务于可选清理 |
| `ecra/review_opencode_sessions.py` | 删除 Runtime.probe、版本解析调用、help、临时 protocol.db、schema/迁移匹配和主版本限制；健康接口只要求 healthy=true，删除不再比较 session.version |
| `ecra/opencode_protocol.py` | 删除版本文本解析器和版本错误类别，保留实际 JSON/JSONL、完成事件、认证提示和脱敏校验 |
| `ecra/review_session_cleanup.py` | 新库先记录待绑定，实际 run 创建后绑定；未知身份恢复不自动认领；归档、真实 ID、调用、文件身份、目录/项目、父子会话和进程退出核对继续保留 |
| `ecra/review_process.py` | 实际 run 的认证/非零/超时/取消如实记录；启动次数与未知模型请求数分离；结束响应/提供商 HTTP 错误才记模型请求观察证据；回收失败保留原始超时或取消 |
| `ecra/opencode_check.py` | CLI、Studio、Portable 共用纯本地检查，启动 OpenCode 和模型次数均为 0；ready 不代表认证、模型或清理已验证 |
| `studio/src/ReviewCenter.vue` 与构建资产 | “检查本地启动条件（不运行 OpenCode）”；版本为空显示“未查询”，不禁用继续复核 |
| 配置说明、两份 OpenCode 文档、UI 验证脚本 | 清除旧预检描述，区分页面验证与本地配置是否可用 |

正常启动、继续复核、失败重试、清理开启/关闭均不依赖版本、旧探测结果或能力缓存。没有新增默认预检开关，没有提前发送模型请求。按需维护仍可在可靠归档后调用数据库路径核对及受控回环服务；它不是复核前置条件。清理失败保留 DONE 和会话，不重跑模型；共享库仍禁止自动压缩和强制 checkpoint。

## 回归结果与证据

日志均位于仓库 `workspace/acceptance/`：

| 日志 | 结果 |
|---|---|
| `direct-run-first-tests.log` | 60 passed，9 subtests passed |
| `direct-run-targeted-final.log` | 68 passed，9 subtests passed，259.45 秒 |
| `direct-run-final-process.log` | 12 passed，20.37 秒；包含最终回收故障和进程拥有权验证 |
| `direct-run-cache-resume.log` | 2 passed；能力缓存缺失、原 DONE 字节保留、仅新剩余项进入实际测试进程 |
| `direct-run-archive-regression.log` | 55 passed，75 subtests passed，1 failed，1054.85 秒 |
| `direct-run-resume-diagnostic.log` | 上述失败项单独重跑 1 passed，80.07 秒 |
| `direct-run-resume-capture-recheck.log` | 同组测试收集环境下复跑 1 passed、60 deselected，33.55 秒；扫描输出另存 `direct-run-resume-captured-output.log` |
| `direct-run-frontend-build.log` | vue-tsc 与 Vite build 通过 |

扩大回归中失败的是 `test_first_scan_is_openable_in_studio_during_review`：静态扫描返回 3，而测试期望 0/1/2。独立复跑及同组收集环境复跑均通过，后一次保存了完整扫描输出并完成 10 个合成答复归档；该轮失败日志保留，原因尚未从该测试被丢弃的扫描输出中定位，不能将合并回归写成全绿。其余续跑、技术失败重试、归档完整性、人工确认、精准清理和 native 恢复测试通过。

修改的测试还包括 `tests/test_opencode_protocol.py`、`tests/test_review_session_cleanup.py`、`tests/test_review_session_cleanup_live.py`、`tests/test_runtime_storage.py`，清除了旧版本和探测断言，保留归属和恢复验证。

新增 `tests/test_opencode_direct_run.py` 的入口是测试桩：记录每次 argv，任何版本/help/db/其他预检都会失败，只有 run 返回合成合法答复。它经过正式 review_all、真实 Windows 子进程、解析和归档，覆盖登录提示、非零、超时、无效输出、取消、故障重试以及 CLI/Studio 本地检查。精准删除测试保留真实回环 HTTP 和 ECRA 归档核对。以上均不称为企业模型成功。

早期测试桩因 Windows 默认输出编码以及 Studio 测试客户端参数写错而失败，已经修正；原日志 `direct-run-process-tests.log` 保留，后续完整通过日志另列。首次使用默认 Python 缺 pytest，随后统一使用 Python 3.10。

## 指定工程的当前实机结果

工程：`H:/stm32_RAG/code/serial - opencode`。本轮实际使用源代码正式 CLI，生成新扫描 `923fe7b1782f441b842f5af8ad64291e`，20 TU、58 变量、23 候选。静态扫描成功只说明检查点可用，不作为模型成功。

正式继续复核命令：

```powershell
$env:OPENCODE_DB = 'D:/opencode/opencode.db'
py -3.10 -B run_ecra.py review-resume --data-root H:/global_static_concurrency_design/workspace/data-roots/direct-run-20261117 --config H:/global_static_concurrency_design/workspace/acceptance/direct-run-20261117/review-config.yaml
```

该验证配置沿用工程设置和当前默认模型来源，只将入口明确设为用户指定的 `D:/opencode/opencode.exe` 并启用复核。当前 exe 与 db 都不存在，因此不能计算该程序摘要、派发 run 或验证企业认证。正式入口返回初始化错误“找不到 OpenCode 命令”，真实 CLI 启动 0、真实模型请求 0、成功归档 0、剩余 PENDING 23。没有 protocol.db，也没有本轮维护日志。没有使用历史模型结果填充当前归档。

证据位于 `workspace/acceptance/direct-run-20261117/`：`environment.json`、`source-formal-run.log`、`source-formal-review.log`、`source-result.json`。扫描结果位于 `workspace/data-roots/direct-run-20261117/scans/923fe7b1782f441b842f5af8ad64291e/`，错误记录是其中 `review/initialization-error.json`。

真实 Chrome 页面截图及 API 读取证据位于 `workspace/output/playwright/direct-run-source/`。页面正确显示“版本未查询”、实际缺失命令错误、23 项待复核，继续按钮不因版本为空禁用。UI 验证 passed=true 与本地配置 ready=false 分开记录。

## 最终 Portable

最终目录包：`H:/global_static_concurrency_design/workspace/dr/ECRA-Portable`。本次交付可直接运行的目录包，没有生成 ZIP。

- 补丁标识：`opencode-direct-run-20261117-final`。
- VERSION.txt SHA256：`e47b38033e3454df16bee5d64476ebe02631687ed15dbfb0ad1239bf199db990`。
- Python 模块集合摘要：`52ed47a6c05c8e61b2c9a788abfd8925ff9ed3af80c439779b1e4cb062fb6641`；逐文件记录在包内 `BUILD-IDENTITY.json`，完整文件清单在 `FILES.sha256.json`。
- 实际解释器：`workspace/dr/ECRA-Portable/runtime/python.exe`；实际模块：`workspace/dr/ECRA-Portable/ecra/__init__.py`。包内测试记录 69 个已加载 `ecra.*` 模块，均来自该包。测试框架来自本机 pytest，生产模块没有借用源码 checkout。
- 新包自检：`workspace/dw/acceptance.json`，**PASS，29 项命令检查**。包括 MinGW/Ninja 构建执行、ARM 构建扫描、正式 CMD 入口、缺失 OpenCode 的任务级失败、PENDING 保留、继续复核及搬迁后扫描；不把这些解释为真实模型通过。
- 包内回归：`package-tests.log` 中 52 passed、9 subtests passed、1 failed。失败原因是测试固件嵌套在外层 checkout 时没有独立 Git 边界，触发了正确的工程/数据隔离保护；仅修正测试夹具，保持生产保护。`package-local-check.log` 补测 1 passed，源码同项补测也通过。原失败日志保留，不改写为一次性全绿。
- 初次 build_portable 的深层 `portable-evidence/test-tool` 复制验收失败于既有的短路径保护。保留其日志和失败结果后，直接验证较短的新包本体，使用 `workspace/dw` 验收工作目录，最终 29 项全部通过。装配期间最后补入的唯一生产差异是 `review_process.py` 的回收故障保护；更新清单和包标识后才执行上述最终包自检和包内测试。

该包通过正式 CLI 对指定工程建立新检查点 `735f0d3c587c45d7aa5a21388f8eaf06`，20 TU、58 变量、23 候选。随后从包内 `run_ecra.py review-resume` 使用相同的 `review-config.yaml` 和显式 `OPENCODE_DB=D:/opencode/opencode.db`，在真实入口解析阶段发现指定程序不存在。当前成功模型归档 **0**，剩余 **PENDING 23**；真实 CLI 启动及模型请求均为 0，没有版本/help/协议库探测。

包内工程结果：`workspace/dr/ECRA-Portable/workspace/data-roots/direct-run-project/scans/735f0d3c587c45d7aa5a21388f8eaf06/`。命令日志在本轮证据目录的 `package-project-scan.log`、`package-project-review.log`，汇总见 `package-final-result.json`。

包内真实 Chrome UI 和接口读取通过，位于 `workspace/dr/ECRA-Portable/workspace/output/playwright/direct-run-package/`。其 bootstrap 明确记录包内 Python、模块路径和上述 VERSION 摘要。截图显示版本未查询、缺失入口错误及 23 项待复核。

## 未完成事项

- 指定企业程序与会话库当前不可访问，原诊断目录也不存在；已请求实际路径，尚未取得。
- 企业版实际 run、至少一个真实模型结果解析/归档/页面读取未完成。
- 企业版真实批量、暂停续跑、精准清理及共享历史库不变性尚未实测；合成/进程回归不能替代。
- 企业发行版认证来源和 HOME/APPDATA 的具体读取行为尚无当前实机证据，不能宣称企业登录问题已被实际验证消除。
- 扩大回归存在一次未定位的静态扫描测试失败，独立复跑通过；未运行全仓全部测试。

只有这些当前实机条件和验证都完成后，才能报告全部验收通过。
