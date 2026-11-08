# 续验：新构建产物上的三工程全量分析

本记录补充[完整固件构建](continuation-build.md)，采用本轮真正完成编译与链接的新 CDB、ELF 和 MAP。原工程、原便携 ZIP 与构建源码副本均保留；每工程使用新的数据根，不注入历史状态。

## 固定输入与闭包

配置位于 `H:/ECRA-quality-20261108/continuation-final-projects/configs/{f030,f411,cdc}.json`，均明确开启 `auto_system_includes:true`、绑定解压候选中的真实 `libclang.dll`，关闭本次不请求的 AI 推理，使用两个提取进程。

| 工程 | 新 CDB 的真实来源 | 当前固件输入 | 排除与边界 |
|---|---|---|---|
| STM32F030 | round5-f030-objects，4 次真实对象编译后完整链接 | 4C、main.elf/main.map | 原源码 `cmsis/core_cm0.h` 声明两个优先级位，配置显式对应；没有板级运行 |
| STM32F411RE CLI standalone | round3-f411，原 GNU Make 的 46 次成功编译、一次完整链接 | 24C，真实 cli_simple_standalone.elf/.map | CDB 其余 22 源没有进入该固件的链接输入，保留原数据库并用实际 linked_objects 过滤 |
| STM32CubeF4 CDC | round1 中文空格源码、外置 MinGW 构建，CMake 实际生成 CDB40 | 39C+1ASM，真实 firmware.elf/.map | HAL/CMSIS 与中间件作为依赖参与调用恢复，变量定义清单按原配置聚焦 Application/Src 与 App；ASM 只记录支持边界 |

F411 的 24 项不是从旧数据库或文件夹名称推测。先读取真实成功的完整 GCC 链接 argv，确认三个直接对象；再逐项读取构建日志中原始 `arm-none-eabi-gcc-ar rcs` 命令，并实际运行包内 `arm-none-eabi-ar t` 核对成员及顺序。真实 MAP 的“Archive member included”段选中 21 个工程归档成员，经原 AR argv 唯一映射到实际对象，形成 24 个输入。每项都匹配原 CDB46 的实际输出路径。另记录 MAP 中 newlib/libgcc 等预编译依赖的 SHA，不声称其源码已经覆盖。

链接时 LTO 与 section garbage collection 可能继续移除符号；本闭包表示真实链接输入的翻译单元，不等于其中每个函数最终都在 ELF 中。未链接 22 源中的 21 项位于原用户变量范围，另一个 log_c 源原本即在范围外；两种排除原因分开记录。

证据：`output/quality-20261108/continuation/final-projects/f411-real-link-closure.json`，包含原链接参数、实际归档成员表、MAP 选中行、全部 24 输入和 22 排除源的明细及哈希。各工程 `*-input-baseline.json` 保存原输入 SHA/大小/mtime；`pre-run-config-finalization.json` 记录正式扫描前显式绑定包内 libclang 和 F030 位宽的配置修订。

## 准备检查与待执行部分

在旧的只读 `1b85908…` 候选上，先于单独 scratch 完成了三份真实 CDB 的 `compilation.prepare`：F030 4C、F411 24C、CDC 39C 和一份 ASM，所有 C TU 的实际标准头目录非空，闭包无缺失对象。分别耗时 0.250、1.391、0.672 秒。这是输入准备证据，不是全量静态提取、可信风险分类或发布完成；当时正式扫描数据根尚未建立，后续实际全量结果如下。

协调者随后在首次构建别名稳定性上发现 Q204 的相邻缺陷，旧候选正式扫描暂停；本项等待修复后的新冻结引擎，不用即将失效的版本重复扫描。原准备证据保留在 `*-prepared.json`。

正式扫描使用公开 `run_canonical`、Windows Job 子进程树资源采样及最终 manifest 校验，不修改分析器或注入状态。资源控制器为实际主机 CPython 3.10.11；固件编译器、CMake/Make 等工具 PATH 和 libclang 明确来自原解压候选。因此这一项是新源码候选和现有包内工具的真实 Windows 集成验证，不能称为新便携包已经封包通过。6GiB Job 提交上限属于显式安全限制，不是物理 32GB 主机门禁。

