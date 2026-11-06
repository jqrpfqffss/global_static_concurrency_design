# 保存后完整比较的内存验收与当前边界

起点为`optimize_ccc@b09ca1a`干净工作区；115号证据已以`a76a180`推送。下表的v72是该起点的实际冻结修改集，3975文件清单SHA为`c9547ef17552255340fc6a4fa3a6321d46013ec14695c28b967afea686d00d1e`，不包含后来开发的CMake V3。

| 阶段 | 实际实现/版本 | 测试/场景 | 状态 | 证据 |
|---|---|---|---|---|
| Phase 2/3 局部 | 完整双摘要按记录建立私有SQLite索引；原summarize/compare与传播规则不变 | 冻结v72完整1547项，1545 PASS/2联网opt-in SKIP，3103.962秒；源与独立副本全部SHA不变 | PASS_SCOPED | [最终收据](acceptance/full-regression-studio-v72-final.json)、[完整日志](acceptance/full-regression-studio-v72.log) |
| Phase 2/3 局部 | 独立无缓存全量先完成再合并当前事实 | 相同当前输入的真实小型原生扫描、弱引用生命周期及注入损坏阻断；包括完整比较、缓存/固定字节Diff等34专项 | PASS_SCOPED | [34项收据](acceptance/native-cold-diff-reader-v72.json)、`tests/test_native_sequential_verification.py`、`tests/test_diff_summary_store.py` |
| 大型保存后消费 | 原INAV权威库与778,008,324字节原完整摘要，原方法/外存方法各独立自有Job | 原库前后SHA一致，两份完整comparison.json全部字节一致 | PASS_SCOPED | [成对最终收据](acceptance/whole-diff-restoration-v72-final.json)、[新路径](acceptance/whole-diff-restoration-v72-selected.json)、[原方法](acceptance/whole-diff-restoration-v72-full.json)、[实际完整输出](acceptance/whole-diff-restoration-v72-comparison.json) |
| Phase 4 CMake | 新V3准备/封存、路径/配置/SDK/追踪保护 | 较早v73专项79项为76 PASS/3 FAIL，浏览器在Ninja工具链接的预检查失败 | FAIL，保留 | [专项失败收据](acceptance/working-cmake-memory-v73-failed.json)、[原日志](acceptance/working-cmake-memory-v73-failed.log)、[浏览器失败](acceptance/browser-working-cmake-v73-failed.json) |
| Phase 4 CMake 修复 | 监视不可变SDK副本，原工作树/Git每屏障完整核对；修复目录重命名保护、工具身份与旧提示；接入真实停止后恢复 | v74专项102项为101 PASS/1旧错误提示断言FAIL，真实Chrome 8组PASS；v75完整1561项为1556 PASS/2 SKIP/2 FAIL/1 ERROR，揭示无关旧别名问题 | 部分PASS，原FAIL保留；不能称完整通过 | [CMake逐版验收](119-guarded-cmake-acceptance.md)、[v74收据](acceptance/working-cmake-v74-failed.json)、[v75收据](acceptance/full-regression-studio-v75-failed.json) |

## 成对资源读数

输入权威库为`H:/ECRA-NATIVE-A13-SEED0/scans/native-golden/scan.db`，两轮前后SHA均为`4549110d23bfb9ed3c78d5ea686fbeeb94e9e140eac4b88974288c25bd4e7913`。基准摘要SHA为`001c02b85c0953787057ee3a8a6b110ec447e0e22f944cd28966164d2540f108`。比较脚本为`scripts/validate_native_diff_reader.py --operation diff`。

| 指标 | 原完整恢复方法（v72 full，32GiB Job） | 外存比较（v72 selected，8GiB Job） |
|---|---:|---:|
| Job提交峰值 | 27,140,870,144 B（25.2769 GiB） | 1,631,346,688 B（1.5193 GiB） |
| 进程树RSS采样峰值 | 26,991,595,520 B | 1,629,634,560 B |
| 进程树私有提交采样峰值 | 27,140,870,144 B | 1,623,482,368 B |
| 含原库SHA后验的观察耗时 | 2041.312秒（34.02分钟） | 2677.125秒（44.62分钟） |
| 输出目录采样分配峰值 | 1,974,800 B | 1,892,028,472 B |
| 最终输出分配 | 1,946,128 B | 2,544,152 B |
| 完整比较输出 | 892 B | 892 B |
| 完整输出SHA | `8c5a97824be8442b8a8d05f35d6f88761dadde2bc5ae6d187289e575260506c4` | 相同 |

该同源实验Job提交峰值降低93.9893%，耗时增加；用临时磁盘换取内存，不能宣称加速。成功后只移除本次私有且无结果引用的派生索引，原权威库、摘要和历史未删除。两个Job在64GiB Windows主机上先后执行，另有测试共享主机；时间不作独占性能结论。磁盘采样不含MFT/ADS、瞬时峰值或删除后仍打开文件，不代表完整G4。

**此轮没有修改INAV源码**，因此全部比较输出虽完整，仅892字节且没有变更影响项。它证明完整保存后读取/比较的这条路径，不证明有改动时的大型影响图输出峰值，不证明当前活facts/report共存的峰值，也不证明完整新原生Diff/恢复、32GB物理机或全部G3。独立全量的生命周期测试同样不能代替大型Job实测。

## H3与后续工作

v72的独立全量参考摘要仍写在正式扫描目录内。当前后续修复把它移到独立`work/diff-comparison/full-reference-*`，成功后保存完整校验的SHA/字节数审计，再只移除这份无引用的本次派生摘要；失败继续保留完整参考及双侧差异诊断。原PASSED字段、变量数、重新提取数与比较规则不变。该修复已在真实顺序验证/损坏注入等25项服务回归中通过，但v72收据不为后来修复背书；须以当前冻结测试为最终依据。原始[25项日志](acceptance/working-retry-services-v74-exploratory.log)保留，尚不是该修改集完整回归。

最新已完成的真实冷原生扫描及完整facts/report对照见[115号](115-final-large-read-and-cold-acceptance.md)：生产者冻结v66、388TU、4123输入、0缓存命中，全部事实/报告0差。它没有改标为v74生产者。新生整轮大型Diff及恢复内存继续待验。用户延期的其它G2、32GB真机、干净离线电脑、Windows原生高DPI、真实模型及人工UAT均保持NOT_VERIFIED，跨环境严格报告FAIL保留且比较规则未放宽。完整重构仍未完成。

本机工作根：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`。v7受控开发中断见[原收据](acceptance/working-cmake-v73-v7-interruption.json)，不计PASS。当前可复核的旧Portable仍为[114号v71](114-portable-v71-typed-cold-reader-acceptance.md)，不包含后续CMake工作字节或双摘要外存实现。
