# OpenCode Windows 修复与验收记录（2026-11-17）

## 结论及证据边界

**现场企业版故障尚未闭环，跨版本完整验收未通过。** 本轮已实施运行上下文、协议、数据库保护、启动入口、归档恢复和诊断修复。官方 1.18.35、1.19.5 的 Windows 真实 CLI / 本地模拟模型集成测试分别 7 项通过；最终 Portable 的实际 CLI 三 Worker/暂停恢复/清理另有 2 项通过。真实指定工程完成源码和 Portable 两次静态扫描；真实模型补充尝试因账户额度不足失败，成功真实模型归档为 0，不能替代企业版验收。

本机无法访问 `D:/opencode/opencode.exe`、`D:/opencode/opencode.db` 和用户指定的原维护诊断目录。这三处在首次检查时即不存在，未进行替换、创建假库或伪造原始故障复现。用户给出的企业程序 SHA256 `89033a52eb30350f19edd20575e624133b89021dba0e69d87167b3e682c369dd` 仅是历史记录，**本轮未能复算**。已询问资源实际位置及可用合法模型，尚未收到补充。

## 环境与真实工程

| 项目 | 本轮实际值 |
|---|---|
| 系统/用户 | Windows 10 10.0.19044 / AMD64，Administrator |
| 工具根目录 | `H:/global_static_concurrency_design` |
| 分支 / 起始提交 | `optimize_ccc` / `bd5339607e592e0d9ac361b5077d0a3a72c2cc5d` |
| 起始工作区 | 干净；没有回退提交；本轮修改未提交 |
| 源码 Python | `C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe` |
| 工程 | `H:/stm32_RAG/code/serial - opencode`，真实存在 |
| 源码配置 | `config/semantics.yaml`；真实模型补充批次由正式 Studio profile 配置显式选择 5 个真实候选 |
| 数据根目录 | `workspace/data-roots/opencode-compat-20261117` |
| 扫描 ID | `3159158c51c84ca783def7b55ae8e41a` |
| 静态结果 | 20 个 TU；58 个变量；23 个候选/盲区项 |
| scan.db SHA256 | `920b8ac129a87aaf66382fb351b5ca44567e774a32b60c12706f65779a28eadb` |
| 静态引擎前后指纹 | `907d802c427ea267219b984409a57b35d2cd678a34138958295304d76472dc9d`，一致 |

未修改固件业务源码。静态扫描使用正式 native pipeline：

```powershell
py -3.10 -B run_ecra.py run --no-review --scan-mode full `
  --data-root H:/global_static_concurrency_design/workspace/data-roots/opencode-compat-20261117 `
  --config H:/global_static_concurrency_design/config/semantics.yaml
```

最终任务状态为 INCOMPLETE：静态结果有效，模型项未完成。58/23 是本工程实际结果，没有套用此前 1417/468 的记录。

## 根因：已证实与尚未证实

代码核对证实维护调用没有使用已准备的认证数据/scope，又清除了继承的 OPENCODE 环境并重建空用户目录；正式复核却使用另一份数据。现已统一上下文，通过参数观测测试证明维护、运行、清理使用一致的认证与配置来源。还修复了固定版本全输出比较、无条件 pure、只接受单个原生文件入口、全局固定迁移摘要及并行能力报告临时文件竞争。

**这只能证明并修复代码缺陷，不能证明企业域认证具体读取了哪个文件/环境。** 因企业程序、历史库、原始日志缺失，A 普通终端、B 重定向、C Job 启动、D 隔离、E 单因素认证路径对照无法针对指定 exe 执行。不能将标准 auth.json 认定为域登录凭据，也不能声称已消除已复现企业故障的具体触发项。官方 CLI 的测试结果不替代该项。

## 兼容能力矩阵

