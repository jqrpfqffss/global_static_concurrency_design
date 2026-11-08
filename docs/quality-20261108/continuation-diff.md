# 后续真实 CDC 差异、缓存与恢复验证

本记录持续更新；尚未完成的轮次不能视为通过。对应证据目录为 `output/quality-20261108/continuation/diff/`，独立数据根为 `H:/ECRA-quality-20261108/continuation-diff`。本职责未恢复被工具停止的原生窗口操作；缩放限制另见 [continuation-ui.md](continuation-ui.md)。

最终统一v4的真实冷/暖及恢复验收使用全新证据目录，当前状态见 [continuation-diff-v4.md](continuation-diff-v4.md)；本文保留前轮完整经过、失败和修复依据，不替代最终版结论。

## 真实工程与隔离方式

采用 ST STM32F407IG CDC_Standalone 真实工程及既有p00验收扩展，来源为 STM32CubeF4 v1.28.3 / `94cae6e83f00e276a11957e7833c01ac3d0bd7af`，无RTOS、未烧录。完整源码从交付检查者刚完成真实MinGW编译/链接的副本复制；566个原文件逐SHA及mtime核对，保留上游许可证、组件头部声明和固定提交/子模块身份。原工程、原Git及原确认数据库不写入。

新工程在 `source-cdc/` 建立独立本地Git仓库。原CMakeLists、HAL、CMSIS、USB栈、启动汇编和39个C翻译单元全部保留；没有用微型工程替代真实工程，也没有手写或重映射既有compile_commands。新的CMake配置/真实编译和链接生成各版本自己的数据库。

唯一新增验收存储为 `App/lab.c` 的 `ecra_quality_diff_counter`，通过工程原有的 `main → Lab_Poll` 和 `SysTick_Handler → Lab_OnTick` 接入真实调用链。基准的foreground读改写由保存/恢复PRIMASK完整包围；当前提交移除屏蔽并改变实际消费的头文件宏。独立预期来自源码窗口推理：前者在完整证据下应受保护，后者两个执行域均修改同一volatile存储，单次字访问的原子性不能保护整体RMW。

| 版本/实验 | 输入与独立预期 | 状态 |
|---|---|---|
| 基准 `3dd83d1ee84aaa51b0ca6e0e0d555b8ca5a1653f` / `quality-protected-base` | `Lab_Poll` 完整PRIMASK窗口；宏 `ECRA_QUALITY_STEP=1u` | 已实际完成39 C TU全量基准，`analysis_valid=true`；目标SAFE_PROVEN / COMPLETE |
| 当前 `b2da0c5fdfac7349b0569deb4f5765dbaf1e3c34` | 移除完整屏蔽，宏改3u；应保留SUSPECT，并进入差异范围 | 已通过原74c0引擎差异/独立无缓存全量对照；39/39 C TU解析，目标SUSPECT且纳入差异；完整语义/分类均0不一致 |
| 同输入再次执行 | 明确相同配置字节、Python/GCC/CMake/Clang和 `PYTHONHASHSEED=0`，应有效复用缓存且证据相同 | 原74c0真实warm完成：基准/当前各39 TU缓存全命中，独立full核对通过；完整基准summary未命中，已复现Q204 |
| 后续头文件语义变化 | 应拒绝过期恢复或正确失效，再生成与全量一致的有效结果 | 尚未完成 |

来源及逐文件收据：外部数据根的 `source-provenance.json` / `setup.json` / `known-semantic-change.patch`。

## 当前实际发现及修复候选

### Q203：正常C+ASM工程被工作字节CMake准入误拒绝

原包下 `include_uncommitted:true`、正式Windows/Ninja外置构建，实际CMake configure退出0，但`working_cmake.audit_trace`将内置 `CMakeDetermineCompilerId.cmake:1153` 的汇编器 `--version WORKING_DIRECTORY .../CompilerIdASM` 查询误判成项目自定义命令，CLI退出3。原失败在 `diff2.log` / `diff2-execution.json`；精确源、命令和查询保存于 `q203-original-asm-rejected-query.json`。

