# 页面状态矩阵

所有业务页共同状态：LOADING“正在读取…”，EMPTY“尚无…/具体下一步”，VALID“已校验静态快照”，STALE“输入已变化/需重新扫描”，PARTIAL“覆盖不完整/查看缺口”，FAILED“失败阶段+原因+修复”，OFFLINE_ARCHIVE“归档证据模式/原源码不可用”，PERMISSION_ERROR“路径+权限+修复”。不能加载时保留未知，不展示绿色0。

| 页 | 主要动作随状态变化 | 禁止行为 |
|---|---|---|
| 概览 | 添加工程/检查并扫描/查看扫描/继续人工确认/打开当前结果 | 多个强主动作；全工程安全横幅 |
| 向导 | 下一步/检查/启动，仅真实检查通过可启动 | 丢输入、用芯片标签伪装宏 |
| 扫描 | 开始/安全停止/检查点恢复/重试 | 假ETA/百分比；无检查点的暂停 |
| 变量 | 选择对象/读取下一段/复制 | top N完整宣称；未知enum当安全 |
| 覆盖 | 查看影响对象/真实修复路径 | 99% TU等于99%安全 |
| AI | 可选启用/失败重试（落地后） | DONE等于SAFE；缺源码重新证明 |
| 人工 | 保存决策/撤销/解决冲突 | 未提交成功提示；无依据刷绿 |
| 历史 | 打开/对比/继续确认 | 证据不同继承旧安全 |
| 共享 | 校验预览/导入/导出/清理预览 | 损坏包污染、未校验自动删旧数据 |

任务状态：CREATED→PRECHECK→BUILD→EXTRACTING→EXTRACTED→SOLVING→CLASSIFYING→PUBLISHING→STATIC_VALIDATED→AI_REVIEW→COMPLETE；异常INTERRUPTED/FAILED/INVALID。STATIC_VALIDATED仅代表静态证据有效，COMPLETE也不代表硬件安全或人工确认完成。
