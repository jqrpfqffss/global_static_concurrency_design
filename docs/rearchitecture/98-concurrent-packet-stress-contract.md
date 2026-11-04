# 多Worker完整Packet内存压力验收合同

> 实际限定验收已完成（2026-11-05）：[INAV双副本收据](acceptance/native-review-packet-concurrent-inav-v57.json)PASS_SCOPED，831.484秒，4GiB真实Job内核累计提交峰值2,813,624,320B，RSS采样最大2,788,945,920B。两个独立对象确实到达屏障后才分别写出完整文件/重验收据；不是串行执行。每份Packet为615,590,601字节，完整SHA、缓存键及628,662,175B文件SHA均与97号对照完全相同。两份共1,257,324,350B文件不代表全流程磁盘峰值或G4收益。原12.59GB库完整SHA前后不变，冻结3778文件SHA不变，清单SHA256 `fa7a4ee0da2459356f1fa35a14c6d5d5d02e2230536362c4193c1eedb6e5b49f`。没有联网模型或新原生扫描。

F030同一观察器[双副本试跑](acceptance/native-review-packet-concurrent-f030-v57.json)也通过。首次v56小试未取结束后Job累计峰值，初始采样小值不作为内存结论，[原收据](acceptance/native-review-packet-concurrent-f030-v56-incomplete-peaks.json)保留；v57补结束后的内核读取。RSS仍可能漏掉亚秒瞬时尖峰，不能称精确瞬时峰值。已有完整代码回归[冻结v54](acceptance/full-regression-studio-v54-final.json)1508项：1506PASS/2联网SKIP，2714.123秒；3760引擎及独立测试副本文件SHA不变。其不包含后续任务诊断或100号停止修复，不替代当前整树全套。

97号只证明单Packet。下一步在同一Windows Job中并行构造两个真实INAV最大候选的完整Packet，并用屏障确保两个对象同时驻留；各自写文件、重验收据投影和完整缓存键，原库前后完整SHA不变。不能以顺序执行冒充并行峰值，不能去重共享两个Python对象，不能截断证据。预设4GiB Job、主机至少8GiB提交/物理余量，沿用仅终止自有Job的安全停止。

这是**相同真实最坏候选的两份独立并发压力操作**，不是两个不同候选、完整候选队列、联网模型或整套saved_run。即使通过，八Worker、实际大工程恢复、物理32GB和G1–G8仍待验。Job峰值在进程结束后追加读取内核累计峰值；RSS只是采样最大，不能称无漏采瞬时峰值。控制器及完整原Packet对照沿用97号，结果产生前不标PASS。首次F030并发小试逻辑通过，但旧观察器未取末次Job峰值，不用其初始小值宣称内存收益，保留原收据。

复现：`py -3.10 -B -X utf8 scripts/validate_native_packet_reader.py --source <封存INAV scan目录> --work <全新独立目录> --mode selected --job-gib 4 --copies 2 --write-packet --verify-packet`。不同副本在不同目录各自保存完整Packet/收据；主动停止只关闭此观察器自有Job。共享64GB主机且并行回归/打包，耗时不作性能提速对照。
