# 中断恢复与原生Diff摘要缓存：限定范围验收

起点：`optimize_ccc@fc32c743554d40c3dc2f36eac0e6271ded57de24`，真实工作区干净。实现前合同见[104号](104-interrupted-native-and-diff-reader-contract.md)。未改分析器、Diff摘要/影响传播算法、判定或原黄金。

## 已实际执行

| 阶段 | 核心实现 | 代码 | 场景 | 结果 | 证据 |
|---|---|---|---|---|---|
| 恢复观察器 | 原任务确已退出、同引擎/配置/根，使用新scan_id和独立临时目录，原输出保留；正式入口重验TU缓存 | `scripts/measure_native_golden.py` | U08 / G5：真实2TU提取后合并前中断；恢复发布；改源仅重提1TU；拒绝活跃/未知所有者、不同配置/引擎、相同ID、已完成/已发布来源 | PASS，5项/38.258s | [收据](acceptance/native-published-recovery-v63.json)、[日志](acceptance/native-published-recovery-v63.log) |
| Diff消费者 | 完整报告Merkle/输入门禁通过后，命中路径使用有界投影；共享缓存跨scan_id复用，每个正式扫描有独立摘要归档 | `ecra/git_diff.py` | U04/U08 / G1/G5/G6：原完整摘要及键完全一致；命中禁止全量加载基准；损坏重建；历史归档不变；隔离源码污染及复制时篡改阻断；实际PARTIAL拒绝 | PASS，4项/104.652s | [收据](acceptance/native-diff-summary-cache-v64.json)、[日志](acceptance/native-diff-summary-cache-v64.log) |
| 关联回归 | 旧CLI摘要修复/污染阻断、观察器身份、PDH、正式发布/独立包/恢复、复核仅失败项、实际工作输入编译视图 | 原测试模块，未改期望放宽门禁 | U04/U08/U15/U19 / G5/G6 | PASS，26项/308.819s | [收据](acceptance/native-recovery-diff-targeted-v64.json)、[日志](acceptance/native-recovery-diff-targeted-v64.log) |
| 原路径F030黄金 | 当前核心应用重新原生扫描，原完整事实/报告严格有序比较；保留2 PARSED/2 PARTIAL | 冻结v64应用，原比较器未改 | G1：43原文件内容/大小/mtime不变；facts/report均0差异 | PASS，总控制耗时38.016s（含完整比较，非单独扫描计时） | [收据](acceptance/native-diff-cache-f030-v64.json)、[原执行信封对照](acceptance/native-diff-cache-f030-v64-envelope.jsonl) |
| 真实Chrome | 从任务页连续两次扫描，第二次复用摘要，打开真实shared访问证据，完整包独立导入 | `scripts/validate_native_diff_cache_ui.py` | U04/U06/U12/U19/U22限定范围；配置通过真实API预置，非本轮向导验收 | PASS，5组/156.781s；33源文件及首轮DB不变；254本地请求，0外部/控制台错误 | [可复跑收据](acceptance/native-diff-cache-ui-repro-v64.json)、[首轮独立操作收据](acceptance/native-diff-cache-ui-manual-v64.json)、[证据截图](ui/screenshots/native-diff-cache-v64/03-shared-evidence.png) |
| 独立全套 | 冻结3835文件并建立独立测试副本，实际发现1521测试 | 冻结v64应用/测试；新增独立UI控制器另验 | 完整回归 | NOT_VERIFIED，仍待最终汇总；不是1521通过 | [启动收据](acceptance/full-regression-studio-v64-started.json) |
| 当前INAV | 先审计上轮中断；相同冻结生产者、原4123输入/配置预检；新ID恢复正式扫描，随后完整G1/刷新/最大Packet | 冻结v62生产者 + 冻结v63观察器 | G1/G2/G3/G4/G5 | NOT_VERIFIED，已到388/388 TU及后续输入一致性验证，仍待全局分析/真实发布/最终对照；恢复不是冷提取计时 | [原中断审计](acceptance/inav-current-published-v62-interruption.json)、[带时间的进展快照](acceptance/inav-current-published-recovery-v63-progress.json) |

