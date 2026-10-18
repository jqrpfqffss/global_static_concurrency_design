"""Merge immutable static evidence with current semantic reviews.

Review progress is a separate axis: an unfinished or inconclusive review is
never evidence against a static risk. Only an effective semantic verdict may
confirm or refute that risk.
"""
from collections import defaultdict


CONCURRENT_SIGNALS = {'GS-MULTI-CONTEXT', 'GS-MULTI-WRITER', 'GS-RMW-INTERLEAVE',
    'GS-STALE-SNAPSHOT', 'DMA_SHARED_REVIEW', 'GS-LOCAL-STATIC-REENTRANT', 'GS-OWNER-VIOLATION'}
DECISIONS = {
    'confirmed': ('已确认并发风险', '存在风险；查看复核依据并修复。'),
    'likely': ('疑似并发风险', '有并发风险线索，尚未证实为实际缺陷。'),
    'unresolved': ('无法判断', '缺少入口、访问或定义证据，不能判定安全。'),
    'safe': ('已复核：未发现并发风险', '仅在该项复核列出的条件下成立。'),
    'screened_safe': ('已排查：未发现并发风险', '当前编译配置下没有可形成读写冲突的已知访问；不覆盖解析盲区、汇编或未建模硬件入口。'),
    'screened_shared': ('共享访问，无需复核', '已通过严格单写者门禁；这是共享访问筛除结论，不等同于静态安全证明。'),
    'inventory': ('未发现并发风险', '当前建模路径未发现跨执行上下文读写线索；结论仅适用于已解析范围。'),
    'supplemental': ('补充声明（未分析访问）', '来自未编译文件或条件分支变体；仅盘点声明，并发访问尚未分析。'),
}
RISK_PRIORITY = ('confirmed', 'likely', 'unresolved', 'safe')


def review_category(record):
    """Classify the raw review outcome, for review progress only."""
    if record.get('state') != 'DONE':
        return 'unresolved'
    return {'CONFIRMED': 'confirmed', 'LIKELY': 'likely', 'REVIEWED_SAFE': 'safe',
            'FALSE_POSITIVE': 'safe'}.get(record.get('status'), 'unresolved')


def effective_decision(finding, record, *, variable=None):
    reviewed = review_category(record)
    if reviewed != 'unresolved':
        return reviewed
    static = finding.get('static_classification') or (variable or {}).get('static_classification')
    if static == 'SUSPECT':
        return 'likely'
    if static == 'UNKNOWN':
        return 'unresolved'
    if static in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}:
        return 'safe'
    # Legacy findings may predate static_classification. Never let a review's
    # cached copy of that field replace the finding/variable's static evidence.
    return 'likely' if set(finding.get('rules', [])) & CONCURRENT_SIGNALS else 'unresolved'


def aggregate_decisions(decisions):
    return min(decisions, key=RISK_PRIORITY.index)


def decision_label(group, records=()):
    if group == 'safe' and records and all(review_category(r) == 'safe' for r in records):
        return '已确认误报' if all(r.get('status') == 'FALSE_POSITIVE' for r in records) else '已复核安全'
    return DECISIONS[group][0]


def variable_decisions(facts, report, records):
    variables = {v['symbol_id']: v for v in facts['variables']}
    groups = defaultdict(list)
    for finding in report['findings']:
        sid = finding.get('symbol_id')
        if sid:
            groups[sid].append(effective_decision(finding, records.get(finding['finding_id'], {}),
                                                  variable=variables.get(sid)))
    result = {}
    for sid, variable in variables.items():
        static = variable.get('static_classification')
        if variable.get('coverage_source') in ('supplemental', 'inactive_branch'):
            resolved = [d for d in groups[sid] if d in {'confirmed', 'safe'}]
            result[sid] = aggregate_decisions(resolved) if resolved and len(resolved) == len(groups[sid]) else 'supplemental'
        elif groups[sid]:
            result[sid] = aggregate_decisions(groups[sid])
        elif static == 'SUSPECT':
            result[sid] = 'likely'
        elif static == 'UNKNOWN' or variable.get('parse_status') == 'FAILED':
            result[sid] = 'unresolved'
        elif static == 'SAFE_PROVEN' or variable.get('audit_status') == 'STATIC_SAFE_PROVEN':
            result[sid] = 'screened_safe'
        elif static == 'SHARED_NO_REVIEW' or variable.get('audit_status') == 'SHARED_NO_REVIEW':
            result[sid] = 'screened_shared'
        else:
            result[sid] = 'inventory'
    return result
