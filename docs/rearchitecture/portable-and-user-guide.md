# ECRA Studio 开发预览操作与复现

当前阶段候选v12入口：`H:/ECRAStudio-build-20261101-studio-v12/ECRA-Portable/ECRA.cmd`；ZIP在同一父目录。目录/中文解压各26命令、包内Python3.10.9真实Chrome主流程15项和配置往返7项通过，109运行时/前端/许可文件与冻结a8e源相同，完整回归1214项中1212通过/2项联网opt-in跳过。ZIP535,735,013B，SHA-256为e80df57ae6cfaf84469713d401da6a3aa2e8df9cdeb4ec18f2af9639d05c85ae。包含挂起启动/Job及整机提交保护、配置同步；未包含随后未提交的字符串共享/独立Git实现。完整重构/大型工程/干净机门禁仍未通过，旧包保持封存。

首次保存配置后，可在向导第4步“开始此配置扫描”；之后在首页“按此配置重新扫描”使用同project/profile当前已保存版本，新扫描独立发布。高级YAML返回表单时回填现值，再前进只同步实际改动；原文有独立哈希备份可恢复。共享受控映射等无法安全改写的配置会明确拒绝并留在高级编辑器。修改或恢复后须重新检查保存；生产未提交源码隔离仍受阻断，不应为绕过门禁改客户源码/暂存区。

协作实际走法：A导出“人工确认增量”→B在“数据与共享”导入→分歧时在“人工历史”核对双方确认者、设备、理由→填写新依据并选择合并结论。合并新增审计事件、原分支保留；不填依据会拒绝。可再次导出完整包供另一端继续确认，重复增量幂等。已在本机两独立数据根/真实浏览器验证；第二台物理电脑与工程师盲测待验。

**当前为真实扫描、归档与确认工作流的开发候选，完整发布门禁仍未通过。** 新 CLI `run` 默认使用独立数据根和 SQLite；`--legacy-output` 仅显式兼容与黄金比较。大工程资源、dirty 隔离、完整 U01–U24 和干净机验收尚未完成。

## 启动

开发机：`py -3.10 -m pip install -r requirements-studio.txt`，然后双击仓库 `ECRA.cmd`，或运行 `py -3.10 -B run_ecra.py ui`。前端编译资源已经随源码提供，运行时无需Node。关闭启动窗口或Ctrl+C停止本地服务；浏览器标签关闭本身不结束前台控制台。服务只绑定127.0.0.1随机端口，启动URL包含本次临时会话，不能沿用旧会话。

指定其他盘：先设置 `ECRA_DATA_ROOT=H:/ECRAStudio-data`，或运行 `ECRA.cmd --data-root H:/ECRAStudio-data`。默认 `%LOCALAPPDATA%/ECRAStudio/data`。不要把数据放在固件或可被升级覆盖的安装目录。普通查看/确认不要求系统工具链。

Portable：预览包内 `ECRA.cmd` 双击进入GUI，显式CLI参数继续调用原命令。内置runtime/Python3.10.9和离线后端依赖、Vue静态资源/许可证；不包含Node、OpenCode或客户结果。实际目录/ZIP/验收路径以 `evidence/portable-result.json` 为准。干净机器、完整新扫描工作流尚未验证，不将本机打包通过称作G8全部通过。

## 当前可用流程

