# 当前交付收敛记录（V7）

本阶段记录已由[最终V8验收](continuation-final-v8.md)更新：Git2.37相邻回归已修复、独立复验并于12:12合入；下列“当前阻断”保留11:55的真实状态，不是最新结论。

本页是续轮的当前状态入口；旧轮次记录保留原版本、失败与收据，不能合并称为一次最终版本全套通过。更新至2026-11-08 11:55 UTC，尚未完成的任务保持运行中。

**当前阻断**：主区V6的65方法回归完整结束，63个方法成功，1个FAIL及1个ERROR均为Git stat-only场景；没有跳过。相同fixture/字节在宿主Git2.37.2与包内Git2.56.0.3交叉复现，旧Git的`--exit-code --name-status`仍误报不变文件，新Git正确；隔离全局配置后不改变结论，16行对照中索引字节均不变。独立候选先前通过的范围不能推翻主区新失败。Q207共同查询修复正在进行；后续最终封包已暂停。原65项失败和651前后不变证据保留。

主区仍为 `optimize_ccc` / `fe27afe73596d98e1a21e3f28a2125d38d7272d0`，未切分支、提交、推送或暂存修改。11:37 UTC已在逐文件前置校验与完整备份后合入45项操作，静态引擎为 `65c0fb3dbc29bda7ad74aeeadeb4666c6b1eeda545bc9521c3961f476eca7682`。65方法回归EOF/651前后hash一致后，11:50又备份并合入4项GUI操作，主区vue-tsc/Vite成功且154生产文件重现V7逐SHA相同产物。Q404“取地址”标签已在真实1366×768源码入口查看；静态引擎与V6完全相同，Git失败仍未解除。

## 修复与复验范围

| 工作 | 实际证据 | 当前状态 |
|---|---|---|
| NMI/HF物理证据、GNU函数别名漏入口 | Q205/Q206真实ARM向量重定位、GCC/nm、强覆盖、合法HardFault正例及不支持ABI明确失败；26项联合、10个独立语义例、实际CLI发布SUSPECT与Studio查询通过 | 已合入；主区相关复验中 |
| 损坏归档、导入和历史一致性 | 共用4MiB清单/身份/状态合同，合法legacy独立保留；最终r2真实19项通过。实际坏清单界面给出文件、影响、重试/历史入口 | 已合入；真实故障与恢复已操作 |
| SQLite停止、任务与人工持久化 | 实际12.6GB只读库停止响应约0.312秒；原库不变、完整性与发布检查未删除。实际人工保存→撤销→关闭Chrome→重开继续→重新签署→Ctrl+C重启后仍保留 | 已合入；所列范围通过 |
| 工作字节监控与只读Git | Q207只在命令级关闭Git索引auto refresh，并使用真实内容差异契约；Q208先准入、完整原mask监控、再严格准入；Q209父到子锁定目录身份后注册通知，拒绝替换及真实ABA | 已合入；71项候选与19项独立复验通过；真实CDC整轮运行中 |
| 中文路径与C+ASM构建、重复配置 | 官方ASM只读查询精确允许、中文GCC无损解码、稳定物理路径别名、同toolchain保留实际Cache契约 | 已合入；小例、三真实工程和固定提交cold/warm通过 |
| 界面与结果来源 | 笔记本确认按钮、坏结果就绪门禁、旧nested容器只读派生、函数别名/普通调用标签、已知覆盖状态、ADDRESS_TAKEN“取地址” | 前几项已合入；最后标签GUI-only V7已构建冻结，待主区delta及最终包画面 |
| 文档/便携边界 | 真实PS5.1离线构建，根级用户教程/assets完整进入包；OpenCode仍为外部安装项，未将QA/Node/Playwright带入runtime | Q307已合入；V4完整包通过，V6运行、最终V7排队 |

## 真实工程与版本适用范围

三个独立真实STM32工程F411、STM32CubeF4 CDC、F030均已在V4完整执行 `run → status → report → status`；退出码依次2/0/2/0。67个C单元中65 PARSED、2 PARTIAL、0 FAILED，另有1个真实ASM构建单元；430个盘点对象、244个待办，全部保留INCOMPLETE。353个非容器对象与前一组合有序JSON完全一致，24个nested容器得到正确汇总，未将父项排除解释为叶风险消失。原源码、CDB、ELF/MAP与静态库不变，详见[三工程记录](continuation-final-projects-v4.md)。

V4 CDC固定提交cold/warm与独立full均完成：cold 2077.891秒、warm 1185.188秒；warm命中同一完整基准且39/39 TU缓存复用。完整事实、对象、finding、影响范围及风险摘要对照一致。工作字节最后一轮曾真实失败，保留该失败；修复Q207–209后的V6从全新真实克隆重新执行，尚未计通过。

大型INAV MATEKH743任务固定在V4/core63a5，16GiB Windows Job、8workers，当前388/388 C单元提取完毕，正在风险分类。V6四个后续Python修改仅影响工作字节准入/监控和Git差异入口；INAV本轮正常full、include_uncommitted:false路径未经过这些修改，提取/分析/存储生产文件逐字节相同。因此让该任务完成并仅按其真实版本报告，不改旧checkpoint标签，不宣称它是65c引擎整轮通过。大型Diff/恢复完整矩阵仍独立列为缺口。

