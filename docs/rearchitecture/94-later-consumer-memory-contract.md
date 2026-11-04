# 后续操作省内存：最后一项的代码审计与实施合同

> 第一个消费者已实现并完成限定验收，见[95号](95-runtime-refresh-memory-acceptance.md)：F030真实刷新/完整G1子对照0差，既有INAV 12.59GB库运行时完整投影0差、实际2GiB Job提交峰值约116MiB；完整复核/Packet/Diff恢复仍未完成，下面合同继续适用。

用户顺序见[87号](87-functional-priority-execution.md)。本页是审计与待实施合同，不是功能完成或性能通过声明。确认继承、完整数据根复制与显式数据库未提交输入先验证，保留原分析器和完整归档。

| 真实消费者 | 当前内存来源 | 必须保留的行为 / 下一步 |
|---|---|---|
| `workflow.checked_scan/status` | 原生状态投影和完整report有界摘要已实现；状态候选身份和人工/AI队列仍按数量驻留 | 保留完整输入/环境/引擎/原report摘要核对；86号只证明大型摘要，不证明整个status |
| `workflow._saved_run(render_only=True)` | 默认`checked_scan`恢复完整facts/report，然后`report.prepare`重新组织全量变量、冲突和诊断 | 首先把已有权威库刷新改为有证据的最小元数据读取，复用原分类/总结函数；完整校验仍执行。不能从小投影重新发布静态权威库 |
| `review_all/build_variable_review_packet` | 全facts/report及所有候选驻留，函数/调用反向索引重复；同一变量Packet仍可能很大 | 同一EvidenceProvider按身份读取完整相关证据；Packet可导航和分页但不能截断访问、路径、保护、未知。必须与原Packet逐字段/关系对照 |
| 复核源码 / 引用 | 已新增归档源码MCP，显式传入每个工作线程，并让独立收据重验同一归档 | 目前引用收集仍拼接整份文件；之后按行范围流读，保留原始字节SHA、原行号和UTF8替换解码行为；不得改变证据有效性规则 |
| Git Diff / 故障恢复 | `verify_full`和全局求解需要完整事实；有些基准摘要及恢复入口仍可能恢复完整图 | 分开测消费者和全局求解。保留完整base→current、不动点/影响闭包及完整校验；TU缓存恢复不冒充任意全局位置续算 |
| 完整数据根 / 包 | 已有流式复制、哈希、WAL和严格完整包路径；大型全数据根与新dirty跨根恢复尚未联合验收 | 小工程复制不能替代INAV整体测量；旧dirty视图含绝对路径，在没有重定位证明时必须拒绝重新证明，归档查看仍可用 |

实施时只修改执行/读取方式，不修改静态分类、风险阈值或复核八步逻辑。每条消费者均须记录：原/新输入身份、完整语义差异、私有提交/RSS/系统可用内存/分页/磁盘峰值、实际停止及原扫描/人工历史SHA。目标是让后续操作可用；小夹具、仅摘要2GiB Job、共享64GB机器测量均不能标为物理32GB整套通过。

第一步选择“已有权威库的report刷新”：它不需要重新求解全局事实，且当前确实会加载完整图。先审查`report.prepare`、`decisions.variable_decisions`、`html_report.risk_summary/final_conclusion`、`scope.validate_selection`与`scan_persistence.append_runtime`的实际字段依赖，以完整运行时投影逐字段0差验证，再接复核/大Diff；不复制另一套判定规则。任何尚需完整读取的路径继续明确列NOT_VERIFIED，不用未实现的按钮或内存承诺代替代码。
