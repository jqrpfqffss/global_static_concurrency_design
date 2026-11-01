# ADR-010：已提交版本的独立Git管理库（实施前合同）

## 已实施范围与局部验收

`ecra/independent_git.py`已接入prepare_current/prepare_base；复用现有工程身份/trees路径，在project_workspace/git-snapshots内复制独立镜像、保持全部refs/符号refs、原origin配置、HEAD及info/attributes/exclude。普通Git命令关闭可选索引刷新。新状态有CREATING/REFRESHING/READY，引用更新只从显式本地路径读取，旧refs/config/HEAD按状态独立保存；已有未知或原仓库登记的历史树拒绝接管。相同SHA复用前核对common-dir、登记、HEAD、配置/引用和所有权；中断不修理、不删除。

6项真实Git专项、20项冻结workspace回归、49项Diff回归通过：[收据](evidence/independent-git-v4.json)。包含全部原文件SHA/mtime、staged/dirty/untracked保留、独立对象无hardlink、Git describe/remote/symbolic refs、源tag增删刷新、身份篡改/中断/历史树拒绝。尚未覆盖完整大工程full/Diff同输入对照或只读挂载，不能关闭H1/H2/G1。包含字符串共享的778文件新完整回归另在冻结目录运行，未预报结果。

include、扩展、shallow、alternates、局部自定义钩子等不能证明等价的管理布局目前明确失败，不悄悄忽略。core.bare仅在私有管理库调整，实际检出的工作树仍non-bare。明确的旧格式开发/黄金验证入口保留已有project输出兼容；正式canonical入口的固件重叠拒绝门禁不变，本次实际用户工程没有使用该例外。

初轮失败保留：临时测试Git对象的只读属性导致破坏性独立性验证失败，已仅对测试自建对象chmod；现场未动真实源。旧workspace边运行边编辑实现导致两项实现变化门禁失败，随后在逐文件冻结副本重跑20项通过。早期Git兼容项目路径失败14项，修复后49项通过，没有删除/放宽原静态和Diff断言。

## 原始实施合同

已审计`git_diff.prepare_current/prepare_base → git(original, worktree add) → _relative_worktree_gitdir`。现行代码虽将源码树与构建放到外部，worktree登记仍写原`.git/worktrees`，不符合H2。只检查status/index不足以证明只读。

复用WorkspaceResolver的project_workspace/worktree_root与工程身份。准备已提交版本时先在该工程的独立git-snapshots目录创建不共享对象、不使用alternates的完整镜像，再由镜像建立相同既有路径的detached工作树。登记、索引、HEAD与对象只写数据根；原始仓库只读。原有base/current固定SHA、直接比较方向、相对Git引用兼容、源码污染门禁、编译数据库重定位、缓存、完整影响传播及verify_against_full逻辑保持不变。未提交快照仍拒绝，不能借此解除dirty门禁。

镜像必须复制全部refs/tags并核验捕获前后原refs/HEAD未变。对象必须独立（`--no-hardlinks`、无alternates）；不能用`--shared`或自动网络fetch。原始仓库配置/扩展若依赖未支持的外部Git管理布局，明确失败，不假设普通clone等价。创建失败保留现场，不重用半成品、不自动移除旧树。已有仍登记在原仓库的历史树完整保留；新准备不能改写其`.git`转接，需明确给出独立数据根重扫的办法。不同Windows盘符仍按既有规则保留可验证的绝对Git引用。

复用时检查所有权、源仓库、固定SHA、实际common-dir、refs/config与Git转接身份；拒绝被换成原仓库/其他项目/损坏中间态。原Git可选索引刷新关闭；绝不为扫描执行原仓库checkout/reset/clean/prune。

验收先完成真实Git测试：源含未提交/staged/未跟踪但只选提交版本；全部原源码与`.git`字节/mtime不变；镜像工作树Git版本/describe/refs与旧方式一致，工作树字节相同，原对象修改/删除不影响私有对象；复用/中断/错误SHA/身份替换/旧树保留。之后运行原workspace/Diff回归、真实F030外置CMake与原生full/Diff完整语义对照。未通过前不称H1/H2/G1完成；更不代替低完整性执行、只读挂载或完整dirty工作流。

依据：[Git clone独立对象与镜像选项](https://git-scm.com/docs/git-clone)、[Git worktree管理目录](https://git-scm.com/docs/git-worktree)。这些文档描述能力，本项目仍须以真实操作验收。
