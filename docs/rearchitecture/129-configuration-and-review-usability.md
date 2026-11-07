# 配置完整性与人工确认使用修复（最终v86）

**最终入口为v86；下文v84/v85记录保留为分阶段验收历史。**

起点 optimize_ccc@30c060410266820f8be59868d1ae49bd51ace2f1，工作区干净。本轮先审查真实配置、表单同步、启动门禁和用户截图，再实际修复。

## 已定位问题与冻结方案

1. 保存配置后仍须另外启动一次真实构建预检；历史预检不放行，但按钮没有解释禁用原因，多个分离动作使用户无法开始。进一步逐行核对确认 openProfile 原本会设置 savedYaml，初步归因已更正。提供一次明确点击后顺序执行配置检查、保存、真实构建预检及扫描的流程；失败中止并显示原因，不跳过预检。
2. 当前表单仅覆盖基本构建/范围/入口/Git。缺少 OpenCode 全部设置、芯片/字长、排除文件、预期宏、CMake 参数与超时、解析工作数与超时、自动入口及扩展并发语义。增加带类型、逐项说明的配置目录；未填写保持引擎默认，仅显式改动字段进入原有无损 YAML 合并。未知字段、注释、未改分支保留。复杂语义以独立JSON段编辑（与YAML结构等价），并提供对应JSON示例；旧兼容字段明确标记，不当作日常默认。
3. 新建配置不会自动套用 config/semantics.yaml 的用户工程路径和 Diff 基准。新增“从现有 YAML 导入”供用户明确选择完整配置，保留原文，随后映射到表单；实际 config/semantics.yaml 的每个活动叶字段纳入对照测试。
4. 每个配置项提供简短用途、默认或例子；OpenCode 命令逐参数填写，不作为 shell 执行，不暗中调用模型。
5. 人工填写区改为可收起，默认优先阅读证据；身份、调用链与技术原文按需展开。主视图不重复渲染全部静态集合，空集合不占行；完整对象与未来字段仍在高级原文中。风险、未知与冲突提示保持可见，草稿和不可变事件协议不变。

## 验证计划

- 真配置活动叶字段与表单目录逐项比对；OpenCode 参数/布尔/数字/摘要设置、注释/未知字段/共享结构及类型的无损往返。
- 新建与重开保存配置；真实预检成功后开始扫描、失败停止、配置变化取消待启动；不写固件。
- 1366×768、1600×900，收起/展开填写区和证据；草稿、明确确认及撤销。
- 专项后端、前端类型构建、真实浏览器与新便携包入口。其他 G2、32GB 真机、离线干净机、系统 DPI、人 UAT 与整轮 Diff/恢复仍待验。

本轮配置与阅读交互范围已通过最终验收，见下方实际结果；整体重构门禁仍未全部通过。

## 当前配置字段对照

31个活动字段全部有编辑位置或明确用途；附加目录共45项。未知未来字段仍保留在高级原文。配置注释不作为生效字段；多行列表作为一个完整选项。

| 配置字段 | 对应位置 |
|---|---|
| `version` | 兼容与位置设置 |
| `project.root` | 普通表单 |
| `project.chip` | 工程 |
| `project.core` | 普通表单 |
| `project.native_word_bits` | 工程 |
| `analysis.git_diff.enabled` | 普通表单 |
| `analysis.git_diff.base_ref` | 普通表单 |
| `analysis.git_diff.current_ref` | 普通表单 |
| `analysis.include_dirs` | 普通表单 |
| `analysis.exclude_dirs` | 普通表单 |
| `analysis.exclude_files` | 排查选项 |
| `analysis.parse_timeout_seconds` | 排查选项 |
| `analysis.extraction_workers` | 排查选项 |
| `analysis.auto_system_includes` | 普通表单 |
| `analysis.open_report` | 兼容与位置设置 |
| `analysis.cmake.build_dir` | 构建细节 |
| `analysis.cmake.generator` | 构建细节 |
| `analysis.cmake.build_type` | 普通表单 |
| `analysis.cmake.toolchain_file` | 普通表单 |
| `analysis.cmake.args` | 构建细节 |
| `analysis.cmake.clean_before_configure` | 构建细节 |
| `analysis.cmake.build` | 构建细节 |
| `contexts` | 普通表单 |
| `review.enabled` | OpenCode |
| `review.command` | OpenCode |
| `review.timeout_seconds` | OpenCode |
| `review.retries` | OpenCode |
| `review.workers` | OpenCode |
| `review.summary.enabled` | OpenCode |
| `review.summary.max_chars` | OpenCode |
| `review.summary.fix_retries` | OpenCode |

详见[逐字段审计与专项测试](acceptance/configuration-v84-audit.json)。

## 实际验收与分发

