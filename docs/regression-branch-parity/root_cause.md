# 根因、复现和修复

## CMake 实际编译的 C++ 翻译单元被跳过

A/B 都在 [`ecra/compilation.py`](../../ecra/compilation.py#L655) 按少数源文件后缀接纳 TU。B 的 Ninja 目标数据库也在同一阶段按后缀筛选。用 ARM GCC、Ninja 和实际链接的四 TU 夹具复现，`state.c++` 和 CMake 显式指定 `-x c++` 的 `extra.unit` 都有编译与对象输入，A/B 只分析另两个 C 单元。缺失首次出现在 L1。随后 `state.c++` 的匿名命名空间对象与 `Outer::Object::member`，以及 `extra.unit` 的 `explicit_language` 均不进入 AST、求解或 Studio。

C 在 Ninja 已展开的命令中识别真实编译步骤，用显式语言优先、已知 C/C++/ASM 后缀兜底。编译数据库入口、ARM 标准头搜索和 C 暂定定义识别使用同一判定。无法识别的目标编译命令会报告文件。回归 `test_real_target_keeps_cxx_suffix_and_explicit_language` 对实际归档对象和 Clang 定义作断言。C 夹具实扫 4/4 PARSED，原缺失的 3 个根对象均恢复。独立 AST 与 C 的 26 个已定义源根逐一对应。夹具与简单 C++ 符号身份的测试覆盖不等于所有模板、TLS、模块或运行时语义均受支持。

```cmake
set_source_files_properties(extra.unit PROPERTIES LANGUAGE CXX COMPILE_OPTIONS "-x;c++")
target_sources(firmware PRIVATE state.c++ extra.unit)
```

```cpp
// state.c++
namespace { int same; }
namespace Outer { struct Object { static int member; }; int Object::member; }
// extra.unit
namespace { int explicit_language; }
```

## 手工任务入口会盖过真实的多个任务实例

A/B 的 [`context_graph`](../../ecra/analysis.py#L170) 对已匹配的 C 入口跳过自动登记。同一个 `worker` 在 `main` 中分别传给两次 `xTaskCreate` 或 `osThreadNew`，配置 `kind: TASK, functions: [worker]` 后，两个真实注册点消失于上下文传播，只剩一个非重入逻辑任务。`worker` 内的 `target_state++` 被判为 `SAFE_NON_INTERLEAVING`。移除手工标签后的 A/B 反例均恢复两个参与者并报 `SUSPECT`。任务创建语义允许两个任务使用同一函数，而函数内的静态存储仍由两个实例共享。

C 保留每个已恢复的任务创建点和各自物理执行身份。一个配置任务只有一个入口且可关联到实际创建时，沿用配置标识，保留变量归属、并发和抢占声明。同一入口的额外创建点仍是独立任务。有多个可匹配的手工任务且无法确定对应关系时，保留手工任务和已恢复证据。Clang 和已配置的指针分析在同一调用点找到同一入口时，合计一个实例，保留任一来源报告的可能重复创建。FreeRTOS 定时器回调仍使用守护任务的串行模型。

首轮修复把已经匹配的手工任务改成自动编号，导致实际唯一合法写入者触发归属违规，风险从 `MEDIUM` 变为 `HIGH`，并丢失两条配置关系。它也会删除尚未由编译单元恢复的第二个配置任务，使共享计数器被错判安全。带 `entry_registrations` 规则的同一次创建还会因两份证据产生虚假的第二个任务。三个真实 Clang 用例先复现失败，补修后通过。`test_manually_named_rtos_entry_retains_each_created_task` 仍覆盖 FreeRTOS 和 CMSIS-RTOS。独立 ARM 夹具的 `parallel_task_state` 从 A/B 的 `SAFE_PROVEN` 改为 C 的 `SUSPECT`。

最小反例如下。任一任务在另一个任务的读取和写回之间完成更新，都可使结果丢失。`volatile` 对这一交错不提供互斥证明。

```c
extern void *osThreadNew(void (*entry)(void *), void *argument, const void *attributes);
static unsigned value;
static void worker(void *argument) {
    (void)argument;
    value++;
}
int main(void) {
    osThreadNew(worker, 0, 0);
    osThreadNew(worker, 0, 0);
    return 0;
}
```

## CMake 用例影响后续 MinGW 测试

新增 C++ 闭包测试直接调用 Clang 提取器，提取器将当前测试进程切换到固件构建目录。随后 MinGW 用例使用相对路径运行 `run_ecra.py`，Python 在构建目录找不到脚本，退出码 2 与一个合法扫描状态相同，测试直到检查结果库时才发现报错。A/B 的工作树保持不变，使用真实子进程的 B/C 对照确认，同时保留原始标准错误。C++ 用例现已登记工作目录清理，原断言均保留。按原顺序运行真实 CMake、Ninja 及 MinGW 测试，MinGW CLI 返回实际证据库，16 项通过。

## SQLite 发布失败后的收据状态

B 已经生成内部静态结果后，[`_run_canonical`](../../ecra/scan_persistence.py#L417) 还要进行深校验、人工历史对接、审计归档和发布清单写入。注入 `archive_audit()` 的 `OSError`，B 没有发布新清单，但异常逃逸时 `run.json` 和 `result_validity.json` 仍来自内部扫描的成功阶段。此问题影响自动读取收据的使用者。目录中存在 `scan.db` 也不足以证明已发布。

C 对发布清单前的失败记录 `FAILED` 或 `INTERRUPTED`、失败收据退出码及异常栈，再继续抛出原异常。新增回归检查前次权威库 SHA、最新扫描指针和失败收据，并确认失败目录没有发布清单。既有冻结源文件在归档期间变动的回归确认原异常行为兼容。

## Studio 旧归档的拒绝原因

完整回归另发现 B 读取仅保留原件的旧归档时，会在识别归档缺少可验证证据之前尝试查找变量指纹。提交一个任意 symbol ID 会得到对象查找错误，掩盖已经触发的旧归档只读限制。B 上的原测试独立复现。C 先验证归档能否保存人工结论，再读取变量指纹。静态扫描引擎摘要与此修正前一致。

## 已解释的非缺陷差异

- A 的真实 INAV argv 含 ARM GCC 的 `-flto=1`，libclang 报 `unsupported argument '1' to option '-flto='`。B 已有 Clang 兼容映射。保留原始失败诊断，三版统一通过配置将 Clang 参数改为 `-flto`，真实 GCC 构建命令和产物仍按原始值生成。等价性核验包括宏、ABI、目标、目录和参数顺序。
- `serial - opencode` 的旧 `.ecra` 为固件 `00b16f75…` 的 20 TU 全量，旧 `.ecra1` 为 `c7faf3b9…` 的 23 TU 差异扫描。后者独有的 38 行来自额外的 3 个 `ecra_diff_*.c` 和它们包含的 `ecra_diff_probe.h`，逐行保存于隔离目录 `serial-history-comparison.json`。固定 20 TU 全量时，58 个对象均保留。历史报告还各自使用完整和差异的展示分母。
- `H:/ecra_output` 中的三个串口历史归档也已保留原件副本。直接读取归档 SQLite，三份当前侧库存均为 58、基准侧均有 38 条删除记录，直接影响和保守影响的数量分布不同。见隔离目录 `historic-serial-diff-selection.json`。这些记录属于已识别的串口工程。
- 另对 42 份本机历史扫描读取收据和 SQLite，其中 15 份有 2,000 项以上。11 份 16,566 行的历史 INAV 报告绑定另一固件提交 `f25434a9…`，另外 4 份 12,315 行的报告记录了不同分析引擎摘要。该记录没有识别出用户报告的精确 A/B 归档组合。核对清单 `historic-large-report-inventory.json`。
- 该串口工程 A 有 4 条没有显式分类键的 `STRUCT_MEMBER_CONTAINER`。B/C 显式存储 `CONTAINER`，子成员继续各自分类。四行定义、身份和归类见 [classification_changes.csv](classification_changes.csv)。该变化没有将风险降级，也不改变 49 个独立对象的分母。
