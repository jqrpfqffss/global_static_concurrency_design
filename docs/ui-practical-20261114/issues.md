# 问题及阻断台账

本台账区分本轮产品缺陷、测试准备错误和历史工具阻断。I01–I13均已在更新后的实际程序沿原路径修复并通过；本轮记录已收尾，受阻功能及附加未形成的异常边界不计通过。原有未提交删除项没有纳入本轮修复。

## I01：文本筛选摘要变化，列表仍为旧结果

- 页面与数据：变量与风险→筛选，demo-a归档dc5e3796…，先搜索state得到6项。
- 操作：按定义位置/降序，填写定义文件other.c，立即查看结果或关闭。
- 原实际：摘要变成other.c，列表仍6项，包括main.c/shared.h。预期应立即限制到正确对象，不能要求额外主搜索。
- 根因：文本依赖原生change；关闭移除焦点输入时，查询更新没有可靠提交，摘要却已随v-model变化。
- 修复：[filterUpdates.ts](../../studio/src/filterUpdates.ts)对输入防抖，关闭/查看/Esc前提交待更新条件；[App.vue](../../studio/src/App.vue)统一入口、支持回车和组合输入、页面切换取消。未删除功能或降低校验。
- 复验：index-Cn6c7cff.js中other.c正确1项；不存在函数+关闭、不存在上下文+Esc均0项。
- 状态：已修复并通过。
- 证据：[原画面](../../output/playwright/ui-practical-20261114/06-filter-file-stale-before.jpg)、[原快照](../../output/playwright/ui-practical-20261114/06-filter-file-stale-before.txt)、[新版画面](../../output/playwright/ui-practical-20261114/10-filter-file-fixed.jpg)、[新版快照](../../output/playwright/ui-practical-20261114/10-filter-file-fixed.txt)。10号采样仍显示读取状态，最终稳定结果由主代理实际会话核对。

## I02：已知DMA复核缺口显示“未识别”

- 页面与数据：覆盖与诊断，demo-a有1条变量阻断、5条缺口，DMA过滤匹配2条。
- 操作：查看类型与完整证据。
- 原实际：DMA_SHARED_REVIEW显示“未识别缺口类型”，缺少可用核查说明。
- 根因：[CoverageCenter.vue](../../studio/src/CoverageCenter.vue)展示字典没有覆盖引擎已生成类型。
- 修复：补充DMA共享缓冲区待复核和外部函数缺实现的准确中文说明，列表同时保留原始code；没有改动引擎事实、变量分类或安全结论。
- 复验：index-BjcqUQke.js从历史切回demo-a，DMA2条显示中文及原code；完整证据说明生命周期、CPU时机、缓存一致性和所有权交接，明确不单独证明错误。
- 状态：已修复并通过。
- 证据：[原画面](../../output/playwright/ui-practical-20261114/11-coverage-unknown-label.jpg)、[原快照](../../output/playwright/ui-practical-20261114/11-coverage-unknown-label.txt)、[新版画面](../../output/playwright/ui-practical-20261114/19-coverage-labels-fixed.jpg)、[新版快照](../../output/playwright/ui-practical-20261114/19-coverage-labels-fixed.txt)。

## I03：证据标签被后到数据或重读重设

- 页面与数据：变量详情，stress真实归档；选择054后证据仍读取时立即点调用标签。
- 原问题与预期：异步完成后或保存同对象时重设默认标签，不能稳定保留用户阅读选择；预期当前标签不被后到数据覆盖。
- 根因：[App.vue](../../studio/src/App.vue)原loadSelection在并行请求结束后设置detailTab，也没有区分新对象与相同对象重读。
- 修复：只在新对象选择开始时初始化默认标签/源码位置；同对象重读保留阅读位置。
- 复验：index-BjcqUQke.js读取中立即切调用最终保持；保存后标签不变，055重开仍保持调用。
- 状态：已修复并通过。
- 证据：[新版画面](../../output/playwright/ui-practical-20261114/18-next-item-fixed-1920.jpg)、[快照](../../output/playwright/ui-practical-20261114/18-next-item-fixed-1920.txt)、主代理本轮快速切换与保存操作记录。附属浏览器没有被充作本项复现来源。

