# R2b：父进程冻结输入与目录语义验收

2026-11-04，按[合同73](73-frozen-parent-input-contract.md)完成内部父读取接口。此阶段不移除正式dirty扫描/恢复门禁，不宣称R2完整完成。

父进程现在可以把`ParentFiles`显式交给`InputSnapshot`，全部源码读取、文件记录和glob选择都经过同一固定视图。`SOURCE_READS`的已有真实入口继续核对实际字节、逻辑路径、读取次数与父选择集合；无内部视图时仍逐项走原逻辑。固定配置/编译数据库/响应文件可按单文件复制，支持活跃数据根中的已固定配置，避免递归复制整个数据根。

新版工作捕获记录、复制、验证空目录，版本为2；旧文件清单版本仍可按旧合同验证，不能冒充有目录证明的父读取。视图完整清单同时绑定捕获数据库SHA、文件及目录，Windows路径拼写按同一文件身份核对。文件选择前重新验证全部冻结目录/文件，防止被删空目录将歧义map变成唯一候选。闭包与诊断存储固定身份和“原输入最终仍须重验”声明；正式恢复遇到新闭包会明确拒绝，保留原数据，不忽略声明后回退读取实时源码。

| 阶段 / 功能 | 变更文件 / 场景 | 实测结果 | 状态 / 证据 |
|---|---|---|---|
| 独立文件/目录捕获及旧格式兼容 | `ecra/working_snapshot.py`、`working_compiler_view.py`；`test_frozen_parent_inputs` | 原工程/SDK后增目录拒绝；冻结副本目录删除/捕获清单篡改拒绝；旧捕获可验证，父读取能力缺证明明确拒绝 | PASS_SCOPED |
| 父读取与真实算法消费者 | `ecra/input_snapshot.py`、`working_compiler_view.py` | 原配置、DB、flags、源码后来改变仍读取固定字节；未知输入不回退；CRLF/编码语义保持；实际汇编启动+linker-map构造器证明读取冻结证据，实时异常输入未混入 | PASS_SCOPED |
| Windows实际路径 | 同上；真实Clang子进程 | 不同大小写的父输入及实际Worker完整响应保持相同 | PASS_SCOPED，Windows本机 |
| 恢复边界 | `ecra/workflow.py` | 原普通恢复不增加新声明；遇新冻结父读取闭包明确拒绝尚未实现的恢复；原正式dirty gate保留 | PASS_SCOPED，非完整R2 |
| 最终专项 | 新9项 + 既有R2a/父读取/稳定性测试 | 65/65，232.087s；增加单个未消费目录候选的原语义反例。早期64/224.715s及更早分批实测仍保留，最终以统一65项为准 | [源码验收v2](evidence/frozen-parent-source-acceptance-v2.json)，PASS_SCOPED |
| 获准F030联合真实提取/父读取 | 全新私有源码副本与Git、原真实4TU参数、外部SDK/build、固定配置/DB | 384.703s；8个真实Worker；各TU普通/冻结响应字节相同，2PARSED/2PARTIAL；父快照实际读取配置/DB及4源码；1712文件最终原输入重验；完整事实/报告0/0 | [最终联合收据v2](evidence/frozen-parent-approved-f030-v2.json)、[驱动v2](evidence/frozen-parent-approved-f030-driver-v2.py)，PASS_SCOPED |
| 早期联合证明 | 未消费目录候选补充前的独立副本 | 439.844s、8Worker、完整0/0；当时源码SHA保留，不能替代最终版本 | [初版联合](evidence/frozen-parent-approved-f030-v1.json)、[初版源码验收](evidence/frozen-parent-source-acceptance-v1.json)，历史PASS_SCOPED |
| 当前完整回归/Portable | 新增9项后预期发现1439 | 冻结R2a的1430仍是另一个候选；新R2b完整回归尚未执行。v37软件包绑定R1/7066dea，不能标作本阶段新分发包 | NOT_VERIFIED |

最终联合对照完整事实SHA `3691cd1ce744a9ffd3a7cdec687029bfe7a2f47dbc8b80aec644831db6f2a3d4`、完整报告SHA `d0b2e0cf52543168349c96e6acd3b2c46a026874251204d91e7fe8ddc272123c`，各自两侧相同。输入闭包SHA `fabb64011a7fbd99ddfcdd497c8217f0cce3270aacb422744056f115aeccc7ec`。这些值属于本次独立副本的固定逻辑路径，不能与R2a或初版另一个副本的哈希混比。不是原路径黄金完整扫描、正式dirty Diff、另一真实G2工程或目标板硬件结论。

首次6项父读取测试中5项因夹具把编译数据库放在数据根祖先而被既有H2检查正确拒绝，夹具改到独立metadata目录后继续；随后6项复现1个实际实现缺陷：删除冻结空目录后选择没有先验证完整集合，修复后早期64项通过。复查又补出单个未消费目录候选不应提前使其他输入失败，新增1项原生文件系统反例并保持原可选输入/OSError语义后，统一65项通过。全部失败、旧日志路径与SHA都在源码收据，不覆盖失败记录。

专项复现：

```powershell
py -3.10 -B -X utf8 -c "import sys,unittest;sys.path.insert(0,'tests');unittest.main(module=None)" tests.test_frozen_parent_inputs tests.test_working_compiler_view tests.test_working_snapshot tests.test_parent_source_reads tests.test_scan_stability -v
```

获准F030驱动须使用新的独立`work`目录，不能覆盖先前证据或修改获准原工程。原工程、原配置/DB、外部build/SDK、私有Git副本及全部当前引擎SHA前后均0变化；完整原/新Worker响应及原输入仍保留在收据指定私有目录。

下一步R2c仍须将真实配置/响应文件读取和编译器探针在消费前固定，接入`prepare_current(true)`、全TU请求/缓存键、归档与恢复的同一捕获身份，再验证外置CMake及全Diff扩大闭包/`verify_against_full`。独立原型未接入这条正式链，版本预览与正式入口继续明确阻断。R3全消费者/大型恢复、R4不变确认继承、R5全根迁移、R6完整故障/UAT、R7全部门禁均未由本阶段关闭。`all_gates_passed=false`。
