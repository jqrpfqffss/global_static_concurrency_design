"""NVIC evidence validation and BASEPRI threshold proofs."""
import re
from collections import defaultdict


def literal(text):
    match = re.fullmatch(r'\s*(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\s*', text or '')
    return int(match[1], 0) if match else None


def irq_key(name):
    return re.sub(r'_(IRQHANDLER|IRQN)$', '', (name or '').upper())


def priority_model(facts, cfg):
    bits = cfg.get('project', {}).get('nvic_priority_bits')
    if type(bits) is not int or not 1 <= bits <= 8:
        return {}, '缺少有效 nvic_priority_bits。'
    events = facts.get('irq_priority_events', [])
    funcs = {f['function_id']: f for f in facts['functions']}
    roots = {b['function_id'] for b in facts.get('context_bindings', []) if b['call_depth'] == 0}
    by_irq, groups = defaultdict(list), []
    for e in events:
        args = e.get('arguments', [])
        if e['api_name'].endswith('PriorityGrouping'):
            groups.append(e)
        elif args:
            by_irq[irq_key(args[0])].append(e)
    if len(groups) != 1:
        return {}, 'NVIC 分组缺失或存在多次/动态配置。'
    def valid(e):
        # Only unconditional setup in MAIN before its first application call
        # or shared access is proven here. Uncalled setup is never evidence.
        fid = e['function_id']
        if fid not in roots or funcs.get(fid, {}).get('name') != 'main' or e.get('conditional_ancestor'):
            return False
        first = [a.get('offset', -1) for a in facts['accesses'] if a['function_id'] == fid]
        first += [c.get('offset', -1) for c in facts['calls'] if c['caller_function_id'] == fid
                  and c.get('callee_function_id') in funcs and not c.get('callee_name', '').startswith(('HAL_NVIC_', 'NVIC_'))]
        return not first or e.get('offset', -1) < min(first)
    if not valid(groups[0]):
        return {}, 'NVIC 分组未证明在 MAIN 访问前无条件执行。'
    group = (groups[0].get('argument_values') or [None])[0]
    if group is None:
        group = literal(groups[0]['arguments'][0])
    if group is None or not 0 <= group <= 7:
        return {}, 'NVIC priority grouping 无法恢复。'
    pre_bits = min(bits, 7 - group)
    sub_bits = bits - pre_bits
    result = {}
    for irq, entries in by_irq.items():
        if len(entries) != 1 or not valid(entries[0]):
            continue
        event = entries[0]
        args = event['arguments']
        values = event.get('argument_values') or [literal(a) for a in args]
        priority = values[1] if len(values) > 1 else None
        if priority is None:
            continue
        if event['api_name'] == 'HAL_NVIC_SetPriority':
            sub = values[2] if len(values) > 2 else None
            if sub is None or not 0 <= priority < (1 << pre_bits) or not 0 <= sub < (1 << sub_bits):
                continue
            logical = (priority << sub_bits) | sub
        else:
            if not 0 <= priority < (1 << bits):
                continue
            logical = priority
        result[irq] = dict(logical=logical, preemption=logical >> sub_bits, bits=bits,
                           sub_bits=sub_bits, evidence=event)
    return result, '已核对 MAIN 初始化位置、NVIC 位数、分组及唯一优先级配置。'


def context_priorities(facts, model):
    funcs = {f['function_id']: f for f in facts['functions']}
    result = defaultdict(list)
    for b in facts.get('context_bindings', []):
        if b['call_depth'] == 0:
            key = irq_key(funcs.get(b['function_id'], {}).get('name'))
            result[b['context_id']].append(model.get(key))
    return {cid: items[0] for cid, items in result.items()
            if items and all(item is not None and item == items[0] for item in items)}


def relations(facts, contexts, cfg):
    from itertools import combinations
    model, reason = priority_model(facts, cfg)
    priorities = context_priorities(facts, model)
    rows = []
    for a, b in combinations(sorted(contexts), 2):
        kinds = (contexts[a]['kind'], contexts[b]['kind'])
        row = dict(contexts=[a,b], relation='MAY_INTERLEAVE', reason='按异步执行模型保留交错候选。')
        if set(kinds) == {'MAIN','ISR'}:
            row.update(relation='CAN_PREEMPT', higher=a if kinds[0]=='ISR' else b,
                       lower=b if kinds[0]=='ISR' else a, reason='ISR 可抢占未屏蔽的 MAIN。')
        elif kinds == ('ISR','ISR'):
            if a not in priorities or b not in priorities:
                row.update(relation='UNKNOWN_PREEMPTION', reason=reason + ' 至少一个 IRQ 的优先级未证明。')
            else:
                av, bv = priorities[a]['preemption'], priorities[b]['preemption']
                row.update(relation='SERIAL' if av==bv else 'CAN_PREEMPT', reason=reason,
                           priorities={a:av,b:bv})
                if av != bv:
                    row.update(higher=a if av<bv else b, lower=b if av<bv else a)
        rows.append(row)
    return rows


def basepri_status(windows, isrs, facts, cfg):
    model, reason = priority_model(facts, cfg)
    priorities = context_priorities(facts, model)
    if not isrs or any(c not in priorities for c in isrs):
        return 'UNRESOLVED', reason + ' 无法恢复全部竞争 IRQ 优先级。'
    if not windows or any(not w['basepri_known'] for w in windows):
        return 'UNRESOLVED', '完整访问窗口的 BASEPRI 值或被调函数效果未知。'
    thresholds = [v for w in windows for v in w['basepri_values']]
    if not thresholds or 0 in thresholds:
        return 'PARTIAL', '完整访问窗口中存在 BASEPRI=0，屏蔽未持续覆盖。'
    for cid in isrs:
        info = priorities[cid]
        shift = 8 - info['bits']
        for value in thresholds:
            if not 0 < value < 256 or value % (1 << shift) or (value >> shift) % (1 << info['sub_bits']):
                return 'UNRESOLVED', 'BASEPRI 阈值未按 NVIC 位数和抢占分组边界对齐。'
            if info['logical'] < (value >> shift):
                return 'INEFFECTIVE', f'{cid} 优先级高于 BASEPRI 阈值，仍可抢占。'
    return 'EFFECTIVE', 'CFG 完整窗口持续被 BASEPRI 屏蔽；所有竞争 IRQ 均满足已证明的阈值/分组关系。'
