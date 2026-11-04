# 自动盘点编译输入：F030 原生子阶段验收

本页封存已经完成的内部自动盘点验收，不是最新正式GUI/Diff/恢复的验收。后者接入合同见[91号](91-dirty-input-workflow-contract.md)。所有原始失败尝试和黄金输入保留。

| 项目 | 实测结果 |
|---|---|
| 输入 | 获准F030快照的独立私有Git副本，4个真实TU；原工程不改 |
| 冻结程序 | v45，父提交`f212a8b94a5fd9aa103b0e113bc16af2e34f9e8e`加明确工作区覆盖；3718文件；清单SHA256 `b03ffe523f70c71d10496f02b84b171a075ae221113da7a16a4635146af4487a` |
| 自动固定 | 1714文件，107274982字节，176目录；包括实际外部CWD、GNU标准头、配置/数据库/工具 |
| 同一逻辑输入 | 普通全量与自动固定全量，完整facts/report差异均0；原始/冻结依赖及预处理签名核对通过 |
| 完整包 | 独立导入后完整facts/report差异均0；3490301字节，SHA256 `1d482f1df8b2082994481dc2e41834d7020dd3fb27bca9dddfb1d10b90844af8` |
| 真实覆盖 | 2 PARSED / 2 PARTIAL / 0 FAILED，保留INCOMPLETE和退出码2，没有把部分解析转成成功 |
| 普通 / 冻结 / 控制器耗时 | 21.625 / 484.563 / 924.844秒；路径及输入核对昂贵，不能宣称提速 |
| 原件保护 | 获准原件、私有Git/索引、外部build/SDK、冻结引擎的SHA/大小/适用mtime前后差异均为空 |
| 收据 | [完整机器收据](acceptance/automatic-f030-v45-v1.json)，原始目录`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/automatic-f030-v45-v1` |

复现命令（必须使用新目录保留已有证据）：

```powershell
py -3.10 -B -X utf8 scripts/validate_frozen_scan_pipeline.py --automatic-inputs --engine <冻结引擎目录> --source <获准的无.git源码快照> --config <真实显式数据库配置> --work <独立全新验收目录>
```

**边界**：v45还使用V1内部视图。这次结果不能证明后来V2公开接入、归档源码MCP、正式恢复、CMake构建或大项目内存已经完成。F030部分解析由Clang对既有启动代码等的诊断造成；`verify_against_full`对部分提取仍须按原规则失败，不能为了验收改变该门禁。其他G2工程按用户要求待验；物理32GB/第二PC/干净离线/原生DPI/联网OpenCode/UAT仍NOT_VERIFIED。
