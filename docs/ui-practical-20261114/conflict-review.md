# 新增增量与并行冲突实操

此补充发生在早期completion审计之后，不覆盖那些时点收据。主隔离根为 `H:/ECRA-ui-practical-20261114/data`（54917），第二分支复用已真实备份并启动验证过的 `backup-ui`，通过正式 `ECRA.cmd --data-root ...` 再次独立启动（61158）。主浏览器独立持久profile为aux-browser（无头），副本用backup-verify-browser（可见窗口）；Windows Chrome 156、1366×768、device scale factor 1。两根均为测试数据，源固件及正式记录不涉及。

源对象为同一归档dc5e3796ca6a40c98a827a7125c52955的 `c:@g_msgSP`，main.c:4。两边指纹完全相同 `78dbed67df4741f763001f41a7f8aac83bc8e05415d0959d0943a034b1a0f657`。全部签署、导出、导入和解决动作来自UI，没有直接写DB。依据文本明确声明只用于隔离冲突验收，不作为工程安全结论。

|编号|入口/目的|前提与预期依据|实际操作/实际结果|问题与状态|证据|
|---|---|---|---|---|---|
|CF01|新增人工增量合并|同一归档/证据身份；不可变历史允许并行分支，不能覆盖另一方|副本查g_msgSP→签有风险；主根查同对象→签无风险。副本从数据共享导出delta并真实下载；主根UI选择delta，显示新增事件1|新增合并已通过；包不是重复零事件样例|backupverify-15～27、package-186～200；conflict-two-branches.json、audit-conflict-delta-package.json|
|CF02|并行冲突与历史|两个独立父集合为空的签署，必须保留双方而不能最后写入覆盖|继续人工确认→g_msgSP显示离线确认冲突、待办3回4；人工历史列双方不同结论/依据/UUID。空依据点原“确认有风险”被后端拒绝“解决冲突必须填写依据”，事件仍仅2条|数据校验通过；按钮体验发现I12|package-202～205；audit-conflict-unresolved-main.json|
|CF03|显式合并全部heads|必须核对双方且填写依据；不能丢失旧事件|更新前端后刷新、继续上次位置→展开；空依据三种合并按钮全禁用，填依据后启用；点“合并冲突并确认有风险”，待办4→3、历史保留双方加解决共3条|I12已修复并通过，1366当前视口标签完整无重叠|package-206～214；209/211/213/214截图已查看|
|CF04|重开与重复导入不复活冲突|解决应持久，重复旧分支delta应去重|刷新→变量与风险重选g_msgSP→人工历史仍3条；再次选择同delta显示新增0；DB唯一head仍是解决事件|已通过|package-215～222；219截图已查看；audit-post-conflict-checks-20261114.json|

I12根因在 `studio/src/App.vue` 人工控件模板：风险/待核实按钮只检查确认者，冲突态没有同步后端的必填依据规则，而且文案仍是普通签署，虽然提交会携带resolve=true。最小修复仅增加冲突态空依据禁用、三种“合并冲突并…”文案和冲突依据placeholder。普通签署规则及后端校验未改变。`npm run build`（vue-tsc+vite）通过，新构建同步到正式测试runtime；两浏览器实际DOM核对 `index-CdM0AXW-.js`，CSS仍 `Dw60A1lg`。主代理还完成32项现有测试。旧版203/205与新版209/211/213提供前后证据。解决后按钮自然恢复普通签署文案，风险按钮在普通态保留原有规则。

新事件链：主根无风险 `6a3f89e3-21de-499a-a733-97fa4ebf364d` 与副本有风险 `d1ad400e-d537-46ea-9523-3ebab9e92a74` 均revision1、parents=[]；解决事件 `53e4e05e-06b7-47f4-8e52-7949bab86a09` 为revision2，parents精确包含上述双方。三条都绑定同项目、归档、symbol与fingerprint。delta文件9362字节，SHA256 `27321a9069f0fea0922e78ba515d1af07988e2f4937c5992a522934a4e455b38`，7事件/包成员校验无问题。

最终主根审计 `audit-post-conflict-20261114.json`：8归档/5项目，0绑定问题、0深审计错误。dc5原6事件payload逐字节SHA全部保留，新增3，当前共9，风险3/原始安全1、人工待办3；其他7归档的规范绑定/静态/人工事件/prior/当前统计与冲突前完全一致，包括4198待办4、6919待办6（raw RECHECK3）、stress8事件/142待办。8个主根scan.db字节SHA都未变。

副本最终 `audit-post-conflict-backup-20261114.json`：原14事件均保留，授权新增1，合计15（dc5现在7）；5个scan.db字节SHA都未变。RS04“副本原14事件未变”是之前只读启动时点，不能理解为本次签署后副本完全没有变化。`conflict-before-event-hashes.json`和 `audit-post-conflict-checks-20261114.json`保存前后逐事件哈希比较、父heads和静态库比较。旧completion/备份启动收据保留原时点，不覆盖。

结束时两个独立浏览器均正常关闭；只关闭本补充启动的backup服务进程树，61158已不监听、剩余进程0，主54917仍监听。证据 `backup-conflict-closed-tree.json`、`backup-conflict-shutdown.json`。没有关闭主代理IAB或主服务。未执行永久释放；上传阶段取消、真实模型成功及多核真实合并等既有缺口维持专项记录的准确状态。
