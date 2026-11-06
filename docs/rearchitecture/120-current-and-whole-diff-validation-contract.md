# 当前活数据与整轮Diff/恢复：独立测量合同

2026-11-07状态更新：[123号](123-v78-full-regression-and-native-start.md)已收齐冻结v78完整1568项PASS（1566 PASS/2联网SKIP，0失败/错误）。以下两份任务均已在新正式数据根实际启动并受16GiB Job约束，已观察存活worker及后代活动；当前侧正在原黄金依赖快照，整轮正在真实基准CMake准备。它们的最终语义、峰值和恢复仍NOT_VERIFIED；下文等待条件是实施前合同，不能把已启动当成最终通过。

[118号](118-memory-comparison-final-acceptance.md)已经证明保存后的完整双摘要消费，不能替代扫描当前facts/report仍驻留时的峰值，更不能代替含基准准备、真实改动和恢复的整轮原生Diff。本段把这三种范围严格分开记账；当前仅前一项有最终大型PASS。

## 同一原黄金输入的当前引擎

冻结v78为4037文件，manifest SHA `113465220a07a2ffcb354f07d761d9fecab2beab68b25fe345ec48126e7351cd`。独立控制器等待该版1568项完整回归实际PASS/2联网opt-in SKIP后，才在新`H:/ECRA-NATIVE-L78-SEED0`启动原4123固定输入、388TU、零继承缓存的正式冷原生扫描，16GiB自有Windows Job。

外部观察器仅在实际`analyze`返回、完整当前facts/report仍驻留时，额外调用生产`compare_spooled(lambda: summarize(...))`，并要求完整输出SHA匹配[118号892字节原输出](acceptance/whole-diff-restoration-v72-comparison.json)。原报告随后原样返回，正式发布仍须通过；再以原完整有序、类型敏感比较器核对全部facts/report，刷新报告和读取最大完整Packet各使用独立2GiB Job，原权威库与全部原输入/引擎在前后完整SHA核对。

这是**显式加观察的实际冷原生扫描及同源当前侧消费者**，没有源码改动，也没有新的Git pin/基准准备，因此不能称整轮Git Diff。控制器不改冻结应用、比较器、原数据根、状态指纹或黄金清单。v76/v77队列均在启动前主动停止，以便改用包含包内兼容修补及121号ELF/MAP路径绑定的v78；原停止状态保留，不能计为大型PASS。

最终收据为工作根下`inav-current-published-native-v78-live-queue.json`、`inav-current-published-native-v78-live/execution.json`、`live-current-comparison.json`、完整对照及后续消费者收据。它们尚未收齐时，状态为NOT_VERIFIED。原已完成冷原生生产者仍是[115号v66](115-final-large-read-and-cold-acceptance.md)，不改标为v78。

## 有真实改动的整轮Diff与TU恢复

新建独立`H:/ECRA-WHOLE-S78/firmware`，完整复制获准公开INAV的全部已跟踪工作源文件，保留许可；在全新自包含Git仓库建立两份完整提交。该工作负载保留完整源码，基准是已获准的固定工作字节，当前版在实际参与H743编译的`uartIrqHandler`中增加一个`volatile uint32_t`计数器和真实递增访问。完整原补丁、两版SHA和输入清单保存。不是向事实库注入假变量；这份私有固件从不部署到目标板，也不冒称原仓库完整历史或另一个独立G2工程。

原黄金源与Git保持；所有CMake、ELF/MAP、Git工作树、Clang产物、缓存和扫描库在独立数据根。首次真实预检查`H:/ECRA-WHOLE-P78-SEED0`因旧ELF/MAP路径缺口明确FAIL；121号修复后在独立`H:/ECRA-WHOLE-P79-SEED0`实际重跑，388TU全部输入检查PASS，672.406秒，原固件/Git不变。正式测量使用全新`H:/ECRA-WHOLE-D78-SEED0`，不能继承预检查TU缓存或旧扫描。完整原`MATEKH743.elf`目标、ELF/MAP闭包及全部实际TU保留，不能删掉显式闭包来通过。

| 实际步骤 | 通过条件 | 状态 |
|---|---|---|
| 全部源码导入、实际编译目标预检查 | 完整两提交及源码原件核对，真实CMake/Ninja/ARM编译和依赖计划通过；新正式根仍不存在 | PASS_SCOPED；[实际388TU准备](acceptance/managed-build-closure-inav-v78-preflight.json)，不是并发分类 |
| 整轮首段 | 等冻结v78完整回归与真实预检查均PASS；在16GiB Job用公开`run_canonical(..., scan_mode='diff')`完成完整基准；两个真实当前TU已提交后显式KeyboardInterrupt | WAITING / NOT_VERIFIED；中断不是扫描PASS |
| 正式恢复 | 同引擎、配置、数据根、原输入；旧进程确已退出，旧扫描未发布；使用新scan_id，重新验证原TU缓存及完整原生链路 | WAITING / NOT_VERIFIED |
| 完整结果 | 独立无缓存全量state=PASSED、分类/语义0差，至少388TU及至少2缓存命中；实际新增计数器有真实访问及DIRECT_CHANGED影响，原基准库/固件/Git和冻结引擎不变 | WAITING / NOT_VERIFIED |

观察器只注入明确的中断点，没有替换事实、分析、摘要或比较算法。恢复重新运行全局分析，不是恢复任意求解器内部状态。控制器前后核对完整原始源/Git以及所有冻结引擎文件；保存第一份已完成基准库SHA，要求恢复后原库仍不变。任何FAIL、中途资源停止或未收齐最终证据都不能计PASS。

工作根下`whole-native-inav-v78-r2-queue.json`是状态入口，首段/恢复各自`execution.json`包含Job峰值、进程树RSS/提交、主进程、系统可用内存、主机分页及磁盘采样。分开保留第一段和恢复耗时/临时磁盘；不能把恢复耗时称冷扫描提速。此轮没有原旧实现整轮对照、32GB物理机或全部G4物理峰值证明，仍不能把118号保存后25.28→1.52GiB填到整轮前后表。

准备中的原v78私有克隆因复制只读属性导致写入自建改动失败，后续预检查又正确拒绝浅历史布局；两份FAIL记录及私有目录保留。新v78创建另一套独立完整两提交仓库，没有移除旧克隆的浅历史标记、放宽Git布局门禁或覆盖旧历史。

## 门禁边界与复现

以上是同一64GiB Windows开发主机上的受限Job测量，另有测试共享资源；不计物理32GB电脑或独占时序性能。磁盘为文件分配采样下界，不含MFT/ADS、瞬时未采样值及删除后仍打开文件；原始共享缓存/构建与最终归档需分别记账。其它G2、干净离线电脑、人工UAT和原严格跨环境报告FAIL保持原状态。

工作根：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`。实际控制器为`run-current-inav-live-v78.py`、`measure-native-current-live-v78.py`、`prepare-whole-inav-v78.py`及`preflight-mapped-inav-v78.py`、`run-whole-native-inav-v78-r2.py`和`measure-whole-native-diff-v78-r2.py`。它们是普通Python验收控制程序，不是外部编码代理。均需本机冻结输入/工具，使用新独立输出；同名目录和旧收据不可覆盖。完整收据齐全后另立最终验收，不在本合同提前改为完成。
