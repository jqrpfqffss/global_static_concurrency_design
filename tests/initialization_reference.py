"""Historical exhaustive entry-closure oracle, preserved for index equivalence."""
from collections import defaultdict
from ecra.initialization import WRITES, is_async_enable


def reference_phase_entries_closed(accesses, facts, contexts, cfg):
    """Reject phase proofs with an unmodelled executor before IRQ activation.

    A source access ID is shared by every invocation of its function.  Seeing
    that ID once during main initialization does not prove that another
    foreground entry cannot call it later.  Other asynchronous roots may also
    activate the target IRQ while main is writing, including NMI or an IRQ
    inherited from a bootloader.  Until their closure is proved inert, fail
    closed for the initialization optimization.
    """
    writers = [row for row in accesses if row.get('access_kind') in WRITES]
    if not writers:
        return True
    target_irq_contexts = {cid for row in accesses for cid in row.get('contexts', ())
                           if contexts.get(cid, {}).get('physical_kind') == 'IRQ'}
    roots = [row for row in facts.get('context_bindings', ()) if row.get('call_depth') == 0]
    call_graph = defaultdict(set)
    for call in facts.get('calls', ()):
        if call.get('callee_function_id'):
            call_graph[call['caller_function_id']].add(call['callee_function_id'])

    def reaches(start, target):
        seen, pending = set(), [start]
        while pending:
            fid = pending.pop()
            if fid == target:
                return True
            if fid in seen:
                continue
            seen.add(fid)
            pending.extend(call_graph.get(fid, set()) - seen)
        return False

    functions = {row['function_id']: row for row in facts.get('functions', ())}
    main_ids = {fid for fid, row in functions.items() if row.get('name') == 'main'}
    if len(main_ids) != 1:
        return False
    reset_ids = {row.get('function_id') for row in facts.get('vector_entries', ())
                 if row.get('kind') == 'MAIN' and row.get('slot') == 1}
    allowed = main_ids | reset_ids
    writer_functions = {row.get('function_id') for row in writers}
    enable_functions = {event.get('function_id') for event in facts.get('irq_priority_events', ())
                        if is_async_enable(event.get('api_name', ''), cfg)}
    function_ids = {row['function_id'] for row in facts.get('functions', ())}
    opaque_callers = {row.get('caller_function_id') for row in facts.get('calls', ())
                      if not row.get('callee_function_id') or row.get('callee_function_id') not in function_ids}
    def closure(start):
        seen, pending = set(), [start]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(call_graph.get(current, set()) - seen)
        return seen
    for call in facts.get('calls', ()):
        callee = call.get('callee_function_id')
        if (call.get('call_kind') == 'ASSEMBLY_LITERAL_CALL'
                and call.get('caller_function_id') in reset_ids and callee in main_ids):
            continue
        if (callee and (call.get('call_kind') == 'CONFIGURED' or call.get('offset') is None)
                and any(reaches(callee, writer) for writer in writer_functions)):
            # A configured or locationless edge contributes context reachability
            # but cannot be placed before the enable in a complete Clang CFG.
            return False
    for root in roots:
        cid = root.get('context_id')
        fid = root.get('function_id')
        kind = contexts.get(cid, {}).get('physical_kind')
        if kind not in {'FOREGROUND', None} and cid not in target_irq_contexts:
            reachable = closure(fid)
            if reachable & (writer_functions | enable_functions | opaque_callers):
                return False
        if contexts.get(cid, {}).get('physical_kind') != 'FOREGROUND':
            continue
        if fid not in allowed and any(reaches(fid, writer) for writer in writer_functions):
            return False
    return True
