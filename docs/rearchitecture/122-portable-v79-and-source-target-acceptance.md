# 便携包与归档源码定位：最终限定验收

本轮在`optimize_ccc@c807040`上继续直接实施。后端固定为v78，前端v79只修改`studio/src/SourceViewer.vue`及对应构建资源。先冻结[45号交互合同](ui/45-archived-source-target-visibility.md)，沿用原九导航、分栏、颜色、证据滚动区和固定人工区；没有重新设计页面。完整重构仍未完成，本文的PASS仅覆盖表内范围。

后续同日已收齐[123号v78完整回归](123-v78-full-regression-and-native-start.md)：1566 PASS/2联网SKIP，0失败/错误，6015.042秒。两份大型原生任务已实际启动；其最终结果仍待验。

| 阶段 | 实现的核心功能 | 变更文件 | 测试/场景ID | 状态 | 对应证据 |
|---|---|---|---|---|---|
| Phase 4 | 加载归档代码及跳行后，将所选行移到现有证据区内；只处理最新请求，卸载后不再更新 | `studio/src/SourceViewer.vue`、`ecra/studio/web/index.html`及JS资源 | U12/U19/U22局部；真实Chrome，实际导入库，原固件和原构建/SDK/任务数据根暂时移走 | PASS_SCOPED | [5组坐标/操作收据](acceptance/source-target-v79.json)、[实际控制器](acceptance/source-target-v79-controller.py.txt) |
| Phase 4 修复前对照 | 原归档数据可以读取，但所选main.c:3在可见证据区外 | 同一导入库、旧v77程序 | 数据读取PASS；目标行可见高度0px，不能算定位通过 | FAIL_VISIBILITY，原证据保留 | [修复前原收据](acceptance/source-target-v77-before.json)、[原截图](ui/screenshots/source-target-v77-before/01-source-without-originals.png) |
| Phase 6 v77完整回归 | 包内Ninja版本探测准入、工作字节CMake全量与Diff、停止/恢复等 | 冻结v77的4022文件，源及独立副本SHA不变 | 1563项：1561 PASS/2联网opt-in SKIP，6380.347秒，0失败/错误 | PASS_SCOPED，不含121号路径绑定 | [最终收据](acceptance/full-regression-studio-v77-final.json)、[原日志](acceptance/full-regression-studio-v77.log) |
| Phase 6 v77包内流程 | 内嵌Python 3.10.9及真实CMake/ARM/Git，实际ECRA.cmd启动 | v77 Portable | 29专项PASS/0跳过，2935.607秒；真实Chrome八组PASS；32265分发文件后验不变 | PASS_SCOPED | [最终补充](acceptance/portable-v77-final.json)、[29项原日志](acceptance/portable-v77-embedded-tests.log)、[Chrome原始字节收据](acceptance/browser-working-cmake-v77-raw.json) |
| Phase 6 v78包内流程 | 上述流程加121号受控外置ELF/MAP绑定 | v78 Portable；148应用文件匹配冻结源 | 34专项PASS/0跳过，2681.587秒；真实Chrome八组PASS；32279分发文件后验不变 | PASS_SCOPED | [最终补充](acceptance/portable-v78-final.json)、[34项原日志](acceptance/portable-v78-embedded-tests.log)、[Chrome收据](acceptance/browser-working-cmake-v78.json) |
| Phase 6 v79前端候选 | 原样复用经验证的后端及工具，重新构建和验证真实源码定位 | v79 Portable；148应用文件匹配冻结源 | 目录与中文ZIP各27检查、真实Chrome五组、实际ECRA.cmd认证API、32306文件完整后验PASS，无额外文件 | PASS_SCOPED，不计干净电脑/完整G7或G8 | [最终收据](acceptance/portable-v79-final.json)、[组装收据](acceptance/portable-v79-assembly.json)、[目录](acceptance/portable-v79-uncompressed.json)、[中文ZIP](acceptance/portable-v79-zip-extracted.json) |
| Phase 2/6 大型当前侧与整轮Diff | 原黄金冷原生扫描及当前活对象比较；真实改动INAV派生工程的完整基准、两个当前TU后中断及新scan_id恢复 | 冻结v78后端，独立数据根及16GiB自有Job | 1568项完整回归最终PASS；实际388TU准备PASS，两个正式任务已启动 | RUNNING / NOT_VERIFIED，最终回执未收齐 | [实际启动证据](123-v78-full-regression-and-native-start.md)、[120号合同及控制器](120-current-and-whole-diff-validation-contract.md) |

## 真实界面复核

同一导入权威库SHA为`59e105f1a8dddbd90a2b28cb0ff4a22915a94fcd3556b85983c1624ab3b74bbe`，前后均未变化。修复前1366×768中所选行位置为746.95–791.14px，证据区仅482.31–546.31px，实际可见高度为0。v79首次打开和切回后所选行位置为491.95–536.14px，完整44.1875px可见；1600×900下完整22.09375px可见。真实跳到第1行、再回第3行也通过。五次检查均保持文档滚动为0、四个决定/撤销按钮在视口内，确认者与理由草稿不丢。

已实际查看[1366修复后截图](ui/screenshots/source-target-v79/03-target-and-draft-1366.png)及[1600截图](ui/screenshots/source-target-v79/02-source-1600.png)。原件不可用期间，只读取独立导入包中的main.c归档；没有重新扫描或提交人工决定。测试最终恢复了两个原命名空间，控制台0错误、0外部请求。这不替代无系统工具的第二台电脑、全部调用图、极端长文本、Windows系统DPI或人工UAT。

