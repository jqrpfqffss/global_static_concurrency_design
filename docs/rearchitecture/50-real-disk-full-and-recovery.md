# 真实NTFS磁盘满、人工确认与导出恢复

本阶段修复真实故障暴露的专业交互缺陷：v30发生SQLITE_FULL时只显示英文`database or disk is full`。现由服务统一识别SQLite满盘、ENOSPC及Windows磁盘满错误，保留技术原文，说明检查独立数据盘/临时盘、释放空间、核对当前结果和人工状态再重试，并指向“数据与共享”。不承诺所有多步骤操作均完全未保存，不把失败说成成功。

| 阶段/实现 | 实际验收 | 状态 | 证据 |
|---|---|---|---|
| 首轮真实VHD | 已收到内核ENOSPC，但测试错误假设必须剩余不足4096B；NTFS当时20480B空闲仍不能扩展，0组完成。原失败保留 | FAIL（测试前置假设） | [v1](evidence/real-disk-full-volume-v1.json) |
| v30真实VHD | 人工提交拒绝且原事件完整；导出不发布半包且旧包/静态库不变；释放填充后同一GUI提交和严格包往返成功；中文可操作性失败 | FAIL（错误交互），4个完整性/恢复组PASS | [v2](evidence/real-disk-full-volume-v2.json) |
| 源码修复真实VHD | 新建256MiB虚拟NTFS真正写至内核ENOSPC，剩余0B；4组完整性/恢复及中文原因/恢复动作均通过 | PASS，仅本子范围 | [v3](evidence/real-disk-full-volume-v3.json) |
| 可复用脚本重跑 | 参数化实际引擎/解释器/获准包/新工作目录；同样4组通过，运行时源码SHA无变化；不是模拟错误或页面 | PASS | [v4](evidence/real-disk-full-volume-v4.json) |
| API/归档专项 | 首次26项25PASS/1FAIL：断言用了Windows短路径，服务正确返回规范长路径；修正测试后26PASS，13.569s。数据库锁错误不误标磁盘满，失败无新事件且静态字节不变 | PASS，原失败保留 | [原失败](evidence/disk-full-messages-focused-v1.json)、[通过](evidence/disk-full-messages-focused-v2.json) |
| G5完整门禁 | 本轮覆盖真实满盘写人工/导出/恢复；断电、全部WAL边界、迁移中断等未齐 | NOT_VERIFIED | 不以本子范围关闭G5 |

测试只格式化本次新建的256MiB文件型VHD：先核对映像路径与唯一关联磁盘、RAW、精确大小、File Backed Virtual、非启动/系统盘，再核对新增分区身份与原先未占用盘符。填充只写新建自有文件；恢复只截短持有句柄的该文件；finally正常卸载该映像。四次映像/失败现场均保留，四份生命周期均`detached:true`。这不是物理系统盘写满或物理32GB机器验收。驱动见[scripts/validate_disk_full_volume.ps1](../../scripts/validate_disk_full_volume.ps1)，实际浏览器和事务断言见[scripts/validate_disk_full_ui.py](../../scripts/validate_disk_full_ui.py)。

| 数据保持 | v3/v4实际结果 |
|---|---|
| 静态库SHA | 前后`867573286a1e6061bd6ec26a4126226eeb43562007f875e7bec3bbb7004f4634` |
| 原人工事件 | 满盘提交后仍1个、原内容完全相同；释放后新增1个，合计2个，旧事件仍完整 |
| 有效完整包 | 满盘导出失败后原包SHA不变，未出现新的最终`.ecra-report` |
| 恢复完整包 | 真实浏览器原生下载，独立数据根严格导入，静态binding及全部人工事件一致 |
| 固件/黄金输入 | 只操作获准F030完整结果包的私有副本；原包SHA保持；本轮没有新固件原生扫描 |

实际截图：[满盘确认失败](ui/screenshots/continuation-20261103/disk-full-v4-01-real-full-confirmation-not-saved.png)、[满盘导出保持旧包](ui/screenshots/continuation-20261103/disk-full-v4-02-real-full-export-keeps-last-valid-package.png)、[恢复后提交](ui/screenshots/continuation-20261103/disk-full-v4-03-space-recovered-real-confirmation-saves.png)。原始trace/日志只保留外部工作目录，不提交会话凭证。

复现（管理员PowerShell7；`WorkRoot`必须不存在，父目录已存在，保留全部映像；浏览器控制器需开发环境Python3.10和Playwright，实际服务解释器单独指定）：

```powershell
pwsh -NoProfile -File scripts/validate_disk_full_volume.ps1 -Engine H:/global_static_concurrency_design -Package H:/ECRAStudio-data/rearchitecture-20261031/studio-acceptance/exports/golden-f030.ecra-report -WorkRoot H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/new-disk-full-attempt -RuntimePython C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe
py -3.10 -B -X utf8 -m unittest tests.test_studio_api tests.test_studio_downloads tests.test_report_package -v
```

修复尚不在已封存v30中；新版本必须重新冻结/完整回归/打包并以包内解释器复测，不能将源码PASS借给旧包。
