# v24：schema3与流式完整校验的实包验收

2026-11-02，运行时`aac467f4198cdc79c1bf8f575dd37d9d3fac5e0f`，冻结1706个跟踪文件；后续历史检索源码不在此包内。不是完整重构完成宣告。

| 项目 | 实际结果 | 证据 |
|---|---|---|
| 完整冻结回归 | 1330项，1328PASS/2联网SKIP，1970.369s；源码与独立测试副本后验SHA无差异 | [完整收据](evidence/full-regression-studio-v24.json) |
| Portable | 构建exit0、1102.797s；包内Python3.10.9；目录与中文ZIP解包分别27CLI（21exit0/6预期INCOMPLETE2） | [构建](evidence/portable-studio-v24-build-v1.json)、[封存](evidence/portable-studio-v24-seal.json) |
| 分发核对 | 30014文件完整SHA；121运行时源码匹配冻结源；ZIP611948764字节，SHA256 `20f9c6740de350ba837fd1d278304dd7862309628e7beba196cca4505650ba79` | [完整文件校验](evidence/portable-v24-files-verification.json) |
| 实包真实Chrome | 13组112个重叠断言通过：预检查16、示例11、主流程17、缺证据旧件6、profile7、上下文8、目录7、Git6、容量9、覆盖8、旧迁移6、协作7、启动器4 | [逐组收据索引](evidence/portable-studio-v24-seal.json)、[实图目录](ui/screenshots/portable-v24) |
| 实际进程异常 | 新鲜独立根、F030真实扫描：Worker异常→失败/GUI重试，服务异常→后代结束/重开中断/GUI重试；旧库/人工事件/最新指针不变，均有真实TU命中 | [5项通过](evidence/browser-scan-crash-recovery-v24-v1.json)、[截图](ui/screenshots/scan-crash-recovery-v24-v1) |
| 跨版本1000确认 | 本包未重跑；[v23第三批1000](evidence/browser-review-upgrade-third-batch-v23-v1.json)是独立历史证据，共3000事件，不借为v24实际新批次 | NOT_VERIFIED_V24_NEW_BATCH |
| schema3/校验器 | 本包实际包含WITHOUT ROWID/部分索引、严格schema注册与全节点/全边流式完整校验，专项F030全字段差异0 | [ADR布局](30-compact-sqlite-layout-adr.md)、[ADR校验](32-streamed-integrity-validation-adr.md) |

入口：`H:/ECRAStudio-build-20261102-studio-v24/ECRA-Portable/ECRA.cmd`。

复现：`py -3.10 -B -X utf8 -m unittest discover -s tests -v`；`py -3.10 -B -X utf8 scripts/validate_scan_crash_recovery_ui.py --engine H:/ECRAStudio-build-20261102-studio-v24/ECRA-Portable --python H:/ECRAStudio-build-20261102-studio-v24/ECRA-Portable/runtime/python.exe --config <原获准F030配置> --work <新独立目录> --evidence <新截图目录> --allow-external-toolchain`。黄金编译数据库原外部编译器获准，仅此标志显式允许，不替换原工具链。

| 门禁 | 当前边界 |
|---|---|
| G1/G2 | F030完整facts/report对照PASS；INAV冷原生v10仍在生产持久化，完整大型对照尚待有效输出。其他真实工程NOT_VERIFIED_USER_DEFERRED。 |
| G3 | 旧16GiB受控失败保留；当前v10峰值采样约10.02GB但尚未完成，不能据此关闭G3。物理主机64GiB，32GB真机NOT_VERIFIED。 |
| G4 | 未证明完整保留策略物理占用减少70%；schema3小工程相同行25%减少不可外推。 |
| G5/G6 | 当前实包真实异常重试/恶意包/完整小包往返子集通过，断电/系统重启/磁盘满等全矩阵及大型完整协议仍未关闭。 |
| G7/G8 | 非完整U01–U24；第二物理电脑、Windows原生DPI、干净离线PC、真实OpenCode、工程师盲测继续NOT_VERIFIED。 |

大型比较已从等待的v1控制器切换为v2：原v1在任何校验之前撤销，[收据](evidence/inav-cold-v10-comparison-package-v1-superseded.json)保留。v2已确认本v24完整1330通过，等待v10有效结束和全部4123输入/1565引擎SHA后验，再在2GiB Job中做完整有序对照和标准包往返。生产者仍是冻结v23/c311，未中断、替换或向运行时注入优化。该队列的完成结果尚待验，不冒充第二物理机/G4。
