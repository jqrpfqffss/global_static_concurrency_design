# 当前干净回归收齐、新本版INAV正式原生启动

2026-11-05，承接101/102号。当前已交付v60功能候选、独立确认/搬迁/工作字节Diff/复核流程；当前INAV原生仍在运行，**整套重构未完成，不预先标PASS**。

## 已实际完成

| 范围 | 实际结果 | 证据 |
|---|---|---|
| 干净c374ebc当前应用全套 | 1512项：1510PASS/2真实联网opt-in SKIP，2722.338秒，无FAIL/ERROR；3792文件引擎及独立测试副本SHA不变 | [最终全套](acceptance/full-regression-studio-v61-final.json) |
| 正式发布观察器 | 新`canonical-published`模式，真实Job/预算租约，子进程调用原`run_canonical`包括最终发布，不预建scan目录/marker；必须是真实STATIC_VALIDATED manifest才算完成。旧legacy/canonical-body模式不变 | `scripts/measure_native_golden.py` |
| 两项观察器回归 | 2项PASS，8.072秒：实际1TU原生、完整库/manifest/临时边界/租约释放；声明输出不匹配时不创建假扫描，不碰其他根。明确是受控测试，不计G2 | [回归](acceptance/native-published-observer-tests-v62.json)、`tests/test_native_published_observer.py` |
| 真正获准F030完整发布 | 2GiB Job，28.843秒，Job累计提交峰值147,558,400B、RSS采样最大182,530,048B；55个有效宿主页率样本。实际公开发布包装及最终manifest检查通过，仍退出原INCOMPLETE语义 | [完整执行](acceptance/native-published-observer-f030-v62.json) |
| 同输入F030完整对照 | 与100号真实原路径扫描完整facts/report均0差，原比较器不变；不拿计数相同当等价 | [完整比较](acceptance/native-published-observer-f030-v62-comparison.json) |

新观察器只改测量/调用入口：父进程持有数据根活动和扫描预算，监测12/16GiB软/硬目标并给TU并行实际压力文件，接近硬阈值请求停止；主机保护只关闭本次自有Job。完整资源、主进程/进程树、系统可用RAM/提交、PDH宿主页率、磁盘逻辑/文件分配采样仍保存。RSS与文件磁盘是采样值，文件物理分配不含MFT/ADS，宿分页不能归因单一ECRA；不冒充物理32GB或完整G4。

## 新本版INAV：启动事实与未验收边界

[启动时快照](acceptance/inav-current-published-v62-started.json)只证明启动，不是完成收据。原4123项冻结输入SHA/大小/mtime预检一致；原完整配置SHA `d1bc911bfc315eb94e6d15177f7b33efa170363fa139763a703122d4ea435d04`、冻结输入DB SHA `a97d28ede111d9c8c26d23ae93b577aea0071b623b28c80dec8affe842428f91`均匹配。私有配置只换独立输出根，原分析配置摘要仍为`e60dad4e41ec844f374e3f588924ea6036b3d4e1ea6633884f05d4eb395e65e4`；8Worker、388TU原构建闭包、ELF/map、工具链、上下文与全部语义字段保留。

生产者是冻结v62，3822文件，清单SHA256 `65a6a6b751d5ae613b8227e5d05776e3387e2414b818a28af64aea7575ae8754`；`ecra/`及既有tests与干净c374ebc/v61逐字节一致，新增仅观察器/回归/记录。完整1512通过后才启动，继承原封存编译环境，固定`PYTHONHASHSEED=0`、`SOURCE_DATE_EPOCH=1793577600`，冷提取，不复用旧引擎TU缓存，不修改旧检查点或黄金库。

实际独立输出：`H:/ECRA-NATIVE-C62-SEED0`。观察：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/inav-current-published-native-v62`。完整原生Windows Job上限16GiB。原`H:/ECRA-NATIVE-A13-SEED0`只作为不可变比较参考，原固件/构建输入仍在原路径只读使用。

后续自动链：[实际驱动脚本](acceptance/inav-current-published-v62-driver.py.txt)先等公开原生完成/有效性/manifest→原4123输入及引擎后验→2GiB Job严格完整facts/report对照→2GiB Job已有结果真实刷新（不重新分析）→新库最大完整Packet实际写出与收据校验。任一失败保留原件/失败证据并停在失败，不把前项完成冒充后项通过。

动态队列：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/inav-current-published-native-v62-queue.json`；原生最终`execution.json`位于观察目录；完整G1结果为`inav-current-published-v62-full-comparison.json`；后续刷新/Packet各有独立execution。启动时只处于真实依赖快照阶段，结果必须重新读取，不能将本页时间点的状态当作最终结果。旧原生v13和97/98号旧库消费实测不计为此次新原生已通过。

只停止本次任务可在观察目录写`stop`文件，按原安全停止语义保留已提交TU/诊断和旧有效结果；全局求解未提供任意位置续算，恢复仍需回到已验证入口。不删除旧数据来给新任务腾空间。

## 仍需完成

新INAV原生、完整G1、后续刷新/Packet需等真实最终结果；本脚本不包含完整大Diff/恢复或完整模型队列。102号列出的基准摘要/全量核验大对象、生产者与可选AI联合峰值、历史codec、源码整文件读取仍需处理；CMake未提交构建、dirty绝对视图跨根重放未证明。其他G2按用户要求待验。物理32GB、第二电脑/干净离线、原生DPI、联网模型、工程师UAT及G1–G8整体继续NOT_VERIFIED/未通过。
