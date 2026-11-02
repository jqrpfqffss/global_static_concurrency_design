> 后续实包结果见[v17验收](20-portable-v17-acceptance.md)：此处“待重建/运行中”为本阶段封存时的历史状态。

# 2026-11-02 缺证据旧归档与深构建路径阶段

本阶段接续3f7cec8，不代表完整重构完成。运行中的冻结源/原始黄金数据不修改；其他G2工程仍NOT_VERIFIED_USER_DEFERRED。

| 场景 / 门禁 | 实现与实际验证 | 状态 / 证据 |
|---|---|---|
| U21，缺证据降级 | 显式勾选后捕获全部现存原字节；UNVERIFIED导航容器不推导变量/SAFE/AI/人工结论；标准协议独立Viewer往返、重复幂等。已知归属冲突、活动WAL、已有输入哈希不符仍拒绝 | 源码子范围PASS；14项legacy专项11.354s；[Chrome6项](evidence/browser-legacy-degraded-v2.json)、[合同](ui/19-legacy-degraded-viewer-contract.md)、[截图](ui/screenshots/legacy-degraded-ui-v2)。大型双旧数据/新实包待验 |
| U21，完整旧结果保留 | 原完整转换、人工确认/位置/原文件/幂等/坏输入保护真实Chrome6项重验通过 | PASS；[收据](evidence/browser-legacy-full-after-degrade-v1.json)。不将缺证据容器称为完整事实恢复 |
| H2，旧迁移边界 | 原固件即使没有Git/CMake标记，也依据显式固件根拒绝其内部数据根；在第一次创建目录前检查 | 专项PASS，未写入原固件；不代替生产构建写保护沙箱 |
| Portable v16 | 1009文件快照，1280完整回归运行中；目录/中文ZIP解压各27命令通过；11组浏览器子范围通过，预检查第8项实际失败 | FAIL；[构建](evidence/portable-studio-v16-build-v1.json)、[CMake深路径失败](evidence/browser-portable-v16-preflight-failed.json)。包及原失败日志保留，不能发布为门禁通过 |
| U02/G8，深TEMP修复 | 保留实际目录与参数，短Junction根不再跟随过深任务TEMP；验证独立用户根、同一文件、冲突/越界拒绝；43项Portable/预检查/Workspace专项14.175s通过 | 修复源码/实际v16工具集的Chrome8项PASS；[收据](evidence/browser-build-deep-tools-v17-v1.json)、[ADR](18-portable-short-alias-adr.md)、[截图](ui/screenshots/build-preflight-deep-tools-v17-v1)。新包仍须重建 |

深路径复验使用当前源码、宿主Python3.10.11及原v16实际CMake/Ninja/ARM/Clang工具，不冒充新包Python3.10.9已验。该运行的严格跨环境对照facts相同，report因coverage.compilers的Portable审计条目与宿主黄金不同而FAIL，原[失败结果](evidence/build-deep-tools-v17-comparison-different-environment.json)保留；没有扩展规范化规则隐藏差异。之后的同宿主F030真实GUI重扫6项通过，完整facts及规范report均零差异；见[浏览器](evidence/browser-build-same-host-v17-v1.json)和[严格同环境对照](evidence/build-same-host-v17-semantic.json)。未改变比较规则。

上下文实包控制器首轮仍断言“保存后即可扫描”，与新真实构建门禁冲突而失败；仅改为要求未检查时禁用，第二轮8项PASS，[首轮](evidence/browser-portable-v16-contexts-v1-failed.json)/[复验](evidence/browser-portable-v16-contexts-v2.json)均保留。降级Viewer首轮控制器在自有副本删除只读facts.json时被Windows拒绝，在服务启动前失败；第二轮在复制时明确省略该文件，原始文件从未变动，不冒充原工程事实缺失。

已实现的缺证据路径不从旧facts.db猜测类型或顺序；它保留原数据库/JSON/HTML/未知文件原字节，不执行旧schema或脚本。全部缺失项、UNVERIFIED状态、禁用确认/复核同时在API与真实页面验证。只读迁移的完整路径继续保留原逻辑和安全门禁。

下一候选需包含本阶段源码、更新控制器和实际路径修复；前一个v16包不包含缺证据Viewer且有实际CMake失败，不能用其收据证明当前工作树。大型INAV v8的G3 FAIL、G1大型完整对比/全局外存工作集、H2生产写保护/dirty隔离、物理32GB/第二机/DPI/人工UAT等仍未关闭。
