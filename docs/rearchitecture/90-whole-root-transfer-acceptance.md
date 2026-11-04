# 整套数据搬迁：实际跨盘与原目录不可用验收

实施合同见[89号](89-whole-root-transfer-contract.md)，用户顺序见[87号](87-functional-priority-execution.md)。本项复用Resolver、不可变事实、人工事件、既有任务监督与启动设置，没有修改静态分析算法、判定阈值或Diff语义。

## 精确版本与结果

实际使用冻结v44：父提交 `6dae2eca171c7a154df7b3829fa8149440a57ab1` 加本次明确记录的工作区覆盖，3710文件，清单SHA `73800574928950b0222a9d93723c5a6330d1cd1dc51f768ba563d38b1706c2e0`。不是把父提交当新代码。冻结代码、测试副本和实际工程均独立于固件。

| 验证 | 实际结果 | 证据 |
|---|---|---|
| 搬迁/数据库/WAL/API/启动配置/真实扫描相关 | 49 PASS，114.802s | `test_data_transfer`、`test_studio_api`、`test_studio_preferences`、`test_canonical_scan` |
| 搬迁/真实构建预检查/Resolver/继承/完整包扩大回归 | 63 PASS，222.595s | `test_data_transfer`、`test_build_preflight`、`test_studio_workspace`、`test_workspace`、`test_review_inheritance`、`test_report_package`；范围重叠，不相加成独立总数 |
| 最终搬迁专项，含旧盘符/Windows短路径及配置无损派生 | 13 PASS，14.525s | `py -3.10 -B -X utf8 -m unittest tests.test_data_transfer -q`；真进程kill、rename后状态故障、WAL已提交内容、中途源变、空间不足、API/后台写入屏障均有断言 |
| 获准F030、真实Chrome、H→I盘中文路径复制 | PASS：140文件、11,959,464字节逐文件校验后发布 | [实际收据](acceptance/root-transfer-f030-v44.json)、[复制完成截图](ui/screenshots/root-transfer-v44/01-complete-copy.png) |
| 将本测试旧根暂时移开，旧根确实不可用 | PASS：新根旧检查点完整输入复验和CLI status可恢复；静态库SHA保持 `2c009b0fb6dc5a72d03106fed3e2552bb7882254801c3b9285bc696938bd3f99` | 同一实际收据；原测试目录最终恢复保留 |
| 新根继续人工确认及标准完整包独立导入 | PASS：原事件保留，新事件可见，导出后独立导入有两个事件 | [继续确认截图](ui/screenshots/root-transfer-v44/02-new-root-review.png)及同一收据 |
| 真正停止的监督任务搬迁后重试 | PASS：旧任务 `05f8fe01bdc2465481a731e9bda0d7f9` 实际130/INTERRUPTED；新根从其原配置派生输出并真实构建预检查/原生重扫 | 同一收据；不是构造任务页面/伪造停止元数据 |
| 原/新完整事实根 | 相等：`514fa4543569ada226992813ef3b63164d99032f505e7b01e7919e29126e4c48`；全部类型/顺序/关系由深校验根覆盖 | 同一收据。F030保留其真实部分解析/覆盖状态，没有冒充全覆盖 |
| 搬迁后新确认再次扫描的继承 | PASS：重扫沿用新根最后的“暂无法确认”，原来源可追溯，本轮零伪造事件 | [独立复验收据](acceptance/root-transfer-v44-inheritance.json)；在已完成v44真实流程后独立读取验证，未改写原收据 |
| 前端 | 类型检查、离线资产构建 PASS；实际Chrome无页面错误/外部请求 | `cd studio; npm run build`，实际收据 |
| v44完整回归1482项 | **1480 PASS / 2联网opt-in SKIP**，2368.375s，退出0 | [最终收据](acceptance/full-regression-studio-v44-final.json)；3710文件在冻结源/测试副本的SHA均无差异。仅对应v44，不代表之后的第三项开发源码已完整回归 |

最初Windows短路径反例确实失败，原因是8.3路径与长路径未统一；补充真实路径解析、保留迁移时短路径别名，并重新通过13项。较早v43实际GUI已走到新根确认，但验收脚本错误读取已经移开的旧路径而失败；旧失败收据保留。v44修正后四组全流程实际通过，不改写旧收据。

原固件43个文件/原配置的SHA、大小和mtime均未变化；原扫描和原人工事件不改；冻结引擎文件未变化。复制期间旧根保留，测试中的“不可用”由临时移动**本测试自己的**原数据目录实现，不删除/移动获准固件。

## 使用与复现

普通用户：**设置与验收状态 → 独立数据根 → 整套数据复制与恢复**。选择独立空目标，检查计划，启动完整复制；完成后在上方选择该目标保存，关闭软件再启动。恢复另一完整Studio根时勾选来源选项。失败保留原根与私有pending；能校验来源一致且存在日志时显示恢复按钮。

开发验收：`py -3.10 -B -X utf8 scripts/validate_root_transfer_ui.py --config <已获准F030配置> --work <新的独立目录> --target <另一盘的新目录>`。脚本只用显式获准输入、私有LOCALAPPDATA、真实服务/浏览器/监督进程，完成后保留所有收据。

活动profile只重绑已知路径，原文与未知字段均保留；旧构建/Git工作树完整留在新根保留区，由Resolver重新建立活动目录。无法证明的新编译输入如果仍指向旧数据根会阻断，明确要求在工程接入中检查/重建编译数据库；不会把未知路径字符串替换后冒充等价构建。

## 未关闭的门禁

这是获准F030的完整功能链路验收，并非50GB/INAV整根搬迁实测。物理32GB、第二台PC、原生DPI、干净离线Portable和工程师UAT仍NOT_VERIFIED。上一封口Portable仍为v37，本次功能在当前源码和已构建前端中实现，不能宣称v37已包含它们。

用户四项中：人工确认继承和本页搬迁的上述范围已实现并通过；正式未提交输入完整工作流接下来实施，消费者省内存最后处理。原H1–H6/G1–G8及完整重构仍未全部关闭，`all_gates_passed=false`。