1. “数据与共享”选择完整 `.ecra-report`；校验成功后从项目概览或历史打开。无原固件时显示归档证据模式，仍能浏览完整已归档字段、访问/调用关系/未知条件/代码与来源索引。
2. 点击静态卡片下钻；变量工作台服务端搜索与分页。时序与访问、调用与保护、归档源码、人工历史分组按需读取，每段有哈希/总数/继续入口。未归档源码明确提示不可用。
3. 填写声明确认者与依据，选择确认有风险/确认无风险/暂无法确认；处理状态独立选择。确认无风险必须有依据。提交成功才显示已保存；关闭重开后从“继续上次位置”恢复。撤销需理由，新增审计事件。
4. 导出完整包或人工增量。另一个数据目录/电脑可继续确认再导回；同事件幂等，不同并行分支进入冲突，查看人工历史并填写依据后显式解决。不得把接受风险当安全。
5. 工程配置四步登记固件、CMake/Ninja目标或真实编译数据库、范围和固定 Diff refs；检查后保存独立 profile。配置检查本身不冒充真实构建成功。进入“扫描任务”选择 profile 和资源预设，启动真实扫描；构建、完整输入闭包和发布前后校验由原引擎执行。未提交字节隔离尚未完成，当前正式流程明确拒绝 include_uncommitted。
6. 任务中心显示真实阶段、TU计数、进程树工作集/私有提交/峰值提交、系统可用物理内存与提交、盘空闲和分段日志。可安全停止，再从已校验TU缓存恢复；全局求解从入口重做，不宣称任意指令处续跑。自动软目标12GiB、峰值提交16GiB不是32GB实机性能验收结论。接近阈值降并行或请求停止，Windows Job Object限制本任务进程树。
7. 可选 OpenCode 页面读取真实队列和原始收据，可启动全部候选或仅技术失败项；需要原源码和本机有效检查点。导入包只能查看归档时，不提供重新证明按钮。TECH_FAILED不改变静态分类，未配置模型不等于扫描失败。
8. “数据与共享”可生成空间整理预览；候选仅含无引用CAS和受控可重建TU缓存。核对全部路径后勾选确认隔离，可恢复原路径；永久释放需再次单独确认。出现新引用、内容变化、占用或锁冲突时停止并保留现场。有效历史、人工记录、构建与导出包不在回收范围；目录大小为逻辑字节，不能当保证物理释放量。

9. 旧`.ecra`/工具workspace在“数据与共享”填写旧结果目录及原记录中的工程目录，先检查归属，再开始只读迁移；后台显示实际捕获文件与转换/校验阶段，完成后打开结果。原数据保留；完整facts.json与报告流式入库，其他未知/复核文件以原字节审计保留。缺完整facts.json、活锁/WAL或归属不符会明确失败，不能把旧facts.db猜测还原为完整证据。旧决定未经合同核验不自动套成本轮安全；旧文件清单和文本/十六进制可分段查看。旧源文件缺失时不从当前工程冒充补齐。同源同内容重复迁移保留已提交的人工确认。

旧`.ecra`和工具workspace必须保留，不能把旧目录随意改名成新包。大型迁移、双来源历史合并、缺证据降级Viewer与完整U21仍未通过。同工程、同profile的新扫描保留旧确认的来源及完整事件历史；证据指纹变化或不确定时显示“需重新确认”，旧SAFE不冒充本轮决定。当前指纹采用保守全库绑定，可能产生额外复核，禁止仅按名称继承。

## 复现命令

```powershell
py -3.10 -B -m unittest tests.test_scan_store tests.test_human_reviews tests.test_report_package tests.test_studio_api tests.test_studio_workspace tests.test_bounded_extraction -v
py -3.10 -B scripts/validate_ui_contract.py --output docs/rearchitecture/evidence/ui-contract.json
py -3.10 -B scripts/prepare_studio_wheels.py --cache .tools-cache
py -3.10 -B scripts/prepare_studio_wheels.py --cache .tools-cache --offline
```

开发时先运行 `py -3.10 -B scripts/collect_studio_licenses.py --cache .tools-cache` 收集经哈希校验的离线wheel/Vue许可到studio/public；在studio目录执行 `npm.cmd ci`、`npm.cmd run build`。后续干净Vite构建会自动复制许可证。安装包运行端不需要这些开发工具。`build_portable.ps1 -OutputDir <全新目录>`拒绝覆盖旧包并执行目录/ZIP验收，轮子必须先有发布者SHA收据。

从不含.git的冻结源码构建时，支持旁置`<源码目录>.sha256.json`，格式为passed/head/files数组（每项file/size/sha256）。包版本标识前逐文件验证实际工作字节、拒绝越界或篡改，包内SOURCE-SNAPSHOT.json保留完整来源清单；不会凭目录名猜测提交。这使后续代码开发与已冻结候选打包分离。实际完整打包验收仍以每个新包独立收据为准。

