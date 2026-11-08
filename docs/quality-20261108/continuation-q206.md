# Q206：GNU函数别名丢失中断执行身份

已在独立候选修复已确认的错误SAFE，并与Q205组合进入最终v4，完成[三工程实际全量复验](continuation-final-projects-v4.md)。旧ZIP、旧冻结引擎和真实工程未改；大型INAV、离线重建交付包等最终验收独立推进，不以本小样例或三工程收据替代。

## 根因与独立依据

原v3只把 `is_definition()` 的函数加入facts。GNU `void ExceptionRoute(void) __attribute__((alias("Impl")));` 在Clang AST中是声明而非函数体；真实向量slot2/3虽然指向ExceptionRoute，但该function_id不在函数表，context_graph跳过了入口，Impl的共享访问被误当作不可达，最后给出SAFE。原始独立证据在 `output/quality-20261108/continuation/diff/q205-c-function-alias-boundary.json`。

GNU alias的目标必须与声明满足类型和同一TU约束，不能用跨文件同名推断。[GCC函数属性说明](https://gcc.gnu.org/onlinedocs/gcc/Common-Function-Attributes.html) 本轮额外以实际ARM GCC、nm同址和vector relocation证明这不是普通C源码调用。Clang属性宏的token extent可能横跨后续宏和其他声明，直接搜索首个字符串会取错；实证脚本与日志在 `q205-independent-review/q206-ast-probe.*`，不据此猜目标。

## 修复范围

只改候选 `H:/ECRA-quality-20261108/continuation-q206-candidate/ecra/{extract.py,vectors.py}`：先识别真实Clang alias属性，再读取Clang展开声明中的精确链接符号；完整TU提取后绑定唯一真实函数体，因此支持目标后定义和header原型。facts保留原声明位置、属性类型/短拼写、展开声明、目标符号/定义位置及恢复依据。控制流使用 `GNU_FUNCTION_ALIAS` 边，保留alias函数身份和源向量槽，沿边传播实际中断上下文，未伪造普通源callsite。

当前只恢复相同无参数void ABI、非weak/非inline真实目标。C强定义覆盖weak alias继续使用既有同USR强弱合并，并过滤被覆盖alias所属的边；正反输入顺序均验证。参数/返回转发、不能证明的目标、weak目标interposition、同名汇编实现，以及未展开汇编可能覆盖weak alias时明确拒绝分析。错误保留已完成TU提取材料，不发布遗漏函数体产生的SAFE；这不是通用指针/汇编/链接器符号重写支持。

## 冻结身份与复验

静态指纹 `83fa8deb65560586807773aedc06d4da558eefd85a19824c7f6e7d84e27c1c8d`，extract SHA `3a4cd1f0…`、vectors SHA `56330ba6…`。完整SHA和差分在 `output/quality-20261108/continuation/q206/candidate-frozen.json`、`candidate.patch`。README同步能力边界；未改分析/物理身份/屏蔽判据模块。

同一个已知答案oracle在原v3真实编译后运行：2个方法的3个子场景失败，均为错误SAFE，保留 `actual-before-v3/` 和对应日志。冻结候选13个方法9.585秒通过，包含NMI/HardFault、普通可屏蔽IRQ有效保护、目标后定义/header声明、直接/参数宏/字符串化宏/固定宏、非别名字符串/注释、同名TU静态隔离、C strong覆盖weak alias、ASM strong/宏ASM覆盖，以及无法展开和参数转发的明确失败。

真实完整ELF/nm对照包含：无覆盖的weak符号W且与Default_Handler同址；另一C文件strong符号T且与默认体异址，两种输入顺序和实际有/无共享访问均按所选体分析；汇编strong替换及weak target被替换后出现异址时明确拒绝。ELF/MAP、对象、C/header/ASM源码、实际CDB、nm/objdump文本、分析前后facts和报告保存在 `actual-frozen/`。这是已知答案的小样例完整链接，未冒充第四个真实工程、硬件实测或最终便携包。

最后生产字节修改后，13个新增方法及相邻vector/solver/NVIC/mask/Q109共80个方法22.222秒通过。两组有重叠，不相加证明覆盖。初期测试脚本误按LF解析nm的CRLF导致9个StopIteration，原 `tests-v1.log` 保留；仅修正测试文本解析，未修改产品判据或放宽答案。初始候选使用绑定不存在的方法名也保留 `first-positive.log`；改为libclang正式C API后复验通过。

## 合并门禁

Q205单独修复不能恢复不存在的alias函数；Q206单独修复也不能解决旧context覆盖。因此原手工同ID/目标体补充反例需要在组合引擎确认SUSPECT或明确拒绝，不能仅凭各自测试通过发布。组合复核收据为 `output/quality-20261108/continuation/q206/joint/receipt.json`，状态以其实际结果和根验收记录为准。

组合只读副本指纹 `63a5cff7e9babcf0a4982726f68ca8390ad5f840b92d31d41e511a859d857710`，10个真实ARM对象反例均通过：slot2/3分别验证无手工、同ID目标体、同IDalias入口、不同ID目标体、错误vector；同ID不同原始入口明确拒绝，其他相容形式保持真实物理身份及SUSPECT/INEFFECTIVE。新增两个模块合计26方法23.179秒通过，记录 `joint-candidate-tests.log`。这些重叠复验不累加为覆盖总数。

另真实执行组合副本的公开 `run_ecra.py run --project … --config …` 两次。已恢复NMI例25.406秒exit2，静态快照VERIFIED，库中shared为SUSPECT/INEFFECTIVE，包含别名边与NMI槽；deep图/投影校验通过，读前后scan.db SHA一致。不可变数据库内scans.state按协议保留UNVERIFIED；其同一发布目录的manifest.json已正式标为STATIC_VALIDATED，并独立记录run_state=INCOMPLETE（AI关闭、1项待复核），不是未发布。参数alias例3.875秒exit3、FAILED/analysis_valid=false，没有发布scan.db或风险JSON；真实 `workers/TU-00000.response.json` 仍为PARSED，保留访问和UNRESOLVED属性证据。两次输入文件均未改变。完整命令、返回值、日志、只读审计及路径见 `formal-cli/{receipt,read-only-audit}.json`；原始工程在 `H:/ECRA-quality-20261108/continuation-q206-formal-cli`。这是host Python3.10.11加原包native工具的源码候选验证，不冒充更新后便携包实测。

进一步使用同一正式Studio ASGI应用的认证GET `/api/scans`、`/api/scans/{id}/summary`、`/api/scans/{id}/symbols?search=shared`，全部HTTP200；列表找到该扫描，列表和详情都按绑定清单展示LOCAL_SNAPSHOT/STATIC_VALIDATED，风险shared仍SUSPECT，可确认、可继续复核。这里验证的是实际路由和数据协议（TestClient），未宣称又完成一次浏览器视觉检查。公开CLI `status --json → report → status --json` 返回0/2/0，均解释为INCOMPLETE且resumable，报告刷新保留全部静态数据库字节。因report按合同会刷新运行态，此三命令在完整数据副本运行，只改变配置中不参与分析摘要的output根，不改源码、事实或身份。原NMI发布目录内全部文件前后SHA完全不变。清单、API响应、实际命令与日志在 `output/quality-20261108/continuation/q206/publication-contract/receipt.json`，因此未发现CLI结果无法从声明入口查看的缺陷。