| 平台/入口/发行版 | 初始化与基础复核 | 存储 | 精准清理 | 实际层级和限制 |
|---|---|---|---|---|
| Windows x64 原生官方 1.18.35 | 真实初始化、JSONL 完成与归档通过 | 测试独立/共享库通过 | 真实 API 删除、历史会话保护通过 | B，7 项；C 补充请求失败 |
| Windows x64 原生官方 1.19.5 | 同一适配器通过 | 测试独立/共享库通过 | 同上 | B，7 项；未执行 C |
| 现场 xOpenCode 1.19.5-h1 | banner/后缀/明确登录提示规则有 A 测试；实际未验证 | 指定 D: 库不可用 | 未验证，不能标记为发行版不支持 | 必须的 C 未执行/未通过 |
| Windows npm `.cmd` / 官方 1.18.35 | 实际安装入口初始化、复核、归档通过 | 独立测试库通过 | 本入口此轮未选清理测试 | B，1 项；实际保留 npm 入口 |
| Windows npm `.ps1` / 官方 1.18.35 | 实际安装入口与三 Worker 通过 | 独立/共享测试库通过 | 精准清理、暂停恢复通过 | B，2 项；真实发现并修复了 `$args` 参数合并问题 |
| Windows `.bat`、Node 参数前缀 | 实际 Windows 启动与特殊字符边界测试通过 | 不由参数测试授予 | 不由参数测试授予 | A；本机 npm 包仅提供 exe，没有 JavaScript CLI 入口；企业包装入口 B 未完成 |
| 未知 1.x 协议族 | 先隔离探测；需首次运行验证完整事件 | 与测试 schema/迁移逐项比对，失败阻止写入 | 另验调用和服务/会话归属 | A；未知版本不会直接获得全部能力 |
| 2.x 或后台服务运行模型 | 当前适配器尚未验证服务归属，明确阻止 | 不启动用户库命令 | 保留会话 | 未完成适配，不等同于产品本身不支持 |

实际官方文件身份：

- 1.18.35：`C:/Users/Administrator/AppData/Roaming/npm/node_modules/opencode-ai/bin/opencode.exe`，SHA256 `83567c13cc5e361ded7e48351cb024cd4503285960d82c30fc585194da46d757`。
- 1.19.5：本轮从官方 npm 包下载至 `workspace/acceptance/opencode-compat-20261117/cli-1.19.5/package/bin/opencode.exe`，SHA256 `d7b473388cb62555970e400ce54cdfb6d6573608beea6f8fdf382cd1a698a3fa`；没有替换用户安装。

## 分层验证与结果

证据根目录：`workspace/acceptance/opencode-compat-20261117/`。包含失败与重试的原始记录，不把旧失败日志改写为通过。

| 证据 | 类型 | 结果 |
|---|---|---|
| `environment.json` | 真实环境 | 分支、Python、资源存在性、程序摘要 |
| `protocol-final.log` | A | 26 通过：编码、banner、冲突版本、非零退出、认证提示、启动器、缓存/入口变更等 |
| `protocol-binding-final.log` | A | 28 通过，增加 npm `$args` 转发及认证/配置变更缓存失效 |
| `protocol-cleanup-final.log` | A | 54 通过，1 未选中，9 subtests 通过 |
| `shared-fault-final.log` | A | 3 通过：额度/公共故障停止派发、可选清理能力、选择批次恢复 |
| `regression-verified.log` | A | 65 通过、1 旧断言失败；失败断言已修正并在上项单独通过，不能把此日志称为全通过 |
| `final-regression.log` | A，扩大范围后发现问题 | 214 通过、15 失败（含 subtest 失败）、2 跳过、246 subtests 通过；保留原记录，后续修复与基线核对见下文 |
| `repair-regression-final.log` | A，修复后相关回归 | 115 通过、102 subtests 通过，1003.64 秒 |
| `windows-cwd-final.log` | A，最终 cwd 与维护验证 | 35 通过，21.51 秒；含实际 Windows 深目录启动 |
| `diagnostic-final.log` | A，最终公共故障/脱敏验证 | 4 通过，55 未选中 |
| `engine-guard-final.log` | A，静态边界 | 2 通过，4 未选中；新静态模块和静态变化仍使指纹改变 |
| `legacy-checkpoint-final.log` | A，旧检查点恢复 | 3 通过，3 未选中；测试改用实际 workspace 结果位置 |
| `live-11835-final.log` | B | 7 通过，662.68 秒 |
| `live-1195-final.log` | B | 7 通过，713.56 秒 |
| `installed-entries.json` | 真实入口，无模型 | npm cmd/ps1 初始化均通过；修改前失败保存在 `installed-entries-before-fix.*` |
| `live-cmd-final.log` | B | 1 通过，6 未选中，203.66 秒 |
| `live-ps1-final.log` | B | 2 通过，5 未选中，456.80 秒 |
| `real-project-scan.log` | 真实工程静态 | 58 变量/23 候选，检查点有效 |
| `real-source/final-audit.json` | C 补充尝试 | 失败；2 次 CLI 调用，至少 1 次实际模型请求，0 成功归档 |
| `source-ui/result.json`、`review.png` | 真实 Chrome UI | 通过：显示实际入口/版本/能力、无模型预检、读取原有队列；不是 C 通过 |
| `canonical-followup.log` / `canonical-benchmark-final.log` | 静态与归档回归 | 单独归档导入通过；benchmark 测试的数据根冲突修正后通过，未放宽生产配置一致性检查 |
| `native-interleaving-final.log` | 实际本机 C 编译/执行 | 1 通过；使用包内 MinGW 完成此前因 PATH 无编译器跳过的重放 |
| `package-final.log`、`package-final-result.json` | 最终 Portable B | 2 通过，253.410 秒：4 项/3 Worker/清理 4 项，2 项/1 Worker/暂停恢复/共享测试库清理 2 项 |
| `package-recovery-result.json` | 实际故障恢复 B | 已有 2 项 DONE 保持原字节，新增模型调用 0；重试失败清理成功；两条历史会话/消息逻辑摘要一致 |

