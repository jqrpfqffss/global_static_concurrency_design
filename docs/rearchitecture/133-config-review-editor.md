# v90：config 原文件独立表单编辑

基于 optimize_ccc 的 07d72d6。按最新用户要求替代 v88/v89 的按工程绑定、多来源编辑方式：不需要先保存工程配置；唯一活动来源是工具 config 下两份原文件；工程背景允许为空。历史版本文档和收据保留，旧工程副本不删除、不自动导入。

## 实现边界

- 全局认证 API `/api/review-materials`，不接受来源、路径、文件导入参数。旧工程绑定写入/预览接口关闭。工程配置所有步骤和无扫描的 OpenCode 页面都能打开编辑器。
- 普通文字表单：案例名称、问题描述及可选分类、来源、代码、发生过程等；自动分配 CASE 编号、生成固定八段格式和合适的代码围栏。工程背景为独立文本框，空白保存为零字节。
- 以原文件为基础定位并替换改变的字段，不重写未修改案例；保留 UTF-8 BOM、原 CRLF、非标准元数据、其它章节、来源和模板。新段自动生成 Markdown，正文中看似 CASE/标题的文字转义为普通正文。
- 跨数据根共用短暂配置锁，原文哈希防止并发覆盖，临时文件+原子替换；旧版与拟保存版本在独立数据根备份。工具 config 中只改两份明确授权的 Markdown，不创建扫描产物、数据库或锁文件。
- 每次新任务从 config 冻结两份文件；恢复严格使用原任务快照。扫描策略、五种 OpenCode 结论、原收据校验与模型提示词合同不变。

## 验证进度

源码相关测试 157 项：156 通过、1 项可选联网单测跳过。表单测试覆盖 26 条原始案例逐字节无改动回写、追加自动编号、代码围栏、标题转义、自定义字段/章节保留、重复编号、空背景；API/任务测试覆盖无工程读写、拒绝外部来源、旧绑定不再生效但保留、并发冲突、原子失败、备份、任务冻结及恢复。

真实浏览器从 profiles 为空的页面开始：编辑并重新打开空背景、新增 CASE-0027、修改该条、确认其余 26 条原文未变、跨标签保留草稿、关闭提醒、搜索重开均已通过；1366×768、1440×900 下保存按钮固定可见，表单阅读区可用。测试只修改隔离测试 config，仓库原始两份资料不改。

真实 STM32F030 完整四个 TU 扫描与六项 OpenCode 复核已完成：扫描 `3ce7f311a3e54b658f7fdd060cdb06a1`，复核任务 `70a35ef40980459bbb155d9d3b50c6b1`。背景文件为零字节，六项 DONE、技术失败 0，结果为 LIKELY 1、FALSE_POSITIVE 5。原收据逐项校验通过，均有案例正文成功 read 记录。复核期间页面实际保存了两份新原文，保存前后任务均为 RUNNING，任务快照及静态 scan.db 均未变化；没有将新背景或新案例正文混入该轮。原始 INCOMPLETE 与退出码 2 保留，不把疑似风险当成安全。

Portable 自带 Python 的完整相关套件 141 项：139 通过、2 跳过（可选联网单测、开发 TestClient）；实际联网六项单独验证。之后对最小输入自动补全、BOM 首行、普通/加粗元数据、正文转义等补充修复，源码及包内各 22 项针对性回归全部通过。原有 26 条案例无改动保存仍逐字节相同。

独立副本运行真实 Portable `ECRA.cmd`，子进程只提供 Windows 系统 PATH。从 profiles 为空开始重做编辑、空背景、CASE-0027 自动编号、草稿保留、两个窗口冲突、仅填写名称/说明新增 CASE-0028 等操作均通过。编辑后对程序目录逐项核对：只有 `config/concurrency_cases.md`、`config/review_context.md` 两个文件改变，其余 32,936 个文件未变，无新增程序缓存/数据库/锁文件。原默认资料及最终发行目录没有被验收文本覆盖。

验收收据与截图：

- [空白界面编辑流程](acceptance/review-editor-v90-ui.json)、[Portable 编辑复验](acceptance/review-editor-v90-packaged-ui.json)、[最小填写/冲突/写入范围](acceptance/review-editor-v90-extra-ui.json)
- [真实空背景六项复核](acceptance/review-editor-v90-real-review.json)、[运行中编辑快照检查](acceptance/review-editor-v90-active-edit.json)
- [源码套件](acceptance/review-editor-v90-source-tests.json)、[包内套件](acceptance/review-editor-v90-packaged-tests.json)、[补充修复回归](acceptance/review-editor-v90-targeted-tests.json)
- [表单截图](acceptance/review-editor-v90-form.png)、[空背景截图](acceptance/review-editor-v90-empty.png)

原始日志、Playwright CLI 脚本与网络模型响应位于本机 `H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/ui-v90`，Portable 编辑副本位于相邻 `ui-v90-portable`。源码 UI 通过隔离 CONFIG_HOME 验证；包内 UI 通过真实启动器的包内 config 验证，均未修改固件。发行清单与 ZIP 最终验收使用另附的 `portable-v90-assembly.json`、`portable-v90-final-check.json`，只在实际通过后计通过。

其他 G2 工程、32GB 真机、干净离线电脑、原生 DPI、人工 UAT、大型整轮 Diff/恢复未完成门禁仍按原记录待验，跨环境严格对照 FAIL 保留。