第一轮曾先触发目录变化保护，原日志 `diff1.log` 保留；该次变化来源尚未稳定确认，不被直接当成已修缺陷。第二轮增加纯文件系统内核事件观察，未修改或抑制产品保护；观察到的`.git/index.lock`事件处于控制器前后状态读取边界，正式阻断已明确进入上述内置ASM查询准入，不通过忽略保护取得通过。

按主检查者要求，修复只在独立候选 `H:/ECRA-quality-20261108/continuation-diff/candidate-source` 实现。完整ecra/config/scripts、无.git；唯一生产差异为 `ecra/working_cmake.py`，静态摘要 `29c73f8560386832c3a3202a9e1cbf0323824f3ca10ba0722bf2a7f23262482b`。主工作区基线套件和原封存ZIP/解压包均不回写。

新增准入同时绑定：真实内置模块路径、配置的ASM编译器、完整固定`--version`参数及输出变量/10秒限制、该执行器拥有的私有构建根、CMakeCache版本对应的CompilerIdASM目录。项目命令仅包含相同token不会获准；额外命令、额外参数、外部/源码工作目录、其他编译器、伪来源和输出重定向仍拒绝。

针对性回归3项全部通过，298.050秒：真实C+ASM双次只读构建及完整capture_inputs成功、真实项目借用同形查询仍被拒绝、11种解析边界反例。原源码/Git字节mtime均保留，没有源内build目录。见 `q203-candidate-tests-v2.log`、`q203-candidate-source.json` 和 `q203-working-cmake.patch`。新测试仅存在候选的 `tests/test_working_cmake_asm.py`，待主检查者统一集成。

小型准入fixture仅使用int和生成宏，不依赖标准头，显式关闭该fixture的额外标准头探测以隔离本准入契约；真实CDC始终保留 `auto_system_includes:true`。原先开启探测时，在中文包路径出现ACP输出被UTF8替换的独立真实失败，连未改的C-only旧测试也失败，日志 `q203-positive-diagnostic.log` 保留；该问题已作为Q306交由交付检查者独立修复，不能将29c候选描述为标准头路径问题也通过。

### Q204：compact目录别名随祖先注册顺序变化，阻断完整基准复用

同配置、同源码、同工具路径和 `PYTHONHASHSEED=0` 的真实warm轮次中，基准实际构建目录未变，但第一次被传给CMake的路径是祖先别名下的`builds/<id>`，第二次变为该精确目录自己的hash别名。物理路径等价、文本不同，导致CMake重写Cache/compile_commands，严格输入校验正确拒绝复用旧基准权威文件。基准TU缓存仍为39/39命中；本缺陷不描述成全部AST重提取或错误复用。

另一候选 `H:/ECRA-quality-20261108/continuation-diff/q204-candidate-source` 已冻结，唯一生产差异 `ecra/portable.py`：compact构建目录只复用同一精确物理目录的别名，保留非compact工具整包祖先别名合同。整包静态摘要 `1aa36301e3094f5eef1cf4a6d944869addc74499d00d20a9dd9e82151b610fb9`；portable.py文件SHA为 `fda84c640e1b60bdda95449eba81be6fa80061efa430a3e63a51b618a529b4f5`。未改Q203候选、主区或原包。

30项针对性及相邻检查通过，6.402秒，含真实Windows junction注册顺序、非compact工具sibling布局、真实CMake/ARM GCC生成的Cache和编译数据库字节一致，以及原便携/Studio检查。原顺序缺陷复现为 `q204-before.log`；新测试 `tests/test_compact_alias_order.py`；修复补丁及逐文件收据为 `q204-portable.patch` / `q204-candidate-source.json`。

真实CMake首轮到首次重新配置会自然改变编译器缓存帮助文案；初版测试将其混入对照而失败，原记录 `q204-candidate-tests.log` 保留。修正版显式建立同顺序重新配置字节稳定基线，再只改变别名注册顺序，不修改产品完整性判据；完整结果 `q204-candidate-tests-v2.log`。最终组合引擎的真实全流程重复尚未由本候选单独完成，不能用旧74c0扫描冒充最终引擎验收。

