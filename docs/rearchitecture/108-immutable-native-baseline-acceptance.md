# 原生基准重新生成与TU恢复验收

承接已推送`26e164e`，先记录[107号合同](107-native-baseline-regeneration-contract.md)，再修复真实CMake专项暴露的旧库/新检查点不一致。仍仅改`git_diff.prepare_base`及测试；原30个规范化、摘要、指针目标、影响闭包函数AST不变。没有改分析器、弱化检查点或覆盖旧指纹。[源码核对](acceptance/native-baseline-protected-functions-v66.json)。

| 阶段 | 核心实现 | 文件 | 场景/测试 | 结果 | 证据 |
|---|---|---|---|---|---|
| 正式基准失效重建 | 每次失效使用新权威库目录；旧库/旧pin保留；相对索引在全部准备成功后才原子更新 | `ecra/git_diff.py` | U04/U08、G1/G5/G6；真实CMake宏1→2，基准数组4→8字节，原静态库不变，独立无缓存全量校验通过 | PASS | [8项冻结验收](acceptance/native-baseline-regeneration-v66.json)、[完整日志](acceptance/native-baseline-regeneration-v66.log) |
| 基准提取恢复 | 按固定基准SHA隔离、原完整键校验的共享TU缓存；新目录回到全局入口 | 同上、`tests/test_native_diff_summary_cache.py` | 真实2TU提取后合并前中断，再到新权威库；2 hits/0 extracted/0 corrupt；旧失败目录完整不变 | PASS，包含在同一8项中，不重复相加 | 同上 |
| 索引及发布失败 | 索引不是信任凭据；未知版本/bool版本/不同SHA/越界/未知字段拒绝；索引发布前故障保留旧索引和旧库 | 同上 | G5/G6；原显式数据库复用/完整原摘要键/损坏/污染/PARTIAL/复制期间改动继续测试 | PASS，8项总计246.946s | 同上 |
| 当前F030黄金 | 本版核心应用重新原生，保留原2 PARSED/2 PARTIAL，43文件内容/大小/mtime不变；原完整有序比较器未改 | 冻结v66，3855文件 | G1限定获准F030输入；事实/报告0差 | PASS，原生及完整对照总计39.531s | [收据](acceptance/native-baseline-f030-v66.json)、[执行信封](acceptance/native-baseline-f030-v66-envelope.jsonl) |
| 当前真实Chrome | 两次可见UI发起正式Diff、第二次完整校验后命中摘要、打开shared全部相关访问证据；完整包独立导入 | `scripts/validate_native_diff_cache_ui.py` | U04/U06/U12/U19/U22限定CSS1366×768；预置真实profile API，不计本轮四步向导 | PASS，5组/169.125s；280本地请求，0外部/控制台错误；33原文件不变 | [收据](acceptance/native-baseline-ui-v66.json)、[截图](ui/screenshots/native-baseline-v66/03-shared-evidence.png) |
| 较早完整回归 | v64精确源快照，含共享摘要/恢复观察器，未含本页后续重建补丁 | 冻结3835文件及独立副本 | 1521实际测试，1519 PASS / 2真实联网SKIP / 0失败；全部文件SHA不变 | PASS，3210.811s；不是最新代码全套 | [最终收据](acceptance/full-regression-studio-v64-final.json) |
| 当前完整回归 | v66固定3855文件及独立副本；8专项通过后才启动完整测试 | 冻结v66 | 当前1525项 | NOT_VERIFIED，等待最终汇总 | [带时间状态](acceptance/current-validation-v66-progress.json) |
| 大型原生 | 原v62中断保留，新恢复已完成388 TU并进入16566变量/3540候选发布阶段；后续原完整G1/刷新/Packet仍需收据。v66冷原生已排队，等待当前全套和前轮完整证明 | 冻结v62 + 冻结v66，二者分开记录 | G1/G2/G3/G4/G5 | NOT_VERIFIED | 同上 |

当前冻结manifest：`7140548fac9bb0a45fc8b541327bd89a8a0ff88421b235fa934f481d007c2abc`，起点26e164e上的本次改动。8项在独立复制目录执行，原冻结源和副本各3855文件全部SHA不变；F030与Chrome使用同份核心应用。后续文档更新不当作新的核心实现，也不把较早快照全套挪用为本版全套。

故障证据保留：[CMake首轮失败](acceptance/native-cmake-baseline-v65-failure.log)、[检查点摘要与两种旧库读法对照](acceptance/native-baseline-v65-mismatched-checkpoint.json)、[真实构建缓存变化门禁](acceptance/native-baseline-v65-rejection-reasons.json)。原完整读法和有界读法对权威库所得hash相同，state不同；不能据此改state迁就旧库。另保留[故障测试路径错误](acceptance/native-baseline-v66-fixture-failure.log)：缓存实际在既有`formal`命名空间下，测试修正为寻找该受控路径并精确选择固定SHA目录后，最终8项全量重新执行通过，没有改产品门禁。

实现沿用`WorkspaceResolver.for_results`和既有主缓存；不会递归搬动或覆写旧基准。索引只接受固定SHA及可选32位UUID目录名，仍须逐轮验证配置/引擎/事实/完整报告Merkle/源和真实预处理闭包。构建缓存实际变化时允许安全缓存失效，不强求命中。失败、PARTIAL及发布中断不更新最后已验证的索引。各扫描的独立摘要归档与完整基准证据仍能装入标准完整包。

剩余边界：首次冷摘要、当前侧摘要/完整Diff恢复仍有大对象，见[106号](106-cold-diff-summary-reader-audit.md)；CMake未提交输入仍未实现。真实TMFC/H747及独立DMA/回调/RTOS工程按用户要求待验；物理32GB、完整G4磁盘峰值、干净离线第二电脑、真实联网模型、Windows原生DPI及盲UAT未验。当前封存Portable仍[101号v60](101-portable-v60-functional-acceptance.md)，未将本次源码当作新包验收。**完整重构仍未完成。**

真实大工程既有前后数据仅按原范围保留：[97号](97-native-review-packet-acceptance.md)同一旧INAV最大Packet，完整恢复控制Job峰值19,405,934,592B，逐对象控制1,443,061,760B；完整Packet/输出文件相同。它不是本轮全扫描、冷Diff或磁盘收益。当前v62恢复与旧冷原生耗时不能拼成提速，当前v66冷原生尚待启动，扫描峰值/最终归档/耗时/全字段差异须等待最终收据，不预填PASS。

复现：`py -3.10 -B -X utf8 -m unittest tests.test_native_diff_summary_cache -v`；Chrome复现沿用105号命令，`--engine`选择本版固定源、`--work`选择全新的独立目录。需要真实ARM GCC/CMake/Ninja/Chrome及开发机已缓存的Playwright CLI；不访问额外客户工程、不调用模型、不把自建2TU当G2。
