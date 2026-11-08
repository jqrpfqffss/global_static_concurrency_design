# final-v6真实CDC工作字节复验

本轮仅使用冻结final-v6，core `65c0fb3dbc29bda7ad74aeeadeb4666c6b1eeda545bc9521c3961f476eca7682`。之前v4固定提交cold/warm/独立full、恢复已通过，dirty首次失败仍完整保留；[Q207记录](continuation-diff-q207.md)描述准入、只读Git和注册身份三个共同边界修复。

新证据：`output/quality-20261108/continuation/diff-final-v6/`。新源/数据根：`H:/ECRA-quality-20261108/continuation-diff-v6`。未修改原CDC工程、旧报告、原确认数据、旧Git或任一冻结引擎。

## 输入和实际方式

- 从本轮已有的真实CDC隔离仓库重新`git clone --no-hardlinks`，移除新副本remote，不使用alternates或旧检查点；上游STM32CubeF4 v1.28.3、固定来源提交、LICENSE及已有集成来源文件保留。
- HEAD为真实验收提交`3c632672a3076998477e36e2e2db1bb126240aa5`；基准`quality-protected-base`为`3dd83d1ee84aaa51b0ca6e0e0d555b8ca5a1653f`。头宏由已提交5u实际改为7u未提交，Git状态只有`M App/lab.h`。
- 配置SHA `f6eb690e55ed1e9657a990b57b8416e1f1a3c95114824602a5330a9b10614649`；继续原`include_uncommitted:true`策略，Ninja管理真实CDB、真实C+ASM构建、完整链接、`auto_system_includes:true`、`verify_against_full:true`，未手写或重映射CDB。
- 变量目标范围沿用既定`Application/Src`与`App`，排除Drivers/Middlewares变量及显式system文件；必要依赖函数/目标变量访问仍参与分析。实际发现396对象、选择245、按明确范围排除151；完整构建与39 TU解析不等于已展示所有第三方变量。
- 初始真实索引SHA `8321a9f3a1bded15a631f2aea5e1297a11677b946b7124a4922729cd13ac1be4`提前持久化。源全部文件SHA/大小/mtime及目录清单、引擎全部内容、HEAD/索引与配置分别冻结，结束后逐项比较。
- 普通Windows CPython3.10.11显式`-B`、`PYTHONHASHSEED=0`，调用冻结v6的`run_ecra.py --config <新配置> --no-review --scan-mode diff`；CMake/GCC/Ninja来自封存便携工具根。此项不是最终ZIP双击入口验收，实际依赖路径由正式input_manifest记录。

`run_final_dirty.py`只做外部QA编排；实际产品入口由`run_phase.py v6-dirty --scenario dirty`调用。独立内核观察器只记录事件，不过滤、不重置产品watch、不注入任务/队列/检查点。

## 当前覆盖状态

| 场景 | 预期 | 结果/证据 |
|---|---|---|
| 原始工作输入捕获与首次准入 | 568真实工作文件、HEAD/索引保留，原mask/身份锁生效，不因首次只读准入通知误拦 | 已实际进入后续构建；原v4失败不删除、不改记通过 |
| 两次全新私有目录构建 | 实际C+ASM配置/编译/链接均成功，编译闭包和预处理输入等价 | 已通过：两个独立构建的40条真实CDB均为39C+1ASM，实际ELF/MAP及目标符号存在，命令退出0；证据已逐字节备份 |
| 完整SDK和Clang输入固定 | 完整外部搜索边界、源字节和生成输入必须重新核对 | 已通过COMPLETE_GUARDED_CMAKE_INPUTS_V1，原始最终复核要求为true，完整封存收据已核对 |
| 基准/当前分析与独立无缓存full | 保留39 C TU、ASM向量与全部必要依赖；全245变量语义/分类比较；已知完整保护基准SAFE、移除屏蔽且实际宏7u当前SUSPECT | 已通过限定合同：39 PARSED、0 PARTIAL、0 FAILED；基准SAFE/EFFECTIVE→当前SUSPECT/UNRESOLVED且选入Diff；独立full39 TU/245变量分类与语义mismatch各0 |
| 正式发布与原输入最终验证 | native完整节点/投影验证、SQLite正确、真实原HEAD/索引/源/配置/引擎不变，不以INCOMPLETE当安全 | 已通过：STATIC_VALIDATED/source_reverification true、SQLite ok；568源及目录清单/HEAD/index/config/engine逐项未变；原退出2/INCOMPLETE保留 |

实际产品运行2350.391s，外层核验总2368.296s，2026-11-08 12:08:29Z结束。正式归档`data-dirty/scans/e588975e0b5244b6b3594f071ed01ed0/scan.db`，SHA `8667baaccbac70974d58cb370748beb495250d3aa7b224b1e5c5342e1f38c3fb`。这只属于实际core65c0版本；后续仅Git兼容命名逻辑的新core2b9e不重标此结果，也不修改旧检查点。

## 完整证据与剩余复核

`v6-dirty-audit.json`、`retention.json`、`v6-dirty-guarded-proof.json`及`v6-complete-native-evidence-scope.json`保存原退出码、完整解析、独立full、保护、输入封存和数据保存证据。55个完整facts关系、245变量及206完整finding均存于权威native库；accountability缺失/重复均0。211个存储风险对象中5 SAFE_PROVEN、136 SUSPECT、70 UNKNOWN，其他对象按容器/非存储规则保留。没有把待复核项隐藏或计作安全。

Diff实际展示/选中1个目标；该展示范围之外的风险和未知仍留在完整归档，不能称作已证明安全。没有联网OpenCode，也未完成人工签署。

实际两个ELF的`Lab_Poll`反汇编均为`mrs PRIMASK → ldr → adds #7 → str → msr PRIMASK`，没有`cpsid`：证明实际工作头宏7u被两次构建消费，且保存/恢复PRIMASK本身没有覆盖RMW逻辑窗口。对应map含真实counter地址。`.asm`原输出、两份ELF/MAP/原生CDB备份在证据`build-artifacts/`与`retained-build-artifacts.json`中；复制CDB只作字节证据，不重映射、未用它伪造新分析输入。

原v4首次dirty失败仍保留为真实失败，v6成功来自已修复共同原因的新字节与全新根，不是盲重试、删watch、过滤.git或手改任务状态。

## 相关跨引擎真实恢复合同

`output/quality-20261108/continuation/cross-engine-q207/receipt.json`已用真实F030独立数据根完成：只读复用delivery round5实际4命令GCC CDB、已链接ELF/MAP/objects，本项未重新构建固件、未移动/伪造CDB。

同一真实工程、同一配置字节，v4新full扫描24.704s原退出2，生成STATIC_VALIDATED/INCOMPLETE归档`ca25d9eb52994ef49c573fad2208a432`；v4 status可恢复。C65候选status明确拒绝跨实现复用，report原退出3，提示先刷新静态扫描。旧数据库SHA前后均`765e22ceba35b2407945b3a8be88b47703b1f0120349bc25920c264a47ae0938`，原源/CDB/ELF/MAP/objects的SHA、大小和mtime均未变。没有修改任何engine_tag、检查点或旧状态来制造恢复。

这证明跨引擎旧任务被诚实拒绝、有效旧报告保留；不代表C65已重新完成F030分析，也不替代本轮完整CDC dirty流程。