`npm run build`的TypeScript检查与Vite构建通过；工作区[12项静态UI合同检查](acceptance/ui-contract-source-target-v79.json)也通过。第一次调用检查器漏传必需`--output`，仅返回usage/code=2，没有执行检查；补齐外置输出参数后实际执行通过，不将usage错误当产品故障或已执行测试。静态合同检查不能代替上面的真实Chrome操作。

## 版本、完整性与失败记录

v79清单SHA为`fb93a2bf295159edd51ffca2b038b65eb3e89e4c1a0fd9fdad9fe7555c2f012e`，后端v78清单SHA为`113465220a07a2ffcb354f07d761d9fecab2beab68b25fe345ec48126e7351cd`。全部474个Python/测试/依赖源码文件逐文件相同，28805个runtime/tools/wheels文件匹配v78已验证分发清单。34项和八组后端流程只按其未变范围继承，不称在v79重复执行，也不因前端改动取消正在运行的冻结v78完整回归或大型任务。

v77/v78原合并控制器都因测试程序对CMD尾部重复转义而最终FAIL；此前29/34专项和八组Chrome已实际通过。原[失败1](acceptance/portable-v77-controller-quote-failed.json)与[失败2](acceptance/portable-v78-controller-quote-failed.json)保持原字节。新[补充控制器](acceptance/portable-v77-v78-final-controller.py.txt)在外置目录创建ASCII辅助CMD，真实调用原`ECRA.cmd`，自有2GiB Job内认证请求`/api/scans`成功，之后重新逐个核对全部分发文件和ZIP。没有改包内程序或重写原失败；补充仅关闭启动测试程序的转义错误。v79使用同一已验证调用方式，单独留有[最终控制器](acceptance/portable-v79-final-controller.py.txt)。

当前便携候选入口：`H:/ECRAStudio-build-20261106-studio-v79/ECRA-Portable/ECRA.cmd`。ZIP为同级`ECRA-Portable.zip`，777311619字节，SHA256 `c8c72ed913103a1131eaaa46557b23ee7853eff4ed88161c517e2438fd39d5dd`；分发清单SHA为`4cc69160bc621f77196f57da99a6754fe0bca5757e280cd6466229701b89e893`。程序及工具不能与客户固件或长期数据根混放。源码修改后包内文档是冻结时版本；后续验收以仓库本文及最终原始收据为准，不能静默重打已封存ZIP。

仓库保存[逐文件证据拷贝清单](acceptance/stage-v79-evidence-copy.json)；原日志、脚本、JSON与截图按SHA核对复制，未复制会话令牌文件。完整原始证据仍在`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3`。

首次暂存后逐个读取Git blob核对，发现已有`browser-working-cmake-v77.json`受到`core.autocrlf=true`的CRLF→LF转换，SHA与原始浏览器收据不同；其JSON数据未变，但不能称原字节相同。保留旧Git文件，另存上述`-raw.json`并对本批新原始文件明确`-text`，禁止换行转换。[首次FAIL](acceptance/stage-v79-git-byte-first-failed.json)保留；[再次核对](acceptance/stage-v79-git-byte-proof.json)覆盖全部29个清单文件的实际Git内容，字节差异为0，旧Git文件未改。原始日志中的换行和空格不为代码格式检查而修改。该问题不影响包或产品测试，也没有修改测试结果。

## 资源结果与剩余门禁

| 指标 | 原保存后完整恢复/比较 | 外存比较 | 本轮最新当前侧/整轮Diff |
|---|---:|---:|---|
| Job提交峰值 | 27140870144 B，25.2769GiB | 1631346688 B，1.5193GiB | NOT_VERIFIED |
| 输出目录采样分配峰值 | 1974800 B | 1892028472 B | NOT_VERIFIED |
| 最终输出分配 | 1946128 B | 2544152 B | NOT_VERIFIED |
| 观察耗时（含原库后验） | 2041.312秒 | 2677.125秒 | NOT_VERIFIED |
| 完整比较输出 | 892字节 | 字节完全一致 | 尚无最终收据 |

上表原成对结果仅是[118号保存后同源完整双摘要消费](118-memory-comparison-final-acceptance.md)，不含源码改动，不是最新整轮冷扫描；最终输出也不是完整标准归档大小。最新标准归档、整轮磁盘峰值和扫描耗时待实际完成后单独报告。没有用25.28→1.52GiB代替整轮成绩或宣称提速，原权威库和历史未删除。原黄金冷原生完整对照仍以[115号v66](115-final-large-read-and-cold-acceptance.md)为最近已完成证据，不改称v78。

复现基础包检查：`<包内runtime/python.exe> -B <包内validate_portable.py> --bundle <包根> --work <新的外置验收目录>`。工作区完整回归命令为`py -3.10 -B -X utf8 -m unittest discover -s tests -v`，精确版本复验须使用对应冻结副本。上述归档UI/最终包控制器含本机数据路径与防覆盖断言；复跑必须使用新的工作目录和对应已验证导入包，不覆盖原收据。产品使用端无需Node。

其它G2工程继续按用户要求待验；32GB物理机、第二台干净离线电脑、系统DPI、真实模型及人工UAT均NOT_VERIFIED。跨环境严格报告FAIL及逐字段审计见[114号](114-portable-v71-typed-cold-reader-acceptance.md)，比较器未放宽。未提交CMake仍遵守117号限定准入；自定义生成命令、显式ELF/MAP混合闭包等未证明场景明确拒绝，不能称任意CMake未提交工程均支持。Phase 6及完整G1–G8仍未关闭。
