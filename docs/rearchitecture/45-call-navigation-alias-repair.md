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
