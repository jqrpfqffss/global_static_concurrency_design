# 新扫描原生文件压缩：实施范围与验收计划

2026-11-03。实施前记录，继承[ADR-022固定合同](31-owned-storage-compaction-contract.md)。只处理本次新扫描私有文件；既有归档、黄金原件、人工库、目录属性和源码不改。v26冻结后独立实施，不借v26测试或原生测量证明本变更。

默认auto，允许off；设置存于独立数据根settings，原子保存、revision冲突保护和损坏原文备份，启动任务时固定所选策略。既有任务的策略不随后续保存变化。

Windows以独占句柄检查普通单链接文件、实际最终路径与文件身份，执行FSCTL_SET_COMPRESSION；完整前后SHA、逻辑长度及身份必须一致。只允许新scan.db私有pending文件、已经完成的实际Worker响应及本次实际TU key的缓存载荷。逐文件记录分配量、耗时、压缩状态和失败。非NTFS/非Windows/不支持/超过官方30GB单文件范围显式SKIPPED；不虚报为已节省。实际I/O或字节异常阻止新有效发布，上一有效归档保留。

本步先接入透明文件压缩，不实现已发布库重写或VACUUM整理；新建库仍由现有事务构造、校验后独占发布。该限制须保留，不能将其写成完成全部整理策略。所有完整证据、顺序、重复、恢复文件与缓存保留；压缩不改变SQLite/JSON协议或跨盘标准包内容。

UI按ADR-022现有设置区域追加策略表单，数据与共享的既有占用区显示中文类别、逻辑量和实际文件分配量，未知显示未测量。必须真实API、实际Chrome保存/重开/任务固定/真实F030产物/错误与输入不变验收后才标通过；当前尚未实现/验收。

后续实际接入与专项/真实GUI结果见[43号验收](43-storage-policy-and-native-compaction-acceptance.md)。仍需新冻结完整回归与Portable；大型70%门禁必须完整策略实测，当前40.2058%FAIL不变。微软接口合同：[FSCTL_SET_COMPRESSION](https://learn.microsoft.com/windows/win32/api/winioctl/ni-winioctl-fsctl_set_compression)（同步操作、单文件30GB范围）。
