# R2a：冻结编译文件视图的实现合同

2026-11-04，接续[68号方案](68-remaining-refactor-execution-plan.md)的R2。此子阶段处理真实提取Worker对冻结文件的访问；不移除`formal_workspace`或版本预览的dirty阻断，不声称完整Diff/CMake验收完成。

当前原型通过测试内替换`Index.parse`注入VFS，不能代表正式Worker已支持。新的内部请求合同必须让真正`ecra.extract`子进程消费由既有`working_snapshot.capture/validate`创建的、带完整SHA固定的文件视图，不能用测试mock替代。

1. 只在既有Resolver的独立工作树归属范围创建新的私有视图；原捕获、原固件、原索引和原build不修改。项目内全部捕获文件以原逻辑路径映射到复制字节，mtime保持；使用`redirect-only`及`use-external-names=false`，保留`__FILE__`、`__BASE_FILE__`、`__TIMESTAMP__`、USR、位置和诊断。
2. 外部搜索目录必须显式列出并独立完整复制，包括原本存在但未被include的文件及空目录，从而保持正/负`__has_include`。不得把SDK目录直接remap回实时原目录，不允许未声明路径fallthrough。外部复制前后、发布前检查内容/mtime/文件集合，失败只保留私有现场。
3. JSON视图用流式写入；完整文件清单保存在SQLite，不能把所有原文/所有记录额外常驻内存。文件副本逐块复制、核对SHA、保留mtime及必要空闲空间，禁止硬链接和重解析点。
4. Worker在解析前核对描述文件和overlay清单的SHA、Resolver归属、逻辑root/source/工作目录；工作目录须在工程内或明确完整捕获的外部build边界内。不得与unsaved源码覆盖混合，必须核对实际Clang输入。PENDING阶段的视图不能被消费，完整校验后才原子发布COMPLETE。未提供内部视图的既有请求完全保持原有路径。
5. 真正子进程验证完整TU输出、有类型/顺序事实和预处理签名不变；覆盖暂存/工作区不同、删除/重命名/未跟踪/忽略生成头、原/SDK后来变化、正负探针、宏和损坏视图。仅Clang成功、符号数量相等或摘要一致不能替代全字段对照。

此接口仍只证明固定Clang输入的能力。正式集成还须把父进程源码/配置/响应文件读取、编译器探针、CMake构建生成、Git选择与扩大闭包/缓存/`verify_against_full`接到同一捕获身份；对已支持构建模式分别提供完整原生/Diff旧新对照和无写入证据后，才可解除对应门禁。缺外部搜索目录时拒绝/保留原生诊断，不猜测一个能编译的不同输入。