补充观察：最后一轮快速同批次点击源码标签时曾有一次疑似跳回，未独立重现；随后单步选择header实例并点调用，稳定保持。该瞬态未作为新增已确认缺陷，也未用于扩大通过范围。

## I04：确认后“下一项”跳回较前对象

- 页面与数据：人工确认第2页，stress155对象、150待办。
- 操作：第2页确认050与052后，在052详情点击下一项。
- 原实际与预期：跳回048而非后继，打断连续处理；050/052保存身份本身正确，不是串写。
- 根因：[App.vue](../../studio/src/App.vue)用确认后刷新列表的findIndex计算相邻位置；所选项已移出待办时得到-1，无法代表原序列位置。
- 修复：保存与扫描、对象、筛选范围绑定的位置锚点；移出队列后的下一项取填补该位置的后继，前一项取前驱，并处理页末收缩、页码和禁用状态。
- 复验：index-BjcqUQke.js第二页054→055、页末100→101均正确；刷新继续上次位置回长变量。独立审计确认4条人工签署的身份/指纹正确。
- 状态：已修复并通过。
- 证据：[原确认](../../output/playwright/ui-practical-20261114/13-next-item-before.jpg)、[跳回048](../../output/playwright/ui-practical-20261114/14-next-item-wrong.jpg)、[修复后](../../output/playwright/ui-practical-20261114/18-next-item-fixed-1920.jpg)、[050/052审计](../../output/ui-practical-20261114/audit-after-stress-paging.json)、[054/100审计](../../output/ui-practical-20261114/audit-before-package-import.json)。

## I05：人工增量导出完成提示误称完整结果包

- 页面/操作：历史详情导出人工确认增量，前往数据与共享查看完成记录并真实下载。
- 原实际：实际文件是含6个完整事件的UTF-8增量JSON，完成提示却显示“完整结果包已就绪”，可能使用户误以为含完整源码证据。
- 根因与修复：[ExportProgress.vue](../../studio/src/ExportProgress.vue)完成态没有区分job.kind；已按delta显示“人工确认增量已就绪”，完整包保留原说明，没有改变导出内容。
- 复验：index-Dz_fcmH4.js实际页面的增量/完整包完成文案分别正确，已查看关键视口截图。
- 状态：已修复并通过。
- 证据：[包实操P02](package-review.md)、[增量包审计](../../output/ui-practical-20261114/audit-export-delta.json)、[新版完成提示](../../output/playwright/ui-practical-20261114/package-84-i05-delta-complete-visible.png)。

## I06：已结束任务仍显示交接进行态

- 页面/操作：打开已经COMPLETE/published的demo-a重扫4198及demo-b差异9961任务。
- 原实际：标题已经“扫描已发布”，下方role=status仍提示“预检查通过，已进入正式扫描”，终态与进行中语义冲突。预期已结束任务不再显示进度交接提示，历史阶段仍可追溯。
- 根因与修复：[TaskCenter.vue](../../studio/src/TaskCenter.vue)原显示优先判断progress_kind，而完成任务仍保留诊断字段。新增preflightNotice，仅对RUNNING/STOP_REQUESTED显示交接提示；任务引擎状态及阶段历史不改动。
- 复验：Dz版从任务历史打开已结束Diff9961，标题已发布且没有交接进行态提示，历史阶段保持。
- 状态：已修复并通过。
- 证据：[终态仍有进行提示](../../output/playwright/ui-practical-20261114/21-diff-task-label-before.jpg)、[快照](../../output/playwright/ui-practical-20261114/21-diff-task-label-before.txt)、[针对性回归](regression-details.md)。

新版证据：[25-diff-task-terminal-fixed](../../output/playwright/ui-practical-20261114/25-diff-task-terminal-fixed.jpg)、[页面快照](../../output/playwright/ui-practical-20261114/25-diff-task-terminal-fixed.txt)。

