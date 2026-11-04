# R2c第二步：固定数据库的内部工作区Diff链

本阶段继续[80号](80-frozen-full-scan-integration.md)，仍不向普通GUI/CLI开放`include_uncommitted`。`formal_workspace`原始拒绝条件保持原字节。新增入口只接受内部传入、已经完整验证的视图，并保留所有原正式输出/数据根边界；没有第二套Resolver。CMake、自动数据库、补充扫描、固定提交的视图模式和冻结检查点恢复仍不支持。

| 调用点 | 实现与语义边界 | 当前实证 |
|---|---|---|
| `frozen_scan.execution_workspace/check_mode` | 内部视图可用于显式数据库的完整扫描或`HEAD + include_uncommitted`比较；只在路径校验用的副本移除dirty拒绝标记，真实分析配置不变；视图无效时不能开始基准分析 | 普通同配置调用仍拒绝；内部实际2 TU全链运行 |
| `cli.run` | 在pin之后、耗时基准分析之后分别重验原HEAD/index/工作字节/目录与同一捕获；不是在基准结束后再捕获一组输入冒充原pin | 基准真正完成后修改index，返回失败且当前Worker未启动 |
| `git_diff.prepare_base` | 固定base提交独立运行，不继承当前冻结视图或未提交模式；原base→current与所有影响传播算法不动 | 真基准完整扫描、真实当前Diff和独立当前完整扫描 |
| `git_diff.verify_full` | uncached重提取也显式传递同一视图；不以缓存命中或复用主扫描响应代替独立核对 | 每次2个实际独立Worker请求均绑定原视图，状态PASSED；全部事实精确相同，Diff附加impact逐字段核对 |
| `git_diff.write_comparison_patch`调用者 | 使用同一捕获里保留原HEAD/index/工作字节的Git副本生成原格式完整patch，逻辑路径不变；原patch算法不改 | 真实“原源码临时改变后恢复”反例先失败，再修复通过；patch完整字节与捕获Git独立生成结果一致 |
| `compilation.prepare/ParentFiles.walk` | 编译准备中的源码枚举同样使用冻结目录；向旧代码呈现原逻辑路径并保留os.walk目录剪枝；普通路径保持原枚举 | 父目录真实新增文件后，枚举仍精确等于已捕获名称/目录，不能让实时未编译文件改变覆盖清单 |

最初两个Diff专项实际通过70.536秒：真实基准/当前/独立全量、完整事实及原影响算法输出、普通入口保留拒绝、基准期间index变化。随后增加patch对抗测试，**1项真实FAIL，34.169秒**：虽然源码在最终检查前已恢复，旧调用仍把临时内容写进patch。这是内部链路缺口，未被称作正式门禁通过；原失败日志单独保留。改为捕获Git后，3项Diff及1项目录专项全部通过，**4项108.060秒**。

真实dirty Diff冷/热/损坏缓存已完成：热命中2 TU，实际损坏后重新提取2 TU，每轮uncached完整核对PASSED，**1项82.844秒通过**。冷/热/恢复结果的impact分别引用每轮独立存放的基准库/摘要/patch，测试逐个证明这三个引用文件的完整SHA完全一致且等于原pin绑定，才对照其余全部字段。生产比较器、规范化合同及任何扫描/证据文件没有改写。最初测试直接比较这些不同存储位置而失败：23项22PASS/1FAIL，随后单项修正中暴露另外两个引用位置，57.641秒与57.948秒各1FAIL；全部日志和最终82.844秒PASS均保留在[精确收据](evidence/frozen-dirty-diff-source-v1.json)，不把它们冒充一次23项全绿。

完整扫描/父读取/背压的**最终23项统一复跑仍待新冻结执行**；新完整回归应为1449项，旧v40的1444全套只绑定`f2dca32`。新的原路径F030黄金对照也需实际执行，不能借用旧结果。源码审计确认48个未改算法函数AST相同，13个保护区/Resolver/缓存/恢复模块字节相同：[审计](evidence/frozen-dirty-protected-algorithms-v1.json)；该静态证明不能替代真实回归。

现有专项证明内部链路能消费真实固定输入，不是原e69在获准真实工程上完成dirty Diff的完整G1证据。F030原构建仍2 PARSED / 2 PARTIAL；基准解析不足不能被本阶段转成安全或强行通过Diff。INAV、真实外置CMake/GCC生成闭包、只读输入全故障矩阵、停止/恢复和正式UI仍需后续实际验证，达到条件才开放支持模式。R3–R7与[79号](79-r2b-regression-and-v13-package-final.md)所列外部待验不变，完整重构未完成。
