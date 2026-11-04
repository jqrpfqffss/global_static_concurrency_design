# 原生复核逐对象读取与真实停止/重试验收

> 后续收齐：[v54完整回归](acceptance/full-regression-studio-v54-final.json)1508项为1506PASS/2联网SKIP，2714.123秒，3760引擎和独立测试副本SHA不变。两份完整INAV最大Packet同时驻留/写文件/收据检查已按[98号](98-concurrent-packet-stress-contract.md)4GiB Job通过，峰值提交2,813,624,320B。包内首次初始化停止暴露的所有权pending缺陷及修复另见[100号](100-owner-publication-stop-acceptance.md)，不以本页早期通过代替后续停止修复或全部重构完成。

2026-11-05，接续[96号先行合同](96-native-packet-reader-contract.md)。起点`optimize_ccc@8f679e9b0889fea3b68193d8af28e9501139b599`，保留既有修改。本阶段接通原生`review/review-failed`消费者；**不代表大Diff、全部恢复、联网模型、物理32GB或全部重构完成**。

## 实现与合同

`native_review_packet`按原ordinal读取完整对象、全部访问/路径及完整反向调用闭包，复用原Packet生成器。只投影生成器实际读取字段，不采样；原完整证据仍在authority导航。CFG读取原生成器使用的其他字段及节点数量。共享提示上下文完整对照，不能用95号小投影代替完整coverage/limitations/编译输入。

原生`_saved_run`复核/技术失败重试和检查点采用元数据刷新，不能据此新建authority；原源码/环境/引擎/输入闭包及完整报告摘要前后仍实际重验。缓存JSON摘要及文件SHA分段计算，字节合同不变。独立收据完整验证Packet JSON语法，仅保留原校验器实际使用的写回/NVIC/技术标识符；模型仍收到完整Packet。历史shared-codec或非对象Packet仍用原解码，**该兼容分支不承诺有界**。

INAV暴露原Packet生成器对递归边调用`.get`，而`analysis.py`实际输出两元素数组。现支持原数组及历史dict，保留原形状/顺序，未知格式拒绝，未改分析器。v51选择器曾漏数组，其构造成功已由[失效收据](acceptance/native-review-packet-v51-invalidated.json)撤销语义验收资格，不作为体积收益或等价证据。

任务使用独立`review-diagnostics`，不再显示旧扫描TU进度；计数为“复核项目已处理（含技术失败）”，结束不等于AI成功。停止只有一个监视器，重试保持原全部/仅失败模式和历史。沿用冻结导航/布局。

## 验收结果

| 场景/门禁子集 | 实测结果 | 证据 |
|---|---|---|
| 原Packet合同 | 6组真Clang深度案例、旧v1/v3、重复/别名、递归/异常格式；完整序列化字节对照，禁止whole-provider.load | `tests/test_native_review_packet.py` |
| 原路径真实F030 | 冻结v55全部6个Packet与完整共享上下文序列化相同；原8,962,048B库SHA不变，0.156秒；非新扫描 | [收据](acceptance/native-review-packet-f030-v55.json) |
| 当前专项 | 冻结3761文件v55，172项为171PASS/1联网SKIP，103.552秒，SHA全不变；与之前18/60项重叠 | [专项](acceptance/native-review-regression-v55.json) |
| 原生生命周期 | 真Clang扫描后禁止全图读取；两并行候选一成功一失败，failed-only只重试失败项；中断130、包/历史/原静态SHA。协议替身非模型推理 | `tests/test_native_review_workflow.py` |
| Chrome/F030 U08/U15子流程 | 1366×768实际Studio及受监督子进程：打开不启动任务，停止→INTERRUPTED，重试6/6技术失败，failed-only新增历史，Packet可读，完整包独立导入收据相同；161个源/配置/原扫描文件及代码/资产不变，无页面错误/外部请求 | [浏览器](acceptance/native-review-f030-ui-v55.json)、[计数](ui/screenshots/native-review-v55/02-real-review-failures-count.png)、[停止](ui/screenshots/native-review-v55/01-real-review-stop.png)、[Packet](ui/screenshots/native-review-v55/03-real-packet-archive.png) |
| 前端 | 实际`npm run build`通过vue-tsc/Vite，离线资产`index-DOTmv6eH.css/index-DWMAlMa4.js` | 构建输出与浏览器资产SHA |

v55清单SHA256 `1c91b3db53cba044682bc5d51178df99f795cdc430f677cb6c76ad5ec4104058`。v54独立冻结完整回归仍执行中，不能用较早v49的1495PASS/2SKIP冒称当前树通过。v55增加任务诊断/UI和专项，验证范围分列。

