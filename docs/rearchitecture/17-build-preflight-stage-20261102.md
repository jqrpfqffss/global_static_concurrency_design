# 2026-11-02 真实构建门禁阶段

起始HEAD aa4ea0a（optimize_ccc），工作区干净；该HEAD已按用户上一轮要求推送。本轮继续实现，不重置、覆盖原固件或改动冻结运行的引擎。完整重构仍未完成。

| 阶段 | 实现 | 实际验证 | 状态 / 证据 |
|---|---|---|---|
| Phase4 / U02 | 四步向导保存配置后执行真实构建检查；显示目标/变体、工具、独立路径、全部TU原始/Clang参数及分页；通过才启用向导扫描 | 真实Chrome：F030数据库4TU、缺失编译器阻断/修复/原生发布；真实ARM教学CMake目标Release、缺失Toolchain阻断/表单修复/2个ARM ELF对象，8项通过 | 所列源码路径PASS；[浏览器收据](evidence/browser-build-preflight-v3.json)、[截图](ui/screenshots/build-preflight-v3)、[实施前合同](ui/18-build-preflight-contract.md) |
| Phase4 / U05 | 正式任务在事实提取前复用WorkspaceResolver/prepare/dependency_results/InputSnapshot；工具与全部真实编译输入不通过不得进入扫描；OpenCode独立 | 8项专项通过（8.453s），含实际CMake/ARM构建、缺编译器/宏、计划损坏、worker阻断、离线Git路径及允许保存不可运行草稿；31项已有API/资源/原生回归通过（118.925s） | 已验子范围PASS；CMake/Ninja/Git实际缺失的全部GUI组合及当前Portable复验仍NOT_VERIFIED |
| H1 / G1，小工程 | 原算法未改；GUI原生结果对照原版黄金完整图 | facts及规范report全字段/类型/顺序/关系零差异；42固件文件、原配置/编译数据库SHA/mtime未变 | PASS（仅同输入F030）；[对照](evidence/build-preflight-f030-semantic-v2.json) |
| 先前完整回归 | 4b3c406冻结982文件 | 1272项：1270PASS/2联网opt-in SKIP，2347.971s，两份982文件SHA不变 | PASS（不包含本轮新代码）；[收据](evidence/full-regression-acceptance-4b3.json) |
| 大型黄金基准 | 原版完整9GB JSON直接有序/类型摘要与深校验比较图独立核对 | 7227.406s，Job37,097,472B；原JSON/图不变，facts/rawreport/规范report摘要全相同 | 比较基准PASS，非新引擎G1；[收据](evidence/inav-original-json-hash-v2-complete.json) |
| G3，INAV v8 | 388TU冷扫描，ADR013完整祖先闭包 | 4810.313s，退出3，analysis_valid=false；Job17,180,913,664B，classification开始private12,042,674,176B；祖先found.add处分配失败 | FAIL；[失败/栈/4123输入及890引擎后验](evidence/inav-ancestors-native-v8-failed.json)。后续完整比较/导出未执行 |

前端类型检查和离线构建通过，静态UI合同12项通过；它们不替代浏览器或人工UAT。第一次浏览器预检查实际在重试时失败：旧轮询返回覆盖新任务身份，导致已成功检查的按钮仍被禁用；已加入轮次及任务身份校验，第二次6项、第三次含CMake的8项均通过。原失败收据/trace保留，不将其改成PASS。

原先“只检查路径”的API继续用于草稿校验，明确ready_for_scan=false；它不授予真实构建许可。TaskManager新增precheck模式，使用相同受监督进程和预算；检查输出全部在work，不能冒充已发布scan。首页/任务中心实际扫描也先检查，失败只留诊断，旧快照/人工历史保留。离线Git查找与已有原生Git相同tools/git/cmd/git.exe，不依赖宿主PATH。实际扫描仍执行原有构建、输入快照、覆盖与发布门禁。

INAV另启动只读测量包装下的24GiB分类诊断，原冻结引擎不改；显式复制并核验旧TU缓存，不承诺命中，实际命中以后验为准。它不是16GiB达标实验或冷耗时对比。首轮包装器字符串换行转义错误，在引擎导入前SyntaxError，已保留[失败](evidence/inav-classification-retention-v1-not-started.json)并修复为raw代码串、增加实际worker编译校验；第二轮仍在运行。完整原版图的只读[列表计数](evidence/inav-evidence-retention-v1.json)只辅助诊断，不能推算原生内存收益。

当前可启动且有完整实包收据的仍为v15：H:/ECRAStudio-build-20261102-studio-v15/ECRA-Portable/ECRA.cmd。它不含本轮真实构建门禁；新包/新冻结全套尚待执行，不能用v15的实包PASS证明新代码。U05完整组合、U21缺证据降级、全局外存工作集/H2生产写保护/dirty隔离、大型Diff/G1/G3/G4、物理32GB/第二物理机/DPI/人工UAT等仍未完成；G2其余工程继续NOT_VERIFIED_USER_DEFERRED。
