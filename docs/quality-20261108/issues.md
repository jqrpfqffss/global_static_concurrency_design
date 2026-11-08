# 问题与修复台账

仅当前代码证据充分或实际复现的问题进入确认台账。历史描述、审美建议和新功能设想不作为已确认缺陷。

当前状态以[最终 V9 记录](continuation-final-v9.md)和下列当前表为准：本轮所有确认且可执行的代码修复已在本地主区，engine2b9e；最后 Q405 GUI 已在正式 V9 解压包独立操作复验。下面早期“候选、待合入”等单元格保留发现当时状态，不能解读为当前仍未修。原失败未被改写；大型正式发布/性能与目标环境缺口仍单列。

## 当前处理状态

| 编号 | 当前状态与必要边界 | 最终相关证据 |
|---|---|---|
| Q001、Q301–307 | 已修并在实际配置/构建/交付复验；Q307正式包8份用户说明59链接有效，OpenCode仍外部安装 | delivery、continuation-build、continuation-headers、continuation-offline-build-v9 |
| Q101–109 | 已修并复验原场景与相邻入口；坏记录隔离不破坏邻项，状态/清单共享合同，停止可中断，容器不重复人工待办，叶风险保留 | state、continuation-regression、continuation-q108-ui、continuation-q109 |
| Q201、Q202、Q205、Q206 | 已修严重误安全和证据丢失；真实向量/alias/保护正反例、独立推理与真实工程通过；未知/不支持不补成安全 | analysis、continuation-q205-independent-review、continuation-q206、continuation-final-projects-v4 |
| Q203、Q204 | 已修受控ASM协议及路径别名/已有toolchain缓存；真C+ASM与CDC cold/warm/工作字节流程通过 | continuation-headers、continuation-diff-v4、continuation-diff-v6 |
| Q207–209 | 已修索引自改写、Git2.37相邻误选、权限预检误通知及native注册身份竞态；严格监控未放宽，主区55/包Git18及最终ARM链路通过 | continuation-final-v8、continuation-diff-v8、regression/main-v8-git-smoke |
| Q206-UI、Q401–404 | 已修alias关系措辞、确认按钮、保存失败提示、TU处理/覆盖标签、已知枚举；真实操作/故障/持久化/长链/最终V8画面通过，V9相同相关逻辑 | package-ui-final-v8、continuation-q108-ui、ui |
| Q405 | 已修；正式V9小窗口F411/NMI共同确认入口复验通过，三人工事件及静态原件不变；最终原生Diff确认入口亦实际查看 | q405-v9、continuation-native-diff-ui-v9、evidence/final-v9-ui |
| D001（诊断限制） | 资源JSON write_bytes未反映真实进程写出，界面未使用该字段；保留未修，不用该值作吞吐结论；非当前主要流程阻断 | continuation-final-v9、inav-publication-bounded-observation |

## 发现与修复的原始过程

