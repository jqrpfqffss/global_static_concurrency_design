# v27实包完整封存：空间策略与无损新文件整理

2026-11-03（北京时间）。**完整重构未完成，all_gates_passed=false。** 运行时1493c051165973838b35653e26ce1a0943e419d3、2043冻结文件；后续旧调用邻居修复d2c221b另验，不在本包。

| 项目 | 实测/状态 | 证据 |
|---|---|---|
| 完整回归 | 1369项：1367PASS/2联网SKIP，2016.572s；冻结源与独立测试副本无差异 | [完整收据](evidence/full-regression-studio-v27.json) |
| 真实构建 | 498.438s，目录及中文ZIP解包各27CLI，21exit0/6预期INCOMPLETE2 | [构建](evidence/portable-studio-v27-build-v1.json)、[目录](evidence/portable-v27-cli-uncompressed.json)、[解包](evidence/portable-v27-cli-zip-extracted.json) |
| 完整分发 | 30338文件全部SHA；127运行时源码匹配；ZIP640164606 B，SHA256 0edc217422f44c06917c19c14256fba7b4ab88902aae8b400c7e3fc8348b282f | [完整封存](evidence/portable-studio-v27-seal.json)、[文件核验](evidence/portable-v27-files-verification.json) |
| 原13组Chrome | 预检查16/示例11/主流程17/旧缺证据6/配置7/上下文8/目录7/Git6/容量9/覆盖8/旧迁移6/协作7/启动器4；112个重叠断言全通过 | 对应browser-portable-v27逐组收据，[截图](ui/screenshots/portable-v27) |
| 额外4组Chrome | 历史8、启动目录6、实际进程崩溃恢复5、新空间策略8全部通过；合计17组139个重叠断言 | [历史](evidence/browser-portable-v27-history.json)、[目录](evidence/browser-portable-v27-data-root.json)、[崩溃](evidence/browser-portable-v27-crash-recovery.json)、[空间策略](evidence/browser-portable-v27-storage-policy.json) |
| 空间真实闭环 | GUI保存/重启、当前OFF任务保留策略/下一AUTO原生扫描、完整字节校验压缩、中文逻辑/实际分配量、独立Viewer标准包完整根一致、并发拒绝及损坏原件备份修复 | [实现与原生零差异](43-storage-policy-and-native-compaction-acceptance.md) |
| U16 | 本包没有重跑1000项；历史v23第三批1000单独保留，不能借为v27运行证明 | [U01–U24逐项](ui/29-user-scenario-status-v27.md)：11PASS/13NOT_VERIFIED |
| 大型G1/G4 | 新固定环境原版有效完成，新版仍发布中；比较图/完整对照/标准包/全策略物理统计排队。旧六字段差异及40.2058%失败不覆盖 | [实际协议](44-fixed-environment-pair-and-verifier.md) |

Windows入口：`H:/ECRAStudio-build-20261103-studio-v27/ECRA-Portable/ECRA.cmd`。ZIP：`H:/ECRAStudio-build-20261103-studio-v27/ECRA-Portable.zip`。软件与用户数据分离；普通使用端无需Node。构建/本机实际包通过不等于干净离线PC或第二物理机验证。

参考截图：[首页](ui/screenshots/portable-v27/main-01-overview.png)、[向导](ui/screenshots/portable-v27/main-02-project-wizard.png)、[证据](ui/screenshots/portable-v27/main-03-evidence-workbench.png)、[扫描](ui/screenshots/portable-v27/main-04-scan-published.png)、空间策略/占用与历史完整套图位于上述截图目录。截图是实际Chrome操作结果，不是模型页面或工程师UAT。

新原版完整备份与当前Native发布同用一块机械盘。已核对仅本次原版参考控制器/备份进程身份，将其I/O从NORMAL降为LOW；不改变文件字节/引擎/内存预算/比较规则，不操作其他应用。[调度收据](evidence/original-seed0-reference-io-priority-v1.json)。并行负载下的扫描耗时只作本次实测，不归因为独占加速。

仍缺：当前大型全字段/完整协议、实际磁盘70%目标、完整外置只读构建与生产写隔离、未提交输入正式全链、完整每变量证据继承、全部失败矩阵、全量根搬迁、当前大工程GUI/U16、用户延期的其余真实工程，以及物理32GB/干净机/两机/DPI/联网OpenCode/工程师UAT。各子范围通过不替代整阶段门禁。
