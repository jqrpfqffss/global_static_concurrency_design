# 最终V8交付验收

当前仍在完成终验，不是全项目无缺陷声明。更新至2026-11-08 12:51 UTC。原始失败、旧冻结版本和过程证据继续保留；详细界面、三工程与回归说明见[前一阶段记录](continuation-final-v7.md)。

主区 `optimize_ccc` / `fe27afe73596d98e1a21e3f28a2125d38d7272d0`，最终静态引擎：`2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`。未提交、暂存、推送或发布。12:12 UTC在核对全部V7生产文件、其它源码和两文件preimage后，备份并合入Q207最终Git查询修复；154生产文件与冻结V8逐SHA相同。GUI DHpgztut及所有分析/提取/存储文件与前一冻结组合相同。

| 验收项 | 当前实际结果 | 状态/边界 |
|---|---|---|
| Git只读与真实内容差异 | 新查询用NUL numstat内容记录核对原名称，不按增删行数非零筛选；0/0、binary、rename、empty/mode保留，内容记录缺失明确失败。显式禁止textconv/external diff。宿主2.37回归25项23.420s、包Git2.56回归18项22.689s均通过；独立32实际case、原两失败×两Git、8实际invalid-ref拒绝，所有索引字节不变 | 修复已合入；主区复验中 |
| 主区有界相关回归 | 真主区engine2b9/宿主Git2.37，55方法156.600秒全部通过，0skip；651源码前后同，测试进程及后代已退出；原V6的65项FAIL1/ERROR1收据仍保留 | 所列主区相关回归已通过；不是1646全套重跑 |
| 三独立真实STM32工程 | F411/CDC/F030原生链接、V4真实全扫、67C/65PARSED/2PARTIAL，430对象244待办；全部INCOMPLETE。353非容器证据逐JSON不变、24nested容器正确归并 | 所列V4未变分析路径已通过；不改贴新引擎标签 |
| CDC固定提交full/Diff/cold/warm | V4两轮及独立full证据全同，warm39TU复用 | 所列版本范围已通过 |
| CDC真实工作字节整轮 | V6/core65 fresh clone、两次C+ASM真实构建/SDK封存、完整39TU与独立39TU full；2350.391秒/raw2，245对象，分类/语义mismatch0；头宏7u修改导致SAFE/EFFECTIVE→SUSPECT/UNRESOLVED。568源文件SHA/大小/mtime、目录namespace、HEAD、index及配置原件不变 | 实际整轮已通过；仍INCOMPLETE，仅按65版本记录 |
| 最终V8小型ARM端到端 | 真实最终解压包的Python/Git/CMake/Ninja/GCC，2C完整CDB/ARM ELF/MAP/objdump；base full39.890秒SAFE/EFFECTIVE→Diff90.937秒SUSPECT→current full33.563秒。5对象完整证据仅移除impact后逐项一致，产品独立full分类/语义0差异。三轮2PARSED/0PARTIAL/0FAILED，raw2/INCOMPLETE保留，源/库完整性与154生产SHA不变 | 实际最终包通过；不是新增真实工程数量 |
| 实际人工与故障恢复 | 真解压V4包启动，保存/撤销/关闭Chrome重开/服务重启三事件保留，跨项目不串；源码新GUI两视口、别名、容器、长链、错误/重试、取地址标签、标准包下载校验均实际操作。静态三库SHA未变 | 所列操作通过；最终包画面待验 |
| 最终完整离线包 | frozen builder V8 4370文件/302936047字节，快照SHA `969b1f85fb8593e6dd68a766ce628707fd5d189fea1b59922e76c6c601c285d2`；真实PS5.1 OfflineCheck59.687秒/build1190.063秒、双全SHA/双27命令通过；4370源码/27921缓存输入/3旧ZIP前后不变，缓存准备诊断元数据另列 | 正式构建通过；根实际再解压CRC/清单/154SHA/59链接亦通过 |
| 最终包Git回归 | 新包Python3.10.9+MinGit2.56，完整18方法99.104秒，0FAIL/ERROR/skip；准确argv/环境/二进制/模块/engine落盘，32692名字大小、154源及关键Python/Git/libclang SHA前后不变 | 实际最终包通过；不借宿主Python/Git，不把测试装进包 |
| 大型INAV MATEKH743 | V4/core63a5真实Studio NEW，388/388 C提取及风险分类完毕，16567盘点对象、3541候选，16GiB Job下实际提交峰值约10GB；当前单次存储发布，pending持续写入 | 运行中；正常full未经过后续Git/dirty改动，仍按原版本报告 |

