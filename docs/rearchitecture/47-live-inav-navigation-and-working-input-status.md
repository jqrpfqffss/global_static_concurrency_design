# 真实INAV证据分页与未提交输入配置门禁

2026-11-03；延续optimize_ccc，实施前HEAD f747643，v1查询修复另提交cfe1a88。此轮不修改提取、求解、风险分类或G1规范化方法，不改正在运行的冻结v27原生扫描/原版备份。最新已封存、可运行的完整分发仍是[v27](46-frozen-v27-acceptance.md)，不能把下述源码修复记成它已经包含的内容。

## 已复现并修复的真实分页错误

使用获准INAV原版完整比较图的独立副本，原facts根9da30821…、17,831,825,408字节，既有3000个人工事件。选择真实canonical变量`tu::src/main/drivers/time.c::c:time.c@sysTickUptime`，实际main/SysTick入口和READ/RMW均来自原图，不构造目标板行为或新调用边。

原ConflictPairs.load先发布新page.offset，再逐个请求本页证据，最后才替换rows；请求期间会把新关系序号显示在旧证据上。实际v27浏览器失败及trace保留。修复只在本页所有请求成功后同时发布rows/page；失败保留上一页，并清除重试前的旧错误。没有删减关系、改变页大小或隐藏未知条件。

`scripts/validate_inav_evidence_ui.py`通过实际ECRA.cmd或显式源码解释器启动真实服务/Chrome。标准原生包模式要求ECRA_REPORT及import_origin；原版比较图必须显式选择诊断模式，不能代替新版原生包。测试保持一个真实下一页请求未完成，核对旧页码与旧证据仍对应，再释放原请求；不伪造API内容。全部113组冲突逐页展开引用；访问函数双向直接调用逐页核对ordinal/定义；完整相关slice边由测试自己的SQLite账本核对，没有把全facts装进浏览器。

| 实测轮次 | 状态与边界 | 证据 |
|---|---|---|
| v27诊断v1 | FAIL：测试填搜索词后漏提交，50行未筛选；截图确认后只修测试 | [原失败](evidence/browser-inav-navigation-v27-v1-failed.json) |
| v27诊断v2 | FAIL：真实分页序号/证据切换时序问题，1组已过，不能记完整通过 | [原失败](evidence/browser-inav-navigation-v27-v2-failed.json) |
| 源码诊断v3 | FAIL：前三组通过，113关系、5423相关边/1486API页、最大响应95349B；随后测试局部变量覆盖main路径，未完成全套 | [原失败](evidence/browser-inav-navigation-source-v3-failed.json) |
| 源码诊断v4 | FAIL：前5组通过；旧比较图按格式只编码facts/report，未归档源码。第6组错误地要求该图含源码文本，界面实际正确显示缺失；不补造或读取现场源码 | [原失败](evidence/browser-inav-navigation-source-v4-failed.json) |
| 源码诊断v5 | **6组PASS**，113关系/全部5423相关边、1486页API、95349B最大响应；17.8GB全静态SHA前后660dffb2…一致、3000个人工事件不变。第6组实际验证缺源码提示；不声称该图拥有归档文本 | [收据及截图摘要](evidence/browser-inav-navigation-source-v5.json) |
| 新原生结果包/新Portable | NOT_VERIFIED；须先完成同seed完整G1、标准包导出/严格导入，再在实际新包重复；不得借原版图诊断关闭门禁 | 原生v12比较/包队列及后续冻结版本 |

原始路径均位于`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`。v5已结束并核对静态全文件SHA、人工事件数；main路径是归档已存在的main→scheduler→micros证据witness，不冒充枚举全部可能路径，完整相关边仍独立遍历。直接上游按实际函数分别231/0/6/76条，下游分别0/3/2/2条，各页/调用位置/原始引用逐项核对。目标板实测、物理第二台电脑、Windows系统DPI、工程师UAT均未验证。

