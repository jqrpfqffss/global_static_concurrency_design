# R3a：原生命令行状态与后置校验不再恢复整张报告

> 后续真实INAV完整报告摘要也已结束，原值匹配、原库/状态/源文件不变，Job提交峰值34,557,952B；完整范围见[86号](86-inav-native-report-digest-acceptance.md)。这没有关闭全部消费者迁移。

审计基点`08200b4`，仍按原任务H1/H2/H3/H6及G1/G6执行。`workflow.status`先经`read_saved_json → scan_persistence.read → EvidenceProvider.load('report')`恢复完整报告；`checked_scan(with_facts=False)`也仍恢复完整报告并在Python再次构造摘要。`saved_run`后置校验和`verify_saved_publication`回退检查重复走此路径。GUI现有分页读取并不证明这些命令行消费者已迁移。

| 改动 | 实现与可核对合同 | 验收 |
|---|---|---|
| `native_consumers.status_report` | 在同一权威图读取所有候选身份/分类、完整Diff选择ID、必要计数和既有运行态，不加载访问/调用/保护载荷；1203条候选完整保留，没有topN | 新旧完整对象读取作为独立参考，实际状态输出相同；禁止`EvidenceProvider.load`后仍能完成 |
| `native_consumers.clean_report_digest` | 逐节点计算**原**`logical_digest(clean_report(report))`；磁盘memo只存哈希；字符串按UTF8字节分段引用/转义；保留全部类型、字段、列表顺序/重复；不把原生ordered hash冒充旧ECRA_MERKLE_V1 | bool/int、正负0、大整数、跨块UTF8/转义、共享DAG、finding在其他位置的opaque值、缺status插入和损坏长度均验证 |
| `workflow.checked_scan` | 新私有`_report_projection`仅用于无需事实且丢弃完整报告的检查；默认完整返回合同保持；检查完整原始状态摘要、引擎、文件SHA、环境、负探针和原pin均不取消 | 实际既有F030检查点无重扫、全字段报告摘要通过；不存在修改旧指纹放行 |
| `workflow.status`与两处后置调用 | 原生状态使用元数据和完整摘要；本轮不改变继续复核初始全图恢复；正式状态不再提示查看HTML | 实际原生状态/源变化拒绝、当前队列、Diff及既有完整包/复核合同回归 |
| 旧固件/工具内原生结果 | 在打开runtime/queue SQLite之前调用原formal边界，返回`LEGACY_READ_ONLY`和迁移动作；不在固件建立摘要memo或WAL共享内存；scratch/junction按已有no_links拒绝 | 故意禁止旧runtime读取，完整固件树SHA不变；junction目标没有写入 |

新模块是只读消费者，因此明确加入已有`REVIEW_REPORT_MODULES`例外；它不产生/修改静态事实、不运行求解器。实测当前静态引擎摘要仍为`d8ade9133510614044e53de78f9330a5597317d5901d5cd063f0a419d18b3082`，与已保存74ebb5f的实际F030检查点一致，不需要为了状态读取重新解析固件。未知/新的分析模块仍默认包含在引擎摘要中。

最终 **38项PASS，101.804秒**，其中10项新消费者检查含真实192MiB Windows Job子进程对大型共享报告计算完整摘要；其余为9项真实原生扫描/CMake/包/历史、16项深复核状态/重试/并发/证据合同与3项完整范围检查。[精确收据](evidence/native-consumers-source-v1.json)、[完整最终日志](evidence/native-consumers-related-final-v5.log)。192MiB是该codec子进程的实际强制预算，不是大型工程G3或物理32GiB验证。

实际现存原路径F030归档的完整后置检查通过，**1.922秒**、6个候选身份、完整重建调用0；归档DB SHA `e77034e097918f4c10efee6a87b495668a39dc602e35e8f49a24cf7b47a57aae`不变，原固件/配置/引擎无变化：[最终原生检查](evidence/native-consumer-existing-f030-final-v2.json)。这是重验已有检查点，不改标为新扫描或全量/大型Diff。

历史原始结果保留：初轮5项7.966秒PASS；一次编排错误引用不存在的`tests.test_review_state`，18项中17通过/1 loader ERROR，94.321秒，并非产品运行失败；改用实际存在的`test_review_integrity`后36项103.044秒PASS；提前拒绝旧固件runtime后36项102.118秒PASS；增加opaque共享与坏长度反例后完整38项再通过。所有日志/SHA在收据中，不隐去错误，也不把重叠集合相加为全套。

上一批1449冻结已实际完成：**1447 PASS / 2联网opt-in SKIP，2281.791秒**，3665源文件及独立副本SHA差异0；[完整收据](evidence/full-regression-studio-v41.json)。它绑定74ebb5f，不包含本模块，不能用于宣称新1459项通过。

下一步必须以新精确源完成1459项全套及大型真实报告摘要读路径。`saved_run`初始`checked_scan(with_facts=True)`、源码变化回退、Packet构建的完整图、全局Diff摘要/恢复仍需继续迁移/测量。本阶段不关闭整个R3，亦不解除冻结dirty/CMake/恢复门禁。R4确认继承、R5整根搬迁、R6完整故障/UAT、R7总验收继续未完成，`all_gates_passed=false`。