## 自动回归如何解释

原始主区74c完整套件已于11:32:40 UTC完整结束：`Ran 1646 tests in 20226.883s`，退出1，`failures=3, errors=3, skipped=2`。这是3个方法的等待时限失败及其各自的活动fixture清理ERROR，另有2个真实OpenCode opt-in跳过；不是6个独立业务失败，也不能从失败/错误事件数反算精确成功方法数。479文件前后完全相同、引擎前后74c相同。原始失败、警告和退出码保留。异步等待修正后的9项真实终态/清理已另外通过。

V4状态组合140项也完整结束，唯一两个ERROR来自同一SQLite方法的12秒全流程准备时限。阶段实测旧库准备已需14秒，尚未进入被测SQL；修复仅分离准备时限与真实stop响应时钟，必须确实进入SQL/写stop，原响应<5秒及旧库/无半发布断言保留。修正后3方法/2子例与8项恢复邻居均通过，不倒改原140项结果。主区V6正在运行8模块65方法，另存原log/退出码/前后源码。

## 实际界面操作

通过真实 `ECRA.cmd`、初始仅Windows系统PATH，从中文空格路径、无.git的V4解压目录启动；使用持久Chrome profile，没有注入人工状态。空首页打开内置真实教学归档，再用系统文件选择器导入NMI已知答案归档和真实F411旧归档。随后源码预览仅用于检查新GUI，明确不代替最终包画面。

- NMI `shared` 实际签署风险→撤销→关闭浏览器→同profile重开继续→重新签署→正常Ctrl+C服务退出及重启，风险1/待办0仍存在。静态DB SHA始终 `c80fe1ec…`，教学项目待办6、人工0不变。
- F411搜索 `g_cli.command_list` 得5项，父容器无需确认、叶项疑似风险仍需确认；旧库SHA始终 `b770def0…`。展开16处访问、42组潜在关系、`cli_process_char → on_char_received → uart_irq_handler_common → USART1_IRQHandler` 上游链，1366×768窗口中项目/对象和确认入口保持可见。
- 仅在这份隔离导入副本把manifest故意改为数组，页面明确指出失败阶段/路径、保留数据和恢复下一步。只恢复该故障清单的原始字节后实际点击“重试读取”，搜索5项恢复，三个项目的静态SHA和人工计数均不变。这是人工修复故障文件后的重试，**不是自动修复损坏文件，也没有恢复/注入确认、AI或任务状态**。

实际通过“历史→详情与操作→导出标准完整包”下载94838字节NMI包，SHA `523e607dd7d57549d91b7df9d8544c8546af49f3f69b0fc8d1a9ff9743d0a688`。26成员CRC/清单SHA全过，静态DB与当前副本相同，三条人工事件/全部字段/父子关系与真实UI操作后的API记录完全一致。只读核对，不注入状态。证据`package-ui-v4/browser-export/receipt.json`。源码V7预览正常Ctrl+C退出0.875秒，自行清会话；界面结束后三项目计数和静态SHA均不变。

关键视口截图均已实际查看：`output/playwright/quality-20261108/continuation/` 中 `ui-r2-f411-long-chain-1366.png`、`ui-r2-corrupt-manifest-explained-1366.png`、`ui-r2-manifest-retry-restored-1366.png`、`v5-source-alias-corrected-1920.png`、`v5-source-alias-scrolled-1366.png`、`ui-r2-identity-scope-scrolled-1366.png`、`ui-r2-address-kind-before-1366.png`、`ui-v7-address-kind-corrected-1366.png`、`ui-v7-standard-export-succeeded-1366.png`。最终成品画面待补。

## 当前交付物、证据与限制

冻结引擎源码：`H:/ECRA-quality-20261108/continuation-final-engine-v7`；完整builder：同父 `continuation-builder-source-v7`，4370文件，快照SHA `c212e5f7db2d48cab3dcff70d82a8be1d3aba3f1869dd1871dd9906d5d495598`。最终GUI为 `index-DHpgztut.js`，Python与V6完全同。原V4、V6、旧ZIP均保留各自版本记录，最终包尚未完成时不推荐用户把旧包当本次最终产物。

原始证据入口：`output/quality-20261108/continuation/` 下 `main-apply-v6-receipt.json`、`final-candidate-source-v7.json`、`builder-frozen-v7.json`、`regression/full-suite-01/assessment.json`、`regression/main-v6-smoke/`、`diff-final-v6/`、`new-upgrade-v4/`、`offline-build-v6/`、`offline-build-v7/`、`package-ui-v4/`。

仍未验证：本轮真实联网OpenCode（用户明确禁用外部代理）、原生浏览器缩放和操作系统DPI、干净离线物理电脑、物理32GB机器。64GB本机上的16GiB Job不能冒充32GB机器。新版兼容HTML已真实生成，但本轮file协议视觉操作被工具阻止，未通过HTTP或原生窗口绕过；首轮file检查只属于首轮字节。未知、DMA/RTOS/动态回调等超出现有模型的部分不能据此证明安全。真实工程本身的风险和覆盖缺口仍需工程师复核。
