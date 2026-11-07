# OpenCode案例库与工程背景传递（v88）

用户提供任务日志：在work/tasks/<id>/concurrency_cases.md查找失败，且没有案例库及review_context.md配置入口。

## 审计结论与实施前规格

原CLI和workflow均从实际semantics.yaml相邻目录加载review_context.md与concurrency_cases.md。原八步提示、案例索引/正文read要求、源代码阅读合同、摘要修复、重试和收据不改。Studio把配置移到projects/<工程>/profiles，再移到work/tasks；目前只尝试从profiles相邻目录复制两个文件，文件不存在就静默跳过。因此工具config中的真实案例库丢失，review_context缺失还会静默返回空。

新增每个独立工程配置的“案例库与工程背景”页面，明确来源、状态、大小、哈希、案例数和工程背景是否只有注释。支持沿用原相邻文件/工具config默认、本机Markdown文件、编辑工程副本；不改写工具config原件。材料绑定与不可变内容在独立数据根管理，按配置区分。现有YAML与CLI相邻文件合同保留。

实际扫描启用OpenCode、复核全部、仅重试失败三条入口均在启动前解析并冻结相同资料；precheck不调用模型也不因可选资料而阻断。配置了不存在的来源时明确失败，不再悄悄漏掉材料。每个任务保存实际来源与内容哈希；已启动任务继续使用冻结版本，新任务读取新配置。恢复优先复用并校验原任务资料。完整prompt与原案例正文阅读链仍使用现有引擎。

## 必须验证

工具默认、旧相邻文件、自选文件及编辑副本四种来源；内容注释剥离与有效背景；案例完整索引/正文快照；后续编辑不改已启动任务；错误路径/并发保存/链接/UTF8与大文件边界；整套数据迁移包含工程副本。真实浏览器配置页面、任务实际快照和原review_all输入边界分别记录。联网提供商复核没有实际执行时仍标NOT_VERIFIED，不以模拟模型结论代替。

本轮资料配置与传递范围已完成，实际验证边界见下文；全项目门禁仍未全部通过。

## 源码阶段实测

原review.py/review_context.py/case_library.py/cli.py/workflow.py及合同、摘要、收据实现均与v87逐字节相同，见[原合同核验](acceptance/review-materials-v88-original-contract.json)。新层只负责资料配置、来源解析、完整冻结与审计；GUI明确拒绝配置不可读来源，不改旧CLI的缺失文件处理代码。已覆盖prepare_packets离线输入准备分支。

真实浏览器配置默认26案例、编辑工程背景、选择中文文件、失败提示、保存和重开均通过。新静态扫描不需要可选资料；真实手动复核任务成功冻结两份文件并生成含背景与案例的原提示。不存在的模型命令导致6条TECH_FAILED、0条DONE，属于明确的技术失败路径，不冒称联网模型成功。见[源码流程](acceptance/review-materials-v88-source-browser.json)。第一次隔离测试复制了旧CMake缓存导致别名路径冲突，失败保留；重新使用干净数据根配置后通过，没有删除或放宽原缓存校验。最终包与后验待记录。

源码最终77项专项通过，1项真实联网提供商用例按条件跳过，不计联网验证。覆盖原案例库、八步复核、深层复核、原生复核/重试/包、API、资料来源与冻结、文件排除表单。首轮组合测试发现资料保存SQLite连接未及时关闭导致Windows临时目录清理失败，已用显式closing修复并完整复测；失败日志保留。默认工程背景缺失仍按原约定视为空，明确选择的不存在文件则拒绝保存；实际原引擎代码未修改。

## v88 最终包验收

源码77项专项（1项联网用例跳过），包内58项专项（同一联网用例跳过），其余均通过。没有修改测试或放宽比较规则。首轮包内案例库分发回归需要源码build_portable.ps1而旧运行包未附带，保留首次FAIL后补入冻结清单中的7份真实构建支持文件，原58项重新运行通过，再重新生成完整清单与ZIP。

实际包内入口使用Windows-only PATH，验证三条入口：

| 入口 | 实际观察 |
|---|---|
| 原生扫描并离线准备输入 | prepare_packets保留原功能；冻结26案例与工程背景，生成原Packet/提示词；未调用模型 |
| 手动复核全部 | 新任务读取新背景V2；原任务V1文件哈希不变；案例完整字节与工具config相同 |
| 仅重试技术失败 | 再次冻结完整案例与当前背景，仍保留原静态事实库字节 |

测试命令明确指向不存在的可执行文件，只验证技术失败和输入链路，0条模型成功结论；不把它算作真实提供商联网复核。原review、CLI、workflow、案例库、背景处理、八步提示和收据代码与v87逐字节一致。GUI新增的是可见的来源校验与任务冻结：明确配置不可读来源时提示修复；旧CLI的缺失资料处理代码保留。

[最终后验](acceptance/review-materials-v88-final.json)、[最终包内浏览器](acceptance/review-materials-v88-portable-browser.json)、[分发与中文解压](acceptance/review-materials-v88-portable-assembly.json)、[77项源码专项](acceptance/review-materials-v88-source-tests.json)、[脚本/提示词/冻结原件附件](acceptance/review-materials-v88-proof.json)。原42个固件文件和5个教学源文件未变，32,913个程序文件未被运行改写；两轮复核前后原scan.db完全相同，人工事件仍为0。所有本轮测试服务与浏览器已关闭。

最终入口：H:/ECRAStudio-build-20261107-studio-v88/ECRA-Portable/ECRA.cmd。ZIP为784856085字节，SHA-256 3739ba3ba43c339af60a7089f5523b5df6d053aa2a6755f8e79321c3611167a3。冻结源清单SHA-256 c377fe22b3fd35ca77907066cb9d4fe1bb9bb84822e5d21731229aa55c5c3a37。终验收据保存在包外与源码仓库，封存包不再修改。

[使用教程及截图](../studio-v88-review-materials-guide.md)。用户已运行的旧任务不会被中途替换输入；配置后应新建复核任务。真实OpenCode提供商成功复核、其他G2、32GB真机、干净离线电脑、原生DPI、人工UAT和整轮大型Diff/恢复仍NOT_VERIFIED。原跨环境严格FAIL保留。
