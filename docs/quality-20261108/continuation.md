# 续轮执行记录

用户在上一轮限定范围交付后要求继续。本轮沿用已有矩阵、台账和证据，不将历史通过重新计数，也不覆盖原候选ZIP。

## 执行顺序

1. 核对工作区仍为 optimize_ccc@fe27afe 加上一轮本地修复；静态引擎74c0…，生产文件和未提交成果保留。
2. 当前源码完整测试集；只显式关闭两项 opt-in 联网AI，记录失败、跳过、资源及源码前后hash。
3. 在独立数据根实际启动完整 INAV MATEKH743 当前侧全量扫描，包含真实 CMake 配置、目标编译/链接、完整分析和发布；跟踪尾部发布耗时。未结束前不预报通过。
4. 用包内工具补真实F030/CDC/F411固件完整链接与Windows MinGW条件，区分工程外部依赖和工具缺陷。
5. 独立检查者补大报告、真实浏览器缩放及连续复核/跨项目界面。实际DPI/物理目标机缺失仍单列。
6. 已确认缺陷先复现再修复；静态模块在大型任务运行中冻结，必要修改须明确使该轮失效或先合理停止，不能混用不同引擎的结果。受影响验证重新执行，候选包另行生成。

## 大型整工程实际启动

独立配置：`H:/ECRA-quality-20261108-continuation/inav-full.json`；数据根 `inav-full-data`，观察证据 `inav-full-observer`。实际命令：

```powershell
py -3.10 -B -X utf8 scripts/measure_native_golden.py --engine H:/global_static_concurrency_design --config H:/ECRA-quality-20261108-continuation/inav-full.json --data-root H:/ECRA-quality-20261108-continuation/inav-full-data --work H:/ECRA-quality-20261108-continuation/inav-full-observer --mode canonical-published --limit-gib 16 --scan-id quality-inav-full --profile-id quality-inav-current
```

获准的独立公开工程派生输入 `H:/ECRA-WHOLE-S78/firmware`，实际HEAD `a040c6bef605f929fa017b7089c5b7976a2b2bba`，开始时干净，未切换分支或修改源文件。选择完整 `MATEKH743.elf`，不排除业务目录；`build:true`、复核/Packet关闭。16GiB是自有Windows Job限制，机器实际64GiB，不能称32GiB真机验收。

本轮 full 单独关闭 git_diff；不是有改动的完整差异矩阵，也不是原冻结v78输入等价证明。新数据根不继承旧缓存；原样保留上轮包、原大型失败/未完成现场、确认记录及历史报告。状态和最终结果由后续实际收据更新。

本轮完整证据：`output/quality-20261108/continuation/`，其界面图在 `output/playwright/quality-20261108/continuation/`。各职责记录另列 continuation-build.md、continuation-regression.md、continuation-ui.md。

## 首轮正常停止与本批候选

首轮实际完整目标构建/链接和388TU依赖盘点完成，随后发现下列新的根模块缺陷，需要修改静态引擎。为避免长任务中途变更引擎导致最终输入校验失效，通过该观察器的正式stop文件请求正常停止。最终退出130、1174.484秒、analysis_valid=false/INTERRUPTED，无发布manifest；原缓存统计记录extracted72、corrupt0，但后续实际可核对的持久缓存为64个.json+64个.facts，scan_progress亦64/388，两种口径分别保留，不推测8项差异原因。Job峰值1,652,187,136字节。它不是大型完成或冷扫描性能通过。

主工作区完整1646项测试仍在运行，源文件保持74c0…字节。修复先在独立源码副本中实施和验证，合并同一批后才冻结下一轮大型输入；没有手改旧检查点或把解析计数/64对缓存算成388完整扫描。

