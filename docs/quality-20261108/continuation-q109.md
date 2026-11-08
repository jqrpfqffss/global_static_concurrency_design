# Q109：嵌套容器被误计为未知和人工待办

## 真实复现及根因

本轮真实 F411 完整构建后的 CDB46，经真实链接闭包过滤24C，使用冻结 `8393edcd…` 全量扫描，保留原归档 `H:/ECRA-quality-20261108/continuation-final-projects/f411-data/scans/final-v2-f411`。报告显式分类123个存储对象，未知4；原界面未知8、待人工42。

额外四项为 `g_cli.command_list`、`command_list[*]`、`history`、`history_stash`，均是 `STRUCT_MEMBER_CONTAINER`。独立叶对象已经分别分析；command_list三个叶子为2 SAFE/1 SUSPECT，history[*]、history_stash[*]/[0]为SUSPECT，候选和继承访问仍在。四项容器没有独立finding，也不应重复计入风险分母。

这不是遗漏叶存储分析或补充声明：`analysis.py`按既有契约排除嵌套容器，却只给根结构体和数组容器汇总显式CONTAINER标签。旧SQLite物化索引对缺标签项使用UNKNOWN，当前查询又把它当独立未知加入待办。产品方案8.3已经要求父对象不重复计数，故不能仅用“保守”解释为通过。详尽对象、类型、访问、上下文、叶候选ID及统计证据见 `output/quality-20261108/continuation/final-projects/f411-nested-container-diagnosis.json`。

## 独立候选中的修复

候选位于 `H:/ECRA-quality-20261108/continuation-q109-candidate`，基于只读v2，原冻结源、原归档、便携目录和ZIP均未修改。

- `analysis.py`：嵌套容器与根容器一样得到明确CONTAINER汇总；通过同一 `root_symbol_id` 与规范字段路径的 `.`/`[` 子关系选择真实已分析叶子，保存其 `member_symbol_ids`。不会把 `history_stash` 等相似名称当作history子成员，不改变叶分类或复核分母。
- `scan_store.py`：保留原 `_project` 物化和deep.validate重建合同。只在读取旧归档时，对“权威facts缺少显式分类键、权威resource_kind为确证str节点并与容器索引一致、原索引为UNKNOWN默认值”的行派生CONTAINER，计数与静态筛选共用同一表达式。原库不写入，显式UNKNOWN/SUSPECT及仅篡改索引kind的行不被派生覆盖；deep仍拒绝损坏索引。
- `studio/current_results.py`：共用只读派生，列表、当前结论、待办及概览一致；保留 `raw_static_classification` 和 `static_classification_derived` 来源，汇总返回 `derived_static_classification_count`。人工记录和AI账本继续独立保存。
- `html_report.py`：新嵌套容器按已证实成员ID显示子叶；旧facts缺该列表时按原根/字段关系派生表格，不改原facts。修正成员安全计数读取 `safe_proven`，保留旧 `safe` 格式兼容。

新facts显式CONTAINER的来源标志为0；旧归档的派生为1。协调者在独立UI候选中同步来源文案和真实操作验证，另记其证据，不能把此代码检查代替浏览器验收。

## 回归及原件兼容性

新增 `tests/test_nested_container_projection.py` 包含七项针对性检查：真实Clang嵌套结构体已知叶冲突、结构体数组容器归账、多维数组保守边界、旧库查询/导出/导入/历史保留、schema1深校验、损坏分类索引和显式风险不被覆盖、索引kind不能伪造权威容器身份。HTML还覆盖非字符串、重复和无关成员ID的明确拒绝。根review收紧后的联合45项通过，24.229秒，记录 `output/quality-20261108/continuation/q109/combined-v2.log`；此前44项通过的日志保留。

原F411实际归档完整deep校验、完整结果包导出、导入和再deep校验已通过。收紧后的最终复验67.969秒，记录 `real-f411-compat-v2.json`；前轮73.516秒收据也保留。原scan.db/reviews.db/manifest三个文件前后逐SHA不变；导入DB逐字节等于完整包内scan.db，facts/report根hash相同。只有四个嵌套容器的读取视图派生CONTAINER，当前41容器、4未知、38待人工；静态84安全/1共享筛除/34疑似以及全部原叶风险保留。完整导入目录 `H:/ECRA-quality-20261108/continuation-q109-real-f411-v2/imported-data/scans/final-v2-f411` 可供协调者真实UI复验。

