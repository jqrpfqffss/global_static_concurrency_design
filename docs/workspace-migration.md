# 工程工作区与旧数据迁移

正式 Studio 和 CLI 的数据目录与旧 AppData 迁移见[工具数据目录](workspace-storage.md)。以下目录树说明兼容结果和 Git 缓存的组织，正式扫描归档放在活动数据根的 `scans/<扫描ID>/`。

```text
<ECRA>/workspace/projects/<最多24字符的ASCII名称>_<身份摘要前20位>/
  project.json
  scan.lock                    # 仅运行期间存在
  results/
    index.html                 # 保留现有页面与延迟加载布局
    opencode_review.html
    facts.json
    facts.db
    reports/ inventory/ review/ diagnostics/ html_details/
    cache/ snapshots/
    git_diff/
      artifacts/base-<SHA>/ base-db-<SHA>/ current-<SHA>/
      summary-cache/ evidence/ <指纹>.patch
  trees/base-<SHA前16位>/ current-<SHA前16位>/
  builds/<源码绝对路径与构建配置摘要>/
```

缓存、历史及 Git 产物仍放在 results 内，保持原报告相对链接和历史归档协议。构建与源码工作树分开。源码工作树使用较短的 trees 层级和 16 位提交目录名，避免 Windows Git 的 $GIT_DIR 长度限制；始终验证完整提交 SHA，短名冲突明确拒绝，不复用错误版本。Git 子命令启用 core.longpaths，且不写用户 Git 配置。两个角色即使比较同一 SHA，也保留各自 worktree；同角色同 SHA 重复使用，执行身份和输入校验。没有自动回收工作树或历史的后台任务。

## 身份与归属

`ecra.workspace.WorkspaceResolver` 统一解析工具、原工程、Git 仓库、结果、缓存、历史、Git 工作树及构建边界。原 `project_root` 不随分支改变；真正分析的 `analysis_root` 可以是隔离工作树。运行时路径上下文由程序建立，YAML 不能注入内部 `_workspace`。

身份为规范化仓库绝对路径与工程相对路径的 SHA-256。Windows 解析真实路径、统一斜杠并折叠大小写；Git 分支不参与身份。目录使用前 20 位，project.json 保留完整摘要、完整路径、相对路径、创建时间与初始输出位置，发现不匹配立即拒绝。工程移动产生新身份。工具移动而工程未移动时身份不变；应保留并搬迁完整 workspace。旧 project.json 的 output_root 可追溯原位置；包含旧绝对路径的检查点仍需通过输入校验，否则重扫，不改写指纹伪造命中。

目录标签只作显示辅助；完整中文工程名保存在元数据中。初始化先独占创建 project.json.pending，写入并刷新后发布 project.json。遇到遗留 pending 会明确报出初始化锁，不能把半成品当作有效身份。恢复时先确认创建进程已退出、备份目录并核对 JSON 完整身份；完整 pending 可改名为 project.json，不完整 pending 应保留为备份后重试。损坏的正式元数据不会被自动覆盖。

正常仓库通过最近的 .git 标记识别仓库边界；差异扫描再用 Git 验证真实仓库根。工具和固件应放在各自独立的目录。受管理的 workspace 可以位于工具仓库下。可写数据路径中的链接、项目身份冲突、未知数据目录和外置构建缺少所有权都会明确报错。

## 配置规则

默认不需要 output 字段：

```yaml
project:
  root: "D:/firmware/Board"
analysis:
  git_diff:
    enabled: true
    base_ref: origin/V8.20.1
    current_ref: HEAD
```

默认和自选数据目录：

```yaml
analysis:
  output:
    location: tool             # 默认 <工具>/workspace
    # location: custom
    # custom_dir: "D:/ECRA/workspace/data-roots/legacy"  # 当前工具下的绝对路径
```

