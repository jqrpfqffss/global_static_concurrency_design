# 2026-10-31 续轮：真实扫描链与验收进度

本文件记录可复查的阶段实现，**不代表完整重构完成**。分支 optimize_ccc，起点 HEAD e69a10bbcb870dfc19a7d69cf2267774d08b3342。保护区算法未修改，已有文件与黄金基线不覆盖；修改前源码备份保存在外部 continuation-h3/pre-h3-source.zip。

## 本轮实现

| 范围 | 实现 | 验证/状态 |
|---|---|---|
| Phase1 存储 | schema v2 调用边真实 ID 索引；共享节点恢复；精确 path/node 查询；源码 gzip CAS 与原始字节校验 | 真实 4TU 全字段比较通过；完整专门关系/外存仍未完成 |
| Phase2 任务 | 独立进程与 Windows Job Object；16GiB 提交预算；实际进程树采样、阶段/TU/日志；停止文件与已验证 TU 缓存 | 真实浏览器开始/停止/恢复通过；完整故障矩阵、32GB大工程未通过 |
| Phase3 新扫描 | CLI 默认 canonical；原分析引擎、全部发布前后输入门禁；静态 scan.db 不变；save/checked/status/report/Diff 逻辑路径适配 | 不生成 facts.json/facts.db/业务 HTML/reports/inventory；兼容旧渲染必须 --legacy-output；全消费者低内存迁移仍未齐 |
| Phase3 AI | 原八步 Prompt；同源只读 MCP；逐项 AI 事件/水位；技术收据/包；独立 review/review-failed 任务 | 407项 stdio 完整分页测试；真实缺失工具故障产生13项 TECH_FAILED，静态库 SHA 不变；未执行联网模型 |
| Phase4 GUI | 真实任务中心与 AI 页；已有中文九导航/四步向导/人工工作台；真实调用树按方向/分页/折叠/缩放 | 14项真实 Chrome 流程通过，含调用树、源码行、组合筛选和清理；完整 U01–U24/系统DPI/真人 UAT 未通过 |
| Phase5 包 | 源码对象和完整收据对象随包校验；AI账本随包重建；相同扫描追加合并审计对象/人工事件 | 离线库/包专项通过；真实50GiB无引用缓存回收/恢复通过，原归档不变；旧格式GUI迁移和物理两机未完成 |

新任务全部经过原输入一致性与静态完整性门禁后，才写 manifest 并移动项目 latest-scan 指针。失败任务没有正式发布指针；旧有效扫描不覆盖。STATIC_VALIDATED 表示扫描时输入校验通过，不能解释成“全工程无风险”或当前源码已再次核实。

## 实际收据

