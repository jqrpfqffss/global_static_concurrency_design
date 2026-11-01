# H2 未提交输入隔离：实施合同（进行中）

固定提交管理库已独立：prepare_current/base现在只在WorkspaceResolver所属git-snapshots登记新worktree；原.git不再承载这些新登记。真实Git6项、冻结workspace20项与Diff49项局部通过，旧树不改写/删除，详见[ADR-010](09-independent-git-adr.md)。复杂Git布局仍明确拒绝，完整只读挂载/dirty隔离/大型full-Diff仍未验，不能据此称H2通过；封存v12不含此后续实现。

## 正式启动所有权修正（与源码写保护分开）

已接入普通完整性OwnedProcess：Windows进程挂起创建、加入Job后才继续，解决venv转接器在文件gate前产生未受控真实解释器的问题。StartupInfoEx只继承NUL与日志句柄，创建失败无无Job回退，监视器关闭时回收本Job并等待后关闭句柄。真实venv/后代Job归属、受控OOM、当前源码Chrome15项停止/恢复/缺工具/再次扫描通过；见owned-job-regression-v2.json、browser-owned-job-v1.json、10-process-job-ownership.md。这**没有启用Low令牌或标签**；下述Low写保护仍为原型，H2/dirty完整隔离仍未通过。

## 已接入的任务临时目录控制

`resource_policy.temporary_environment`只在调用方已验证并持有的任务目录创建独占temporary子目录，覆盖子进程TEMP/TMP/TMPDIR/SQLITE_TMPDIR，不改broker环境、不复用已有临时目录、不回退到继承的固件路径。TaskManager在进程启动和Job放行前调用，编译器、Python及SQLite文件后备临时表均继承该环境；仍不代表其他H2隔离问题已经解决。

38项专项通过，真实子进程在传入TEMP=固件目录时仍将临时文件写入任务目录、源目录无新增；Windows8.3/长路径以实际文件身份核对。实际4TU原生再次与旧版完整事实/规范报告根比较差异0；真实Chrome15项停止/恢复/AI故障/同profile重扫通过，4个实际任务均有独占temporary目录，源及.git保持不变。见evidence/worker-temporary-v2.json。该修复晚于Portablev10；v10仍封存匹配434988c/1b573a1运行时，不冒称包含本修复或覆盖当前树的完整1189项。

## Windows进程写保护前置原型（尚未接入正式扫描）

`ecra/studio/write_guard.py`使用禁用特权的受限主令牌、Low完整性等级和显式标准输入/日志句柄继承列表，先挂起启动、加入受控Job后再继续。只为一个全新、无重解析点、与源码/程序目录不重叠的私有目录设置Low继承标签；现有目录一律拒绝，绝不改原固件/SDK/安装目录的标签。普通Medium或未标注的原始文件可读，Low子进程及普通后代的写操作由Windows阻止。此机制依据[Microsoft MIC文档](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)、[受限令牌](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)及[CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)。它不是防恶意代码的完整沙箱，也不证明构建输入等价。

当前Windows实测3项PASS：覆盖/创建/删除/建目录/原.git写入及后代写入全部拒绝，原固件可读且哈希不变，私有目录正常写入；源码/安装目录内部的新标签目录在创建前拒绝。另`scripts/validate_windows_write_guard.py`以冻结的parsed-F030配置在Low子进程实际CMake/Ninja/ARM编译链接成功、Clang解析peripheral.c为PARSED（6变量/9访问），原源码及.git全文件SHA不变，收据evidence/windows-write-guard-v1.json。

失败尝试均保留：v1诊断脚本引号错误；v3误选早期缺少系统头探测的基线配置，链接成功而Clang为FAILED；v4显式使用早已冻结的auto_system_includes=true配置成功，没有改变原固件/配置。该验证只构建独立小工程并提取一个TU，不当作全量扫描、Portable/只读挂载或H2验收。

生产接入仍需将所有可写工作区、缓存、构建和隔离Git元数据放在全新私有工作胶囊内，由普通完整性broker验证后发布权威归档/人工事件。禁止为方便执行而重标现有整个数据根。原先已是Low的文件、网络文件系统、非管理员干净机尚未验证；正式dirty扫描门禁和原.git/worktrees问题仍未解除。

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

新增真实Clang实验：只在测试中向原参数注入VFS overlay，不改生产Extractor、unit或算法。显式文件映射保留原逻辑文件名/宏/sizeof(__FILE__)布局/原始缓冲及完整事实；原测试源和头改写后仍读取冻结字节。redirect-only将捕获时不存在的__has_include探测保持为不存在，外部SDK显式映射；同样映射若允许fallthrough则读到后来新增的忽略头文件，完整对照失败。`working-vfs-1.log`单项PASS，源码在test_working_snapshot；此实验未包含于3590227的1161项冻结全回归，也未开放正式dirty扫描。

依据为[LLVM18.1.8 RedirectingFileSystem实现](https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-18.1.8/llvm/lib/Support/VirtualFileSystem.cpp)：该版本接受redirect-only、use-external-names和显式文件/目录映射。生产接入仍须审核外部include根、原编译/预处理闭包、缓存和重做、Git/CMake元数据；不能把一个Clang视图实验当作整个只读构建通过。另确认现有committed Git worktree注册仍写原.git/worktrees，完整H2不能只以Git status/index未变化宣布通过，后续须改独立Git管理库并验证构建语义。
