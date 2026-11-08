# V9 当前验收与交付记录

更新至 2026-11-08 14:43 UTC。代码修复、已完成的实际操作与尚未完成的门禁分别记录；本页不表示完整发布门禁已通过。旧轮次收据、失败和 ZIP 均保留。

当前主区为 `optimize_ccc` / `fe27afe73596d98e1a21e3f28a2125d38d7272d0`。静态引擎为 `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`。全部修复已在本地工作区；没有暂存、提交、推送、合并或发布。

独立只读核对确认主区、冻结引擎和解压包的154生产文件一致。冻结目录 `continuation-final-engine-v9` 仅用于固定分析/界面代码，其根级旧辅助打包脚本SHA仍为dc9845…；它不是本次正式构建输入。真正使用的 `continuation-builder-source-v9/build_portable.ps1` 与主区均为 reviewed SHA `69aeebd31b85dd020375ca55bc50aeb04f3c710fab219b2d33c3799a414185cd`，正式命令及快照收据绑定此builder。该非运行时差别原样列在 `final-worktree-v9.json` 的 DEVIATIONS_FOUND，未为取得字面全同而改冻结原件。

## 已完成与剩余门禁

| 范围 | 实际结果与依据 | 当前状态 |
|---|---|---|
| 误安全与证据 | 修复 NMI/HardFault 保护判据、同 ID 配置抹去向量证据、GNU 函数别名丢失入口、AI 证据不足掩盖静态冲突；真实 GCC/ELF、独立语义推理与相邻正反例复验 | 所列缺陷已修复；不扩展为任意机制完全支持 |
| 任务、归档与停止 | 坏任务/清单隔离、真实终态与恢复、SQLite 长检查可停止、旧容器派生兼容；有效旧库、人工事件和叶项证据保留 | 具体契约与原故障复验通过，见台账 |
| Git、缓存与工作字节 | 只读索引、旧 Git stat-only 误选、目录注册身份竞态已修；两个 Git、独立 32 case、真实 CDC 工作字节整轮及最终包小型 ARM full→Diff→full | 所列范围通过；各记录保留实际版本 |
| 最后主区相关回归 | engine2b9、宿主 Git2.37；55 方法 /156.600s，0 FAIL/ERROR/skip，651 源码前后相同 | 已通过；不是 1646 全套重新通过 |
| 三个独立真实 STM32 工程 | F411、STM32CubeF4 CDC、F030 原生构建链接；V4 扫描67C：65 PARSED、2 PARTIAL、0 FAILED；430 对象244待办，均 INCOMPLETE | 所列真实工程路径已通过；不把部分覆盖写成全工程安全 |
| 实际人工流程 | 真 ECRA.cmd→筛选/搜索/长调用链/源码→签署/撤销→关闭 Chrome 重开→服务重启；三个实际事件保持，三项目无串用；真实导出包逐成员校验 | 所列操作通过；最终 V9 另复验共同确认入口 |
| 最终 V9 小窗口确认 | 实际解压包、Windows-only PATH、原持久 profile、viewport:null；内容1447×631/外窗1461×781。F411 与 NMI 切换后，项目/变量/定义位置/独立人工状态和四按钮同屏，原三事件不变 | Q405 正式成品原场景通过；两图已由检查者与协调者实际查看 |
| 最后GUI两渲染视口 | 同一最终包1366×768/1920×1080下，共同确认身份完整、四按钮同屏、document与身份容器无横溢；18实际命令exit0、三库SHA与人工事件相同 | 受影响画面通过；仅渲染视口，不冒称目标原生窗口/缩放 |
| 最终 V9 差异阅读 | 实际解压包读取先前 V8 同引擎原生扫描：3明确影响、2单列潜在影响，清除筛选后完整5对象；shared 两处 RMW、风险和当前对象身份可读；静态 SHA 与0人工事件保持 | 实际最终界面通过；不是 V9 重跑 full/Diff/full |
| 最终完整便携包 | 正式 WinPS5.1 OfflineCheck62.875s / build1055.765s；未压缩和 ZIP 中文空格解压各全文件 SHA、各27实际命令通过；154生产文件一致、59文档链接有效 | 正式构建和实际解压操作通过；OpenCode仍外部安装 |
| V8→V9 验证继承 | 127生产 Python、27772 tools、Python本体和libclang逐SHA相同；V9只有已说明 GUI 变化。V8实际包 Git18 与 ARM full/Diff/full 保留原版本标签 | 继承只针对相同组件，不称全部 runtime 字节相同 |
| 大型 INAV MATEKH743 | V4/core63a5，真实 Studio NEW，388/388 C提取、分类和发布前输入验证结束；16567变量/3541候选；单次发布仍运行，14:31 UTC pending约10.02GB | **尚未通过**最终数据库完整性、正式发布、终态与大型性能门禁 |
| 目标环境 | Windows10实际运行；物理64GiB主机/16GiB Job。真实联网OpenCode、物理32GB、干净离线物理机、OS DPI/页面原生缩放、目标原生1920/1366窗口及当前legacy file视觉 | 尚未验证或环境阻塞，不能用渲染视口/限额模拟替代 |