外部原始日志根：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`。

| 检查 | 结果/证据 |
|---|---|
| 同一原始输入独立提取 | identical-native/acceptance.json：facts、静态 report 完整有序类型比较差异均为 null；原文件 SHA 保持；仅合同中的运行信封独立保存 |
| SQLite 新库实际大小 | 同输入 scan.db 6,664,192 B，包含新增归档来源；不能与旧目录直接相除宣称70%收益 |
| 第一次任务 | native-task-receipt-2.json：4TU、15变量、13待复核，原引擎仍为 INCOMPLETE；进程树峰值提交138,690,560 B，仅小项目范围 |
| 原生 full/恢复/失败保持 | tests/test_canonical_scan.py；新任务 merge 故障不改变旧 scan.db 与 latest 指针；report 刷新不改变静态库 |
| 原生固定提交 Diff | canonical-diff-1.log：真实两提交、base→HEAD、IDE未跟踪文件、SQLite基准证据、保存恢复通过；不代表完整 Diff 矩阵 |
| MCP与账本/导入专项 | ledger-mcp-tests-2.log：35项通过；merge-tests-1.log：17项通过；新增版本随后需增量回归 |
| 真实浏览器 | output/playwright/studio-native-20261031-final/acceptance.json：11项通过；含真实停止/恢复、工具缺失AI故障，零页面错误/外部请求；截图/video/trace 同目录 |
| 原生等价首次失败 | canonical-native-1.log：引擎 tuple 序列化未兼容，已修复为原 JSON 数组规则；失败保留 |
| 全套回归首轮 | full-regression.log：存在旧 Diff 渲染 review_targets 缺失导入和旧 CLI 布局合同失败，不能计为通过。修复后frozen-engine-v2实际1112项中1失败5错误2跳过，剩余旧产物测试合同已修复；frozen-engine-v3完整回归1129项，1127通过、2实际模型测试跳过，1631.320秒；此后6个引擎文件变更另有专项 |

已将旧布局测试明确切换到 --legacy-output，保留全部原断言；新格式另用原生扫描/恢复/失败/Diff/包与浏览器断言验证。不会把兼容测试误称新扫描格式通过。

## 仍需继续完成

全部专门关系索引、OpenCode恢复时全量 facts 读取消除、全局求解工作集与资源闭环、dirty 字节隔离、三类大型原生 full/Diff 黄金、完整相关证据指纹的精确继承、完整专业证据工作台、旧历史流式 GUI 迁移、最终 Portable 重建验收、干净离线机与系统 DPI/真人 UAT。G1–G8 总门禁保持未通过。

## 2026-11-01 续轮新增实测

- `evidence/native-canonical-v3.json`：相同原始配置路径/字节、源码、ARM工具链、编译数据库，独立原生4TU提取；完整有序facts和静态report差异0，原黄金哈希不变，旧产物不存在。
- `evidence/gc-capacity-50gib.json`：真实写入53,687,091,200字节、引用校验/隔离/释放；实际磁盘空闲增加53,687,025,664字节。原包/静态库/人工历史不变。仅无引用合成缓存容量夹具，不代表原生G3/G4。
- `evidence/browser-canonical-v3.json`：14项真实Chrome操作通过；调用树双向、源码行定位、组合过滤/键盘分割线、人工保存/重开/撤销、恶意包拒绝、清理完整闭环、原生开始/停止/恢复、缺失OpenCode工具13项TECH_FAILED且静态SHA不变。系统DPI和真人盲测未验证。
- `output/playwright/studio-capacity-20007-20261101/acceptance.json`：20007行显式容量夹具通过真实服务分页、最后身份检索、人工保存重开；最大API响应16,656字节，首页0.266秒、末行检索/打开0.218秒。该夹具没有原生提取，不用于G1–G4。
- 新增源代码窗口/组合筛选/跨实例预算/软阈值调度/完整清理专项；`source-view-tests.log`21项，`resources-filters-tests.log`18项、`pre-freeze-v3-tests.log`13项通过，范围不同不相加充当完整套数。
- 重复扫描修复finding基线；锁覆盖验证和发布。`cleanup-baseline-tests.log`14项通过；同profile变更保留全部旧人工事件并显示RECHECK_REQUIRED。
- 性能和Portable脚本仍发现旧路径依赖；首次新包实际原生ARM扫描成功，但旧验证器读facts.json失败，失败目录保留。验证器已迁移SQLite并从本轮latest读取，随后v4目录及长中文ZIP解压各26命令通过；v5再加入恢复缓存/清理监督器退出保护，最新v6进一步检查主操作首屏边界。

当前实际主机64GB RAM；没有32GB Windows、独立工程师/目标板或干净离线VM验收收据。完整Phase和G1–G8继续未通过。

最新专项：`evidence/regression-canonical-v5.json`记录完整冻结快照与后续6文件差异；当前68项模块回归107.490秒通过，原Portable 20项42.390秒通过。未把不同范围套数相加。`evidence/native-canonical-v5.json`仍为原输入原生全字段0差异。

清理增加未放弃的中断/失败任务、partial CLI扫描和旧断点引用保护；不能因缓存可重建就删除恢复所需TU。监督器进程在移动后退出，重启后任务标中断，可从原计划恢复；跨实例存活任务不被误标。实际8项清理测试与清理控制器/包专项通过。

## 已封存的当前阶段候选 v6

实现提交：`7ef7c8a8f5b8e56ff4ddb1e3fcb9c7d25f74d8e2`；设计/审计提交：`ff03425`。用户原有config/semantics.yaml注释改动与原任务文档未纳入这些提交。

`H:/ECRAStudio-build-20261101-canonical-v6/ECRA-Portable.zip`：504,252,703字节，SHA-256 `419432b2931549436c20594053a40d8dedef850002a232b4ae1d4b395f6f873c`。目录与长中文ZIP解压各26条命令通过，含真实ARM编译/链接、默认SQLite扫描及保存命令静态SHA不变；包内Python3.10.9真实Chrome十四项通过。当前100个程序源码/前端/许可文件与包逐字节一致。

收据：`evidence/portable-canonical-v6.json`、`portable-source-match-v6.json`、`browser-portable-canonical-v6.json`；截图已归档ui/screenshots/v6。此候选不是完整重构发布，仍有本文件列明的实现和G1–G8门禁待完成。
