# 首次工作区初始化停止：缺陷修复与验收

接续[99号修复合同](99-owner-publication-stop-contract.md)。真实包内Python3.10.9/F030在首次初始化期间安全停止，留下完整`project.json.pending`；重试被原安全归属门禁拒绝。[实际失败](acceptance/portable-review-v58-owner-stop-failed.json)保留，不将v58工具链检查PASS当作整个应用通过，不将其升级为最新封存包。

`workspace._owner_publication`只在主线程创建归属claim→flush/fsync→原子改名的短临界区暂缓SIGINT，完成后恢复原处理器并交付停止。已写入完整归属后，停止仍为130；后续初始化可以正常重试。API线程不安装全局信号处理器。直接抛KeyboardInterrupt时，只清理本次新建且未发布的claim；I/O异常、历史未知pending、硬退出等原保守人工恢复规则不放宽。未删除旧数据/人工历史，不接管外来锁，不改归属身份算法/路径边界。

这项改动属于`workspace.py`，仍计入原静态引擎摘要。因此旧检查点按原门禁需新扫描，**没有给旧state替换指纹或把workspace排除出引擎校验**。原历史结果仍可查看；新扫描证据继承继续遵守完整输入/事实不变证明。

| 验收 | 实际结果 | 证据 |
|---|---|---|
| 三项新增故障测试 | 在claim刚打开、fsync中、改名后实际调用`_thread.interrupt_main`，完整marker先发布、原处理器恢复、无悬挂claim、重试成功；显式异常回滚/I/O失败保留；API线程不碰全局信号。独立3项1.485秒PASS，含于下列23项，不相加 | `tests/test_workspace.py`新增三方法 |
| 原工作区/隔离/归属回归 | 23项全部PASS，218.179秒；包括原未知pending、损坏、身份冲突、外置构建、迁移和锁保护 | [冻结源码核对收据](acceptance/owner-publication-regression-v59.json) |
| 原生/搬迁/复核 | 冻结v59，32项全部PASS，138.780秒：canonical_scan/studio_workspace/data_transfer/native_review_workflow；不允许whole-authority重建，失败重试/AI历史/原静态仍验证 | 同上；两组是分开执行，不冒称完整全套 |
| 真正原路径F030新原生 | 24.547秒，退出2并保留原2PARSED/2PARTIAL及INCOMPLETE；与v48完整facts/report根均0差，43个原文件内容/大小/mtime未变 | [原生收据](acceptance/owner-publication-f030-v59.json) |
| 真实Chrome/F030停止重试 | 新原生检查点复制到独立数据根，真实服务/受监督进程停止→重试→6项技术失败→failed-only历史新增→完整Packet查看→完整包导入相同；静态SHA和人工历史/原件/代码资产不变，无页面错误/外部请求 | [浏览器收据](acceptance/owner-publication-f030-ui-v59.json)、[截图](ui/screenshots/owner-stop-v59/02-real-review-failures-count.png) |

新F030库物理SHA256 `3d5fa4b74a225c28fd88cdb033c14faad9eac44f34bbdb89b9c9ce17a01d6df7`，这是新扫描，不覆盖原库。完整facts根仍为`514fa4543569ada226992813ef3b63164d99032f505e7b01e7919e29126e4c48`，report根仍为`62fd77e001bef0561313db0d9d148bab6c29ddf47a4b930bbc813e325a0af4b6`。没有删PARTIAL来通过Diff门禁。

冻结v59父提交677e760加工作区覆盖，3779文件，清单SHA256 `474a45e2648ead76f22b7510c42d1e77aec8880f92be5f39b8e55ed607b19fb3`；冻结文件后验无变化，原仓库engine/tests逐字节匹配冻结源。v54全套1506PASS/2SKIP属于修复前读路径，不冒称v59全套。修复后的新Portable须独立验证才能封存；物理机/联网模型/UAT/G1–G8整体仍未通过。

复现关键故障（其余方法为同一模块，完整命令见机器收据）：

```powershell
py -3.10 -B -X utf8 -m unittest tests.test_workspace -q
py -3.10 -B -X utf8 -m unittest tests.test_canonical_scan tests.test_studio_workspace tests.test_data_transfer tests.test_native_review_workflow -v
py -3.10 -B -X utf8 scripts/validate_native_review_ui.py --source <本版真实原生scan目录> --config <本版原有效配置> --work <独立新目录>
```
