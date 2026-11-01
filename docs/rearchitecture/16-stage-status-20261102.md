# 2026-11-02 阶段实现与验收

这是已执行工作的验收入口，完整重构仍未完成。当前分支为optimize_ccc；没有重置工作区、推送、覆盖用户config/semantics.yaml修改或未跟踪的任务文档。

## 可以实际启动的阶段包

`H:/ECRAStudio-build-20261102-studio-v15/ECRA-Portable/ECRA.cmd`

完整ZIP：`H:/ECRAStudio-build-20261102-studio-v15/ECRA-Portable.zip`，545,003,832B；SHA-256 `d0a0e3bfe7ab5462da013acbf8e69f38b49d172b70750e1790973a783f77aaf7`。

运行时代码b50103f，893文件实际工作快照，manifest SHA-256 `b3146bfb0aa8de31fab52d7ee19213dbfe91d2c03b6145ec0da6e6d643afa282`。120个实际分发的Python/Web/许可/示例/启动器/校验器/需求文件与冻结来源逐字节相同。生成的依赖lock由构建完整文件清单验证。离线用户指南和两个校验过的教学资产实际入包；无需系统Node或源码即可查看真实教学归档。

此包的原目录与长中文路径ZIP解压各27条真实命令PASS（各21条退出0，6条按原语义INCOMPLETE退出2）。包内Python3.10.9的真实Chrome分别通过：示例10、主流程16、配置往返7、上下文8、目录选择7、Git选择6、20007行容量/排序9；这些是独立专项，不相加成全套回归。已人工查看1366教学工作台、任务页截图；搜索、对象、详情标签、依据框和主要确认动作可见。其余布局由相应脚本断言，不冒充Windows系统DPI或工程师盲测。

v15整套1264项冻结回归仍在运行；当前仅将CLI/浏览器/资产一致性子范围标PASS，见[阶段包收据](evidence/portable-studio-v15-runtime-ui.json)、[源码一致性](evidence/portable-source-match-v15.json)及[实际截图](ui/screenshots/portable-v15)。未以旧包或较早全套结果代替当前v15完整验收。

v14因解压启动器的程序路径Junction被示例读取拒绝而实际失败，无已发布ZIP；[失败收据](evidence/portable-studio-v14-failed.json)保留。修复只读程序资产的位置解析后重建v15，数据写入路径的链接拒绝仍受真实Windows测试保护。

## 本轮逐项交付

| 阶段/场景 | 实际改动与文件 | 实际验收 | 状态及证据 |
|---|---|---|---|
| Phase2/H1，祖先工作集 | evidence.py完整多起点反向闭包；可重算祖先缓存按成员数有界；ADR013 | 独立e69完整切片/随机图/循环/重复边/坏身份/驱逐23项PASS；完整函数/调用边/未知入口保留；F030完整facts及规范report零差异 | 子范围PASS；[分配收据](evidence/evidence-ancestors-v1.json) |
| Phase2，完整回归 | 890文件冻结含ADR013；不含后续程序别名修复 | 1263项，1261PASS/2联网OpenCode opt-in SKIP，1880.423s，代码及测试副本890文件SHA不变 | PASS；[收据](evidence/full-regression-ancestor-v1.json) |
| Phase6，较早完整回归 | 886文件b5c299e快照 | 1259项，1257PASS/2联网SKIP，1880.152s，SHA不变；其v14 Portable仍失败 | 回归子范围PASS；[收据](evidence/full-regression-studio-v14.json) |
| Phase0/1，严格比较基准 | 原版独立冷扫描JSON流式转完整图并逐节点/关系/投影深校验 | 原JSON SHA保持；14251.031s，Job103,161,856B；比较DB17,831,825,408B | 比较基准PASS；[收据](evidence/inav-original-graph-v3-complete.json)；不是新扫描或标准归档 |
| Phase0/H1，直接完整JSON摘要 | hash_native_json.py；ADR014；仅开发验收工具，不改正式编码 | 13项专项PASS；全部作用域与独立GraphWriter/NormalizedGraph相同；真实F030原版JSON完整有序facts/规范report摘要相同，原字节/mtime不变 | 小范围PASS；[收据](evidence/native-json-hashes-v1.json)；大型运行中 |
| Phase1/U03，只读输入 | validate_readonly_native.py，在新建副本施加Windows ACL，实际子进程写入拒绝 | 42原文件及副本不变；原版13.703s、新版24.062s均analysis_valid=true/INCOMPLETE；完整facts/规范report零差异，ACL恢复 | 适用DB扫描PASS；[收据](evidence/readonly-native-f030-v2.json)；非物理只读卷/生产恶意进程隔离 |
| Phase4/6，真实上位机 | 普通上下文表单、受限目录浏览、真实示例、首屏工作台、Portable资产及别名修复 | 包内七组真实Chrome和27+27命令通过；无模拟数据/API；真实停止/恢复/重扫/故障恢复/人工事件转移 | 已覆盖路径PASS；U01–U24整体仍PARTIAL |

