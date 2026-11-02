# v25实包：历史检索与GUI启动目录；大型门禁仍失败

2026-11-03（北京时间）。运行时dca72be3114126608896b9b8c5397faa9fe4e49e；后续验证缓存与hash seed改动不在本包内。完整重构未完成。

| 项目 | 实际结果 | 证据 |
|---|---|---|
| 完整回归 | 1351项，1349PASS/2联网SKIP，1939.639s；1856冻结文件与独立测试副本后验无差异 | [完整收据](evidence/full-regression-studio-v25.json) |
| 实际分发 | 30157文件完整SHA；123运行时源码匹配；目录和中文ZIP解包各27CLI，21exit0/6预期INCOMPLETE2 | [封存](evidence/portable-studio-v25-seal.json) |
| ZIP | 626219593 B，SHA256 5e2398ba402c2ce24c46a66c11656b761823686ec173f3e6e2c52eb1552a62fd | [构建](evidence/portable-studio-v25-build-v1.json) |
| 原13组Chrome | 112个重叠断言，预检查/示例/主流程/缺证据旧件/配置/上下文/目录/Git/容量/覆盖/旧迁移/协作/启动器全部通过 | 逐组收据与[实际截图](ui/screenshots/portable-v25) |
| 新增3组 | 历史8、数据目录6、实际进程崩溃恢复5全部通过；合计16组131个重叠断言 | [历史](evidence/browser-portable-v25-history.json)、[目录](evidence/browser-portable-v25-data-root.json)、[崩溃](evidence/browser-portable-v25-crash-recovery.json) |
| 首轮控制错误 | 剩余9组控制器指向20261102而实际包为20261103，全部在启动前失败；在新-r2目录重跑9组全部通过，不改写原失败 | [保留原失败](evidence/browser-portable-v25-remaining-suite-v1-harness-failed.json) |
| U16 | 本包未重新执行1000项批次；v23已有第三批实测仍独立保留，不借为v25运行证明 | [本包逐项状态](ui/28-user-scenario-status-v25.md)：11PASS/13NOT_VERIFIED |

入口为H:/ECRAStudio-build-20261103-studio-v25/ECRA-Portable/ECRA.cmd。普通用户可在“历史与对比”检索并按行继续确认/导出，在设置中选择下次启动数据根；完整根搬迁未实现。

**后续大型差异勘误**：已完成的冷INAV/c311仍有G1差异，不能用本包小工程/GUI通过代替大型语义通过。第一差异为facts.accesses[43096].symbol_id，相关三条记录在该局部窗口发生轮换；全facts还有unknowns/snapshots/points_to_stats/context_insensitive_pointer_model/multi_field_coherence共六个顶层字段摘要不同。16566个符号的静态分类查询投影逐ID对照差异0，只是一个诊断，不能据此关闭G1。[第一差异](evidence/inav-cold-v10-first-mismatch-diagnostic-v1.json)、[局部完整节点摘要及全部顶层字段](evidence/inav-cold-v10-root-window-diagnostic-v1.json)保留。

已在未修改的原版提取器中用真实blackbox.c TU复现hash seed导致访问库存顺序变化；相同seed0时原/新13类组件摘要一致，详见[诊断](evidence/blackbox-hash-seed-probe-v1.json)。这不能解释或豁免所有全图差异。归一化规则不修改；需按[固定执行环境协议](40-fixed-execution-environment-baseline.md)重新完成独立原版与新版完整原生对照。G1维持FAIL，当前实包all_gates_passed=false。

G4亦未达到：同完整数据根+共同构建口径，实际文件分配仅减少40.2058%，标准包尚未计入，见[完整物理统计](37-full-retention-physical-accounting.md)。原32GB物理机、第二物理机、干净离线PC、原生DPI、真实OpenCode及工程师UAT继续NOT_VERIFIED。
