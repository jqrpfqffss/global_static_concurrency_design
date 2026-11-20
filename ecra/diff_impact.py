"""Three-way accounting of identified comparison objects and causal witnesses."""
from collections import ChainMap, Counter, defaultdict, deque

from .common import digest
from .diff_dependencies import SCHEMA
from .diff_risk import coverage_assessment


IMPACT_SCHEMA = 1
LABELS = dict(DEFINITE='明确影响', UNCERTAIN='待核实', EXCLUDED='可排除')


class _Effect:
    """One complete input/output relation, without its Cartesian expansion."""
    __slots__ = ('entry', 'inputs', 'outputs', 'observed', 'witness', 'complete', 'pending')

    def __init__(self, graph, fid, row, complete, side):
        self.entry = graph.node(('entry', fid))
        self.inputs = defaultdict(list)
        for source in row['inputs']:
            node = graph.node(source['node'])
            reason = ('RETURN_DEPENDENCY' if node[0] == 'return' else
                      'PARAMETER_DEPENDENCY' if node[0] == 'parameter' else
                      'CONTROL_DEPENDENCY' if source.get('dependency_kind') == 'CONTROL' else 'DATA_DEPENDENCY')
            record = graph.input((node, source['certainty'], reason,
                                  tuple(source.get('uncertainty_reasons', ()))))
            self.inputs[node].append(record)
        self.outputs = tuple(graph.output(row) for row in row['outputs'])
        self.observed = tuple(graph.output(row) for row in row['observed'])
        self.witness = dict(row['witness'], side=side)
        self.complete = complete
        self.pending = {}

    def neighbors(self, node, certainty, origins):
        sources = self.inputs.get(node, ())
        entry = node == self.entry
        def mode(source=None):
            return (certainty == 'DEFINITE' and self.complete
                    and (source is None or source[1] == 'DEFINITE'))
        modes = {mode(source) for source in sources}
        if entry:
            modes.add(mode())
        for strong in modes:
            if strong not in self.pending:
                outcomes = {(target, 'DEFINITE' if strong and strength == 'DEFINITE' else 'UNCERTAIN')
                            for target, strength, _ in self.outputs}
                self.pending[strong] = {outcome for outcome in outcomes if (*outcome, False) not in origins}
        # After a transfer, only its skipped self-target can remain. Later
        # sources finish that target once; they do not rescan the whole product.
        active = {strong for strong in modes if any(target != node for target, _ in self.pending[strong])}

        def output_edge(output, source=None):
            target, strength, uncertainty = output
            strong = mode(source)
            pending = self.pending[strong]
            outcome = (target, 'DEFINITE' if strong and strength == 'DEFINITE' else 'UNCERTAIN')
            if target == node or strong not in active or outcome not in pending:
                return
            following = (*outcome, False)
            if following not in origins:
                raw_strength = strength if self.complete and (source is None or source[1] == 'DEFINITE') else 'UNCERTAIN'
                reason = source[2] if source is not None else 'CALL_DEPENDENCY'
                details = sorted(set(source[3] + uncertainty)) if source is not None else list(uncertainty)
                yield target, raw_strength, reason, dict(self.witness, uncertainty_reasons=details)
            # The caller installs the origin before advancing this generator.
            # Never discard an outcome merely because a consumer inspected it.
            if following in origins:
                pending.discard(outcome)

        if active:
            # Preserve the original output-major order, including an entry
            # that also appears among the inputs and mixed-strength duplicates.
            for output in self.outputs:
                if entry:
                    yield from output_edge(output)
                for source in sources:
                    yield from output_edge(output, source)
        if entry:
            for target, strength, uncertainty in self.observed:
                strength = strength if self.complete else 'UNCERTAIN'
                effective = 'DEFINITE' if certainty == strength == 'DEFINITE' else 'UNCERTAIN'
                if target != node and (target, effective, False) not in origins:
                    yield target, strength, 'CALL_DEPENDENCY', dict(self.witness, uncertainty_reasons=list(uncertainty))


