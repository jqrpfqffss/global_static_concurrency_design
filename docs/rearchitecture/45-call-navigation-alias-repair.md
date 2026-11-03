# 调用邻居：旧字段别名的真实修复

2026-11-03。v27封存后独立发现/实施；不把本修复借为v27已打包内容，不修改任何扫描算法、事实、schema或原档案。

实际隔离旧格式重现：calls使用caller_id/callee_id时，原既有投影正确保存source_id=caller，但QueryService.call_neighbors只从summary读取caller_function_id，返回neighbor_id=null。UI因此有调用边和数量，却无法继续展开该调用者。[重现](evidence/call-neighbor-alias-reproduction-v1.json)不是原生扫描或模拟产品页面。

实现改为优先使用已校验的source_id/target_id，继续保留v1档案缺少投影值时的原engine字段回退。字段别名优先级仍由既有投影定义；同名不同TU不按名称合并，多处调用的ordinal/次数/顺序不变。没有改旧数据库、重新推断分类或构造新边。

| 验收 | 实际结果 |
|---|---|
| 新兼容场景 | caller/caller_id及callee/callee_id、强字段优先、同名不同TU、重复调用、多页、双向展开、定义链接、FastAPI实际请求；原静态文件字节不变 |
| v1实际schema | 使用冻结旧schema构造原投影缺失值的完整typed档案，完整深检通过；原engine字段双向回退及定义链接正确，静态字节不变 |
| 首轮回归 | 21项中1夹具URI连接错误，原失败保留；仅修正测试连接uri=True，未因此改产品逻辑 |
| 联合专项 | 34PASS，19.687s，0错误/0SKIP；API、原有完整图/类型/标量/分页及新调用兼容场景。[收据](evidence/call-neighbor-alias-focused-v2.json)、[原失败](evidence/call-neighbor-alias-focused-v1-failed.json) |
| 大型调用树/本修复新实包 | 待当前真实INAV完整协议及后续实际浏览器/新打包验证，不借小夹具关闭U12/U13/G7。v27分析/打包仍指1493c05 |

变更仅ecra/studio/query.py与tests/test_studio_call_navigation.py。复现：`py -3.10 -B -X utf8 -m unittest tests.test_studio_call_navigation tests.test_studio_api tests.test_scan_store -v`。当前大型扫描、原版备份/全图及比较队列继续使用其冻结v27源文件，本次查询层修复不注入运行任务。

## v1投影存在时禁止二次回退（后续独立修复）

对冻结v1 schema完整构造并通过深检的档案进一步核对发现：v1的caller/callee投影与caller_function_id/callee_function_id不同时，原查询使用“投影匹配 OR 原字段匹配”，同一调用边因此可能同时计入两个调用者或被调用者。先运行新增场景，实际得到2条而非1条，原失败日志保留。该问题不表示分析器新增了调用边，而是只读筛选把历史边归属扩大。

ecra/scan_store.py现在仅在source_id/target_id为NULL时启用v1原引擎字段回退；已有历史投影优先级、全部原字段、ordinal、重复次数、schema和数据库字节保持原样。新增测试覆盖相互冲突的caller与callee别名、缺投影回退、上/下游筛选和完整深检。

| 验收 | 实际结果 |
|---|---|
| 修复前 | 1项实际FAIL：总数2、next_offset=1，期望总数1、无下一页。[原失败](evidence/call-v1-projection-precedence-before-v1.json) |
| 修复后联合专项 | 35PASS、0SKIP、14.558s，包含API13项、ScanStore19项及调用导航3项。[收据](evidence/call-v1-projection-precedence-focused-v2.json) |
| 已有实包/正在完整回归 | v27和已冻结v28均不包含本段修复；1371项v28回归不能记为本修复回归。新冻结版本及其Portable仍待实际验收。 |

本段修复只影响v1归档只读查询，未修改受保护分析算法或运行中的v27大型扫描。原失败与首轮35项通过的日志分别保留，不覆盖后续补齐callee断言的第二轮日志。
