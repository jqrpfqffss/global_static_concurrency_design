# ADR-015：受监督任务的深TEMP不能充当短构建别名根

实际v16包的新预检查浏览器用例前7项通过，第8项CMake修复后仍失败：CMake TryCompile无法进入约300字符的工作路径。原build_path把Junction放在任务自己的TEMP下；资源隔离已把TEMP移到深层work/tasks/<id>/temporary，别名因此没有缩短路径。原失败日志和包保留，不能把CMake夹具改成短路径后冒称修好产品。

保持实际源码、目标、编译器和全部编译参数。现有TEMP下别名在ASCII且最终根长≤120字符时仍使用；过长/非ASCII时使用经过原studio_data_root/no_links验证的独立 `%LOCALAPPDATA%/ECRAStudio/path-aliases`。这里只保存指向同一实际目录的确定性Junction；真实构建、对象、缓存和TEMP仍在受控数据根。支持显式ECRA_PATH_ALIAS_ROOT，但必须绝对、独立、ASCII/8.3可表达且足够短；与目标/程序/可识别源码重叠、链接根、冲突旧目录均拒绝，绝不删除或接管。

保留原hash目录命名、same-target校验及碰撞拒绝，原有别名不被清理。将选择变量加入runtime_environment输入合同，实际编译数据库与快照仍绑定实际路径/字节，不削弱工具链/头文件门禁。本项是路径表达修复，不是写保护沙箱；生产H2/G3等未完成项不变。

须验证真实Windows Junction、深TEMP、同文件字节/mtime、冲突/越界保护，并在同样深的数据根运行实际Portable CMake构建与完整预检查浏览器流程；不能只验证字符串变短。新包必须从新冻结源重建，v16失败收据保持原状态。
