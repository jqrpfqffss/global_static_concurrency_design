# 最终 V9 界面关键证据

本目录保存原图逐字节副本与小收据。归档阶段仅只读核对既有证据并复制文件，没有启动浏览器/服务、修改产品、访问 INAV 或重新扫描。

正式 V9 ZIP SHA-256：`7a0e45b0f3dda3ee47d7759f9784ab66ca9f8fa089543157f64c9f9be9a6c03d`（785692863 B）；Python 引擎 `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`。Q405 两图来自真实解压成品，不是源码预览。native Diff 两图来自最终 V9 程序读取已有 V8 同引擎扫描结果，不能表述成 V9 重新执行了扫描。

| 图 | 运行/数据模式 | 准确图注 |
|---|---|---|
| [01-q405-final-v9-f411.png](01-q405-final-v9-f411.png) | FINAL_V9_PORTABLE / UNVERIFIED_ARCHIVE | 正式 V9 解压包；F411 长源码下展开填写区并普通滚动至按钮。项目 github_stm32_bare_metal、叶项 g_cli.command_list[*].name、定义 apps/cli/cli_simple.c:20、独立人工待确认状态与四个按钮同屏。未填写或签署。 |
| [02-q405-final-v9-nmi.png](02-q405-final-v9-nmi.png) | FINAL_V9_PORTABLE / UNVERIFIED_ARCHIVE | 正式 V9 解压包；从历史切换 resolved-nmi 的 shared，确认栏更新为本项目、本变量、main.c:1 与既有人工风险状态，四个按钮仍可见，没有残留 F411 身份。未签署或撤销。 |
| [03-native-diff-final-v9-confirmation.png](03-native-diff-final-v9-confirmation.png) | FINAL_V9_PORTABLE / LOCAL_SNAPSHOT / EXISTING_V8_SCAN | 正式 V9 解压包读取已有同引擎 V8 native Diff。shared 的两个读改写访问下方，确认区同时显示 中文 空格 Git 工程 · shared、main.c:3、人工待确认及四个按钮。发布记录静态已校验不等于全工程安全；分析仍 INCOMPLETE。未签署。 |
| [04-native-diff-final-v9-all-five.png](04-native-diff-final-v9-all-five.png) | FINAL_V9_PORTABLE / LOCAL_SNAPSHOT / EXISTING_V8_SCAN | 正式 V9 解压包读取同一已有 native Diff；退出详情并清空筛选后显示全部 5 项（shared、vectors 容器与 3 个安全叶项）。顶部仍分列影响清单 3 与保守潜在影响 2；全部 5 项不是全部安全或新一轮扫描。 |
| [05-q405-before-final-v8.png](05-q405-before-final-v8.png) | HISTORICAL_FINAL_V8_PORTABLE / UNVERIFIED_ARCHIVE / BEFORE_FIX | 保留的 V8 原缺陷画面：F411 长源码滚到填写/按钮处时，确认栏只有“当前：待确认”，变量身份离开视野。用于说明 Q405 修复前行为，不能作为 V9 仍失败的证据。 |

## 窗口与观察边界

- Q405 最终两图：`viewport:null`；独立读取实际内容 1447×631、outer/bounds1461×781@0,0，处于 screen avail1463×783 内。未调整 zoom/DPI。
- native Diff 两图：启动日志明确使用同一 `viewport:null` 配置，PNG 像素为 1448×632；原收据/日志没有保存可独立核对的数值 inner/outer/bounds。截图像素不等于已通过 eval 独立读取的 inner，不借用 Q405 的精确窗口数据。
- 1366×768、1920×1080 的原生窗口与 OS 显示缩放没有因本次归档增加通过范围。DPR 观察值不构成缩放验证。
- Q405 两图由独立检查者实际操作并查看；native Diff 由协调者操作，本归档检查者另行实际查看保存的两图。原 V8 before 也已复看。

## 数据与结论保持

- Q405：实际操作没有填写、签署或撤销，原 3 个人工 event_id 与 payload SHA 前后完全相同；27 条 CLI 命令退出码均为 0。
- native Diff：原收据记录静态文件 SHA `2db113e09143b3ea88939fdb62e3be4252b6d46e233fc2d90f9e6f4a471a6d41`，与同引擎 V8 实际扫描一致；人工事件仍为 0。本次归档核对该收据，没有重新读取或写入扫描数据库。
- 发布记录 `STATIC_VALIDATED`、阅读模式 `LOCAL_SNAPSHOT` 与分析状态 `INCOMPLETE` 含义不同。全部清单5项=1个疑似+1个容器+3个静态安全叶项；差异影响3、保守潜在影响2仍分别展示。不能把未列出、无需人工或静态发布校验解释为全工程安全。

