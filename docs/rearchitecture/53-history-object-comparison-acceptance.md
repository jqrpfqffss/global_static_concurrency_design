# 历史对象对比：实际操作与证据入口

落实任务书7.10“与基准对比”：按先行[交互合同](ui/30-history-comparison-contract.md)，在现有历史行选择基准、从另一批次发起对比，同页查看分类/完整根摘要、检索canonical对象，打开基准或当前的完整证据工作台。无新增导航或模拟页面。原生Git Diff、静态判定、人工事件协议不变。

| 实现 | 边界 |
|---|---|
| `ecra/studio/comparison.py` | 仅只读两个已保存库；完整canonical ID精确关联，同名不同TU不合并。SQL双左连接支持包内SQLite版本，服务器分页/字面搜索/类型筛选；临时SQL工作集落文件，两个库读缓存各8MiB，不恢复完整facts/report。 |
| `GET /api/history/compare` | 原有Host/Origin/session边界、受控扫描ID路径校验；同批次、不同工程、缺证据旧原件、未发布任务、清单不一致拒绝，原库/人工记录不写入。 |
| 保守证据比较 | 事实或报告完整根任一变化，所有共有对象均提示变化需核对；只有双方完整根及对象节点指纹相同时显示归档证据相同。新增/本轮未观察到分别显示；绝不将后者称已修复，也不自动继承旧SAFE。 |
| Vue实际操作 | 基准/方向按数据根保存；返回历史保留检索位置；双方完整身份/根摘要可展开；分页读取成功后原子替换页序号和行；双方证据按钮复用原工作台精确定位，分别显示原静态分类。 |

| 验收 | 结果 | 证据 |
|---|---|---|
| 新比较单测 | 8PASS，10.081s。覆盖同根不改事件、同名不同canonical、完整上下文/报告/顺序变化、反向与分页、字面特殊字符/注入串、缺证据/未发布/损坏发布绑定、配置边界及20007对象容量夹具 | [专项](evidence/history-comparison-focused-v1.json) |
| 相关回归 | 41PASS，33.048s，比较/历史/API/原生下载/完整包 | [回归](evidence/history-comparison-focused-v2.json) |
| 前端 | vue-tsc+Vite，1.33s；最终index-C0ah1Ypi.js/index-B6exn6Xr.css | [构建及资产SHA](evidence/history-comparison-frontend-v3.json) |
| Chrome首轮 | 已完成10组，打开基准证据后错误测试定位器`.detail`找不到，实际工作台已打开；修正为现有`.detail-panel`，失败数据/截图保留 | [原失败](evidence/browser-history-comparison-host-v1.json) |
| Chrome次轮 | 14组通过，包括原历史8组及新对比6组；随后截图审查将分页横排并移除面向用户的验收门禁术语 | [v2](evidence/browser-history-comparison-host-v2.json) |
| 最终Chrome | **14组通过**；23份既有真实原生F030归档副本，双方实际15个canonical对象均因全局完整证据变化保守提示需核对；`c:@HCLK`在双方均有真实访问，按钮分别打开正确批次/身份/完整证据 | [v3](evidence/browser-history-comparison-host-v3.json) |
| 数据保持 | 1534份原来源文件SHA/大小/mtime不变；23份私有静态库SHA不变；原人工事件均未改变；128份当前运行时文件SHA不变 | 同上 |
| 明确范围 | 真实F030配对只有15对象，已验证一页末尾按钮禁用；20007分页是明确标注单测夹具，**未声称真实大工程多页网络挂起验收**。实际无效配对测试是同批次认证HTTP，不同工程为单测，不冒充实际GUI跨工程测试 | 同上，收据单独列出范围 |
| 剩余 | 当前源码完整1392项回归、新Portable包待实际执行；大型原生完整包、物理第二机器/DPI/UAT仍待验。本功能不是严格同输入G1证明，也不实现自动人工确认继承 | NOT_VERIFIED |

[1366实际界面](ui/screenshots/continuation-20261103/history-comparison-host-v3-11-comparison-reopen-1366.png)、[基准方向/真实计数](ui/screenshots/continuation-20261103/history-comparison-host-v3-09-real-archive-comparison-direction-and-counts.png)、[双方证据入口/人工历史保持](ui/screenshots/continuation-20261103/history-comparison-host-v3-10-both-evidence-entries-preserve-original-human-history.png)。浏览器密度不是Windows系统DPI测试。当前源码功能不回填为v30已经包含。

```powershell
py -3.10 -B -X utf8 -m unittest tests.test_studio_comparison tests.test_studio_history tests.test_studio_api tests.test_studio_downloads tests.test_report_package -v
cd studio
npm run build
```

实际浏览器复现：`scripts/validate_history_ui.py --engine <源码或实包> --python <服务解释器> --archive-list <已获准真实归档目录清单> --work <全新独立目录> --evidence <全新独立证据目录> --comparison-acceptance`。清单及本轮原始控制器/trace保留于`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/history-comparison-*`，不以伪造扫描身份造场景。
