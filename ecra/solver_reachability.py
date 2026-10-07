"""Prove which internal function bodies can affect the pointer solution.

Definitions and their extracted facts stay in the audit inventory. Only an
internal function with no possible entry path is omitted from pointer solving.
Externally linked definitions and explicit entries seed the graph; calls and
function references in reachable bodies extend it.
"""
from collections import defaultdict, deque
import re


EXCEPTION_ENTRIES = {'SysTick_Handler', 'PendSV_Handler', 'SVC_Handler',
                     'NMI_Handler', 'HardFault_Handler', 'MemManage_Handler',
                     'BusFault_Handler', 'UsageFault_Handler'}
BENIGN_ATTRIBUTES = {'ALWAYS_INLINE_ATTR', 'NO_INLINE_ATTR', 'NORETURN_ATTR',
                     'PURE_ATTR', 'CONST_ATTR', 'HOT_ATTR', 'COLD_ATTR'}
BENIGN_ATTRIBUTE_WORDS = {'always_inline', '__always_inline__', 'static', 'inline',
                          'noinline', '__noinline__', 'noreturn', '__noreturn__',
                          'pure', 'const', 'hot', 'cold'}


def may_be_implicit_entry(function):
    name = function.get('name', '')
    if (not name.startswith('HAL_') and function.get('parameter_count', 0) == 0
            and (name.endswith('IRQHandler') or name in EXCEPTION_ENTRIES)):
        return True
    for kind, spelling in zip(function.get('entry_attributes', ()),
                              function.get('attribute_spellings', ())):
        if kind in BENIGN_ATTRIBUTES:
            continue
        if kind != 'UNEXPOSED_ATTR':
            return True
        words = set(re.findall(r'[A-Za-z_][A-Za-z_0-9]*', spelling))
        if not words or not words <= BENIGN_ATTRIBUTE_WORDS:
            return True
    if len(function.get('entry_attributes', ())) > len(function.get('attribute_spellings', ())):
        return True
    return bool(function.get('is_weak'))


def function_designators(value, targets):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if item.get('op') == 'function' and item.get('id'):
                targets.add(item['id'])
            pending.extend(child for child in item.values()
                           if isinstance(child, (dict, list)))
        elif isinstance(item, list):
            pending.extend(child for child in item if isinstance(child, (dict, list)))


def prepare(facts, cfg, coverage=None):
    """Record a conservative internal-function reachability proof once."""
    if 'pointer_solver_pruning' in facts:
        return facts['pointer_solver_pruning']
    from .analysis import matches

    # An incomplete translation unit can contain a reference to a private
    # function from a shared header. Its AST is unavailable, so no negative
    # reachability proof is possible for this build.
    coverage = coverage or {}
    incomplete_kinds = {'PARSE_FAILED', 'SOURCE_NOT_IN_DATABASE', 'ASSEMBLY_SOURCE_REVIEW'}
    if (any(issue.get('kind') in incomplete_kinds for issue in facts.get('unknowns', ()))
            or any(unit.get('parse_status') == 'FAILED' for unit in facts.get('translation_units', ()))
            or coverage.get('translation_units_failed')
            or coverage.get('unlisted_sources')
            or facts.get('build_closure', {}).get('missing_objects')):
        proof = dict(reason='INCOMPLETE_BUILD', pruned_function_ids=[],
                     pruned_function_count=0, source_facts_retained=True)
        facts['pointer_solver_pruning'] = proof
        return proof

    functions = {row['function_id']: row for row in facts['functions']}
    roots = {fid for fid, row in functions.items()
             if not row.get('is_static') or may_be_implicit_entry(row)}
    graph = defaultdict(set)

    def reference(owner, targets):
        if owner in functions:
            graph[owner].update(targets)
        else:
            roots.update(targets)

    for issue in facts['unknowns']:
        if issue.get('target_function_id'):
            reference(issue.get('function_id'), (issue['target_function_id'],))
    for reg in facts.get('registrations', ()):
        if reg.get('function_id'):
            reference(reg.get('registered_by'), (reg['function_id'],))
    for table in ('vector_entries', 'assembly_vector_entries'):
        roots.update(row['function_id'] for row in facts.get(table, ())
                     if row.get('function_id'))
    configured = cfg.get('contexts', ())
    configured_edges = cfg.get('call_edges', ())
    if configured or configured_edges:
        for fid, function in functions.items():
            if (any(matches(function, context) for context in configured)
                    or any(matches(function, {'functions': [edge.get(side, '')]})
                           for edge in configured_edges for side in ('caller', 'callee'))):
                roots.add(fid)
    # An address taken in a function body becomes an entry only if that body
    # can run. Ownerless designators (for example global initializers) are
    # roots. This also covers older extractions missing FUNCTION_ADDRESS.
    for table in ('pointer_constraints', 'semantic_calls', 'indirect_accesses'):
        for row in facts.get(table, ()):
            targets = set()
            function_designators(row, targets)
            reference(row.get('function_id'), targets)
    reference_edge_count = sum(map(len, graph.values()))
    for call in facts['calls']:
        target = call.get('callee_function_id')
        if target:
            graph[call['caller_function_id']].add(target)
    reached = set(roots)
    pending = deque(roots)
    while pending:
        for callee in graph[pending.popleft()] - reached:
            reached.add(callee)
            pending.append(callee)
    pruned = sorted(fid for fid, function in functions.items()
                    if function.get('is_static') and fid not in reached)
    proof = dict(reason='INTERNAL_FUNCTION_NO_ENTRY_PATH',
                 pruned_function_ids=pruned,
                 pruned_function_count=len(pruned),
                 root_function_count=len(roots & functions.keys()),
                 reference_edge_count=reference_edge_count,
                 direct_call_edge_count=sum(1 for call in facts['calls']
                                            if call.get('callee_function_id')),
                 source_facts_retained=True,
                 assumptions=['Complete parsed references for each internal-linkage definition',
                              'Ownerless addresses and configured/vector entries seed possible roots'])
    facts['pointer_solver_pruning'] = proof
    return proof
