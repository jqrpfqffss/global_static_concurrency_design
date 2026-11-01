# 需求追踪与阶段门禁

状态只能由实际运行收据更新。初始审计不构成功能验收；全部场景的详细预期以原任务书为准。

| 约束 | 实现/保护边界 | 验证 | 当前状态 |
|---|---|---|---|
| H1 | 分析算法保护区不修改；完整有序、类型敏感的证据持久化 | 黄金输入全字段往返/旧新对照，非分类计数比较 | NOT_VERIFIED |
| H2 | 复用 WorkspaceResolver；独立数据根；拒绝正式 project 输出 | 路径、链接、dirty 快照、只读固件验证 | NOT_VERIFIED |
| H3 | 全消费者迁移后停写旧格式 | legacy-consumers 清单逐项回归；最终产物白名单 | FAIL |
| H4 | reviews.db 不可变事件、独立处理字段、冲突 DAG | 重开/撤销/重复导入/离线冲突/指纹变化 | FAIL |
| H5 | 冻结九导航、四核心页面、中文三维结论 | 真实浏览器操作 + 数据库断言 + 截图 | FAIL |
| H6 | 归档完整性、只回收不可达对象、原子导入 | 恶意包/损坏/引用检查/失败回滚 | NOT_VERIFIED |

| 场景 | 自动化验收目标 | 当前状态 |
|---|---|---|
| U01 | 首次工程/导入/示例，下一步明确 | FAIL |
| U02 | 四步向导前后不丢输入、真实参数门禁 | FAIL |
| U03 | 只读目录原生扫描与输入不变 | NOT_VERIFIED |
| U04 | 真实 base/current/HEAD/dirty 输入 | FAIL |
| U05 | 缺工具路径诊断、无污染 | NOT_VERIFIED |
| U06 | 首次及再次相同 profile 扫描 | FAIL |
| U07 | 大项目阶段/TU/RAM/磁盘真实计数 | FAIL |
| U08 | 停止/重启/有效旧归档/已提交 TU | FAIL |
| U09 | 四卡统计与查询同口径 | NOT_VERIFIED |
| U10 | 20000 行服务端分页/筛选/排序 | PARTIAL（20007行真实浏览器九项含排序/重开通过；原生大工程容量仍未验） |
| U11 | 真实 g_mfcInterface.msgSp 存储与交错 | NOT_VERIFIED |
| U12 | 完整调用边分段遍历 | PARTIAL（真实F030双向树通过，大工程未验） |
| U13 | NVIC/PRIMASK/BASEPRI 真实未知与证明 | NOT_VERIFIED |
| U14 | 失败 TU 与覆盖缺口下钻 | NOT_VERIFIED |
| U15 | 可选 AI/失败/重试与静态正交 | FAIL |
| U16 | 1000 项分批确认/重启/继续位置 | NOT_VERIFIED |
| U17 | 撤销新增事件保留原理由 | NOT_VERIFIED |
| U18 | 完整证据变化须重新确认 | PARTIAL（原生变更/离线历史保留通过） |
| U19 | 无源码第二电脑完整包继续确认 | NOT_VERIFIED |
| U20 | 增量幂等与并行决定显式冲突 | PARTIAL（两个独立数据根/真实Chrome七项通过，物理双机未验） |
| U21 | 两种旧目录流式无损/归属/降级 | PARTIAL（六项真实Chrome迁移；巨型/双来源/缺证据降级未通过） |
| U22 | 三分辨率/四 DPI/键盘/长中文 | NOT_VERIFIED |
| U23 | 50GB 真实占用/引用回收/恢复 | PARTIAL（50GiB实盘容量与UI闭环通过；非原生项目收益） |
| U24 | 恶意/损坏包隔离与可恢复错误 | PASS（已覆盖的恶意/损坏包集合） |

| 技术门禁 | 必需证据 | 当前状态 |
|---|---|---|
| G1 | 同输入、全字段全关系与 Diff 逐项一致 | NOT_VERIFIED |
| G2 | INAV 388 TU + TMFC/H747 或等价 + DMA/回调/RTOS 真工程 | NOT_VERIFIED |
| G3 | 32GB Windows 12/16GB 资源实测 | NOT_VERIFIED |
| G4 | 同引擎输入前后磁盘峰值/最终大小、至少70% | NOT_VERIFIED |
| G5 | 完整故障注入矩阵、旧归档不污染 | NOT_VERIFIED |
| G6 | 外键/哈希/包/事件/Viewer 一致 | NOT_VERIFIED |
| G7 | U01–U24 浏览器/数据库/截图 | FAIL |
| G8 | Windows x64 干净机离线 Portable | NOT_VERIFIED |

Phase 0–6 在各自完整门禁通过前保持 BLOCKED/进行中。允许独立模块继续开发，不以模块单测 PASS 替代整阶段 PASS。人工盲测及目标板硬件试验单独记录。

## 实际测试与未覆盖部分