| 编号 | 当前确认的问题 | 原场景与修复状态 | 证据 |
|---|---|---|---|
| Q105 | 一份合法JSON但非对象的manifest阻断整个结果目录，详情也500 | 原清单[]使/api/scans整体500，独立有效示例仍可读；独立候选用共用有界清单合同按项报错，主区待合并 | continuation-regression.md、server-candidate/ |
| Q106 | 损坏ZIP/CRC或清单容器错误返回泛化500 | 真实HTTP上传失败保留原数据；候选明确400、导入阶段/影响/下一步，并检查坏合并目标；主区待合并 | continuation-regression.md、fault-matrix-01/ |
| Q107 | SQLite长完整校验时停止请求不能及时打断 | 实际EvidenceProvider.validate+ScanDiagnostics，5秒请求停止、15秒外部截止仍未返回；候选将受监督连接关联到SQLite interrupt，同一12.6GB原件约5.48秒结束（请求后约0.47秒），原件不改；75项/95子例通过，主区待合并 | product-sqlite-stop-before/candidate.json、sqlite-candidate-tests.log |
| Q203 | 工作字节CMake拒绝标准ASM编译器版本查询 | 真实CDC C+ASM准入退出3；候选严格绑定内置来源、实际ASM编译器和私有CompilerIdASM目录，实际完整捕获及自定义命令拒绝等3项/11边界反例通过，主区待合并 | continuation-diff.md、q203-*.json/log |
| Q306 | 中文路径编译器标准头探测把ACP字节按UTF8替换，丢失真实头目录 | raw GCC退出0；UTF8严格解码失败、Windows ACP936成功；受控构建也有同类输出链路。独立候选仍在实现/复验，不通过关闭系统头规避 | continuation/headers/raw-probe-baseline.json |

原生缩放检查被Computer Use因无法可靠确定浏览器URL自动停止，未绕过；真实缩放和相关图形流程本轮NOT_VERIFIED。实际构建三工程已补齐，详见continuation-build.md；固定提交CDC全量/Diff/独立全量对照由另一独立CLI流程继续，不冒充未提交CMake已通过。

## 联合冻结与继续验证

全部候选已合成独立 `H:/ECRA-quality-20261108/continuation-final-engine`，静态引擎摘要 `1b85908f5313ce13466cd0ddf39abff2299bffb46e2fc414f7a47428099f11ed`；逐文件来源/基线/候选SHA见 `continuation/final-candidate-source.json`。这不是已合入主区或已封包，主区74的完整回归仍保持原字节。

- Q105/Q106服务最新合同49项通过，真实故障HTTP11项通过；有效LOCAL的STATIC_VALIDATED与DB UNVERIFIED差别有独立回归，不进行错误相等比较。
- Q107最终停止桥75项、95子例通过；同12.6GB只读原件在5.016秒请求停止、5.328秒结束，约0.312秒响应，原件不改。此为停止响应修复，不是完整校验速度优化。
- Q203与Q306联合真实C+ASM/系统头/`stdint.h`解析通过，4项617.560秒，拒绝自定义命令与11个ASM边界反例仍有效；Q306标准源29项另通过。
- 新Q204：同物理构建目录因别名注册顺序改变Cache/CDB字节，完整基准复用受阻。旧74 warm的基准及当前各39/39 TU命中，不能说AST全部重提取。最小portable.py修复30项通过，包含真实Windows junction和稳定后的实际CMake字节对照，最终组合上的完整基准复用仍待真实重跑。
- 新Q108：实际Chrome复现坏报告后进入变量详情导致整个应用空白；前端共同就绪门禁和明确重试/历史恢复已实际复验，签署→关浏览器→重开→继续通过，详见continuation-q108-ui.md。此独立Playwright错误状态任务不恢复被停止的原生缩放任务。

新INAV正式全量命令及启动输入在 `continuation/final-inav-start.json`；全新数据根 `H:/ECRA-quality-20261108-continuation-final/inav-full-data`、观察器 `inav-full-observer`。同一冻结字节的联合定向测试在 `continuation/final-candidate-joint-tests.log`；原1646项主区基线单独记录，不能混成同版本“全套通过”。最终引擎的三工程全量及CDC dirty工作字节/固定提交full-Diff独立full对照也正在执行，未结束前均保持未验证。

