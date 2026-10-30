"""Associate scalar snapshots with stores after storage canonicalization."""
from collections import defaultdict, deque


def read_then_writeback_hints(facts):
    """Keep accesses intact; emit an extra relation for exact storage identity.

    Track unchanged scalar parameters, constant adjustments, and direct getter
    returns. Unknown return values are never associated with arbitrary reads.
    A visited (function, parameter) set bounds forwarding, including recursion.
    Relations describe possible value flow, not a concurrency verdict.
    """
    reads, stores, forwarding = defaultdict(list), defaultdict(list), defaultdict(list)
    variables = {v['symbol_id']: v for v in facts['variables']}
    return_sources = {f['function_id']: f.get('scalar_return_sources', []) for f in facts['functions']}
    for access in facts['accesses']:
        # Overlap copies are not proof that precisely this object was loaded.
        if access.get('inherited_from_access_id') or access.get('reachability') == 'PROVEN_UNREACHABLE':
            continue
        if access['access_kind'] == 'READ':
            reads[(access['function_id'], access['file'], access['offset'])].append(access)
        if 'writeback_parameter_index' in access:
            stores[(access['function_id'], access['writeback_parameter_index'])].append(access)
    direct_calls = [c for c in facts['calls'] if c.get('call_kind') == 'DIRECT' and c.get('callee_function_id')]
    for call in direct_calls:
        for arg in call.get('value_arguments', []):
            if 'parameter_index' in arg:
                forwarding[(call['caller_function_id'], arg['parameter_index'])].append(
                    (call['callee_function_id'], arg['argument_index'], call.get('allowed_contexts'),
                     arg.get('derived_value', False)))

    call_sites = {(c['caller_function_id'], c['file'], c['offset']): c for c in direct_calls}

    def origin_reads(source, caller):
        pending = deque([(source, caller, [caller], source.get('derived_value', False), None)])
        visited = set()
        while pending:
            value, function, path, derived, allowed = pending.popleft()
            site = value.get('read_site')
            if site:
                for read in reads.get((function, site['file'], site['offset']), ()):
                    active = set(read.get('contexts', ()))
                    if allowed is not None:
                        active.intersection_update(allowed)
                    yield read, path, derived, active
                continue
            returned = value.get('return_call')
            if not returned:
                continue
            call = call_sites.get((function, returned['file'], returned['offset']))
            if not call or call['callee_function_id'] != returned['callee_function_id']:
                continue
            active = allowed
            if call.get('allowed_contexts') is not None:
                active = (set(call['allowed_contexts']) if active is None
                          else active.intersection(call['allowed_contexts']))
            callee = call['callee_function_id']
            key = (callee, None if active is None else frozenset(active), derived)
            if key in visited:
                continue
            visited.add(key)
            for result in return_sources.get(callee, ()):
                pending.append((result, callee, path + [callee],
                                derived or result.get('derived_value', False), active))

    hints, seen = [], set()
    for call in direct_calls:
        for arg in call.get('value_arguments', []):
            for read, read_path, derived, active in origin_reads(arg, call['caller_function_id']):
                sid = read['symbol_id']
                storage = variables[sid].get('canonical_path', variables[sid]['qualified_name'])
                if '[*]' in storage:
                    continue  # a dynamic index is overlap, not exact identity
                if call.get('allowed_contexts') is not None:
                    active.intersection_update(call['allowed_contexts'])
                todo = deque([(call['callee_function_id'], arg['argument_index'],
                               [call['caller_function_id']], frozenset(active), derived)])
                visited = set()
                while todo:
                    function, parameter, path, active, derived = todo.popleft()
                    key = (function, parameter)
                    if not active or (key, active, derived) in visited:
                        continue
                    visited.add((key, active, derived))
                    route = path + [function]
                    for write in stores.get(key, ()):
                        contexts = sorted(active & set(write.get('contexts', ())))
                        identity = (sid, read['access_id'], write['access_id'], tuple(contexts))
                        if write['symbol_id'] != sid or identity in seen or not contexts:
                            continue
                        seen.add(identity)
                        def location(access):
                            return {k: access[k] for k in ('access_id', 'file', 'line', 'function_id', 'offset')}
                        hints.append(dict(kind='READ_THEN_WRITEBACK', symbol_id=sid, storage=storage,
                            read_site=location(read), write_site=location(write), read_contexts=contexts,
                            write_contexts=write['contexts'], call_path=route,
                            read_return_path=read_path,
                            derived_value=derived or write.get('writeback_derived_value', False),
                            reason='同一canonical storage先读取，旧值经getter返回或标量实参传递（可能含常量运算）后写回；需检查完整READ→WRITEBACK窗口'))
                    for callee, index, allowed, adjustment in forwarding.get(key, ()):
                        todo.append((callee, index, route, active if allowed is None else active.intersection(allowed),
                                     derived or adjustment))
    return hints
