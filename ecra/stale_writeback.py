"""Associate direct argument loads with scalar parameter stores, after storage canonicalization."""
from collections import defaultdict, deque


def read_then_writeback_hints(facts):
    """Keep accesses intact; emit an extra relation for exact storage identity.

    Only unchanged scalar parameters and direct argument values are tracked.
    A visited (function, parameter) set bounds forwarding, including recursion.
    Relations describe possible value flow, not a concurrency verdict.
    """
    reads, stores, forwarding = defaultdict(list), defaultdict(list), defaultdict(list)
    variables = {v['symbol_id']: v for v in facts['variables']}
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
                    (call['callee_function_id'], arg['argument_index'], call.get('allowed_contexts')))
    hints, seen = [], set()
    for call in direct_calls:
        for arg in call.get('value_arguments', []):
            site = arg.get('read_site')
            if not site:
                continue
            for read in reads.get((call['caller_function_id'], site['file'], site['offset']), ()):
                sid = read['symbol_id']
                storage = variables[sid].get('canonical_path', variables[sid]['qualified_name'])
                if '[*]' in storage:
                    continue  # a dynamic index is overlap, not exact identity
                active = set(read.get('contexts', ()))
                if call.get('allowed_contexts') is not None:
                    active.intersection_update(call['allowed_contexts'])
                todo = deque([(call['callee_function_id'], arg['argument_index'],
                               [call['caller_function_id']], frozenset(active))])
                visited = set()
                while todo:
                    function, parameter, path, active = todo.popleft()
                    key = (function, parameter)
                    if not active or (key, active) in visited:
                        continue
                    visited.add((key, active))
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
                            reason='同一canonical storage先作为实参读取，旧值经未改写的标量参数传递后写回；需检查完整READ→WRITEBACK窗口'))
                    for callee, index, allowed in forwarding.get(key, ()):
                        todo.append((callee, index, route, active if allowed is None else active.intersection(allowed)))
    return hints