## 当前全量结果

该轮引擎冻结于 `H:/ECRA-quality-20261108/continuation-final-engine-v2`，静态摘要 `8393edcd9ec5d958f97559a49eda73a2a5edd425a15cc18ad8ce7de33a330902`。三项已顺序完成；每项冷提取，不复用前轮缓存。启动参数、配置 SHA、受限工具 PATH 和前后引擎摘要见 `final-v2-launch.json`。后来发现的Q109及最终组合引擎验收另记，不能把839轮当作修复后的新facts通过。

| 工程 | 全量及发布 | C TU / 盘点 | 分类与后续工作 | 资源 |
|---|---|---|---|---|
| F030 | 已发布 STATIC_VALIDATED，分析有效、快照 VERIFIED；退出2，INCOMPLETE | 4TU：2 PARSED、2 PARTIAL、0 FAILED；15盘点 | 7 SAFE_PROVEN、1 SUSPECT、5 NON_STORAGE、2 CONTAINER；当前待人工1。PARTIAL不是安全证明 | 86.500秒；Job峰值提交148,828,160字节；峰值工作集184,754,176字节 |
| F411 | 已发布 STATIC_VALIDATED，分析有效、快照 VERIFIED；退出2，INCOMPLETE；status/report相邻检查通过 | 24 TU全部PARSED；171盘点 | 显式分类123：84 SAFE_PROVEN、1 SHARED_NO_REVIEW、34 SUSPECT、4 UNKNOWN；原Q109误计4容器，原待人工42；候选只读修复后38 | 586.953秒；Job峰值提交190,791,680字节；峰值工作集214,798,336字节 |
| CDC | 已发布 STATIC_VALIDATED，分析有效、快照 VERIFIED；退出2，INCOMPLETE；status/report相邻检查通过 | 39 C TU全部PARSED；1ASM记录边界；244盘点 | 显式分类210：5 SAFE_PROVEN、135 SUSPECT、70 UNKNOWN；原Q109误计20容器，原待人工225；候选只读修复后205 | 1440.344秒；Job峰值提交574,320,640字节；峰值工作集581,148,672字节 |

F030 的 PARTIAL 来自原固件中 Clang 对 naked 函数内 C 语句的限制，以及原指针/整数转换诊断，错误均保存；没有修改固件、压制诊断或把部分解析当作完整覆盖。实际 ELF 使五个 linker 外部符号归入 NON_STORAGE，不再把它们计作需要复核的存储对象；两个数组容器单独记录，当前风险分类总数8与盘点总数15不同且可解释。

F030 已实际执行 `status --json → report → status --json`，返回0/2/0；两次状态均为 INCOMPLETE 且可继续，report 的2按已有命令契约表示结果仍不完整。静态库前后 SHA 不变，SQLite完整性与外键检查通过，源码逐文件SHA/大小/mtime、CDB、ELF、MAP全部未变。

另保存了真实对象 `c:@systicks` 从定义、三个访问、上下文和调用链到候选及待人工状态的完整轨迹 `f030-systicks-trace.json`。独立阅读原源码可见 `main.c:25` 的 64 位计数器、`peripheral.c:58` 的 SysTick 递增及73–74行轮询读取；在 Cortex-M0/32位上，未证明64位访问或整个递增操作原子，volatile也不能替代保护，因此不能得出安全结论。实际 SUSPECT 与这一独立推理一致，同时原 PARTIAL 仍保留；本次没有调用AI或注入人工签署。

初版验收控制器曾误要求 report 也必须退出0，因此其 `final-v2-f030-audit.json` 保留 `checks_passed:false` 原收据；随后按照 README/CLI 已有的0/1/2结果契约另写 `final-v2-f030-audit-contract-correction.json`，解释原始返回0/2/0及其他全部独立检查通过。没有改结果、放宽分析完整要求或重写原失败文件。后续控制器显式分别核对 status 与 report 的返回契约。

