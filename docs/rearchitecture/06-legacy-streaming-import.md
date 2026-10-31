# 旧归档流式迁移合同与实测（进行中）

沿用任务书§7.10、既有九导航、线框和共享页：来源选择→归属检查→只读迁移计划→真实后台阶段→校验后发布→打开同一证据/人工工作台。新增区域在“数据与共享”的包导入/导出之后、空间整理之前；不引入第二套页面或模拟风险。原工程与旧结果目录使用绝对路径字段，仍未实现Windows原生目录选择器。

`legacy_import.inspect`复用WorkspaceResolver的工程/仓库身份算法，核对run.json和scan_state.json；工具workspace另核对原project.json。拒绝链接、WAL/恢复文件、来源和目标交叠、错工程和缺少完整事实。不能把旧facts.db当作无损事实根：旧写入器排序列、将bool变成SQLite整数，且不保存所有根级对象。缺完整facts.json时明确缺证据并停止，原数据保留；缺证据归档的专门降级Viewer尚未完成。

`publish_json_scan`与新扫描使用同一有序类型图、投影和独占原子发布。递归解析容器，SQLite保存中间边、重复键检查和共享JSON节点映射，不重新构造完整事实/报告/共享池。仅单个标量token与解析栈在Python中；超大单字符串仍可能占用相应内存，未声称全输入常数内存。非法前向引用、重复键、非有限浮点、截断及尾随数据拒绝，字段/顺序/重复/负零无损。

事实和报告完整入库，其原字节SHA、大小、来源名、处置方式保存到provenance.legacy_inputs。其他旧文件（含旧facts.db、HTML、AI/人工文件及未知文件）作为不执行的CAS审计原字节留存并进入标准包；尚未逐版本证明的旧数据库不当作冗余删除。旧来源不写、不移、不删。完成后只回收本次私有转换JSON；重复导入验证相同根后回收本次私有重复库，不触碰已有归档和人工事件。旧数据保留可能增加磁盘，不计作G4收益。

迁移状态固定LEGACY_READ_ONLY，当前源码/工具/模型未重新证明。完整旧report中的原始AI/历史字段保留；独立新人工库默认PENDING。没有经过合同验证的旧AI/人工决定，不自动投影为当前SAFE。旧文件清单/完整SHA/文本或十六进制片段可分页继续查看；大段有总字节/游标，HTML/代码只用文本插值。旧源文件未归档时显示缺失，不用当前源码填充历史证据。这些限制在所有结果页面显示，并随包内provenance传递。

任务使用独立跨进程活动租约与持久SQLite小记录。新Studio不能把另一个活进程的迁移误判中断；退出后无租约RUNNING改为INTERRUPTED。私有失败现场保留，用户可核对源数据重新迁移；尚未实现巨型迁移在任意字节断点继续。来源完整清单和哈希在发布前复验；相同来源/内容再次导入命中既有扫描，当前人工确认不被覆盖。

实测入口：`scripts/validate_legacy_import.py`、`scripts/validate_legacy_ui.py`、`tests/test_streamed_evidence.py`、`tests/test_legacy_import.py`。原64文件的真实4TU黄金旧输出在隔离副本经原版checked_scan批准，转换facts/report全字段有序类型差异0，原目录哈希不变，标准包往返通过。50,000行普通JSON与50,000节点shared池的完整根哈希相等，峰值工作集分别28,692,480/30,687,232B；SQLite分别84,123,648/84,160,512B，大于11MB输入，不是G4收益。原始日志见continuation-h3/legacy-stream-v5-acceptance.json，范围为编码/存储，不是原生分析。

真实Chrome的六项迁移操作见output/playwright/studio-legacy-20261101-v3/acceptance.json，保存五张实际截图、视频和trace：错工程拒绝、迁移真实原生结果副本、人工保存重开、原始审计分段/脚本不执行、重复导入保留确认、损坏输入保留旧有效库。真实原生4TU旧输出的转换不能冒充新扫描G1，也不能替代大型shared JSON、双旧来源人工事件合并、完整U21/G6。

验证器修正：原版checked_scan会在验证成功时写diagnostics/resume_source_changes.json，直接在只读黄金目录调用会失败并留下.tmp。本轮失败日志保留；本次产生的唯一.tmp按创建时间和长度核对后移到验证失败现场，六个已冻结权威文件SHA仍匹配既有收据。现改成在隔离完整旧输出副本执行原版验证，并用Python audit hook禁止该验证进程向冻结baseline写入；黄金目录不解除只读。此修正不修改原引擎。

## 浏览协议与有界证据翻页

原SQLite保持所有标量类型；API另外提供整数十进制exact_value、浮点repr与hex，防止JavaScript binary64舍入大整数或隐藏负零。合法旧JSON的未配对UTF-16代码单元在HTTP/MCP使用JSON转义传输，界面以带说明的JSON转义表示，原值/根哈希不改变。Unicode正常文本仍直接展示。

通用EvidenceNode每次保留一页关系/一段文本，提供前后导航、总量与UTF-8字节游标，不再把所有已翻页内容累积到浏览器。20007行真实服务容量复测新增八项操作，最大API17,192B、首屏0.234s、末尾对象搜索/打开0.141s，并实际检查大整数、负零、转义、407条关系前后页、长UTF-8文本前后段与SQLite确认持久。见output/playwright/studio-capacity-wire-20261101-v2/acceptance.json。这仍是显式存储/浏览夹具，不是原生固件和全部U10。