## I07：比较详情将INCOMPLETE显示为未识别状态

- 页面/操作：demo-a旧dc5与新4198正常比较后，打开双方构建身份与完整根摘要。
- 原实际：覆盖显示“未识别状态：INCOMPLETE”；历史列表已有局部正确翻译，详情却缺失。预期已知部分覆盖状态在各处含义一致。
- 根因与修复：[api.ts](../../studio/src/api.ts)共用字典缺项；补充“部分覆盖（INCOMPLETE）”，[HistoryCenter.vue](../../studio/src/HistoryCenter.vue)移除重复局部特判。未知新状态继续明确保留未知，不改变比较算法。
- 复验：Dz版沿dc5→4198正常比较进入完整根摘要，双方覆盖均为部分覆盖（INCOMPLETE）。
- 状态：已修复并通过。正常比较16共同对象、搜索与当前证据导航本身已通过。
- 证据：[原详情](../../output/playwright/ui-practical-20261114/20-history-coverage-label-before.jpg)、[完整快照](../../output/playwright/ui-practical-20261114/20-history-coverage-label-before.txt)、[回归记录](regression-details.md)。

新版证据：[26-history-coverage-label-fixed](../../output/playwright/ui-practical-20261114/26-history-coverage-label-fixed.jpg)、[页面快照](../../output/playwright/ui-practical-20261114/26-history-coverage-label-fixed.txt)。

## I08：真实Diff任务标题误称完整扫描

- 页面/操作：demo-b Git差异任务9961完成后打开任务详情。
- 原实际：标题为“完整扫描·扫描已发布”，而实际阶段和归档是双版本差异。差异结果13项及真实源码变化本身正确。
- 根因与修复：全量/Diff任务元信息共用mode=scan，前端却固定映射为完整扫描。TaskCenter改为准确通用“扫描分析”；不从可能后来修改的当前配置猜任务模式，归档继续显示真实全量/差异身份。
- 复验：Dz版真实Diff9961任务标题为扫描分析·扫描已发布，未再显示完整扫描。
- 状态：已修复并通过；此问题与I06虽同组件，但用户误解和原操作证据不同。
- 证据：[错误标题与Git阶段](../../output/playwright/ui-practical-20261114/21-diff-task-label-before.jpg)、[快照](../../output/playwright/ui-practical-20261114/21-diff-task-label-before.txt)。

新版证据：[25-diff-task-terminal-fixed](../../output/playwright/ui-practical-20261114/25-diff-task-terminal-fixed.jpg)、[页面快照](../../output/playwright/ui-practical-20261114/25-diff-task-terminal-fixed.txt)。

## I09：同名同位置头文件static对象缺少TU辨别

- 页面/数据：stress结果中5个header_state均显示shared.h:9；底层规范身份不同。
- 原实际：列表只显示相同名称/文件/行，用户需逐个打开完整身份才能区分，确认区同样容易失去编译单元上下文。已有人工记录绑定没有因此串写。
- 根因与修复：[App.vue](../../studio/src/App.vue)列表摘要缺少规范身份中的TU信息。已在列表、详情及当前人工确认对象补可读编译单元提示，[workbench.css](../../studio/src/workbench.css)处理显示；规范身份与存储逻辑不变。
- 复验：index-Dz_fcmH4.js的1366视口中5个TU可区分；one.c签风险后下一项正确到two.c，two.c签安全后当前待办筛选归0且前后按钮禁用，总待办142。
- 状态：已修复并通过。
- 证据：[原同名列表](../../output/playwright/ui-practical-20261114/22-scope-binding-after-sort.jpg)、[原快照](../../output/playwright/ui-practical-20261114/22-scope-binding-after-sort.txt)、[新版列表与签署对象](../../output/playwright/ui-practical-20261114/23-header-tu-disambiguation-fixed.jpg)、[5个TU实例](../../output/playwright/ui-practical-20261114/24-five-tu-instances-fixed.jpg)。

## I10：长YAML提交失败后错误信息位于视口外

