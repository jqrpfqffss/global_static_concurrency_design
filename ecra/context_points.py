"""Refine pointer accesses by physical caller without splitting shared storage.

The first inclusion solution remains the conservative fallback. A second finite
solution separates invocation-local parameter, local, result and literal slots
by execution context. Global/static objects keep their original identities, so
foreground callback registration and IRQ consumption still communicate.
"""
from collections import defaultdict, deque
import copy

from .common import digest
from .points_to import Solver


def scoped_location(location, context):
    if context is None or location.startswith(('obj:', 'unknown:', 'fn:', 'context-slot:')):
        return location
    return 'context-slot:' + digest(context)[:16] + ':' + location


def scoped_expression(expression, context):
    if not isinstance(expression, dict):
        return expression
    result = {}
    for key, value in expression.items():
        if key == 'id' and expression.get('op') == 'loc':
            result[key] = scoped_location(value, context)
        elif isinstance(value, dict):
            result[key] = scoped_expression(value, context)
        elif isinstance(value, list):
            result[key] = [scoped_expression(item, context) for item in value]
        else:
            result[key] = value
    return result


class ContextSolver(Solver):
    def __init__(self, facts, cfg=None):
        super().__init__(facts, cfg)
        self.escape_contexts = {row.get('_context_id') for table in ('semantic_calls', 'pointer_constraints')
                                for row in facts.get(table, [])}

    def parameter_location(self, target, index, call):
        return scoped_location(super().parameter_location(target, index, call), call.get('_context_id'))

    def return_location(self, target, call):
        return scoped_location(super().return_location(target, call), call.get('_context_id'))

    def add_access(self, locations, record, mode, **extra):
        context = record.get('_context_id')
        if extra.get('hardware'):
            allowed = [item['id'] for item in self.facts.get('hardware_contexts', [])
                       if item['function_id'] == record['function_id']]
        else:
            allowed = [context] if context is not None else None
        if allowed is not None:
            extra['allowed_contexts'] = allowed
        super().add_access(locations, record, mode, **extra)

    def guard_impossible(self, record):
        return bool(self.guard_evidence(record))

    def guard_evidence(self, record):
        if record.get('function_id') in self.facts.get('guard_unknown_entries', set()):
            return []
        proofs = []
        for condition in record.get('path_conditions', []):
            # NULL is intentionally absent from the base may-points lattice.
            # A singleton address is therefore not a must-equal proof. Only
            # disjointness can prove an equality arm unreachable.
            if not condition.get('equals'):
                continue
            possible = self.value(condition['parameter'])
            expected = self.value(condition['target'])
            if not possible or not expected or any(value.startswith('unknown:') or value.endswith('/$overlap')
                                                   for value in possible | expected):
                continue
            a, b = {self.symbol(value) for value in possible}, {self.symbol(value) for value in expected}
            if None not in a | b and a.isdisjoint(b):
                proofs.append(dict(context_id=record.get('_context_id'), file=condition.get('file'),
                    line=condition.get('line'), reason='Immutable pointer parameter targets disjoint storage objects',
                    possible_targets=sorted(possible), compared_targets=sorted(expected)))
        return proofs

    def escaped_return_slots(self, function):
        result = super().escaped_return_slots(function)
        for context in self.escape_contexts:
            slot = scoped_location(function + ':return', context)
            result.update({slot} | self.descendant_slots.get(slot, set()))
        return result


def site(row, caller=False):
    return (row.get('caller_function_id') if caller else row.get('function_id'),
            row.get('file'), row.get('offset'))


def clone_record(row, context, expression_fields):
    result = dict(row, _context_id=context)
    for field in expression_fields:
        value = row.get(field)
        if isinstance(value, list):
            result[field] = [scoped_expression(item, context) for item in value]
        elif isinstance(value, dict):
            result[field] = scoped_expression(value, context)
    return result


def union_rows(rows, access=False):
    """Coalesce one fact with several execution witnesses, never erase a gap."""
    grouped = {}
    for row in rows:
        key = digest({key: value for key, value in row.items()
                      if key not in {'allowed_contexts', '_context_id', 'access_id'}})
        if key not in grouped:
            grouped[key] = dict(row)
            grouped[key].pop('_context_id', None)
            if 'allowed_contexts' in row:
                grouped[key]['allowed_contexts'] = list(row['allowed_contexts'])
        elif 'allowed_contexts' not in row:
            grouped[key].pop('allowed_contexts', None)
        elif 'allowed_contexts' in grouped[key]:
            grouped[key]['allowed_contexts'] = sorted(set(grouped[key]['allowed_contexts']) | set(row['allowed_contexts']))
    result = list(grouped.values())
    if access:
        for row in result:
            row['access_id'] = 'A-' + digest({k: v for k, v in row.items() if k != 'access_id'})[:20]
    return result


