# 修复版v23冻结与最终冷原生验收（进行中）

## 版本与范围

实际分支`optimize_ccc`，修复提交`c311aa4ec2f392ea66887e1ad502bf0e0c2825ac`。冻结1565个已提交文件，逐文件原始字节SHA验证；清单SHA `b390056b27c5855581a31bba8a0c358e10d34879957e4d710eae93dc3fa6920f`。冻结目录`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/frozen-engine-studio-v23`，与后续新增的验收控制器/文档分开。当前未宣告完整重构完成，也未推送本轮新增提交。

v23包含ADR-018/019/020的等价分配实现，以及[标量完整性修复与旧包勘误](27-scalar-byte-boundary-integrity.md)。v19/v20/v21/v22旧包全部保留，其旧测试不能证明新发现的攻击会被拒绝。v22没有运行十三组浏览器，不将其构建成功写成已封存实包。

## 当前实际状态

| 阶段 | 已实现核心功能/文件 | 当前结果 | 证据/边界 |
|---|---|---|---|
| 安全修复 | `scan_store.py`、`App.vue`、对应边界/恶意包回归、真实GUI负例 | 源码专项27 PASS；消费者43 PASS；实际源码Chrome17 PASS；同输入F030全字段0差异 | [阶段27](27-scalar-byte-boundary-integrity.md)，不代替本实包 |
| 完整冻结回归 | 冻结副本另复制运行`unittest discover`，1315项，源/测试副本前后SHA | 1313 PASS、2项真实联网opt-in SKIP，1953.141s，差异0 | [完整收据](evidence/full-regression-studio-v23.json)，不借用旧版计数 |
| 实际Portable构建 | `build_portable.ps1`、锁定wheel/离线网页/嵌入Python、目录与中文路径解包CLI | 构建exit0，490.265s；目录/ZIP各27命令完成 | 本机`portable-studio-v23-build-v1-result.json`；完整发布门禁未过 |
| 实包GUI | 四组受影响场景加九组其他场景，主流程包含新标量恶意包负例，13组112断言 | 全部PASS；另有5项实际异常退出恢复通过 | [封存收据](evidence/portable-studio-v23-seal.json)、[崩溃与重试](evidence/browser-scan-crash-recovery-v5.json)，物理DPI/干净机/UAT另验 |
| 升级续确认 | 同一原版完整INAV验证根，保留既有2000事件，v23实际GUI再逐项追加1000暂无法确认 | PASS，2012.094s；三次重启，共3000，原静态图SHA与原事件不变 | [第三批收据](evidence/browser-review-upgrade-third-batch-v23-v1.json)，不是新版大型原生或UAT |
| 大型冷原生 | 同一冻结源、原INAV配置/4123输入，16GiB Windows Job，新数据根，无缓存迁移/运行时注入 | RUNNING，实际388TU全部冷提取完成，正在全局分析；尚未有效发布 | [全部输入启动前校验](evidence/inav-canonical-allocation-native-v10-preflight.json)；本机`inav-canonical-allocation-native-v10/execution.json`动态记录，原G3 FAIL未关闭，不是32GB真机 |
| 大型完整对照/标准包 | 使用同一修复版验证器，原17.8GB全图与新库深检/有序全字段对照，再完整标准包导出/严格导入第二数据根 | WAITING_NATIVE，NOT_VERIFIED | 本机`inav-cold-v10-comparison-package-v1/execution.json`，不是第二物理电脑或G4通过 |

## 已有大型实测，不能混用范围

