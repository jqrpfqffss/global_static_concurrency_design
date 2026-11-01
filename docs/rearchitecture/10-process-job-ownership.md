# Windows Job启动所有权修正（实施前合同）

冻结4e6完整回归使用venv解释器时，既有故障注入器将限制施加到`Popen.pid`。Windows venv的python.exe是转接启动器，真实解释器已成为另一个PID；ready.json里的os.getpid才是执行器身份。故障注入器未核对这两者，有可能限制了转接器，却让真实分配器跑到整机提交耗尽。2026-11-01 06:52:33Z资源事件2004记载新启动的Python PID17076提交61,144,150,016B；其创建时间为06:52:25Z，不能误认作早已启动的备份进程。备份、新版原生扫描观察器和原版图编码同时失败；具体关联须保留事件和故障测试收据，不能把观察器失败当成16GiB扫描预算不足。

正式TaskManager也使用先Popen、再assign、再文件gate。文件gate只阻止引擎代码，不能阻止venv转接器在Job分配前创建真实解释器；必须修正启动顺序。复用已实测的write_guard中STARTUPINFOEX句柄白名单与挂起进程原语，新增普通完整性OwnedProcess：CREATE_SUSPENDED → Job assign → ResumeThread → 引擎gate。此处不启用Low令牌，也不声称H2写保护或dirty隔离已完成。失败只终止本次尚未运行的进程，关闭进程/线程句柄，不能回退到无Job执行。

诊断OOM测试先以外层512MiB Job覆盖转接器和全部后代，再对ready.json声明并验证的真实PID施加128/192MiB限制。故意耗尽前必须确认limit.json身份匹配及实际Job限制；丢失/不匹配直接拒绝。任何超时也只回收该Job，不可留下失控分配器。原来真正触发MemoryError与旧报告失效的断言保持，不能改成跳过。

验收必须包含真实Windows venv启动器及后代、挂起时无子程序副作用、Job登记的真实PID、受控分配失败与峰值、任务原生扫描/停止/重扫、关闭与创建失败无遗留进程。PE依赖测试应以真实基础Python解释器作DLL缺失夹具，不能误把venv转接器当作链接python310.dll的解释器。已有全套失败保留，修复后另冻结复跑，不修改旧冻结目录或抹去失败记录。

实测修正：第一轮49项中48项通过；新测试将原始PeakJobMemoryUsed也断言≤128MiB，实际读到134,377,472B，超过设限159,744B，因此失败。没有删除这个失败记录或抬高配置预算。改为在分配器捕获MemoryError后保留全部载荷、只释放预留的1MiB日志空间、让全部Worker等待，实读Job配置/flags与全部PID的PrivateUsage之和，再放行退出；原始Job历史峰值继续原样保留，不伪报为实际提交峰值达标。[微软字段定义](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)没有给出失败申请计账时的峰值不变量；[官方支持问答](https://learn.microsoft.com/en-us/answers/questions/6054259/windows-job-object-can-a-rejected-memory-commit-in)同样指出不能把失败申请与成功提交等同，具体内核计账次序未经证明。本项目不会用该解释抹平G3大型扫描原始峰值；这里只修正进程所有权/受控OOM测试的测量对象，系统32GB门禁仍待验。
