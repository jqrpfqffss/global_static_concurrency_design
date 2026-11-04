# 后续操作内存：已有结果刷新，第一个消费者验收

接续[94号审计](94-later-consumer-memory-contract.md)，本阶段只完成**已有原生权威库的`report`刷新**。完整复核、Packet、大Diff和故障恢复仍有读取工作，不能称第四项全部完成。功能支持/失败边界仍按[93号](93-dirty-database-workflow-acceptance.md)执行。

## 实现

`native_consumers.runtime_inputs`只读取原分类/身份/范围等摘要实际需要的字段，不恢复访问、调用、冲突乘积或全局求解关系。复用原`report.prepare`及`decisions/html_report`中的原有总结函数，没有另写分类规则。已有静态诊断/coverage不重算、不改写；完整权威库的report摘要、输入闭包、源码/环境/引擎门禁仍在刷新前后执行。

`workflow._saved_run(render_only=True)`及源码改变后的失效分支使用该元数据。`report.generate`、`scan_persistence.persist`新增“仅已有库”内部约束：元数据不能用于创建/替换静态authority，原始AI/人工数据库仍独立。普通扫描和实际复核没有被悄悄替换为小投影。`cli`补显式固定视图重验阶段，长耗时校验不留空白阶段或假百分比。

## 可复核结果

| 验收 | 实际结果 / 证据 |
|---|---|
| 原/新运行时完整一致 | 4项初验全部PASS，24.460秒；PENDING、5种语义结论、TECH_FAILED及full/Diff逐一执行原完整生成与新投影持久化，完整解码runtime相等；禁止缺库时从元数据新建authority |
| 扩展回归 | `test_native_refresh`、`test_native_consumers`、两个真实dirty保存/复核配置场景：15项全部PASS，118.491秒；包含实际源码改变后标失效，`EvidenceProvider.load`全程禁用 |
| 真实原路径F030 | [收据](acceptance/native-refresh-f030-v48-v1.json)，原生扫描+原完整生成对照+真实`report`刷新共32.765秒；完整runtime差异0、全图重建调用0、原authority SHA及原件不变 |
| F030完整静态G1子对照 | 与v44同源同构建扫描完整facts/report差异均0；facts根`514fa4543569ada226992813ef3b63164d99032f505e7b01e7919e29126e4c48`；真实2 PARSED/2 PARTIAL和INCOMPLETE保留，不删失败来源 |
| 既有真实INAV完整库消费 | [实际2GiB Job收据](acceptance/inav-runtime-projection-v48-v1.json)：12590489600字节原authority，16566变量、3540候选/AI事件；完整runtime/AI投影差异0；原库、reviews.db、state、manifest全SHA前后相同 |
| INAV资源 | 实际Job提交峰值121921536B（约116.27MiB），进程树RSS峰值133251072B；元数据读取/原总结/独立runtime落盘6.000秒，含原12.59GB库及收据前后完整SHA的控制器75.594秒。与其他回归并行，未测同条件旧完整消费者峰值，不能声称相对提速或内存降低比例 |

INAV此项只读**旧v13生产者49960e**的完整事实库，在全新scratch里持久化AI/runtime对照；没有在原数据根写入。不是新原生扫描、完整`status/saved_run`输入重放、完整复核、GUI发布或物理32GB验收，不能把它合并进G2新生产者结果。旧G3/G4整体门禁状态不变。

源冻结v48：父提交`d3308d8390e6e64981af87e945611ad8c6cf1a0c`加工作区覆盖，3746文件，清单SHA256 `461bc2342ea670a42f63809310958c6848bf85f95f167a23e69a942e4d200aa5`。源/观察器SHA均由实际Job控制器核验。测试文件之后仅修正旧拒绝文案断言，冻结源不改。

## 完整回归失败记录与剩余工作

[v46完整回归](acceptance/full-regression-studio-v46-v2-failed.json)实际1494项：1491PASS / 1FAIL / 2联网SKIP，2543.887秒，3722引擎及测试副本SHA无变化。失败是`test_working_compiler_view`仍要求“隔离快照尚未完成验收”的旧全阻断文案；产品已按91号只开放显式数据库，auto/CMake仍拒绝。本次保留低磁盘/外部复制竞态及auto拒绝检查，只将文案断言更新为“显式编译数据库”，单项2.724秒PASS，未删除或跳过测试。较新v48完整回归仍执行，包含同一旧断言，不改运行中的冻结副本，不宣告完整通过。

后续仍须完成：实际复核/Packet的逐对象完整读取和原Packet对照、大Diff/恢复工作集、dirty视图跨根重放、CMake未提交构建及完整故障矩阵。最新封存Portable仍v37，未包含新增功能。其他G2工程按用户要求待验，物理32GB/第二PC/干净离线/原生DPI/真实联网模型/UAT继续NOT_VERIFIED；完整重构及G1–G8未全部完成。

复现大库消费（新目录，原件只读）：

```powershell
py -3.10 -B -X utf8 scripts/validate_native_runtime_projection.py --source <已封存完整scan目录> --work <独立全新验收目录> --job-gib 2
py -3.10 -B -X utf8 -m unittest tests.test_native_refresh tests.test_native_consumers -q
```
