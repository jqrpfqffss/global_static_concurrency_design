# 外置CMake的ELF/MAP路径绑定

整轮INAV真实准备暴露了现有路径缺口：实际388TU构建完成，ELF/MAP在受控外置构建目录，但配置中的`build/ecra-i/bin/MATEKH743.elf(.map)`仍被输入快照当作源码根下的文件读取，因MISSING明确失败。原`whole-native-inav-v78-inputs/acceptance.json`、预检查及source_changes均保留；不能删掉这两个输入来跑通测量。

本阶段只为明确的逻辑构建前缀建立一一对应：配置必须选择外置CMake，两个声明均是配置`cmake.build_dir`内的相对路径，原声明位置均不存在，实际本轮构建步骤成功，目标目录有匹配当前源码根的ECRA归属标记，两个对应产物均在该真实构建目录存在。才将实际路径、完整SHA/大小和原声明写入`build_closure_binding`，并保留为`coverage.build_closure`及InputSnapshot真实输入。没有改原YAML、变量判定、链接符号判断、编译参数、ELF/MAP内容或比较规则。

已有原始显式文件、绝对路径、非该构建前缀、源码内构建、未执行成功构建均保持原解释；不会根据文件名去猜测另一个ELF。缺少归属、越界或缺少任一产物必须失败。原配置与新路径之间的关系是受控构建元数据，不能宣称原本缺失的源码路径是已消费文件。

修改为`ecra/managed_build_closure.py`、`compilation.py`、`cli.py`、`studio/preflight.py`。普通编译数据库及已有绝对闭包不新增绑定字段；原分析器不变。独立无缓存全量使用同一实际链接产物；原生输入快照、最终复验和损坏门禁不省略。未提交CMake的显式ELF/MAP仍未准入，本段先关闭固定提交CMake整轮Diff的缺口，不据此放宽117号V3策略。

首次工作区5项实际回归PASS，31.562秒，包括真实ARM链接、两Git版本分别使用独立ELF/MAP、原件与索引不变及独立无缓存全量PASSED。增加同例真实预检查后，冻结v78的14项针对回归PASS/0跳过、61.661秒，原冻结源及独立副本4037文件SHA不变；[收据](acceptance/managed-build-closure-v78-focused.json)、[原日志](acceptance/managed-build-closure-v78-focused.log)。manifest SHA为`113465220a07a2ffcb354f07d761d9fecab2beab68b25fe345ec48126e7351cd`。其它四项覆盖原显式路径保留、归属缺失、缺少单侧产物、前缀/越界/未构建门禁；另9项保留原别名、命令审计、停止和未准入模式门禁。完整1568项回归、原F030全部字段对照及最新大库在新冻结修改集上重跑，收齐前NOT_VERIFIED。

原v76/v77完整回归、包内测试及真实Chrome继续按各自版本收据记账，不能替这份新增修改背书。原F030已在冻结v78实际重新原生扫描，保持原2 PARSED/2 PARTIAL及code=2，43个原文件内容/大小/mtime不变；原完整有序、类型敏感比较器对全部facts/report均0差，[收据](acceptance/managed-build-closure-f030-v78.json)、[完整执行信封](acceptance/managed-build-closure-f030-v78-envelope.jsonl)。它不能替代大型INAV。原INAV黄金使用显式绝对ELF/MAP，预期绑定不触发；仍须实际最新全部字段对照验证，不能只靠代码推理宣称0差。
