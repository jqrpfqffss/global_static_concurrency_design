# OpenCode 结果展示与真实复核验收（v89）

## 审计与实现规格

基于 optimize_ccc 的 0f8c301。原版 `decisions.review_category` 是分类依据：DONE/CONFIRMED → 确认风险，DONE/LIKELY → 疑似风险，DONE/REVIEWED_SAFE 或 FALSE_POSITIVE → 安全/误报，其他状态 → 待复核/无法判断。旧结论失效、技术失败不能成为安全结论。

发现的问题：Studio 漏译 REVIEWED_SAFE，只展示执行状态，列表使用 finding_id，原答复只有 JSON。现补齐四类筛选与全轮数量、变量名/定义位置、服务器搜索分页；独立证据缺口单独标识。正文显示模型原文的依据、交错过程、保护、影响、建议、源码引用；原 JSON 与执行收据折叠保留，源码引用可打开归档阅读器。默认选择扫描绑定的工程配置。统计为复核对象，不冒充全部变量数。

权威 facts/report 不改写。当前账本用 SQL 选取快照水位内的最新事件，筛选后分页，不在 Python 载入全轮答复；旧快照兼容入口沿用已有全量读取方式。结论映射与原版逐项测试对照。

真实 OpenCode 1.18.35 联调发现绝对路径授权不匹配当前 read 工具的工作树相对路径；非 Git 工程又使用全局工作树 `/`。`_review_env` 为同一批明确的只读 packet/案例文件补充绝对、规范化、Git 工作树及非 Git 全局根的相对路径拼写，不放开通配 Markdown、源码读权限、写操作、shell 或网络工具。格式修复阶段仍无读权限。参考上游 [read 工具实现](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/read.ts) 和 [权限文档](https://opencode.ai/docs/permissions/)。

## 验收边界

真实工程为已获准的 STM32F030C8T6 裸机固件，原目录只读，全部扫描和复核产物位于独立测试数据根。真实模型为本机已登录的 deepseek/deepseek-flash，由工程配置表单保存；案例使用工具原始 26 条案例，工程背景用页面编辑工程副本。

首轮只读案例正文被 OpenCode 权限拒绝；该轮不能作为通过证据。期间修改引擎后，输入闭包重验将该轮六项全部标成 TECH_FAILED，历史响应保留，未绕过门禁。第二次试验发现非 Git 全局工作树路径仍未授权，且 2GiB 父测试 Job 内的进程返回 0xC00000FD，该次试验也不计通过。测试初始化一度误复制历史指针而没复制被引用扫描，程序正确拒绝缺失的权威库；修正为仅复制 profiles，未放宽历史校验。

最终轮使用只读冻结源码 `frozen-engine-studio-v89-r3`、新的扫描身份、4GiB 父测试 Job（产品扫描任务预算仍为 16GiB），未复用前两轮模型缓存。小预算试验的失败不能据此宣布低于 2GiB 的 OpenCode 复核受支持。

## 已实测结果

- 真实扫描：`9dc4ba9fab1a48e1955f5910e82478c7`；复核任务：`149c2c18a3c74b229d2c26ae0c776d6c`。真实固件四个 TU、完整十五项对象清单中的全部六项复核目标完成。
- 原始枚举：DONE 6、TECH_FAILED 0；LIKELY 1、REVIEWED_SAFE 1、FALSE_POSITIVE 4。该真实工程本轮没有 CONFIRMED；CONFIRMED 展示/筛选由明确标识的协议夹具覆盖，未伪造真实风险结论。
- 原 `workflow.py` 保留疑似风险/静态覆盖不足时的 `INCOMPLETE` 和退出码 2。六项复核执行完成不表示风险排除或全工程安全。
- 原 `verify_receipt` 逐项通过；每项 ANALYZE 提示词均包含页面配置的 `F030-REAL-20261107` 背景，模板 HTML 注释未进入提示词；每项原始 JSONL 中均有 `read` 成功读取案例正文的记录，不以复制文件、索引存在、MCP 的“未找到”答复或模型自述替代成功阅读。
- 案例库 SHA-256 为 `85b45cdff897edee2ba53db42c26318f6e40f70d271f09bc885cefe5073c2e77`，包含 26 条案例；背景副本 SHA-256 为 `372dc990c7f627a1fe1de06fb760190f6c3cad38f1c47915274f77756e99a01d`。页面保存的 deepseek/deepseek-flash、workers=2、timeout=900 实际生效。
- 固件四十二个文件的内容、大小、mtime 全部未变，没有新增产物；静态 scan.db 在复核前后 SHA-256 一致。
- 浏览器真实输出验收：安全清单五项含 REVIEWED_SAFE 和 FALSE_POSITIVE、疑似清单一项、确认风险空态真实为零；搜索、原文折叠、源码定位、配置再次打开均通过。1440×900、1366×768、1920×1080 下检查无页面横向溢出、证据区可读。将复核操作栏压到一行，1366×768 下证据区比第一版增加约 76px。
- 固定源码相关测试 148 项：147 通过、1 项可选联网单测跳过。真实联网验收使用上述完整六项任务，单独记录。新结果查询 8 项测试在最新测试源码再次全部通过。
- Portable 自带 Python 下 132 项：130 通过、2 跳过（可选联网单测、仅开发环境依赖 TestClient 的 API 单测）；实际封包 HTTP/浏览器另测，未往运行时加入测试依赖。首次测试发现缺少 TestClient 开发依赖和 Packet 测试辅助脚本，失败日志保留；补入冻结辅助脚本，重新测试通过。
- 既有 INAV 完整权威库 12,590,510,080 字节、3,540 项复核账本，两次分类分页查询约 0.187 秒，进程峰值提交 16,748,544 字节，仅返回所需页。该数据全部待复核，不冒充 INAV 真实模型验收，更不代表整轮 Diff/恢复内存验收。

原始响应和完整任务目录保留在 `H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/ui-v89-live-r3`。公开到仓库的精简收据见下方链接；其中未包含用户登录凭证、会话令牌或原始源码响应。

- [完整真实复核审计](acceptance/opencode-v89-real-full-review.json)
- [真实结果页面验收](acceptance/opencode-v89-real-ui.json)
- [Portable 页面复验](acceptance/opencode-v89-packaged-ui.json)
- [固定源码测试](acceptance/opencode-v89-source-tests.json)、[Portable 测试](acceptance/opencode-v89-packaged-tests.json)、[大型查询测量](acceptance/opencode-v89-large-query.json)
- [安全详情截图](acceptance/opencode-v89-safe-1366.png)、[疑似风险详情截图](acceptance/opencode-v89-likely.png)

复现：按 [v89 操作指南](../studio-v89-opencode-guide.md) 配置并实际发起完整任务，再使用 `scripts/audit_studio_live_review.py --help` 逐项验证原收据、案例正文阅读和背景输入。浏览器 CLI 操作脚本和截图原件位于同一 continuation-h3 测试目录，`check-v89-live-ui.py`、`check-v89-portable-ui.py` 均只对真实任务输出点击和读取。封包最终哈希与启动复验另附本地 `portable-v89-assembly.json` / `portable-v89-final-check.json`，只在文件生成并验证后计通过。

其他 G2 工程、32GB 真机、干净离线电脑、原生 DPI 和人工 UAT 仍为 NOT_VERIFIED；跨环境严格报告对照 FAIL 与大型整轮 Diff/恢复的未完成验收不因本次改动关闭。