B 层使用真正的 Windows OpenCode 与测试库，本地模型服务是模拟的。覆盖单 Worker、三个 Worker、每项归档、暂停恢复、清理关闭/开启、初始化/启动失败重试、数据库只读/锁/不兼容。测试各保留两条人工历史会话及消息并核对前后，验证只删除本次已归档会话；不接触指定 D: 历史库。这些是真实数据库保护测试，但不是该 D: 库验收。

扩大回归发现并修复了慢 checkpoint 回调阻塞 Worker 补位、隔离 GIT_DIR 与只读路径基准不一致等问题。合成摘要/格式修复测试显式使用测试桩并检查 stdin，不再依赖 Python 文件名绕过初始化。旧测试读取 `.ecra` 而非实际 workspace 输出、子进程继承冲突数据根的假设也已修正。

**没有宣称全仓测试全绿。** `test_review_publication_upgrade_accepts_only_matching_static_bytes` 在独立导出的未修改 bd533960 基线中也失败（`baseline-engine-module.log`、`baseline-engine-check.log`）。该测试期待接受的更早迁移摘要不满足当前严格规则，本轮未放宽它。合并回归中的一次 Windows 导入重命名占用失败，单独重跑通过；原失败日志保留，不能视为已经修复了通用文件占用问题。两项跳过中，本机 C 重放已补测；需要另行启用真实模型的 stale-writeback live 测试仍未执行。

## 最终 Portable 与实际加载证据

包目录：`workspace/p/ECRA-Portable`；交付 ZIP：`workspace/p/ECRA-Portable.zip`。清单与摘要见包内 `FILES.sha256.json` 及外部证据 `final-package.json`。构建缓存位于 `workspace/.ecra/oc-portable-cache`，未新增 C 盘 ECRA 数据区。首次 pip wheel 参数错误、过深构建路径及过深迁移自检路径的失败记录均保留；缩短本轮验收目录后，`workspace/w/acceptance.json` 的 **29 项 Portable 自检 PASS**，同时其 OpenCode C 项仍明确为 NOT_TESTED。

真实包内启动使用：

