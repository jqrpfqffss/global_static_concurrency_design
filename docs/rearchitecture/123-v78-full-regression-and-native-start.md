# v78完整回归与大型原生任务实际启动

后续最终结果见[125号](125-live-current-native-and-complete-package-acceptance.md)：当前侧原生/G1/报告/Packet已通过；整轮已中断后恢复，最新大型完整包在途。本页两份任务的启动状态及`*-started.json`仅保留为原时间证据，不覆盖后续结果。

2026-11-07已收齐冻结v78最终回执：1568项中1566 PASS、2联网opt-in SKIP，0失败、0错误，6015.042秒。4037个冻结文件及独立测试副本全部SHA未变。原日志SHA256为`b722af51d07d453b0a8f3bf589efb726db4be7da818f026a69f9ad546b23a843`；版本由清单`113465220a07a2ffcb354f07d761d9fecab2beab68b25fe345ec48126e7351cd`固定。原收据scope沿用了旧`a76a180`文字，但真实`parent_commit`是`beb483e650eb35d73b97a8f1661ae841d4cee4d6`并带受控修改集；不修改旧收据，不把这段旧文字当成真实HEAD。

| 阶段 | 实现的核心功能 | 变更文件 | 测试/场景ID | 状态 | 对应证据 |
|---|---|---|---|---|---|
| Phase 2/3/4/6 后端完整回归 | 工作字节CMake全量/Diff、真实停止重用检查点、独立无缓存全量、私有参考摘要清理、外置ELF/MAP绑定及全部既有回归 | 0323368、beb483e、c807040后端修改；冻结v78及独立副本 | H1–H6/G5限定；1568项完整发现集，两个联网opt-in未执行 | PASS_SCOPED，不能据此关闭全部G1–G8 | [最终收据](acceptance/full-regression-studio-v78-final.json)、[原日志](acceptance/full-regression-studio-v78.log)、[实际控制器](acceptance/full-regression-studio-v78-controller.py.txt) |
| Phase 6 前端候选沿用后端 | v79只有SourceViewer目标行定位/最新请求更新；474个Python/测试/依赖源与冻结v78逐字节一致 | 450094c及v79包，当前前端有独立真实操作验收 | U12/U19/U22局部五组、包内34后端专项及八组CMake流程分别记账 | PASS_SCOPED，不把后端全套当v79全部UI实测 | [122号包与真实界面](122-portable-v79-and-source-target-acceptance.md)、[后端身份/包后验](acceptance/portable-v79-final.json) |
| Phase 2/6 原黄金当前侧 | 原4123固定输入、388TU、零继承缓存，实际冷原生发布；facts/report仍驻留时消费完整基准摘要，之后全字段对照、刷新和最大Packet | 冻结v78；新`H:/ECRA-NATIVE-L78-SEED0`，16GiB自有Job | 实际worker及后代已活动；启动观察时正在真实依赖快照，最终结果未收齐 | RUNNING / NOT_VERIFIED | [原队列启动快照](acceptance/inav-current-published-native-v78-live-started.json)、[实际进程观察](acceptance/large-v78-start-state.json) |
| Phase 2/6 整轮真实Diff与恢复 | 公开INAV完整派生工程、两个完整提交、真实IRQ计数器改动；先完整基准，再两个实际当前TU提交后中断，新scan_id恢复，独立无缓存全量核对 | 冻结v78；新`H:/ECRA-WHOLE-D78-SEED0`，16GiB自有Job | 实际worker及CMake已启动；不是小夹具或向数据库注入变量 | RUNNING / NOT_VERIFIED，尚未达到中断/恢复/最终核对 | [原队列启动快照](acceptance/whole-native-inav-v78-r2-started.json)、[实际进程观察](acceptance/large-v78-start-state.json)、[120号完整合同](120-current-and-whole-diff-validation-contract.md) |

两份正式数据根在此次启动前不存在，预检查根和旧缓存没有搬入；实际子进程受17179869184字节Job提交上限控制。启动观察记录了两份存活worker、后代活动和真实资源样本，仅证明开始执行，不是最终峰值、成功恢复或语义相同。整轮Diff用获准公开INAV工作字节构建私有两提交仓库，不能计作另一个独立G2项目；不改原黄金源/历史。

工作根为`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`。后续以原活动队列`inav-current-published-native-v78-live-queue.json`和`whole-native-inav-v78-r2-queue.json`及各自最终`execution.json`/对照/后验为准；仓库的`*-started.json`是本次不可变启动快照。原当前侧快照中的早期状态名含`CURRENT1525`，实际控制器门禁严格检查1568项最终PASS，未改成较小测试集。原生任务不因本轮文档或前端提交而重新开始。

已完成的保存后同源双摘要消费仍为[118号](118-memory-comparison-final-acceptance.md)：Job峰值25.2769→1.5193GiB，观察耗时2041.312→2677.125秒，输出目录采样分配峰值1974800→1892028472字节，最终输出分配1946128→2544152字节，两份892字节完整比较输出相同。该场景没有源码改动，最终输出不是标准完整归档，不能填入本次整轮前后表。最新当前侧与整轮的最终内存、磁盘、标准归档大小、耗时、全字段差异均仍NOT_VERIFIED；未捏造性能收益。

复验命令为`py -3.10 -B -X utf8 -m unittest discover -s tests -v`，精确重现须使用上述冻结副本、原工具和新的验收目录。v79 Portable入口为`H:/ECRAStudio-build-20261106-studio-v79/ECRA-Portable/ECRA.cmd`；SHA、真实截图和检查命令见122号。没有重复执行字节相同的34项后端专项或再启动一份完整1568项。

其它G2继续用户延期；32GB物理机、干净离线电脑、真实系统DPI、联网模型和人工UAT保持NOT_VERIFIED。跨环境严格报告FAIL及逐字段审计保留，原比较规则未放宽。未提交CMake的准入限制按117/121号保留，未证明命令和闭包不能静默接受。完整重构及Phase 6仍未完成。
