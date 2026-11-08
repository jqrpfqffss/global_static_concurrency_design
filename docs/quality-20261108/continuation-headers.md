# Q306候选：中文路径的GCC标准头探测

本项只修改独立候选，主工作区原静态引擎`74c0…`及原Portable/ZIP保持冻结。候选位置为`H:/ECRA-quality-20261108/continuation-headers-candidate`，组合验证副本为相邻`continuation-headers-asm-candidate`。正式合并、完整回归和大型工程重扫由协调者统一执行；本记录不是候选已交付声明。

## 当前缺陷证据

已有真实C+ASM工作字节构建在GCC标准头阶段失败。独立重复捕获确认：

- 实际Windows `GetACP()`为936；开启`PYTHONUTF8=1`时，Python的preferred encoding却为UTF-8，不能拿它代表外部GCC输出编码。
- 同一真实包内Arm GCC10.3.1，用物理中文路径执行`-mcpu=cortex-m0 -mthumb -E -x c -v -`，退出0。stderr不能严格UTF-8解码，但可以严格cp936解码，能够恢复真实存在的完整标准头目录。
- `LC_ALL=C`和`LC_ALL=C.UTF-8`都不能把该Windows原生GCC路径输出变成UTF-8。
- 直接以ASCII别名启动会输出ASCII，但只读构建执行器会先验证并展开到同一物理工具路径。因此不能用别名绕过真实保护入口，也不能靠关闭`auto_system_includes`消除此缺陷。

原始bytes在`output/quality-20261108/continuation/headers/*stderr.bin`；`raw-probe-baseline.json`记录三种真实命令、解码结果、GetACP、Python UTF-8模式、工具路径身份及主基线原场景失败。失败原因不是编译器执行失败，而是父进程将ACP bytes按UTF-8替换成`�`后丢失路径。

## 必要修复范围

1. `compilation.py`仅对标准头探测请求原始输出，显式传`text=False, encoding=None, errors=None`。不改变`common.execute`的全局默认。
2. 搜索列表路径分别严格尝试UTF-8及Windows真实ACP，依据实际目录、规范化身份去重；同一行若对应两个不同的实际目录，明确报编码歧义。无法无损恢复任何一行、缺结束标记或空列表都失败，不能静默缩小标准头范围。
3. 技术失败保留阶段、编译器退出码及严格解码后的可读诊断；两种编码均无效时显示原始字节hex，不用替换字符制造路径。
4. `guarded_cmake.py`仅新增严格的三参数binary输出组合，其他额外选项仍拒绝。原GuardedProcess、只读ACL、输入watch、资源预算、argv准入与CMake trace策略不变；不另行启动绕过保护的进程。
5. 受控返回值可以是bytes，落盘execution JSON只保存binary协议标记、字节数与原始输出SHA。原始日志继续原样保存；标准头消费者提供可读解码。实际完整prepared JSON序列化及回读已验证，不把bytes直接塞进JSON。

候选实际只改变两个生产根模块，`common.py`逐SHA未变。精确清单见`candidate-manifest.json`：

| 文件 | 候选SHA256 |
|---|---|
| ecra/compilation.py | `2edb2d28f1a6dd52a2ae436810a6796356871b26c1be33375b5b3b5394dbf111` |
| ecra/guarded_cmake.py | `3e733e7f8e1d6e940967529737b2ae4e7b997b4136f280d2db14997196a2a0f8` |

新增回归为`tests/test_system_include_encodings.py`与`tests/test_system_include_guarded.py`，均在独立候选目录。组合验证另复制analysis代理已冻结的Q203 `working_cmake.py`，文件SHA为`90b3d4ed1e22851b5dbf3294df6155c89a62ea888765e494e3705dbd308d8260`；本项没有编辑该模块。

## 已完成验证

| 场景 | 实际结果 | 证据 |
|---|---|---|
| 严格ACP、UTF-8、实际目录歧义、坏路径不能部分丢弃、非Windows编码协议、失败可读性、严格binary选项、既有CMake范围及CLI标准头 | 29项全部通过，0跳过，28.119秒 | `header-source-tests.log` |
| 真实物理中文包路径GCC →标准头 →含stdint.h的uint32_t共享对象Clang解析 | PARSED，shared对象存在，目录实际存在 | 上述套件的真实Windows用例 |
| 实际只读CMake C+ASM、auto_system_includes=true、生成输入及stdint解析、原源不变、raw日志SHA与JSON保存 | 通过，3个C TU及1个ASM来源；readonly及namespace检查仍为true | `actual-guarded-header.json` |
| Q203同批实际ASM阳性、项目自定义进程负例及ASM准入边界 | 与上一行合计4项全部通过，0跳过，617.560秒 | `combined-guarded-tests.log` |

非Windows一项是编码协议回归，不声称已在Linux实机执行。本轮没有重跑便携整包、三个旧真实工程全扫或大型INAV，不能用上述小样例代替它们。

组合测试耗时主要出现在原CMake trace逐条路径边界核查。faulthandler显示`working_cmake.audit_trace → no_links/Path.resolve`；没有为缩短时间跳过trace、减少边界检查或改变准入条件。一次55秒限时定位进程被停止，其stack日志保留`combined-full-stack.log`；正式组合运行实际等待完成并通过。

测试控制器还发生过Windows当前目录清理及混用Portable环境的旧fake-cc夹具问题；处置和日志保留情况详见同目录`controller-incidents.md`。这些没有冒充产品缺陷或用于放宽预期。真实缺陷的原始stderr和主基线失败证据始终保留。

## 待统一完成

需要把本项两文件与Q203、SQLite长校验停止候选一次合并，冻结新的完整候选指纹，再进行相关完整回归、实际产品操作与大型工程重扫。原74c0扫描和原ZIP继续按其原范围保留，不能直接当作新候选的验收结果。
