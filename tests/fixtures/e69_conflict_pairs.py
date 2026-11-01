"""Frozen e69a10b conflict_pairs, unchanged reference for allocation-only optimization."""
from collections import defaultdict
import itertools
from ecra.common import digest
from ecra.analysis import all_resolved_routes,CONFLICT_PAIR_INLINE_LIMIT

def conflict_pairs(accesses, relations, contexts):
    """Build member-level conflict groups without losing any full path.

    A Cartesian product of every left/right route is only a presentation
    expansion: it repeats the same complete routes thousands of times on a
    large firmware.  One group therefore stores the two access/context
    instances and *all* routes on both sides.  The UI expands both collections
    and reports their product count, retaining every possible pair while
    keeping facts and HTML proportional to the actual call graph.
    """
    from .evidence import access_role
    relation_by_contexts = {tuple(sorted(row['contexts'])): row for row in relations}
    instances = {}
    for access in accesses:
        if access_role(access.get('access_kind')) is None:
            continue
        for context_id, route in all_resolved_routes(access):
            key = (access.get('access_id'), context_id)
            instance = instances.setdefault(key, dict(instance_id='CI-' + digest(key)[:20],
                context_id=context_id, access_id=access.get('access_id'), access_kind=access['access_kind'],
                function_id=access['function_id'], file=access.get('file'), line=access.get('line'),
                canonical_path=access.get('canonical_path'), call_path_count=0,
                access_scope=access.get('access_scope', 'MEMBER_ACCESS'),
                inherited_from_canonical_path=access.get('inherited_from_canonical_path')))
            instance['call_path_count_kind'] = ('EXACT_PATH_COUNT' if access.get('call_path_lists_complete', True)
                                                else 'WITNESS_COUNT')
            # Full routes stay once in access.all_call_chains.  A conflict
            # participant references that evidence by access/context instead
            # of duplicating every route for every competing counterpart.
            instance['call_path_count'] += 1
    pairs = []
    by_context = defaultdict(list)
    for instance in instances.values():
        by_context[instance['context_id']].append(instance)
    # The ordinary rows are useful for a small variable, but even after call
    # routes are shared, one row per access pair is quadratic.  A context pair
    # has one execution relation, so its complete product can be represented
    # by the two context selectors over the variable's canonical accesses.
    # The original accesses (including every access ID and full graph evidence)
    # remain in variable.accesses and can reproduce every row on demand.
    grouped = {cid: (items,
                     [item for item in items if access_role(item['access_kind']) == 'WRITE'],
                     [item for item in items if access_role(item['access_kind']) == 'READ'])
               for cid, items in by_context.items()}
    potential_rows = 0
    context_ids = sorted(grouped)
    for i, left_cid in enumerate(context_ids):
        left_all, left_writes, left_reads = grouped[left_cid]
        for right_cid in context_ids[i:]:
            right_all, right_writes, right_reads = grouped[right_cid]
            if left_cid == right_cid:
                if contexts.get(left_cid, {}).get('reentrant'):
                    potential_rows += (len(left_writes) * (len(left_writes) + 1) // 2
                                       + len(left_writes) * len(left_reads))
            else:
                potential_rows += (len(left_writes) * len(right_all)
                                   + len(left_reads) * len(right_writes))
    if potential_rows > CONFLICT_PAIR_INLINE_LIMIT:
        for i, left_cid in enumerate(context_ids):
            left_all, left_writes, left_reads = grouped[left_cid]
            for right_cid in context_ids[i:]:
                right_all, right_writes, right_reads = grouped[right_cid]
                if left_cid == right_cid:
                    if not contexts.get(left_cid, {}).get('reentrant'):
                        continue
                    count = (len(left_writes) * (len(left_writes) + 1) // 2
                             + len(left_writes) * len(left_reads))
                    write_paths = sum(row['call_path_count'] for row in left_writes)
                    read_paths = sum(row['call_path_count'] for row in left_reads)
                    path_count = (write_paths * read_paths
                                  + (write_paths * write_paths
                                     + sum(row['call_path_count'] ** 2 for row in left_writes)) // 2)
                else:
                    count = (len(left_writes) * len(right_all)
                             + len(left_reads) * len(right_writes))
                    path_count = (sum(row['call_path_count'] for row in left_writes)
                                  * sum(row['call_path_count'] for row in right_all)
                                  + sum(row['call_path_count'] for row in left_reads)
                                  * sum(row['call_path_count'] for row in right_writes))
                if not count:
                    continue
                left = left_writes[0] if left_writes else left_reads[0]
                right = right_all[0] if left_writes else right_writes[0]
                left_context = contexts.get(left_cid, {})
                right_context = contexts.get(right_cid, {})
                same_physical = (left_context.get('physical_id') is not None
                                 and left_context.get('physical_id') == right_context.get('physical_id'))
                reentrant_physical = left_context.get('reentrant') or right_context.get('reentrant')
                if same_physical and not reentrant_physical:
                    relation = dict(contexts=sorted({left_cid, right_cid}), relation='SERIAL',
                                    reason='两个逻辑入口属于同一物理执行上下文；该前台域或 IRQ 向量内部串行执行。',
                                    physical_id=left_context['physical_id'])
                elif left_cid == right_cid:
                    relation = dict(contexts=[left_cid], relation='MAY_REENTER',
                                    reason='同一执行上下文默认串行；显式可重入上下文另作并发候选。')
                else:
                    relation = relation_by_contexts.get(tuple(sorted((left_cid, right_cid))),
                                                        dict(contexts=[left_cid, right_cid],
                                                             relation='UNKNOWN_PREEMPTION',
                                                             reason='未恢复两个执行上下文的关系。'))
                mhp = ('NO' if relation['relation'] == 'SERIAL' else
                       'MAYBE' if relation['relation'] == 'UNKNOWN_PREEMPTION' else 'YES')
                possible = mhp != 'NO'
                pairs.append(dict(
                    conflict_id='C-' + digest([left['instance_id'], right['instance_id'],
                                               left_cid, right_cid, 'CONTEXT_ACCESS_PRODUCT'])[:16],
                    representation='CONTEXT_ACCESS_PRODUCT',
                    access_reference='variable.accesses',
                    pair_generation=('COMBINATIONS_WITH_REPLACEMENT' if left_cid == right_cid
                                     else 'CROSS_PRODUCT'),
                    pair_rule='AT_LEAST_ONE_WRITE', pair_count=count,
                    participant_a_read_access_ids=sorted({row['access_id'] for row in left_reads}),
                    participant_a_write_access_ids=sorted({row['access_id'] for row in left_writes}),
                    participant_b_read_access_ids=sorted({row['access_id'] for row in right_reads}),
                    participant_b_write_access_ids=sorted({row['access_id'] for row in right_writes}),
                    participant_a=left, participant_b=right, relation=relation,
                    mhp=mhp, may_concurrent=possible, has_write_conflict=True,
                    status='需确认' if possible else '忽略（同一串行上下文）',
                    path_combination_count=path_count,
                    path_combination_count_kind=('EXACT_PATH_PRODUCT'
                        if all(row['call_path_count_kind'] == 'EXACT_PATH_COUNT'
                               for row in left_all + right_all) else 'WITNESS_PRODUCT')))
        return sorted(pairs, key=lambda pair: (
            not pair['may_concurrent'], pair['participant_a']['context_id'],
            pair['participant_b']['context_id'], pair['conflict_id']))
    for left_cid, right_cid in itertools.combinations_with_replacement(sorted(by_context), 2):
        if left_cid == right_cid and not contexts.get(left_cid, {}).get('reentrant'):
            continue
        candidates = (itertools.combinations_with_replacement(by_context[left_cid], 2)
                      if left_cid == right_cid else itertools.product(by_context[left_cid], by_context[right_cid]))
        for left, right in candidates:
            if access_role(left['access_kind']) == access_role(right['access_kind']) == 'READ':
                continue
            # The exact same source access on the exact same route is one
            # access instance, not a self-conflict.  The same source point in
            # another context deliberately remains a distinct instance.
            if (left['access_id'] == right['access_id'] and left['context_id'] == right['context_id']
                    and not contexts.get(left['context_id'], {}).get('reentrant')):
                continue
            left_context = contexts.get(left['context_id'], {})
            right_context = contexts.get(right['context_id'], {})
            same_physical = (left_context.get('physical_id') is not None
                             and left_context.get('physical_id') == right_context.get('physical_id'))
            reentrant_physical = left_context.get('reentrant') or right_context.get('reentrant')
            if same_physical and not reentrant_physical:
                relation = dict(contexts=sorted({left['context_id'], right['context_id']}),
                                relation='SERIAL',
                                reason='两个逻辑入口属于同一物理执行上下文；该前台域或 IRQ 向量内部串行执行。',
                                physical_id=left_context['physical_id'])
            elif left['context_id'] == right['context_id']:
                relation = dict(contexts=[left['context_id']],
                                relation='MAY_REENTER' if contexts.get(left['context_id'], {}).get('reentrant') else 'SERIAL',
                                reason='同一执行上下文默认串行；显式可重入上下文另作并发候选。')
            else:
                relation = relation_by_contexts.get(tuple(sorted((left['context_id'], right['context_id']))),
                                                    dict(contexts=[left['context_id'], right['context_id']],
                                                         relation='UNKNOWN_PREEMPTION',
                                                         reason='未恢复两个执行上下文的关系。'))
            mhp = ('NO' if relation['relation'] == 'SERIAL' else
                   'MAYBE' if relation['relation'] == 'UNKNOWN_PREEMPTION' else 'YES')
            possible = mhp != 'NO'
            has_write = access_role(left['access_kind']) == 'WRITE' or access_role(right['access_kind']) == 'WRITE'
            state = ('需确认' if possible and has_write else
                     '无写冲突' if possible else '忽略（同一串行上下文）')
            pairs.append(dict(conflict_id='C-' + digest([left['instance_id'], right['instance_id']])[:16],
                              participant_a=left, participant_b=right, relation=relation,
                              mhp=mhp, may_concurrent=possible, has_write_conflict=has_write, status=state,
                              path_combination_count=left['call_path_count'] * right['call_path_count'],
                              path_combination_count_kind=('EXACT_PATH_PRODUCT'
                                  if left['call_path_count_kind'] == right['call_path_count_kind'] == 'EXACT_PATH_COUNT'
                                  else 'WITNESS_PRODUCT')))
    return sorted(pairs, key=lambda pair: (not pair['may_concurrent'], not pair['has_write_conflict'],
                                           pair['participant_a']['context_id'], pair['participant_b']['context_id'],
                                           pair['conflict_id']))
