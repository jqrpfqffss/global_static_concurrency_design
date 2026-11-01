# 四步向导的真实Git版本选择合同（实施前冻结）

已实施与局部验收：git_versions只读服务、GitVersions组件与POST profiles/git-versions真实接通。4项真实Git/API与8项原配置单测通过，Chrome6项实际选择/分页/检索/错误/保存/重开/非Git切换通过；42个获准F030源文件/原编译库不变，测试派生工程全部源/.git SHA与mtime不变，无外部页面请求。首轮select缺精确可访问名称失败已修复，原trace保留。见[evidence/git-selection-and-task-poll-v2.json](../evidence/git-selection-and-task-poll-v2.json)、[真实HEAD](screenshots/git-selection-v2/01-git-head-1366.png)、[实际保存](screenshots/git-selection-v2/02-refs-saved.png)。固定页脚已验，长表单仍在自身区域滚动；不据此称完整U04、DPI或UAT通过。

U04仍沿用第3步“分析范围”和已有base→current两个字段；九个导航、四步顺序、色彩/token和固定页脚不变。不新增独立版本管理器，不为扫描切换原HEAD、fetch、改索引/暂存区。

同一字段区提供“读取并核对本地Git版本”，从填写的固件路径实际查找仓库。基准/当前各可选择真实本地分支、remote ref、tag或HEAD，保留原始ref/SHA手工输入。基准空仍表示全量。列表在服务端筛选和分页，每页最多100，不把未列出的分支当不存在；前后翻页替换本页选项，不累积。加载列表不自动改两个已填字段。

显示实际仓库、当前分支或detached HEAD、HEAD SHA、所填两端引用解析到的commit SHA，以及staged/unstaged/untracked/conflicted实际计数。未提交覆盖明确为“本次固定提交比较不包含”；生产include_uncommitted仍拒绝。引用或根目录更改后不能显示旧SHA为当前已核对；页面读取只是当时预览，原生扫描启动仍按原pin/构建/输入一致性门禁重新固定，不以预览放行扫描。

Git缺失/坏引用错误给中文原因；无Git工程可继续全量。查询只读原仓库，Git可选索引刷新关闭，临时输出只在独立data/work/git-versions且及时关闭删除；不运行原钩子、网络或checkout。不解析/执行commit消息，不返回任意文件内容。

浏览器验收必须实际选择不同ref、核对SHA与dirty覆盖、生成/保存YAML、返回/重开、服务端翻页/检索、切换工程清除旧状态和非Git/错误状态；保存后的配置实际值必须与选择一致，源及.git全部SHA/mtime不变。另复跑原配置往返与主流程；保存截图并检查1366首屏固定操作。真实大工程Diff/只读挂载/系统DPI/UAT继续单列，不由本功能代替。