本轮黄金与浏览器：

```powershell
py -3.10 -B scripts/validate_studio_baseline.py --baseline H:/ECRAStudio-data/rearchitecture-20261031/baseline --data-root <全新数据目录> --receipt <收据.json>
py -3.10 -B scripts/validate_studio_native_equivalence.py --baseline H:/ECRAStudio-data/rearchitecture-20261031/baseline --candidate H:/ECRAStudio-data/rearchitecture-20261031/final-engine --name <新的比较目录名> --receipt <收据.json>
py -3.10 -B scripts/validate_studio_ui.py --package H:/ECRAStudio-data/rearchitecture-20261031/studio-acceptance/exports/golden-f030.ecra-report --work <全新测试目录> --evidence output/playwright/<新轮次> --firmware H:/ECRAStudio-data/rearchitecture-20261031/baseline/firmware --compile-database H:/ECRAStudio-data/rearchitecture-20261031/baseline/compile_commands.json --native-scan --ai-failure
```

测试工作目录必须新建，避免覆盖已有测试/确认数据。完整Playwright收据、失败截图、视频与trace保存在output/playwright；它们是自动操作证据，不是工程师盲测或目标板验证。

配置同步（源码已实现；封存v10不含此功能）：普通目录字段每行一个，逗号和空格保留。已有配置在第4步点“上一步”，表单会先读取当前完整YAML；再次前进只同步实际修改字段，原文备份位于独立数据根settings/profile-drafts，可点“恢复同步前原文”。切换构建方式会替换该构建分支，界面明确提示并保留完整前文。共享映射/合并键无法证明仅影响本字段时保留高级编辑，不猜测展开。修改或恢复后重新检查保存才能扫描；工程配置可用名称打开，新建配置不会覆盖已有配置。详细检查可展开，表单内容独立滚动，底部操作保持可见。

上述配置同步现已包含于阶段v11：双击H:/ECRAStudio-build-20261101-studio-v11/ECRA-Portable/ECRA.cmd，包内Python/Chrome主流程15项与配置7项通过；见evidence/portable-studio-v11.json。其冻结4e6完整测试在Windows venv出现4个失败断言（故障注入PID与PE夹具），后续源码已修复并有专项证据，仍须完整复跑及新包验证。v11不含后续挂起启动Job所有权/整机提交保护，不能冒称所有发布门禁已通过。


## 最新封存阶段包 v13（完整发布门禁未通过）

启动H:/ECRAStudio-build-20261101-studio-v13/ECRA-Portable/ECRA.cmd，或解压同目录ECRA-Portable.zip。ZIP 535,745,045B，SHA-256 3f23a7022307222380e287302fe7dc7ffed47e40f6376795deab6ddb2289d819；具体收据见evidence/portable-studio-v13.json。真实Git版本选择可分页/搜索本地refs，显示HEAD、提交和未提交范围；保存后扫描重新固定输入。只覆盖已提交版本，未提交完整隔离仍未完成。任务状态文件被Windows短暂独占时显示重试提示，读取恢复后自动消除提示，原结果仍可打开。

此包完整回归1230项（1228PASS/2联网SKIP），包内Chrome主流程16、Git6、配置往返7项及目录/ZIP各26命令通过。尚无干净离线机、系统高DPI、物理第二台电脑与工程师盲测通过记录；大型G1–G4尚未关闭。

源码后续支持：构建步骤可选择按引擎默认/明确开启/关闭编译器标准头文件探测；默认仍为CMake开启、编译数据库关闭。分析范围步骤可编辑main/ISR/任务等入口ID/类型/逐行函数、添加/移除和分页。仅编辑所选字段；高级规则保留，移除入口会移除整段入口，下一步可恢复同步前原文。共享别名无法证明局部编辑时该部分显示只读原因，保留高级YAML。此功能尚未进入上述v13包，见context-forms-v2.json。
