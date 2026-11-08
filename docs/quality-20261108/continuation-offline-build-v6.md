# V6 Windows 完整离线便携构建

当前状态：**完整离线封包和两轮 nominal 运行门禁已通过，最终交付仍阻断**。启动后在真实旧报告操作中确认 `ADDRESS_TAKEN` 被显示为“未识别状态”，协调者已冻结仅含 GUI 标签修复的 v7 源码；之后主线程在同一核心的 stat-only 工作区 smoke 中发现实际失败，最终封包等待其根因修复。v6 保留为该核心的完整封包证据，v7 已在读取源码/缓存前停止排队，不能把两者当作最终交付通过。本记录不替代受影响工作区扫描或最终界面操作验收。

本轮使用冻结源码目录 `H:/ECRA-quality-20261108/continuation-builder-source-v6`，在新的 `H:/ECRA-quality-20261108-offline-build-v6` 执行原有离线准备检查及完整打包脚本；没有覆盖旧包、复用旧包目录或进行补丁压缩。

| 身份 | 固定值 |
| --- | --- |
| 原分支提交 | `optimize_ccc@fe27afe73596d98e1a21e3f28a2125d38d7272d0`，含已接受本地修改 |
| 核心摘要 | `65c0fb3dbc29bda7ad74aeeadeb4666c6b1eeda545bc9521c3961f476eca7682` |
| 冻结源码 | 4,370 个文件，302,929,858 字节 |
| 源码清单 SHA256 | `638452f8b2c6068a29a191cd16827f159ca103a0e7d4ceed2cedaaafb663717e` |
| 打包脚本 SHA256 | `69aeebd31b85dd020375ca55bc50aeb04f3c710fab219b2d33c3799a414185cd` |
| 前端 | `index-DBiOaukX.js`；CSS 沿用已冻结内容 |
| 打包环境 | 实际 Windows x64、Windows PowerShell 5.1；缓存中的 Python 3.10.9、完整 MinGit 2.56.0.3 |

启动控制器是 [run_offline_build_v6.py](../../output/quality-20261108/continuation/run_offline_build_v6.py)。它通过正常 Python import 复用原 v4 命令封装，仅改三个路径；启动的产品脚本未改。控制器在自身进程移除所有大小写形式的 `PSModulePath`，让 Windows PowerShell 5.1 初始化自己的标准模块路径，避免此前 PowerShell Core 环境继承造成的检查控制器错误。产品脚本的隔离验收仍实际使用 Windows 系统 PATH。

实际调用：

```powershell
py -3.10 -X utf8 -B output/quality-20261108/continuation/run_offline_build_v6.py
```

内部顺序为 `prepare_portable_cache.ps1 -CacheDir H:/global_static_concurrency_design/.tools-cache -OfflineCheck`，通过后运行 `build_portable.ps1 -OutputDir H:/ECRA-quality-20261108-offline-build-v6 -CacheDir H:/global_static_concurrency_design/.tools-cache -GitSource H:/global_static_concurrency_design/.tools-cache/git-diff-runtime/MinGit-2.56.0.3`。未设置 `SkipZip`。

本轮保留完整未压缩文件 SHA 清单、未压缩目录实际隔离门禁、ZIP 中文空格临时目录解压后的全文件 SHA 门禁及第二轮实际隔离门禁。最终 ZIP 只在原打包脚本解压门禁通过后改为正式文件名。

| 实际结果 | 证据口径 |
| --- | --- |
| OfflineCheck exit 0，54.219 秒 | 原固定缓存检查、未安装或下载新组件 |
| 完整 build exit 0，878.500 秒 | 原 `build_portable.ps1`；未压缩目录、中文空格临时解压目录各全文件 SHA + 27 个实际命令通过 |
| 总控制器 1,086.172 秒 | 包含构建前后输入与已有 ZIP 的完整 SHA 核验 |
| 4,370 个源码文件、27,921 个缓存输入文件（1,871,556,344 字节） | 前后全部 SHA 相同；两个旧 ZIP SHA 也完全相同 |
| 32,691 个内容清单文件及清单本身，共 32,692 个 ZIP 文件 | 名字、大小、重复文件检查通过；154 个 `ecra/` 生产文件与冻结 final-engine-v6 完全相同 |
| 工具继承 | `tools/` 共 27,772 个文件与实际已验证 v4 包逐 SHA 一致；Python 本体、libclang、ARM GCC、MinGit、CMake、Ninja 关键文件再次实际取 SHA 一致 |
| runtime 差异 | 仅新 pip 生成的 fastapi/idna/uvicorn 三个 EXE 入口及对应 RECORD；入口的 `__main__.py` 字节与旧包相同，嵌入本次解释器路径，不能称整棵 runtime 字节相同 |

成品为 `H:/ECRA-quality-20261108-offline-build-v6/ECRA-Portable.zip`，**785,692,259 字节**，SHA256：

```text
a7cc76fbbf200829db6942092c8630999e8ef9ca4305552f6bdceba4ae886f8e
```

OpenCode 服务商复核仍为外部依赖，本轮原便携门禁只实际验证禁用接口，不将它计入在线 AI 验证。当前65核心工作区失败与旧 GUI 标签缺口仍需后续最终版本处理，`release_ready=false`。

冻结检查包括所有 builder 源码文件、九类实际输入缓存目录（Python、VC 运行库、CMake、Ninja、MinGW、ARM GCC、downloads、wheels、MinGit）及两份已有 ZIP 的前后 SHA。`.tools-cache/local-tools.json` 和 `preparation-result.json` 是原准备脚本有意重新生成的诊断收据，与组件文件分开记录；其他开发日志不属于该输入缓存范围。不能据此声称整个 `.tools-cache` 每字节不变。

原始证据：

- [冻结 builder 收据](../../output/quality-20261108/continuation/builder-frozen-v6.json)
- [输入缓存和旧 ZIP 基线](../../output/quality-20261108/continuation/offline-build-v6-intake.json)
- [运行收据](../../output/quality-20261108/continuation/offline-build-v6/receipt.json)
- [源码、缓存和旧 ZIP 后验](../../output/quality-20261108/continuation/offline-build-v6/input-postflight.json)
- [双轮门禁、ZIP 与组件独立复核](../../output/quality-20261108/continuation/offline-build-v6/build-component-audit.json)
- 原生日志 `output/quality-20261108/continuation/offline-build-v6/offline-check.log`、`build.log`。
- [v7 排队中止收据](../../output/quality-20261108/continuation/offline-build-v7-queue-held.json)：仅停止尚未进入构建、没有子进程的等待控制器，未杀 v6 正常构建。

验证口径：v4 包已实际完成 F030 四个 C 文件编译、链接、真实 CDB、CLI 与 API，以及包内 MinGit 的真实全量/差异已知答案对照，见 [v4 包原生链路](continuation-portable-v4-native.md)。这些是按其原核心和工具版本保留的证据。本轮 v6 改动涉及 dirty 工作树准入、Git 工作区内容判别、目录监视身份保护及前端标签；受影响 dirty 全流程由协调者另行记录，最终 GUI 在本轮成品中操作验证。不得把 v4 的既有结果重新标成 v6 实际运行，也不因为同一组件的继承关系声称所有新模式已经复验。
