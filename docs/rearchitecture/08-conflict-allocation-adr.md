# ADR-009：冲突参与者对象分配（验证中）

受保护文件：analysis.py，仅conflict_pairs的临时参与者创建。原生INAV旧版分类阶段的只读py-spy栈停在common.digest → conflict_pairs:449；记录continuation-h3/inav-original-stack-v1.log。旧版仍运行，不修改其冻结代码。

`dict.setdefault(key, dict(...digest...))`在命中已有实例时也先计算整个默认值；每条完整路径都做一次。改为只在key首次出现时创建实例，后续仍按每条路径原样增加call_path_count，并原样更新最后一条记录的call_path_count_kind。实例键、首条记录获胜、遍历顺序、摘要输入和全部关系逻辑均不改变。实例仍为真实普通dict，但复用既有RecordDicts的共享schema键，值保持独立；不改变任何输出字段/字段顺序/数组顺序/重复次数。

证明边界：只支持既有JSON输入字典；digest纯函数无副作用。新分支创建时以原关键字参数相同次序填充字段；重复键时等价于setdefault返回既有对象。全部候选、串行/可重入、未知抢占、完整与witness路径、阈值两侧的产品表示保持原实现。没有降低CONFLICT_PAIR_INLINE_LIMIT或采样/截断路径。

验收：冻结e69函数原文为独立测试参考并记录SHA；比较空/单域/多域/相同物理域/可重入/重复ID/不同路径模式/产品阈值两侧的完整有序类型化摘要；真实F030已有黄金各变量的全部冲突重新求值比较；独立内存容量样本比较临时分配；运行现有保护/分类相关回归。未完成前不称H1/G1/G3通过，INAV新旧全字段对照仍为必要门禁。若输出不同须撤回该改动，不按无证明的排序掩盖差异。

已验证局部：4项专门测试PASS；12,000访问/48,000路径样本临时Python峰值10,032,993B→5,013,433B，采样耗时0.805s→0.274s（tracemalloc开启，不能代替原生资源门禁）。原函数原文SHA为7f73bfe450235519c5d2a877581396b697bc00567c16f298cd9edc52f6bfebe5。已归档F030的13变量/2冲突行逐字段差异0；另重新实际提取4TU（2PARSED/2PARTIAL），全部facts和规范report与原生独立黄金差异0，源码/.git/原黄金哈希不变、旧HTML/JSON/库存目录不生成。见evidence/conflict-allocation-v1.json、native-parsed-allocation-v1.json。

原型失败保留：dict.update的空字典快路径使共享schema布局失效，现改按原顺序逐字段写入；首个参与者断言误选IRQ自重入冲突，现按真实context定位。初次198项回归还出现跨进程hash-seed复核测试退出码2而预期1；运行期间工作区源码曾变更，原因尚未证明。后续须在冻结字节上完整复跑，不以4项专项替代该失败。此受保护模块是此前“分析区未改”的明确例外，仅对象分配改变，判定/关系仍受完整G1门禁约束。
