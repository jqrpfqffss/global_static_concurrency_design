# 数据格式与迁移：已实现部分与边界

本版本仍**不是 Phase 1–6 完成声明**。scan.db 协议版本2，读取/严格校验继续支持版本1。v2 将引擎实际使用的 caller_function_id/callee_function_id 纳入调用边索引；v1 按旧投影校验并从权威边补充调用查询，不重写归档。SQLite是权威证据，新正式扫描不另存完整事实JSON。

## 权威树与业务投影

| 表/视图 | 字段/关系 | 索引/约束 |
|---|---|---|
| nodes | id、hash、kind、value、length；null/bool/int/float/str/object/list | SHA唯一，长度非负；相同SHA逐内容检查后才合并 |
| edges | parent、ordinal、key、child | parent+ordinal主键，父子外键；child反向索引；全部顺序/重复保留 |
| roots | facts/report/provenance → node | 根名称主键、外键 |
| records | dataset、relation、ordinal、node、symbol/function/source/target身份 | 复合主键；symbol/function/source/target复合索引 |
| symbols | canonical ID、原ordinal、node、名称、静态分类、存储种类、定义、覆盖 | identity唯一；分类/名称+ordinal索引 |
| projects/profiles/scans | 原项目/配置/扫描身份、状态、facts/report根哈希 | 项目/配置外键；一个scan.db一份扫描 |
| accesses/functions/call_edges/protection_events/findings/irq_priorities/coverage_gaps/translation_units | 对权威records的只读关系视图 | 使用records索引；不是第二份JSON |

未知未来字段保存在原始有序树中。bool与int分开，float用hex保留负零；字符串使用UTF-8 surrogatepass。对象字段顺序也保留。SHA绑定类型、长度、字段/列表顺序与子哈希。共享节点只去重物理记录；重复逻辑边仍保留。

目前还没有完成任务书要求的全部专门业务关系（特别是 points-to/context/init/diff/evidence_refs 的独立索引与外存求解）。它们的原始值可完整恢复/逐段浏览，**不能据此宣称完整规范化架构或低内存全局求解已完成**。源码原始字节已使用 gzip 内容寻址对象，完整 Prompt/Packet/响应/技术收据通过审计对象索引保存；全引用回收仍未落地。

`EvidenceProvider` 提供symbol/records/node/text分页、完整根摘要、归档源码引用；`QueryService`统一静态/人工筛选与统计，不把AI完成映射安全。大文本分段游标单位为UTF-8字节，切在完整字符边界；每段有总长/哈希/继续游标。显式 `load()` 只用于兼容/验收，仍可能重建完整Python对象，UI禁止调用它取整库。

发布先完整写临时SQLite、FULL同步、完整性/外键检查，再同目录NTFS硬链接独占发布。现有scan永不覆盖；不支持安全发布的文件系统明确失败。读取连接query_only/trusted_schema关闭。深度校验含类型、逐节点哈希、顺序、重复键、外键与业务投影重建。

## 人工记录

reviews.db独立于静态库。binding绑定scan/project/facts_hash/report_hash。events保存完整不可变事件及revision；predecessors为有向前驱关系，UPDATE/DELETE触发器拒绝改写；positions仅保存可变工作位置。每次保存使用BEGIN IMMEDIATE，核对expected_heads；多头即CONFLICT，显式决定并引用全部分支后解决。确认无风险必须有依据；撤销新增事件，原操作保留。处理状态与判定状态独立。

AI 使用独立的 ai_events（sequence、ordinal、finding_id、state、hash、payload）和 ai_snapshots。每项变化追加事件；水位快照引用截至该 sequence 的每项最新状态，不复制整份队列。ai_finding 索引支持查询，UPDATE/DELETE 触发器禁止改写。GUI 按 SQL 分页读账本；风险清单等派生展示可重建，不将其再复制进每次快照。原始每项结果、历史尝试、最终回答及必要审计对象全部保留。旧人工 schema、旧 AI 快照与新水位 schema 都有精确白名单；未知 SQL/版本拒绝导入。

复核证据导航采用固定数据库的 stdio MCP，仅提供 evidence 只读工具。无任意文件路径、SQL、shell、URL 或写操作；与 GUI 共用 EvidenceProvider。格式修复阶段不启用该工具，原八步提示词与答复合同保留。配置方式依据 [OpenCode MCP 文档](https://docs.opencode.ai/docs/mcp-servers/) 和 [MCP stdio 规范](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/draft/basic/transports/stdio.mdx)；真实联网模型验证仍未执行。

UI本地设备声明在数据根settings/device.json，不跟随结果包迁移，不是认证身份。完整证据指纹保守绑定整份facts/report和canonical ID，因此无关变化也可能要求重查；尚未实现跨扫描自动继承/RECHECK_REQUIRED投影，不会只按变量名继承安全。

## 用户数据与旧格式

唯一解析器仍为WorkspaceResolver；默认 `%LOCALAPPDATA%/ECRAStudio/data`，可用绝对路径环境变量 `ECRA_DATA_ROOT` 或旧custom_dir选择其他盘。项目身份算法不变。GUI配置独立保存在 `projects/<identity>/profiles/*.yaml`，原文/注释/未知字段保留，旧版本另存history；SQLite写锁和revision阻止并发编辑覆盖。

既有resolver复制迁移保留，新增GUI明确选择来源的只读转换，复用同一工程identity，原目录不删除。完整JSON及shared池通过SQLite中间关系流式转入相同权威图；其他旧字节CAS审计保留，包与回收可达性共用既有索引。六项真实Chrome迁移与50,000节点池编码实测见06-legacy-streaming-import.md。两个旧来源合并、巨型历史与缺证据降级Viewer仍未完整验收。不要删除任一原目录。显式tool/project仍存在于旧CLI兼容路径；Studio正式路径校验拒绝它们，H2全工作流尚未关闭。

## 包与导入原子性

`.ecra-report`：ZIP64，manifest.json + 一致SQLite快照scan.db/reviews.db + 可选evidence/SHA256。manifest绑定协议/schema、scan/project、完整根与每个文件大小/SHA。导出用SQLite Backup API，临时归档完整关闭后原子独占发布。

导入先隔离到data/work；拒绝ZIP路径穿越、反斜杠/盘符、重复大小写、链接/设备/加密、超过预算的条目/总大小/压缩比。验证清单、SQLite精确schema（含未知SQL拒绝）、integrity/外键、全部节点/投影及人工事件关系，再在可信schema重建人工事件，最后重命名发布。已有同scan同证据仅事务合并事件；同ID不同证据拒绝，原数据不变。

`.ecra-review-delta`：版本化JSON信封，绑定完整scan证据，含全部必要前驱；事件ID幂等，相同ID不同内容拒绝。未知schema/来源摘要不一致不污染旧记录。源代码与备注只能文本渲染。包能查看归档证据，但不提供无源码重新原生扫描/重新证明能力。
