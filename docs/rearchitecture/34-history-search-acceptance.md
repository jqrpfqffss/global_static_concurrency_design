# 历史检索与逐行操作：实现及验收

按[冻结合同](ui/26-history-search-contract.md)在原“历史与对比”页面补齐工程、配置/目标/变体、核心、Git、模式、发布状态及UTC日期检索。只从归档读取身份，不以当前profile补造旧核心/目标。服务端逐条读取小元数据，独立根内临时SQLite主键排序和分页，不汇集全部事实图；列表损坏单条保留诊断，未发布任务不列入有效历史。

逐行打开、继续确认、标准包/确认增量导出绑定该行scan_id；继续确认恢复该归档保存的位置。筛选和页码按数据根保存在标签页，刷新期间等待父页bootstrap完成，防止直达历史时空白。1366下常用检索/分页常驻，完整身份列表独立可聚焦滚动；高级筛选沿用已有折叠方式。

| 验收 | 实际结果 | 证据 |
|---|---|---|
| 专项/API | 7项历史回归+归档身份/API共29项PASS，18.055s；禁全图load、完整包/全人工事件往返、UTC边界/日期缺失、字面检索/注入、损坏/伪清单、归属/鉴权、分页/失效页码 | [29项](evidence/history-focused-v2.json) |
| 首轮测试错误 | 测试夹具误调用不存在的ReviewStore.record，7个setup错误；改用原append，未改生产事件语义 | [原失败](evidence/history-focused-v1-harness-failed.json) |
| 浏览器首轮 | 真实分页/刷新通过；下拉可访问名称含选项文字导致精确定位失败，已补精确aria-label | [原失败](evidence/browser-history-host-v1-failed.json)，trace仍在本地output |
| 实际归档浏览器 | 23份已获准F030真实历史原生扫描，不改scan_id/字段/事件；8项真实Chrome PASS：身份集合、分页重开、组合条件/UTC、空筛选恢复、逐行两类导出/严格导入全事件、继续确认到正确归档、损坏单条、1366布局 | [最终v3](evidence/browser-history-host-v3.json)、[原归档清单](evidence/history-authorized-native-archives-v1.json) |
| 视觉修正 | v2操作8项通过，但全页20个身份条目使分页过远；审查截图后将分页移到列表上方并限定列表滚动，v3重验包含视口内分页及实际滚动断言 | [v2原收据](evidence/browser-history-host-v2.json)、[v3实图](ui/screenshots/history-host-v3/08-history-1366-controls.png) |
| 前端 | TypeScript/Vue类型检查、Vite离线静态构建PASS，无新增依赖；静态九导航/API合同通过 | [静态合同](evidence/history-static-contract-v1.json)，不代替GUI或UAT |
| 全量回归/实包 | 本子阶段尚未进入新Portable；v24为此前aac467f/schema3冻结包，不借其1330结果作为新历史源码全回归 | NOT_VERIFIED |

复现：

    py -3.10 -B -X utf8 -m unittest tests.test_studio_history tests.test_scan_identity tests.test_studio_api -v
    npm.cmd --prefix studio run build
    py -3.10 -B -X utf8 scripts/validate_history_ui.py --archive-list <history-authorized-native-archives-v1.json> --work <新独立目录> --evidence <新截图目录>

输入必须是既有获准的真实已发布扫描，控制器仅复制归档组件及一致人工快照，不重新扫描或写原固件。

边界：跨任意历史批次完整语义对比未实现，不呈现假按钮。已归档Diff方向可检索，正向Diff/核心夹具专项通过不充作真实大型Diff/G1。实际浏览器源清单为23次真实F030扫描，不是G2新增第三类工程。第二物理机、Windows原生DPI、工程师UAT及完整G7仍未完成。