F411、CDC 的实际 `status → report → status` 均为0/2/0，审计通过，源码副本、CDB/ELF/MAP、静态库和引擎字节不变；SQLite完整性和外键检查通过。报告刷新按原契约更新运行时归档审计/manifest，静态 scan.db 的SHA不变。未请求AI、未添加人工签署。原839误计状态仍保留为Q109证据，不把225或42当作修复后的待办数。

F411 的统计口径单独核对：报告的123个显式分类对象之外，还有37个已标容器、7个非存储对象和4个未填显式分类的嵌套容器，总数171。后四项为 `g_cli.command_list`、`command_list[*]`、`history`、`history_stash`，原查询投影按UNKNOWN展示；加上原静态4UNKNOWN，原界面当前UNKNOWN为8、待人工为34疑似+8未知=42。该原始状态完整保留，不通过删数据对齐数字。原静态未知分别保留地址逃逸和汇编函数引用执行上下文缺口，见 `f411-preserved-unknown.json`。

进一步只读追踪确认：这四项全部为 `STRUCT_MEMBER_CONTAINER`，不是补充声明或遗漏的可分类叶子。`analysis.py:1150` 按既有契约将它们从独立风险分母排除；1312行的容器汇总只处理根结构体/数组，因而嵌套行没有显式CONTAINER标签。具体成员仍分析：command_list三个叶子两项SAFE、一项SUSPECT；history[*]与history_stash[*]/[0]均SUSPECT，对应finding保存。两条整成员访问也分别向三个、两个叶子继承，访问与上下文证据没有丢失。

父容器不重复计分类分母已有依据：产品方案8.3与历史e69验收fixture均明确该约定。现有UI说“容器单列”，却把这四项按UNKNOWN加入人工待办，故这是查询/展示层的容器身份与待办统计缺陷，不能只用“保守”解释为通过；不是本轮扩展DMA支持或扩大分析分母的需求。已将原始对象/叶子/访问/上下文/候选ID及代码位置交协调者修复，冻结引擎与原归档不动。证据 `f411-nested-container-diagnosis.json`；修复后读模型结果另记，原42待办收据保留。

相同根因在完成的CDC上也得到验证：原90未知包含20个缺标签嵌套容器，显式静态未知为70。冻结Q109候选只读查询原CDC得到34容器、70未知、205待人工，5安全/135疑似和原scan.db SHA完全不变，证据 `output/quality-20261108/continuation/q109/real-cdc-read-only-projection.json`。该候选还实际完成旧F411完整包导出、导入、deep校验，原文件不改；修复细节、字段来源、102项相关回归及兼容证据见[Q109记录](continuation-q109.md)。最终新facts全量仍由最终组合引擎验收，不以只读派生替代。

三工程都保存完整的运行、退出、覆盖、分类、资源、原件不变性及实际恢复命令收据。此轮通过的是新真实构建输入上的完整扫描、有效归档和现有命令契约；保留F030 PARTIAL、所有未知/疑似及Q109原始缺陷。没有HIL、板级运行、真实联网AI或干净离线物理机结论，耗时也不能当作经过前后对照的性能优化结果。

## Q108 的独立代码检查

独立只读检查 `continuation-ui-candidate/studio/src/App.vue` 与 `ScanIdentity.vue` 的最小就绪门禁：变量列表、详情、保存和继续均要求当前扫描绑定的 summary；失败及切换扫描清除旧编辑依据，并使未完成请求失效；SymbolAI、覆盖和复核工作区也受相同就绪门禁保护。历史降级只读分支与显式错误重试入口仍保留，未见本批门禁新增阻断。

该项是代码复核，没有追加浏览器通过结论。实际坏归档空白复现、修复后签署、关浏览器和重开继续仍以[Q108 真实操作](continuation-q108-ui.md)为依据。精确源码 SHA 与检查项见 `q108-independent-source-review.json`。
