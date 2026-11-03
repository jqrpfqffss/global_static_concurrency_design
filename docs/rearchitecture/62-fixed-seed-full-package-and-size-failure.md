# 固定输入大型严格对照通过，含完整包尺寸未达70%

2026-11-04。此记录绑定原版e69固定seed0/date-epoch与1493c05（冻结v27）冷原生v12，不能改标成v34/v35的新原生扫描。原版388TU、4123输入与699引擎文件，候选388TU、4123输入与2043冻结文件前后哈希已分别核对；原版完整备份独立保留。

| 验收 | 实际结果 | 状态/证据 |
|---|---|---|
| 完整事实 | 原版与候选全部有序/有类型事实根均43153000056630428dd91c4af9787cda65c107f4690814e36b607e21de4696aa，差异0 | PASS_SCOPED |
| 完整规范化报告 | 仅沿既有执行包络/原标准化合同，两根均26af6df2f8a675ef2be0a25f2be4b45c807f1ba2a8cd21a4d7af72aa53ed52db，差异0 | PASS_SCOPED |
| 完整验证 | 两图SQLite完整性/外键/全部字节与节点哈希/完整投影深校验，既有比较器未修改、冻结代码差异0 | [完整比较与标准包](evidence/seed0-v12-full-comparison-package-v1.json)、[驱动](evidence/seed0-v12-full-comparison-package-driver-v1.json) |
| 完整标准包 | 4008043398B，SHA0e52a72c04fe66399241eae1406f8490a23b637465f13c76d7121c6613640b08 | 完整导出和独立根严格导入PASS |
| 导入绑定 | scan/project、完整facts/report、profile均与源一致，归档源码及必要审计对象完整校验 | 同上，`H:/ECRA-INAV-ROUNDTRIP-SEED0-V12/scans/native-golden` |
| 资源 | 完整比较+导出/导入17174.844s；导出3599.078s、导入2290.422s；2GiB Job峰值提交141062144B | 不恢复整个事实图；共享机械盘时间不作独占性能归因 |
| 含完整包实际物理占用 | 47665101856B→14363843800B，降低69.8650727%，目标≥70% | **FAIL**；[两次稳定计量](evidence/seed0-v12-retention-with-archive.json)、[摘要](evidence/seed0-v12-retention-with-archive-summary.json)、[范围](evidence/seed0-v12-retention-with-archive-spec.json) |

这里的G1只对上述真正独立的同输入生产者成立。此前事实根/报告Merkle元数据诊断单独保留，不以诊断替代完整字节验证。原始v10差异6项FAIL和本次新读取器仍运行的试验也不改写。15份保护区/提取/输入/Diff文件在v27与v34字节相同，见[保护区哈希](evidence/protected-core-v27-v34-hashes.json)；这仍不代替当前writer64MiB原生v13及新存储/消费者的完整实测。

原生before/after内存、耗时及输出峰值仍按[52号记录](52-fixed-seed-native-v12-completion.md)独立保留：e69 Job峰值29811765248B、15454.922s；1493c05峰值10687008768B、31846.532s，候选更慢，未宣称提速。两者运行在64GiB主机的受控Job，不是32GB物理机验收。producer输出峰值与后续归档临时/导入范围分别记录；完整全策略历史瞬时峰值未补造，因此G4不能仅凭最终尺寸改成全门禁PASS。

原始完整包位于`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/inav-seed0-v12-comparison-package-v1/inav-seed0-v12-full.ecra-report`，保留作标准协议与后续编码对照，不删除有效数据以凑目标。后续[BZIP2完整编码试验](64-complete-archive-compression-adr.md)只改变ZIP封装，原包、manifest及每个原始文件字节须全部保留和核对；未完成严格导入/新计量前，不宣称70%达标。

实际v30包读取本次完整原生包的前三组已通过（5访问/113冲突/5423边及1486个有界API页），随后调用见证使用默认5秒断言失败，原件[保留](evidence/native-inav-evidence-ui-v30-v2-failed.json)。新控制器等待真实第一页及120秒请求上限，在实际v34包重验，尚未结束；不能把前三组或旧比较图6组冒充完整新版原生GUI通过。

当前仍未关闭：v32 writer64MiB冷原生v13的完整最终对照、新512MiB读取试验、大型GUI余项、G4尺寸与完整峰值、其他G2工程（用户延期）、物理32GB/第二PC/干净离线/DPI和工程师UAT，以及生产强写隔离/dirty快照/全根迁移/不变确认自动继承等代码缺口。


后续v34实际重验6组全部通过，完整边/见证/未知NVIC及真实归档RMW源码均已核对，见[native-inav-evidence-ui-v34-v1](evidence/native-inav-evidence-ui-v34-v1.json)及[63号补充](63-frozen-v34-acceptance.md)。原v30五秒等待失败保持不变；通过的是新一轮实际验收，不将旧失败倒写。


2026-11-04后续实际结果：[完整压缩包严格导入及稳定计量](65-complete-compact-archive-retention.md)已通过，保留策略最终降低71.6497%；旧69.865%FAIL及原包保留。完整G4峰值、新生产者/读取器、第二PC/UAT仍未关闭。
