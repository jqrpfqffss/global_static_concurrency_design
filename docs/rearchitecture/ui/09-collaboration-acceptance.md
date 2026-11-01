# 双端确认协作验收合同与实测

继承原有“数据与共享→导入增量”“变量与风险→人工历史→确认操作”布局，没有新增模拟页面。两端均从同一真实原生F030完整包导入，使用两个受打包Python3.10.9驱动的Studio服务器、独立数据根/设备声明、真实Chrome隔离origin。所有事件变更、导出、导入经过可见GUI；数据库只独立检查结果。

| 操作 | 实际结果 | 证据 |
|---|---|---|
| A确认→导出增量→B导入两次 | 新增1，再次新增0 | browser-collaboration-v3.json |
| A确认无风险、B暂无法确认并离线合并 | 两分支同时保留，各自确认者/设备/依据可查 | screenshots/collaboration-v3/01-both-device-conflicts-visible.png |
| 空依据尝试解决冲突 | 真实400与可理解提示，3个事件及两分支未变化 | 同收据第四项 |
| 核对历史后填写依据、选择新结论 | 新增第4个事件，parents恰为全部两个冲突头，原事件不改 | 02-explicit-resolution-retains-history.png |
| A导出完整包→B已有扫描再导入→重开 | 新增2，四事件字节逻辑内容与A一致；新结论和历史保留 | 03-imported-full-package-history-after-reopen.png |
| B最终增量回A | 新增0，静态库/原始原生结果未改，无外部请求/page error | 同收据第七项 |

SQLite Backup一致快照可能改变物理数据库头，不能把其SHA不同误报静态证据修改。实际核对每个导入库相对首次导入的SHA始终不变，并对完整图/投影/引用作deep校验、绑定与源一致；原生源目录全部文件SHA亦不变。首两次验证器失败和原始日志保留在continuation-h3/collaboration-v1、v2；v1是DevTools响应体缓存逐出，v2是错误的跨Backup物理SHA断言。未改产品逻辑掩盖失败。

结论仅为本机两origin七项自动化通过，不能将它称为第二台物理电脑、无源码干净环境、工程师满意度或目标板硬件验证。U19/U20完整场景仍保留未验证边界。完整trace/video见output/playwright/studio-collaboration-v3；截图已人工目视检查1600×900布局和固定确认区。