- 当前配置31个活动项均有编辑位置或用途；45项附加设置带类型和说明。44项源码专项（配置无损往返、API、真实预检、资源策略）通过，前端类型检查/构建和12项UI合同检查通过。新包内21项配置/资源测试通过。
- 真F030配置：重开已保存配置可操作；OpenCode带空格程序路径及逐参数设置无损往返；缺失真实编译数据库时没有启动扫描；修正后一次点击完成保存、预检和正式原生扫描。
- 真CMake教学工程：从v84封存包 ECRA.cmd 在Windows-only PATH启动，实际构建并扫描成功；归档目标demo、Release变体和配置解析并行数2一致。
- 人工确认：1366×768收起填写区后证据高度约470.92px，1600×900截图另存。收起、切换对象后草稿保留，显式确认与撤销产生2条不可变事件；重新启动封存包后仍能看到。技术原文入口保留。
- 最终后验：42个原始F030固件文件、5个CMake教学源文件的名称/大小/mtime/SHA-256均未变；310个既有归档静态文件未变；32,873个程序清单文件未被运行改写。仓库475个程序/前端/测试文件与冻结版本相同。

初次脚本错误分别为历史按钮名称、源码选择器拼写；其部分通过和失败原件保留，没有改为整轮PASS。CMake源测试的隔离LOCALAPPDATA过长，触发已有ASCII别名长度保护；最终包在显式隔离短目录 `H:/ECRA-UI84-PATHS` 下真实复测通过，没有放宽路径校验。封存包测试头部误沿用了“source CMD”的描述，原件保留后更正说明；server.json和启动脚本证明实际入口为v84封存包。

[最终收据](acceptance/configuration-v84-final.json)、[包内浏览器](acceptance/configuration-v84-portable-browser.json)、[分发清单/解压](acceptance/configuration-v84-portable-assembly.json)和[选定脚本与截图附件](acceptance/configuration-v84-proof.json)分别记录。54项旧工具/运行时验证是相同工具字节的继承结果，不冒称本轮重跑或覆盖新配置行为。程序包冻结后新增的终验记录保存在包外与源码仓库，避免修改封存包形成循环哈希。

入口：`H:/ECRAStudio-build-20261107-studio-v84/ECRA-Portable/ECRA.cmd`。ZIP：`H:/ECRAStudio-build-20261107-studio-v84/ECRA-Portable.zip`，784175284字节，SHA-256 `958fc3359d1a3240fffa23ee20b1e34238e350b9481b4d4d5ff80ea795ca3dc8`。冻结源码清单SHA-256 `e99d6cfde79f0543250ab490f7b02e72381264e8f08c2b37c3e4fa833ab77492`。旧包保留。

操作说明见[v84配置与人工确认指南](../studio-v84-configuration-guide.md)，其中有真实界面截图。配置读写和流程已验；真实OpenCode提供商联网调用未验证。其他G2工程、32GB真机、干净离线电脑、原生系统DPI、人工UAT和整轮大型Diff/恢复仍待验；已有跨环境严格报告FAIL保留，比较规则没有改动。

## v85 最终边界修复

补上旧配置值类型错误时的控件保护：例如review.command写成字符串时，显示就地说明并允许恢复默认或返回原文修复，不对该值调用数组操作。保留原文，不静默转换。v84已封存验证；中间候选v85仅改变前端这一处保护，Python/测试/工具字节应与v84一致，终验另记。

最终v86还修正从编译数据库切换为CMake时的操作顺序：先初始化分支默认，再应用显式附加选项，避免覆盖用户选择的生成器和build开关。新增独立回归，22项配置/资源源码测试通过。v85保留为中间候选，最终验收另记。

## v86 最终验收

最终45项源码专项、包内22项配置/资源测试、类型检查和构建通过；v86实际入口完成错误命令格式提示→显式修复→真实CMake预检→正式原生扫描。目标demo、Release及配置并行数2一致，收起填写区后证据高度仍大于430px。先前F030缺文件阻断、成功扫描、草稿/确认/撤销及重启历史均保留独立证据。

最终后验通过：42个原固件文件、5个本轮教学工程文件的名称/大小/mtime/哈希不变；310个旧归档静态文件不变；32,884个受清单保护的程序文件未被运行改写，仓库475个程序/前端/测试文件与冻结版相同。测试服务和浏览器已关闭。

[最终v86收据](acceptance/configuration-v86-final.json)、[45项源码专项](acceptance/configuration-v86-source-tests.json)、[v86包内浏览器](acceptance/configuration-v86-portable-browser.json)、[封装与中文解压](acceptance/configuration-v86-portable-assembly.json)、[选定脚本与截图附件](acceptance/configuration-v86-proof.json)。旧`validate_build_preflight_ui.py`中的“预检前开始按钮必须禁用”属于被本轮用户请求替代的旧交互合同，本轮不冒称运行通过；新入口实际脚本与截图在附件中。

启动：`H:/ECRAStudio-build-20261107-studio-v86/ECRA-Portable/ECRA.cmd`。ZIP：`H:/ECRAStudio-build-20261107-studio-v86/ECRA-Portable.zip`，784528737字节，SHA-256 `8a7d676698e866f94a071dd7749e39aced7899460efc9035cca4c38cb7779bda`。冻结源码清单 SHA-256 `f1b73ebbe6d09e1122df9c06933cab0b8505d6120c400789b2d05fe8c41f4a39`。

上述为本轮配置与人工确认使用范围的PASS；真实OpenCode联网调用及前述大型整轮/硬件/离线/DPI/人工UAT待验项没有被替代，严格跨环境FAIL仍保留。
