# Q207：工作字节准入与只读Git自写

本记录描述最终v4真实dirty失败后的两条独立因果链、最小修复和复验边界。v4固定提交cold/warm/独立full及恢复已通过，dirty首次失败仍保留，见[原轮次记录](continuation-diff-v4.md)。本修复不能倒填成v4通过。

证据目录：`output/quality-20261108/continuation/diff-final-v4/dirty-watch-investigation/`。新独立候选：`H:/ECRA-quality-20261108/continuation-diff/q207-candidate-source`。原主仓库、封存包、冻结v4及正在运行的INAV源均未修改。

独立review另发现既有`InputWatch.directory`注册前后的路径身份窗口，真实rename/replacement后watch可能仍附着旧目录；该反例在v4和fc候选相同，不能忽略。后续在独立v2副本修复，fc原冻结内容及反例不动；详见本记录末尾。原反例见`output/quality-20261108/continuation/q207-independent/watch-registration-identity.json`及对应review脚本。

## 问题与独立依据

| 编号/影响 | 当前实证、预期及原因 | 修复与已执行复验 |
|---|---|---|
| Q207a / 重要：首轮工作字节流程被自身准入通知阻断 | v4真实CDC dirty原退出3/45.484s，唯一`.git/logs/refs`通知在10:24:15.382Z，早于capture阶段10:24:22.799Z，落于watch安装后的严格权限遍历。独立自然fresh Git clone不修改时间戳，也在首次只读目录/权限遍历收到多个目录LAST_WRITE通知；文件字节、HEAD/索引不应因此被当作冻结后的业务修改。 | 初次严格准入时明确“尚未固定输入”；随后安装原全部mask/范围watch，再严格检查权限并watch.check。没有删除mask、忽略.git、吞掉通知或重置已安装watch。完整真实CDC新clone到达capture边界，正式watch保持UNCHANGED；后续真实源码ABA、HEAD、索引、ACL变化仍拒绝，准入→watch间改为低完整性标签由第二检查拒绝。 |
| Q207b / 重要：只读Git比较会改变调用者索引 | 在真实fresh-stat-index副本，原工作捕获Git argv/env虽GIT_OPTIONAL_LOCKS=0，普通diff仍创建index.lock/替换index，索引6349a89...→932aca46...；这不是原refs通知的原因。Git官方合同明确diff默认自动刷新stat缓存。 | 两个共同Git入口逐命令关闭autoRefreshIndex，不改用户全局/本地Git配置。最终用NUL numstat实际内容记录核对raw名称及洁净判断，保留0/0、binary、rename；两Git真实对照证明索引不改、内容变化不丢、stat-only不扩大Diff。 |

