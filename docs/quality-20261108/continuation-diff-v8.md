# 最终V8便携包ARM已知答案验收

最终实际ZIP为`H:/ECRA-quality-20261108-offline-build-v8/ECRA-Portable.zip`，785692766字节，SHA `b4590047afd32bfe3beb803b7a934ae52c893daf3d12a4fbe2c2ff456880ab1a`。从该ZIP新解压的实际目录`H:/ECRA-quality-20261108-offline-build-v8/解压 终验/ECRA-Portable`执行，core `2b9e8750136a6a0bbd48c41ae40d2b3399fe88c8031f628a2713269cea7cbdea`。根协调者的`continuation/extracted-v8-receipt.json`先核对ZIP、全32691清单及154生产SHA；本项运行后再次核对154个生产文件全部等于冻结清单。

本项是2个真实编译单元的已知答案样例，用于最终Git命名逻辑、中文空格路径、包启动及ARM/CMake集成验收。它不计作第四个真实公共固件工程，不替代[原V4固定提交cold/warm](continuation-diff-v4.md)或[原V6真实39TU CDC dirty](continuation-diff-v6.md)，旧结果及检查点均保留原引擎版本。

## 真实入口和冻结输入

- PowerShell7外层QA仅将PATH限制为`C:/Windows/System32;C:/Windows`，清除PYTHONHOME/PYTHONPATH，局部设置`PYTHONHASHSEED=0`；由本次解压包的`runtime/python.exe -X utf8 -B`执行外层helper，正式扫描通过包目录内`ECRA.cmd run --config <实际配置> --scan-mode full|diff --no-review`启动。
- Git2.56.0.windows.3、CMake、Ninja、ARM GCC10.3.1及Git内部exec-path均实际来自该包，物理路径和可执行SHA记录在`receipt.json`；没有依赖开发机Git/CMake/GCC/Python。临时ASCII别名仅由产品路径适配层生成并解析回同一物理目录。
- 全新工程位于`H:/ECRA-quality-20261108/continuation-packaged-diff-v8/工作 根/中文 空格 Git 工程`，全新数据在相邻`实际 数据根`，与工具目录分离。样例文件包括真实CMakeLists、toolchain、链接脚本、头文件及两个C源，真实Git提交固定作者、时间、文件字节和引用。
- 基准提交`43c005eae2705ff79b9b9873016d44ef7f45293d`；当前提交`54f5da318c1c90424146918135d010391dbc22bb`。对比固定基准与实际HEAD，`include_uncommitted:false`策略保留，没有改用merge-base或手工CDB。
- QA helper只把原63a5期望digest改为精确2b9e，其余全部原断言不变；原helper、准备收据和新helper均保留。运行完成后source哈希、Git clean及HEAD断言通过。没有改真实用户工程或确认数据。

## 已通过结果

独立已知答案：基准前台`shared++`整个RMW在真实`cpsid i`/`cpsie i`窗口中，唯一并发普通IRQ无法在窗口内抢占；当前删除该屏蔽，普通IRQ与前台都可读改写同一共享量，存在旧值覆盖窗口。`volatile uint32_t`及单次字访问不能证明整个RMW无竞争。

| 实际轮次 | 用时 | 已知答案及实际结果 | 覆盖与原状态 |
|---|---|---|---|
| 基准full | 39.890s | SAFE_PROVEN / EFFECTIVE；实际反汇编有cpsid/cpsie | 2 PARSED、0 PARTIAL、0 FAILED；5对象；原退出2、STATIC_VALIDATED / INCOMPLETE |
| 当前Diff及产品独立full | 90.937s | SUSPECT / NOT_FOUND；真实移除cpsid/cpsie，`c:@shared`被选中 | 2 PARSED、0 PARTIAL、0 FAILED；独立full的5对象分类和语义mismatch各0；原退出2、STATIC_VALIDATED / INCOMPLETE |
| 当前独立full | 33.563s | SUSPECT / NOT_FOUND，与Diff一致 | 2 PARSED、0 PARTIAL、0 FAILED；所有5对象的完整风险证据仅移除Diff impact展示元数据后逐项相等；原退出2、STATIC_VALIDATED / INCOMPLETE |

每轮均实际CMake/Ninja配置并构建，真实CDB恰好2条，真实链接产出ARM机器类型40、可执行类型2的ELF及MAP；没有跳过链接、伪造或重映射数据库。各轮CDB、ELF、MAP与objdump原输出均保存到证据目录。所有权威native库SQLite quick_check为ok，manifest的`source_reverification:true`，发布后输入重新核验通过。当前存储风险对象4个，其中3个只读向量元素为SAFE、共享RMW为SUSPECT；另保留1个容器，未把待复核当安全。

未启用OpenCode，不宣称AI联网推理、人工复核或硬件执行已完成。原退出2/INCOMPLETE明确保留，不将STATIC_VALIDATED等同完整复核完成。本项没有产生新的可执行严重/重要缺陷。

## 证据位置与QA启动纠正

证据根为`output/quality-20261108/continuation/packaged-diff-v8/`：

- `receipt.json`：正式argv、实际包/工具路径、时长、返回码、Git pin、原断言及完整full_verification。
- `post-run-audit.json`：154生产SHA、3库SQLite和来源复核、全部5对象独立full证据比较。
- `base-full-*`、`current-diff-*`、`current-full-*`：真实构建产物、反汇编、报告与目标完整证据。

外层脚本位于`continuation/final-projects/packaged_diff_smoke_v8.py`，追加只读审计为`audit_packaged_diff_v8.py`。第一次错误使用Windows PowerShell5读取无BOM的外层QA launcher，尚未启动Python或创建验收根即参数解析失败；原日志保留为`packaged-diff-v8-winps-qa-launch-failed.log`。改用PowerShell7执行同字节launcher后原断言完整通过，记录于`packaged-diff-v8-launch.log`。这项QA编排错误未修改产品；产品正式PowerShell脚本的BOM及中文文档由根协调者另行核对。

三轮库分别为新数据根下`base-full-data/scans/a6c53e2fcdf3414da239902b0fa79080`、`diff-data/scans/46cba8a215be4b73ba2e77f0a86f96c8`、`current-full-data/scans/1f4a0fe20b484c8bb22d3a1552820e5f`，均保留。控制器和追加审计均退出0；本项没有残留服务、浏览器或测试进程。