class _ImpactGraph:
    """Share repeated descriptors; expand only newly reachable outcomes."""
    def __init__(self):
        self.adjacency = defaultdict(list)
        self.nodes, self.inputs, self.outputs = {}, {}, {}

    def node(self, value):
        value = tuple(value)
        return self.nodes.setdefault(value, value)

    def input(self, value):
        return self.inputs.setdefault(value, value)

    def output(self, row):
        value = (self.node(row['node']), row['certainty'], tuple(row.get('uncertainty_reasons', ())))
        return self.outputs.setdefault(value, value)

    def effect(self, fid, row, complete, side):
        effect = _Effect(self, fid, row, complete, side)
        for node in effect.inputs.keys() | {effect.entry}:
            self.adjacency[node].append(effect)

    def edge(self, source, target, certainty, reason, witness):
        source, target = self.node(source), self.node(target)
        if source != target:
            self.adjacency[source].append((target, certainty, reason, witness))

    def neighbors(self, node, certainty, origins):
        for relation in self.adjacency.get(node, ()):
            if isinstance(relation, _Effect):
                yield from relation.neighbors(node, certainty, origins)
            else:
                yield relation


def dependency_proof(function):
    proof = (function or {}).get('dependencies', {})
    return proof if (proof.get('schema') == SCHEMA
                     and proof.get('source_digest') == function.get('digest')) else {}


def regional_gaps(base, head):
    rows = []
    for side, summary in (('base', base), ('head', head)):
        scope = summary.get('comparison_scope', {})
        rows.extend(dict(side=side, kind='DYNAMIC_PREDEFINED_INPUT', unidentified_objects_possible=True,
                         **region) for region in scope.get('clock_regions', ()))
        for unit in scope.get('units', []):
            if unit.get('parse_status') != 'PARSED':
                rows.append(dict(side=side, kind='EXTRACTION_REGION', **unit,
                    unidentified_objects_possible=True,
                    note='此区域可能存在尚未识别的对象，不计入已识别对象三类数量。'))
        if scope.get('missing_objects'):
            rows.append(dict(side=side, kind='MISSING_BUILD_OBJECTS', objects=scope['missing_objects'],
                             unidentified_objects_possible=True))
        if not scope.get('inventory_known'):
            rows.append(dict(side=side, kind='MISSING_TU_INVENTORY', unidentified_objects_possible=True))
        if scope.get('build_complete') is not True:
            rows.append(dict(side=side, kind='BUILD_INVENTORY_UNPROVEN', unidentified_objects_possible=True))
    return rows


