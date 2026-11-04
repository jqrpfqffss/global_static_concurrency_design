# v37：多核三步操作的实际Portable验收

2026-11-04。软件严格绑定R1提交`7066dea6b31bb3d0913cccd3c9f606145012d57d`，3426冻结文件、清单SHA `824400305d0ab70ca46d4abb2454cb6da8a6a533adedf866e3f297dc18e0d0ab`。后续R2a/父读取代码属于其他提交，不能算进本包的新原生扫描或分发验收。

| 阶段 / 实现 | 文件 / 场景 | 实测结果 | 状态 / 证据 |
|---|---|---|---|
| Phase6统一回归 | 精确冻结源及独立测试副本 | 1423项、1421PASS/2联网opt-in SKIP，2058.096s；全部源/测试SHA0变化 | [完整回归](evidence/full-regression-studio-v37.json)，PASS_SCOPED |
| Phase2普通原生路径 | 原路径/原配置F0304TU，原e69完整参考 | 有序、有类型完整事实及既有规范化报告差异0/0；2PARSED/2PARTIAL，INCOMPLETE保留，原输入/引擎SHA不变 | [原生黄金对照](evidence/native-exact-f030-v37-v1.json)，PASS_SCOPED |
| Phase4/5实际用户操作 | 22普通Chrome组 + 1真实owned VHD组 | 23组183重叠断言全部PASS；含多核选择/真实ELF上传/受控8GiB任务/证据/人工/完整包8组、核心表单8、预检查16、历史14、证据归属4、文本容量11 | [完整封存](evidence/portable-studio-v37-seal.json)，PASS_SCOPED |
| Phase6分发及CLI | 目录与中文ZIP实际解压；内置Python3.10.9 | 31700文件完整SHA、130运行时与冻结源匹配；两个形态各27CLI：21exit0、6预期INCOMPLETE exit2 | 同封存及[文件校验](evidence/portable-v37-files-verification.json)，PASS_SCOPED |
| 多核原CLI兼容 | 实际包内Python执行旧已有组合入口 | 完整原e69事实/报告对照0；输入及原结果保持 | [包内CLI](evidence/portable-v37-multicore-cli-proof.json)，PASS_SCOPED，非真实双核G2 |
| 真实磁盘满 | 新256MiB VHD，核对所有权后挂载/断开 | kernel ENOSPC、4实际GUI完整性/恢复场景、中文动作、无运行时代码变化，最终完整断开 | [生命周期](evidence/portable-v37-real-disk-full-lifecycle.json)，PASS_SCOPED |

入口为 **`H:/ECRAStudio-build-20261104-studio-v37/ECRA-Portable/ECRA.cmd`**。软件ZIP为759319767B，SHA-256 **`96826c586243dc648c726ba5495a884434ba650efc1f4634e0e778312d65bb89`**。这是软件分发包，不能与大型扫描结果完整包3157389743B混比或用来衡量G4扫描保留目标。

首轮预检查在5项后发生控制器定位超时：保存旧版本配置会异步恢复历史检查，同一个按钮名称会正常从“检查真实构建”变为“重新检查真实构建”；原控制器瞬时`count()`后固定旧名称。现场显示历史检查且禁止直接启动，产品门禁正常。保留[首轮FAIL](evidence/portable-v37-preflight-initial-failure.json)与[现场截图](ui/screenshots/portable-v37-preflight-initial-failure.png)。

控制器改用跟随两个合法名称的同一定位器，完整16项在**同一未修改软件包**重新通过；没有减少断言、绕过历史检查或改产品门禁。[重跑](evidence/portable-v37-preflight-controller-retry-v2.json)记录新控制器SHA `336ab24e9224fee653806e777ba2409ae296e7aa78910b4745cacee82feb1765`；16项名称/顺序与原v36成功合同一致。其余22组保留首轮实际结果，[汇总](evidence/portable-v37-browser-reconciliation-v2.json)绑定原始失败汇总SHA及新重跑，原汇总不覆盖。封存使用这个明确可追踪的23组结果。

截图均为实际页面：[全部本包截图](ui/screenshots/portable-v37/)，尤其`multicore-workflow-*`、`profile-*`、`preflight-*`、`real-disk-full-*`。多核流程仍使用同一获准F030的两个独立原生扫描别名，不能算另一类真实双核工程；原组合算法和ELF匹配未改，完整选择固定/旧新对照见[70号](70-pinned-multicore-workflow-acceptance.md)。

可复现命令/argv已在各浏览器、CLI、原生和封存收据中记录；重跑必须使用新work/evidence/data副本。新的UI预检查验证器为`py -3.10 -B -X utf8 scripts/validate_build_preflight_ui.py --help`；多核为`py -3.10 -B -X utf8 scripts/validate_multicore_workflow_ui.py --help`。两者以`--engine`和`--python`显式选择被验包及其内置解释器，不把宿主Python冒充包内运行。

U01–U24最新完整逐条矩阵仍为[36号矩阵](ui/36-user-scenario-status-v36.md)的14PASS/10NOT_VERIFIED，各条原来源保留；本包新增/重验的子场景不自动关闭剩余10项。v36的完整大归档6组及原3000+新增1000/三次重启是真实独立旧证据，本包没有重复这些整项，不改标成v37新生产者。原始大型图导航6组在本包实际通过，但该旧图缺归档源码，不能当作本包完整原生大归档再验。

整体仍BLOCKED：R2c正式dirty/完整构建-Diff-恢复、R3全消费者/大型恢复、R4证明继承、R5全根迁移、完整故障矩阵及真实工程师UAT仍未完成。其他G2工程用户已延期，物理32GiB/第二PC/干净离线PC/原生DPI/真实联网模型继续NOT_VERIFIED。本机自动化GUI通过不等于真实用户满意度或目标板硬件复现，`all_gates_passed=false`。
