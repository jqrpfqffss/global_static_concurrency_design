# 冻结 v36：实际验证队列与未关闭项目

2026-11-04。当前实现提交 `176ed696e34354593ff2bc5aa800972a641d152e`，分支 `optimize_ccc`，提交后工作区干净，未推送。v36 是精确冻结的 3050 文件副本，manifest SHA-256 为 `ca27507d93b9bfa527e65a3ee06cf99e63a158fc1297135207b24e14c743dc8d`。这里只记录执行状态，**不是完成收据**：[机器可读观察](evidence/v36-queue-observation-v1.json)。

| 阶段 | 已实现或正在验证的核心功能 | 文件 / 测试 | 当前结果 | 证据 |
|---|---|---|---|---|
| Phase 2/5 | 同输入大型完整语义、完整包及严格导入；最终保留量71.6497%下降 | 不改既有比较器/输入；完整字节和文件分配量 | PASS_SCOPED；完整G4峰值待验 | [65号记录](65-complete-compact-archive-retention.md) |
| Phase 4 | 实际切换TU时的证据请求归属、自动重读、失败重试；长文本失败不显示假“未知” | `EvidenceNode.vue`；真实F0304组、容量/传输11组、UI合同12项、vue-tsc/Vite | PASS_SCOPED，源码已提交 | [66号记录](66-evidence-request-identity-and-retry.md) |
| Phase 6 | 完整回归、精确原版F030原生对照 | 冻结v36；目标1408项、其中2联网opt-in SKIP | NOT_VERIFIED，排在v35回归后执行 | 队列 `full-and-native-v36-v1-queue.json` |
| Phase 6 | 真实Portable、包内Python、目录/中文ZIP两组CLI、全分发SHA、Chrome与实际VHD | 目标22组174个重叠断言；其中包含新的TU请求4组/长文本容量11组 | NOT_VERIFIED，必须等待回归及F030原生通过后构建 | 队列 `v36-build-and-browser-v1-queue.json` |
| Phase 4/6 | 完整大型压缩包在实际v36的main/SysTick、5423边分页、调用见证、未知NVIC与归档源码 | `validate_inav_evidence_ui.py`，目标6组，真实ECRA.cmd入口 | NOT_VERIFIED，排在该包实际封存后 | 队列 `native-inav-evidence-ui-v36-v1-queue.json` |
| Phase 4/6 | 旧3000事件独立副本再新增1000声明、三次真实重启、位置与原事件保持 | `validate_review_fourth_batch.py`；仅版本标签改为v36，合同不变 | NOT_VERIFIED，排在大型GUI验证后；不预先写入人工事件 | 队列 `review-fourth-batch-v36-v1-queue.json` |

外部控制器与队列都在 `H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`，精确路径/SHA见观察收据。控制器等待依赖通过再进入下一步，工作目录全部新建；不会覆盖旧的失败收据、原工程、旧扫描或人工记录。最终成功时才写 `docs/rearchitecture/evidence/portable-studio-v36-seal.json`；不存在该文件或 `passed` 不为真时，不得把队列目标当作通过。

v35/5c21ac3 的完整1408项队列仍在独立执行。它与v36的101份Python运行时及187份测试文件SHA全部相同；差异集中在证据组件/编译网页与验收文档脚本。仍独立执行v36验证，不以字节相同代替新的浏览器和Portable验收。v35原页面已由额外真实F030探针证明有串入旧命令的缺陷，见[明确发布状态](evidence/portable-v35-additional-release-readiness.json)；即使其较早21组通过，也不能称没有已知显示缺陷。

构建成功后的目标入口是 `H:/ECRAStudio-build-20261104-studio-v36/ECRA-Portable/ECRA.cmd`，**尚未存在完成收据，当前不交付为已验Portable**。当前源码入口为仓库 `ECRA.cmd`，其开发模式使用已安装Python，不能冒充包内Python离线验收。真实源码截图见[66号记录](66-evidence-request-identity-and-retry.md)。

独立的writer64MiB冷原生v13绑定旧冻结49960e，新512MiB完整只读比较绑定5bcfa01，两者仍未结束，不能重标为v36原生结果或声称提速。当前已完成的大型全字段对照仍只绑定e69/1493c05。

仍需实际实现/关闭的项目包括：生产强写隔离，正式dirty字节快照及真实构建等价，全数据根搬迁，不变完整证据证明后的确认继承，大型Diff/全局外存与完整消费者恢复，多核普通用户向导，断电/WAL/迁移中断等完整故障矩阵。其他G2工程按用户决定待验，物理32GB/第二台PC/干净离线/Windows原生DPI、真实联网OpenCode、5–8名工程师UAT继续NOT_VERIFIED。完整Phase/H/G门禁均未宣称全部完成。