def classify_impacts(base, head, reasons, modified, *, build_changed):
    """Build typed edges; a possible edge never upgrades itself to definite."""
    bv, hv = base['variables'], head['variables']
    all_ids = bv.keys() | hv.keys()
    graph, function_vars = _ImpactGraph(), defaultdict(set)
    definite, uncertain = set(), set()
    evidence, exclusion = defaultdict(list), {}
    queue, origins = deque(), {}
    related_functions = defaultdict(set)
    unresolved_functions = set()

    def mark(sid, certainty, reason, witness=None):
        if sid not in all_ids:
            return
        (definite if certainty == 'DEFINITE' else uncertain).add(sid)
        reasons[sid].add(reason)
        if witness is not None and witness not in evidence[sid]:
            evidence[sid].append(witness)

    def seed(node, certainty, reason, witness):
        node = tuple(node)
        key = (node, certainty, False)
        if key not in origins:
            origins[key] = dict(reason=reason, witness=witness, previous=None)
            queue.append(key)

    def edge(source, target, certainty, reason, witness):
        graph.edge(source, target, certainty, reason, witness)

    for side, summary in (('base', base), ('head', head)):
        for sid, variable in summary['variables'].items():
            for fid in variable['accessors']:
                function_vars[fid].add(sid)
            graph_id = variable.get('graph_id')
            related_functions[sid].update(summary.get('graphs', {}).get(graph_id, {}).get('functions', variable['accessors']))
        callees = defaultdict(list)
        for caller, callee in summary['edges']:
            callees[caller].append(callee)
        for fid, function in summary['functions'].items():
            proof = dependency_proof(function)
            if not proof.get('complete'):
                unresolved_functions.add(fid)
            for row in proof.get('effects', []):
                graph.effect(fid, row, bool(proof.get('complete')), side)
            # Missing/unsupported dependency facts cannot be promoted by a
            # call-graph relationship. Keep the reachable boundary uncertain.
            if not proof.get('complete'):
                for sid in sorted(function_vars[fid]):
                    edge(['entry', fid], ['variable', sid], 'UNCERTAIN', 'FUNCTION_ONLY_DEPENDENCY', dict(function=fid))
                for callee in callees[fid]:
                    edge(['entry', fid], ['entry', callee], 'UNCERTAIN', 'FUNCTION_ONLY_DEPENDENCY', dict(function=fid))

    def effect_groups(proof):
        groups = defaultdict(list)
        for row in proof.get('effects', []):
            key = (row['kind'], tuple(tuple(v['node']) for v in row['outputs']),
                   tuple(tuple(v['node']) for v in row['observed']))
            groups[key].append(row)
        return groups

    localized = set()
    for fid in sorted(modified):
        before = dependency_proof(base['functions'].get(fid))
        after = dependency_proof(head['functions'].get(fid))
        old_groups, new_groups = effect_groups(before), effect_groups(after)
        changed_rows = []
        for key in sorted(old_groups.keys() | new_groups.keys()):
            old, new = old_groups[key], new_groups[key]
            if [r['signature'] for r in old] != [r['signature'] for r in new]:
                # Keep order within one effect destination. A changed literal
                # cannot pull independent statements into this group.
                changed_rows.extend(dict(row, witness=dict(row['witness'], side=side))
                                    for side, rows in (('base', old), ('head', new)) for row in rows)
        complete = all(dependency_proof(summary['functions'].get(fid)).get('complete')
                       for summary in (base, head) if fid in summary['functions'])
        order_only = (not changed_rows and before and after and
            [r['signature'] for r in before['effects']] != [r['signature'] for r in after['effects']])
        if complete and not order_only:
            localized.add(fid)
        else:
            seed(['entry', fid], 'UNCERTAIN', 'FUNCTION_ONLY_DEPENDENCY',
                 dict(function=fid, issues=sorted(set(before.get('issues', []) + after.get('issues', []))),
                      note='只有函数级变化或不完整依赖证据，不能证明全部访问都受影响。'))
            # Return flow may have changed even when its exact expression was
            # not recovered. Only actual consumers receive this uncertainty.
            seed(['return', fid], 'UNCERTAIN', 'FUNCTION_ONLY_DEPENDENCY', dict(function=fid))
        for row in changed_rows:
            for observed in row['observed']:
                certainty = observed['certainty'] if complete else 'UNCERTAIN'
                mark(observed['node'][1], certainty, 'SEMANTIC_IMPACT', dict(kind='CHANGED_EXPRESSION', **row['witness'],
                    uncertainty_reasons=observed.get('uncertainty_reasons', [])))
            for output in row['outputs']:
                seed(output['node'], output['certainty'] if complete else 'UNCERTAIN',
                     'SEMANTIC_IMPACT', dict(kind='CHANGED_EXPRESSION', **row['witness'],
                         uncertainty_reasons=output.get('uncertainty_reasons', [])))

    # Final storage dimensions/context/protection remain independent positive
    # evidence. If the only local evidence is a may-target effect, changes in
    # its derived risk/access labels must not manufacture a definite edge.
    for sid in sorted(reasons):
        why = reasons[sid]
        if 'MATCH_UNCERTAIN' in why:
            mark(sid, 'UNCERTAIN', 'MATCH_UNCERTAIN', dict(kind='OBJECT_IDENTITY_GAP'))
        elif why:
            old_accesses, new_accesses = bv.get(sid, {}).get('impact_accesses', []), hv.get(sid, {}).get('impact_accesses', [])
            strong = lambda rows: [row['sha256'] for row in rows if row['certainty'] == 'DEFINITE']
            weak_access_change = bool(old_accesses != new_accesses and strong(old_accesses) == strong(new_accesses))
            weak_only = (sid in uncertain or weak_access_change) and sid not in definite and 'DIRECT_CHANGED' not in why
            mark(sid, 'UNCERTAIN' if weak_only else 'DEFINITE', 'VERSION_EVIDENCE',
                 dict(kind='VERSION_EVIDENCE', dimensions=sorted(why)))
        if 'DIRECT_CHANGED' in why:
            seed(['variable', sid], 'DEFINITE', 'DIRECT_CHANGED', dict(symbol_id=sid))

    assessments = {}
    for sid in sorted(all_ids):
        assessments[sid] = {side: coverage_assessment(variable, summary.get('comparison_scope', {}))
                           for side, variable, summary in (('base', bv.get(sid), base), ('head', hv.get(sid), head)) if variable}
        for side, assessment in assessments[sid].items():
            extraction_gaps = [gap for gap in assessment['related_gaps']
                               if gap.get('kind') in {'PARSE_FAILED', 'PARTIAL_PARSE_REGION'}]
            if extraction_gaps or assessment['unaccounted_gaps']:
                # Equal observed hashes cannot prove equality inside an
                # unobserved region. Also reach actual value consumers: an
                # internal-linkage destination is not isolated from inputs.
                seed(['variable', sid], 'UNCERTAIN', 'COVERAGE_DEPENDENCY', dict(side=side,
                    extraction_gaps=extraction_gaps, unaccounted_gaps=assessment['unaccounted_gaps']))

    # Physical storage edges never travel through a container. Unknown array
    # indices and missing extents remain possible, even beside an exact edge.
    roots, storage_shapes = defaultdict(set), {}
    bs = ChainMap(bv, base.get('dependency_storage', {}))
    hs = ChainMap(hv, head.get('dependency_storage', {}))
    storage_ids = bs.keys() | hs.keys()
    dependency_storage_changed = False
    for sid in sorted(storage_ids - all_ids):
        if bs.get(sid, {}).get('declaration') != hs.get(sid, {}).get('declaration'):
            dependency_storage_changed = True
            seed(['variable', sid], 'DEFINITE', 'DIRECT_CHANGED', dict(symbol_id=sid, dependency_scope=True))
    for sid in sorted(storage_ids):
        for variable in (bs.get(sid), hs.get(sid)):
            if variable:
                roots[variable['root']].add(sid)
                # Disk-backed records also contain large access/proof payloads.
                # Retain only these immutable fields for pairwise overlap checks;
                # processing base then head preserves the original side preference.
                storage_shapes[sid] = {key: variable.get(key) for key in
                    ('root', 'container', 'array_index', 'offset_bits', 'size_bytes')}
    seeded_variables = {node[1] for node, _, _ in origins if node[0] == 'variable'}

    def storage_edges(sid):
        # Generate overlaps only for reached storage. Constructing all pairs
        # up front makes an unchanged large array quadratic in time/memory.
        a = storage_shapes.get(sid)
        if not a or a.get('container') and sid not in seeded_variables:
            return
        root = a['root']
        for other in sorted(roots[root] - {sid}):
            b = storage_shapes[other]
            if b.get('container'):
                continue
            strength = 'UNCERTAIN'
            ia, ib = a.get('array_index'), b.get('array_index')
            if ia and ib and '*' not in ia + ib:
                if ia != ib:
                    continue
                strength = 'DEFINITE'
            elif a.get('container'):
                strength = 'DEFINITE'
            else:
                lo, ro, ls, rs = a.get('offset_bits'), b.get('offset_bits'), a.get('size_bytes'), b.get('size_bytes')
                if all(type(v) is int and v >= 0 for v in (lo, ro, ls, rs)) and ls and rs:
                    if lo + ls*8 <= ro or ro + rs*8 <= lo:
                        continue
                    strength = 'DEFINITE'
            yield (('variable', other), strength,
                   'PHYSICAL_OVERLAP' if strength == 'DEFINITE' else 'POSSIBLE_OVERLAP',
                   dict(root=root, source=sid, target=other))

    def propagate():
        from itertools import chain
        while queue:
            key = queue.popleft()
            node, certainty, via_storage = key
            cause = origins[key]
            if node[0] == 'variable':
                path, cursor = [], key
                while cursor is not None:
                    record = origins[cursor]
                    path.append(dict(node=list(cursor[0]), certainty=cursor[1],
                                     reason=record['reason'], witness=record['witness']))
                    cursor = record['previous']
                mark(node[1], certainty, cause['reason'], dict(kind='DEPENDENCY_PATH', path=list(reversed(path))))
            neighbors = chain(graph.neighbors(node, certainty, origins), storage_edges(node[1]) if node[0] == 'variable' and not via_storage else ())
            for target, strength, reason, witness in neighbors:
                storage = reason in {'PHYSICAL_OVERLAP', 'POSSIBLE_OVERLAP'}
                if via_storage and storage:
                    continue  # A projected overlap is not a second write.
                effective = 'DEFINITE' if certainty == strength == 'DEFINITE' else 'UNCERTAIN'
                following = (target, effective, storage)
                if following not in origins:
                    origins[following] = dict(reason=reason, witness=witness, previous=key)
                    queue.append(following)

    propagate()

    # No semantic change is itself an explicit equivalence proof, including
    # identical unresolved boundaries on a comment-only scan. Missing proof
    # with a real change, however, defaults to uncertain, never excluded.
    has_change = bool(modified or any(reasons.values()) or build_changed or dependency_storage_changed
                      or base.get('semantics') != head.get('semantics')
                      or base.get('unknowns') != head.get('unknowns'))
    opaque_changed = any(base.get('semantics', {}).get(key) != head.get('semantics', {}).get(key)
                         for key in ('irq_priority_events', 'hardware_contexts', 'address_escapes', 'pointer_targets'))
    exemptions = {}
    for sid in sorted(all_ids):
        old, new = bv.get(sid), hv.get(sid)
        if sid in definite:
            continue
        if sid in uncertain:
            continue
        identical = bool(old and new and old['dimensions'] == new['dimensions'] and old['findings'] == new['findings'])
        private = bool(identical and not build_changed and old.get('private_storage_isolation')
                       and new.get('private_storage_isolation') and not (related_functions[sid] & (modified - localized)))
        gaps = any(value['related_gaps'] or value['unaccounted_gaps'] for value in assessments[sid].values())
        # A fully excluded failed-TU region need not invalidate an independent
        # object. Opaque calls/assembly/missing metadata still have no global
        # non-interference proof for externally visible storage.
        opaque_boundary = any(len(summary.get('unknowns', [])) != len(summary.get('impact_unknowns', []))
            or any(row.get('kind') not in {'PARSE_FAILED', 'PARTIAL_PARSE_REGION'}
                   for row in summary.get('impact_unknowns', [])) for summary in (base, head))
        complete = not (related_functions[sid] & unresolved_functions)
        proof = None
        if identical and not has_change:
            proof = 'UNCHANGED_SEMANTIC_EVIDENCE'
        elif private and not gaps:
            proof = 'PRIVATE_STORAGE_ISOLATION'
            exemptions[(new or old)['symbol_id']] = '未逃逸私有标量，两版直接访问及上下文一致，且无实际依赖路径到达此对象。'
        elif identical and complete and not gaps and not opaque_boundary and not opaque_changed and not build_changed:
            proof = 'COMPLETE_DEPENDENCY_SEPARATION'
        if proof:
            exclusion[sid] = dict(proof=proof, functions=sorted(related_functions[sid]),
                evidence_digest=digest([old['dimensions'], new['dimensions']]),
                note='两侧相关证据一致，已核对依赖闭包和覆盖限制；未发现从变化到该对象的实际或可能依赖。')
            reasons[sid].add('INDEPENDENCE_PROVEN')
        else:
            mark(sid, 'UNCERTAIN', 'CANNOT_EXCLUDE_IMPACT', dict(kind='MISSING_EXCLUSION_PROOF',
                incomplete_functions=sorted(related_functions[sid] & unresolved_functions),
                build_changed=build_changed, global_boundary_changed=opaque_changed,
                opaque_dependency=opaque_boundary))

    # A non-escape proof concerns the destination's storage ownership. It
    # cannot exclude a possible value/control influence from an uncertain
    # external input. Close those remaining possible edges before exclusions.
    for sid in sorted(uncertain - definite):
        seed(['variable', sid], 'UNCERTAIN', 'CANNOT_EXCLUDE_IMPACT', dict(symbol_id=sid))
    propagate()
    for sid in definite | uncertain:
        exclusion.pop(sid, None)
        exemptions.pop((hv.get(sid) or bv[sid])['symbol_id'], None)

    # Object identity uncertainty outranks a causal match across versions.
    for sid in sorted(all_ids):
        if 'MATCH_UNCERTAIN' in reasons[sid]:
            definite.discard(sid)
            uncertain.add(sid)
    categories = {sid: 'DEFINITE' if sid in definite else 'UNCERTAIN' if sid in uncertain else 'EXCLUDED' for sid in all_ids}
    # Containers are audit/aggregation objects only and never a second risk.
    for sid in sorted(all_ids):
        variable = storage_shapes[sid]
        if not variable.get('container') or 'DIRECT_CHANGED' in reasons[sid]:
            continue
        members = [child for child in roots[variable['root']] if child != sid and child in all_ids
                   and not storage_shapes[child].get('container')]
        if members:
            categories[sid] = ('DEFINITE' if any(categories[c] == 'DEFINITE' for c in members) else
                               'UNCERTAIN' if any(categories[c] == 'UNCERTAIN' for c in members) else 'EXCLUDED')
            reasons[sid] = {'CONTAINER_AGGREGATION'}
            evidence[sid] = [dict(kind='CONTAINER_AGGREGATION', member_ids=sorted(members))]
            exclusion.pop(sid, None)
            if categories[sid] == 'EXCLUDED':
                exclusion[sid] = dict(proof='ALL_MEMBERS_EXCLUDED', member_ids=sorted(members))
    counts = Counter(categories[sid] for sid in all_ids if not storage_shapes[sid].get('container'))
    return dict(schema=IMPACT_SCHEMA, categories=categories, evidence=evidence,
        exclusion_proofs=exclusion, coverage=assessments, fallback_exemptions=exemptions,
        counts={key: counts[key] for key in LABELS}, identified_object_count=sum(counts.values()),
        container_count=sum(bool(storage_shapes[sid].get('container')) for sid in all_ids),
        regional_gaps=regional_gaps(base, head))
