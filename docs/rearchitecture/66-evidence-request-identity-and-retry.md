# 真实 TU 证据的请求归属与失败重试

2026-11-04。审计发现 `EvidenceNode.vue` 在接收另一个 node/scan 后仅清空视图，既不使旧请求失效，也不重读仍展开的节点。覆盖与诊断中，同一“原始真实编译命令”组件在切换 TU 时会复用，因此迟到的旧请求会把旧 TU 命令显示在当前 TU 区域。

| 阶段 / 实现 | 变更文件 | 实际测试 / 场景 | 状态 / 证据 |
|---|---|---|---|
| Phase 4，修复前真实复现 | 冻结 v35 / 5c21ac3 的真实页面 | 获准 F030 归档；挂起 startup.c 的真实节点请求，界面选择 main.c，再释放旧请求；当前区域错误显示 #22571，预期 #22610 | **FAIL 原件保留**：[实际失败](evidence/evidence-request-old-v35-v2-failed.json) |
| Phase 4，请求归属 | `studio/src/EvidenceNode.vue` | 身份切换或卸载使旧请求失效；展开节点自动读取当前身份；迟到旧响应不修改数据/错误/忙碌状态；实际原始编译命令各项顺序与后端一致 | 真实 F030 Chrome 4组 PASS：[源码实测](evidence/evidence-request-fixed-source-v1.json) |
| Phase 4，真实重试 | 同上；`scripts/validate_evidence_request_ui.py` | 实际网络中断→中文失败与“重试读取证据”→读取当前 TU 的真实节点；未伪造 HTTP 响应或分析数据 | 同一4组；修复前后控制器 SHA 完全相同 |
| Phase 4，长文本与分页 | `scripts/validate_studio_capacity.py` 的可选验收 | 首段真实请求中断时不显示假的“未知”内容；后段失败保留上一有效段，重试相同 UTF-8 offset；真实20007行、排序/重开、精确数值与有界证据分页仍通过 | 11个重叠场景 PASS：[传输夹具](evidence/evidence-text-retry-source-v2.json)；此夹具不是原生固件/G2 |
| Phase 4，编译与 UI 合同 | 已构建网页资源；现有设计 token 不改 | `npm run build` 的 vue-tsc/Vite 实际通过，12项机械合同通过 | 只证明已验源码，不借用为 v35 已包含 |
| Phase 6，包含该修复的 Portable | 后续新冻结源码 | 当前 v35 回归/构建队列绑定较早字节，不能静默更新其运行时 | NOT_VERIFIED；[v35额外发布状态](evidence/portable-v35-additional-release-readiness.json)明确失败缺陷 |

修复沿用既有原生 details、页码、条数、全部字段及 SHA 引用，不变更分析策略、证据内容或分页上限。节点与首段文本一并准备后才发布视图；文本换段失败时保留当前有效段并明确显示错误，重试仍使用失败的 offset。不会用人工确认或静态安全状态代替请求状态。

实际 F030 的 startup.c/main.c 原始命令节点分别为 #22571/#22610；编译器真正消费的标准化参数在此工程恰好共享同一节点，因此复现明确使用不同的**原始真实编译命令**，没有改造黄金输入制造差异。修复前脚本首次误选共享字段而未找到不同节点的 `StopIteration` 留在独立 work/log；改正后以完全相同控制器分别取得旧运行时 FAIL 和新源码 PASS。长文本第一次脚本有 `scan_id` 命名错误，[原失败](evidence/evidence-text-retry-source-v1-harness-failed.json)保留；修正后重新使用全新私有目录完整11项通过，不将脚本错误归咎于产品。

截图：[旧版本串入旧命令](ui/screenshots/evidence-request-source-v1/old-v35-real-stale-command-failure.png)、[切换后的正确命令](ui/screenshots/evidence-request-source-v1/f030-01-second-TU-keeps-its-real-command-after-old-response.png)、[实际故障及重试](ui/screenshots/evidence-request-source-v1/f030-02-real-network-failure-with-evidence-retry.png)、[重试成功](ui/screenshots/evidence-request-source-v1/f030-03-retry-reads-the-current-TU-from-real-backend.png)。原图已目视检查，未图像编辑。

复现命令：`py -3.10 -B -X utf8 scripts/validate_evidence_request_ui.py --package H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/parsed-f030-ui.ecra-report --engine <待验引擎目录> --python <其实际Python.exe> --work <新目录> --evidence <新证据目录>`；容量/文本命令为 `py -3.10 -B -X utf8 scripts/validate_studio_capacity.py --work <新目录> --evidence <新证据目录> --sorting --evidence-retry-acceptance`。

U14/U22 的这些子范围通过，不关闭完整缺口组合、原生系统 DPI 或工程师 UAT。旧 v34/v35 普通集合可能通过，但仍含本次额外复现的显示缺陷；其原字节和收据不改写，后续包必须实际重验。完整 H5/G7 仍未通过。