### v2冻结与v1相邻遗漏

真实首次构建表明Q204第一版只覆盖已存在目录：初次请求build_path时目录未创建，仍落到祖先别名，重开才取精确别名。没有把30项局部通过冒充完整原场景通过。第二版保留“调用者随后创建其自有构建目录”合同，只为明确compact目录建立指向精确尚不存在目标的junction，不创建或写目标。实际不存在→创建→重开、注册顺序、ARM/CMake字节、失效别名与工具siblings共33项通过。

旧1b…INAV正常stop退出130，456.329秒，Job峰值提交1,436,053,504字节，未发布，不计大型完成。原1b联合96通过/129子例/1跳过，耗时818.87秒；跳过为未显式提供中文物理编译器的正例，不代表Windows全缺。v2显式指定包内中文物理GCC，独立原场景1项通过、无跳过（`final-v2-physical-chinese-gcc.log`）。

当前有效冻结源为 `H:/ECRA-quality-20261108/continuation-final-engine-v2`，引擎 `8393edcd9ec5d958f97559a49eda73a2a5edd425a15cc18ad8ce7de33a330902`。相对1b仅portable.py与对应回归变化；逐文件SHA及来源见 `final-candidate-source-v2.json`。原源/旧包均不改。新大型数据根 `H:/ECRA-quality-20261108-continuation-final-v2/inav-full-data`，启动收据 `final-inav-start-v2.json`，同字节的v2联合、三个真实工程全量、固定提交CDC冷/热及dirty整轮继续，不混用旧检查点。

v2联合控制器最初使用不存在的测试文件名，pytest明确“no tests ran”退出1，原日志 `final-candidate-v2-joint-tests.log` 保留；更正为实际文件清单后的运行写入独立 `final-candidate-v2-joint-tests-valid.log`，没有覆盖失败命令或把未执行记通过。

### v2实际结果与继续修复

v2联合44通过/20子例/1跳过/1失败，981.46秒；唯一失败是本检查者创建的精简源码副本没有根build_portable.ps1，-File不存在，未进入“已有bundle禁止覆盖”产品检查。原日志保留；在补齐当前原样打包脚本的独立完整builder源码中，只重跑该契约1项通过、1.07秒（`v2-portable-script-real-contract-retry.log`）。没有修改或放宽预期。

真实F411新构建/扫描确认Q109：4个STRUCT_MEMBER_CONTAINER从分类分母排除正确，但根容器汇总漏掉该类型，读模型将缺标签项默认UNKNOWN；界面实际显示8未知/42待人工，其中4是容器，成员叶风险已独立保留。真实1366修前画面与源码/API证据充分，不能仅以“保守UNKNOWN”把状态不一致解释为通过。独立候选正在修根因和旧归档只读派生；旧物化投影/完整校验合同保持，已有显式风险/AI/人工数据不得被覆盖。详见后续Q109记录。

因Q109需要改变静态引擎，v2 INAV在正式stop后退出130、1253.969秒，Job峰提交1,432,195,072字节，未发布；构建及现场保留。下一大型轮将在这批根因修复和真实小工程复验后启动，不将当前局部进展计成完整验收。

另有Q204的独立Cache元数据原因：同工具链重复-D会改写CMake已初始化的类型/帮助文案。仅加:FILEPATH的设想被实际反例否定，未应用；独立小候选在Q301真实相对路径合同确认“已缓存同一实际文件且不会clean”时才保留缓存原选择，新/变化/clean仍显式指定。35项及7边界、真实外置C+ASM三次Cache+CDB稳定等已通过，当前只在q204-v3-candidate-source，尚未合入冻结源或宣称真实整轮命中。

