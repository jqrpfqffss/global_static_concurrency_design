"""冻结 6e3b665e 的保护评估，用于索引优化的独立等价性对照。"""

def legacy_assess(accesses, events, contexts, facts, cfg):
    relevant = [a for a in accesses if a['access_kind'] in {'READ', 'WRITE', 'RMW'}]
    ids = {c for a in relevant for c in a.get('contexts', [])}
    mains = {c for c in ids if contexts[c]['kind'] == 'MAIN'}
    isrs = {c for c in ids if contexts[c]['kind'] == 'ISR'}
    related = {a['function_id'] for a in relevant}
    for a in relevant:
        graph_slice = facts.get('call_graph_slices', {}).get(a.get('call_graph_slice'))
        if graph_slice is not None:
            related.update(graph_slice['function_ids'])
        else:
            for paths in a.get('all_call_chains', {}).values():
                related.update(f for path in paths for f in path)
    detected = [e for fid in related for e in events.get(fid, [])]
    details = [dict(access_id=a['access_id'], file=a['file'], line=a['line'],
                    states=a.get('mask_states', [])) for a in relevant]
    if not detected:
        return 'NOT_FOUND', details, '未发现关联路径上的同步或中断屏蔽操作。'
    if all(e.get('protection_type') == 'barrier' for e in detected):
        return 'INEFFECTIVE', details, 'DMB/DSB/ISB 只约束内存或指令顺序，不屏蔽中断，也不提供互斥。'
    windows = [w for w in facts.get('mask_windows', []) if relevant and
               w['symbol_id'] == relevant[0]['symbol_id'] and w['context_id'] in mains]
    funcs = {f['function_id']: f for f in facts['functions']}
    unmaskable = any(funcs.get(b['function_id'], {}).get('name') in {'NMI_Handler', 'HardFault_Handler'}
                     for b in facts['context_bindings'] if b['call_depth'] == 0 and b['context_id'] in isrs)
    unmaskable |= any(contexts[c].get('unmaskable') for c in isrs)
    main_accesses = [a for a in relevant if set(a.get('contexts', [])) & mains]
    complete = all(a.get('contexts') for a in relevant) and all(
        any(s['context_id'] == c and s.get('complete') for s in a.get('mask_states', []))
        for a in main_accesses for c in set(a['contexts']) & mains)
    isr_pairs = [r for r in facts.get('preemption_relations', []) if set(r['contexts']) <= isrs]
    participants = bool(mains and isrs) and ids == mains | isrs and not unmaskable
    participants &= all(r['relation'] == 'SERIAL' for r in isr_pairs)
    nmi = any(funcs.get(b['function_id'], {}).get('name') == 'NMI_Handler'
              for b in facts['context_bindings'] if b['call_depth'] == 0 and b['context_id'] in isrs)
    if (complete and mains and isrs and ids == mains | isrs and not nmi
            and not any(contexts[c].get('unmaskable') for c in isrs)
            and all(r['relation'] == 'SERIAL' for r in isr_pairs)
            and windows and all(w.get('faultmask') for w in windows)):
        return 'EFFECTIVE', details, 'CFG 完整访问窗口持续 FAULTMASK=1；竞争方不含 NMI。'
    primask = bool(windows) and all(w['primask'] for w in windows)
    if complete and participants and primask:
        return 'EFFECTIVE', details, 'CFG 全路径和被调函数证明完整访问窗口持续 PRIMASK=DISABLED；竞争方仅为可屏蔽 ISR。'
    base_found = any(e.get('protection_type') == 'basepri' for e in detected)
    if base_found:
        from ecra.interrupts import basepri_status
        status, reason = basepri_status(windows, isrs, facts, cfg)
        if status == 'EFFECTIVE' and not (complete and participants):
            return 'UNRESOLVED', details, 'BASEPRI 阈值已解析，但参与者或 CFG 覆盖不足。'
        return status, details, reason
    states = [s for a in main_accesses for s in a.get('mask_states', []) if s['context_id'] in mains]
    if states and any(s['irq_state'] == 'UNKNOWN' for s in states):
        if all(s.get('complete') for s in states) and not any(e['event_kind']=='primask_set' for e in detected):
            return 'PARTIAL', details, 'CFG 分支汇合不能保证每条路径都持续屏蔽中断。'
        return 'UNRESOLVED', details, '分支汇合、未知调用或不支持的控制流阻断了 PRIMASK 状态证明。'
    if unmaskable:
        return 'INEFFECTIVE', details, 'PRIMASK 不能屏蔽 NMI/HardFault 竞争方。'
    if primask and len(isrs) > 1:
        return 'UNRESOLVED', details, 'MAIN 已屏蔽，但 ISR 之间的冲突尚未排除。'
    if any(s['irq_state'] == 'DISABLED' for s in states) or any(e['event_kind'] == 'lock_exit' for e in detected):
        return 'PARTIAL', details, '检测到屏蔽操作，但未持续覆盖完整 READ→MODIFY→WRITE 窗口。'
    return 'DETECTED', details, '发现保护操作，尚无完整冲突窗口的有效性证明。'
