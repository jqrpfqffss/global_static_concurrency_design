# 上传取消补充实操与 I13

本补充沿用独立持久 Chrome / Playwright、Windows、1366×768、deviceScaleFactor=1，原隔离服务 `127.0.0.1:54917` 和测试根。前端仍是 `index-CdM0AXW-.js`。限速仅通过 Chrome 支持的 `Network.emulateNetworkConditions` 设置上传 20480 字节/秒；真实 localhost 请求照常发送，没有拦截、替换响应或注入页面状态。

|编号|入口与条件|实际操作与预期|实际结果|状态|证据|
|---|---|---|---|---|---|
|UC01 / P12|数据与共享→选择完整结果→上传中“取消上传”；原 sample-compact 442731 字节|20KiB/s 下选择文件，约29.6%点击取消；应说明用户主动取消、未发布且旧记录保留|原 job cbfa9550420f4ab0b9154e2d451055be 为 CANCELLED/UPLOAD，但提示“上传连接已断开，请重新选择…”；未发布，16库SHA全同，临时目录已删除|发现 I13|package-225～229；upload-cancel-first-result.json|
|UC01 复验|正常重启已同步的新后端，地址不变|再次同包限速上传，约40.7%点击取消并恢复网络|job 0476c1c6b9b741c2b504ca5bb953d0d3 为 CANCELLED/UPLOAD，收到163840/442731字节，无result；UI明确“已取消导入上传；已有扫描与人工记录保留。”|已修复并通过|package-230～235；235视口实际查看；i13-runtime-sync.json、i13-server-restart.json|
|UC02|无主动取消的连接意外中断|上传中通过CDP offline断网后恢复；再尝试上传中正常关闭自己的持久浏览器，重新打开|CDP离线使轮询短时失败，但此Chrome没有终止已打开的上传socket；恢复后207f1237b7f9473180bf43318f172caf正常完成。关闭浏览器时上传也完成，ea685e7c96ef4a7b979100d4ce3aaba1重开显示完成；两者均为重复合并、新增0|真实无cancel断流失败分支受阻未验证；不是产品失败|package-236～247；240、247显示实际完成；247视口实际查看|

I13 根因经实际任务记录修正：旧 `server.py` 将 `ClientDisconnect` 包装成 `OperationCancelled`；旧 `abort_upload` 未区分已登记的用户取消，因此主动取消显示断流原因。最初仅据源码推断会被记 FAILED 不准确，实测原任务是 CANCELLED，原收据完整保留。

修复涉及 `ecra/studio/import_jobs.py` 与 `ecra/studio/server.py`：使用明确的上传断开异常；在事务内读取持久取消请求，已取消与真实断流分别记录，避免晚到异常改写已有终态；保留服务停止和其它失败原因。`tests/test_import_jobs.py` 补相关回归，执行代理报告41项相关回归通过；自动回归不替代UC02真实UI失败覆盖。

主代理经原 `launch-isolated.ps1 -Port 54917 -NoBrowser` 重启，收据记录源码与runtime两文件SHA相同；会话令牌已正常更新。旧取消任务未删除或重写。网络参数在package-235、239恢复；关闭的浏览器会话销毁其CDP条件，重开后又在package-246明确设回默认无限速，最后正常关闭子浏览器。没有改动主浏览器网络设置。

原样例及证据位置：`H:/ECRA-ui-practical-20261114/downloads/sample-compact.ecra-report`；所有截图和每步DOM在 `output/playwright/ui-practical-20261114/package-225～247-*`。CDP参数、真实上传POST、cancel POST及 `net::ERR_ABORTED` 记录在 `package-operations.jsonl` 对应229、241、244的detail。

最终只读审计在主代理最后一次正常刷新和继续上次位置完成后执行：[audit-post-upload-20261114.json](../../output/ui-practical-20261114/audit-post-upload-20261114.json)、[核对收据](../../output/ui-practical-20261114/audit-post-upload-checks-20261114.json)。主根仍8归档/5工程，绑定及深审错误均0。复验前后16个扫描/人工数据库字节全部一致，17个人工事件payload全部一致，原5个导入任务payload完整保留；新增3个任务准确为1取消、2重复合并0，上传临时文件0。逐归档完整审计记录与冲突补充结束时全部相同；dc5仍9事件/待办3，stress仍8事件/待办142，6919仍待办6。备份根本阶段未启动或写入。