正式离线builder输入目录 `H:/ECRA-quality-20261108/continuation-builder-source` 已从v2核心加当前原打包脚本/启动器/交付文档独立复制4305文件、301,001,717字节，目前标为PREPARED_NOT_BUILT_OR_FROZEN，等待最终修复叠加与源清单冻结；不是已生成的新ZIP。

## v3的真实完成范围与严重阻断

组合v3在 `continuation-final-engine-v3`，核心摘要 `6cede8359026fd75dd801f6d45ac34ba422a18eee77888078babb8cd862d54f7`。Q109+Q204工具链元数据修复合并后关键联合56通过/100子例/1跳过，46.66秒；中文物理路径GCC正例另实际1通过无跳过。其生产网页为`index-DtkBozpG.js`。

三个真实项目完整扫描/发布及status→report→status均完成（0/2/0），原源码、编译/链接信息与静态库刷新均不变，全部新TU缓存命中0。F411：24PARSED、171盘点、38待办；CDC：39PARSED、244盘点、205待办；F030：2PARSED+2PARTIAL、15盘点、1待办。全部保持INCOMPLETE，不是全安全。353个非容器完整有序对象JSON与前一引擎逐个严格相同，仅24个nested父容器新增正确标签/成员汇总，新facts derived标记0。详见continuation-final-projects-v3.md及final-v3-three-projects-summary.json。

真实Chrome读取原v2 F411原字节：4派生容器明确来源，未知8→4/待办42→38，风险叶保留42关系/16访问，1366与1920视口均已查看。最新UI对隔离manifest损坏→明确失败→恢复记录的该文件备份→真实点击重试也通过；这是故障文件恢复，不注入人工/AI/任务状态。证据q109-final-ui-receipt.json及截图。服务和浏览器已关闭。实际CLI `--legacy-output`也完成（284.921秒，退出2），但file协议被浏览器工具拒绝，当前HTML文件视觉验收环境阻塞，没有用HTTP替代或绕过限制。

正式升级后NEW任务实际通过产品API创建于原74数据根，任务`d2529566dda44dc38a53c72e37dd4899`，16GiB Job/8workers，并非observer同engine恢复。随后实证Q205严重错误安全：同ID手工context覆盖真实NMI/HF物理属性。必须修复，故通过正式stop接口协调停止；终态INTERRUPTED/130、published:false，1008个资源样本，Job峰提交1,142,427,648字节、最大观测20进程，原输入/缓存核对和自有服务后代清理见new-upgrade-first/receipt.json，停止原因另见new-upgrade-q205-stop.json。不能把PARTIAL_OR_FAILED控制器收据包装成大型通过，也不能用v3三工程替代Q205后整体验收。

Q205独立候选将保留或明确拒绝配置与自动物理证据冲突；不全面重写分析器。Q105严格清单候选另发现漏接合法legacy发布格式的回归，完整/降级迁移已真实复现后修复中。原完整1646项基线仍在74源码上运行，已出现异步测试10/40秒等待与随后删除活锁错误，独立实际迁移约50秒正常完成，不能把等待超时直接认定产品业务失败；原FAIL/ERROR与修后有界等待/正常清理回归分别保留。

## 尾部只读调查边界

历史未完成12,592,009,216字节pending库已经提交facts/report/provenance和16566个查询对象，但没有完成发布。这仅是历史排障原件，不能当当前成功扫描。原件只读完整SHA为 `9cccd8390ce4a9c743b21d28dce9431dc78bc2a6d71ddc84e2a04169422c93f7`。

对同一文件的64/512MiB SQLite缓存及顺序读取/文件缓存敏感性探测保留了全部超时和初次控制器误差：第一条读探针实际114.57秒被停止，未到120秒，因此用controller-correction.json明确标为无效超时基线，没有用它证明速度收益。后续外部截止控制器严格记录120/240秒未完成，顺序SHA预读130.031秒也单列。共享主机及OS缓存未受控，因此本轮尚无足够依据宣称已优化尾部速度，未因此改缓存预算、删除完整性检查或降低任何安全标准。
