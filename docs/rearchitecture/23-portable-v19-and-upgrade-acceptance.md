# Portable v19与升级续确认验收（2026-11-02）

本阶段封存运行时`034ecb5604011b319b6d040ba88e4f2160ca5754`的实际候选。完整重构仍未完成，不能据本阶段宣布H1–H6或G1–G8全部通过。v18快速撤销失败、混用工作区测试拒绝、各轮大型失败与未完成产物均保留。

| 阶段 / 场景 | 实际实现及验证 | 状态 / 证据 |
|---|---|---|
| Phase 4/6，确认事务与工程身份 | 1297项冻结回归：1295 PASS、2项真实联网opt-in SKIP，1919.477s；1211源码文件与独立测试副本前后未变 | PASS于该冻结版本，[完整回归](evidence/full-regression-studio-v19.json) |
| Phase 6，实际Portable | 942.547s构建；118运行源文件逐字节匹配，29535分发文件SHA校验；ZIP 567853752字节 | PASS于本机实包，[封存](evidence/portable-studio-v19-seal.json)、[文件校验](evidence/portable-v19-files-verification.json)；不是干净离线电脑验证 |
| Phase 6，目录与中文路径解压 | 两种实际形态各27条CLI：21个exit0及6个预期INCOMPLETE exit2，未将INCOMPLETE报为完整成功 | PASS，[目录](evidence/portable-v19-cli-uncompressed.json)、[中文解压](evidence/portable-v19-cli-zip-extracted.json) |
| Phase 4/5，真实Chrome | preflight16、sample11、main16、legacy-degraded6、profile7、contexts8、directories7、git6、capacity9、coverage8、legacy6、collaboration7、launcher4全部通过；111条有交叠的操作断言，不与单元测试相加宣称覆盖数 | PASS，[13组收据索引](evidence/portable-studio-v19-seal.json)、[截图目录](ui/screenshots/portable-v19) |
| U17，真实写锁与撤销 | reviews.db独立事务持锁时真实POST等待；字段禁用、只读SQL无提前事件；Esc关闭详情后释放锁、提交、重开、撤销，原事件/理由保留 | PASS，[实包16项](evidence/browser-portable-v19-preflight.json)、[撤销截图](ui/screenshots/portable-v19/preflight-07-human-undo-retains-original-event.png) |
| U18，构建及源码变化 | 私有教学副本真实ARM构建Release→Debug并重扫，再修改RMW表达式并重扫；两代旧确认均只作历史，当前RECHECK_REQUIRED可重新确认 | PASS于实测输入，同16项收据；教学例子不是G2要求的独立真实工程，不是目标板安全结论 |
| U16，跨软件升级续批 | v19直接打开v17原数据根，保留原1000事件；再确认1000个不同UNKNOWN，均明确自动化声明NEED_MORE_EVIDENCE；新350/700/1000处真实关闭/重启服务；共2000事件，旧1000逐项不变，静态图全SHA/size/mtime不变 | PASS，[独立收据](evidence/browser-review-upgrade-batch-v19-v1.json)、[1000项后截图](ui/screenshots/review-upgrade-batch-v19-v1/upgrade-batch-1000.png) |
| G7，完整用户场景 | 当前11 PASS、13 NOT_VERIFIED，范围逐项列出。U18新增实包证据，其余缺失不借用局部测试封口 | NOT_CLOSED，[U01–U24逐项表](ui/22-user-scenario-status-v19.md)、[机器表](evidence/user-scenarios-v19.json) |

升级批次耗时2867.813s，包括17.8GB静态图前后全SHA及浏览器/三次重启；保存至UI回读中位1.453s、P95 2.125s、最大4.031s。H/I在同一机械盘且有其他诊断并行，不能归因于单项优化或当作独占性能/UAT指标。此批次直接使用原版真实INAV原生结果的已标记独立字节副本，不产生新版原生结果，不替代G1/G2/G3或标准大包往返。

## 可复现入口与完整性

实际程序：`H:/ECRAStudio-build-20261102-studio-v19/ECRA-Portable/ECRA.cmd`；ZIP：同级`ECRA-Portable.zip`。ZIP SHA-256：`947bc7f20545436b3c671b7e9b436998f4a83d876c757cf9205404b6ba1f072c`。最终端无需Node、系统Python或数据库服务；本机包内依赖实测不等于第二台物理机离线验收。

浏览器控制器位于`scripts/`：`validate_build_preflight_ui.py`、`validate_studio_ui.py`、`validate_builtin_sample.py`、`validate_profile_roundtrip.py`、`validate_context_forms.py`、`validate_directory_browser.py`、`validate_git_selection.py`、`validate_studio_capacity.py`、`validate_studio_coverage.py`、`validate_legacy_ui.py`、`validate_legacy_degraded_ui.py`、`validate_review_collaboration.py`及`validate_portable_startup_ui.py`。本轮从冻结副本执行，以各收据的实际命令为准，失败尝试不覆盖。

```powershell
# 仅开发机全套回归；应先冻结源码与测试副本，不在运行中修改引擎。
py -3.10 -m unittest discover -s tests
# 实包验证控制器：参数与私有测试输入以封存收据为准。
py -3.10 scripts/validate_build_preflight_ui.py --help
py -3.10 scripts/validate_review_upgrade_batch.py --help
```

升级控制器严格要求原测试根恰有已知1000条事件，已完成的2000事件根不得重复运行；它主动拒绝不匹配数据，不能通过清空历史来重跑。新的验收应另建明确授权的测试根并先完成第一批。

## 同输入基准与剩余技术门禁

| 输入 / 运行 | 内存峰值 | 磁盘 / 完整归档 | 时间 / 完整语义差异 | 结论 |
|---|---|---|---|---|
| 同输入F030原/当前宿主 | 本轮不新增内存收益数字 | 新库11317248字节；非大型70%收益证明 | 当前原生34.360s，完整facts及严格规范report差异0；配置原字节、42原文件不变 | 小工程对照PASS，[收据](evidence/review-host-native-exact-v2.json) |
| 原版INAV 388TU | Job29805875200字节 | 原最终目录46427649982字节、57773文件；只读完整备份已校验，不是新标准包 | 12542.188s，原生INCOMPLETE exit2，有效性与覆盖保留 | 黄金基线已保留，详见此前大型记录 |
| 新版v8 INAV冷扫描 | Job17180913664字节，超过16GiB | 失败诊断目录，无有效新归档 | 4810.313s、exit3、MemoryError；不能比较成等价PASS | G3 FAIL，G1大型未验 |
| 24GiB预算的retention-v2诊断 | 已观察Job18449494016字节，超过16GiB | 仍在发布，非最终归档，不以部分DB/目录估收益 | 当前仍RUNNING；严格全图及完整标准包往返等待有效发布和全输入后验 | G3 FAIL；G1大型/G4 NOT_VERIFIED |

外存全局工作集、生产H2写沙箱与dirty完整隔离、图形化数据根搬迁、巨大双旧来源迁移、完整故障注入矩阵仍未完成。另两类G2工程按用户决定待验；物理32GB、第二台物理机/干净离线Windows、原生Windows DPI、真实联网OpenCode及5–8名工程师盲操作UAT均NOT_VERIFIED。没有通过删除历史、缩小覆盖、强制命中失效缓存或降低保护阈值来绕过门禁。
