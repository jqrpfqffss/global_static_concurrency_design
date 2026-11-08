# INAV发布尾部性能静态复核

范围仅为仍在运行的V4/core63a5、任务`f2f751073cb34310b8d8beb06673a501`的canonical graph writer、投影与校验。沿用[前次两样本观察](inav-publication-bounded-observation.md)及其原始JSON；本次只读取冻结源码、现有小收据和文件metadata，未打开pending数据库、attach进程、改输入、干预原collector或运行新基准。

14:35:14Z保存的`continuation/new-upgrade-v4/publication-static-cost-review.json`中，仍只有同一个`scan.db.d138929782794d12a4ec6fa1b4a31817.pending`，logical size 10,055,155,712B，journal22,016B，正式scan.db和manifest均不存在；11:47:53Z开始的阶段仍未正式发布。九个审查源码的SHA与启动前清单一致。持续写入不是性能通过。本次没有可证据支持的完成百分比或ETA。

## 可证明的成本

- 诊断41个顶层列表共7,436,830条记录。仅functions/control_flow/nvic_programs/pointer_storage/accesses/unknowns/mask_windows七类dict记录即6,507,820条，尚不含这些记录内部嵌套证据、其他34个列表、report和provenance。
- `scan_store._project:285–314`对每条object记录至少执行一次kind SELECT、一次标量字段SELECT、一次records INSERT。因此上述七类初次投影至少19,523,460次Python→SQLite execute调用；还不计符号插入、遍历数组的SQL、各索引B树维护和graph writer调用。这里不是实际trace计数，而是当前记录数乘以明确代码路径得到的下界。它不证明目前已经走到投影。
- `GraphWriter.put:219–277`更早还须对每个未命中身份memo的容器，单独查memo、插入节点、逐边递归/插入、查hash、更新或核对后删除、写memo。标量缓存为8192项；未命中需hash查询/精确比较。节点hash唯一索引、edge索引及文件支持的临时身份表都在写入过程中维护；64MiB SQLite page cache不等于9GB Python对象全部进入页缓存。该设计具有按完整边/标量次数计的高常数和索引查找成本，I/O不能用最终文件增量代替。
- `EvidenceProvider.validate(deep=True):480–518`在正式库生成后，还将执行第二次integrity/FK检查、完整node/edge哈希流扫描，并在另一个临时库调用相同`_project`重建全部records/symbols后逐行比较。对应七类记录的投影成本会再发生一次；这属于明确的完整校验路径，不是第二次完整权威graph保存。当前pending仍增长，不能把已耗时归因于尚未证实开始的deep校验。

以上证明百万级输入会触发数千万次小SQL操作及至少两轮投影，能解释一个明确的规模成本来源；不能据此精确分摊当前约数小时耗时，更不能把该下界当作实际执行进度。

## 未证实的假设与已排除方向

未找到此canonical/single_publication路径无条件重复调用完整generate/publish的循环；日志和唯一pending也未显示重启保存。GraphWriter内置容器的文件支持身份memo跨facts/report/provenance共享，防止相同对象反复展开；`json_rows.RecordDicts`返回的是实例的真实builtin `dict`，并非dict子类，因此不能将“未知容器子类回退到LRU”写成本次事实根因。`clean_report`仅浅拷贝finding字典，没有深拷贝全部静态证据。

相等内容但不同对象的容器确实需要先遍历并建立临时边，再hash比对/删除；代码可证明这条重复工作存在。但没有pending节点/边和对象身份数据，无法量化本轮发生次数，不能据此声称发生了异常对象膨胀或数据丢失。

`_validate_nodes`使用按node id及(parent,ordinal)排序的两个流，现代码未见逐node重扫全部edges的明显N²循环。`_project`按每个记录的parent取本记录字段，不是每条记录扫描全部关系；对应主键/child索引实际建在schema中。去重的完整边比较和索引维护会增加成本，但本次没有证明整体出现超线性失控，也没有取得足以修复某个具体性能缺陷的因果证据。

结论：已确认高调用次数、索引维护与重复完整投影的结构性成本；尚无证据将当前长尾定位为具体异常循环或给出安全的生产优化。大型发布耗时、最终空间/峰值、完整性校验、最终输入复核和再次打开体验门禁仍未通过。后续应保留实际完成/失败收据再定量，不以CPU/I/O活跃代替验收，本项不修改冻结实现。
