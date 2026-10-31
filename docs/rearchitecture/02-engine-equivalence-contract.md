# 完整语义等价合同 v1

冻结基准引擎见 `00-baseline-audit.md`。默认不修改 `analysis/points_to/context_points/solver_reachability/call_graph/protection/nvic/interrupts/physical/decisions` 的判定。

1. 固定 firmware SHA、全部 dirty 字节、编译命令/宏/实际头文件、生成输入、工具链二进制、配置、环境与引擎。旧新使用相同字节和真实构建闭包；目录映射只能由显式清单建立。
2. 存储层往返必须保留每个字段、JSON 标量类型、浮点有符号零、字典字段顺序、全部数组顺序及重复次数。未知未来字段同样保留，禁止只保存已知 schema 子集。
3. 关系索引是可查询投影，绝不替代权威原始值。symbol_id/canonical identity 不重新推断。容器、OUT_OF_BUILD、NON_STORAGE 不计为 SAFE。
4. 全字段比较以严格有序类型敏感树摘要为准，逐根/逐关系保留哈希与数量。路径迁移、时间、引擎身份等运行元数据只能在明确列出的运行信封内区分，不能静默删除字段以求相等。嵌套证据不排序。发现任意不明差异即 FAIL。
5. `git_diff.summarize` 的既有语义摘要用于跨执行输入对照，不能替代存储完整性。旧 `scripts/compare_scan_facts.py` 将外层行排序且排除 findings，不是唯一 G1 门禁；保留其用途但新增严格全字段检查。
6. OpenCode 完整证据、八步 Prompt、SAVED/FORMAT_FIX/SUMMARY_FIX/TECH_FAILED 合同不变。只读模型复核不是编码代理委派；本轮仍不自动调用联网模型。
7. 自动化小型 Clang/ARM 测试只证明该输入。三类真工程、完整 Diff、32GB 资源与离线机未测不得写 G1–G8 全部通过。

比较失败应给出根、字段/数组 ordinal、类型及摘要差异；原黄金库不得由迁移器或清理程序覆盖。基线 archive 和输出单独保留，哈希核对失败必须停止。

本轮原生4TU比较首次严格比较发现 `coverage.consumed_inputs.<file>.read_completed_ns` 不同，原失败收据保存为 `evidence/native-equivalence-before-runtime-envelope.json`。该字段及 `read_started_ns` 是工具实际读取输入缓冲的审计时间，原始值另存 execution_envelope；相同记录的status/sha256/size仍逐字段比较。它们不描述固件执行顺序；访问、初始化、保护事件数组一律不排序、不移除。另行分离的运行字段只有generated_at、fingerprint、workspace.results_root。后续结果只能依据重新执行/检查的实际收据更新。
