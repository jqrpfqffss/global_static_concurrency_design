# 任务元数据短暂读取失败与固定操作合同

已修复并实际验证：read_task_json局部重试、pollError独立恢复和flex剩余视口已接入。12项任务/API专项通过（2项新读故障、10项原API）；主流程Chrome16项通过，包含真正CreateFileW独占只读句柄造成API失败→UI提示→释放后恢复的完整流程，没有mock API。任务记录/静态库SHA不变，1366与1600主操作都在首屏。见[evidence/browser-main-git-picker-v2.json](../evidence/browser-main-git-picker-v2.json)、[实际读失败](screenshots/git-selection-v2/03-real-sharing-failure.png)、[已发布操作](screenshots/git-selection-v2/04-published-action.png)。配置往返另7项通过。永久权限失败/JSON损坏仍显式失败；全故障矩阵/系统DPI/UAT继续未验。

实际Chrome主流程main-git-picker-v1失败：Windows读取正在原子替换的task.json出现PermissionError；后续任务已经发布，旧轮询错误仍持续显示，把“打开扫描结果”挤出1366首屏。失败截图/trace保留。这是已观察到的缺陷，不以删除坐标断言过关。

只对任务所属的状态/诊断JSON增加最多5次、合计200ms的PermissionError读取重试；永久拒绝仍返回错误，损坏JSON、丢文件/输入门禁不吞掉，不退回缓存伪称最新。与全局read_json分开，不改变静态输入消费规则。

页面分开记录轮询错误和用户操作错误；下一次完整轮询成功仅清除对应轮询错误，不清除操作失败。失败时保留最后一次真实详情并明确“状态暂时无法读取，正在重试”，技术原因可展开；不呈现新的阶段或假成功。现有主操作/顺序/导航/token保持，任务容器按实际剩余视口伸缩，错误、提示和展开配置不能把固定任务操作挤出首屏，长阶段/日志在自身面板滚动。

增加真实Windows文件共享锁注入：已完成且不再写入的本任务task.json暂时被只读独占句柄锁住，实际API读取失败→真实浏览器显示轮询错误→释放句柄→真实轮询成功恢复；全程静态库和任务记录原字节不变，打开操作在1366/1600首屏。不是Playwright mock响应。另单测证明永久权限失败与JSON损坏不被静默忽略，并重跑15项原主流程/配置往返。系统DPI/物理双机/UAT仍未验。
