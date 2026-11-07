# 从工程师实际操作出发的验收与修复（2026-11-07）

本轮从 `optimize_ccc@75142c44d91484374e48243c9dcb55c4866c089e` 的干净工作区开始，Codex 直接实施。先以实际 v79 Portable 和空数据目录操作真实 F030 包，再修复、重走用户路径。原需求文档 H1–H6 继续生效，交互依据为[46号补充](ui/46-investigation-drafts-and-evidence-names.md)，现有九导航、颜色、分栏和固定操作区未重设计。

最终便携候选 v81 已通过本轮限定范围验收；[最终收据](acceptance/user-workflow-v81-final.json)明确 `all_gates_passed=false`，不能据此宣称完整重构或全部门禁通过。最新大型原生完整包的既有最终证据仍见[126号](126-latest-large-package-and-recovery-acceptance.md)。整轮大型 Diff/恢复、其他未获准 G2 工程、物理 32GB、干净离线电脑、系统 DPI 和人工盲测分别待验。

## 用户实际遇到的问题及修复

1. 写完调查依据、选好“待验证”，按 Esc 回列表再打开同一变量，文字和状态都会丢失。现在按扫描及规范变量身份独立保留本窗口草稿，切换对象、筛选、页面和 Esc 不丢；同名 static 不串笔记。存在草稿时关闭/刷新触发浏览器提醒。**草稿仅存当前窗口内存，不承诺重启恢复或随包迁移；正式确认必须显式提交，仍由数据库持久保存。**
2. 并发参与者显示 `auto:SysTick_Handler:bacec779` 和 `c:@F@SysTick_Handler`。现在首先显示归档里的上下文种类、物理域和函数全名，原身份仍可见；确切身份查询、逐页读取和最多128项缓存，不猜入口、优先级或安全性。
3. 审计发现对象读取失败时旧人工状态可能残留在新对象表单。现在读完当前对象前禁用确认、清空旧证据，迟到响应不能写入其他对象；读取失败可重新点击对象。正式确认已成功而统计刷新失败时，仍明确显示“已保存”，不把已提交文字误留为草稿。
4. 损坏文件被正确拒绝，但原提示只有诊断编号。现在提供文件完整性、数据盘空间、重新选择文件及反馈诊断的中文指引；确认增量还提示核对归档归属。只包装失败的上传请求，导入已提交后刷新失败仍显示已提交。
5. 真实新 F030 扫描的 `EXECUTION_CONTEXT_UNRESOLVED` 被界面称为未识别类型。现在显示“执行上下文未恢复”，并提示核对调用者、main/IRQ/任务入口及回调；原始代码与记录保留，仍为 INCOMPLETE。

变更集中于 `App.vue`、`reviewDrafts.ts`、`EvidenceIdentity.vue`、`evidenceNames.ts`、`ConflictPairs.vue`、`CoverageCenter.vue` 及构建资源。Python 分析、Diff、归档和人工事件协议没有变化。新编译输出和8项专项检查通过；12项已有 UI 结构检查通过。

## 实际操作范围

