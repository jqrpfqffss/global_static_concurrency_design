"""逐函数穷举的历史参考算法，仅用于核对分组优化，不用于生产扫描。"""
from collections import defaultdict
from ecra.common import digest


def reference_coherence(variables, accesses_by_symbol, contexts, calls=(), bindings=()):
    """Find source-backed cross-field transactions on one storage root.

    Field sensitivity must not erase a protocol in which one executor publishes
    several fields and another consumes the same set.  Requiring at least two
    common fields in one writer function and one reader function avoids using
    names or project-specific allow/deny lists as a substitute for evidence.
    """
    from ecra.evidence import access_role
    callers = defaultdict(set)
    for call in calls:
        if call.get('callee_function_id'):
            callers[call['callee_function_id']].add(call['caller_function_id'])
    caller_contexts = defaultdict(set)
    for binding in bindings:
        caller_contexts[binding['function_id']].add(binding['context_id'])
    roots = defaultdict(list)
    for variable in variables:
        if variable.get('root_symbol_id'):
            roots[variable['root_symbol_id']].append(variable)
    result = defaultdict(list)
    grouped = {}
    for root_id, members in roots.items():
        writes, reads = defaultdict(set), defaultdict(set)
        sites = defaultdict(lambda: defaultdict(list))
        for member in members:
            sid = member['symbol_id']
            for access in accesses_by_symbol.get(sid, []):
                role = access_role(access.get('access_kind'))
                if role is None or access.get('reachability') == 'PROVEN_UNREACHABLE':
                    continue
                for cid in access.get('contexts', []):
                    physical = contexts.get(cid, {}).get('physical_id')
                    if not physical:
                        continue
                    key = (physical, access.get('function_id'))
                    (writes if role == 'WRITE' else reads)[key].add(sid)
                    sites[key][sid].append(access['access_id'])
                    if role == 'READ':
                        # A caller can consume several fields through separate
                        # one-level accessors. Attribute their actual reads to
                        # that invocation as a conservative coherence group.
                        # Context intersection prevents an unrelated caller
                        # domain from inheriting the read.
                        for caller in callers.get(access.get('function_id'), ()):
                            if cid in caller_contexts[caller]:
                                caller_key = (physical, caller)
                                reads[caller_key].add(sid)
                                sites[caller_key][sid].append(access['access_id'])
        for writer, written in writes.items():
            if len(written) < 2:
                continue
            for reader, observed in reads.items():
                if writer[0] == reader[0]:
                    continue
                common = written & observed
                if len(common) < 2:
                    continue
                # A large cooperative call graph can have thousands of writer
                # and reader functions for the same physical context/member
                # set.  The cross product is an audit presentation detail, not
                # a new coherence fact.  Keep one source-backed group and its
                # exact pair count, functions, accesses and one concrete pair.
                key = (root_id, writer[0], reader[0], tuple(sorted(common)))
                evidence = grouped.get(key)
                if evidence is None:
                    evidence = grouped[key] = dict(kind='MULTI_FIELD_COHERENCE',
                        coherence_id='MC-' + digest(key)[:20],
                        root_symbol_id=root_id, writer_physical_context=writer[0],
                        reader_physical_context=reader[0], member_symbol_ids=list(key[3]),
                        writer_function_ids=set(), reader_function_ids=set(),
                        writer_access_ids=set(), reader_access_ids=set(),
                        function_pair_count=0,
                        witness=dict(writer_function_id=writer[1], reader_function_id=reader[1]),
                        reason='同一写入函数发布多个成员，另一物理上下文中的同一调用过程直接或经一层访问器读取这些成员。')
                evidence['function_pair_count'] += 1
                evidence['writer_function_ids'].add(writer[1])
                evidence['reader_function_ids'].add(reader[1])
                candidate = (writer[1], reader[1])
                previous = (evidence['witness']['writer_function_id'],
                            evidence['witness']['reader_function_id'])
                if candidate < previous:
                    evidence['witness'] = dict(writer_function_id=writer[1],
                                               reader_function_id=reader[1])
                evidence['writer_access_ids'].update(
                    ident for sid in common for ident in sites[writer][sid])
                evidence['reader_access_ids'].update(
                    ident for sid in common for ident in sites[reader][sid])
    for evidence in grouped.values():
        for name in ('writer_function_ids', 'reader_function_ids',
                     'writer_access_ids', 'reader_access_ids'):
            evidence[name] = sorted(evidence[name])
        for sid in evidence['member_symbol_ids']:
            result[sid].append(evidence)
    return {sid: sorted(rows, key=lambda row: (
                row['root_symbol_id'], row['writer_physical_context'],
                row['reader_physical_context'], row['member_symbol_ids']))
            for sid, rows in result.items()}