正式冻结后还须使用最终组合引擎针对真实F411重新扫描，旧839结果作为缺陷与原构建证据保留，不能冒充修复后全量结果。

最后生产修改后，另跑原分类已知答案、结构体调用路径、HTML与完整证据57项，15.488秒全部通过，见 `analysis-html-adjacent-v2.log`。最终冻结的4个生产文件、测试及来源SHA列于 `candidate-frozen.json`；两组45+57项是102个相关方法，不是整项目suite声明。三工程中的CDC也以原静态SHA不变实证相同读取修复：20个旧嵌套容器派生后，未知90→70、待人工225→205，原5SAFE/135SUSPECT及全部叶风险不变，见 `real-cdc-read-only-projection.json`。

## 保留的失败及边界

没有删除难例或根据修复结果回写预期。初轮 `targeted-v1.log`、`targeted-v2.log` 两个断言失败，独立原因如下；v3另有调用HTML底层函数前未建立输出目录的测试控制器错误，记录保留。v4完成6项通过。

1. 首个混合fixture把多维 `history[0][0]` 与未访问叶子放在同一根。当前未物化该多维路径时会保守按整根访问继承，未访问叶也受影响，不能独立要求SAFE。已保存原诊断 `nested-fixture-readonly-diagnostic.json`，并保留独立边界回归，明确影响范围扩大；没有修改该边界算法或放宽风险要求。精确嵌套结构体的已知答案改用独立fixture，避免将另一能力边界错误混作Q109预期。
2. SQLite一致快照使用官方backup API，页头change-counter可能与原库不同，初版把“原库物理字节等于导入库”当作合同是错误。正确核对原库字节完全不变、导入库逐字节等于包内scan.db、facts/report根hash与完整证据值不变。没有放宽证据相等要求。

v1还因测试文件直接导入TestCase触发额外原ProjectTest，共46项；其原日志完整保留，但不把这次开发中运行算作冻结后的整套验收。最终联合回归和真实旧归档验收使用单独命令及新日志。

## 协调者实际界面与兼容入口复验

用原v2 F411的完整自有数据副本 `continuation-q109-ui-data`，先在旧v2后端真实Chrome复现8未知/42待办及父容器可填写人工确认。换成组合v3后端与生产网页`index-DtkBozpG.js`，未改扫描静态库：实际概览4未知/38待办、41容器/34疑似/84安全，明确注明4项为按归档类型派生；未知筛选只剩tx_buf[*]/active_buffer/pending_tx/printf_buffers[*]，没有将它们判安全。

实际搜索g_cli.command_list：父容器和其数组容器均无需人工确认，说明“归档未记录本项静态分类，按已保存对象类型显示”；3成员仍为1疑似/2安全，点击疑似name成员保留42组并发关系、16处访问和人工入口。1366×768及1920×1080视口截图均实际查看；浏览器/OS缩放未验证。未签署真实工程测试结论，人工风险事件仍0。

在该副本记录manifest精确备份后故意写[]，实际刷新显示明确失败面板而无空白；将这个故障文件从已记录备份恢复、点击真实“重试读取”，搜索条件保留、5项结果/风险入口恢复。这不是恢复注入人工/AI/任务状态。静态库SHA与原件一致，manifest恢复后与原件逐字节一致，证据`q109-final-ui-receipt.json`、`q109-final-ui-*.txt`及截图。已关闭测试浏览器和核对归属的服务，`q109-closed.json`。

用正式CLI `--legacy-output --no-review --scan-mode full run` 对真实F411编译/链接输入生成兼容HTML，284.921秒退出2、INCOMPLETE保留，`q109-actual-legacy-matched-cli.json/log`。首次控制器误指向另一份便携副本，与CDB真实编译器物理路径不符，产品按既有外部工具约束明确拒绝；失败原日志保留，仅更正控制器运行根，不打开allow_external_toolchain、不改CDB/编译参数/产品代码。生成HTML后的file://打开被浏览器工具明确阻止，`q109-legacy-file-ui-blocked.json`；没有HTTP替代或其它绕过，因此本轮兼容HTML视觉仍环境阻塞。

上述v3实际流程是Q109范围证据。之后确认的严重Q205仍需修复，不能由本节宣称最终引擎/完整交付通过。
