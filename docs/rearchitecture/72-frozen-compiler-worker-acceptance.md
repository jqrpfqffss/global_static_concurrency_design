# R2a：真实Worker冻结编译输入验收

2026-11-04，承接[合同71](71-dirty-compiler-view-contract.md)。对应H1/H2/H6和R2正式dirty隔离的编译Worker子阶段。当前仍不解除`formal_workspace`与版本检查中的dirty阻断；U04完整链路不是PASS。

`ecra/working_compiler_view.py`复用已有捕获/Resolver，创建有完整哈希的`redirect-only` VFS及SQLite文件清单。工程保持原逻辑路径；外部SDK与build搜索目录独立完整复制，保留空目录和mtime，不将搜索回退至实时源目录。实际`ecra.extract`请求可传内部`compiler_view`身份，解析前检查归属及描述/overlay SHA，解析后逐个核对Clang实际缓冲区的SHA/大小。只有完整外部/原始/副本集合复核成功，视图才从PENDING原子发布为COMPLETE；未完成身份不能被Worker消费。unsaved覆盖、关闭输入核对及未捕获的工作目录会失败。未指定视图的原请求路径保持。

| 阶段 / 功能 | 文件 / 场景 | 实测结果 | 状态 / 证据 |
|---|---|---|---|
| 真实Worker视图及损坏处理 | `ecra/working_compiler_view.py`、`ecra/extract.py`；`tests/test_working_compiler_view.py`的7项 | 完整TU/宏/USR/位置/签名相等；改变实时工程/SDK、新增负探针及删除原正探针不穿透；损坏副本/overlay/描述、低磁盘、复制期间变化、最终集合变化均保守失败；实际Worker拒绝PENDING | PASS_SCOPED |
| 原捕获/父读取/稳定性专项 | 新7项 + 既有`test_working_snapshot`/`test_parent_source_reads`/`test_scan_stability` | 56/56，187.983s；真实ARM GCC宏对照与动态宏拒绝保持 | [源码收据](evidence/working-compiler-view-source-acceptance-v1.json)，PASS_SCOPED |
| 获准F030完整4TU的真实提取对照 | 原获准源码的全新独立复制品，私有新Git库；相同逻辑路径/编译参数的普通vs冻结Worker | 8进程，255.390s；4TU响应文件逐字节SHA各自相同；2PARSED/2PARTIAL；完整合并事实/分析报告差异0/0 | [当前收据](evidence/working-view-approved-f030-v1.json)、[驱动](evidence/working-view-approved-f030-driver-v1.py)，PASS_SCOPED |
| 外部build/SDK完整边界 | 实际原编译数据库工作目录及3个真实ARM GCC头目录 | 1667外部文件、共1710项冻结文件完整复核；获准原工程/配置/DB、私有Git副本、外部build/SDK、当前引擎均无变化 | 同当前收据，PASS_SCOPED |
| 更早内部实现对照 | PENDING发布检查前的4TU版本 | 231.969s、8进程完整0/0；保留当时引擎SHA，不能移作最终发布状态验收 | [历史收据](evidence/working-view-approved-f030-initial-v1.json)，历史PASS_SCOPED |
| 较早扩展回归 | 116项，运行时源码仍在编辑 | 115PASS/1FAIL，733.188s；既有引擎变化保护正确拒绝混用版本。此运行不能写为最终源码通过，须改用固定副本复跑 | FAIL_CONTROLLER_SOURCE_MUTATION，日志/哈希保留在源码收据 |
| 冻结副本扩展复跑 | 提交`4967b7dfdcd6a80e22f267af5f8fd20f809a8e4c`的3434文件；manifest `de12c769fbfd245aa61a6293073a138fa23309b086c8affb7c14cf79a4731286` | 118/118、754.451s（含前后完整SHA控制757.891s），全部源文件0变化；新增外部cwd与PENDING反例也执行 | [冻结复跑](evidence/working-view-frozen-related-v2.json)，PASS_SCOPED；旧失败保留 |
| 较早专项命令 | `test_scan_stability`的既有顶层`test_ecra`依赖 | 22PASS/1ImportError；修正`sys.path`后的最终56项通过 | CONTROLLER_COMMAND_ERROR，旧日志不覆盖 |
| 正式dirty、完整Diff/构建、统一回归/分发 | `prepare_current(true)`及正式门禁仍维持原行为 | 新增7项后完整1430正在上述冻结源码的独立测试副本执行，未结束不能宣称通过。前一R1冻结v37/1423已完成1421PASS/2联网SKIP，是另一固定候选 | NOT_VERIFIED完整当前门禁；`all_gates_passed=false` |

F030对照完整事实SHA为`3b761eb37b389f270de2e1174b38c06388707e18509e296cba6095655a1b558b`，完整分析报告SHA为`f5a089cc3a5bcc5f0682431e1afb198cb92c592b7e48ed491c74785c22d317b1`，两侧分别相同；先完成全字段比较再记录摘要。独立副本只为验证文件视图，原生提取未以旧facts JSON回放替代。但它不是原路径黄金全扫描、不是新G2工程，也不是正式dirty Diff通过。私有Git中的暂存/工作区审计标记不同，真实编译源未因此被改成另一个固件；编译源暂存/工作区不同等反例由7项原生Worker测试覆盖。

专项复现（从仓库根目录，保留首次失败及每次新日志）：

```powershell
py -3.10 -B -X utf8 -c "import sys,unittest;sys.path.insert(0,'tests');unittest.main(module=None)" tests.test_working_compiler_view tests.test_working_snapshot tests.test_parent_source_reads tests.test_scan_stability -v
```

获准工程复现用上述公开驱动，复制到获准工作目录后将`work=w/'working-view-approved-f030-v2'`指定为全新路径；驱动拒绝覆盖已有目录。原获准源、编译数据库、配置、SDK路径及所有输入/引擎哈希均记录在收据。完整旧新响应位于该私有工作目录，不能删掉后只保留摘要来声称验收。

下一子阶段必须把父进程源码/配置/响应文件读取及选文件操作接到同一捕获身份，再接入Git current固定、真实编译器探针、外置CMake、扩大闭包/缓存/恢复与`verify_against_full`。原有VFS/PCH/编译生成等未证明模式不能靠删参数或退回实时目录通过。只有各支持模式的完整原生与Diff对照、输入变化拒绝及原源码/.git/index/build无写入成立，才逐模式开放正式dirty入口。跨数据根迁移、继承证明、全消费者/大Diff和G2/G3/G7/G8外部验收仍按[方案68](68-remaining-refactor-execution-plan.md)继续。