def reachable_domains(roots, calls):
    graph = defaultdict(list)
    for call in calls:
        if call.get('callee_function_id'):
            graph[call['caller_function_id']].append(call)
    result = defaultdict(set)
    for context, entries in roots.items():
        pending = deque(entries)
        while pending:
            function = pending.popleft()
            if context in result[function]:
                continue
            result[function].add(context)
            for call in graph[function]:
                if 'allowed_contexts' not in call or context in call['allowed_contexts']:
                    pending.append(call['callee_function_id'])
    return dict(result)


def _pass(facts, cfg, domains):
    from .evidence import ENTRY_GAPS
    unknown_entries = {row['target_function_id'] for row in facts['unknowns']
                       if row.get('target_function_id') and row['kind'] in ENTRY_GAPS}
    # Unknown callback inputs cannot be bounded by the arguments from known
    # callers. Keep every guard arm in that callback and its callees.
    unknown_reachable = reachable_domains({'unknown-entry': unknown_entries}, facts['calls'])
    temporary = {key: [] for key in ('accesses', 'calls', 'unknowns', 'registrations',
                                    'pointer_constraints', 'semantic_calls', 'indirect_accesses')}
    temporary['variables'] = facts['variables']
    temporary['functions'] = list(facts['functions'])
    temporary['build_closure'] = facts.get('build_closure', {})
    temporary['translation_units'] = facts.get('translation_units', [])
    temporary['guard_unknown_entries'] = set(unknown_reachable)
    temporary['pointer_storage'] = [dict(row, location=scoped_location(row['location'], context))
        for row in facts.get('pointer_storage', [])
        for context in sorted(domains.get(row.get('function_id'), ())) or [None]]
    expressions = {'pointer_constraints': ('left', 'right', 'path_conditions'),
                   'semantic_calls': ('expression', 'arguments', 'result', 'path_conditions'),
                   'indirect_accesses': ('location', 'path_conditions')}
    for table, fields in expressions.items():
        for row in facts.get(table, []):
            contexts = sorted(domains.get(row.get('function_id'), ())) or [None]
            for context in contexts:
                temporary[table].append(clone_record(row, context, fields))
    # Guard decisions use a completed may-solution, never an intermediate
    # empty set. Remove only proven-disjoint arms, then recompute to a fixed
    # point. Global storage still participates in every physical context.
    for guard_iteration in range(8):
        solver = ContextSolver(temporary, cfg)
        solver.solve()
        if not temporary.get('points_to_stats', {}).get('complete', False):
            return None
        filtered = {table: [row for row in temporary[table] if not solver.guard_impossible(row)]
                    for table in expressions}
        if all(len(filtered[table]) == len(temporary[table]) for table in expressions):
            break
        temporary = dict(variables=facts['variables'], functions=list(facts['functions']),
                         pointer_storage=temporary['pointer_storage'],
                         build_closure=facts.get('build_closure', {}), translation_units=facts.get('translation_units', []),
                         guard_unknown_entries=set(unknown_reachable),
                         accesses=[], calls=[], unknowns=[], registrations=[], **filtered)
    else:
        return None

    original_calls = defaultdict(list)
    original_accesses = defaultdict(list)
    for call in facts['calls']:
        original_calls[site(call, caller=True)].append(call)
    for access in facts['accesses']:
        if access.get('via_alias') == 'interprocedural points-to':
            original_accesses[site(access)].append(access)

    calls = []
    covered_sites = {site(row) for row in facts.get('semantic_calls', [])}
    for call in temporary['semantic_calls']:
        key, context = site(call), call.get('_context_id')
        covered_sites.add(key)
        allowed = dict(allowed_contexts=[context]) if context is not None else {}
        targets = solver.targets(call)
        for target in sorted(targets):
            source = next((row for row in original_calls[key] if row.get('callee_function_id') == target), {})
            calls.append(dict(source, caller_function_id=call['function_id'], callee_function_id=target,
                callee_name=solver.functions.get(target, {}).get('name', call['name']),
                call_kind='DIRECT' if call.get('target') else 'INDIRECT_RESOLVED',
                file=call['file'], line=call['line'], offset=call['offset'], **allowed))
    for row in facts['calls']:
        if site(row, caller=True) not in covered_sites:
            contexts = domains.get(row.get('caller_function_id'))
            calls.append(dict(row, **(dict(allowed_contexts=sorted(contexts)) if contexts else {})))

    # Direct AST facts retain all physically reachable callers. Only resolved
    # pointer-derived facts need the argument-sensitive replacement above.
    direct = []
    for row in facts['accesses']:
        if row.get('via_alias') != 'interprocedural points-to':
            contexts = domains.get(row.get('function_id'))
            if contexts:
                allowed, excluded = [], []
                for context in sorted(contexts):
                    proof = solver.guard_evidence(clone_record(row, context, ('path_conditions',)))
                    if proof:
                        excluded.extend(proof)
                    else:
                        allowed.append(context)
                direct.append(dict(row, allowed_contexts=allowed,
                                   context_proven_unreachable=not bool(allowed), context_exclusions=excluded))
            else:
                direct.append(dict(row))
    accesses = union_rows(direct + temporary['accesses'], access=True)
    calls = union_rows(calls)
    pruned = []
    for row in facts['unknowns']:
        contexts = domains.get(row.get('function_id'))
        if not row.get('path_conditions') or not contexts:
            continue
        proofs = [solver.guard_evidence(clone_record(row, context, ('path_conditions',)))
                  for context in sorted(contexts)]
        if all(proofs):
            pruned.append(dict(row, context_proven_unreachable=True,
                               context_exclusions=[item for proof in proofs for item in proof],
                               original_issue_digest=digest(row)))
    temporary['context_pruned_uncertainties'] = pruned
    return temporary, accesses, calls


