# 单文件排除与配置一致性（v87）

起点 optimize_ccc@ed1be391e3c42b20a9147ff271fbec0178391c4f，工作区干净。

## 审计与实施前规格

- 原字段 analysis.exclude_files 已在选项目录和无损同步中，但藏于“解析与范围细节”的折叠项；常用“纳入与排除”仅显示 include_dirs/exclude_dirs。目录选择器仅支持目录、compile_commands.json及.cmake，无法选择排除的单文件。因此“字段已覆盖”并不证明用户可以方便完成任务。
- 将单文件排除移到“纳入与排除”，直接显示已有值与简明说明；支持逐行粘贴、逐项移除、工程内文件多选、去重、取消不改变配置。所有输入仍写原 analysis.exclude_files，不产生第二套配置字段。
- 文件选择器仅枚举当前层元数据、只选工程内真实文件，不读取源码内容、不跟随链接、不递归扫盘；选中可跨页面/目录，确认前逐个复核路径。目录排除继续写 analysis.exclude_dirs；跳过解析的 analysis.exclude 留在高级选项，明确它会减少覆盖，避免混淆。
- 复查当前 semantics.yaml 活动字段及编辑位置，尤其路径/列表配置的可操作性。保存与返回表单沿用现有严格无损合并与原文备份。

## 必须实际验收

1. 导入原配置，逐项确认 exclude_files 可见且路径原样保存，OpenCode等非修改项与原文注释保持不变。
2. 真实文件多选、跨层和分页、中文/空格/逗号、重复添加、取消、逐项移除、保存和重开。
3. 真实CMake教学工程扫描：other.c中定义的state不进变量清单，main.c中的同名state仍在；other.c对g_counter的访问和ISR入口证据仍保留。
4. 目录/API/表单专项、前端构建、真实浏览器、最终便携包入口及固件/程序哈希后验分别记账。

实施中，未验证项不计为通过。其他G2、32GB真机、干净离线机、系统DPI、真实OpenCode联网、人工UAT及大型整轮Diff/恢复仍按既有范围待验。

## 已观察结果（源码阶段）

43项目录/表单/API专项通过，前端类型检查及构建通过。真实浏览器已完成取消、多选跨目录和分页、中文/逗号/空格、去重、粘贴、移除、保存及重开；严格比较仅analysis.exclude_files改变，原OpenCode设置与注释保留。实际CMake原生扫描中other.c定义的变量未入清单，main.c同名变量保留，g_counter仍有来自other.c的访问。见[源码浏览器](acceptance/file-exclusion-v87-source-browser.json)和[字段/便利性审计](acceptance/file-exclusion-v87-field-audit.json)。最终包与后验尚待记录。

## 最终包验收

v87包内28项目录/表单测试通过。实际ECRA.cmd在Windows-only PATH启动，导入已有单文件排除可见、可移除并由文件选择器替换；严格配置对照仅exclude_files改变，原注释保留。真实CMake扫描再次证明other.c定义不入清单、main.c同名state保留、other.c的USART1_IRQHandler对g_counter访问仍在；保存配置重开仍一致。

[最终后验](acceptance/file-exclusion-v87-final.json)、[实际包内浏览器](acceptance/file-exclusion-v87-portable-browser.json)、[封装/中文解压](acceptance/file-exclusion-v87-portable-assembly.json)。原始42个固件文件和两套61文件教学源的名字/大小/mtime/SHA均未变，32,893个程序清单文件未被运行改写。冻结源清单SHA-256 b177414832fb2692375585a9bfcc807ec4d5f8fda9a5a0f9497f0385128da58b。

入口H:/ECRAStudio-build-20261107-studio-v87/ECRA-Portable/ECRA.cmd，ZIP SHA-256 4dc6fdebc6a102fea03d4cf7f53c0115084451e310677346725b0fcfd2ec566a。其他既有门禁保持待验。后续OpenCode资料问题另见131号记录。