| 编号 | 级别/影响 | 复现条件与实际行为 | 预期及依据 | 根因 | 修复位置 | 复验与证据 | 状态 |
|---|---|---|---|---|---|---|---|
| Q001 | 重要：新用户可能准备错误运行时 | README混用3.10.9/3.12.10 | 当前Portable配置和cp310依赖 | 旧版本说明残留 | README | 版本/本地链接核对、离线缓存检查；见delivery.md | 已修复 |
| Q101 | 重要：坏任务阻断全部Studio | 截断JSON或缺mode/scan_id使启动/列表/详情异常；复制登记同类 | 独立有效结果可继续访问，坏记录不能冒充恢复成功 | 登记读取缺少隔离与结构检查 | task_records.py、tasks.py、root_transfers.py及两处UI | 坏原件不改、有效邻居仍可用；实际服务重开、29项状态回归 | 已修复 |
| Q102 | 重要：假运行/假完成 | worker已退出，完成收据坏/缺/矛盾导致监控异常而仍留RUNNING | 无有效收据不得宣称成功 | 完成收据读取/一致性验证不完整 | tasks.py | 错码、坏类型、缺字段、130停止、有效收据相邻回归 | 已修复 |
| Q103 | 重要：失败详情和恢复入口消失 | 缺console.log或一份坏诊断令全部detail失败 | 有效状态与其他诊断仍可读 | 任意文件读取异常扩散至整个详情 | tasks.py、TaskCenter.vue | 缺日志、坏preflight/stages与有效异常共存；原件保留 | 已修复 |
| Q104 | 重要：复制崩溃后一直显示发布中 | 外层job在PUBLISHING时监督器退出，重开仍轮询 | 显示中断且可验证恢复 | 启动清理遗漏外层PUBLISHING | root_transfers.py | 外层INTERRUPTED，底层原journal不变，原子rename后恢复回归通过 | 已修复 |
| Q201 | 严重：错误安全结论 | 自定义C入口绑定NMI/HardFault/slot2/3，PRIMASK被判有效并输出SAFE_PROVEN | PRIMASK不能屏蔽这些物理异常 | 保护判断只依赖函数名称/标记 | protection.py | 原四例全变SUSPECT；真实向量表、IRQn、BASEPRI/FAULTMASK和普通IRQ对照；analysis.md | 已修复；旧扫描须重扫 |
| Q202 | 重要：AI证据不足掩盖静态风险 | 同一静态SUSPECT + DONE/NEED_MORE_CONTEXT，报告likely，Studio UNKNOWN | 原decisions契约：证据不足不证伪静态冲突 | SQL投影跳过静态回退 | studio/current_results.py | 30格跨实现矩阵、10种多finding排列；原AI答复与待办保留；analysis.md | 已修复 |
| Q301 | 重要：合法工程扫描失败/预检查输入缺失 | 真实CDC的相对CMAKE_TOOLCHAIN_FILE按工具cwd解析，错误报告输入变化；预检查忽略同一文件 | CMake build优先、source后备的真实路径 | CLI及预检查未统一解析缓存路径 | compilation.py、cli.py、studio/preflight.py | 真实CMake中文空格路径对照、输入变化仍拒绝；预检查快照包含相对toolchain；37项回归 | 已修复 |
| Q302 | 重要：新用户ARM数据库配置普遍缺标准头 | init和Studio新向导默认不探测系统头；真实F030四TU均FAILED，缺stdint.h | 新配置应使用实际编译器标准头，已有显式配置必须保留 | CMake与数据库新配置生成行为不一致 | config.py模板、App.vue新建默认 | 真ARM编译→init→Clang回归；真实旧/新向导对照，从4 FAILED变2 PARSED+2 PARTIAL；无覆盖伪装 | 已修复 |
| Q303 | 重要：照抄下一步命令进入错误工程 | init --config外置成功后打印doctor/run却省略配置路径 | 命令必须继续同一显式配置 | 成功提示丢失配置参数 | cli.py | 中文空格/单引号路径测试，输出保留PowerShell安全引用；delivery.md | 已修复 |
| Q304 | 重要：文档示例命令不可执行 | README --profile参数被当前CLI拒绝，退出2 | 实际help与命令分派 | 旧Studio/CLI约定混用 | README | 原错误收据保留；改为实际--config入口 | 已修复 |
| Q305 | 重要：找不到默认结果、示例可能覆盖活动配置 | README/配置注释仍称默认HTML；原示例setup写活动配置，源码UI缺完整依赖指引 | 当前SQLite/Studio入口与配置保留要求 | 重构后说明未同步 | README、config/semantics.yaml及模板注释 | SQLite实际report/status、示例改独立配置根、完整Studio依赖说明；delivery.md | 已修复 |
| Q401 | 一般：签署按钮落在笔记本视口外 | 1366×768打开人工填写区，动作底边y≈797>768 | 主要操作可见，长证据仍可滚动 | 表单打开后仍强制约302px证据最小高度 | App.vue高度测量 | 表单展开降低最小证据高度，按钮底边≈745；实际填表、保存、独立两尺寸操作；截图03/04 | 已修复 |
| Q402 | 一般：写入失败无法理解恢复方法 | 真实SQLite写锁超时仅显示英文database is locked | 说明保存阶段、草稿/旧记录及下一步 | 通用数据库错误直接透传 | studio/server.py、test_studio_api.py | 真实锁原场景保留草稿，解除后重试成功；DATABASE_BUSY/409与无虚假saved回归 | 已修复，最终浏览器提示复验另见ui.md |
| Q403 | 一般：处理计数易误认为解析成功 | 旧向导四TU都FAILED时页面仍显示“TU解析完成4/4” | 处理数与覆盖成功数分开 | 计数标签不准确 | TaskCenter.vue | 改“TU已处理（含解析失败，成功范围见覆盖诊断）”；实际恢复后页面可见 | 已修复 |