恢复观察器测试首轮暴露重复临时目录；修正为按scan_id独立目录。第二轮实际缓存/源变化行为已通过，但路径断言未规范化Windows 8.3路径，且测试误把原初始化证据格式预期为单独`7`；按真实完整格式`int shared = 7`和绝对解析路径修正后，五项完整重跑通过。未降低产品门禁。[第一次日志](acceptance/native-published-recovery-v63-first-failure.log)、[第二次日志](acceptance/native-published-recovery-v63-second-failure.log)保留。

Diff的原`summarize`、`compare`、schema=7和键维度均保持。正式缓存命中依旧重新验证引擎、完整事实文件、完整报告有序Merkle、源码/预处理/环境；CMake仍先刷新真实构建后验证。共享缓存可重建，扫描pin指向自己的独立归档；复制字节必须匹配此前验证的manifest摘要，复制期间变更拒绝发布。

[源码AST核对](acceptance/native-diff-protected-functions-v64.json)确认`git_diff.py`的31个顶层函数仅`prepare_base`改变，其余30个（包括完整摘要、规范化、指针目标与影响比较）未改。这是补充证据，不能代替真实G1。后续首次摘要构建的全维度迁移边界见[106号审计](106-cold-diff-summary-reader-audit.md)。

应用/测试冻结manifest为`e85d94587b4bf6fbcd7826d1f05b2cf4eaea600fae460b3c63594c05ae9b15a9`（起点fc32c743上的本轮已测修改）；F030、UI和独立全套均使用这份核心应用。新增UI控制器另行实际执行，未冒称它包含在此前3835文件中。首次CLI手工测试339本地请求/0错误，与独立脚本复跑254本地请求/0错误是两次不同受控工程记录，不相加为新的测试项。两次静态`MODELED_SCOPE_COMPLETE`仍独立于AI复核待办，不表示硬件已验证。

## 明确尚未完成

- **冷Diff**仍需按原方法完整恢复基准事实/报告以建立摘要，当前侧摘要、影响比较和完整Diff恢复仍有大对象；这次不称完整Diff已省内存。真实大型Diff及整个恢复链路资源峰值未验。
- v62上轮进程已不存在，无退出码/后验/完成收据，最后日志273/388，原因未知。旧队列的RUNNING是历史残留，不能据此宣称通过。保留原文件SHA，已启动新恢复任务，必须等真实发布和完整比较完成。
- v63恢复复用经原引擎验证的正式TU缓存，重新预处理；全局恢复回到完整分析入口，不是求解任意位置续算。原旧扫描目录未改写。
- 其它G2工程按用户要求待验；物理32GB、第二台干净离线电脑、联网模型、原生Windows DPI和5–8人UAT未验。完整G1–G8及本次完整重构仍未完成。
- 当前已封存Portable仍是[101号v60](101-portable-v60-functional-acceptance.md)，不包含此次源码改动，不把源码测试当作新包验收。

复现：在仓库执行`py -3.10 -B -X utf8 -m unittest tests.test_native_published_observer tests.test_native_diff_summary_cache -v`。仅在独立临时工程创建真实ARM提取/正式发布；不是新增G2项目。额外26项回归、当前原路径F030完整对照均已有表中真实收据；新源快照1521项全套仍待最终汇总，不预先标通过。

浏览器复现：`py -3.10 -B -X utf8 scripts/validate_native_diff_cache_ui.py --engine <本轮固定源码目录> --work <新建且独立的验收目录>`。开发验收机需要Chrome、npx及已缓存的`@playwright/cli`（本机0.1.23），脚本仅使用offline模式；Node/Playwright不进入产品包。脚本保留快照/真实任务ID/网络/控制台/截图/失败收据，以当前快照重新找ref后点击，不使用固定eID或模拟扫描API。新配置通过真实profile API预置，其后两次扫描、打开结果及变量详情均从可见UI触发。
