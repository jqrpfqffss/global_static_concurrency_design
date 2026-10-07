"""NVIC evidence validation and BASEPRI threshold proofs."""
import re
from collections import defaultdict


def literal(text):
    match = re.fullmatch(r'\s*(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\s*', text or '')
    return int(match[1], 0) if match else None


def irq_key(name):
    return re.sub(r'_(IRQHANDLER|IRQN)$', '', (name or '').upper())


def priority_model(facts, cfg, fg_functions=None):
    """恢复每个 IRQ 的逻辑优先级（用于证明同抢占优先级串行）。

    有效性条件（声音性优先）：
    - 分组配置：恰好一次按字面量读取；完全没有分组调用时采用 Cortex-M
      复位默认 PRIGROUP=0（硬件事实：全部优先级位为抢占位）；多次/动态
      分组放弃。
    - 每个 IRQ 恰好一次优先级设置，调用点无条件祖先，且设置函数只从前台
      （MAIN 域）可达——ISR 内改优先级属于运行期重配置，不采纳。
    """
    bits = cfg.get('project', {}).get('nvic_priority_bits')
    if type(bits) is not int or not 1 <= bits <= 8:
        return {}, '缺少有效 nvic_priority_bits。'
    fg_functions = fg_functions or set()
    events = facts.get('irq_priority_events', [])
    by_irq, groups = defaultdict(list), []
    for e in events:
        args = e.get('arguments', [])
        if e['api_name'].endswith('PriorityGrouping'):
            groups.append(e)
        elif args:
            by_irq[irq_key(args[0])].append(e)

    def valid(e):
        if not fg_functions or e['function_id'] not in fg_functions:
            return False
        return not e.get('conditional_ancestor')

    if len(groups) > 1:
        return {}, 'NVIC 分组多次/动态配置。'
    if groups:
        if not valid(groups[0]):
            return {}, 'NVIC 分组未证明在前台初始化路径无条件执行。'
        group = (groups[0].get('argument_values') or [None])[0]
        if group is None:
            group = literal(groups[0]['arguments'][0])
        if group is None or not 0 <= group <= 7:
            return {}, 'NVIC priority grouping 无法恢复。'
        grouping_reason = '已核对唯一分组配置。'
    else:
        group = 0
        grouping_reason = '工程未配置优先级分组，采用 Cortex-M 复位默认 PRIGROUP=0。'
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
    return result, grouping_reason + ' 已核对前台初始化位置与唯一优先级配置。'


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
    # 前台函数：全部执行上下文均为 MAIN 域（ISR 内的优先级设置不采纳）。
    by_function = defaultdict(set)
    for b in facts.get('context_bindings', []):
        by_function[b['function_id']].add(b['context_id'])
    fg_functions = {fid for fid, cids in by_function.items()
                    if cids and all(contexts.get(c, {}).get('kind') == 'MAIN' for c in cids)}
    model, reason = priority_model(facts, cfg, fg_functions)
    priorities = context_priorities(facts, model)
    rows = []
    for a, b in combinations(sorted(contexts), 2):
        kinds = (contexts[a]['kind'], contexts[b]['kind'])
        row = dict(contexts=[a,b], relation='MAY_INTERLEAVE', reason='按异步执行模型保留交错候选。')
        if set(kinds) == {'MAIN'}:
            # 多个 MAIN 上下文属于同一前台调度域：裸机 main/while(1) 串行
            # 派发的任务不会互相并发。
            row.update(relation='SERIAL', reason='多个 MAIN 入口属于同一前台串行调度域。')
        elif set(kinds) == {'MAIN','ISR'}:
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
    by_function = defaultdict(set)
    for b in facts.get('context_bindings', []):
        by_function[b['function_id']].add(b['context_id'])
    contexts_map = {c['id']: c for c in facts.get('contexts', [])}
    fg_functions = {fid for fid, cids in by_function.items()
                    if cids and all(contexts_map.get(c, {}).get('kind') == 'MAIN' for c in cids)}
    model, reason = priority_model(facts, cfg, fg_functions)
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
