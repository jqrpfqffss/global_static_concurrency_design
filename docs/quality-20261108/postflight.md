# 封包后的外部验收收据

本页对应首轮local ZIP；当前正式候选已更新为V9，见[当前验收](continuation-final-v9.md)。原local ZIP及其原始收据保留，没有覆盖或改标为新包。

本文件及最终补充收据在ZIP封存后追加，不回写ZIP或已封存程序。包内质量记录是封包时快照；完整最新结论以此目录工作区版本为准。

## 本轮成品

- ZIP：`H:/ECRA-quality-20261108-delivery/ECRA-Quality-20261108-local.zip`。
- 787,798,791字节；SHA-256：`b02a9e30a9270bfa35c558bc3191d3305c7f02624d789ea24a48f8d6399272ab`。
- 独立中文空格路径解压目录：`H:/ECRA-quality-20261108-delivery/解压 终验/ECRA-Portable`。
- 32,988个内容文件，另有FILES清单自身；全部ZIP成员解压CRC、逐文件SHA校验一致，无.git。解压目录151个生产文件与冻结源码逐字节相同，静态指纹74c0…，没有将基包历史运行收据冒充本轮重跑。
- 这是完整v91基包校验后叠加当前修复的本地验收候选，不是重新执行全部工具链封包门禁，也未发布或覆盖原dist/v91。

收据：[ZIP与解压完整性](evidence/portable-patch-zip.json)、[解压CLI/实际import](evidence/extracted-cli-import.json)。

## 解压后实际启动和继续

2026-11-08实际运行解压目录的 `ECRA.cmd`，当前工作目录与程序目录分离，子进程PATH仅Windows系统目录；使用包外隔离数据根 `H:/ECRA-quality-20261108/packaged-ui`。由包内Python3.10.9启动本地服务，通过其真实启动URL打开有界面Chrome。

- 读取之前阶段目录写入的同一教学库，人工待办5、独立人工风险1；3个人工事件的ID/内容保持，静态hash保持 `261ff9b60b1ce40f233704520d93e280804d07ee1bc119cb5430bd9b67bae12e`。
- 点击“继续人工确认”，自动选中剩余对象g_msgSP，显示5项待办，归档访问/冲突和操作入口正常。
- 1366×768实际视口截图已查看：[解压后继续](evidence/zip-continue-1366.png)；完整20/21图在 `output/playwright/quality-20261108/`。
- 本次重新打开的浏览器控制台0错误、0警告。先前写锁故障阶段的两条预期HTTP409错误单独保留，不混同为零错误。
- 浏览器与本轮服务均已关闭，后续从此目录的ECRA.cmd重新打开并选择同一数据根即可继续；没有注入浏览器状态/历史记录模拟恢复。

服务和浏览器关闭后再次核对32,988个内容文件，全部保持不变；151个生产文件仍与冻结源码匹配，差异列表为空。见[最终关闭后全文件后验](evidence/extracted-final-postflight.json)。静态指纹没有变化，主矩阵已更新为此限定范围通过；完整发布门禁仍为false。

## 验收边界

ZIP一致、目标Windows启动和本条继续流程通过，不意味着所有发布门禁通过。大型INAV整轮、联网AI、干净离线物理电脑、32GB机、完整MinGW目标与原生缩放等缺口见[validation.md](validation.md)。测试人工记录只在隔离教学根，不是客户工程签名。