- 页面/前置：工程配置第4步展开长完整YAML，编辑末尾并保持main滚动在下方。
- 操作：将review.command误填为scalar，点击检查配置与工具路径。
- 原实际：schema正确拒绝，保存也正确禁用，但全局错误在main顶部，当前1366×768视口看不到原因，用户只能看到无法保存。预期提交失败立即出现可读反馈。
- 根因与修复：[App.vue](../../studio/src/App.vue)用户提交失败后未将错误区带入视口；现在等渲染后滚动并聚焦全局alert。后台读取不抢焦点，弹窗仍使用自身错误区；未放宽命令数组校验。
- 复验：index-Dz_fcmH4.js从浏览器script实际核对，沿同一长YAML错误路径操作，完整红色错误进入当前视口，保存仍禁用。随后UI恢复原完整YAML，实际profile与备份字节一致。
- 状态：已修复并通过。
- 证据：[详细AI与I10记录](ai-failure-review.md)、[原不可见错误视口](../../output/playwright/ui-practical-20261114/package-48-missing-command-check-result.png)、[新可见错误视口](../../output/playwright/ui-practical-20261114/package-90-i10-visible-error.png)、[配置恢复审计](../../output/ui-practical-20261114/ai-profile-restoration.json)。

## I11：任务中心同路径配置没有显示用户名称

- 页面/前置：同一demo-b工程根已有多个配置，新增故障恢复配置8972e03b…。
- 操作：在任务中心选择要执行的配置并调整资源预算。
- 原实际：候选仅显示相同工程根和profile ID前8位，无法依据已保存配置名称辨别构建方案；选择错误方案会启动错误目标。预期显示可读名称并保留路径/ID用于核对。
- 根因和修复：[TaskCenter.vue](../../studio/src/TaskCenter.vue)原模板漏掉API已有name；下拉和折叠摘要增加配置名，保留路径/短ID，无名项明确显示未命名配置。选择绑定与任务校验不变。
- 复验：实际加载index-Covwq14P.js后，名称/路径/ID均清楚；选择失败恢复demo-b再切到demo-a，摘要与真实任务绑定正确。
- 状态：已修复并通过。
- 证据：[配置与预算原画面](../../output/playwright/ui-practical-20261114/27-budget-invalid-and-opaque-profile.jpg)、[快照](../../output/playwright/ui-practical-20261114/27-budget-invalid-and-opaque-profile.txt)。同画面1GiB预算正确被拒绝属于正常校验，不列缺陷。新版证据：[30号画面](../../output/playwright/ui-practical-20261114/30-profile-names-fixed.jpg)、[快照](../../output/playwright/ui-practical-20261114/30-profile-names-fixed.txt)、[构建同步SHA收据](../../output/ui-practical-20261114/i11-build-sync.json)。

## I12：冲突解决沿用普通确认文案且空依据仍可提交

- 页面/条件：相同原扫描在backup-ui和主根通过实际UI各自产生人工分支，增量导入后出现真实并行冲突。
- 实际操作：检查风险/暂无法确认动作；依据为空时按钮仍可点，随后后端正确拒绝。
- 原实际与预期：普通“确认”文字未说明此次会合并全部分支heads；在可事先判断的必填条件不满足时，按钮看似可执行。预期冲突态明确说明合并冲突，以及空依据时明确禁用；不能通过放宽后端校验修复。
- 修复：App.vue仅在冲突态明确合并冲突动作，并在必填依据为空时禁用；后端保持原校验与分支存储逻辑。实际加载index-CdM0AXW-.js，空依据三动作禁用，填入后真实合并；刷新重选后3条原始/合并历史仍可读。
- 状态：已修复并通过。最终两独立分支和一个解决事件均同canonical/fingerprint，解决parents精确包含双方；原dc5的6事件payload完整保留，新增3事件后共9。重复同delta新增0、不复活冲突。
- 证据：[完整冲突实操](conflict-review.md)、[旧空依据拒绝](../../output/playwright/ui-practical-20261114/package-205-conflict-empty-rejected.png)、[新版空依据禁用](../../output/playwright/ui-practical-20261114/package-209-conflict-new-form-empty.png)、[刷新后历史](../../output/playwright/ui-practical-20261114/package-219-conflict-resolved-persistent-history.png)、[最终父链与保留检查](../../output/ui-practical-20261114/audit-post-conflict-checks-20261114.json)。两分支来自同设备独立完整备份，不声称两台机器实测。

