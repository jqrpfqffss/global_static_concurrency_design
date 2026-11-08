# 最终 V8 便携包：独立用户使用检查

本次由未实现 GUI 的检查者，从实际 `ECRA.cmd` 启动后的 HTTP 页面完成只读使用检查。结果为**已检查的流程通过，保留窗口环境与长页阅读限制**，不代表整个产品或分析结果完整无缺口。

- 成品：`H:/ECRA-quality-20261108-offline-build-v8/解压 终验/ECRA-Portable`。
- ZIP：785692766 B，SHA-256 `b4590047afd32bfe3beb803b7a934ae52c893daf3d12a4fbe2c2ff456880ab1a`。解压/CRC/154 个生产文件一致性的证据由协调者记录于 [extracted-v8-receipt.json](../../output/quality-20261108/continuation/extracted-v8-receipt.json)。
- 检查者独立读取该解压目录的 `ecra` 与 `workflow`，实际引擎为 `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`。该读取使用宿主 Python `-B`，不冒充内嵌 Python 运行检查。
- 页面实际加载 `/assets/index-DHpgztut.js`。服务由协调者以 Windows-only PATH、PORTABLE 模式启动，根进程 PID 29628；本检查未启动旧成品，也未停止服务。
- 数据仅为已有 QA 副本：`H:/ECRA-quality-20261108-offline-build-v4/界面验收 独立数据`。目录名 v4 不代表本次运行的是旧程序。

## 实际完成的任务

| 用户目标 | 实际入口与结果 | 证据 |
|---|---|---|
| 识别项目、结果来源 | 初始页明确显示 F411 项目、批次、归档来源尚未验证；点击工程身份可查原根路径、配置、编译数据库、Git 身份与 INCOMPLETE | 图 01–02，`cli-003` / `cli-007` |
| 从历史找到已确认风险 | 历史与对比 → resolved-nmi → 确认风险 → shared；原静态疑似与当前人工风险分别保留，三个签署/撤销/重新签署事件可见 | 图 03–04，`cli-020` |
| 理解调用/别名证据 | 实际展开 Impl 上游：函数别名标为同地址实现绑定，并有声明位置，未被标作普通调用 | 图 05 |
| 找到真实叶项 | 历史 → F411 → 继续人工确认 → 搜索 `g_cli.command_list`；选中 `g_cli.command_list[*].name`，待人工总数 38 | 图 06、16 |
| 阅读长链、多访问与源码 | 三层真实调用链、8 个访问函数、16 次访问、42 组潜在并发关系；读取与取地址中文标签可见；“定位此访问代码”打开 `utils/src/cli.c:33`，放大源码窗口正确高亮该行 | 图 06、09–11、17 |
| 找到确认填写入口 | “填写人工确认”可展开；空表单四个主要按钮可到达。未填写、签署或撤销 | 图 07、12–13 |
| 核对覆盖范围 | 覆盖与诊断显示 INCOMPLETE、24 个成功 TU、532 条缺口；缺口及关联证据可查，构建闭包与范围单独展示。解析成功和空列表均未被写成安全证明 | 图 14–15，`cli-101` / `cli-104` |
| 退出再继续 | 正常关闭 Chrome，使用同一持久 profile 重开，F411、待人工 38、上次叶项保留；“继续上次位置”回到该叶项 | 图 08、16，`cli-067` / `cli-068` / `cli-110` |

本检查没有依据实现代码预先指定按钮顺序；使用可见导航、历史、继续复核、搜索和证据入口寻找目标。没有访问真实 OpenCode、注入浏览器存储、恢复内部状态、修改数据库或制造新人工事件。

## 实际画面与窗口边界

全部 17 张新截图均由检查者实际打开查看，不只读取 DOM。原图位于 [output/playwright/quality-20261108](../../output/playwright/quality-20261108)，精确文件名、尺寸及 SHA 在 [acceptance.json](../../output/quality-20261108/continuation/package-ui-final-v8/acceptance.json)。

- 图 01–07 使用真实 headed Chrome 的 1366×768 / 1920×1080 **渲染视口**；浏览器外窗仍约 1057×772。因此证明对应排版，不证明那些目标内容尺寸在物理窗口全部可见。
- 随后正常关闭并以 `viewport:null`、同一持久 profile 重开。只对已核实的本次 localhost 页面所属自有窗口，使用标准 Chrome `Browser.setWindowBounds` 调整正常窗口边界；没有改页面缩放、OS DPI、其他窗口，也没有使用 CUA 或 file 协议。
- 最终实际窗口：bounds/outer **1461×781，位置 0,0，normal**；实际内容 **1447×631**；screen avail **1463×783**，完整位于可用屏幕范围。DPR 1.75、visualViewport.scale 1 仅为观察值，不能据此声称验证了 OS 显示缩放。
- 图 08–17 为以上原生内容范围。1366×768 和 1920×1080 的**原生内容窗口**受当前可用屏幕限制，状态为 **NOT_VERIFIED_ENVIRONMENT**。
- 长证据使用普通页面滚动可阅读，源码可放大。确认区在长源码下方，普通页面向下滚动后四个主要按钮完整可见；项目和当前待确认状态仍可见，**所选变量标题随页面滚动离开视口**（图 13）。这是保留的阅读效率限制，不写成标题始终可见。

## 数据保留及结束状态

检查前后均用 SQLite `mode=ro` 读取三个 QA 归档的人工事件，仅比较 event_id 和 payload SHA。resolved-nmi 原有 3 个事件完全一致，另外两个归档仍为 0；[比较收据](../../output/quality-20261108/continuation/package-ui-final-v8/review-events-comparison.json) 为 `event_ids_and_payloads_unchanged=true`。

最终 `ecra-quality-package-v4` Chrome 已正常关闭（`cli-116-close.log`），持久 profile 保留，服务 PID 29628 留给协调者正常关闭。没有修改生产代码或测试。真实写入、损坏和恢复检查沿用此前独立证据，本次不重复操作人工确认事件。

检查中曾有一次 PowerShell 未加引号的搜索参数错误及一次 `run-code` 函数格式错误，均为控制器调用错误并已纠正。初次尝试清除 CDP 指标没有消除 CLI context 模拟，故随后明确关闭重开为 `viewport:null`，未以该尝试伪称原生窗口通过。

## 沿用实际窗口配置

配置为 [native-window.config.json](../../output/quality-20261108/continuation/package-ui-final-v8/native-window.config.json)，内容 `{"browser":{"contextOptions":{"viewport":null}}}`。在仓库根目录执行：

```powershell
py -3.10 -B -X utf8 output/quality-20261108/continuation/package_ui_final_v8_cli.py --session-file H:/ECRA-quality-20261108-offline-build-v4/ui-session.json --browser-config output/quality-20261108/continuation/package-ui-final-v8/native-window.config.json open
```

该命令使用命名会话 `ecra-quality-package-v4` 与原持久 profile `H:/ECRA-quality-20261108-offline-build-v4/ui-browser-profile`，由私有 session 文件读取当前服务 URL，证据日志会遮盖 token。不要将私有 session 内容放入报告。若服务已切换，先由服务正式启动流程更新 session，不能猜测旧端口。

完整命令、脱敏输出和截图清单在 [package-ui-final-v8](../../output/quality-20261108/continuation/package-ui-final-v8)。归档来源仍未验证且分析 INCOMPLETE；本次 UI 流程通过不构成目标固件安全结论。