| 场景 | 实际实现/测试证据 | 尚未覆盖的完整验收 |
|---|---|---|
| U01/U02 | `validate_studio_ui.py: preview_empty_next_step / preview_four_step_profile_save_retains_input`；配置原文落盘 | 示例、文件夹选择和完整核心配置表单未齐；已接入真实构建/原生扫描，不标全场景PASS |
| U03/U04/U05 | `test_studio_workspace`正式路径阻断，原`test_workspace`隔离/归属/输入安全回归；profile路径检查 | 只读挂载原生大工程、真实refs下拉、缺工具完整UI诊断 |
| U06/U07/U08 | `test_bounded_extraction`提交上界/顺序/崩溃；无假进度或假扫描按钮 | 已接入真实扫描/资源/停止与TU缓存恢复，原生4TU浏览器通过；大工程与完整故障矩阵未验 |
| U09 | 浏览器`preview_static_card_matches_sql_filter`；`test_studio_api.test_pagination_count_and_decision_commit_survive_reopening` | 全部卡片/口径/组合过滤仍需UI逐项验收 |
| U10 | `test_scan_store.test_twenty_thousand_symbols_use_bounded_pages`，20007个对象 | 20007行显式容量夹具真实Chrome已测，最大响应16,656B；排序/全部组合和真实大型结果未全验 |
| U11/U12/U13/U14 | `preview_archived_source_text`；全关系/字段按需节点与调用边API，原分析回归 | 真实F030双向调用树及行号源码已测；真g_mfcInterface.msgSp、NVIC/失败TU专业下钻尚未全验 |
| U15 | 旧复核合同/失败重试原测试保留，AI未启用仍可查看静态归档 | 已接入GUI独立复核任务；真实缺工具13项TECH_FAILED且静态SHA不变通过，未运行联网模型/全重试矩阵 |
| U16 | 浏览器`preview_decision_commit_reopen_and_position`；`test_human_reviews.test_thousand_partial_decisions_are_transactional_and_persist` | 1000项完整浏览器分批确认未测 |
| U17 | 浏览器`preview_undo_preserves_history`；不可变事件/原理由数据库断言 | 两种误确认的全部键盘/撤销组合未全验 |
| U18 | `test_scan_store.test_new_evidence_changes_fingerprint_even_with_same_name`；证据变化不会套用旧事件 | 同profile原生变更后RECHECK_REQUIRED、全部旧事件/来源保留及离线包已测；精确不变证据继承仍偏保守 |
| U19 | 包内Python3.10.9真实Chrome归档/源码/确认；`test_report_package`三隔离目录导出导入继续 | 物理第二电脑/原固件确实不存在的干净机尚未测 |
| U20 | `test_human_reviews.test_two_devices_idempotence_conflict_and_explicit_resolution`；`browser-collaboration-v3.json`七项双origin真实GUI与事件前驱/静态SHA断言 | 两独立数据根完整GUI已验；物理双电脑、多人盲测未验 |
| U21 | `test_legacy_import`、`test_streamed_evidence`；原生4TU旧输出差异0；`validate_legacy_ui.py`六项真实操作；50,000 shared池完整根比较 | GUI只读转换已接通；巨型/双旧来源合并及缺证据专用降级Viewer仍未完成，详见06-legacy-streaming-import.md |
| U22 | 1366/1600/1920真实Chrome截图、Ctrl+F；固定人工区 | Windows系统125/150/200%DPI、全键盘与全部页面状态未全验 |
| U23 | 实际目录占用采样，临时目录消失容错专项 | 真实50GiB缓存释放53,687,025,664B，原归档不变；GUI预览/隔离/恢复/二次确认释放通过。不是原生G3/G4 |
| U24 | `test_report_package`恶意路径/大小写/符号链接/预算/schema/SQL/哈希拒绝；浏览器`preview_malicious_package_preserves_prior_scan` | 完整故障注入矩阵仍属于未通过的G5，不以本集合PASS替代 |

证据入口：`evidence/final-tests.json`、`evidence/native-equivalence.json`、`evidence/golden-roundtrip.json`、`evidence/browser-portable.json`、`evidence/portable-result.json`。本轮所有完整Phase继续BLOCKED；U24的已覆盖集合PASS不代表H6/G5/G6全部通过。

2026-11-01续轮收据：`evidence/native-canonical-v3.json`、`evidence/gc-capacity-50gib.json`、`evidence/browser-canonical-v3.json`。完整实现进度以04-canonical-pipeline-progress.md为准；早期“未接入”状态已由此续轮更正，未覆盖的门禁保持FAIL/NOT_VERIFIED。

U14续轮：CoverageService/真实覆盖页已接通。17项专项与8项F030浏览器操作验证2PARSED/2PARTIAL/236条缺口、完整关联证明、精确身份下钻、分页/重开、零关联TU、原始编译命令/归档源码和静态SHA不变；见browser-coverage-v4.json、ui/07-coverage-contract.md。该范围不代替所有UNKNOWN/失败原因及大工程场景，U14保持PARTIAL。

U06续轮：向导保存后直接开始、首页按相同project/profile当前保存版本重扫、真实任务ID定位已接通。browser-repeat-v1.json的15项真实操作通过，包含停止恢复、缺工具复核和第二次独立原生扫描，原归档/人工/固件.git不变；高级YAML修改后启动禁用。仅4TU与当前保存版本，未解决表单修改回写高级YAML、全部构建模式与大工程门禁。见ui/08-repeat-scan-contract.md。

U02配置同步续轮已解决上述“表单修改回写高级YAML”缺陷：profile_forms受控round-trip、原文哈希备份与恢复、原始类型/引用拓扑检查、仅更新实际改动字段；17项专项及7项真实Chrome通过。详见profile-roundtrip-regression-v1.json、browser-profile-roundtrip-v2.json、ui/10-profile-roundtrip-contract.md。配置修改或恢复后必须重新检查保存，重新打开已保存配置可直接启动。内置常见上下文表单/目录树/真实Git分支下拉等仍未齐，U02保持PARTIAL，不能标全场景PASS；G7仍未通过。