## I13：主动取消上传却提示断网重选

- 页面/条件：通过受支持CDP将真实localhost上传限速20KB/s；没有修改DOM、前端状态或响应。
- 操作：实际上传进度29.6%时点击取消上传，真实POST/cancel发出，原上传请求net::ERR_ABORTED。
- 原实际与预期：最终持久任务cbfa9550…为CANCELLED，但error/页面提示“上传连接已断开，请重新选择…”，没有准确表达用户主动取消。预期主动取消与意外断网分别解释。
- 数据：未发布不完整归档，临时目录删除，16库SHA全同。原结果状态以收据为准；早期FAILED推断未用作本项实操事实。
- 根因与修复：旧server将所有ClientDisconnect包装为OperationCancelled，主动取消和真实意外断网语义混淆。后端修复以专用UploadDisconnected表示连接断开，再在事务中读取取消意图；主动取消准确CANCELLED，未请求取消的断网应FAILED；一般写入/校验异常不得被吞，保留服务退出原因与终态幂等。UC02已实际尝试但未形成socket断流，该附加边界保留验证限制。
- 修复位置：[import_jobs.py](../../ecra/studio/import_jobs.py)、[server.py](../../ecra/studio/server.py)。两文件源码与runtime的SHA已一致，正式launcher同54917重启加载，相关后端组合41/41通过。
- 复验：正式新进程中同包约40.7%点击取消，0476…为CANCELLED/UPLOAD，无result；页面准确“已取消导入上传；已有扫描与人工记录保留”。最终16库与17事件payload全同，原任务保留、上传临时文件0。
- 状态：已修复并通过原主动取消路径。附加非主动断流没有形成：CDP离线和正常关闭浏览器的两个任务均正常重复合并0；其异常分支仅自动回归支持，未写成真实UI失败/恢复通过。
- 证据：[原上传取消收据](../../output/ui-practical-20261114/upload-cancel-first-result.json)，[同步收据](../../output/ui-practical-20261114/i13-runtime-sync.json)、[正式重启收据](../../output/ui-practical-20261114/i13-server-restart.json)；[完整实操](upload-cancel-review.md)、[原错误](../../output/playwright/ui-practical-20261114/package-228-upload-network-restored.png)、[新版取消](../../output/playwright/ui-practical-20261114/package-235-upload-retest-network-restored.png)、[最终审计](../../output/ui-practical-20261114/audit-post-upload-checks-20261114.json)。

## F01：隔离数据库写锁（预期故障已恢复）

仅锁本轮测试reviews.db。保存时明确database is locked，未假报成功，原人工事件不变且草稿保留；释放后同草稿重试成功，g_counter新增风险事件并保留旧1486字符需补证记录，刷新可读，待办5→4。该项是正常错误处理通过，不列产品缺陷。

证据：[失败与草稿](../../output/playwright/ui-practical-20261114/09-save-failed-draft-kept.jpg)、[成功重试审计](../../output/ui-practical-20261114/audit-after-save-retry.json)。

## B01：初始Windows窗口识别受阻（历史工具阻断）

最初Windows Computer Use可枚举应用，但选择独立Chrome窗口时无法可靠识别当前URL，停止该轮操作；当时没有据此宣称看过页面。随后主代理成功建立可用IAB会话，真实操作与截图继续；附属代理用独立持久配置和项目已有Playwright，不操作主浏览器。此历史阻断不再覆盖已完成项，也不是产品缺陷。

## B02：外部VS Code协议被Browser安全策略拒绝

主代理实际点击one.c:8的vscode://file链接，Browser安全策略拒绝打开外部编辑器。已停止该跳转，没有换浏览器、工具或直接运行编辑器绕过；已通知其它代理不再尝试同跳转。该功能标“受阻未验证”，不是已确认产品缺陷，也不能计通过。其它站内页面操作仍可继续。

