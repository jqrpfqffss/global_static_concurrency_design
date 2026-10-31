# H2 未提交输入隔离：实施合同（进行中）

起点为当前候选实现提交7ef7c8a，验收记录提交c378539。该功能尚未接入正式扫描，`include_uncommitted: true`继续拒绝；不能将本设计或独立捕获器测试当成完整H2通过。

复用WorkspaceResolver的工程身份和worktree_root，不创建第二套项目身份。原固件、原.git/index/config/refs与正式build只读。隔离Git仓库使用独立对象库和索引；禁止hardlink到原源码，也不以git worktree add写原仓库管理目录。Git的可选索引刷新关闭。

捕获工作目录的最终原始字节，包括tracked、staged后又修改的文件、删除/改名、未跟踪和忽略文件。不能按扩展名或.gitignore删除可能被消费的输入。Git索引原始字节、阶段条目、staged/unstaged二进制补丁与HEAD分别保留；仅复制工作树会丢失“已暂存A、工作树又退回HEAD”对Git构建版本的影响，因此索引也必须复制。索引引用的未提交blob须以独立pack复制，不依赖原对象库或alternates。

捕获器先使用私有目录和SQLite文件清单，逐文件复制、哈希与记录，标记COMPLETE后才可供构建；失败保留FAILED/PENDING现场，不发布静态有效结果。源中的重解析点、未解决索引和未实现的嵌套Git边界显式失败，不跳过。捕获器不自动删除任何原数据。

接入前还需完成：

1. CMake/编译数据库使用既有relocate_config/relocate_paths映射，拒绝消费泄漏的原仓库输入；保留完整响应文件、生成头及真实命令闭包。
2. 验证__FILE__/__BASE_FILE__/__TIMESTAMP__等宏和路径映射的等价性；不能仅因源字节一致就宣称宏/构建输入相同。
3. 在真实解析前后校验隔离树与消费依赖，原工作区变化仍按原pin/输入门禁失效；保存恢复重做相同校验。
4. 原生full/Diff、staged/unstaged/rename/delete/untracked/ignored-header的全字段比较，真实外置CMake和只读固件测试，以及完整子模块支持。
5. 全部通过后才解除formal_workspace的拒绝门禁、开放向导复选项。既有静态分类、Diff影响闭包、verify_against_full和复核合同保持原样。

完整文件复制是正确性优先的实现起点；其峰值/最终物理占用必须实测，不计作70%收益。后续快照共享仅允许数据根内部的不可变内容，不能链接可写固件文件。