未将纯审美偏好或新产品设想列为缺陷。测试预期调整仅限Q202，独立依据为既有核心决策合同，详见analysis.md。没有降低安全判据、移除检查、改写历史确认或把部分解析算作完整覆盖。

## 续轮确认问题（合入前状态）

| 编号 | 级别/影响 | 复现条件与实际行为 | 预期及依据 | 根因 | 修复位置 | 复验与证据 | 状态 |
|---|---|---|---|---|---|---|---|
| Q105 | 重要：一个坏报告阻断全部结果 | manifest为合法JSON数组，/scans整体500、summary500，有效邻居仍可单独读取 | 坏项隔离并解释，独立有效结果可用 | 无容器/状态/身份合同且异常扩散至列表 | studio/server.py显示清单共用读取 | 候选49项、真实HTTP11检查；LOCAL/REPORT及DB UNVERIFIED独立合同 | 候选已修，主区待合入 |
| Q106 | 重要：损坏导入返回泛化500 | 非ZIP、坏CRC、非对象清单及坏既存合并目标 | 告知导入阶段、影响和下一步，保留旧记录 | ZIP错误未域化、容器读取先于校验 | studio/server.py上传边界 | 真实HTTP故障和标准包往返、原件与已有签署保留 | 候选已修，主区待合入 |
| Q107 | 重要：长SQLite检查中停止无响应 | 真12.6GB历史原件的EvidenceProvider.validate，5秒停止、15秒外部截止仍不结束 | 必要完整检查可被正常停止，不误发布 | 仅排队Python中断，SQLite C调用尚未返回 | scan_diagnostics.py、scan_store.py | 同原件最终5.328秒结束；75项/95子例、旧权威库不变及无半发布 | 候选已修，主区待合入 |
| Q108 | 重要：坏结果仍可进详情并整页空白 | 坏summary后点击查看全部变量、带AI历史的systicks；实际null.result_revision | 失败明确、阻止依赖未就绪结果的操作，可恢复有效历史 | 入口只判scan存在、未判结果读取成功 | App.vue、ScanIdentity.vue | 实际1366窗口前后截图、重试/历史恢复/保存/关闭重开继续 | 候选已修，主区待合入 |
| Q109 | 重要：容器重复加入人工待办，报告分母与界面不一致 | 新构建F4114项、CDC20项STRUCT_MEMBER_CONTAINER缺标签，被旧投影默认UNKNOWN；叶风险已独立分析 | 既有父容器汇总不重复分类/确认契约；旧库原件及显式风险保留 | analysis最终汇总遗漏nested kind；读取层将缺标签与显式UNKNOWN混同；HTML成员表也只按根取 | analysis.py、scan_store.py只读查询、current_results.py、html_report.py、App来源提示 | 102项相邻；真实旧F411深验/包往返、Studio两视口；v3全扫3工程353非容器JSON全同、仅24nested汇总修正；HTML视觉file协议受阻 | 候选已修，v3范围已验；Q205后需最终复验 |
| Q203 | 重要：合法C+ASM工作字节构建被拒绝 | CDC dirty扫描中官方CMake的ASM --version查询被当成任意execute_process | 只接纳可证明的官方只读查询，未知命令仍拒绝 | 白名单漏掉官方ASM识别协议 | working_cmake.py | 实际C+ASM捕获与联合stdint解析，项目进程和11边界反例仍拒绝 | 候选已修，实际dirty整轮继续 |
| Q204 | 重要：无语义变化重复全局计算 | 同物理build目录因注册顺序、首次不存在/再次存在而改变别名；重复toolchain -D另改Cache类型/帮助元数据 | 同物理目录稳定路径；同真实toolchain已缓存且不clean时保持缓存选择，变化/新/clean仍显式传参 | compact复用祖先及缺失目录分支；无条件重复-D | v4 portable.py、compilation.py | 33路径及35工具链邻接、真实三次Cache/CDB稳定和变化toolchain正例通过；v4关键组合及中文正例通过；最终同根warm正在跑 | 候选已修，最终warm/dirty待完成，主区待合入 |
| Q306 | 重要：中文便携路径标准头丢失 | Windows ACP936的GCC stderr被UTF8替换，探测失败 | 按实际输出无损恢复真实目录，歧义明确失败 | 默认文本解码；受控执行器原先不提供严格二进制协议 | compilation.py、guarded_cmake.py | 原raw字节、29项、真实C+ASM/auto_system_includes/stdint联合4项通过 | 候选已修，主区待合入 |
| Q205 | 严重：配置抹去真实NMI/HF物理证据后误判安全 | 真实C向量表slot2/3及GCC/objdump重定位均绑定ExceptionRoute；原同ID手工context可覆盖恢复属性，将PRIMASK从无效变有效并输出SAFE_PROVEN | 不允许同ID声明删除已恢复的slot/unmaskable/真实入口；矛盾字段明确拒绝 | context_graph整对象覆盖；相邻producer/split同ID碰撞 | v4 analysis.py、physical.py、protection.py | 真实10例、13定向/88邻接及独立13通过；联合26和实际NVIC/BASEPRI正反例通过；三真实工程最终全扫通过，v4关键组合通过 | 候选已修并复验，主区待合入；大型整轮另计 |
| Q206 | 严重：GNU C函数别名使真实中断体不可达而误判安全 | 原ExceptionRoute以alias指向Impl，slot2引用声明名；GCC/nm同址且Impl有共享写，图却漏入口到实现并给SAFE | 可证明别名必须传播入口/访问并保留来源；不支持则解释失败且不发布假安全 | 提取/入口解析未关联编译器函数别名目标 | v4 extract.py、vectors.py | 真实GCC/nm、宏/后定义/头、强覆盖/输入顺序；13定向/80邻接及联合26通过。实际CLI已发布SUSPECT+Studio三接口200；不支持ABI退出3并保留worker事实；三真实工程及v4关键组合通过 | 候选已修并复验，主区待合入；支持边界详见Q206记录 |