## B03：缺有效独立多核链接输入

现有本轮工程是普通对象库；历史F030_A/B等同固件别名不能作为真实双核证明。已实际添加/移除第3输入，两个输入选择同一6919扫描时明确拒绝重复事实根；通过文件选择器上传ASCII负向not-an-elf.elf后，页面要求真实ARM小端ELF32，下一步保持禁用。真实各核独立链接ELF与共享RAM绑定缺失，合法上传和后续合并受阻未验证，不列不适用或产品缺陷。

证据：[多核输入](../../output/playwright/ui-practical-20261114/32-invalid-elf-and-multicore-prerequisites.jpg)、[完整ELF错误](../../output/playwright/ui-practical-20261114/33-invalid-elf-visible-error.jpg)。

## B04：真实模型成功调用范围待澄清

主代理已询问本轮产品AI复核是否在允许调用范围，尚待用户答复。机器存在npm/opencode.ps1；本轮缺工具失败是人为指定不存在命令的负向测试，不能写成机器未安装。当前AGENTS禁止外部编码代理委托，其与产品AI复核是不同用途；本记录不擅自扩大或缩小授权。实际模型成功、有效输出与成功恢复尚未验证，失败6项及失败重试不替代成功验收。

## B05：永久释放的操作时确认尚未完成

隔离完成时真实出现“永久释放”复选框及禁用按钮。来源是Computer Use工具确认规则原文：“Permanently delete data: Confirm before any deletion the user cannot reverse through the product’s normal recovery flow.” 它不是仓库AGENTS或新增实现约定。执行后产品不再提供原路径恢复，本轮未完成该不可恢复动作的操作时确认，因此未执行永久清空。用户已经授权的独立可恢复清理正常完成：18项暂存后全部恢复原路径与原SHA。永久释放单列受阻未验证，不能把暂存/恢复视为删除通过，也不误称用户未授权所有清理。

证据：[动态入口](../../output/playwright/ui-practical-20261114/package-162-cleanup-quarantined.png)、[维护MA08](maintenance-review.md)。

## B06：早期上传窗口不足（历史限制，已解除）

早期本地小包迅速进入后台，上传阶段取消未能操作。随后采用受支持CDP限速20KB/s获得真实29.6%进度并点击取消，原限制已解除，因此不再把该功能计受阻；实际发现I13后端取消原因问题，转入修复与复验。后台导入/导出取消不替代上传取消。

## T01：测试根放在Git树内（准备错误已修正）

初始output/ui-practical-20261114/data位于工具Git树内，Studio正确拒绝。随后数据根、偏好调整到H:/ECRA-ui-practical-20261114，固件也放独立目录和Git基线；没有关闭边界校验。正式ECRA.cmd启动及后续真实扫描在新根完成，旧准备副本保留。

证据：[边界核验](../../output/ui-practical-20261114/external-isolation.json)、[启动收据](../../output/ui-practical-20261114/startup-readonly.json)、[恢复扫描](../../output/ui-practical-20261114/recovery-data-evidence.json)。

## 回归状态

新增studio/tests/filter-updates.test.mjs和evidence-interaction.test.mjs，覆盖筛选调度、缺口说明、证据阅读与相邻项状态。已执行的针对性回归及中间失败/修正见[回归详情](regression-details.md)。阶段记录包含29项通过；主代理最后执行全部Studio测试32项通过，npm构建/类型检查及diff检查通过。其后I11再次构建/类型检查通过，I11资源为index-Covwq14P.js、index-Dw60A1lg.css；限定diff检查通过。I11及其后I12构建的index-CdM0AXW-.js状态下，主代理再次运行全部studio/tests/*.test.mjs，32/32通过；完整日志为[studio-tests-final.log](../../output/ui-practical-20261114/studio-tests-final.log)，全区diff检查通过，仅常规CRLF提示。自动回归不代替真实页面复验。
