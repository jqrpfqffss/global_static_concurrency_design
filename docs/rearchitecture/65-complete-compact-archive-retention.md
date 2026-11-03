# 大型完整包：严格导入与最终保留量实测

2026-11-04。本记录仍绑定原版 e69 与冻结 v27/1493c05 的同输入冷原生 v12，不将它改标为 v35 新原生扫描。完整有类型、有顺序事实及既有规范化报告差异均为 0，完整比较器未修改，见[62号记录](62-fixed-seed-full-package-and-size-failure.md)。

| 阶段 / 核心功能 | 实际结果 | 状态 | 证据 |
|---|---|---|---|
| Phase 5，完整包无损编码 | 原标准包 4008043398B → BZIP2 完整包 3157389743B；manifest 字节、成员集合、每个解压文件 SHA 全部一致；原包完整 SHA 前后不变 | PASS_SCOPED | [完整编码](evidence/inav-v12-compact-bzip2-encoding-v1.json) |
| Phase 5，实际包内严格导入 | v34 包内 Python 3.10.9，独立新根、既有完整导入/深校验和默认 512MiB 读取缓存；2305.703s，所有归档事实、审计对象与人工事件合同保留 | PASS_SCOPED | [严格导入](evidence/inav-v12-compact-strict-import-v1.json)、[控制器](evidence/inav-v12-compact-import-retention-v1.json) |
| Phase 2/6，最终占用目标 | 完整数据根、公共构建/缓存及所选完整包均计入；两次完整遍历稳定；47665101856B → 13513190616B，减少 71.6497183687%；整数检验 `after*100 <= before*30` 成立 | PASS_SCOPED | [物理计量](evidence/inav-v12-compact-retention-v1.json)、[精确范围](evidence/inav-v12-compact-retention-spec-v1.json) |
| Phase 6，完整 G4 | 原生输出峰值、后续封装/导入窗口分开；全策略历史瞬时峰值不可重建，文件系统目录/MFT/ADS 不在文件分配量中 | NOT_VERIFIED | 同计量收据；没有据最终尺寸关闭整个 G4 |

此次独立严格导入在 2GiB Job 内执行，观察到 Job 峰值提交 616513536B。新归档 SHA-256 为 `ce4cc263a5f95cc557cef3c929eced9f5d1fc9935b88fd0d99c21f643faa6de7`；旧 DEFLATE 原件 SHA-256 仍为 `0e52a72c04fe66399241eae1406f8490a23b637465f13c76d7121c6613640b08`。新独立根是 `H:/ECRA-INAV-COMPACT-ROUNDTRIP-SEED0-V12/scans/native-golden`。完整内容的 facts 根为 `43153000056630428dd91c4af9787cda65c107f4690814e36b607e21de4696aa`，规范化 report 根为 `26af6df2f8a675ef2be0a25f2be4b45c807f1ba2a8cd21a4d7af72aa53ed52db`。

保留范围明确排除独立黄金备份、原版比较图、冻结软件副本、独立导入验证根，以及旧 DEFLATE 重复编码对照包。旧包实际仍在盘上，没有删除；其 manifest 及全部原始成员已逐一证明完整存在于所选压缩包内。这里证明的是**选定标准完整归档保留策略**达到最终尺寸目标，不是这台机器上包括所有实验副本的总占用下降 70%。此前含 DEFLATE 包的 69.8650727% **FAIL 原收据保持不变**。

| 同输入真实大型指标 | 原版 e69 | 冷 v12 / 1493c05 | 边界 |
|---|---|---|---|
| 原生扫描耗时 | 15454.922s | 31846.532s | 候选更慢；共享机械盘并发运行，不宣称提速 |
| 进程树 RSS 峰值 | 29559390208B | 10618966016B | 64GiB 主机的受控 Job；非物理 32GB 机 |
| Job 峰值提交 | 29811765248B | 10687008768B | 原版 32GiB / 候选 16GiB Job |
| 主进程 peak_pagefile | 29805244416B | 10680487936B | Windows 高水位计数，不冒充 RSS |
| 原生输出采样分配峰值 | 46538663768B | 18794582808B | 只覆盖生产者输出，非整个策略历史峰值 |
| 最终保留策略分配量 | 47665101856B | 13513190616B | 公共构建/缓存及候选完整包计入；稳定完整遍历 |
| 候选标准完整包 | 原始结果及独立完整备份保留 | 3157389743B | 同内容封装；不是精简分享 |
| 完整有序、有类型事实 / 规范化报告差异 | 基准 | 0 / 0 | 仅这个已独立完成的固定生产者对 |

可复现计量命令：`py -3.10 -B -X utf8 scripts/measure_storage_policy.py --spec docs/rearchitecture/evidence/inav-v12-compact-retention-spec-v1.json --output <新的独立收据.json>`。源码/便携包完整导出入口已提供两种编码，见[64号 ADR](64-complete-archive-compression-adr.md)；本次大型试验采用旧包完整重编码，不能代替后来生产导出器在大型输入上的直接验收。

冻结 49960e 的 writer64MiB 冷原生 v13、新 512MiB 独立完整比较仍在执行，不借用本记录封口。其他 G2 输入按用户决定延期；生产强写隔离、dirty 快照、全数据根搬迁、不变证据确认继承、完整故障矩阵、物理第二台电脑/干净离线/原生 DPI/OpenCode 联网/UAT 仍未完成。完整重构与 H1–H6/G1–G8 不宣称全部通过。
