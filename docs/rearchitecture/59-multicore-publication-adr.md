# 多核合并消费者迁移：实施合同

2026-11-03，执行前HEAD5bcfa01。真实审计发现`common.read_json`已能把旧逻辑名`facts.json`映射到`scan.db`；`multicore.combine`仍调用旧`generate`，CLI还强制`results/multicore`位于固件内。该写入路径违反H2/H3，不能把通用读取适配称为消费者全部迁移。

本次只迁移多核合并的输入固定、输出和发布边界。原ELF32 ARM符号解析、共享RAM地址/长度匹配、variant身份映射、上下文/访问/调用处理、`analyze`及`GS-CROSS-CORE`规则保持原实现。组合结果仍为INCOMPLETE，不能称为独立多核原生扫描或硬件验证。

正式输出复用`formal_workspace/WorkspaceResolver`，只允许独立数据根`scans/<scan_id>`中的新目录；默认自动生成ID，显式`--output`必须为上述绝对路径。旧固件内输出拒绝并给迁移提示，不覆盖任何旧目录。输入旧事实只读兼容，新输出仅权威`scan.db`、独立`reviews.db`和必要审计，不生成旧facts/HTML/Markdown。完成输入复验、全图深校验及审计对象校验后最后发布manifest，不更新任何单核心profile的latest指针。

输入配置、完整静态事实文件/权威库及链接ELF均做前后完整SHA核对；配置和ELF原字节作为审计留存。旧输入缺原源码归档时不补造源码能力：合并结果标明派生来源、不提供重新OpenCode证明或原生重新扫描能力；全部已有合并事实仍可在同一GUI协议中查看、人工确认和完整包传递。真实多核工程、生产内存预算、向导多核编排和完整G2仍待验。

实施验收：新旧组合函数同输入完整有序事实与既有规范化报告差异0；私有/共享符号及PARTIAL/FAILED覆盖保持；新结果GUI协议/确认/标准包往返；固件及原扫描不变；输入中途变化和发布失败不生成有效manifest、不覆盖上一有效结果。测试与真实运行收据在取得实际结果后补充。当前状态IN_PROGRESS，不能由本合同直接关闭Phase3。

## 已取得的实施证据

最终多核模块SHA e8579a719bed38c0c19bc54d9530fe1bed92cd067bb3df5c24b9b49db9021983。没有修改任何分析/判定模块。界面仅在既有状态带增加真实“派生结果证据模式”，由服务返回完整来源说明，保留既有布局/颜色/主操作；不将新派生结果误标旧归档，也不展示无实际能力的复核主按钮。

| 范围 | 实测 | 收据 |
|---|---|---|
| 专项与相关回归 | 51PASS，26.930s；其中新增9项，真实Clang事实配合明确声明的ELF/故障夹具；覆盖新旧输入、独立根、输入变化、损坏图、半发布、PARSED/PARTIAL/FAILED、确认及标准包 | [专项](evidence/multicore-publication-focused-v1.json) |
| 旧版完整对照 | e69原组合器与本模块，使用相同获准F030完整图及链接ELF的两个声明别名；完整有序事实30918d06…、既有规范化报告18ef60a4…差异0，全图深校验及输入SHA通过，56.703s | [完整对照](evidence/multicore-exact-f030-v3.json) |
| 当前源码GUI | 真实Chrome1366×768，精确对象、暂无法确认提交、重开后点击继续上次位置、原生浏览器下载及严格完整导入4组PASS；已有2个验收事件完整保留，再增1项；126份运行时/前端文件前后SHA不变，35.203s | [GUI](evidence/multicore-publication-ui-v5.json) |
| 失败原件 | 最初测试导入了整个ProjectTest、夹具缺TU/source_file、短路径断言错误；三次浏览器初轮分别为中文标签断言错误、重复文本选择器错误、误假定重载会自动打开详情。实际保存的事件/数据/trace不删除，按产品合同点击“继续上次位置”重验 | [测试失败](evidence/multicore-publication-test-failures-v1.json)、ui-v1/v2/v3-failed-audited收据 |

该F030输入对只是发布等价验收，未建立真实双核板工程，不计为G2新项目。现有全量事实仍在组合器中恢复，未完成外存组合或生产内存预算。当前模块完成独立发布迁移，但**完整Phase3/H2/H3仍未通过**：正式dirty隔离/强写保护、剩余全消费者审计和恢复矩阵、多核向导编排、真实双核输入仍有待完成。v32 Portable不含本变更；新冻结整套1401项与新打包另验。

复现核心回归：`py -3.10 -B -X utf8 -m unittest tests.test_multicore_publication tests.test_multicore tests.test_studio_api tests.test_report_package tests.test_scan_store -v`。实际黄金比较驱动保留在`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/probe-multicore-exact-f030-v3.py`，输入/输出/完整日志与收据同目录；不能复用已存在的输出目录覆盖旧证据。

正式CLI示例：`py -3.10 -B -X utf8 -m ecra.multicore --project H:/approved/firmware --input CM7=H:/profiles/cm7.yaml --input CM4=H:/profiles/cm4.yaml --elf CM7=H:/build/cm7.elf --elf CM4=H:/build/cm4.elf --shared-region 0x38000000:0x10000 --data-root H:/ECRA-user-data`。示例路径必须替换成获准工程；输出真实scan_id/scan_path，在使用同一数据根的Studio打开。此CLI接口已迁移，普通用户的双核向导尚未实现，不将CLI示例称为完整GUI验收。

[实际对象工作台](ui/screenshots/multicore-publication-ui-v5/01-derived-canonical-object-real-workbench.png)、[人工声明](ui/screenshots/multicore-publication-ui-v5/02-real-human-declaration.png)、[实际下载](ui/screenshots/multicore-publication-ui-v5/03-actual-complete-browser-export.png)。自动化操作不代表工程师UAT或硬件复现。


v4的4项功能已通过，但截图捕获时仍有短暂的详情请求。v5额外等待实际activity结束后重新验收和截图；原v4收据/截图保留，不将加载画面当作最终可操作画面。
