# 最终 V9 工作区只读一致性复核

结论：**DEVIATIONS_FOUND**，差异 1 项。

- 主工作区、final-engine-v9、最终中文空格解压包各154生产文件逐SHA匹配；三个核心均为`2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`。
- `App.vue`、`workbench.css`的主区/冻结源/builder SHA一致；`build_portable.ps1`同审阅值`69aeebd31b85dd020375ca55bc50aeb04f3c710fab219b2d33c3799a414185cd`。前端开发源不进入runtime，生成资产另纳入154文件检查。
- 当前分支`optimize_ccc`，HEAD仍`fe27afe73596d98e1a21e3f28a2125d38d7272d0`；暂存区为空，复核前后index SHA不变。现有本地修改保留。
- 最终ZIP `H:\ECRA-quality-20261108-offline-build-v9\ECRA-Portable.zip`，785692863字节，SHA256 `7a0e45b0f3dda3ee47d7759f9784ab66ca9f8fa089543157f64c9f9be9a6c03d`，与official和实际解压收据一致。
- V8→V9生产差异仅index.html与两组JS/CSS资产替换；127 Python及27772工具文件的闭包清单SHA相同。原V8 Git18/ARM结果保留V8标记；未将整个runtime、ZIP或最终Q405界面假定相同。
- 本次未执行push/fetch/commit或网络命令；本地HEAD检查不构成对其它进程历史推送的远端审计。没有读取INAV数据、冻结V4、重建或全工具字节重hash。

完整逐文件SHA、本地只读Git命令、ZIP元数据差异和偏差列表：[final-worktree-v9.json](final-worktree-v9.json)。最终GUI/nativeDiff由对应独立验收记录判断。
