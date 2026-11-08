# 最终验证范围与未完成项

本页保留首轮的结论与缺口；后来新增修复和实际复验见[当前 V9 验收](continuation-final-v9.md)。本页旧版本“最终”与当时未完成项不能取代最新状态。

本轮为本地修复及验收候选，不推送、合并或发布。未声明整个重构已经达到完整交付门禁。

## 最后相关修改后的验证

| 验证 | 实际结果 | 证据 |
|---|---|---|
| 联合状态/分析投影/人工/包/身份/API | 124 passed、160 subtests，97.72s | output/quality-20261108/final-integration-tests.log |
| 配置/真实预检查/新init/相对toolchain | 37 passed、24 subtests，34.26s；额外真实新init专项含在包内回归 | config-preflight-final-tests.log；delivery.md |
| HTML转义/证据、非UTF8、原子写入、Windows写保护、AI格式与完整性 | 35 passed、25 subtests，14.43s | output-boundary-tests.log |
| 前端草稿/对象身份与证据名称 | 8 passed，0 skipped | frontend-state-tests.log |
| 前端类型检查与生产构建 | vue-tsc / Vite通过；最终 index-C8CfT7jx.js、index-CFjgtXt1.css | frontend-final-build.log |
| 便携包内Python3.10.9核心 | 41 tests，0失败/0错误/0跳过；实际import包内产品而非源码 | [包内收据](evidence/packaged-core-tests.json) |
| 三独立真实工程 | 最终74c0…全扫、status/report、库校验、输入不变通过；INCOMPLETE保留 | [完整收据](evidence/real-projects-final.json)、delivery.md |
| 大型INAV | 最终引擎实际提取time.c/fc_core.c均PARSED，原输入不变 | [限定范围收据](evidence/inav-scoped-final.json) |
| 用户流程与画面 | 实际向导、扫描、停止130、校验恢复、结果、连续确认、真实写锁失败/重试、撤销、导出/导入、关闭再继续 | ui.md、independent-ui.md、evidence/精选图 |
| 旧HTML | 实际file://生成物、搜索/证据/关闭重开、两种视口通过 | legacy.md |

测试组有交叉，不相加作为独立测试总数。早期基线、故障前后证据和失败控制器日志均保留。后来的真实工程及包内核心验证使用最终静态指纹 `74c0b1c0f3fa204088534ad90f5bcefaf4bccb5a00ce42bce4cfb878eea509b2`；没有手工修改扫描状态来补通过。

## 有限范围、已有证据和剩余门禁

- F030为2 PARSED+2 PARTIAL，F411为24 PARSED，CDC为39 PARSED；三个项目都有未解决风险/未知与待复核，退出码2不被改成0。来源、固定提交、许可及已有数据库的来源见delivery.md。此轮没有重新配置/链接三个完整固件，也没有烧录或硬件时序验证；实际构建由有界CMake/ARM回归另外证明。
- 大型INAV整轮全量、完整Diff矩阵、停止恢复和严格事实对照尚未完成。本轮两TU不能替代390条目标输入的全工程验收。既有长耗时/严格对照门禁未通过的记录继续保留，不修改阈值或对照规则。
- OpenCode关闭、传输/重试/格式/聚合及技术失败有回归；没有本轮新的联网模型推理、真实模型逐冲突证伪或案例正文读取验收。已有历史联网收据没有算成本轮通过。
- Windows为实际环境，包在中文空格路径、无.git、仅系统PATH实际运行。没有干净离线物理电脑、另一台32GB机器、全部MinGW真实目标重建、浏览器真实页面缩放或Windows系统DPI切换验收。视口变化不替代缩放。
- 没有本轮受控的大工程峰值RAM/长列表压力前后对照，因此不声称性能优化或大型稳定性门禁通过。三工程耗时只是同机并发验收时的实测，不能当性能保证。
- 当前动态回调、DMA、RTOS/双核、复杂C++等仍按实际证据边界表达；没有扩展成全支持，也没有把未展示/未解析的内容标安全。
- 写锁为实际故障；磁盘满映射、原子写入/回滚有针对回归，没有将其冒充真实断电、硬件损坏或全磁盘故障模拟。
- 本轮便携候选是完整v91基包校验后叠加当前源码/页面/说明的独立副本。没有重新执行整套build_portable工具链构建；未改原v91、旧dist、真实工程或真实确认。ZIP封包后收据另附，包内文档保留封包时快照，不回写已封存文件。

## 证据保存

仓库内保留台账、功能矩阵、精选截图和结构化核心收据。完整命令/日志/全部截图位于工作区 `output/quality-20261108/`、`output/playwright/quality-20261108/`；扫描库及包位于外部隔离目录 `H:/ECRA-quality-20261108/` 与 `H:/ECRA-quality-20261108-delivery/`，均未清理。临时会话凭据不复制进本记录。若迁移本次证据，应保留对应数据根和本地输出，避免只带走简要文档。
