# U16：v32保留3000历史事件，再确认1000项

实际包49960e，包内Python3.10.9与真实Chrome，原版INAV17.8GB图的独立人工库副本；不是新原生扫描或物理跨电脑验证。最终2618.906s，4个验收组全部通过，原始根不变、控制器SHA未变。

| 验收 | 实际结果 | 证据 |
|---|---|---|
| 旧历史 | 开始保留3000个已知事件，完整payload不变 | [实际操作](evidence/review-fourth-batch-v32-v2.json) |
| 新增 | 1000个不同canonical对象，全部NEED_MORE_EVIDENCE；实际按钮提交，不生成安全结论 | 同上，最终4000事件 |
| 重启 | 350/700/1000新增事件后三次关闭服务/浏览器并重开；后端原始位置与UI检索/分类/人工筛选恢复 | 同上，3次重启组 |
| 静态与原件 | 私有图完整SHA660dffb2…不变；原始根仍3000事件，原人工库SHA及图大小/mtime不变；控制器未变 | [驱动](evidence/review-fourth-batch-v32-v2-driver.json) |
| 保存响应 | 中位1.562s，P95 1.718s，最大6.547s；共享机械盘实测，不作独占性能保证 | 实际操作收据 |

界面恢复了原先保存的精确检索，初轮脚本未主动清除检索而错误期待全局待办，新增1项后失败。该副本/3001事件/trace全部保留；第二轮新建私有副本，先验证原检索确实恢复，再通过可见UI清除检索并选择SUSPECT/PENDING，没有SQL重置。详见[合同](ui/33-fourth-confirmation-batch-contract.md)及首轮失败收据。原图只剩366个UNKNOWN待确认，因此新批次先使用真实SUSPECT待办；不补造1000个UNKNOWN。

[350次](ui/screenshots/review-fourth-batch-v32-v2/upgrade-batch-350.png)、[700次](ui/screenshots/review-fourth-batch-v32-v2/upgrade-batch-700.png)、[1000次](ui/screenshots/review-fourth-batch-v32-v2/upgrade-batch-1000.png)。trace和完整私有库留在外部continuation-h3，不提交巨型数据。

本包U16功能范围改为PASS，[完整U矩阵](ui/34-user-scenario-status-v32.md)12PASS/12NOT_VERIFIED。Windows原生DPI、工程师盲测、物理第二电脑、全根复制迁移、原地覆盖升级仍未验；不以分批操作通过关闭完整G7/G8或H4。
