# Portable v17 与真实1000项确认验收（2026-11-02）

这是efc8556的独立实包收据，不代表完整重构完成。后续工程身份栏变更不包含在此包中。完整阶段仍BLOCKED：G1大型逐关系对照、G2其他真实输入、G3/G4性能、生产H2写保护/dirty隔离以及物理环境/UAT未关闭。

| 阶段 / 目标 | 实现与实际结果 | 状态 | 证据 |
|---|---|---|---|
| Phase 2/4，完整当前回归 | 冻结1034文件，efc8556；1287项中1285 PASS、2联网opt-in SKIP；1884.521s；运行前后源码/测试副本SHA无差异 | PASS，限定此快照 | [完整收据](evidence/full-regression-studio-v17.json) |
| Phase 4/6，实际Portable | 内置Python3.10.9；目录与中文ZIP解压各27命令（21个exit0、6个预期INCOMPLETE exit2）；117个程序/静态资产源文件逐字节匹配冻结源；分发清单29364文件SHA已验 | 实包子范围PASS；G8物理干净机待验 | [封存收据](evidence/portable-studio-v17-seal.json)、[分发SHA](evidence/portable-v17-files-verification.json)、[目录](evidence/portable-v17-cli-uncompressed.json)、[中文解压](evidence/portable-v17-cli-zip-extracted.json) |
| U02/U05，真实构建门禁 | 实包预检查8项：实际全TU命令/编译器/输入、缺编译器阻断、修复后真实原生扫描、深路径下Release/demo真实ARM对象；不恢复旧HTML/JSON | PASS，已验工程范围 | [预检查8项](evidence/browser-portable-v17-preflight.json) |
| U05，缺CMake/Ninja/Git | 独立故障工具目录，真实Chrome/API/程序；3种具体错误字段/路径/修复、扫描产物未创建、42个原固件文件不变 | PASS，源码efc范围；非干净机 | [故障注入3项](evidence/browser-missing-tools-v1.json) |
| U16，1000个真实对象分批确认 | 原版完整INAV原生图17831825408字节的独立逐字节副本；1000个不同UNKNOWN对象；350/700/1000处真实服务重启并继续；1000独立不可变事件与原图/静态图全SHA不变；2862.984s含复制/末次校验 | PASS，真实实包UI容量；非新版原生扫描、非UAT | [收据](evidence/browser-portable-v17-human1000.json)、[截图](ui/screenshots/portable-v17/human1000-batch-1000.png) |
| U20/U21，协作与迁移 | 双独立服务7项协作；完整旧迁移6项；缺证据原件Viewer6项；全部通过同一标准包协议，不补造可信变量/安全证明 | 已验子范围PASS；U21巨型双旧来源仍待验 | [协作](evidence/browser-portable-v17-collaboration-v2.json)、[完整迁移](evidence/browser-portable-v17-legacy-v2.json)、[降级](evidence/browser-portable-v17-legacy-degraded.json) |
| G7，全部用户场景 | 24行完整场景逐项状态；10 PASS / 0 FAIL / 14 NOT_VERIFIED；模块PASS不等于全部场景完成 | FAIL，14项尚未完整验收 | [逐项表](ui/21-user-scenario-status-v17.md)、[机器表](evidence/user-scenarios-v17.json) |

13组真实Chrome实际通过的断言数分别为：sample10、main16、profile7、contexts8、directories7、git6、capacity9、preflight8、coverage8、legacy6、legacy-degraded6、collaboration7、launcher4。它们有场景重叠，不作为另一套独立单元测试总数。全部收据与截图在封存收据中可定位；trace/video及大数据保持外置。

首轮失败全部保留：[示例导入30s超时](evidence/browser-portable-v17-sample-first-failed.json)、[启动器导入30s超时](evidence/browser-portable-v17-launcher-first-failed.json)、[协作控制器读取半写session](evidence/browser-portable-v17-collaboration-first-failed.json)、[旧迁移测试输入先触发数据根重叠拒绝](evidence/browser-portable-v17-legacy-first-failed.json)。前两项使用相同冻结控制器及相同期限在新根重跑通过，未延长超时或修改程序；并发HDD负载下的响应时间问题仍保留。协作控制器只等完整JSON发布后再认证；迁移控制器改用独立空目录，继续精确断言归属不符，未放宽边界校验。

| 同一INAV固定输入 | 旧版e69原生黄金 | 新版v8冷原生 | 分类保留诊断v2（11:01快照） |
|---|---:|---:|---:|
| 状态 | 有效INCOMPLETE，原始只读备份完整 | FAIL，exit3，分类时内存不足，无有效归档 | RUNNING，分类结束、发布中；24GiB实验预算 |
| Job提交峰值/字节 | 29805875200 | 17180913664 | 18449494016，已超16GiB目标 |
| 树工作集峰值/字节 | 29537386496 | 17089003520 | 18452652032 |
| 采样输出逻辑峰值/字节 | 46427649982 | 10773364118，失败现场 | ≥20938334860，增长中，含独立恢复缓存 |
| 最终标准完整归档 | 旧目录46427649982字节，非新协议包 | 无 | 尚无，不可用中途数据库计算收益 |
| 原生执行耗时/s | 12542.188 | 4810.313后失败 | ≥7460.969且仍在发布；非冷启动性能 |
| 完整同输入语义差异 | 原JSON与其完整图逐字段摘要一致 | 未生成可比有效结果 | NOT_VERIFIED |

机器为64GiB、H/I同一SATA机械盘，不是32GB物理机。采样磁盘量不含全部目录/MFT/ADS，不能冒充完整物理G4。17.8GB原版比较图是原数据转换，不是新版标准归档或≥70%缩减；554445191字节的软件ZIP也不是扫描结果包。

新诊断显示第一个变量分类前Private Bytes已达16627683328字节，此时issue/gap身份缓存均为0；因此不能把全局准备阶段的大工作集简单归因于分类缓存。后续必须细分调用/访问/保护准备的实测，并在不改判定语义的前提下减少工作集。未在此阶段盲改受保护算法。

实际入口：`H:/ECRAStudio-build-20261102-studio-v17/ECRA-Portable/ECRA.cmd`；ZIP SHA-256 `4296e6cec3acc8f78007fee81185dc524a70ca11a6f18e37558b8602bd0b2e67`。全套：在对应冻结源执行 `py -3.10 -B -X utf8 -m unittest discover -s tests -v`。U16复现入口为 `scripts/validate_human_batch_ui.py --help`，必须显式提供获准原生比较图、实包、包内解释器及新的隔离work/evidence目录；不会扫描未授权固件。

仍未通过：H2生产写保护/dirty完整固定；全局merge/analyze与saved消费者的外存工作集；精确跨版本继承；图形化数据根搬迁；大规模双旧目录迁移/全故障矩阵；另外两类G2输入按用户决定待验；物理32GB、干净离线PC、第二台物理机、Windows原生DPI、真实OpenCode联网及5–8工程师盲测。`all_gates_passed=false`。