**首版范围不足及v2更正**：最终1b85908真实fixed cold的日志证明，首次构建目录尚不存在时仍使用祖先别名，而再次运行目录存在才使用精确别名。首版只解决已存在目录的注册顺序，不能标成完整Q204修复。该原始场景保留于 `final-fixed-cold.log`，追加稳定回归修前失败 `q204-v2-before.log`。

v2另冻结于 `H:/ECRA-quality-20261108/continuation-diff/q204-v2-candidate-source`，唯一生产差异portable.py SHA `eb4b94a1555a3dbd93e7c972dd17ba9f429a94b70a36476def4d1332b312e257`，单独候选static摘要 `1ee2bd96310be38aa3be4f8b6f69678ecede36d691b7d12cd4f9df060406b1c6`。生产中唯一prefer_junction调用在configure_cmake，明确是build目录：取别名时可能不存在，随后正常mkdir和owner标记，再执行CMake。因此v2让compact目录的junction绑定精确的尚未创建目标，而不在别名函数创建/写目标；真实caller创建后解析到同一目录，再次运行保持同一拼写。非compact文件/工具仍保持原合同，已有文件不能冒充目录。未修改旧候选、1b冻结引擎或主区。

33项通过14.105秒：包括首次不存在→实际创建→清注册后重开、已有目录顺序、真实CMake/ARM Cache和编译数据库稳定、非compact工具siblings、原27项便携/Studio及2项已注册/失效别名guard。补丁 `q204-v2-portable.patch`，逐文件收据 `q204-v2-candidate-source.json`，最终日志 `q204-v2-candidate-tests-v3.log`。v2初版测试漏掉已存在caller的mkdir步骤，直接要求CMake穿越尚未创建目标而失败；保留原日志，修正fixture明确断言别名请求时目标不存在，再像实际caller一样创建，未变生产判据。两轮选错测试类的loader错误亦原样保留，不计通过。

**工具链缓存相邻原因及独立候选**：按configure_cmake同形真实C+ASM/ARM参数复测，重复传入相同`-DCMAKE_TOOLCHAIN_FILE=`会让首次重新配置将Cache中的FILEPATH/标准说明/正斜线拼写改为UNINITIALIZED/命令行说明/反斜线，第三次才稳定。即使仅声明`:FILEPATH`仍改变说明文案。原3轮对照 `q204-v2-managed-first-reconfigure.json`、类型声明反例 `q204-typed-toolchain-reconfigure.json`；不能把第一轮自然改写算成缓存损坏或忽略严格字节检查。

先只读证明同一已缓存工具链不重复覆写-D时，真实Cache和编译数据库从首次到两次重配均逐字节相同，见 `q204-same-cached-toolchain-reconfigure.json`。再在完整组合v2的另一副本 `H:/ECRA-quality-20261108/continuation-diff/q204-v3-candidate-source` 仅修改compilation.py：使用已有Q301 build-first/source-fallback解析，只有同一实际存在的请求文件才保留已初始化缓存项；新/缺失/不同文件和实际clean始终保留原显式参数。快照、输入字节校验及风险规则未改。

候选摘要 `7924baf999eb209f00be63168122af70afcaf648b959639d4b6b5ffa1bbcf526`、compilation.py SHA `ef85f59908d830ba1efd0aea9701891de547f749b8eebc968b1e031b4573d26f`。35项通过53.542秒，包含7类边界、Q301相对路径、真实正式外置C+ASM/ARM首次重配稳定、同文件内容变化仍进入编译宏、新工具链对应不同真实构建与宏9、已缓存clean后仍显式工具链和实际编译。补丁 `q204-v3-compilation.patch`、逐文件收据 `q204-v3-candidate-source.json`、测试 `tests/test_cmake_cache_toolchain_reuse.py`、最终日志 `q204-v3-candidate-tests-v2.log`。候选尚待协调者决定是否组合；不得据此宣称仍在运行的v2已包含该更改。

