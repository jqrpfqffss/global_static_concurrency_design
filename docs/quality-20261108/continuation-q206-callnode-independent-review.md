# Q206 CallNode：独立只读审查

已审查UI-only v5 `studio/src/CallNode.vue`，SHA `1edff57755ad664f18a7bf8f48d38c4f13512ca73b20bbdffd3b47aec3495b3b`。v4/v5的41个studio/src文件中只有该文件变化，全部后端Python字节相同，core仍63a5…；本审查没有修改生产、冻结源或包。

原Q206实际公开CLI NMI归档中，读取规范call-neighbors行，核对了四种关系：Impl上游GNU alias、ExceptionRoute下游GNU alias、main下游普通DIRECT、__disable_irq上游普通DIRECT。原scan.db SHA保持不变。

- 仅按每条边的 `summary.call_kind === GNU_FUNCTION_ALIAS` 判断，避免把“调用一个别名函数”的普通callsite也误标成别名绑定。
- 上游正确标“函数别名 → 当前实现”，下游正确标“当前别名 → 实现函数”；普通调用仍沿用原调用者/当前函数/被调用者方向。
- alias的同一file/line现在明确标为“别名声明”，对应真实原始声明行；完整函数别名证据仍可展开，不伪造成C普通调用位置。
- page.total改称已恢复的上游/下游关系，涵盖混合边；没有过滤或丢失原普通调用、多处来源、分页、递归身份和证据节点。加载generation和错误重试逻辑未改变。

范围内只读审查通过，实际行及源码差分在 `output/quality-20261108/continuation/q206/ui-v5-independent-review.json`、`ui-v5-CallNode-reviewed.patch`。初版校验脚本只因Windows相对路径反斜杠与预期正斜杠不同而失败，原脚本/日志保留；改为规范as_posix后确认实际仅CallNode变化，未修改产品或缩小比较集合。

本审查是源代码与真实归档行核对，不声称又完成一次浏览器视觉验收。根负责上下游实际点击、声明阅读及保存/重开截图，以及最新UI重新封包；其他sourceguard门禁仍以根记录为准。
