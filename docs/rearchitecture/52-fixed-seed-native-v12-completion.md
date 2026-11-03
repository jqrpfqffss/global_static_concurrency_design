# 固定环境388TU冷扫描完成与归档前占用

本轮为冻结v27/1493c05的**新原生冷扫描**，不是JSON回放或v30新扫描。原版e69与新版共享固定配置SHA`d1bc911bfc315eb94e6d15177f7b33efa170363fa139763a703122d4ea435d04`、获准INAV 388TU、4123份输入、PYTHONHASHSEED=0及SOURCE_DATE_EPOCH=1793577600，保留真实原编译环境。4123输入及2043冻结文件前后完整SHA核对通过。原始黄金57773文件/46427693457B已独立复制、全SHA复核且源字节不变；只读为文件属性，不冒充物理只读挂载。

| 实测指标 | 原版seed0 v3/e69 | 新版seed0 v12/1493c05 | 状态/范围 |
|---|---:|---:|---|
| 冷CLI主体耗时（秒） | 15454.922 | 31846.532 | 均完成；与备份/构建/回归并发，共享同一物理机械盘，不作隔离加速归因；新轮实测更慢 |
| Job峰值提交B | 29811765248 | 10687008768 | 新版在16GiB受控Job内完成；原版32GiB限额；宿主64GiB，不关闭物理32GB G3 |
| 进程树RSS峰值B | 29559390208 | 10618966016 | 实采；不是进程主RSS与Job混算 |
| 进程树Private峰值B | 29741166592 | 10685960192 | 实采 |
| 扫描数据根采样逻辑峰值B | 46427693457 | 26757450325 | 采样下界；不含全保留策略、归档阶段峰值 |
| 扫描数据根采样分配峰值B | 46538663768 | 18794582808 | Windows实际分配API，排除目录/MFT/ADS |
| 最终扫描数据根逻辑B | 46427693457 | 23371645093 | 含本轮真实保留数据；新版透明无损压缩造成逻辑/分配不同 |
| 最终扫描数据根分配B | 46538663768 | 9210561128 | 不包含另表共享构建/最终标准完整包 |
| 完整事实/报告语义差异 | 完整原件已保留 | NOT_VERIFIED | 原版全图转换仍执行中；之后用未改规范化的严格比较器，差异非0即FAIL |
| 标准完整归档B | 非新版协议 | NOT_VERIFIED | 只在严格差异0后执行完整导出/导入，未拿小包替代 |

[完整原生收据](evidence/inav-canonical-seed0-native-v12-final.json)、[前后输入/引擎核验](evidence/inav-canonical-seed0-native-v12-driver-result.json)、[独立原始备份](evidence/original-seed0-backup-v1.json)、[阶段汇总](evidence/native-seed0-v12-stage-summary.json)。CLI返回2代表真实INCOMPLETE，analysis_valid=true、STATIC_SCAN_SAVED、snapshot VERIFIED；控制器核验成功返回0，不把部分覆盖改成全工程安全。

| G4保留策略实测（归档前） | 原版 | 新版 |
|---|---:|---:|
| 扫描根+同一有效共享构建，实际分配B | 47665101856 | 10336999216 |
| 降幅 | — | 78.3132757227% |
| 全文件两遍稳定核验 | PASS | PASS |
| 标准完整包是否计入 | 否 | **否** |

[完整路径/计量账本](evidence/seed0-v12-retention-before-archive.json)、[规格](evidence/seed0-v12-retention-before-archive-spec.json)、[摘要](evidence/seed0-v12-retention-before-archive-summary.json)。基准独立验证副本/程序文件不作为日常保留根，排除规则已在规格声明；没有删除有效历史或减小归档内容。归档前78.31%只通过该子范围，最终标准包及归档峰值未验，**完整G4仍未关闭**。旧v10六字段差异与40.2058%失败证据继续保留，不覆盖为PASS。

复现和队列控制器保留在`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`：`run-canonical-seed0-native-v12.py`、`run-original-seed0-backup-and-graph-v1.py`、`run-seed0-v12-comparison-package-v1.py`、`run-seed0-v12-retention-v1.py`。这些独占工作目录已存在，不能原地重跑覆盖；新尝试须使用新目录并保留旧收据。严格比较/标准包/导入/原生新包GUI继续等待，未把当前源码或v30包替换进已执行的冻结实验。
