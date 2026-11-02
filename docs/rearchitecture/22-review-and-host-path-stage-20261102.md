# 人工确认提交与宿主深路径阶段（2026-11-02）

接续f445212。本阶段修复实际Portable暴露的问题；新候选的完整回归/实包结果须独立记录。完整重构仍未完成。

| 项目 / 场景 | 实现与实测 | 状态 / 证据 |
|---|---|---|
| v18冻结完整回归 | 1173文件，1295项中1293 PASS、2联网opt-in SKIP，1876.043s；源码/测试副本前后SHA一致 | PASS，限定f445212；[收据](evidence/full-regression-studio-v18.json) |
| v18实际软件包 | 1400.594s构建，目录/中文解压各27命令；main16、sample11、legacy-degraded6通过，但preflight组8项后快速撤销失败 | FAIL；[构建](evidence/portable-studio-v18-build-v1.json)、[首轮四组](evidence/browser-portable-v18-affected-first-suite.json)、[撤销失败](evidence/browser-portable-v18-preflight-failed.json)。不得标为可发布验收通过 |
| U17，提交回读时的备注丢失 | `studio/src/App.vue`：提交至回读结束期间禁用确认者/处理状态/备注；仅清除本次已提交的原文；保存绑定原扫描/对象，Esc关闭详情不丢事务 | 源码实际16项联测PASS，[收据](evidence/browser-review-write-pressure-v3.json)、[截图](ui/screenshots/review-write-pressure-v3/07-human-undo-retains-original-event.png)。新实包待验 |
| U17，真实写锁/关闭详情 | 独立reviews.db上BEGIN IMMEDIATE持写锁；真实POST等待时字段全部禁用、只读SQL确认尚未新增事件；Esc关闭详情后释放锁，事件正常提交；重开并撤销保留完整理由 | 16项收据中的实际写锁断言PASS；无API/页面模拟。首轮控制器错误用写连接读取历史而自锁，改用只读连接，[失败保留](evidence/browser-review-write-pressure-v1.json) |
| U18，真实构建与源码变化 | 独立教学副本Release→Debug后原生重扫，再修改RMW表达式重扫；两代旧人工SAFE都仅作为来源历史，当前RECHECK_REQUIRED，原库/原事件不变 | 源码15/16项流程分别通过；[15项](evidence/browser-review-inheritance-v2.json)、16项收据；教学输入不算独立第三类G2工程，不是工程师安全结论 |
| U02/G8，宿主深构建路径 | `ecra/compilation.py`复用既有短Junction机制，只缩短过深/非ASCII的Windows构建命令路径；保留宿主源码拼写和正式物理目录。实际>180字符外置构建路径经别名完成ARM ELF及原生入库 | 最终10项专项PASS、9.577s；[收据](evidence/final-review-host-identity-focused-v1.json)。之前源码16项已验证完整流程；其他真实CMake工程仍须原生等价验收 |
| H5，芯片/核心身份 | `scan_identity.py`和`ScanIdentity.vue`从已核验配置捕获chip/core，明确配置声明；不从名称/变量推断或用当前profile回填旧库 | 9项身份专项含芯片/核心及完整包往返；纳入10项收据；新实包界面待验 |
| 专项中断 | 65项中1项因测试运行时工作区被本次执行者修改，触发“分析实现已变化”并拒绝发布混用结果 | 该轮FAIL，不能计全通过；[收据](evidence/host-path-and-review-fix-focused-v1.json)。后续从冻结快照重跑完整套件 |

源代码联测中的SAFE决定只存在自有隔离教学档案，确认人和依据明确是自动化门禁验收，不冒充工程师UAT或真实固件安全结论。原获准F030配置/数据库/42文件以及仓库教学原件逐字节保持。源码首轮控制器导入遮蔽了urllib，服务启动检查前即失败，[原失败](evidence/browser-review-inheritance-v1.json)保留。

## ADR-017：宿主与Portable复用同一构建路径机制

实际宿主失败并非缺少Toolchain，而是245字符TryCompile对象目录加文件名超过ARM归档工具限制。Portable已有同目录短别名；宿主此前直接把长物理路径传入CMake。现在仅在Windows物理构建路径超过120字符或涉及非ASCII时采用同一`build_path(..., prefer_junction=True)`。不改变WorkspaceResolver、源码拼写、生成器、目标、变体、宏或编译参数顺序，不移动/重建原固件的正式build；别名元数据仍在已验证独立用户目录。

`test_actual_deep_host_cmake_keeps_real_files_and_arm_build_under_short_alias`真实运行CMake/Ninja/ARM/Clang，核对同一物理目录、真实ARM ELF、源文件不变和scan.db。它只证明该输入，不把samefile检查自动扩大成所有真实CMake工程的宏/生成文件语义等价；其他工程仍受G1/G2完整对照约束。原有分析算法及归一化规则未修改。

## G4只读诊断，不能作为优化收益

新增开发工具`scripts/profile_scan_database.py`显式使用本机已有DBSTAT-enabled SQLite CLI，1GiB Job、32MiB SQLite缓存、只读数据库、独立临时目录、有限查询期限，并记录工具版本/哈希和源SHA。它不是Portable运行依赖，不改写、VACUUM或清理任何库。[SQLite DBSTAT说明](https://sqlite.org/dbstat.html)区分B-tree页占用和未纳入的空闲/指针映射/锁页，测量也不包含文件系统元数据或其他扫描/缓存/构建。

| 实际输入 | 结果 | 限制 / 证据 |
|---|---|---|
| 原版INAV完整比较库17,831,825,408字节 | 9996.735s后主动停止只读诊断，进程峰值46,223,360字节；未获得完整B-tree表 | FAIL/不完整，[记录](evidence/inav-original-dbstat-v1-interrupted.json)、[停止原因](evidence/inav-original-dbstat-v1-controlled-stop.json)；不推断各表大小或G4收益 |
| 当前真实F030原生库11,317,248字节 | 完整B-tree逻辑页11,317,248字节，源全SHA/mtime不变 | [小工程PASS](evidence/f030-dbstat-v1.json)，不能外推大型工程 |
| INAV同库1秒查询期限 | 实际只读子进程被诊断期限停止，保留FAILED与safety_stop | [预期受控停止](evidence/inav-dbstat-deadline-v2-expected-stop.json)，不是完整空间测量 |

大型原生诊断仍在发布，当前16GiB内存目标已FAIL；严格全图与标准包往返只在真正完成、有效性及4123输入/890引擎文件后验通过后开始。全局外存工作集、H2生产写保护/dirty隔离、图形化数据根搬迁、巨大双旧来源迁移和全故障矩阵仍未完成；G2其他输入按用户决定待验，物理32GB/干净离线PC/第二台物理机/原生DPI/真实OpenCode及工程师UAT继续NOT_VERIFIED。
