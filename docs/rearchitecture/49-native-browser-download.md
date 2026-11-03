# 标准包及人工增量：浏览器原生下载

2026-11-03，后续于700befd；1379项冻结v29回归不包含本段新增下载代码/4项测试。最新已封存实包仍v27，尚未把新源码冒充已打包内容。

原前端先fetch完整导出文件、await Response.blob()、创建对象URL后触发下载。现改为认证POST领取单文件短期凭证，浏览器原生下载FileResponse；前端只接收小凭证JSON。未改变.ecra-report、确认增量、归档一致快照/校验/独占发布或静态分析策略，不需新数据库或第三方前端库。审查实际调用方仅App.vue和HistoryCenter.vue，二者均使用原有导出端点返回的已生成文件名。

| 实现/边界 | 具体行为 |
|---|---|
| 新增ecra/studio/downloads.py | 每服务最多128个凭证；仅允许exports下32位hex命名的两种已存在导出文件；no_links检查、设备/文件ID/大小/mtime/ctime绑定；锁内发放、过期清除及变更拒绝。 |
| POST /api/download/{name}/ticket | 沿用会话Header、Origin、Host检查；只授予单一文件，不在地址放Studio会话凭据。15分钟内可Range续传/重试；重复认证领取同一不可变文件不堆积凭证。 |
| GET /export-download/{ticket} | 256bit随机能力凭证、单文件/时效/身份约束；仍检查Host及出现的Origin。到期/缺失/文件变化返回410与重新发起提示；不能凭此访问其他API。保留no-store、no-referrer、attachment。 |
| 兼容性 | 原认证Header的GET /api/download/{name}保留；历史列表和数据共享使用同一原生下载函数；归档/增量协议不变。 |
| 源码与人工数据 | 下载读取闭合导出文件，不重新扫描或修改scan.db；短期凭证不持久化到人工/静态库。源导出包保留，服务重启后重新领取链接。 |

| 实际验收 | 结果 | 证据 |
|---|---|---|
| 首轮专项 | 25项：21PASS/4ERROR；测试误用Python3.10没有的TestCase.enterContext。改为ExitStack，未改生产协议来掩盖失败 | [原失败](evidence/native-download-focused-v1-failed.json) |
| 修复后专项 | **25PASS**，13.987s：真实HTTP认证/跨Origin与Host拒绝、单文件权限边界、Range重组字节、过期/更换/删除/无效链接、旧Header接口、注册表上限及原归档/人工一致性回归 | [收据](evidence/native-download-focused-v2.json) |
| 实际前端构建 | vue-tsc + Vite通过，1.55s；index-Dxjk0qro.js | [构建](evidence/native-download-frontend-build-v1.json) |
| Chrome首轮 | FAIL：人工事件实际已提交，测试断言错写既有中文标签；仅改测试匹配，原截图/数据保留 | [原失败](evidence/browser-native-download-host-v1-failed.json) |
| Chrome次轮 | FAIL：完整包已下载且SHA一致，但Page request事件没有覆盖Chrome下载管理器请求，不能以该计数判断未下载。改用真实Download事件URL+落盘字节，不伪造请求数 | [原失败](evidence/browser-native-download-host-v2-failed.json) |
| Chrome第三轮 | **4组PASS**：真实F030包内变量确认→标准完整包原生下载→严格导入独立根→增量原生下载/重复导入0新增。禁止Response.blob及createObjectURL的实际浏览器tripwire调用数0 | [收据](evidence/browser-native-download-host-v3.json) |
| 传输实测 | 完整ZIP **70287721B**，浏览器保存字节与exports文件SHA同为281b48d1975890c83f52ba8195075846073d01c10d425e44cb7299f727f124ab；含明确标注的67108864B随机无引用CAS容量夹具，不是新固件事实/新原生工程 | 同上 |
| 来源/人工保持 | 原获准F030包SHA前后4c1d0f7e…，原静态SHA前后86757328…一致；新确认事件在完整包中保留，增量再导入幂等。新事件只写隔离测试副本，不写黄金原件 | 同上 |
| 实际历史列表回归 | **8组PASS**，23个既有真实原生归档独立副本；历史行打开/继续/标准包与增量导出/重开、原库/人工记录及全部当前运行时代码SHA保持 | [收据](evidence/browser-native-download-history-host-v1.json) |
| 尚未验收 | 多GiB INAV原生完整包、实际浏览器传输RAM/磁盘峰值、物理第二台无工具链电脑、Windows系统DPI及工程师UAT；不能将64MiB夹具记成大型G2/G3/G4/G8通过 | NOT_VERIFIED |

实际截图：[标准完整包](ui/screenshots/continuation-20261103/native-download-ui-host-v3-01-real-complete-native-browser-download.png)、[确认增量](ui/screenshots/continuation-20261103/native-download-ui-host-v3-02-real-review-delta-native-download.png)。原始控制器、trace、服务器日志及两轮失败保留在`H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3/native-download-*`；会话及下载能力URL不发布到公共收据。

本段不宣称Response.blob在所有浏览器都会把整包驻留JS堆；本轮未测该内存归因。改动验证的是移除应用完整Blob接收路径，并由实际Chrome原生管理下载/Range。新1383项完整回归、打包、实包浏览器与大型标准包仍须实际执行。
