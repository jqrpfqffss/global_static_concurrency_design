# R2c：正式dirty链路的具体代码审计与实施次序

本页是在R2a/R2b真实Worker及父读取子阶段之后的实施方案，不是已接入声明。正式`include_uncommitted`入口、`prepare_current(true)`及冻结父读取恢复仍按原门禁处理。仍以原任务H1–H6、U04及G1/G5/G6验收。

## 已核对的真实调用缺口

| 位置 | 当前事实 | 实施边界 |
|---|---|---|
| `cli.dependency_inputs/dependency_results` | 依赖请求未传视图；ThreadPoolExecutor不能假设继承调用线程ContextVar | 用显式不可变描述参数，所有首次/最终/发布前/复核后/发布后依赖发现一致传递；不更改`cfg`有效分析配置 |
| `cli.extraction_responses` | 请求只含root/unit/config；TU缓存可能直接恢复旧响应 | 固定视图传入实际Worker；缓存仍以完整输入、预处理签名、宏/ABI/引擎为依据，逐条验证缓存响应，不能因命中绕过视图/选择证明 |
| `cli.run` | 目前先pin、分析base、`prepare_current`、编译准备，再建InputSnapshot；含未提交时`prepare_current`直接返回原工作区 | 明确定义dirty捕获时点，原HEAD/index/暂存/工作字节及被消费的忽略输入在base耗时前固定；临界变化失败，不能用较晚的一组输入冒充较早pin |
| `compilation.prepare/normalize/system_includes` | DB/响应文件有实际消耗记录；系统头探针会执行真实编译器；unlisted/assembly/target过滤仍访问文件系统 | 只复用其真实字段和原选择语义；配置/DB/响应/工具二进制及已存在/缺失搜索目录在消费阶段绑定。不能删除参数、用猜测宏或通用目标让扫描通过 |
| `workflow.analysis_config` | 仅明确排除`_workspace/output/output_dir`；其他新增analysis键会进入语义摘要 | 不把唯一view UUID、临时路径或私有开关塞进有效cfg；使用显式运行参数或受控运行上下文，保留原配置/报告等价合同 |
| 父读取/归档 | R2b接口已实现，但普通CLI仍构造默认InputSnapshot | 同一生命周期打开ParentFiles、注册原选择集合并固定源回调；最终核对原输入及完整冻结副本后才能发布，所有异常仍保留上次有效扫描 |
| 恢复/原生重核对 | 新冻结父读取闭包现被明确拒绝 | 实现视图身份/归属、全输入/目录/原pin、环境/引擎及负探针重验，重建实际Worker请求后才逐模式允许恢复；不能删除拒绝条件替代恢复实现 |
| 外置CMake | 字节/Clang视图证明尚不能证明GCC、Git生成器和build产物语义 | 先在独立原索引/工作字节副本构建，保持真实Git状态和时间；实际GCC文件宏/布局、生成头、link/map/ELF及全部编译参数逐项验证。受控build子目录只复制已封存边界，不复制整个活跃数据根 |

## 接入次序

1. 先实现显式compile_database模式的内部完整执行，复用已有Resolver、捕获、OwnedProcess/共享预算和实际解析顺序。所有原始依赖签名与冻结依赖签名/字节对照；未固定的include、builtin资源、预编译输入或外部CWD不能fallback到实时工程。异常时任务失败，未知/部分解析不能转成PARSED。
2. 用原实现/冻结实现对同一固定逻辑输入做**完整原生扫描和Diff**：base/current方向、选择/影响原因、扩闭包、缓存冷/热/损坏及`verify_against_full`均全字段比较，不仅比较变量数和findings分类。元数据变化与真实输入变化分开记录，原规范化不放宽。
3. 配置/源码/头/响应/DB/负探针/索引变化、停止、Worker异常、资源不足、损坏视图/检查点均实测，源码/.git/index/config/build前后SHA与适用mtime不变；只读目录真实运行。通过后才对该支持模式开放普通GUI/CLI，其他模式明确保持阻断。
4. 另做外置CMake及GCC宏/生成闭包同输入证明。文件prefix map不能只对照字符串：`sizeof(__FILE__)`、条件编译、USR、静态局部、诊断、mtime宏、忽略生成头、`__has_include`正负及Git版本脚本都须覆盖。构建若试图改源码，实际失败并给出外置生成路径动作，不能改写原工程或掩盖失败。
5. 正式恢复和归档源回调使用同一已验证捕获，再复验任务中心/四步向导、历史/人工/标准包；具备证明后逐模式解除门禁。旧捕获/旧结果仍按原能力读取，缺证明不自动升级为可复核/可恢复。

获准F030独立副本可用于操作/全字段反例；INAV真实输入用于大型验证。两者均不能填补用户已延期的TMFC/H747及独立DMA/回调/RTOS工程。物理32GiB、独立第二PC、干净离线PC、原生DPI、真实联网模型与工程师盲测继续NOT_VERIFIED，不制造替代来源。

R2c后仍须完成方案68的R3全消费者/大型Diff恢复、R4证明不变的确认继承、R5完整数据根迁移、R6完整故障/UAT、R7统一门禁。新包专项和缓存试验不替代这些代码目标。
