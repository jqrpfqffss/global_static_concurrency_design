# V8 Windows 完整离线构建与解压包 Git 回归

当前状态：**完整离线构建、双轮实际运行门禁、输入后验、组件复核及最终解压包 Git 回归已通过**。实际 GUI、独立 ARM tiny 和整个项目的最终验收由协调者分别记录；这里不会把旧 v4/v6 的成功记录改成 v8 实际运行。

| 身份 | 固定值 |
| --- | --- |
| 源码 | `H:/ECRA-quality-20261108/continuation-builder-source-v8`，4,370 文件，302,936,047 字节 |
| 源码快照 SHA256 | `969b1f85fb8593e6dd68a766ce628707fd5d189fea1b59922e76c6c601c285d2` |
| 核心 | `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea` |
| 前端 | `index-DHpgztut.js`，CSS 沿用冻结值 |
| 打包脚本 SHA256 | `69aeebd31b85dd020375ca55bc50aeb04f3c710fab219b2d33c3799a414185cd` |
| 新输出 | `H:/ECRA-quality-20261108-offline-build-v8` |

已实际完成新源码全部 SHA 核对、输入缓存与已有三个 ZIP 的前后核对，以及 Windows PowerShell 5.1 `OfflineCheck`（exit 0，59.687 秒）。原 `build_portable.ps1` 完整执行 exit 0、1,190.063 秒；包含前后 SHA 的外部控制器总计 1,370.563 秒。没有替换旧包、复制旧包后覆盖或跳过 ZIP 解压门禁。

正式 ZIP：`H:/ECRA-quality-20261108-offline-build-v8/ECRA-Portable.zip`，**785,692,766 字节**，SHA256：

```text
b4590047afd32bfe3beb803b7a934ae52c893daf3d12a4fbe2c2ff456880ab1a
```

| 已验证项 | 实际结果 |
| --- | --- |
| 原未压缩目录与 ZIP 中文空格临时解压目录 | 各全文件 SHA + 27 条实际命令 PASS；每轮21条exit 0、6条按原命令契约保留exit 2，不能将这些结果说成全工程完整无风险 |
| 保存与输出隔离 | 两轮保存命令静态事实不变，包内均无 runtime-data |
| 冻结输入 | 4,370 源码文件、27,921 缓存输入文件前后全部 SHA 相同，首轮local ZIP、v4 ZIP、v6 ZIP SHA 均不变 |
| ZIP 与生产代码 | 32,691 内容文件加清单，共32,692文件；名字/大小/重复检查通过，154个 `ecra/` 文件与final-engine-v8逐SHA相同 |
| 组件继承 | tools全部27,772文件与v4逐SHA相同；runtime1,027文件相同，仅3个新pip入口及对应3份RECORD不同；Python/libclang/ARM GCC/MinGit/CMake/Ninja关键文件另取实际SHA一致 |
| pip入口差异 | 三个EXE内的`__main__.py`与v4相同，嵌入本次解释器路径；不声称整棵runtime字节相同 |

外部控制器 [run_offline_build_v8.py](../../output/quality-20261108/continuation/run_offline_build_v8.py) 正常 import 未改的原命令 helper；仅设定新路径及输入审计值。控制器移除自身继承环境中全部大小写的 `PSMODULEPATH`，Windows PowerShell 5.1 使用自己的标准模块目录。产品 PS 脚本保持冻结字节。缓存组件、下载、wheels、完整 MinGit 的前后 SHA 与可写诊断收据分开记录，原 `.tools-cache/local-tools.json` 与 `preparation-result.json` 可以按原准备流程重新生成。

完整构建要求未压缩目录和中文空格临时解压目录分别执行全文件 SHA 校验与 27 个实际隔离命令，包含 MinGW/Ninja 编译执行、真实 ARM 构建与扫描、SQLite 权威库、禁 AI 接口、报告和状态，且包内不能产生工作数据。通过后原脚本才将 candidate.zip 改为正式 ZIP。