本轮 Q405 的独立使用检查发现：从长证据滚至确认按钮后，旧版对象标题已离开视窗，只剩“当前：待确认”。共同填写栏现保留项目、变量、定义位置和独立人工状态；没有改动静态分类、AI或人工存储。修复及源码预览、最终包两套独立收据见 [Q405](q405-v9.md)。此前 V8 的17张检查图与失败画面仍保留。

原整套1646方法在74c冻结版本实际运行20226.883秒、exit1，保留3个异步等待失败及各自清理错误、2个真实模型 opt-in 跳过；140组合保留两子例准备超时。修正测试阶段时钟后另有原断言成功证据，不倒改旧收据，也不以“测试很多”替代真实操作。详见[回归记录](continuation-regression.md)。

## 当前交付物与启动

正式本地候选：[ECRA-Portable.zip](H:/ECRA-quality-20261108-offline-build-v9/ECRA-Portable.zip)，785692863字节，SHA-256：

```text
7a0e45b0f3dda3ee47d7759f9784ab66ca9f8fa089543157f64c9f9be9a6c03d
```

已实际解压并使用的目录：[ECRA-Portable](<H:/ECRA-quality-20261108-offline-build-v9/解压 终验/ECRA-Portable>)。双击 `ECRA.cmd` 启动；源码安装 `requirements-studio.txt` 后运行 `py -3.10 run_ecra.py ui`。旧 `dist/` 和历史包均未覆盖。

工程配置→真实构建/预检查→扫描任务→项目概览、变量与风险。人工确认保存后，保持同一数据根，再次启动从“历史与对比”打开相应批次，或“继续人工确认”。默认 Windows 数据根为 `%LOCALAPPDATA%/ECRAStudio/data`；显式指定过数据根时继续使用原目录，升级前保留完整数据根及配置。测试用的隔离目录不是用户默认目录。

CLI 每条后续命令保留相同 `--config <文件>`。退出码2和 INCOMPLETE 表示风险待办/覆盖缺口仍存在，不能读成全工程安全。旧报告是历史归档；刷新不等于用新引擎重扫。已有人工结论按原关联保留，证据变化仍需复核。

## 证据与限制

- [完整功能矩阵](matrix.md)、[问题台账](issues.md)、[三真实工程](continuation-final-projects-v4.md)、[CDC 工作字节](continuation-diff-v6.md)、[实际包 ARM/Diff](continuation-diff-v8.md)。
- [V9 正式离线构建](continuation-offline-build-v9.md)、[最终 Q405](q405-v9.md)、[最终 native Diff 阅读](continuation-native-diff-ui-v9.md)、[关键最终截图及 SHA](evidence/final-v9-ui/index.md)。
- [独立工作区/正式构建身份后验](evidence/final-worktree-v9.md)保留唯一非运行时脚本偏差及正确builder绑定；当前入口文档本地链接已实际检查（计数及源码SHA见`current-docs-v9-links.json`），原文档与旧轮次补上历史范围说明。
- 原始机器收据：`output/quality-20261108/continuation/offline-build-v9/`、`q405-final-package-v9/`、`native-diff-ui-final-v9/`、`regression/main-v8-git-smoke/`；旧原始日志未改写。
- [14:44协调后验快照](evidence/final-v9-acceptance-144448.json)保留各原收据真实状态（含构建时尚待后续UAT的原文），汇总`release_accepted:false`与运行中大型门禁；不把早期pending收据改写成整体验收通过。当前Git diff --check为0、暂存区为空。
- 大型运行仍由原控制器负责，`new-upgrade-v4/receipt.json` 持续更新；不打开其 pending SQLite、不注入状态、不将旧扫描或缓存伪装为恢复成功。相关[有界发布观察](inav-publication-bounded-observation.md)只证明观察期间有实际工作，不能据此判性能或发布成功。
- [发布尾部静态成本审查](inav-publication-static-review.md)确认百万级记录会触发数千万次逐条SQL和两轮投影；尚未取得把当前耗时归因于某一异常的证据，没有以猜测替代修复或在原任务中途改变代码。

诊断限制 D001：大型运行 Job JSON 的 `write_bytes` 为0，而独立进程 I/O/文件增长证明有实际写出。界面未使用该字段；本轮不以它证明无工作/吞吐，使用独立观察，未凭推测修改资源API。内存与 Job 限额另有实际记录。

当前没有声称完整交付标准已全部达到。大型正式发布/性能及上述目标环境仍有明确缺口；真实结果中的 UNKNOWN、PARTIAL、SUSPECT 和人工待办没有被隐藏。