首版真实测试后段使用旧式工程内build，CMake在该入口更换工具链会沿用旧CMakeSystem.cmake，宏9断言失败；原日志 `q204-v3-candidate-tests.log` 保留。当前正式合同禁止工程内build，WorkspaceResolver按cmake设置隔离构建，因此改用该正式入口并明确断言新构建目录和真实宏9；没有降低编译证据预期。纯命令边界测试仍检查旧目录中新/改工具链必须传显式参数。

## 原74c0固定提交首轮结果

`fixed-diff1-audit.json` 记录1275.125秒、退出2（保留真实INCOMPLETE，未伪装零退出）。39/39 C TU均解析，盘点245对象、206个候选/盲区复核项；`analysis_valid=true`、SQLite完整性ok。目标变量从基准SAFE_PROVEN/完整保护变为当前SUSPECT/保护未解决，差异理由包含访问、编译语义、冲突、覆盖、保护及静态结论变化。

产品另一次独立无缓存完整提取39 C TU，对245对象核对，`full_verification.state=PASSED`，分类和完整语义不一致均为0。数据库SHA `0e8da2a691330256a75998045dff26eb495976a9176b8ad6f69597d8bf385b54`，扫描ID `de36a09a294e4aff8e44164b012e8526`。这证明本真实工程已提交源码差异范围和风险证据的局部验收，不证明所有未支持机制已覆盖。

原74c0同输入warm完成977.109秒，退出2、有效性true、SQLiteok；基准和当前TU缓存均39命中/0重提取，独立无缓存full仍实际提取39TU且分类/语义0不一致。目标证据（除impact）完全相同、差异选中列表完全相同；impact仅4个归档溯源字段变化（新scanID路径、重建基准数据库SHA/summary路径/patch路径），其余完整相同。没有将不同数据库的二进制SHA表述成相同。对照 `fixed-warm-comparison.json`，主收据 `fixed-warm-audit.json`；新DB SHA `af8a7e72e797b07bd59fb065e57a4a93d48da03dd2a2fff192bbb9e078a4ae5d`。完整基准summary仍hit=false，故Q204原场景未宣称通过。

## 最终组合引擎的独立复验（进行中）

最终候选由主检查者冻结于 `H:/ECRA-quality-20261108/continuation-final-engine`，静态摘要 `1b85908f5313ce13466cd0ddf39abff2299bffb46e2fc414f7a47428099f11ed`。本职责只读该候选。旧74c0检查点均不参与新引擎验收。

新根 `H:/ECRA-quality-20261108/continuation-diff-final` 建立两份无hardlink、无remote的验收源码Git本地clone，均来自本轮自己建立的真实CDC仓库，保留同一基准/当前提交、许可证和全部真实翻译单元。`source-cdc` 专用于工作字节合同，实际未提交头宏3u→7u；`source-fixed-cdc` 专用于固定提交cold/warm，保持clean B，两者输出独立，避免在guard运行时改变其源码。

配置分别固定 `include_uncommitted:true`（SHA `e5397fbc1a362dd15e8853412e90f446a096071434466ae7f516be37540bfe62`）及false（SHA `0a7006cbde0106c8d5f12fbfd68d8cb7c38e7979eaed7b25b5118989ccb9b2c1`）；均保留真实Ninja构建、自动系统包含、full verification及seed0。工具根仍为原封存包，代码执行来自新候选，均显式`-B`避免写入包内pyc。完整参数 `final-setup.json` / `run_cdc_final_phase.py`。

新引擎dirty首次28.765秒触发原source目录变动保护、退出3，日志 `final-dirty.log` 保留。旧/新各首次有同形信号、重试继续，但尚无触发者确证，不能过滤事件或把它判成Q203未修。第二次增加相同通知过滤器的只读ReadDirectoryChangesW观察；已进入实际C+ASM构建，后续结果待完成。固定提交cold和独立full对照另在clean源并行进行，不能用尚在运行阶段代替通过。

