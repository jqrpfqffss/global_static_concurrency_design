# INAV v13完整紧凑包：严格导入与最终70%子门限实测

继[79号标准DEFLATE包](79-r2b-regression-and-v13-package-final.md)的69.8648%真实FAIL后，本次对**同一完整包**仅更换容器压缩：scan.db使用BZIP2 level9，其他载荷DEFLATE6。完整manifest、每个成员名称/顺序和解压后的全部字节SHA均与原包相同，原完整DEFLATE包保留。不是新原生生产者，不能把冻结v32/`49960e0`的扫描改标为较新源码。

| 验收 | 实测 | 结果 / 收据 |
|---|---|---|
| 编码与全载荷对照 | 3,157,552,641B；编码/完整字节复验1315.532秒，控制包络1325.641秒；2GiB Job实际峰值87,556,096B | PASS_SCOPED：[编码/原包保护](evidence/inav-seed0-v13-compact-encoding-v1.json) |
| v37包内Python3.10.9原严格导入 | 独立根`H:/ECRA-INAV-COMPACT-ROUNDTRIP-SEED0-V13`；完整schema/FK/节点/投影/对象校验；2294.687秒，2GiB Job实际峰值616,267,776B | PASS_SCOPED：[严格导入](evidence/inav-seed0-v13-compact-strict-import-v1.json) |
| 同一保留政策的完整文件分配测量 | 原始58,354文件、47,665,101,856B → 当前8,287文件、13,513,363,864B；降低**71.64935489947146%**；两次完整遍历均stable、差异0，78.375秒 | 最终大小≥70%子门限 **PASS**：[完整测量](evidence/inav-seed0-v13-compact-retention-measured-v1.json) |
| 生产者与语义来源 | 冷native v13：388 TU / 4123输入，55454.500秒，Job峰值10,692,485,120B；完整有序事实/既有规范化报告与原始seed0均0/0 | 继承已实测范围：[阶段79](79-r2b-regression-and-v13-package-final.md)，不是重新生产 |

最终策略/资源总收据：[inav-seed0-v13-compact-import-retention-v1.json](evidence/inav-seed0-v13-compact-import-retention-v1.json)。程序`execution.seconds=2302.375`是严格导入控制阶段包络，不能拿它冒充“编码+导入+保留遍历”的总时长。

完整紧凑包路径：`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/inav-v13-compact-bzip2-v1/inav-seed0-v13-full-compact.ecra-report`，SHA-256 **`f3ad33322b79a28e4ca74634137be08f8d2bd65c10f8c50f58e6200585985042`**。严格导入绑定保持原`UNVERIFIED`含义：能够离线查看完整归档证据，不代表当前源码重核对或物理第二台电脑已经验收。

本政策包括完整A13数据根（权威库、人工/AI、Worker、缓存、审计、证据等）、相同common build `I:/ECRA-B1`、一份本次完整标准紧凑包。原始政策同样含完整原始数据根和同一common build。原始独立只读备份、比较图、冻结软件、严格导入根、旧DEFLATE编码作为有明确用途的独立验证副本，按原spec逐一列为排除项；**这些文件全部保留，没有为了门限删文件、清空缓存或省略成员**。

达到的只是该明示政策下的**最终分配大小**门限。采样原生输出峰值18,795,702,152B与原始46,538,663,768B仍是各自记录范围，不是完整政策的全盘历史峰值；Windows目录/MFT/ADS开销未计入。全G4、物理32GiB、跨物理PC、完整UAT仍未关闭。原79号DEFLATE政策69.8648%FAIL不覆盖、不改写；65号v12紧凑包71.6497%同样不改标为本次结果。完整重构依然未完成。
