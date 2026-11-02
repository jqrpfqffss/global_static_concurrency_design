# GUI选择下次启动目录：实现与验收

2026-11-03（北京时间）。按[冻结合同](ui/27-data-root-selection-contract.md)，在原设置页实现普通用户的数据目录选择。WorkspaceResolver仍是唯一解析器：启动参数优先，其次ECRA_DATA_ROOT、GUI默认值、原系统默认。偏好存于用户ECRAStudio/preferences.json，独立于可替换程序和所选数据根；当前窗口与任务绑定原根，关闭启动窗口后重开ECRA.cmd生效。

| 实现 | 文件 | 边界 |
|---|---|---|
| 启动偏好/边界/预览/原子CAS保存 | ecra/studio_preferences.py、ecra/workspace.py | 空根/已登记根；禁止盘根、程序、已知固件、当前根父子路径、链接及其他非空目录；只在明确保存时检查目标可写。 |
| 当前服务与恢复 | ecra/studio/server.py、__main__.py | 原Host/Origin/session保护；保存不切换当前服务；损坏偏好进入明确恢复默认目录并显示全局警告，原设置按内容SHA备份后才修复。显式启动位置不被偏好覆盖。 |
| 普通表单 | DataRootSettings.vue、DirectoryBrowser.vue、App.vue | 只读浏览→检查归属→保存；路径变动废弃旧预览；修复必须显式勾选备份；错误保留输入和原默认值。 |

| 验收 | 实际结果 | 证据 |
|---|---|---|
| 新专项14项 | 优先级、预览只读、精确备份/未知字段、已有归档/全事件重开、真实目录链接、固件/程序/盘根/父子拒绝、实际文件锁冲突、旧revision/变更归属拒绝、损坏偏好恢复、原子替换/可写检查失败保持旧值 | [43项组合回归](evidence/preferences-focused-v2.json)，含历史/身份/API；43PASS，26.703s |
| 真实启动器+Chrome6项 | 私有LOCALAPPDATA，两份已有真实F030归档；实际ECRA.cmd保存→当前根保持→关闭重开选中根/人工事件保留；保存未来根后，当前GUI真实F030扫描仍发布在原服务根；原固件目录被拒绝；损坏偏好实际重开进入恢复，显式备份修复，再次重开正确 | [实际收据](evidence/browser-data-root-host-v1.json)、[所选根实图](ui/screenshots/data-root-host-v1/05-actual-cmd-reopen-saved-root-with-human-events.png) |
| 原数据/程序 | 121个原归档组件、42个原固件文件、原配置及122个ecra文件前后不变；所有原人工事件不变 | 同上。新增扫描为独立根内的新真实任务，不充作大型G1/G2。 |
| 后续两项保护 | GUI6项后补充实际偏好锁冲突→409及手改程序父目录偏好拒绝；均进入上述43项组合回归 | 新实包必须重新运行启动器流程，不借旧源码浏览器证明新增分支。 |
| 前端 | TypeScript/Vue检查、63模块Vite离线构建PASS；无新增依赖，原导航/真实API/无外网资产静态合同通过 | [静态合同](evidence/preferences-static-contract-v1.json) |
| 新完整回归/实包 | 后续冻结候选尚需1351项及实际新包历史/目录流程；v24不含本功能 | NOT_VERIFIED |

复现：

    py -3.10 -B -X utf8 -m unittest tests.test_studio_preferences tests.test_studio_history tests.test_scan_identity tests.test_studio_api -v
    npm.cmd --prefix studio run build
    py -3.10 -B -X utf8 scripts/validate_data_root_ui.py --archive-list <既有真实归档清单> --config <原获准F030配置> --work <新独立目录> --evidence <新截图目录> --allow-external-toolchain

此脚本在私有LOCALAPPDATA保存偏好，不更改实际用户默认设置，所有启动器进程纳入自己的2GiB Windows Job。不是干净离线PC或32GB性能测试。

残留：完整数据根搬迁（含运行记录/构建路径/引用重定位）未实现；现有归档迁移仍用数据与共享。超1MiB或权限拒绝的偏好拒绝读取并进入恢复提示，自动GUI修复该类文件尚未覆盖；不覆盖/丢弃未知原字节。第二物理机、完整只读生产写保护、Windows原生DPI、真实OpenCode及工程师UAT仍待验。

2026-11-03实包闭环：上述功能已在冻结dca72be的v25实际分发中验收（历史8项、启动目录6项），并完成1351项回归与16组131个重叠Chrome断言；收据/截图见[39号封存](39-frozen-v25-and-large-gate-errata.md)。此闭环不包含后续页缓存/hash seed源代码，也不改变大型G1/G4失败状态。
