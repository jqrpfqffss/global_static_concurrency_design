# 最终 V9 成品读取真实原生差异结果

2026-11-08 14:10 UTC，实际程序为 `H:/ECRA-quality-20261108-offline-build-v9/解压 终验/ECRA-Portable/ECRA.cmd`。Windows-only PATH，包内 Python，模式 PORTABLE，启动根 PID33724。使用原持久 Chrome profile 与 `viewport:null`，访问自有 localhost 服务；没有缩放、DPI 或 file 协议绕过。

输入是此前[实际 V8 包 ARM full→Diff→full](continuation-diff-v8.md)生成的差异扫描 `46cba8a215be4b73ba2e77f0a86f96c8`。V8/V9 的127生产 Python、全部工具、Python本体和libclang逐SHA相同；本次只验最后界面读取，不把旧执行改标为 V9 新扫描。

| 实际用户操作 | 观察结果 |
|---|---|
| 变量与风险→shared→证据与调用链 | 当前静态 SUSPECT，mainStep 与 IRQEntry 两处真实 RMW 及冲突关系可读 |
| 查看 Diff 范围和身份 | 明确影响3项、单列潜在影响2项；固定 base43c005e…与 HEAD54f5da3…、include_uncommitted:false；未展示不代表安全 |
| 展开填写区并正常滚到末尾 | 项目“中文 空格 Git 工程”、shared、main.c:3、独立人工待确认与四个动作同屏；不需滚回猜测当前对象 |
| Escape/清除筛选 | 恢复全部5对象：3 SAFE_PROVEN、1 CONTAINER、1 SUSPECT；待办1；原Diff范围提示保留 |
| 关闭浏览器并正常 Ctrl+C 停服 | Chrome持久profile保留；0.328秒后根/服务退出，产品删除会话文件 |

截图为真实窗口画面，PNG像素1448×632；本次收据没有独立记录准确外窗 bounds，因此不借用 Q405 的1447×631/1461×781数值，也不将截图尺寸说成经独立测量的浏览器 inner 尺寸。图已实际打开查看，最终关键图归档见[索引](evidence/final-v9-ui/index.md)。

没有输入确认者/理由或签署。只读 API 与 SQLite 复核：全部5对象、1待办，人工事件仍0，静态库 SHA-256 `2db113e09143b3ea88939fdb62e3be4252b6d46e233fc2d90f9e6f4a471a6d41` 与真实原生扫描完全相同。154生产文件、32692文件名字/大小及 Python/libclang/Git/GCC关键二进制 SHA 前后相同。没有重复第三轮完整工具链全SHA。

结论：**最终 V9 成品的原生差异结果阅读与共同确认入口通过**；不是人工保存的新证明，也不是全工程无风险证明。完整收据：[native-diff-ui-final-v9/acceptance.json](../../output/quality-20261108/continuation/native-diff-ui-final-v9/acceptance.json)。
