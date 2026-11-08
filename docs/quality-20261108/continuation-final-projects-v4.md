# v4组合引擎：三工程最终全量复验

三个工程的最终全量发布及相关审计已完成，所列输入和范围内通过；未将INCOMPLETE/PARTIAL隐藏为完整覆盖。最终冻结引擎为 `H:/ECRA-quality-20261108/continuation-final-engine-v4`，静态摘要 `63a5cff7e9babcf0a4982726f68ca8390ad5f840b92d31d41e511a859d857710`，已包含Q205物理上下文证据保护和Q206GNU函数别名恢复；来源收据 `output/quality-20261108/continuation/final-candidate-source-v4.json`。原v3及更早扫描保留，不改名或回填。

## 输入与方式

复用[真实完整链接构建产物](continuation-build.md)和原源码：F411原CDB46中仅24个真实链接C对象进入闭包；CDC39C+1ASM；F0304C。新配置仅修改输出根到 `H:/ECRA-quality-20261108/continuation-final-projects-v4`，有效分析配置与v3逐项相同，CDB/ELF/MAP启动前SHA均固定。系统头开启，两提取进程、6GiB Windows Job保护，明确原包native工具PATH和libclang；控制器为host CPython3.10.11，不冒充重新构建后的便携包。

以公开 `run_canonical` 的完整发布入口顺序执行F411→CDC→F030，每工程使用全新data/work根和TU缓存；不复用旧引擎TU、确认库或内部状态。命令、输入SHA、正式冷提取标记及资源证据在 `output/quality-20261108/continuation/final-projects/final-v4-{input-preparation,launch}.json` 和 `final-v4-*/{execution.json,console.log,resources.jsonl}`。

| 工程 | 入口/输入 | 当前结果 | 状态 |
|---|---|---|---|
| F411 | 真实link/AR/MAP闭包24C，原CDB46 | 全量发布和相邻命令/一致性审计通过；exit2/INCOMPLETE | 本配置验证通过，保留未知及待办 |
| CDC | 真实CMake CDB39C+1ASM | 39C全部PARSED；244盘点、205候选及待办；全量发布及相邻审计通过 | exit2/INCOMPLETE，ASM及70未知保留 |
| F030 | 真实逐对象构建并完整链接4C | 2PARSED/2PARTIAL/0FAILED；15盘点、1候选及待办；全量发布及相邻审计通过 | exit2/INCOMPLETE，真实部分解析诊断保留 |

## 复验合同

每工程完成后已实际执行 `status --json → report → status --json`，三项均0/2/0，不把INCOMPLETE或PARTIAL计成完整覆盖。SQLite/外键、静态库刷新前后字节、源码及CDB/ELF/MAP不变均通过；静态分类分母、容器独立列出、当前人工待办与候选一致、新facts容器明确CONTAINER且derived=0均通过。

与v3比较每个非容器对象完整的有序JSON，包含访问、上下文、调用、冲突、保护和分类。未预设修复后必须与旧版相同，也未自动把变化当成修复成功；实际353个对象均严格相同、无缺项。`audit_project_v4.py`区分结构/持久化检查与语义差异，原始逐项结果及变化对象文件保留 `final-v4-*-audit.json`、`final-v4-*-semantic-objects.json`。F411全局别名/上下文盘点的真实变化单独验证如下。

这些输入的DMA/动态调用/ASM及原F030部分Clang诊断仍按实际范围记录；不新增硬件、完整RTOS或DMA支持，不以微型样例替代这三项工程。耗时与峰值仅为本轮环境实测，不作为性能优化前后对照，也不声称物理32GiB环境、HIL或全部交付门禁通过。

## F411已完成证据

真实公开全量发布319.484秒，24TU全部PARSED，退出2/INCOMPLETE；171盘点=123独立分类（84SAFE、1SHARED、34SUSPECT、4UNKNOWN）+41CONTAINER+7NON_STORAGE，待办与候选38一致。Job峰值提交185,405,440字节、峰值工作集214,667,264字节，未触发停止。status/report/status返回0/2/0，SQLite及外键完整，源码、CDB、ELF、MAP及报告刷新前后scan.db字节全部不变。4个嵌套容器按真实成员关联验证通过，全部新facts明确CONTAINER、derived=0。