## 既有真实INAV完整Packet

旧v13生产者`49960e`的完整库`H:/ECRA-NATIVE-A13-SEED0/scans/native-golden/scan.db`为12,590,489,600B，SHA256 `4549110d23bfb9ed3c78d5ea686fbeeb94e9e140eac4b88974288c25bd4e7913`。16566变量、3540候选、491011函数、20224调用、1534856未知记录。选实际最大15216访问候选`GS-00abeb3d9a62f851`，各次原库前后完整SHA不变。

| 实际执行 | Job提交峰值 / RSS峰值（字节） | 结果 |
|---|---|---|
| 原完整facts+完整report，16GiB | [原失败](acceptance/native-review-packet-full-v50-failed.json) | MemoryError，FAIL，无完整Packet |
| 原完整facts+单候选旧生成器，32GiB | [格式失败](acceptance/native-review-packet-control-v52-failed.json) | 递归数组`.get`失败，FAIL |
| 仅修正递归兼容的原完整facts+单候选v53，32GiB | 19,405,934,592 / 18,297,094,144 | 主体426.516秒，含哈希/监督501.453秒；[对照](acceptance/native-review-packet-inav-control-v53.json) |
| 新逐对象v53，2GiB，实际写完整文件 | 1,442,013,184 / 1,430,605,824 | 主体265.234秒/控制器328.437秒；[选择读取](acceptance/native-review-packet-inav-selected-v53.json) |
| 生产接入v54，2GiB，写文件并独立读取收据投影 | 1,443,061,760 / 1,433,591,808 | 主体380.750秒/控制器445.140秒；全语法、标识符/NVIC/写回提示相同，禁止整文件read_bytes；[收据检查](acceptance/native-review-packet-inav-receipt-v54.json) |

三次有效结果均为**615,590,601字节同一完整序列化Packet**，SHA256 `3154602da3cf36a914dcf5005d4c005664b37f856cadf9314a90e6be9e45dcb6`，原common.digest/新流式缓存键均为`596b47e1f5a8cd48bacd9eb7e30d92d0c2e3b7cf708c44c7511b4742cb4eeabd`。实际indent=1文件628,662,175B，v54文件SHA `b781b027f315da169440cefde334daadce900f62870aecb162786dca0f0a2551`。v51体积小源于漏边，明确无效。

上述只是**单个完整Packet/收据消费者**。64GB共享主机，对照不写文件而新路径写文件，并行有回归，不作相对提速或整套峰值/物理32GB声明。原库只消费，非新原生G2、完整saved_run输入重放或联网模型。v54清单SHA256 `84b84d0fc32c4cfa4060f6e57be0e9ed16df66728f5f5ff9f698b2b86455d256`，3760文件后验无变化。

## 失败与剩余工作

UI验证器曾误盘点ignored大产物，核对自身PID后在浏览器启动前[停止](acceptance/native-review-ui-v55-v1-stopped.json)；command误用字符串被正式配置[拒绝](acceptance/native-review-ui-v55-v2-failed.json)；异步POST未返回就读任务列表引起[控制器失败](acceptance/native-review-ui-v55-v3-failed.json)。修正验证器为argv数组、等待真实POST响应后通过，未放宽生产门禁。v4流程通过，v5另等最终状态并把计数滚入可见截图。

Diff基准摘要/完整验证及全局求解仍有全图读取；最大Packet多Worker/整个复核联合峰值、引用源文件流读待做；dirty绝对视图跨根重放未证明，CMake未提交构建仍阻断。Portable仍v37，不含新功能。其他G2用户延期；物理32GB、第二PC、干净离线机、原生DPI、联网模型、工程师UAT均NOT_VERIFIED。第四项及G1–G8未全部完成。

复现（work必须全新独立，原件只读）：

```powershell
py -3.10 -B -X utf8 scripts/validate_native_packet_reader.py --source <原生scan目录> --work <独立新目录> --mode selected --job-gib 2 --write-packet --verify-packet
py -3.10 -B -X utf8 scripts/validate_native_packet_reader.py --source <同一scan目录> --work <独立对照目录> --mode control --job-gib 32
py -3.10 -B -X utf8 scripts/validate_native_review_ui.py --source <获准scan目录> --config <原有效semantics.yaml> --work <独立新目录>
py -3.10 -B -X utf8 -m unittest tests.test_native_review_packet tests.test_native_review_workflow tests.test_review_packet_projection tests.test_task_metadata_reads -q
```
