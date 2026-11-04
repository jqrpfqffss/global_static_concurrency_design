# R2c第一步：实际完整扫描接入同一冻结输入

> 后续真实F030全链路已结束，冻结`f2dca32`：4 TU保持2 PARSED/2 PARTIAL，普通与冻结完整有序事实/既有规范化报告0/0，完整包严格独立导入0/0，原始/私有Git/SDK/build/引擎全部SHA不变；1714个固定文件，736.750秒。[实际收据](evidence/frozen-full-approved-f030-v1.json)、[8GiB受控进程资源](evidence/frozen-full-approved-f030-execution-v1.json)。这是独立获准源副本，不改标为原路径黄金或真实dirty Diff；普通扫描26.891秒、冻结扫描474.375秒，额外全树/原始输入验证开销明显，**不称提速或正式生产性能完成**。下方“待执行”为当时记录；后续第二步代码仍需独立验证。

按[76号审计](76-dirty-production-integration-audit.md)，本阶段接通完整原生扫描的内部验证入口，并实际执行扫描、缓存、报告发布及标准完整包。**没有解除正式dirty/Diff/CMake/恢复门禁**，不是U04完成。`all_gates_passed=false`。

| 实现 | 实际行为 | 验收 |
|---|---|---|
| `cli.dependency_inputs/dependency_results` | 显式跨线程/进程传递同一视图；每轮依赖发现都运行原始和冻结Clang，完整实际输入字节/集合及预处理签名不同即失败；参考请求/响应保留 | 真实2 TU、2线程，所有依赖阶段及负探针故障 |
| `cli.extraction_responses/run` | 完整提取使用固定视图；缓存命中也核对固定字节，保留原TU顺序、部分/失败与全部分析逻辑 | 冷/热/真实损坏缓存，完整有序有类型事实及既有规范化报告0/0 |
| `frozen_scan.ScanFiles` | 复用已有ParentFiles/Resolver，配置消费记录与冻结字节核对；每道屏障重新核对原文件、目录、HEAD和index；所有退出关闭视图 | 索引变化、捕获损坏失败；上一有效快照不变 |
| `scan_persistence` | 归档源码使用受验证字节；完整归档审计后再核对原输入和引擎，然后才发布manifest/最新指针 | 实际完整包严格独立导入0/0；审计期间改变原源码也不能发布指针 |
| `scripts/validate_frozen_scan_pipeline.py` | 获准源的独立副本、独立Git staged/work字节、真实编译数据库/参数/外部搜索边界；运行两个完整原生扫描、全字段对照、完整包/独立导入及全SHA保护 | 本阶段新控制器待真实F030执行，不以脚本存在记PASS |

专项最终 **5/5 PASS，123.707秒**：[源码/日志SHA与精确计数](evidence/frozen-scan-pipeline-source-v1.json)、[完整日志](evidence/frozen-scan-pipeline-v3.log)。5项包括完整冷/热/损坏缓存及完整包、负探针变化、真实Git索引变化、捕获损坏/不支持模式拒绝、长归档审计期间原输入变化。测试调用真实Clang Worker、分析器和原生发布，故障注入只在明确边界改变独立夹具，未用模拟提取响应替代扫描。

旧4项成功95.758秒见[v1日志](evidence/frozen-scan-pipeline-v1.log)。补加审计后屏障时一处`read_json`缺少导入，5项中4通过/1ERROR，见[v2失败日志](evidence/frozen-scan-pipeline-v2.log)；补齐导入后完整5项重新通过，不覆盖旧失败。更早夹具未初始化Resolver及两个控制扫描共用历史身份导致的baseline差异在工具执行记录中保留；随后使用独立控制profile，比较器及规范化合同没有改动。

私有参数`_compiler_view`不能由普通CLI/GUI设置。内部模式要求新建独立原生目录、显式compile_database、完整扫描、build_closure_only；自动发现、CMake、Diff、补充扫描及doctor均明确拒绝。它不把运行UUID/视图地址塞入有效analysis配置，也不修改受保护求解、canonical身份、NVIC、上下文或风险分类。冻结输入闭包的正式恢复仍明确拒绝，不能忽略视图身份后读实时源码。

下一步对本批精确源码冻结并运行新1444完整回归、原路径F030黄金对照，以及新控制器的获准F030独立副本全链路对照。完成前这些项目保持NOT_VERIFIED，不借用[79号](79-r2b-regression-and-v13-package-final.md)的旧1439结果。随后继续dirty的捕获时点/pin/base→current、完整Diff/cache/verify_against_full、构建和恢复逐模式证明，达到条件后才开放对应正式入口。R3–R7与外部待验范围不变。
