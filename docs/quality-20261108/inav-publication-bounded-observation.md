# 大型INAV发布阶段有界只读核对

本记录仅属于正在运行的冻结V4/core `63a5cff7e9babcf0a4982726f68ca8390ad5f840b92d31d41e511a859d857710`，任务`f2f751073cb34310b8d8beb06673a501`，原service18116/worker26132。未改源码、配置、工程、Git、任务或检查点，未打开pending SQLite，未attach、发信号或停止进程。记录是当前观察，不是该大型工程发布通过或新版V8整轮通过。

证据位于`output/quality-20261108/continuation/new-upgrade-v4/`：`publication-bounded-observation.json`为两次psutil/文件metadata样本，`publication-source-path-audit.json`为代码、现有小型JSON及日志核对。9个涉及生产/发布/监控的V4文件SHA均等于任务启动前`engine-sources-before.json`，样本间所读源字节也一致。

## 观察到的活动

2026-11-08 13:07:55Z开始的两个样本间隔20.141秒，满足不超过30秒；原单次发布阶段从11:47:53Z开始，采样时已运行约80分钟。

| 对象 | 该20.141秒内变化 | 判断边界 |
|---|---|---|
| worker26132 | CPU +19.188s，读 +1,165,217,792B，写 +658,931,744B；RSS 9,477,218,304B | 当前持续执行，非该窗口静止/只等待；约一个核心忙碌 |
| service18116 | CPU +17.859s，读 +2,234,000B，写 +44,496B；RSS 64,565,248B | 监督服务亦活跃；其高metadata调用不能仅凭CPU归因为writer |
| 唯一当前pending | 同一路径增长41,345,024B至8,535,863,296B；journal仍22,016B | 存储在推进；logical增长不等于已完成比例 |

任务现有资源收据仍显示Job峰值10,021,474,304B、硬限17,179,869,184B、host_pressure soft/stop均false；后续读取时盘空闲约358GB。两个样本只证明这20秒内的活动及当时资源余量，不证明更晚没有压力、也不提供ETA。

读取现有`run.log`、`scan_stages.json`、`scan_progress.json`和`work/tasks/.../task.json`：388/388 TU阶段已结束，snapshot状态VERIFIED，当前stage仍“报告生成与存储（单次发布）”。task为RUNNING，无已记录error、monitor_error或exit_code；未见日志重复进入此stage、显式失败或新建多个当前pending的迹象。这些是有限现有收据，不构成排除所有未记录异常的证明。

## 实际工作量及代码路径

诊断记录的41个顶层facts列表合计7,436,830条条目，包括1,534,856条unknowns、1,284,509条pointer_storage、1,208,050条accesses、1,007,376条mask_windows、491,011条functions、各491,009条control_flow和nvic_programs，另有16,567个变量及3,541个候选。这里是合并facts中的列表记录数，包含TU实例和相互引用；不是同等数量的独立业务函数，也不是SQLite最终唯一节点数或物理行数。嵌套字典、数组、证据和归档源码还会增加节点/边工作量。

实际canonical producer路径为：

1. `cli.py:730`根据当前review关闭/不准备packets走单次发布，跳过前置generate；`cli.py:784`仅调用本阶段的一次`report.generate`。`report.py:121`识别canonical目录后prepare，再进`scan_persistence.persist`。
2. `scan_persistence.py:195`先核验并归档实际输入，构建provenance；仅当正式`scan.db`不存在时调用`publish_scan`。`workflow.clean_report`只浅拷贝待去掉运行态字段的finding字典，静态嵌套证据继续共享，不是再深拷贝全部facts。
3. `scan_store.py:348`创建UUID命名的新`.pending`，SQLite foreign_keys开启、synchronous=FULL、64MiB page cache、temp_store=FILE，使用一个发布事务。唯一hash/关系索引和完整证据没有关闭。
4. `GraphWriter.put_roots/put`遍历facts、report及provenance。每个容器的每条有序边都递归编码/哈希，执行节点/边插入和索引查找；相同内容合并前还必须核对完整边。内置dict/list/tuple的稳定共享身份用文件支持的临时memo避免反复遍历；未知容器子类仅使用8192项有强引用的缓存，保证不误合并临时子对象。标量小值也有8192项缓存，其他通过SQL hash查询和精确内容比较去重。
5. 根构建后`_project`仍须遍历facts/report各列表，写records及symbols和选择性索引；随后提交、integrity_check、foreign_key_check。封闭文件的可选NTFS压缩还需真实全文件前后SHA/身份核对，最后才原子硬链接为正式`scan.db`。
6. 此后仍有ReviewStore、运行态/审计、saved状态及deep证据验证；`cli.py:789`之后必须执行发布后原输入闭包重新核验、最终完整性验收，才更新最终有效状态。

上述循环均受实际有限根、容器边、relation记录或SQL查询结果约束。当前单pending增长和原stage日志与单次发布路径相符，代码未见在此路径无条件重启完整generate/publish的循环。相等内容的精确去重仍可能先构建临时边再删除，SQLite页缓存/多索引/临时memo会产生远大于logical文件增长的I/O；这不能直接等同异常重复保存。没有读取pending表、stack或trace，故不能定位当前具体在facts根、report根或projection中的哪一步，不能确认实际累计节点/边、剩余比例或最终总耗时，也不能仅靠静态有限循环保证不会遇到数据相关性能问题。

监督服务的`studio/tasks.py:223`每次检查预算并写资源收据，每6个样本递归枚举当前scan文件以更新task_disk_bytes；该枚举以及严格路径检查是其metadata工作来源之一。当前样本中的高service CPU与该路径相容，但没有attach/调用栈归因，不能宣称已经证明这就是全部开销或提交优化结论。

## 尚未满足的门禁

核对时正式`scan.db`、manifest、scan_state、reviews.db和diagnostics/completion均不存在；`result_validity.json`仍为`analysis_valid:false / RUNNING`。因此完整大型发布、完整性/投影校验、归档后输入复核、最终退出状态及整个资源/耗时验收均尚未通过。当前snapshot VERIFIED是前一输入核对状态，不等于最终发布已完成。

已观察约80分钟的尾部发布本身是实际性能及用户等待缺口；本记录未定义未经认可的性能阈值，不把“仍在工作”写成性能达标。最终还需正式产物和完成收据、实际峰值/总耗时、退出后重新打开及查询体验证据。对于百万级记录，现界面仅显示阶段名，当前未提供可验证的发布百分比；不能以磁盘增长反推百分比或给虚假ETA。

本项遵照有界核对范围收敛，只记录事实、风险和未完成门禁；没有修改或中断任务。首次外部观察脚本误用PATH的MSYS Python而缺少psutil，在任何采样前退出；随后明确使用既有Windows CPython3.10及其已有psutil完成两样本，没有安装依赖或改变产品环境。

## 14:47 UTC后续有界样本

原控制器仍运行，另一次20秒间隔的进程/文件metadata观察保存为 `new-upgrade-v4/publication-observation-144742.json`。worker仍为26132，观察期间CPU增加7.047秒、进程读计数增加663805952字节、写计数增加13107456字节、RSS9477345280字节；服务18116 CPU增加18.016秒。唯一pending由10091462656增至10093993984字节，正式scan.db与manifest仍不存在。计数是进程I/O，并非物理磁盘吞吐或完成比例；本次没有数据库读取、attach、信号、源码或状态修改，也不能将活动写成发布/性能门禁通过。