1b dirty第二次现已完成3196.703秒、code2/INCOMPLETE，`final-dirty2-audit.json`记录有效性true、SQLiteok；基准39+当前39+独立full39、245对象语义/分类不一致0，目标仍SAFE→SUSPECT且差异选中。扫描 `fb6cd91792c74927b6395b809e409190`，DB SHA `b9563a6604e3dda5b46dbbb1122cc2df6a5c5d6aea5ef2c17d6a792abb3e079b`。成功重试不消除首次变动信号这个未定位限制。

额外的 `final-dirty2-guarded-proof.json` 从实际封存视图只读提取：proof_scope为COMPLETE_GUARDED_CMAKE_INPUTS_V1，最终必须复核原输入；两个不同的受监督实际build均包含40条真实编译命令（39 C+1 ASM），均生成有效ELF（1,764,704字节）和包含目标计数器的MAP，配置/编译退出0。闭合Clang输入中的lab.h确为宏7u、SHA `8da9af3895fbc525ac9a4567f89416d03ffeb93f03ffa21710cdcec5c4838cef`；源前后均只有同一未提交头宏变更，没有注入或恢复内部状态。内核事件8条均为控制器前后.git/index.lock与.git边界元数据，无本成功轮产品过程中的源码事件；仍不能说明未观察的首次信号原因。观察句柄/产品进程已正常结束。

1b固定提交冷轮现已完成，`final-fixed-cold-audit.json`：2125.641秒、退出2，`analysis_valid=true`、SQLiteok；基准39+当前39+独立无缓存full39实际执行完成，245对象分类及完整语义不一致均0。扫描 `77765620e6cb44b4a73a66f180789e65`；源码前后clean、同B、同配置0a7006。该轮是1b版本的真实集成证据，不补warm，也不替代最终组合引擎。

代表变量完整溯源见该轮 `target-current.json` / `target-baseline.json`：身份 `c:@ecra_quality_diff_counter`；实际两个RMW访问位于`App/lab.c:12`与`:18`，前者通过启动汇编Reset_Handler→main→Lab_Poll（物理slot1），后者SysTick_Handler→Lab_OnTick（slot15）。调用路径清单完整、未解决边0；基准完整PRIMASK保护为SAFE_PROVEN/EFFECTIVE，当前保留冲突并为SUSPECT/UNRESOLVED。模型禁用、未伪造AI或人工结论，目标与差异理由按实际存储归档。

由于上述Q204首次不存在遗漏，主检查者另冻结组合v2于 `H:/ECRA-quality-20261108/continuation-final-engine-v2`，静态摘要 `8393edcd9ec5d958f97559a49eda73a2a5edd425a15cc18ad8ce7de33a330902`。全新 `H:/ECRA-quality-20261108/continuation-diff-v2/source-cdc` 是本轮验收仓库的另一无hardlink/无remote本地clone，初始clean B，不复用74/1b检查点。固定配置SHA `611f28c3c29b3c3e7f3223c300b79a4dfd896c1d156fe8620a679e6aad8d67e6`，dirty配置SHA `a4e3d2d6bbb74f876d2b045ac82010f399752fab5caac0a38e158f3d8f0b2d28`；根、配置和工具来源 `final-v2-setup.json`。

v2真实fixed cold日志 `v2-fixed-cold.log` 确认首次build目录得到自己的精确hash别名，完整基准权威及summary复用仍需同根同配置warm实证。1b fixed不追加warm；1b dirty现场继续到结束单独记范围，最终相关路径待协调者统一冻结候选后复验。本职责不修改任一冻结引擎。后续控制器的只读git状态查询显式`GIT_OPTIONAL_LOCKS=0`，避免测试观察者自身写index锁；扫描器环境/配置/输入策略和所有guard均保持产品合同，未将边界观察事件当成产品原因已证实。

