# v3组合引擎：三工程实际全量复验

协调者将已通过针对回归的Q109容器修复、构建别名及工具链输入修复组合冻结于 `H:/ECRA-quality-20261108/continuation-final-engine-v3`，静态摘要 `6cede8359026fd75dd801f6d45ac34ba422a18eee77888078babb8cd862d54f7`。此项使用当时已冻结版本重新提取全部TU，不沿用旧引擎缓存，不将[839轮完整构建与扫描](continuation-final-projects.md)当作修复后的通过。

**后续新发现：** 本轮运行期间，独立分析检查以真实向量表、GCC及objdump证据确认严重Q205：自定义context ID与自动vector槽身份碰撞可覆盖物理异常属性，造成错误保护结论。协调者已要求最小修复；本v3输入继续完成并保留，不再自行重复新扫描。下列结果仅证明确切6cede版本及三份已列配置，不代表Q205已修复或完整交付门禁通过。后续组合引擎另记，不能把本v3收据改名冒充新版本验收。

## 输入与执行

真实构建的CDB、ELF、MAP及源码副本保持不变，F411仍依据真实link/AR/MAP闭包选择24C，原CDB46不修改。配置仅将输出根改到新的 `H:/ECRA-quality-20261108/continuation-final-projects-v3`，保持两个提取进程、系统头开启、明确包内libclang、包内原工具PATH和6GiB Windows Job安全限制。逐项运行公开 `run_canonical` 的全量发布入口，顺序F411→CDC→F030。

运行记录位于 `output/quality-20261108/continuation/final-projects/`：`final-v3-configs.json` 保存原/新配置SHA及仅输出位置变化的收据；`final-v3-launch.json` 保存确切命令、引擎、环境与顺序；每工程 `final-v3-*/execution.json`、console.log、resources.jsonl 保存实际发布与资源证据。

| 工程 | 预期输入 | 实际状态 | 修复后的检查 |
|---|---|---|---|
| F411 | 真实完整链接24C、原CDB46选中24 | 全量发布、status/report及证据对照全部通过；退出2/INCOMPLETE | 24PARSED；171盘点=123分类+41容器+7非存储；4个新nested明确CONTAINER，派生标志0；84安全/1共享筛除/34疑似/4未知，待办与候选38一致 |
| CDC | 真实CMake数据库39C+1ASM | 全量发布、status/report及证据对照全部通过；退出2/INCOMPLETE | 39PARSED，244盘点=210独立分类+34明确容器；5安全/135疑似/70未知、205候选与待办一致；20nested成员与叶证据通过，derived0 |
| F030 | 真实逐对象编译后完整链接4C | 全量发布、status/report及证据对照全部通过；退出2/INCOMPLETE | 4TU：2PARSED/2PARTIAL/0FAILED；15盘点=7安全/1疑似/5非存储/2容器，待办1；原部分解析诊断保留 |

三项均已逐项实际执行 `status --json → report → status --json`，返回0/2/0，原输入不变、SQLite/外键完整、静态字节不被报告刷新改写；检查了新容器的真实root/字段关系和成员列表，并对独立对象的完整访问、上下文、调用、冲突、保护和分类作严格有序JSON对照。该复验不包含新联网AI、HIL或干净离线物理机验收，也不意味着尚未修复的Q205已通过。

F411实际全量及公开发布耗时226.781秒，Job峰值提交187,846,656字节、峰值工作集215,490,560字节；正式TU缓存0命中/24重新提取。130个非容器对象（123分类存储+7非存储）的完整有序JSON与839原输入逐个严格一致，包括所有访问、调用、上下文、冲突、保护及分类；无差异、无漏项。四个嵌套容器的root/字段子关系与成员ID列表均吻合。status/report/status为0/2/0，源码/CDB/ELF/MAP和报告刷新前后的静态scan.db全不变，SQLite/外键完整。证据 `final-v3-f411-audit.json`。

这些耗时不是Q109性能优化对照：没有重启或清除操作系统文件缓存，任务并发负载也可能不同。仅正式TU缓存保证冷提取，不将OS缓存变化归因代码修复。

CDC公开发布耗时1251.875秒，Job峰值提交579,420,160字节、工作集587,685,888字节；F030公开发布55.812秒，Job峰值提交147,456,000字节、工作集182,013,952字节。两者都没有触发资源停止，正式TU缓存均0命中；其后相邻命令和完整证据对照也已通过，记录 `final-v3-cdc-audit.json` 与 `final-v3-f030-audit.json`。

本轮合计67个C TU（65PARSED、2PARTIAL、0FAILED），另1ASM明确记录能力边界；完整盘点430行。与839原相同输入比较，353个非容器对象的完整有序JSON全部严格相同；24个原缺标签嵌套容器新增明确CONTAINER及真实成员汇总。原96安全、1共享筛除、170疑似、74未知保持，当前待人工244，未以丢弃未知或候选降低数字。三项静态库、源码、CDB、ELF、MAP及6cede引擎前后均不变，所有进程正常结束。

总收据为 `output/quality-20261108/continuation/final-projects/final-v3-three-projects-summary.json`，并保存了[可随文档携带的小收据](evidence/final-v3-three-projects-summary.json)。`passed_scoped:true`与`release_ready:false`同时明确：此确切配置复验完成，严重Q205仍需最终组合后的验证。没有自行重复warm扫描或把旧结果改名成Q205后证据。