- Python：`H:/global_static_concurrency_design/workspace/p/ECRA-Portable/runtime/python.exe`（随包 3.10.9）。
- 模块：`H:/global_static_concurrency_design/workspace/p/ECRA-Portable/ecra/__init__.py`。
- 启动包标识：VERSION.txt SHA256 `a4b6a71e678f0cc92cec6ddaa9012ebd8a76f6492d041190e25ba295e46cb3dc`；最终工作代码另逐文件与源码核对。
- 包内实际工程扫描 ID：`89ec3751e2b8459793993fba4afc1b61`，仍为 20 TU、58 变量、23 候选，真实模型 DONE 为 0。
- `package-final-result.json` 记录所有已加载 `ecra.*` 模块来源并逐项断言均在包内；源码 checkout 仅提供测试控制器，不提供生产模块。
- 源码最终浏览器证据为 `source-ui-final`；包内最终浏览器证据导出为 `package-ui-final`。两者都验证真实 Chrome、配置选择、入口/版本/能力和归档读取，未调用模型。

在包内 B 测试中，先实际复现了恢复清理的 WinError 267，证据见 `package-pause.log` 及保留的 ownership.sqlite3。根因是嵌套维护/探测 cwd 超过 CreateProcess 可接受长度；已改为工具 workspace 下的短临时 cwd，认证 scope、数据库与诊断归档位置保持独立。先对原失败记录恢复成功且未重跑模型，再从新任务完成最终两项测试。此结论有实际 Windows 证据，与仍未复现的企业域登录根因分开。

打包时将本轮包内运行数据原样移存到 `workspace/p/portable-evidence/package-workspace`，不删除归档、认证副本或测试历史；ZIP 只包含干净包文件和清单。测试外部库保存在证据目录 `package-external`。源码真实工程任务仍在原数据根，可继续使用。ZIP 字节校验、源码/包代码一致性和最终摘要另记录于 `final-package.json`，不是模型验收证明。

C 补充尝试通过正式 Studio 任务 API，选定：`GS-0d7684eb79d45ec6`、`GS-19dde2edf6eccc7a`、`GS-2facc6728a7ed190`、`GS-47748605926addc4`、`GS-4b49bcc39080dff2`。使用现有合法配置中的 `kimi/kimi-k2.7-code`，实际返回 HTTP 429、账户余额不足。第二个已启动 CLI 被安全停止；提供商内部重试次数未知，因此仅报告“至少一次实际模型请求”。最终首项 TECH_FAILED，其他四项 PENDING；整个工程 TECH_FAILED 1、PENDING 22、DONE 0。错误没有伪装成模型结论或零调用初始化失败。此次使用私有测试库，并未声称绑定了缺失的 D: 库。

## 必须继续完成的现场门槛

1. 提供本机可访问的实际企业程序、指定历史库和原始诊断；重新计算摘要，执行同 exe A–E 对照，确认域认证合法来源与首次触发条件。
2. 有效模型授权/额度恢复后，经隔离探测与只读库兼容检查，实际绑定指定共享库完成真实候选复核，前后核对选定历史消息。
3. 不少于 5 个真实候选完成单 Worker/三个 Worker 批次；部分归档后关闭重开、继续剩余、失败重试；验证清理开关及企业版实际删除协议。
4. 最终 Portable 真实模型归档。包构建、UI 和 B 层不能代替此项。

以上缺失项没有通过延长超时、降级版本、换库、关闭复核或静默回写用户目录绕过。默认静态检查入口保留，自动复核失败保持队列和人工确认语义。

## 修改范围与可审查性

运行上下文/协议/入口集中在 `opencode_storage.py`、`opencode_protocol.py`、`opencode_command.py`、`review_opencode_sessions.py`、`review_process.py`；队列/归档/清理在 `review.py` 和 `review_session_cleanup.py`。`opencode_check.py` 给 CLI/Studio/Portable 提供统一无模型预检。配置、Studio 页面及 profile 字段一致使用 review 配置；新增批次选择只筛选真实候选，不制造 facts。静态扫描算法、风险分类与人工确认未改动。

静态检查点兼容通过精确源码摘要映射保留，非无条件忽略引擎变更。合成协议测试使用显式测试桩，不再通过“程序文件名不含 opencode”绕过生产初始化。运行产物、构建缓存和本轮诊断均在工具 workspace；用户认证文件仅作读取来源，未提交密钥和完整环境。

配置继承、能力状态及剩余运行模型边界详见 [兼容说明](opencode-compatibility.md)。