v2固定提交cold现已完成2038.000秒，`v2-fixed-cold-audit.json`记录code2/INCOMPLETE、有效性true/SQLiteok、基准39+当前39+独立无缓存full39、245对象分类与完整语义不一致均0。目标保护/风险变更及差异范围与独立源码推理相符，源前后clean B，扫描 `f851f45c861c4e599f5628b02539c82e`。协调者随后发现需组合的Q109容器标签修复，要求不再追加旧v2 warm；将等新组合统一冻结后验证最终cold/warm及dirty。因此v2完整基准缓存命中尚未实际验证，不把上述小型元数据实证替代这项真实验收。

本职责这些CLI扫描明确使用常规Windows Python 3.10.11（命令逐轮记录绝对可执行文件）、seed0，加载候选源码与封存包的构建工具/libclang；不是从重新打包后的最终ZIP双击启动。原包实际Windows启动/UI入口的验证另见交付与界面记录，最终新包仍由交付检查者独立重建、核对运行。并行负载不同，记录的原始秒数不用于给出前后性能提升比例。

## 统一最终组合v3（正在验收）

协调者已冻结 `H:/ECRA-quality-20261108/continuation-final-engine-v3`，摘要 `6cede8359026fd75dd801f6d45ac34ba422a18eee77888078babb8cd862d54f7`，包含上述工具链缓存候选及Q109容器标签修复等统一更改。本职责只读该引擎，不再扩展性能改动。

新根 `H:/ECRA-quality-20261108/continuation-diff-v3`，source-cdc初始clean B、无hardlink/remote，全新输出和检查点。fixed配置SHA `84427225af25172618fb67013a7a2a678a281b4ad5334aaf6e7f3ec28a12eacc`，dirty配置SHA `4c582379b30bac7f859c7e9fb0ad266b2c183f58fff3a4aead67d9518a87717d`；完整来源 `final-v3-setup.json`。已在1b dirty真正退出及收据结束后启动v3 fixed cold，计划同根同配置warm，再真实工作字节整轮，始终保留独立无缓存全量核对、自动系统包含、真实构建和seed0。最终状态以实际新收据更新，旧74/1b/v2结果不混入。

原始获准CDC源在进入v3前复查566个文件，SHA/字节数/mtime全部与最初记录相同、无新增；见 `original-source-retained-before-v3.json`。

v3 cold已实际结束1511.063秒，`v3-fixed-cold-audit.json`记录退出2/INCOMPLETE、有效性true/SQLiteok、39基准+39当前+39独立full、245对象分类与完整语义不一致0；目标SAFE→SUSPECT且进入影响范围，源前后clean B、同配置844272。扫描 `ac60058cbb4148ad9bd4064a881cf271`。随后确认下述严重Q205/Q206，协调者要求停止追加旧v3 warm，保留本收据后组合修复重新验收；不能称最终缓存复用已经通过。

## Q205：手工上下文或自动ID覆盖真实物理证据

开始于Q201未知向量边界的只读契约核对。无ABI来源的手工ISR用未知/缺失vector仍为SAFE，是当前依赖正确手工声明的前提；config仅检查kind/ID/selector类型，文档未将ISR限定成受信的外部可屏蔽IRQ，且同kind也承载NMI/HardFault。该前提此前未在每条SAFE报告单列，作为剩余限制记录，不反向定义新的默认策略。初步证据 `q201-unknown-vector-contract-check.json` 本身不足以证明真实固件漏判。

进一步用了真实C向量表和实际ARM编译独立对照：slot2/3绑定ExceptionRoute，GCC按CDB原argv成功编译，objdump确认相应偏移8/12重定位。无手工入口或不同ID手工补充时，PRIMASK下为SUSPECT；手工id恰为`vector:slot:2`/`:3`时，未知/缺失/错误普通vector均变SAFE_PROVEN/EFFECTIVE/COMPLETE。`vector_entries`仍保存实际不可屏蔽槽，`context_graph`却用后来的配置字典替换同ID上下文，删掉slot/unmaskable/真实来源。10项原始对照 `q201-real-vector-manual-override.json`；这是真实错误安全结论，非新增产品设想。