Q105候选相邻回归R1：本轮新白名单曾漏掉合法`ECRA_LEGACY_IMPORT`，完整/降级迁移完成后被候选列表误标FAILED。原74服务没有此回归，主区未混入。r2共享合同已精确修复并用真实两类迁移和包往返通过；未放宽unknown/identity/LOCAL状态。

Q105相邻遗漏R2：history原来独立读清单，坏LOCAL state字符串COMPLETE在目录为FAILED/summary400，却在history为COMPLETE/can_open:true。r2抽出display_manifest.py共享校验，并以包合同4MiB统一原history1MiB差异；最终19/19、1142.022秒、0skip已通过，原数据字节不变，最终v4组合还在覆盖相邻入口。R1旧51方法因外层1200秒先到期，仅27方法完整ok；余24从同字节源续跑，不能称旧单次51通过。

Q201相邻保守误报：实际HardFault已知slot3时，原FAULTMASK谓词误把其PRIMASK/BASEPRI不可屏蔽标记同时用作FAULTMASK禁止证据；有效正例的原失败保留。v4已仅为已证实slot3修正，NMI/未知/混合unmaskable仍禁止；原SAFE正例及相邻反例通过，没有删断言或xfail。

最终组合更新：Q205/Q206以及Q201的HardFault相邻修复均已冻结到v4并通过独立及联合实际ARM样例，详见[最终组合进度](continuation-final-v4.md)、[Q205独立审查](continuation-q205-independent-review.md)、[Q206](continuation-q206.md)。上表“进行中”保留为问题发现当时状态；当前为候选已修、主区待合入、最终工程/封包运行中。Q105 R1/R2最终共享合同19项已通过，没有把控制器超时的原51项写成单次全通过。