V6主smoke发现的Git2.37 stat-only误选是Q207修复的相邻回归，先前包Git2.56下通过不足以放行。最终V8使用真实内容记录关闭该回归，不修改原预期、不让stable.c误入、不更新调用者index，也不通过缩小必要分析范围取得通过。最初新测试同时加入/删除相同空blob，被Git按`--find-renames`合法归并为R100；保留原失败，拆成独立空增/删输入并保留0/0重命名测试。生产没有按错误fixture反向修改。

终验证据在 `output/quality-20261108/continuation/`：`main-apply-v8-receipt.json`、`final-candidate-source-v8.json`、`builder-frozen-v8.json`、`regression/q207-v3-independent/review.json`、`regression/main-v8-git-smoke/`、`diff-final-v6/`、`offline-build-v8/`、`new-upgrade-v4/`。关键已查看截图另保存在仓库[证据目录](evidence/continuation-ui/README.md)，不是仅临时文件。

正式ZIP：`H:/ECRA-quality-20261108-offline-build-v8/ECRA-Portable.zip`，785692766字节，SHA-256 `b4590047afd32bfe3beb803b7a934ae52c893daf3d12a4fbe2c2ff456880ab1a`。root实际再次解压到同父`解压 终验/ECRA-Portable`，校验32691内容成员名字/大小/CRC和154生产SHA；正式脚本已在两份完整目录校验全工具链SHA，此后不重复第三遍全工具链。当前8份用户说明59处本地链接完整，正式PS源码保留UTF8 BOM、实际新包STUDIO-GUIDE中文正确。包无.git、Node/npm/Playwright/OpenCode可执行文件；OpenCode仍是可选外部安装。详见[完整封包](continuation-offline-build-v8.md)、[实际包ARM与Diff](continuation-diff-v8.md)。

原74c整套1646和V4状态组合140均完整结束但有测试等待失败，原log/退出码/前后SHA不改写；已确认的fixture时钟修正另有实际成功证据。不能把它们写成V8全套通过。真实联网OpenCode（用户禁用外部代理）、原生浏览器缩放/OS DPI、干净离线物理机、物理32GB机器及当前新版legacy file视觉仍未验证/环境受阻；没有绕过工具拒绝。静态UNKNOWN、部分覆盖和工程真实风险继续保留。

低影响诊断限制D001：大型运行的Job资源JSON `write_bytes`为0，独立进程I/O观察显示worker已有真实写出；任务界面未显示此字段。本轮不将该字段当作磁盘写出量或“任务没有工作”的证据，实际持续工作另由进程CPU/I/O和文件增长证明（`new-upgrade-v4/owned-publication-observation-120406.json`及原API记录）。未据此改写内存/Job限额统计，也未在本轮引入新的I/O展示功能；若后续消费这个诊断字段，需要单独修正统计来源与回归。

使用入口：便携包双击 `ECRA.cmd`；源码安装Studio依赖后 `py -3.10 run_ecra.py ui`。保持同一数据根，项目概览/变量与风险查看结果，历史与对比→相应批次→继续人工确认。CLI外置配置每条命令都保留相同`--config`；退出码2表示有待办/覆盖缺口，不代表全工程安全。最终ZIP路径和终态将在实际验收后填写。