旧 `output_dir: .ecra` 和 `output.location: user` 使用当前工具数据根。其它旧 output_dir、`location: project` 和工具外的 custom_dir 会提示修改配置和迁移。软件保留固件的忽略规则。

所有 run/full/diff/doctor/review/review-failed/report/status 使用同一解析层。status 不创建扫描结果或触发旧目录迁移；run/doctor 首次初始化时迁移。迁移前只有历史目录的工程，先执行 run 建立当前可验证扫描，再继续 review/report。

## Git 覆盖边界

* `include_uncommitted: false`：固定 base_ref 和 current_ref 的 SHA，分别在独立工作树扫描。包括 HEAD 在内，均不分析原检出工作区的未提交内容。原工作区有旧 .ecra 或业务修改也不会阻断已提交版本比较。终端及 HTML 明确写出这一覆盖边界。
* `current_ref: HEAD` 且 `include_uncommitted: true`：分析实际工作区。暂存、未暂存、删除、重命名、未跟踪文件参与差异、Patch 和内容指纹；不依据 build/.ecra 目录名过滤。被 Git 忽略的实际编译依赖还受 Clang 输入快照约束。
* 非 HEAD 引用不允许 include_uncommitted。引用变化、隔离源码污染、基准事实/摘要/Patch 破坏、输入闭包变化仍会阻断发布和恢复。

隔离工作树的编译数据库从对应提交读取，重定位后写到外部 artifacts，保持提交中的数据库原字节不变。没有可靠数据库的非 CMake 工程明确失败，不借用 HEAD 或原工作区的构建结果。

## CMake

固定提交扫描还检查实际消费的输入归属。子工程通过绝对路径引用原固件 Git 仓库的兄弟源码/头文件时，不会把原工作区内容当作所选提交发布：新版明确拒绝并列出文件。请将仓库内引用写成相对路径，提交可重定位的编译数据库，或使用所选版本的隔离 CMake 构建。真正位于固件仓库外的工具链仍按内容绑定；工具链应与固件仓库分开保存。包含未提交修改的当前侧继续允许读取原工作区，基准侧仍须满足固定版本边界。该检查不忽略任何源文件、不缩小 AST 范围，也不回退到原工作区。

默认 `analysis.cmake.location: workspace`。旧 build_dir 继续接受，参与构建配置摘要；其源码内路径不再是默认实际构建位置。编译数据库显式指向旧 build_dir/compile_commands.json 的配置仍可识别，实际使用当轮外置构建新生成的数据库。`-S` 指向 analysis_root，`-B` 指向工程 workspace/builds 的版本专用目录；generator、工具链、build_type、target、args、build_args 保留。旧 auto_configure_cmake 也通过同一构建实现执行。

清理仅限带当前源码所有权标记的专用构建目录。使用 CMAKE_BINARY_DIR 保存构建生成文件。外置生成头文件仍绑定到输入快照；两个版本的构建路径只在有当轮数据库证据时规范化比较，实际参数和哈希保留。

## 迁移与确认记录

迁移要求旧目录同时有匹配工程身份的 run.json、schema 1 的 scan_state.json、facts.db 和静态报告；仅一个名为 .ecra 的目录不构成归属证明。旧目录有 scan.lock 时先确认旧进程已退出；工具不擅自删除旧锁。

项目锁内枚举旧数据，拒绝链接，预估剩余空间，以 1 MiB 分块哈希并流式复制到 `.migration-pending`。逐文件验证大小和 SHA-256，再复核源文件集合及内容未变化；完成标记与整棵结果目录一起原子发布。中断或磁盘不足时保留原件和 pending，下次逐文件校验后恢复。不会全量读取 facts.json 来识别或迁移。