实际截图：[main证据路径](ui/screenshots/continuation-20261103/inav-original-evidence-ui-source-v5-04-real-main-witness-not-all-path-enumeration.png)、[真实请求未完成时页码与证据保持对应](ui/screenshots/continuation-20261103/inav-original-evidence-ui-source-v5-02a-page-label-and-evidence-stay-atomic-during-real-pending-request.png)、[原版比较图明确显示无源码](ui/screenshots/continuation-20261103/inav-original-evidence-ui-source-v5-06-diagnostic-graph-honestly-declares-source-unavailable.png)。源码诊断不是新Portable验收；当前v27封存的U01–U24统计不因此改写。

## 未提交输入：编辑/预览可验，正式扫描仍阻断

审查确认`ecra/workspace.py:formal_workspace`仍明确拒绝include_uncommitted=true。`working_snapshot.py`是字节/索引捕获原型，尚未接入生产编译/扫描链路。不可删除这一阻断后就宣称完成H2或U04，也不能将VFS/宏的小工程单测冒充生产全模式验证。

当前沿冻结向导第3步的Git版本区域显示该选项，提供实际布尔值无损读取/同步、HEAD限制、真实版本/dirty计数预览和明确生产阻断文案。选择true不能保存成可启动配置；检查配置返回原正式门禁错误。用户可取消选项，恢复固定提交模式并正常保存；返回/重开不丢选项原值。不自动切换分支、提交或修改固件/.git。API明确返回formal_scan_allowed=false及阻断原因；此字段只描述未提交输入门禁，不表示其他配置/工具检查已经通过。

| 范围 | 实际结果 | 证据 |
|---|---|---|
| 表单/Git/API/上下文联合专项 | 37PASS，0SKIP，23.464s；新增严格布尔类型、缺省不补字段、完整注释/未知字段保留、HEAD限制及真实认证API | [收据](evidence/git-working-input-form-focused-v3.json) |
| 第一次专项命令 | 误写不存在的test_studio_context_forms模块，30项/1导入错误；保留原失败，改为真实test_context_forms后重跑 | [原命令失败](evidence/git-working-input-form-focused-v1-failed.json) |
| 前端 | vue-tsc与Vite实际构建通过；未改变冻结导航/线框结构 | [构建](evidence/git-working-input-frontend-build-v3.json) |
| Chrome首轮 | FAIL：前端和后端同一HEAD错误重复显示，使严格定位命中2条；已去重显示，原失败截图保留 | [原失败](evidence/browser-git-working-input-host-v1-failed.json) |
| Chrome修复后 | 8组PASS；真实勾选/HEAD限制/完整YAML同步/正式门禁拒绝/旧profile不变/取消后保存并重开；原42个固件文件及fixture全部文件/mtime不变 | [收据](evidence/browser-git-working-input-host-v2.json) |
| include_uncommitted=true正式原生扫描 | **FAIL／生产接入未实现，继续阻断**。本轮未启动该模式原生扫描，不能把配置预览称为已捕获和分析了未提交字节 | `ecra/workspace.py`保留正式门禁 |

新版本完整回归和Portable验收须包含本轮源码；v28完整1371项已结束为1368PASS/1FAIL/2SKIP，不包含cfe1a88及本轮新增4项，另见[失败及计数修复](48-regression-accounting-and-sparse-fixture.md)。未启动的v28构建/新原生GUI队列已核对PID、创建时间、命令及仅conhost后代后取消，原状态全文备份；没有中断v28回归、原生v12或原版备份，没有删除旧产物。

2026-11-03后续：冻结700befd/v29完整**1379项1377PASS/2联网SKIP**、1923.089s，2229个冻结文件及独立测试副本全部SHA不变，[完整收据](evidence/full-regression-studio-v29.json)。它不包含之后的原生下载和下段复选框修复，不能当最新全部代码完整回归。

随后审查补齐“高级YAML关闭Diff但include_uncommitted=true”状态：允许取消已经为true的选项，避免无base_ref时连清除也禁用；显示当前Diff未启用/应取消的具体原因，生产门禁继续不变。实际Chrome**9组PASS**，包含高级值保留、取消、所有其他字段/注释不变及原已保存profile不被覆盖，[收据](evidence/browser-git-disabled-option-host-v1.json)。不因此宣称未提交原生扫描已接入；后续完整套件预计1383项。