正式 ZIP 已由协调者另行解压到 `H:/ECRA-quality-20261108-offline-build-v8/解压 终验/ECRA-Portable`，CRC、清单、154生产文件、59指南链接等核对通过后才触发本轮实际 Git 回归，未提前使用部分解压目录或未压缩包顶替。

已用这份解压包内 CPython3.10.9 和完整 MinGit 执行冻结的 `test_readonly_git_admission.py` 全部 18 个方法：6 个 ReadonlyGitTests、6 个 ContentNameEvidenceTests、6 个 GuardedAdmissionTests，**18通过、0失败、0错误、0跳过，测试99.104秒，含包前后审计的外层122.453秒**。原 FAIL/ERROR 两方法均实际通过；另覆盖 stat-only/真实内容区分、重命名、二进制、空文件、模式变化、外部 diff/textconv 不执行、协议缺失失败，以及源码/ACL/HEAD/index 改后恢复仍被拒绝。测试文件只从冻结源码读取，不进入用户运行包。

外部 QA 控制器 [run_packaged_q207.py](../../output/quality-20261108/continuation/run_packaged_q207.py) 和 [worker](../../output/quality-20261108/continuation/packaged_q207_worker.py) 已保存实际启动 argv、完整安全子环境、Windows-only 初始 PATH、Git 版本及 SHA、Python 路径与版本、`ecra.__file__`、实际 engine 摘要、测试文件 SHA。子环境由安全 allowlist 构造，**不设置 GIT_CONFIG_NOSYSTEM/GLOBAL 等覆盖**；仍读取 Git 正常默认文件配置，并另存有关语义键的来源，不能从另一控制器推断环境。运行后核对包文件名字/大小、生产文件和关键二进制 SHA 不变。该检查不冒充第三次全部工具字节 SHA，已有两轮全文件门禁另有原证据。

实际启动的外层控制器也使用本包 `runtime/python.exe -X utf8 -B`；worker启动收据证明 Python3.10.9、`ecra.__file__`位于该解压包、核心为2b9e8750…、MinGit版本为 `git version 2.56.0.windows.3`，Git cmd入口和ucrt64实际后端均在该包内。测试文件SHA为 `8b457aaa787a859e766f283dcd8d6da3dc0c891724b38f13ababf6392dcba18a`。测试前后32,692个文件的名字/大小、154个生产文件SHA，以及Python/Git入口/Git后端/libclang SHA均未变化；完整18个被选方法ID也已保存，包含原两个失败方法。

基线证据：

- [builder 冻结](../../output/quality-20261108/continuation/builder-frozen-v8.json)
- [输入基线](../../output/quality-20261108/continuation/offline-build-v8-intake.json)
- [原生命令收据](../../output/quality-20261108/continuation/offline-build-v8/receipt.json)
- [完整输入后验](../../output/quality-20261108/continuation/offline-build-v8/input-postflight.json)
- [双门禁、ZIP及组件独立复核](../../output/quality-20261108/continuation/offline-build-v8/build-component-audit.json)
- [最终解压包 Git18 精确启动收据](../../output/quality-20261108/continuation/portable-v8-q207/launch-receipt.json)
- [实际 Python/Git/模块/环境身份](../../output/quality-20261108/continuation/portable-v8-q207/worker-startup.json)
- [Git18结果与文件后验](../../output/quality-20261108/continuation/portable-v8-q207/worker-result.json)
- [完整原始 unittest 输出](../../output/quality-20261108/continuation/portable-v8-q207/unittest.log)
- [Git默认相关语义配置来源](../../output/quality-20261108/continuation/portable-v8-q207/git-semantic-config.json)
- 原生日志目录 `output/quality-20261108/continuation/offline-build-v8/`。

既有真实工程与旧包范围见 [v4 新包原生 F030/MinGit 链路](continuation-portable-v4-native.md) 和 [v6 完整构建](continuation-offline-build-v6.md)。最终组件继承只依据实际 SHA 相同项；pip 生成入口及 RECORD 可能含本次解释器路径和生成 ZIP 元数据，不声称整棵 runtime 相同。在线 OpenCode 供应商调用仍为外部环境缺口，禁 AI 入口通过不等于在线 AI 复核通过。