| 指标 | 原版真实INAV388TU | v8冷原生失败 | 旧retention诊断受控停止 | ADR-020完整388TU归并回放 |
|---|---|---|---|---|
| 状态 | 有效INCOMPLETE，exit2 | 无有效归档，exit3 | 无有效归档，32792.813s后受控停止exit15 | PASS_CONTROLLED_REPLAY_ONLY，不是原生扫描 |
| Job峰值commit字节 | 29805875200 | 17180913664 | 18449494016 | 新4556472320，原回放主进程峰值9913896960；作用域不同不可混作总收益 |
| 进程树工作集峰值字节 | 29537386496 | 17089003520 | 18452652032 | 新回放4539203584，含原生所有阶段的基准未测 |
| 采样输出逻辑峰值字节 | 46427649982 | 10773364118 | 36738867852 | 不测整个扫描策略磁盘 |
| 采样输出物理峰值字节 | 原轮未测 | 10782513584 | 36751906584 | 不测整个扫描策略磁盘 |
| 最终目录逻辑字节 | 46427649982，57773文件 | 10773364118，无有效库 | 29613200012，未发布现场保留 | 只读原始TU响应，不是最终归档 |
| 最终标准完整归档字节 | 原版多文件目录，不是新标准包 | 无 | 无 | 无 |
| 时间秒 | 12542.188 | 4810.313 | 32792.813 | 原归并453.594→新548.797；新控制器含全量哈希1618.047 |
| 全字段语义 | 完整原JSON、只读备份与完整图基线保留 | 无有效结果，不能比较为0 | 无有效结果，不能比较为0 | 全部原776输入字节不变、完整有序根与全部表指纹一致；不包含全局分类/发布 |

[完整归并收据](evidence/cfg-merge-replay-v1.json)、[旧诊断最终结果](evidence/inav-classification-retention-v2-final.json)及[输入/引擎完整SHA后验](evidence/inav-classification-retention-v2-postflight.json)。原版、失败冷原生与旧探针的历史记录按各自原引擎、预算、仪器和输入身份解释。H/I是同一物理HDD上的盘符，后台验收并发时耗时不能作独占性能归因。没有调低覆盖、改变预算来拼造G3或删除有效对象来拼造G4。

## 复现与交付位置

| 操作 | 命令/路径 | 使用条件 |
|---|---|---|
| 完整源码回归 | `py -3.10 -B -m unittest discover -s tests -v` | 从对应冻结源运行，记录真实计数与两个联网SKIP，不能把0项当PASS |
| 标量门禁 | `py -3.10 -m unittest tests.test_scan_store tests.test_report_package -v` | 边界/类型/恶意ZIP，原库与人工记录须保留 |
| 冷原生 | `py -3.10 scripts/measure_native_golden.py --engine <冻结源> --config <原INAV配置> --data-root <全新独立根> --work <全新诊断目录> --mode canonical --limit-gib 16` | 原配置SHA/4123输入/工具链/环境与原基线相同，全部前后验，不覆盖现有目录 |
| 全字段对照 | `py -3.10 scripts/compare_native_graphs.py --help` | 使用收据记录的原完整图与新有效库，不调整归一化/采样/阈值 |
| Windows入口 | `H:/ECRAStudio-build-20261102-studio-v23/ECRA-Portable/ECRA.cmd` | 已实际构建与完整本机实包封存；属于开发验收候选，完整发布门禁仍未过 |
| 源码失败提示实图 | [恶意包拒绝](ui/screenshots/scalar-tail-host-v1/11-unhashed-scalar-package-rejected.png) | 源码服务实图；v23实际包截图另行归档，不混用 |

## 尚未关闭

G3此前FAIL保持；新冷原生和物理32GB未验。G4全策略物理峰值/最终标准归档70%目标、完整大型full/Diff语义、生产H2写保护/脏输入隔离、全部故障矩阵、巨型双旧来源迁移、GUI数据根切换/搬迁仍未完成。其余TMFC/H747及DMA/回调/RTOS真实工程按用户指令`NOT_VERIFIED_USER_DEFERRED`；第二物理电脑、干净离线PC、原生WindowsDPI、真实OpenCode联网、工程师UAT继续NOT_VERIFIED。不因程序构建或自动化GUI子流程通过改变这些状态。

v23包ZIP 600439088字节，SHA `7021cfbf68e648ac85d58b5f430f9b57fafbddf56b30b1640faf1214f68c0f97`；29880个分发文件全部校验，121个实际运行时源文件逐项匹配冻结清单。[当前U01–U24](ui/25-user-scenario-status-v23.md)为12 PASS/12 NOT_VERIFIED，完整G7仍FAIL。后续[schema3候选](30-compact-sqlite-layout-adr.md)不包含于此v23包，其专项/新冻结验收单独记录。