Git配置合同见[官方git-config的diff.autoRefreshIndex说明](https://git-scm.com/docs/git-config#Documentation/git-config.txt-diffautoRefreshIndex)。这里禁用的是索引自动刷新，不忽略源码改变，也不改变未提交源码策略。

## 自然准入通知的证据链

`read-only-real-clone-natural-acl-1.json`使用真实`git clone --no-hardlinks`、移除本轮副本remote、复制实际未提交头文件；没有设置旧时间戳。clone完成后才打开独立ETW和7类分mask观察器。

- 仅元数据读取时，`.git/logs/refs`收到LAST_WRITE/LAST_ACCESS通知；首次严格权限遍历又在refs/heads、refs/remotes及四个USB目录收到通知，原watch按真实通知拒绝。
- 产品watch mask始终是FILE_NAME、DIR_NAME、ATTRIBUTES、SIZE、LAST_WRITE和SECURITY，不含LAST_ACCESS。额外LAST_ACCESS观察器仅用于诊断，不是产品修复。
- `FILE_BASIC_INFO`显示focus的LastWrite、ChangeTime与attributes前后完全相同，只有LastAccess随后改变；真实索引SHA始终`56df41ac53ed59afc1ffde8be00b9ceb39a7fe8c796aa0ebf79c4da652e220c8`。
- 自有短ETW session已正常停止，未停止其他会话或启用全局WPR。`read-only-real-clone-natural-acl-1.etl`为24,379,392字节；按实际Create→Close区间关联到源目录的3678条事件全部来自只读诊断Python PID37152，1849 Create/1829 Close，未观察到SetInformation。refs通知紧贴同PID的只读打开/关闭。

这些证据支持“初次准入阶段的目录元数据通知被过早当作固定输入修改”。底层NTFS具体通知机制没有被逆向证明，不将推断写成操作系统绝对结论。旧时间戳的显式因果实验另存`read-only-real-clone-stale-1.json`，不是自然反例或验收依据；普通copytree（不复制NTFS安全状态）未重现原目录通知也如实保留。

`candidate-real-cdc-admission-1.json`在完整真实CDC的新Git clone上调用候选实际`working_cmake.prepare`。独立观察器仍记录首次准入通知；真正watch安装后保持UNCHANGED并到达capture边界。该检查在捕获前停止，明确不是完整CMake/扫描通过。

## 修复边界与回归

候选只修改：

- `ecra/working_cmake.py`：严格准入→原mask watch→再次严格权限校验及watch.check。
- `ecra/working_snapshot.py`：逐命令关闭diff索引自动刷新，保留既有Git隔离环境。
- `ecra/git_diff.py`：同样的只读入口修复，3处名称查询用内容判别；正常0/1与技术失败stderr分开处理。
- `tests/test_readonly_git_admission.py`：针对真实Git stat缓存、原索引、内容路径、捕获和Windows权限/通知边界的回归。

首次候选仅禁刷新时，正确的“stat-only stable.c不属于变化路径”预期失败；`q207-targeted.log`完整保留。没有扩大selected范围或改预期；增加实际内容判别后通过。只读参照使用真实Git plumbing patch，覆盖staged与dirty内容，不照抄ECRA当前返回值。

| 验证 | 原始结果 | 证据 |
|---|---|---|
| 同一独立合同对未修改v4的5条负向回归 | 3 FAIL、2 ERROR，8.494s；含索引改写、捕获失败与新clone准入错误 | `q207-baseline-v4.log` |
| 最终针对回归12方法 | 12通过，23.383s，0 skip；含真实source恢复写、HEAD/index/ACL、检查间低完整性标签、真实staging/dirty capture、正确路径和技术失败 | `q207-targeted-final.log` |
| 相邻旧回归52方法 | 52通过，111.822s；Git语义、patch、工作字节、版本API、独立Git、相对gitdir | `q207-neighbor.log` |
| 完整真实CDC自然clone准入 | 实际prepare到capture边界，正式watch未变化 | `candidate-real-cdc-admission-1.json` |
| fc候选阶段完整dirty C+ASM+header与独立full | 该阶段尚未完成，不计此候选通过；后续final-v6已独立完成 | [final-v6记录](continuation-diff-v6.md) |

## 冻结与大型normal full适用范围

候选core digest：`fc958d23d50c436f2fd7529000a9f46b887506ad82e62fe4db50e956ee17d2b9`。

`q207-candidate-frozen.json`逐文件记录SHA，patch为`q207-candidate.patch`（SHA `d22fcf6fb75cb05bfdfe96e63158a34a8e2c32778b36d907b4637f3ffd03c4d6`）。冻结后不再修改此候选，交独立复核及组合。

`q207-code-path-audit.json`对照v4确认仅3个生产文件的6个函数改变；静态判断、提取、向量/别名、保护/NVIC、编译集成、存储/发布、CLI、workspace等其余生产文件全部逐字节相同。git_diff的settings/summarize/compare/selected展示与current_context函数也相同。

正在运行的INAV为normal full、`include_uncommitted:false`、原工程root：`scan_persistence.py`的dirty capture分支未进入；`cli.py`的Diff pin/base/current分支未进入；原root的`validate_analysis_inputs`在隔离Git查询前返回。本修复不要求把与之无关的大型完整分析反复重启。

INAV仍只按其实际v4 `63a5...`版本记录，不能称为fc958...新引擎整轮通过；不改旧engine_tag、检查点或源。受影响的工作字节采集、准入和Diff查询合同必须在新组合字节上完成实际复验。最终便携包启动、浏览器缩放/系统DPI等各自的未验证范围仍独立记录。

## 独立review追加的注册身份窗口与v2闭合

原顺序为先注册目录通知，再打开目标及祖先的禁止删除句柄。review在真实FindFirstChangeNotification返回后、祖先锁之前强制真实线程时序，成功将source重命名并用replacement替换；后续严格权限检查通过，watch.check无信号，新source文件真实改写并恢复字节/mtime仍无信号。没有伪造API返回、快照、数据库或扫描结果。这是实际输入身份保护缺口，不能列为无关建议。

独立`q207-v2-candidate-source`增加第4个生产文件`ecra/guarded_cmake.py`修复：从稳定祖先到目标先持有NoDelete句柄，再注册原mask287；打开最终路径本身而非跟随新junction，用GetFileInformationByHandle的卷/文件ID及普通目录属性核对路径与句柄身份，注册前后均核对。任一API错误或stop只回滚该次新notification及新ancestor句柄，保留原有watch依赖的共享祖先；close完整释放。

- 最终同字节71方法143.105s通过、0 skip：包含原12针对、52邻接及7个身份/资源用例。7项中root/祖先真实替换时序、真实junction替换采用原生Windows操作；3种API失败及取消边界使用明确故障注入，验证已取得的真实句柄被回收，不冒充实际磁盘故障或完整任务恢复。
- delivery独立重放原具体反例：同mask287下rename被真实WinError32阻止，后续真实源码ABA被捕获，退出with后句柄表全空且目录可rename；独立19方法18.003s通过、0 skip。收据`continuation/q207-independent/final-v2-bind-identity.json`及相邻日志。
- v2完整真实CDC自然新clone再次调用实际prepare到达capture边界，原始初次通知仍保留、正式watch保持UNCHANGED；`candidate-v2-real-cdc-admission-1.json`明确这是边界验证，不是完整扫描。

v2冻结core `65c0fb3dbc29bda7ad74aeeadeb4666c6b1eeda545bc9521c3961f476eca7682`；四生产文件及两测试的逐项SHA见`q207-v2-candidate-frozen.json`，总patch SHA `748023a0d45d9cbfa1a4a8afe29f7f406743f4ff7f05a853e200406ea7ab4636`。原fc候选保留不修改。

统一final-v6已使用完全相同的四个生产文件，实际受影响完整dirty/独立full已在新根完成：39 TU全PARSED、245变量分类/语义mismatch各0，原退出2/INCOMPLETE保留；完整范围及限制见[final-v6记录](continuation-diff-v6.md)。其他静态/提取/存储生产文件仍逐字节同v4；INAV保持其原63a5版本记录，不能用本修复重标旧扫描。

## 主区旧Git回归暴露的版本差异与最终v3

主区V6有界smoke并未通过：65方法中“实际变化路径”和“仅stat改变的隔离树”两个合同失败，原日志`continuation/regression/main-v6-smoke/unittest.log`保留。旧PATH Git实际为`D:/git/Git/cmd/git.exe` 2.37.2.windows.2，之前便携对照使用MinGit2.56.0.windows.3。相同字节/索引/mtime fixture、两种安全配置模式的16行独立对照证明：旧Git的raw name-status/name-only即使用--exit-code也列出stat-only，较新Git省略；配置隔离没有改变结论。不能把新Git通过写成旧Git通过。

最终独立v3只再改`ecra/git_diff.py`：用NUL终止的numstat内容记录与raw路径/rename状态交叉核对；numstat两个Git均不会列stat-only，0/0真实rename、空文件和mode变化仍是有效记录，binary的`-`也保留。实际内容记录若未被raw记录覆盖、格式不完整或技术错误，明确拒绝，不能把它降为空Diff。raw与numstat都显式`--no-ext-diff --no-textconv`，与归档patch一致。

- 最终原有ReadonlyGit/权限/注册边界加新增内容案例：host旧Git25方法23.420s通过；portable新Git18方法22.689s通过。真实安全marker的textconv/external转换器在对照命令可执行，而ECRA查询不执行它、仍保留真正C修改。
- state独立复核最终SHA：32个真实产品case、两种Git与配置模式，涵盖mixed/staged/unstaged/delete/R100零计数/binary/空文件/纯mode/空格中文路径/converter；原主区两个失败方法用原aa585d测试字节在两Git均通过；8个真实invalid-ref错误拒绝。所有fixture索引字节最终一致。收据`continuation/q207-v3-independent/review.json`为PASSED_SCOPED_INDEPENDENT_REVIEW，实际exe/version/SHA另存于该目录。
- 首轮新增空文件测试把同时空增/空删预期为A/D，但Git --find-renames按相同空blob合法合并为R100。保留该失败日志，改为分别构造真实空增加、空删除输入；独立R100/0行案例仍单独保留，没有修改生产来迎合预期。首次77方法运行仍记录为76过/1 fixture失败，不改成整轮全过；最终所有受影响25/18方法已重跑通过。

冻结`q207-v3-candidate-source`相对V6精确只有Git模块及该回归文件两处变化。core `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`，Git生产SHA `216c6aa53dcfd8d5d21aa7d6fc23db12be12c8ed8b95ba8507c72c0a0df9cee0`，测试SHA `8b457aaa787a859e766f283dcd8d6da3dc0c891724b38f13ababf6392dcba18a`。逐项冻结及最小patch见`q207-v3-candidate-frozen.json`、`q207-v3-from-v6.patch`。

root已将此单Python差量与最新V7界面合成V8；主区V8有界55方法156.600s/0skip通过且源前后未变。V6真实CDC大SDK dirty已按65c0版本完成，不能重标为2b9e。最终ZIP实际解压后，包runtime、Windows-only初始PATH、小型真实ARM CMake full→Diff→独立full已完整通过：SAFE→SUSPECT正确，独立full的5对象分类/语义mismatch均0，全部5对象完整证据逐项相等、真实ELF/MAP/CDB保留，154生产SHA未变。所有原断言保留，明确是已知答案样例而非第四个公共工程；详情见[最终V8包验收](continuation-diff-v8.md)。
