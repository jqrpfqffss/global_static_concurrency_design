# Q207/208：只读Git与监控准入独立审查

初始候选为 `H:/ECRA-quality-20261108/continuation-diff/q207-candidate-source`，core `fc958d23d50c436f2fd7529000a9f46b887506ad82e62fe4db50e956ee17d2b9`。已逐SHA核对冻结三生产文件；本审查不修改候选、主区、原包、真实工程，也没有重跑大型扫描。完整初审收据 `output/quality-20261108/continuation/q207-independent/fc-initial-readonly-review.json`。

## 已验证的范围

Git官方说明autoRefreshIndex默认会为stat-only差异刷新索引，命令级关闭有独立依据。[Git配置说明](https://git-scm.com/docs/git-config#Documentation/git-config.txt-diffautoRefreshIndex) 新代码没有设置忽略真实源变化的index标志；三个名字查询增加--exit-code，只接受0/1并拒绝stderr，不将技术错误包装为空差异。[Git diff返回码说明](https://git-scm.com/docs/git-diff#Documentation/git-diff.txt---exit-code) 当时独立样例能区分stat-only与内容变化，但这不是该选项在所有Git环境下都能正确列名的证明，见下方后续主回归失败。原binary patch捕获没有改成异常返回1合同，仍完整保存原暂存/工作内容。

另建独立Git根，用实际MinGit构造暂存修改、未暂存修改、删除、R100带空格重命名、未跟踪新文件，以及字节不变仅mtime变化的stable.c。候选正确识别四类真实tracked变化，明确working策略的pin仍纳入未跟踪文件，未误列stable.c；原始index字节SHA不变。没有改真实工程的include_uncommitted策略。证据 `git-mixed-content-review.json`。

源码准入第一遍严格权限读取位于固定输入之前；安装原sticky watch后仍重新检查严格权限并立即check，未忽略.git、未修改mask或放宽原安全等级。双构建/缓冲区/原HEAD/index/全部字节复核保持。Explicit CDB经共享working_snapshot Git入口，不运行原CMake；多核当前由已归档配置/静态库/ELF派生组合，不存在另一个绕过该检查的实时原源码构建入口。这里是代码路径审查，不宣称新增多核硬件支持。

## 发现的既有监控对象身份窗口

原InputWatch.directory先注册通知，再锁定路径祖先。该函数在v4和fc完全相同，问题不是Q207三文件新引入。

在独立目录，控制实际API允许的一个时序：真实FindFirstChangeNotificationW已返回handle后、既有CreateFile祖先锁开始前，真实执行原source→backup、replacement→source。目录替换成功，后续第二次严格权限检查通过，但watch实际仍绑定旧目录；新source内真实写入再恢复字节/mtime后，check仍没有信号，mask仍为287。未伪造API返回、通知结果、数据库或扫描状态。

这证明“锁定路径与监控对象相同”的前提存在窗口；尚未以完整扫描证明错误SAFE，不能扩大为所有既有结果失效。原63a5正常full路径不调用此dirty CMake监控，继续保留其真实版本验证。反例为 `watch-registration-identity.json`，脚本 `output/quality-20261108/continuation/final-projects/q207_watch_identity_review.py`。所有移动路径事先核对位于全新独立根，原源未动。

已交实现者在新的v2副本做最小身份/顺序修复，保留原mask、ACL二检和资源释放。当前fc初审不能标为完整通过；等待v2冻结后独立重放同一反例，并检查原source/ACL/HEAD/index变更仍被拒绝及异常句柄清理，不扩展为新平台。

## 最终v2独立复核

已对冻结 `H:/ECRA-quality-20261108/continuation-diff/q207-v2-candidate-source` 完成只读复核，core为 `65c0fb3dbc29bda7ad74aeeadeb4666c6b1eeda545bc9521c3961f476eca7682`。四个生产文件SHA逐一匹配冻结收据：working_cmake `c22020a3…`、working_snapshot `21cd2051…`、git_diff `004cbf3d…`、guarded_cmake `ee88ca0a…`，完整值见 `final-v2-four-file-review.json`；前三个与fc完全相同，原严格ACL谓词及BuildExecutor尾部逐字节保留。

新InputWatch从稳定祖先到目标先取得NoDelete、OPEN_REPARSE句柄，并核对卷/文件ID，注册原mask通知前后再次核对路径与句柄身份。失败或停止只回滚本次新增资源，保留既有监控共享的祖先；临时身份句柄由finally关闭，没有清除已发生的通知、忽略.git或重设弱mask。

在新的独立根按原相同时序重放真实反例：现在目录替换被Windows真实WinError32阻止；之后对原目录的文件真实写入再恢复字节/mtime仍被mask287检测。with退出后全部句柄表清空，源目录真实rename成功，证明没有遗留NoDelete资源。没有伪造内核结果或产品状态。记录 `final-v2-bind-identity.json/log`。

另独立重跑七个身份/回滚方法及十二个权限/Git方法，19项18.003秒通过、0skip，涵盖source/ACL ABA、HEAD/index变化、首检到watch之间降低权限、stat-only与真实改动区分及原索引保持。这与实现者71项有重叠，不累加成额外覆盖总数，也未重跑大型工程。

初始对象身份阻碍已解除，最终结论为**PASSED_SCOPED_INDEPENDENT_READONLY_REVIEW**，总收据 `output/quality-20261108/continuation/q207-independent/final-v2-independent-review-receipt.json`。完整受影响dirty CMake/ASM/系统头链路、跨引擎恢复拒绝和最终包/UI仍由根在统一最终字节上验收；原63a5正常full运行不改tag/checkpoint，不虚称已使用65c0。

## 后续统一回归否决与证据边界

主线程在同一65c0核心的V6 smoke中实际得到两个stat-only失败：`stable.c`被错误纳入changes，以及无内容变化的隔离副本被`check_isolated_tree`拒绝。原失败已保存，正在跨Git/环境定位；该事实否决“最终工作区链路通过”，不能用上述独立19项通过覆盖。V7最终封包队列已在读取源/缓存前停止，V6当前正常封包只保留nominal便携门禁范围。

19项原始unittest日志与四生产文件SHA均保留，但当次完整启动argv、PATH及Git配置环境没有落盘。工作记录为host Python3.10.11 `-B`与V4包MinGit，不能事后从另一混合内容脚本的`GIT_CONFIG_NOSYSTEM/GLOBAL`设置推定该19项的环境，也不能把新重跑冒充原始凭据。此限制已明确交给独立根因检查者。