同根还覆盖后续自动命名/注册ID及physical pattern split反向覆盖既有配置的入口。Q205候选在 `H:/ECRA-quality-20261108/continuation-diff/q205-candidate-source` 独立基于冻结v3修改，主区和冻结v3不回写：源码物理属性/全部根保留，相容配置另列configuration_evidence；不相容kind/selector/vector/irq/slot/unmaskable明确报错。实际NVIC/BASEPRI仍取正确源slot的优先级/分组，手工数字不混成已恢复物理属性。相容同槽多来源保留source_entries及全部根，矛盾物理/priority/grouping字段拒绝；合法注册共组与timer daemon保留。

邻接独立正例发现真实源HardFault的通用unmaskable标记曾使FAULTMASK仍判SUSPECT。原有效SAFE预期与失败日志保留，按ARM规则仅允许固定槽集合恰为{3}的已知HardFault通过该FAULTMASK条件；NMI、未知或混合/矛盾unmaskable仍拒绝。PRIMASK/BASEPRI未放宽。

最终候选摘要 `f6eae1a34b00edf020355f3c7281da4d8dd9f26cae544fe9d1d3f6c68442df7b`；analysis.py SHA `016b421f72d57fab067435f7e8aa9168e0f5da9eb2db7bed28a1e8c3ff0a1cdb`、physical.py `e945769ebc03a8b450863f725e049f83fe2252f16219fe5d41ca57b2f2f20214`、protection.py `f64477212c65f15232d0d252a03547852976520966ef19f67af9d1e2e6f4cc40`。Q109所在analysis正文从canonical_member_path至EOF与v3逐字相同，收据有尾部摘要断言。

最终13个有实际C编译的针对方法通过15.567秒；88项组合通过31.446秒（早期12方法+76相邻，与最终13重叠，不叠加宣称数量）；新增注册/禁用2项也已纳入最终13重跑。原v3四个独立oracle方法有21子例失败，`q205-v3-before-oracle-tests.log`；最终 `q205-final-scoped-tests.log` / `q205-candidate-and-neighbor-tests.log`。初轮HF正例失败未删改预期；两邻接模块初轮因历史unqualified import未加载的错误亦保留，补正确测试路径重跑通过。新测试 `test_context_evidence_collision.py`、补丁 `q205-context-evidence.patch`、逐文件收据 `q205-candidate-source.json`。README/配置示例注释同步手工前提与同ID规则。当前候选已冻结交独立检查者复核，尚不能替代合并后真实扫描。

## Q206：GNU C函数别名入口遗漏（已交独立修复）

Q205函数别名相邻检查用实际GNU C alias：`ExceptionRoute` alias到写shared的Impl，真实表slot2指向ExceptionRoute。GCC编译成功，nm显示两者同址；冻结v3 source-only及手工补充Impl两例却均SAFE_PROVEN/COMPLETE且无缺口。完整源、配置、实际nm和facts为 `q205-c-function-alias-boundary.json`。这是已知NMI的真实函数体未关联，已编号Q206交交付检查者在另一副本修extract/vector最小范围；本Q205副本未修改别名恢复代码，不将其13方法通过描述成该别名风险也已闭合。

## 范围分开记录

为继续完成独立的已提交源码对照，另建 `semantics-fixed.json` 和 `data-fixed/`，明确 `include_uncommitted:false`，日志逐次显示只分析固定提交。其配置SHA为 `2b443f35db813e4b172d6e066b35fdc1bd36fc412c3b1895895e4645f244c16d`，各轮不改配置字节。

这些固定提交扫描使用原74c0封存引擎，并启用产品的 `verify_against_full:true`；当前侧真实TU事实与另一次独立无缓存提取/完整分析核对。该路径构建自己的两个已提交版本，不是关闭本来需要的工作字节保护；不能将它的成功冒充Q203原路径、未提交修改恢复或新候选最终引擎的验收通过。

本轮没有调用联网OpenCode或人工改写扫描状态。所有候选/未知和技术失败按原合同保留；最终通过范围与剩余项将在各轮实际完成后更新。
