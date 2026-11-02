# ADR-020：归并时共享逐字段相同的只读CFG节点体（实施中）

## 实测与保护边界

原版完整INAV归档有491009个CFG。对最前4000个完整规范CFG的只读元数据查询，节点数组743种，3257个数组引用内容重复；199776个逻辑节点出现对应94541个唯一节点出现。此为有界样本，不代表全工程比例或内存收益，不替代原生G1/G2/G3。CFG外层的function_id、cfg_id及TU身份不同，即使节点体相同仍必须保留每个CFG行。

调用审计：`extract.build_cfg`构造节点和successors；之后`resolve_linkage`只筛选被覆盖弱定义，FactParts提供独立行。归并后的`control_flow`仅供`protection.MaskAnalysis`、`initialization`、`nonlocal_jumps`和`review`读取/遍历，未发现节点体就地修改。全局指针/上下文/初始化/保护逻辑、图的身份/入口/出口/complete/unknown等全部维持。共享位置在归并逐行原digest之后，保留原字典覆盖规则、表/字段/数组次序、所有原CFG及重复节点，不能按函数名或头文件路径猜测相同。

## 实现合同

只处理确切内建dict行的nodes/parameters/unsupported字段；完整验证嵌套值为确切内建JSON类型、str键及有限float。自定义对象/容器/tuple/非字符串键/不支持值旁路，不做类型转换。序列化采用完整有序JSON，区分bool/int/float、负零、键顺序、所有重复及Unicode字符；不排序、不采样、不截断。SHA命中后再次比较先前对象的完整有序编码，碰撞不误合并；失效/逐出的加速项只导致重做原分配。

辅助LRU最多4096项，缓存仅持有现有不可变节点体引用，不保存整份编码副本。每个图的外层dict与function_id/cfg_id/TU仍独立；只复用内容逐字段相同的内层原生dict/list。归并结果的这些内层CFG证据沿既有只读约定使用，后续若需修改必须独立复制并重验；这不允许删减任何未可达CFG。

除降低存活节点体分配，权威GraphWriter可按已证明存活的同一对象复用，减少重复哈希/候选SQL编码。没有实际测量前不宣称发布提速、12/16GiB或70%磁盘通过。原生冷扫描在最终冻结代码、完整回归/独立原合并器/同输入原生验证之后进行；原先v9仅排队，已在任何输入读取或Worker启动前撤销，未取消正在执行的原生任务。

## 验收要求与当前状态

独立冻结原合并器、类型/次序/重复/碰撞/未知字段与旁路回归，完整388TU原始输入归并回放和全部根摘要对照，真实同输入F030原生对照、冻结完整套件与新实包、大型冷原生及完整全图比较均需独立收据。当前实施中，G3原FAIL继续有效。此改造不包含于v21软件候选；不得把v21收据用于此代码。


## 源码候选的已验范围（完整阶段仍未完成）

| 项目 | 实际结果 | 证据 / 状态 |
|---|---|---|
| 独立原合并器 | 5项PASS、6.551s，25组seeded弱定义/解析失败/常量剪枝/重复行，各表及输入逻辑字段有序对照；2400CFG/24000节点全部保留的容量分配更低 | [专项](evidence/cfg-sharing-focused-v2.json) |
| 原Unicode失败门禁 | 首轮正例误含孤立代理字符，原合并器拒绝；修正为双方均须UnicodeEncodeError的负例，未放宽common.digest | [首轮FAIL保留](evidence/cfg-sharing-focused-v1-failed.json) |
| 实际同输入F0304TU | 完整facts与严格规范report差异0；原配置路径/字节/工具链、42原文件与93引擎文件未变，预期INCOMPLETE exit2 | [原生收据](evidence/cfg-sharing-native-exact-v1.json)；不是大型G1/G3 |
| 完整388TU归并回放 | 独立94文件冻结试验，原I:/ECRA-N3完整388个原生TU响应，776原始文件前后SHA不变；完整根9be73ce...及全部表指纹与独立原版一致。12GiB受控Job实际完成；归并后private 9710538752→4338974720字节，主进程峰值commit 9913896960→4550012928字节 | [PASS，完整收据](evidence/cfg-merge-replay-v1.json)。只覆盖归并，不包含Clang/全局分类/发布，不是大型原生G1/G2/G3 |
| 回放时间 | 原归并453.594s，新归并548.797s，含输入哈希/完整指纹的控制器1618.047s | 有额外CPU成本，HDD并发环境也不同，不宣称提速；没有用采样替代全量指纹 |
| 完整1312回归/实包 | 1310 PASS、2项opt-in SKIP，1824.918s；v22实际构建/目录和中文路径ZIP各27项CLI完成，十三组浏览器未运行 | [回归](evidence/full-regression-studio-v22.json)、[实际构建](evidence/portable-studio-v22-build-v1.json)。v22仍有随后发现的[标量完整性缺口](27-scalar-byte-boundary-integrity.md)，不是发布通过 |
| 最终修复版冷原生/完整对照 | 必须绑定标量修复后冻结源；当前未启动 | NOT_VERIFIED，原G3 FAIL继续有效 |

候选提交仅证明表中已验范围，完整Phase2仍未通过。若完整388TU根/表不一致或实际内存没有收益，应回退此分配候选，不能修改对照规范。旧24GiB retention诊断在9小时后仍未发布有效库，已受控停止，原始基线/备份/完整TU缓存及未发布现场保留；不计作成功或自然OOM。其独立停止收据和4123输入/890引擎文件后验另行封存。新冷扫描队列必须指向最终冻结源码，不能调用被撤销的v9队列。

[实际停止收据](evidence/inav-classification-retention-v2-controlled-stop.json)、[最终运行结果](evidence/inav-classification-retention-v2-final.json)、[4123输入/890引擎完整SHA后验](evidence/inav-classification-retention-v2-postflight.json)保留该失败现场的事实：运行32792.813s后退出15、未发布有效库，Job峰值18449494016字节。没有删除原数据或把停止伪装成成功。
