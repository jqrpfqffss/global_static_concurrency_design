# 空间策略、真实文件压缩与实际GUI闭环

2026-11-03（北京时间）。[实施前合同](42-native-storage-compaction-implementation.md)；本阶段源码已接通，完整重构仍未完成。后续v27实包与新大型冷原生必须分别验证，不借v25收据。

| 功能/验收 | 实际结果 | 文件/证据 |
|---|---|---|
| 按新任务固定策略 | 默认auto/可选off，独立settings、revision冲突、损坏原文备份、任务启动快照；运行中GUI保存只影响下一任务 | ecra/storage_policy.py、studio/tasks.py、task_worker.py、scan_persistence.py |
| 无损整理 | 仅已完成实际Worker、本轮实际TU key的载荷、新私有scan.db；独占句柄、最终路径、单链接、逻辑长度/身份及前后全SHA；非支持显式SKIPPED；失败保留未发布现场 | ecra/windows_storage.py、storage_compaction.py、cli.py、scan_store.py |
| 新数据库发布 | 全部SQLite事务关闭且原完整性/外键检查通过后压缩私有pending；之后原独占原子发布。已发布归档/人工库不进入压缩；未关闭同步或减少校验 | tests/test_storage_compaction.py |
| 专项/API | 首轮12项中1故障注入路径比较错误保留；修正后13项全过；再与现有API/资源/图/seed合同联合56PASS，29.867s | [联合收据](evidence/storage-compaction-focused-v2.json)、[原失败](evidence/storage-compaction-focused-v1-failed.json) |
| 真实F030全字段 | 37.032s，完整facts/report有序、类型敏感差异0，原输入/99个后端文件不变；2PARTIAL/2PARSED均保留，只有2PARSED缓存 | [原生完整收据](evidence/storage-compaction-native-exact-v2.json) |
| 原生控制失败 | 首轮误要求四个TU都可缓存，实际2PARTIAL应不缓存；完整原生输出保留，改控制器后在新v2数据根重跑 | [保留原失败](evidence/storage-compaction-native-exact-v1-harness-failed.json) |
| 实际Chrome/启动器 | 源码版8项全部通过：保存读回、OFF任务中改未来AUTO、重启、下一真实AUTO扫描、真实分配量、导出到独立Viewer完整根相同、冲突拒绝、显式备份修复；原输入和后端字节不变 | [GUI v3](evidence/browser-storage-policy-host-v3.json)、[截图](ui/screenshots/storage-policy-host-v3) |
| 实际UI修复 | v1下拉框名称不精确，补明确aria-label；v2修复成功后details自动合拢隐藏保存提示，改为保留用户展开状态。两个失败不覆盖 | [v1](evidence/browser-storage-policy-host-v1-failed.json)、[v2](evidence/browser-storage-policy-host-v2-failed.json) |
| 完整回归/Portable/大型 | 尚需新冻结1369项完整回归、实包及同d1bc配置/seed0/日期epoch的新大型原生；当前不能关闭G1/G3/G4/G7/G8 | NOT_VERIFIED，原G1/G4失败仍保留 |

| F030本次新文件 | 数量 | 逻辑字节 | 压缩前文件分配 | 压缩后文件分配 |
|---|---:|---:|---:|---:|
| 新权威库 | 1 | 8962048 | 8962048 | 5971968 |
| 全部实际Worker | 4 | 1863304 | 1871872 | 516096 |
| 实际可缓存TU载荷 | 2 | 579197 | 581632 | 176128 |

这是该小工程文件级结果，不是完整保留策略的降幅或大型70%达标证明。压缩计划只指向本次拥有的新文件，黄金/已有归档/人工库不进入计划。原输入实际校验为全SHA/size/mtime，不冒充完整ACL/MIC审核；关闭策略跳过软件主动压缩，保留用户既有文件系统属性。尚未实现已发布库重写、VACUUM整理或全量根搬迁。物理32GB、50GB真实GUI清理、第二物理电脑、干净离线PC、原生DPI、联网OpenCode及工程师UAT继续待验。

UI维持现有导航/主布局：在独立数据根panel折叠显示“新扫描空间策略”，真实数据占用逐类显示逻辑大小与实际文件分配，未知为“未测量”，不以0替代。文件身份去重使用临时SQLite账本，结束关闭并回收；采样不会读取用户文件内容，明确排除目录/MFT/ADS及本次账本。

复现：`py -3.10 -B -X utf8 -m unittest tests.test_storage_compaction tests.test_studio_api tests.test_studio_resource_policy tests.test_scan_store tests.test_bounded_extraction tests.test_extraction_runtime_cache -v`。GUI使用`scripts/validate_storage_policy_ui.py --config <获准F030配置> --work <全新外置目录> --evidence <全新证据目录> --allow-external-toolchain`；打包后以`--engine <实包目录>`明确运行。原始trace与日志位于各次外置work/evidence，含会话资料的trace不纳入公共证据。

最终排版补验：占用类别名称完整单行、MiB与原始字节分层显示；等待实际采样完成再截图。新v4整组8项再次全部通过，[v4收据](evidence/browser-storage-policy-host-v4.json)和[最终源码截图](ui/screenshots/storage-policy-host-v4)保留。不是高DPI或大型空间场景验收。

最后能力边界修正：先识别不支持压缩的文件系统，再要求NTFS文件ID接口，避免把不支持文件系统的身份接口当作实际I/O损坏。14项专项重新全部通过，2.913s，见[最终专项](evidence/storage-compaction-focused-v3.json)。非支持分支为真实NTFS文件上的能力注入，物理FAT/UNC待验；须纳入新冻结1369项完整回归。