## SHA-256

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| [01-q405-final-v9-f411.png](01-q405-final-v9-f411.png) | 66032 | `527e5489968f77ecb96e0367545ea85a831818575a757dfbff12edb2c6337630` |
| [02-q405-final-v9-nmi.png](02-q405-final-v9-nmi.png) | 63321 | `9b32e2288d381427314401e5a934858474bf723c588f173c6e8dfb94dfea7cf9` |
| [03-native-diff-final-v9-confirmation.png](03-native-diff-final-v9-confirmation.png) | 64997 | `0e587a4e3eadd2bd072e9555fd0436754d7996c1b8316599aee8564b6e2b2dbc` |
| [04-native-diff-final-v9-all-five.png](04-native-diff-final-v9-all-five.png) | 69044 | `5f45259fa3ac78c2d6506f147a8120372993cc01f329e1ac9c1f4cf5d379815c` |
| [05-q405-before-final-v8.png](05-q405-before-final-v8.png) | 63248 | `7f8d30ba9118bde67d7e53993a98771ffa35834e028aee103bfaffe497a53e41` |
| [q405-final-package-v9-acceptance.json](q405-final-package-v9-acceptance.json) | 4518 | `e4b0538f89f7ab22c0f8da43a0e6ffe62ff5225ae87bd535072e265bada01de2` |
| [native-diff-ui-final-v9-acceptance.json](native-diff-ui-final-v9-acceptance.json) | 5766 | `fb6de2ddbc3df9add14b48296bde1b117417896bd38a213f0d35235f4ecbfcc4` |
| [q405-review-events-comparison.json](q405-review-events-comparison.json) | 1217 | `c971063cbdc560b84080b4dc8200e12a9039c8af5d0125e574b56373880f54b2` |

精确来源、观察方式、尺寸与逐文件 SHA 同时保存在 [index.json](index.json)。原图/原收据未被覆盖。

## Q405 最终 V9 渲染视口补验

随后在同一正式 V9 包单独复验 1366×768 与 1920×1080 渲染排版。使用常规 Playwright resize，独立读取的 page.viewportSize/inner 与目标相符；outer1463×783 保持不变。因此仅补渲染通过，不增加相应原生窗口或 OS 显示缩放通过范围。

两图均已实际查看。项目、真实叶项 g_cli.command_list[*].name、定义位置与独立人工待确认状态完整，四个主要按钮都在渲染视口内；document.scrollWidth==clientWidth，无页面横向溢出。当前组合名称能单行放下，虽然实际样式为 white-space:normal/overflow-wrap:anywhere，也不假称已验证更长输入的强制多行。

此次没有填写或签署/撤销；18 条 CLI 操作退出码均为 0，原 3 个人工事件 ID/payload 哈希及三个既有 scan.db 的逐字节 SHA 前后相同。Chrome 已正常关闭，服务留给协调者停止。

| 补充文件 | 模式/图注 | SHA-256 |
|---|---|---|
| [06-q405-final-v9-render-1366.png](06-q405-final-v9-render-1366.png) | 正式 V9 包，1366×768 渲染视口。F411 真实长叶项的项目/变量/定义/人工状态与四按钮同屏，无截断或页面横向溢出；名称在本宽度下能单行放下，不构成额外超长名称强制换行验证。 | `f5060db71d6987c1dbb2ff787a9cef0b49723e90f6f6794c623285816e6d4f17` |
| [07-q405-final-v9-render-1920.png](07-q405-final-v9-render-1920.png) | 正式 V9 包，1920×1080 渲染视口。F411 真实长叶项的项目/变量/定义/人工状态与四按钮同屏，无截断或页面横向溢出；名称在本宽度下能单行放下，不构成额外超长名称强制换行验证。 | `ea7d5b2b0caf687b4c7499cd06e2061583bfed28dd533925fa809af2a6a4602e` |
| [q405-final-package-v9-render-acceptance.json](q405-final-package-v9-render-acceptance.json) | 小收据逐字节副本 | `a7f663125b27d2811cee6852edc1e818aaadc7c1aba4a14cadf1dc4a20653dbf` |
| [q405-render-review-events-comparison.json](q405-render-review-events-comparison.json) | 小收据逐字节副本 | `c3cf1e4fc3143f5726eeb0ed5f479bdd5a25168715d21c71ca25056fd97c75fa` |
| [q405-render-static-before.json](q405-render-static-before.json) | 小收据逐字节副本 | `342bb8a3834e1be784cd8164bc6c31dee3495daa3c98bb6053638787489c38b6` |
| [q405-render-static-after.json](q405-render-static-after.json) | 小收据逐字节副本 | `49c83787eb63a7f6bf104ad485e615420fb6bac9e749d765bd3d8ead619e6f2f` |

本次新增完整原始日志位于 `output/quality-20261108/continuation/q405-final-package-v9-render`，没有追加旧 native/source/V8 验收日志；旧索引修改前字节也保留在该目录。
