# 最终组合 v4 与收敛进度

此为V4阶段记录；当前主区、Git2.37新失败及最终GUI状态见[当前V7记录](continuation-final-v7.md)，可恢复步骤见[当前执行点](continuation-checkpoint-final.md)。下列运行中状态保留当时版本，不是最新终态。

本页建立于2026-11-08 09:21 UTC，随实际终态收据更新，运行中不计通过。主仓仍为首轮74c0引擎以保留原完整回归；没有切分支或覆盖用户历史数据。

冻结候选：`H:/ECRA-quality-20261108/continuation-final-engine-v4`；核心摘要 `63a5cff7e9babcf0a4982726f68ca8390ad5f840b92d31d41e511a859d857710`。逐文件来源与SHA见 `output/quality-20261108/continuation/final-candidate-source-v4.json`。当前网页为 `index-DtVJ1HEe.js`，包含旧容器派生汇总的来源说明。不能将原74完整回归记成v4全套通过。

| 工作 | 当前证据与结果 | 状态 |
|---|---|---|
| Q205自动物理证据与配置冲突 | 真实向量slot2/3、GCC/objdump证明原错误SAFE；修复保留真实来源/根入口，矛盾配置明确拒绝；含FAULTMASK合法HardFault正例。13定向、88邻接及独立13通过 | 候选局部已通过 |
| Q206 GNU函数别名 | 真实GCC/nm同址、宏展开、头/后定义、强覆盖与双输入顺序；支持可证明的同TU强no-arg void ABI，不能支持的明确失败且保留已提取事实。13定向、80邻接通过 | 候选局部已通过 |
| 两安全修复组合 | 同63a5核心26项通过，10个真实向量/手工配置/alias组合无误安全；实际CLI正确SUSPECT已发布，Studio三接口200，status/report/status=0/2/0；不支持alias退出3且不发布假结果 | 已通过（所列场景） |
| 共享结果清单合同 | LOCAL/REPORT/LEGACY_IMPORT、4MiB边界、身份、历史/摘要/目录同合同；原坏项隔离且有效邻居可用。最终r2 19项1142.022秒通过 | 候选局部已通过 |
| 原全套与异步测试 | 原1646方法仍跑；三方法10/40秒等待失败各跟一次清理ERROR，不算六个独立业务缺陷；9项修后实际终态/清理426.709秒通过，业务断言未删改 | 原套已失败（局部），余项运行 |
| 最终组合关键回归 | `regression/final-v4-critical/`，22模块195方法，194通过/1中文物理GCC正例因未指定路径跳过，1120.880秒；前后源0变化、核心63a5不变。随后在同冻结源显式指定实际中文物理编译器，原跳过正例1通过/0跳过，含系统头与stdint真实解析；`regression/final-v4-physical-chinese-gcc/` | 所列关键回归已通过；未代替实包验收 |
| 三真实工程 | 新数据根`continuation-final-projects-v4`，F411/CDC/F030全部run及0/2/0相邻链通过，耗时319.484/1441.281/107.265秒；67C新提取65PARSED/2PARTIAL/0FAILED，1ASM另属实际构建闭包，全部INCOMPLETE。430盘点中353非容器有序JSON与v3全同、24nested汇总正确、derived0，待办244。原源码/CDB/ELF/MAP/静态DB/核心均不变；见[三工程记录](continuation-final-projects-v4.md) | 所列实际工程范围已通过；不含硬件或大型整轮 |
| 最终CDC full/Diff/cold/warm/dirty | 新根`continuation-diff-v4`，真实固定提交与工作字节、独立full、输入不变性与完整证据比较 | 运行中 |
| 大型INAV正式升级NEW任务 | 原自有数据根与配置，真实Studio API新任务，16GiB Windows Job/8workers；旧记录与64对缓存不改，不注入内部状态。`new-upgrade-v4/` | 运行中，不是完成或同引擎恢复通过 |
| 真离线完整打包 | 冻结builder 4368源文件，`builder-frozen-v4.json`；包内Python/CMake/GCC/Ninja/MinGW及可选MinGit，OpenCode仍外置。WinPS5.1正式OfflineCheck及未压缩27条真实工具/构建/CLI链PASS、静态库不变、程序目录无运行数据；当前8份用户说明59处本地链接0缺失。正在生成ZIP及原脚本解压验收 | 未压缩范围通过；ZIP/实际成品UI仍运行中 |

Q307：正式打包脚本只复制`docs/rearchitecture`，其中当前用户入口引用的根级教程在新构建中缺失；CLI短说明还残留默认HTML输出承诺。独立builder已补根级Markdown及文档assets（不带QA工作数据/开发依赖），当前CLI说明改为Studio/独立数据根与显式legacy边界，等待成品链接和操作验证。修复需随主源码最终合入，旧包不改。

实际Windows PowerShell 5.1离线检查的前几次外层控制器失败记录均保留：首轮从Python继承了PowerShell Core的PSMODULEPATH导致找不到系统模块；一次控制器自身NameError未启动产品；随后大小写敏感dict删除变量不生效。最后按Windows环境名不区分大小写移除该继承变量，让5.1初始化普通系统模块；未修改产品脚本来吞错误，也不将这些失败计成产品通过。见`offline-build-v4*/`各原始收据和日志。

仍未验证：真实联网OpenCode（用户禁止调用外部代理）、原生浏览器缩放/系统DPI、干净离线物理机与32GB物理机。兼容HTML实际生成已完成，但本轮file协议视觉操作被工具拒绝，未通过其它入口绕过。已支持的合成传输、视口和本机Windows验证不能替代上述条件。