旧 HTML、facts、review、缓存、历史、未知附加文件全部保留；新扫描前按原归档协议存入 snapshots。migration.json 记录文件清单、哈希、字节数、耗时及 `PRESERVED_REVALIDATION_REQUIRED`。完整检查点同时绑定实际编译器、LibClang 和构建工具二进制内容，以及 PATH/CPATH 等编译输入环境；环境改变即失效。旧收据必须重新通过扫描指纹、引擎、源码和引用校验；失败保持历史可查，不能作为新变量的有效确认。当前分支没有独立的 HTML 人工确认持久化接口；已有 HTML 内嵌备注及 review 状态按原字节保留，不创造未经验证的变量绑定，也无法读取浏览器外部的私有存储。

包含工作区的 Git 扫描，仅排除 migration.json 清单中仍与原哈希一致的已知未跟踪产物；已跟踪文件、源码/头文件/CMake 输入、未知文件及输入清单实际消费文件均不排除。旧数据变化后立即重新进入工作区校验。

无法自动识别时，原目录保留并打印原因。手动恢复应先备份整个旧目录及外部引用，将副本归档到新 results/snapshots/下的独立目录，然后重跑。不要覆盖 project.json、改写 scan_state 的工程路径/摘要，或将旧 DONE 记录直接贴到新队列。没有通过旧归属校验的文件仍按普通 Git 输入处理。

## 运行、升级与空间管理

`workspace/` 已加入工具仓库忽略规则。Portable 打包使用源码/配置/工具白名单，不复制 workspace；升级请解压到新目录并保留原 workspace，工具写权限不足时显式选择可写 custom_dir。完整搬迁数据后重新扫描可重建绝对路径相关缓存，历史原件保留。不会将用户数据当作临时目录清理。

同工程运行与复核共享项目 scan.lock，不同工程锁独立；基准递归扫描使用其 artifact 内独立锁。异常退出后，先通过 PID 与运行日志确认进程已结束，再由用户处理遗留锁。报告、状态及缓存继续使用原子文件替换，迁移使用目录发布；后续扫描失败则标记 result_validity 无效，旧完整报告保留在 snapshots。

清理策略是人工审计：先备份整个项目工作区，检查 scan_state、报告 pin、复核收据和 snapshots 对 worktree、facts、Patch 的引用，再决定移走整个已废弃工程工作区。此版本不自动删除任何历史、缓存或被引用的提交。空间占用应同时统计 results、builds、worktrees、snapshots 和保留的旧 .ecra，不能只统计 index.html。

工具连同工作区迁移后，如果 Git 报“工作树登记路径不一致”，先备份旧目录并核实 project.json 的仓库和工程身份，再由用户在原固件仓库执行 `git -C "<repository_root>" worktree repair "<新工作区>/trees/base-<短SHA>" "<新工作区>/trees/current-<短SHA>"`，然后重扫。该命令只修复 Git 工作树登记，不切换或重置源码。仅复制工具且仍继续使用旧副本时，不应把同一登记转给副本；可选择新的空 custom_dir，保留旧 workspace 作为历史，重新建立独立工作树。不要手工改写事实/检查点摘要。

Portable 的 ASCII 别名覆盖实际工作区子目录，而非只覆盖工具根目录；因此工具名为 ASCII、项目名含中文时，ARM ar/ranlib 仍能使用正确的 ASCII 工作目录。真实存储路径和输入哈希不被替换，别名目标不匹配即拒绝。

Portable 对过深或含中文的实际构建目录使用经目标验证的短 ASCII Junction。仅使用 8.3 路径仍可能被 CMake 展开为长路径，无法满足 GNU Make/ARM binutils；构建别名因此与普通工具路径别名分别处理。无需用户安装额外运行时。

基准完整事实缓存命中前会重新配置/构建 CMake，随后校验实际生成物和编译输入闭包。即使自定义环境变量被 CMake 消费，也不能沿用旧生成头文件的事实。外置生成源码按原 build_dir 的逻辑位置执行 include/exclude 规则；原始事实、源码证据和输入哈希保留真实物理路径，比较摘要才规范化已证明归属的构建路径。
