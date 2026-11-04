# 未提交输入完整工作流：接入合同

接续[76号代码审计](76-dirty-production-integration-audit.md)，用户顺序为[87号](87-functional-priority-execution.md)：确认继承、数据搬迁已有实际提交和限定范围验收；本项接下来实施，省内存最后。此文是实施合同，不能据此解除尚未验证的正式门禁。

1. 先接显式编译数据库：在耗时base分析之前固定HEAD/index/工作区完整字节与目录；保留暂存与未暂存之间的区别，但本轮current语义为实际工作区，不能只取暂存区。自动盘点真实参数、响应文件、完整外部include目录、实际Clang缓冲区、工具/配置/数据库单文件；外部边界重叠去重只能减少物理复制，不能删逻辑输入。未知/不能证明的模式明确阻断。
2. 沿用已有不可变capture、compiler view、ParentFiles、实际Worker与完整原始/冻结依赖及预处理对照。已有 `redirecting-with: redirect-only` 是整个VFS的禁止回退策略，不能为了漏捕SDK而改成实时读取。此行为已核对[LLVM18原实现](https://raw.githubusercontent.com/llvm/llvm-project/release/18.x/llvm/lib/Support/VirtualFileSystem.cpp)的映射查找及打开文件分支；此处保持原设置，不改分析器。
3. 向导/版本预览/TaskManager/预检查/扫描共用同一个固定描述，不把捕获UUID或路径塞进有效analysis配置。原始配置/数据库的已消费SHA必须与冻结副本一致；捕获晚于读取时不能忽略前一次的已消费内容。输入变化则失败且保留上一有效结果。
4. 完成冻结输入的status/复核前校验与恢复：重新核对原HEAD/index/源码/目录集合、外部输入、环境/引擎、完整capsule、原始/冻结Clang依赖和预处理状态、父进程选择集合。缺证明或损坏继续拒绝；完整包在无原源码时仅归档查看，不能冒充重新扫描。
5. base始终来自所选固定提交，不能继承current的dirty视图。验证 `base → current`、扩闭包、缓存冷/热/损坏、全量独立对照及 `verify_against_full`，保持原全字段/顺序规范化。源/Git/index/build不改。只在每一支持模式全流程通过后，才解除该模式GUI/CLI门禁。
6. 外置CMake单独验证构建捕获和真实GCC/生成头、宏、编译闭包、Git版本脚本、ELF/map。不能用编译数据库Clang视图的证明冒充构建等价；不能将整个活动数据根当SDK复制，更不能回退到原固件构建。无法证明的构建模式保持明确阻断。

界面沿用现有Git版本控件与四步向导：显示真实HEAD、base/current方向、未提交覆盖和输入固定/预检查状态；不新增导航或模拟页面。实际错误必须指向编译数据库、未知参数、SDK边界、输入变化或构建模式及修复动作。正式入口开放前，先做自动盘点/固定的内部完整真实扫描与反例，再接预检查/恢复/实际Chrome。

G2其他工程按用户要求待验；独立物理32GB/第二PC/干净离线/原生DPI/联网OpenCode/UAT继续NOT_VERIFIED，当前H/G及完整重构不宣称完成。