容量夹具的局部分配：2000函数、1999调用边，完整输出SHA相同，Python临时分配峰值135,262,473→1,343,104B。它不是进程树RSS、INAV或G3收益；不拿它替代大型扫描。

只读首轮夹具实际失败并保留[原收据及恢复审计](evidence/readonly-native-f030-v1-failed.json)：编译数据库放在数据根祖先，被正式边界正确拒绝；Windows设置ACL还规范化了AUTO_INHERITED标记。旧副本访问权限已恢复，原固件ACL始终未改。第二轮将输入合同独立放置，并在冻结新副本ACL基线前完成Windows规范化，之后精确恢复通过。失败轮不改成PASS。

## 大型数据与资源门禁

| 项目 | 原版真实值 | 候选真实值 | 判定 |
|---|---|---|---|
| INAV388TU冷扫描 | 12542.188s，Job29,805,875,200B，analysis_valid=true/INCOMPLETE；独立完整备份57,773文件/46,427,649,982B逐文件SHA通过 | v7：4427.547s，退出3/analysis_valid=false，Job17,180,798,976B；16GiB受控上限，分类祖先集合处MemoryError | G3 FAIL；失败输出不算最终收益 |
| ADR013新候选 | 同一冻结源码/配置/DB/工具链闭包 | v8已完成4123输入/890代码文件启动前核验，完整1263回归通过后才启动冷提取 | RUNNING，尚无完整结果，不标G1/G3 PASS |
| 最终磁盘与完整标准归档 | 原版原始目录/备份完整保留 | 新版大型有效结果和完整标准归档未完成；17.83GB是原版比较图，545MB是程序ZIP | G4 NOT_VERIFIED；没有≥70%收益结论 |
| 用时比较 | 原版与候选不是独占同一磁盘负载 | H/I是同一物理HDD；v7与原版转图并行，v8与只读比较工具等并行 | 不将耗时或全卷空间变化归因于某项优化 |
| 机器 | 主机实际64GiB，显式Windows Job限制已记录 | 物理32GB机器未测 | NOT_VERIFIED |

v7失败见[完整收据](evidence/inav-instances-native-v7-failed.json)；v8启动前记录见[preflight](evidence/inav-ancestors-native-v8-preflight.json)。2GiB Job下的原JSON直接摘要与独立全图核对也在运行，未以未结束进程宣称比较通过。

## 仍需完成的门禁与代码

| 门禁/硬约束 | 当前剩余项 |
|---|---|
| H1/G1 | 当前大型全量逐字段比较；大型Diff直接base→current、影响闭包/verify_against_full及严格同输入完整对照 |
| H2/U03 | 生产子进程写保护、dirty字节正式隔离、完整外置构建模式与物理只读挂载；本轮ACL小工程不替代这些 |
| H3/Phase2 | 全局merge/求解仍依赖大内存对象；保存后部分消费者仍恢复完整facts/report，双全量Diff工作集仍需重构 |
| H4/U18 | 可证明相同证据的精确跨版本继承与完整兼容合同；当前不确定时保守RECHECK，历史不覆盖 |
| H5/G7 | 完整环境/执行计划、数据根图形选择、剩余普通复核配置、全部极端页面状态/长名/DPI/盲测；完整U01–U24仍PARTIAL |
| H6/G5/G6 | 完整故障注入矩阵、大型标准包导入/事件往返/损坏恢复、缺证据旧格式降级与完整双物理机协作验证 |
| G2 | 继续已批准的INAV/F030；其余H747/独立DMA/回调/RTOS真实工程遵用户决定NOT_VERIFIED_USER_DEFERRED，不重复索要路径 |
| G3/G4 | 新候选大型完整运行、物理32GB、完整归档及实盘峰值/缓存/build/worktree总量；局部Python分配不替代 |
| G8 | 当前实际包/中文解压/包内浏览器已验；干净离线物理Windows、原生系统DPI、第二台电脑、5–8工程师盲测仍NOT_VERIFIED |

本阶段不宣称H1–H6、G1–G8或Phase0–6整体完成。原始备份、失败轮、冻结代码与人工历史全部保留。

补充已验：当前包覆盖诊断8、真实两服务人工增量/冲突协作7、完整旧迁移6、实际ECRA.cmd启动4均通过。入口测试PATH仅有Windows目录，实际子进程为包内Python，在私有LOCALAPPDATA默认根落数据，全部被检程序字节/mtime不变；--no-browser仅抑制桌面浏览器弹窗，随后由真实Chrome进入同一服务，不冒充物理干净机双击。逐项状态见[U01–U24](ui/17-user-scenario-status.md)，当前7PASS/3FAIL/14NOT_VERIFIED，完整G7继续未通过。legacy首轮夹具把已改变分类的HCLK留在UNKNOWN筛选，launcher首轮提前匹配空态说明；修正控制器后重验，未改产品结果或校验。