| 阶段 | 用户路径与实现 | 实际检查 | 场景对应及边界 |
|---|---|---|---|
| Phase 4 | 空目录启动→导入同事完整包→概览疑似下钻→函数/上下文→归档源码 | 实际 v79 对照及修复后 source CMD；真实 F030 完整包 | U01/U09/U11/U12 局部；不是模拟结果 |
| Phase 4 | 边排查边记依据→Esc→切换其他变量→覆盖页→返回→关闭提醒取消 | 两份草稿分别保留，未提交不产生人工事件；三个尺寸源码目标行和四按钮可见 | U16/U22 局部；不是1000项人工盲测或系统 DPI |
| Phase 4 | 读取失败→恢复重试；确认提交成功→统计刷新失败 | 浏览器明确注入 HTTP 错误，只验证异常恢复；真实归档不模拟，确认事务确实写入 | 读取失败禁用决定；提交后失败仍显示已保存 |
| Phase 4 | 显式暂无法确认→撤销→刷新→继续上次位置 | 实际4条自动化声明/撤销事件，原原因、事件ID及父子关系保留 | U16/U17 局部，声明不构成实际工程风险判定 |
| Phase 5 | 浏览器下载增量→另一个空数据根导入原完整包→导入增量→再次导入 | 下载2981字节；原4条事件完整可读，重复新增0；真实损坏文件拒绝且旧记录不变 | U19/U20/U24 局部；同主机独立服务，不是物理第二台电脑 |
| Phase 4 | 四步普通向导→保存配置→查看真实编译输入→开始扫描→覆盖诊断 | 实际获准 F030，未手改 YAML；4 TU/25项预检；新 scan `b7336600cd6641ef9a1c5faf35c77192` 发布，exit 2/INCOMPLETE、2 PARSED/2 PARTIAL保留 | U02/U03/U06/U09/U14 局部；15对象、1疑似/5未知/7安全/2容器，原固件目录42文件 SHA/大小/mtime/命名空间不变 |
| Phase 4 | 大型 INAV 结果名称搜索→逐页关系→代码→草稿 | 最新严格完整包导入结果的2668文件独立逐字节副本；113组/226参与者逐项核对原身份、函数全名和归档物理域；1366/1600/1920三尺寸 | U10/U12/U13/U22 局部；未覆盖超过20,000行或全部调用路径，也不补造硬件优先级；0个人工事件 |
| Phase 6 | 封存程序与实际 CMD 重启 | v81目录/中文解压各27检查、实际CMD重启、接收端6组/大型Viewer3组检查通过；中间v80保留；474个Python/测试/依赖源与冻结v78一致 | 沿用未变后端原1566 PASS/2联网SKIP及34包内专项的限定范围；不声称本轮重复执行 |

增量 SHA-256：`dd28068ac3cf2af3f4446355d7bf020ca007b875d38505efe40f327a3856acc5`。最新大型包来源仍为 `7e72bc5d7ee4f01d5e88bf17845aa6c50d7cae5974a11f5422193b970fc787f5`；本轮 Viewer 静态库为 `c6180f66323ae9ce72711ee8c83858cdce04114cc1e210a30aaa7dc3e760163b`。原大型严格导入目录及本轮副本 scan.db 后验保持不变。

## 验证方式与未掩盖的失败

实际 Chrome 由 Playwright CLI 操作；每步从新 snapshot 获取控件引用，不直接调用后台写接口替代点击。后台查询及只读 SQLite 用于结果对照。两个故障用例明确注入 HTTP 503，不用于声称真实扫描成功。全部自动化确认都带“自动化验收”声明。

原 v79 丢草稿失败永久保留。测试控制器也有失败，均与应用结果分开保存：接收端首次启动竞态、固定2秒等待早于导入完成；误等英文 `File`，实际后端已返回中文拒绝；引用解析器未支持 `[active]`；Windows `npx.cmd` 将无空格 JavaScript 中的 `>` 当作 shell 重定向，导致空输出退出；原生扫描等待器误限定 `h2`，实际标题已发布。修正为等待真实页面状态、解析实际引用属性、直接以 Node 运行同一缓存版本的 Playwright CLI（0.1.23），以及核对实际 heading/任务记录。原扫描已完成后终止的错误等待器仍保留在途原记录，独立补充收据证明真实发布和原件未变。没有把这些测试控制器失败删掉或改成 PASS。

复现核心检查：`node --test studio/tests/investigation-state.test.mjs`、`npm run build`（studio目录）、`py -3.10 -B -X utf8 scripts/validate_ui_contract.py --output <外置文件>`。实际分段控制器、源状态、截图与原始 CLI 快照位于外置 `H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/user-*v80*` 与 v81验收目录，[最终证据索引](acceptance/user-workflow-v81-evidence-index.json)保存逐文件原SHA，[浏览器记录索引](acceptance/user-workflow-v81-browser-records.json)保存外置完整日志包SHA；含会话令牌的启动记录不进入公开归档。


