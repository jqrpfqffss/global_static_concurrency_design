# V9 完整离线便携构建

当前状态：**完整离线构建、两轮实际运行门禁、输入后验及组件复核已通过**。随后最终解压包的 [Q405](q405-v9.md) 与 [native Diff 阅读](continuation-native-diff-ui-v9.md)亦已实际操作验收，分别有正式成品收据；不从构建本身推定界面通过，也不以先前 SOURCE_UI_PREVIEW 代替。

| 身份 | 冻结值 |
| --- | --- |
| 源码 | `H:/ECRA-quality-20261108/continuation-builder-source-v9`，4,370 文件、302,937,028 字节 |
| 源码快照 SHA256 | `274ebf4c54ac8ac39dce8a8038c72b833cbb47360151b55374cf1b3a709c2c3a` |
| 核心 | `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`，127 个生产 Python 文件与 v8 相同 |
| 新界面 | JS `index-hDrZQigI.js`、CSS `index-C8hLhrqC.css` |
| PS 打包脚本 SHA256 | `69aeebd31b85dd020375ca55bc50aeb04f3c710fab219b2d33c3799a414185cd` |
| 新输出 | `H:/ECRA-quality-20261108-offline-build-v9` |

外部 [run_offline_build_v9.py](../../output/quality-20261108/continuation/run_offline_build_v9.py) 在协调者明确确认预包 native 场景通过后才启动，没有后台自动排队。它正常 import 原命令 helper，使用真实 Windows PowerShell 5.1 原 `OfflineCheck` 和完整 `build_portable.ps1`，移除继承的全部大小写 `PSMODULEPATH`，不改产品 PS 或冻结源码。

本轮按原打包脚本执行未压缩目录与中文空格临时解压目录的两轮全文件 SHA、各 27 个实际隔离命令。输入后验覆盖4,370源码文件、27,921缓存输入文件及已有四份 ZIP（首轮local、v4、v6、v8），禁止覆盖旧包。缓存诊断收据与组件字节分开记录；原准备脚本仍可重新生成 local-tools/preparation-result。

| 实际验证 | 结果 |
| --- | --- |
| WinPS5.1 OfflineCheck | exit 0，62.875 秒 |
| 原完整 build_portable.ps1 | exit 0，1,055.765 秒；包含前后输入 SHA 的控制器总计1,277.578秒 |
| 未压缩目录与 ZIP 中文空格临时解压目录 | 各完整内容 SHA 校验、各27条实际命令 PASS；保存静态事实不变，包内均无runtime-data |
| 冻结输入后验 | 4,370源码、27,921缓存输入文件前后全部SHA相同；旧四ZIP全部SHA不变 |
| 成品清单 | 32,691个内容文件加清单，共32,692个ZIP文件；名字/大小/重复检查通过，154生产文件与final-engine-v9逐SHA相同 |
| v8直接继承对照 | 从已验收v8 ZIP读取清单直接比较：127生产Python文件、27,772个tools文件、Python本体及libclang完全相同；不将v8用例改标为v9实测 |
| runtime差异 | 对v4基准仍只有新pip生成的3个EXE入口及对应3个RECORD，入口`__main__.py`一致、含本轮解释器路径；不称整棵runtime相同 |

正式 ZIP：`H:/ECRA-quality-20261108-offline-build-v9/ECRA-Portable.zip`，**785,692,863字节**，SHA256：

```text
7a0e45b0f3dda3ee47d7759f9784ab66ca9f8fa089543157f64c9f9be9a6c03d
```

27条命令按原合同保留风险/不完整结果的exit 2，不将其计作技术失败后忽略，也不改写为全工程完整无风险。在线OpenCode实际供应商调用不在这两轮离线门禁内。

v8 最终解压包的实际 Git18 与独立 ARM 链路保持原 v8 身份，不重新标为 v9 实测，也不因本次界面改动重复其全场景。本轮已按实际 SHA 比较127生产 Python 文件与全部工具组件，继承仅适用于这些相同组件；新 Q405 界面后来已在 v9 最终成品实际操作验证，见上。v8 记录见 [完整构建和包内 Git18](continuation-offline-build-v8.md)。

最终只读核对再次确认：主工作区、final-engine-v9、最终解压包154生产文件完全相同，分支仍为optimize_ccc@fe27afe，暂存区为空。另保留一个明确的非runtime差异：engine-only目录内辅助`build_portable.ps1`仍为旧dc984598…，它没有承诺可重建正式包；真正本轮正式入口为主区及`continuation-builder-source-v9/build_portable.ps1`的69aeebd3…，official命令和最终包SOURCE-SNAPSHOT均绑定后者。没有修改冻结目录来隐藏差异。详见 [final-worktree-v9](evidence/final-worktree-v9.md)。

证据：

- [builder 冻结身份](../../output/quality-20261108/continuation/builder-frozen-v9.json)
- [准备但未启动的历史收据](../../output/quality-20261108/continuation/offline-build-v9-prepared.json)
- [本轮输入基线](../../output/quality-20261108/continuation/offline-build-v9-intake.json)
- [原生运行收据](../../output/quality-20261108/continuation/offline-build-v9/receipt.json)
- [完整输入后验](../../output/quality-20261108/continuation/offline-build-v9/input-postflight.json)
- [154源、直接v8继承、ZIP与双门禁独立审计](../../output/quality-20261108/continuation/offline-build-v9/build-component-audit.json)
- 原始 `offline-check.log`、`build.log` 位于 `output/quality-20261108/continuation/offline-build-v9/`。

本记录只说明构建和相关组件验证。在线 OpenCode、真实工程支持边界、大型工程资源情况及整个项目的交付结论，仍由对应矩阵和证据分别判断。
