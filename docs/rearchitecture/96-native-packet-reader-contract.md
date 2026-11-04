# 逐对象Packet读取：内部验收合同

接续95号已有结果刷新。此合同先于实现；现已接入原生`review/review-failed`，限定验收见[97号](97-native-review-packet-acceptance.md)。整套大工程恢复仍未完成。原Packet生成器仍为对照，不改八步复核、格式修复、来源引用、风险判定或完整导航。

读取器从同一权威图选择完整变量/候选、原访问路径涉及函数、完整反向调用闭包及原Packet实际使用的全部关系。以源列表ordinal保留顺序和重复；不能依赖旧schema的caller/callee别名索引而漏掉实际`caller_function_id/callee_function_id`。使用原有标量内容哈希与edge_child定位；无相应索引的关系只扫描定位字段，不恢复整份facts。所有全局NVIC/上下文等原Packet直接包含的字段仍完整提供，不按大小截断。

控制流原Packet只保留除nodes外的完整字段及node_count，可以直接读取原nodes数组长度；完整nodes仍可从原EvidenceProvider导航。完整权威库不修改、不删除，Packet对照必须覆盖完整值、顺序、重复和所有字段，不能只比访问个数。

先以现有真实Clang深度复核案例、F030以及旧schema/空身份/重复关系反例，对原完整事实方法与新读取方法的**实际序列化Packet逐字段0差**；随后实际INAV对象放入资源监督Job测量。通过后才把已有复核消费者接入逐对象读取，保留完整输入闭包和原源码/环境/引擎重验。没有完成整个复核/停止/继续/收据/共享包回归前，整套低内存恢复仍NOT_VERIFIED。旧原生生产者数据的Packet读取不能冒充新原生扫描或物理32GB验收。