## 最终便携包、独立复核与截图

实际入口为 `H:/ECRAStudio-build-20261107-studio-v81/ECRA-Portable/ECRA.cmd`，同级 `ECRA-Portable.zip` 为 780302019 字节，SHA-256 `ef8b223147ce3c4e5783457a50b59c6307e0d65daa54f3760016e32c4bae88b1`。32,452负载文件加清单共32,453文件，实际操作退出后全SHA与命名空间均无差异；148应用文件匹配冻结源，28,805运行时/工具文件与已验证v78逐字节相同。源快照SHA为 `fb1dcaf4f66dbf92e0f33be784a5bb26a278c56d58a4b039325e764d4f7c98d3`，分发清单SHA为 `721e660013a51234773c688d96d404befe22504836d157b21ccf7070e4daa9b3`。包内文档冻结于打包时，最终验收以后续仓库本文及原始收据为准，不静默替换已封存ZIP。

[实际接收端重启检查](acceptance/user-workflow-v81-portable-receiver.json)与[实际大型Viewer检查](acceptance/user-workflow-v81-portable-large.json)均为最终 v81 的真实程序。两份原 source 服务结束后才启动新的实际 CMD，使用仅 Windows 的 PATH。接收端6组覆盖历史继续、名称、草稿、真实提交失败保护、关闭提醒、损坏包和新原生覆盖诊断；大型Viewer再次核对全部113组/226参与者及三尺寸源码。原4条人工事件的**每个字段、值及父列表**后验相等，见[完整人工字段对照](acceptance/user-workflow-v81-human-fields.json)，没有排除字段。大型Viewer没有新增人工事件。两个服务树提交峰值分别为 57708544 和 56975360 字节，仅代表这次Viewer操作，不含浏览器，也不是整轮扫描峰值。

三份F030导入副本的静态库及完整证据61文件保持原字节；大型副本2667个不可变文件（含全部证据对象）后验无差异。新F030扫描不产生旧完整facts/report JSON或HTML。**计数校正：本轮原固件目录实际为42文件；前面进度曾沿用另一轮43的口径，后者额外包含当时的独立semantics.yaml，本轮按42记账。** 未把外部配置当固件文件，也未把原生部分覆盖改成完整覆盖。

可直接审核[修复前丢失的草稿](ui/screenshots/user-workflow-v81/02-original-lost-draft.png)、[修复后1366下的源码与两份独立草稿](ui/screenshots/user-workflow-v81/03-preserved-draft-source-1366.png)、[最终包真实main/IRQ关系](ui/screenshots/user-workflow-v81/10-portable-main-irq.png)、[最终包原4条确认历史](ui/screenshots/user-workflow-v81/09-portable-original-history.png)和[最终包覆盖修复指引](ui/screenshots/user-workflow-v81/08-portable-context-guidance.png)。截图已实际查看，未经生成或替换数据。全部13张截图与原始机器收据按SHA归档。

整轮大型 Diff/恢复在本轮收尾时仍为 `RUNNING_RECOVERY_AND_COMPLETE_INDEPENDENT_VERIFICATION`，见[在途快照](acceptance/user-workflow-v81-whole-diff-snapshot.json)，不是最终通过结果。其前置新完整包已通过的范围仍以126号为准；原跨环境严格报告 FAIL 继续保留，未修改比较规则。其他G2工程按用户决定待验；物理32GB、干净离线电脑、原生系统DPI、真实联网模型与人工UAT仍不能由本轮自动化代替。

提交前另以 Git 暂存对象复核全部64份原始证据与截图的字节、长度和SHA，见[Git字节对照](acceptance/user-workflow-v81-git-byte-proof.json)。原始Windows CRLF保持不变；源代码与说明文档通过空白检查。原始证据按CRLF格式检查，6份控制器副本保留原有EOF空行告警，不为消除格式告警重写原记录。