def refine(facts, cfg, contexts, paths):
    """Publish a complete context fixed point, or retain the original solution.

    Call after initial context discovery and before storage canonicalization.
    ``contexts``/``paths`` are seeds only; the caller reruns context_graph once
    after this returns so call chains honor the published allowed_contexts.
    The returned bool states whether a refined model was published. No partial
    refinement is committed if a solver limit or unstable entry graph remains.
    """
    if facts.get('context_pointer_model_applied'):
        return True
    if not contexts or not facts.get('points_to_stats', {}).get('complete', False):
        facts['context_points_to_stats'] = dict(complete=False, reason='Initial pointer/context coverage is incomplete')
        return False
    roots = defaultdict(set)
    for binding in facts.get('context_bindings', []):
        if binding.get('call_depth') == 0:
            roots[binding['context_id']].add(binding['function_id'])
    domains = {function: set(per_context) for function, per_context in paths.items()}
    baseline_registrations = {(reg['function_id'], reg.get('kind'), reg.get('file'), reg.get('offset'))
                              for reg in facts.get('registrations', [])}
    for iteration in range(1, 9):
        result = _pass(facts, cfg, domains)
        if result is None:
            facts['context_points_to_stats'] = dict(complete=False, iterations=iteration,
                reason='Context pointer equations exceeded their explicit limit; original solution retained')
            return False
        temporary, accesses, calls = result
        current_registrations = {(reg['function_id'], reg.get('kind'), reg.get('file'), reg.get('offset'))
                                 for reg in temporary.get('registrations', [])}
        if not current_registrations <= baseline_registrations:
            # Newly resolved asynchronous roots must participate in the next
            # pass. Context discovery uses the same generic configured/vector
            # semantics as the main classifier.
            from .analysis import context_graph
            candidate = copy.copy(facts)
            candidate.update(calls=calls, registrations=temporary['registrations'], unknowns=[])
            _, discovered, _ = context_graph(candidate, cfg)
            for binding in candidate['context_bindings']:
                if binding.get('call_depth') == 0:
                    roots[binding['context_id']].add(binding['function_id'])
            baseline_registrations.update(current_registrations)
            for function, per_context in discovered.items():
                domains.setdefault(function, set()).update(per_context)
            continue
        narrowed = reachable_domains(roots, calls)
        if narrowed != domains:
            domains = narrowed
            continue
        facts['context_insensitive_pointer_model'] = dict(
            accesses=[row for row in facts['accesses'] if row.get('via_alias') == 'interprocedural points-to'],
            calls=[row for row in facts['calls'] if row.get('call_kind') == 'INDIRECT_RESOLVED'],
            stats=facts.get('points_to_stats', {}))
        facts['accesses'], facts['calls'] = accesses, calls
        # Variable-scoped missing facts found by the refined solver are still
        # real gaps; keep them in addition to first-pass coverage evidence.
        recomputed = {site(row) for table in ('indirect_accesses', 'semantic_calls', 'pointer_constraints')
                      for row in facts.get(table, [])}
        pruned = temporary.get('context_pruned_uncertainties', [])
        pruned_ids = {row['original_issue_digest'] for row in pruned}
        retained = [issue for issue in facts['unknowns']
                    if digest(issue) not in pruned_ids and not (site(issue) in recomputed and
                            (issue['kind'] == 'UNRESOLVED_POINTEE'
                             or issue.get('actual_escape') and issue['kind'] in {'ADDRESS_ESCAPE', 'FUNCTION_ADDRESS'}))]
        facts['unknowns'] = union_rows(retained + temporary['unknowns'])
        facts['context_pruned_uncertainties'] = pruned
        facts['address_escapes'] = [issue for issue in facts['unknowns'] if issue.get('actual_escape')]
        facts['context_points_to_stats'] = dict(temporary['points_to_stats'], complete=True,
            iterations=iteration, context_bindings=sum(map(len, domains.values())))
        facts['context_pointer_model_applied'] = True
        return True
    facts['context_points_to_stats'] = dict(complete=False, iterations=8,
        reason='Execution-context fixed point did not stabilize; original solution retained')
    return False