| 编号 | 级别/影响 | 复现条件与实际行为 | 预期及依据 | 根因 | 修复位置 | 复验与证据 | 当前状态 |
|---|---|---|---|---|---|---|---|
| Q307 | 一般：便携包文档链接断开、输出位置指引过期 | 正式脚本仅复制rearchitecture，而当前入口链接根级教程；CLI短说明默认指向index.html | 无源码分发也能读承诺的操作教程；正式CLI结果进Studio，legacy需显式选择 | 打包文档复制范围未跟随Studio改动、旧CLI文案残留 | 独立builder/build_portable.ps1，docs/portable-usage.txt | 明确复制根级md及assets、主教程直链；正式离线构建和解压链接检查进行中 | 候选已修，待成品复验及主区合入 |

| 编号 | 级别/影响 | 真实复现与根因 | 修复/验证位置 | 当前状态 |
|---|---|---|---|---|
| Q206-UI | 一般：正确别名关系被说成普通调用 | 实际新包NMI调用树显示“调用者→当前函数 main.c:3”，同边完整证据却是GNU_FUNCTION_ALIAS/alias声明；不是一条运行时callsite | CallNode.vue按已有summary.call_kind区分上下游别名、声明位置/证据标题，普通调用不变；独立四方向/类别实际库审查通过；源码入口1366/1920画面已查看，PageDown后标签可读 | 候选已修，最终新包待验 |
| Q404 | 一般：已知完成覆盖状态显示未识别 | 实际历史页将分析器合法MODELED_SCOPE_COMPLETE写成“未识别状态”；History与身份窗口共用label遗漏此枚举 | mutable UI api.ts仅加“已完成建模范围分析”，保留其它未知值原fallback；vue-tsc/Vite通过，最新asset DBiOaukX | 候选已修，最终画面待验；不表示全工程安全 |
| Q207 | 重要：只读Git采集改写用户索引并触发保护 | 真实fresh-stat CDC副本执行原working_snapshot git diff，在GIT_OPTIONAL_LOCKS=0下仍create index.lock/replace index；source字节不变，InputWatch拒绝 | 独立对照仅命令级diff.autoRefreshIndex=false后index SHA不变、diff stdout相同、native通知0；官方Git合同确认默认auto refresh。独立共同入口候选由analysis_correctness修验 | 原场景失败已证，候选进行中，不能盲重试记过 |
| Q208 | 重要：冻结前权限预检的目录通知误拦工作字节 | 实际dirty仅.git/logs/refs通知发生于首次只读ACL遍历、早于固定HEAD阶段；真实fresh clone自然对照和ETW定位到同诊断Python只读open/close，0 SetInformation；源/HEAD/index未变 | 候选采用权限准入→原mask watch→第二次严格权限检查+watch.check，仍需证明权限竞态及所有固定后真实变更拒绝；不删mask、不忽略.git、不过度推断NTFS底层机制 | 原场景失败已证，独立修验中，最终dirty尚未通过 |

验证夹具T002（不作为产品stop失败）：原Q107单模块进程12秒总预算在old.db准备14秒时已超时；publish停止线程还会在真正SQL进入前自行5秒到期。阶段证据`v4-sqlite-fixture-diagnostic/`已证明。独立test-only候选将准备预算与实际stop响应时钟分离，总限180秒，必须真实进入SQL/真实写stop，响应仍严格<5秒，旧库/无发布/无pending/零连接六断言未变；3方法/两busy子例和8邻接全过。原140组合的这两子例ERROR仍保留，不能倒改为原套全过。