130个非容器对象的完整有序JSON逐个与v3相同，包含访问、调用、上下文、冲突、保护和分类；不是仅比较最终数字。全局函数盘点2525→2563，新增38条有来源的GNU alias边，执行上下文29→66。38个别名均解析到Default_Handler；实际最终ELF的nm地址及readelf符号表证明所选实现同址，目标函数没有全局/static访问，所以不会改变上述共享状态对象证据。实际工程使用LTO，最终符号LOCAL/type t；初始辅助检查误要求W，原脚本、真实readelf证据及纠正依据保留 `final-v4-f411-alias-controller-correction.json`，未放宽地址/目标证明或修改产品。完整收据 `final-v4-f411-audit.json`、`final-v4-f411-alias-evidence.json`、`final-v4-f411-actual-alias-link-check.json`。

该工程自定义 `.isr_vector_tbl` 不在当前向量节恢复集合，普通约定名称的handler由现有命名合同恢复。DebugMon_Handler不属于该命名集合；这里其真实默认体没有共享访问，不声称已支持自定义节布局或DebugMon的任意自定义实现。

通过正式Studio API导出标准完整归档，再用正式下载接口取得 `H:/ECRA-quality-20261108/continuation-final-v4-export-copy/final-v4-f411.ecra-report`，27,392,726字节，SHA `ab61cc79e4f4af871254695d3a23f11078843c49f04f0d716a5c3f39e1a0e391`。导出在完整数据根副本执行，原发布目录全部文件SHA不变，包内facts/report摘要与原清单一致。此新包供根验收者通过真实文件选择器导入，不能仅由本API导出测试宣称浏览器已通过。收据 `final-v4-f411-public-export.json`。

## CDC与F030最终证据

CDC真实全量发布1441.281秒，Job峰值提交569,696,256字节、工作集577,671,168字节。39个C TU全部PARSED，另1ASM明确记录；244盘点=210独立分类（5SAFE、135SUSPECT、70UNKNOWN）+34CONTAINER，205候选/人工待办一致。20个嵌套容器真实成员ID与根/字段关系吻合，新facts均明确CONTAINER、derived=0；210个非容器对象全部证据与v3逐个严格相同。报告刷新、SQLite/外键、源码和构建产物不变均通过。证据 `final-v4-cdc-audit.json`。

F030真实全量发布107.265秒，Job峰值提交147,664,896字节、工作集183,091,200字节。4TU仍为2PARSED/2PARTIAL/0FAILED，原GNU naked函数等Clang能力诊断未屏蔽；15盘点=8分类（7SAFE、1SUSPECT）+2CONTAINER+5NON_STORAGE，待办1，与实际systicks共享竞争风险一致。13个非容器对象全部证据与v3严格相同；源码、CDB、ELF/MAP、静态库及相邻命令全部通过。证据 `final-v4-f030-audit.json`。

三项合计67C（65PARSED、2PARTIAL、0FAILED）及另1ASM，430盘点、24个嵌套容器验证、353个非容器对象全部证据一致，96SAFE/1SHARED/170SUSPECT/74UNKNOWN、77容器、12非存储、人工待办244。正式TU缓存命中均0，重新提取24/39/4，未复用旧引擎结果；主扫描与审计控制器均已正常结束，无资源停止。

最终总收据 `output/quality-20261108/continuation/final-projects/final-v4-three-projects-summary.json`，并保存[可携带小收据](evidence/final-v4-three-projects-summary.json)，SHA `46df6113884f10d34b887726cda40d2fe0be2abc1d9d2040393ba975f4bbc23e`。`passed_scoped:true`与`release_ready:false`分别表示本轮三份确切输入已验收，以及大型INAV/离线重建包等整体验收由独立根记录推进，不能从这里推断为已通过。