| 编号 | 级别/影响 | 实际复现/根因 | 修复及原场景复验 | 当前状态 |
|---|---|---|---|---|
| Q209 | 重要：监控注册瞬间可能绑定错误目录对象 | 原InputWatch.directory先注册native通知再锁身份；独立检查在注册时机执行真实rename/replace，再对新目录source做修改→还原字节/mtime，旧watch未察觉。未声称实际发布了错误安全结果 | 父→子no-delete锁先于注册，无reparse及volume/fileID前后核对；部分失败只释放本次资源。原真实时机重放现在WinError32阻止替换；后续ABA可检测，close后锁清空且目录可rename。独立19项和候选71项通过 | 已合入；真实CDC工作字节整轮运行中 |

Q207最终修复还覆盖无内容变化的fresh-stat假Diff：三项name/name-status查询按Git `--exit-code` 的0/1真实内容契约，带命令级`diff.autoRefreshIndex=false`；patch命令仍保留其原退出契约，错误stderr不吞。真实staged/unstaged/delete/带空格R100 rename/untracked均通过，stable.c不误入，索引逐字节不变。Q208修复后仍保留原完整通知mask及严格两次ACL准入，不忽略.git目录。见[独立复核](continuation-q207-independent-review.md)。

**Q207相邻回归R3（上述旧“最终”措辞已失效）**：合入V6后，主区65方法复验在宿主Git2.37.2出现stat-only误选与隔离副本误拒；包内Git2.56.0.3下先前通过不能外推到旧版Git。关闭autoRefreshIndex后，旧Git的raw名字即便加exit-code仍不强制内容核对；这是本轮修复的相邻回归，不把它追认成原始代码同样行为。原FAIL/ERROR保留，候选v3正在以实际numstat内容记录核对名称，两Git/两config/四fixture共16对照已证明该方向；0/0重命名不能丢，未匹配内容须明确失败。最终修复尚未合入或放行，完整证据在`regression/main-v6-smoke/git-environment-diagnostic/`。

Q404相邻实际使用还发现ADDRESS_TAKEN已知访问值显示未识别。`extract.py`真实产生READ/WRITE/RMW/ADDRESS_TAKEN四值；最后只补“取地址”，未知fallback不变。V7 vue-tsc/Vite通过，GUI为DHpgztut；不改变静态事实/分类和人工记录。后续新成品画面另验。

12:15当前状态：Q207 R3最终内容记录修复已在两Git25/18项与独立32case、原两失败、8技术错误中通过，12:12已备份合入主区V8/core2b9e；原V6 FAIL/ERROR保持。Q404已主区构建重现相同产物，实际1366窗口修后截图已查看。V6真实CDC dirty完整2350.391秒结束、输入/HEAD/index不变、独立full分类/语义mismatch0；最后Git查询的受影响小工程最终包端到端另验。Q101–109、Q201–209、Q301–307、Q401–404的当前修复均已在本地主区，最终主区/成品终验仍需结束；详见[最终V8验收](continuation-final-v8.md)。

| 编号 | 级别/影响 | 复现条件与实际行为 | 预期及依据 | 根因 | 修复位置 | 原场景复验与证据 | 当前状态 |
|---|---|---|---|---|---|---|---|
| Q405 | 重要：连续复核时动作处丢失当前对象身份 | 实际native小窗口从F411长证据/源码滚到确认栏，项目/变量标题在视窗外，仅剩“当前：待确认”；未实证发生错误签署 | 确认动作同屏可辨别项目、变量、位置与独立人工状态 | 共同确认栏只呈现状态，没有对象上下文 | studio/src/App.vue、studio/src/workbench.css；共同入口一次修复 | V9源码预览、正式解压包F411/NMI切换实际操作及截图；三事件payload不变，native Diff另验。见[q405-v9](q405-v9.md) | 已修复并在正式成品通过；静态/AI/人工逻辑未改 |
