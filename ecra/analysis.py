from collections import Counter, defaultdict, deque
import copy
import fnmatch
import itertools
from math import gcd
import re

from .common import digest


TABLES = ("variables", "functions", "accesses", "calls", "unknowns", "protection_events", "registrations", "snapshots",
          "pointer_constraints", "semantic_calls", "indirect_accesses", "irq_priority_events", "control_flow", "pointer_storage",
          "constant_regions", "nvic_programs", "nvic_globals", "nvic_irq_definitions")
CONFLICT_PAIR_INLINE_LIMIT = 4096


def merge(parts):
    from .points_to import resolve_linkage
    parts = resolve_linkage(parts)
    facts = {t: [] for t in TABLES}
    variables, functions = {}, {}
    unique_rows = {t: {} for t in TABLES[2:]}
    for part in parts:
        if part.get('parse_status') == 'FAILED':
            failed_sources = {tu for v in part.get('variables', []) for tu in v.get('translation_units', [])}
            failed_sources.update(f.get('translation_unit') or f.get('file') for f in part.get('functions', []))
            for source in sorted(failed_sources - {None}):
                issue = dict(kind='PARSE_FAILED', file=source, diagnostics=part.get('diagnostics', []))
                unique_rows['unknowns'][digest(issue)] = issue
        for v in part.get("variables", []):
            if part.get('parse_status') == 'FAILED':
                v['parse_status'] = 'FAILED'
            sid = v["symbol_id"]
            if sid not in variables:
                variables[sid] = v
            else:
                old = variables[sid]
                previous_type = old['type']
                compatible_array_declaration = (old.get('is_array') and v.get('is_array')
                    and old.get('array_element_type') == v.get('array_element_type')
                    and (old.get('array_size') is None or v.get('array_size') is None))
                if v.get("parse_status") == "FAILED":
                    old["parse_status"] = "FAILED"
                for field in ("declarations", "definitions", "translation_units"):
                    for item in v[field]:
                        if item not in old[field]:
                            old[field].append(item)
                if not old["definition_file"] and v["definition_file"]:
                    for field, value in v.items():
                        if field not in {'declarations', 'definitions', 'translation_units', 'parse_status'}:
                            old[field] = value
                if previous_type != v["type"] and not compatible_array_declaration:
                    issue = dict(kind="TYPE_VARIANT", symbol_id=sid, types=[previous_type, v["type"]])
                    unique_rows['unknowns'][digest(issue)] = issue
        for f in part.get("functions", []):
            functions[f["function_id"]] = f
        for t in ([part['_table']] if part.get('_table') in TABLES[2:] else
                  () if part.get('_table') else TABLES[2:]):
            for row in part.get(t, []):
                unique_rows[t][digest(row)] = row
    facts["variables"] = sorted(variables.values(), key=lambda x: x["symbol_id"])
    facts["functions"] = sorted(functions.values(), key=lambda x: x["function_id"])
    for t in TABLES[2:]:
        facts[t] = list(unique_rows.pop(t).values())
    regions = defaultdict(list)
    for row in facts['constant_regions']:
        regions[(row['function_id'], row['file'])].append(row)
    facts['constant_pruned_evidence'] = []
    for table in ('accesses', 'calls', 'unknowns', 'protection_events', 'registrations',
                  'pointer_constraints', 'semantic_calls', 'indirect_accesses', 'irq_priority_events'):
        kept = []
        for row in facts[table]:
            owner = row.get('function_id') or row.get('caller_function_id') or row.get('registered_by')
            proof = next((r for r in regions.get((owner, row.get('file')), ())
                          if r['offset'] <= row.get('offset', -1) < r['end_offset']), None)
            if proof is None:
                kept.append(row)
            else:
                facts['constant_pruned_evidence'].append(dict(table=table, evidence=row, proof=proof))
        facts[table] = kept
    return facts


def matches(f, c):
    names = [f["name"], f["qualified_name"], f["function_id"], f["file"] + "::" + f["name"]]
    return (any(n in c.get("functions", []) for n in names)
            or any(fnmatch.fnmatchcase(n, p) for n in names for p in c.get("patterns", []))
            or any(re.fullmatch(p, n) for n in names for p in c.get("regex", [])))


def preemption_relations(facts, contexts, cfg=None):
    from .interrupts import relations
    facts['preemption_relations'] = relations(facts, contexts, cfg or {})
    return facts['preemption_relations']


def context_graph(facts, cfg):
    funcs = {f["function_id"]: f for f in facts["functions"]}
    graph = defaultdict(set)
    for call in facts["calls"]:
        if call["callee_function_id"] in funcs:
            graph[call["caller_function_id"]].add(call["callee_function_id"])
    issues = []
    for edge in cfg["call_edges"]:
        callers = [f for f in funcs.values() if matches(f, {"functions": [edge.get("caller", "")]})]
        callees = [f for f in funcs.values() if matches(f, {"functions": [edge.get("callee", "")]})]
        if len(callers) != 1 or len(callees) != 1:
            issues.append(dict(kind="UNRESOLVED_CONFIG_CALL", edge=edge))
            continue
        a, b = callers[0]["function_id"], callees[0]["function_id"]
        graph[a].add(b)
        facts["calls"].append(dict(caller_function_id=a, callee_function_id=b, callee_name=callees[0]["name"],
                                   call_kind="CONFIGURED", file=callers[0]["file"], line=callers[0]["line"]))
    contexts, roots, matched, disabled = {}, defaultdict(set), set(), set()
    for h in facts.get('hardware_contexts', []):
        contexts[h['id']] = dict(h, discovery='HAL DMA argument contract')
        roots[h['id']].add(h['function_id'])
    for entry in facts.get('vector_entries', []):
        fid = entry['function_id']
        if fid not in funcs:
            continue
        cid = 'vector:' + entry['vector']
        contexts[cid] = dict(entry, id=cid, reentrant=False)
        roots[cid].add(fid)
        matched.add(fid)
    for c in cfg["contexts"]:
        fs = [f for f in funcs.values() if matches(f, c)]
        if not c.get("enabled", True):
            disabled.update(f["function_id"] for f in fs)
            continue
        if not fs:
            issues.append(dict(kind="UNMATCHED_CONTEXT", context_id=c["id"]))
        contexts[c["id"]] = dict(c, discovery="configured", reentrant=c.get("reentrant", False))
        for f in fs:
            roots[c["id"]].add(f["function_id"])
            matched.add(f["function_id"])
    if cfg["analysis"].get("auto_contexts", True):
        for f in funcs.values():
            fid, name = f["function_id"], f["name"]
            if fid in matched or fid in disabled:
                continue
            kind = None
            # Vector handlers have no arguments. HAL_*_IRQHandler helpers,
            # including zero-argument FLASH/SYSTICK dispatchers, inherit their
            # actual callers; inventing
            # roots here creates false IRQ contexts even for task-only calls.
            if not name.startswith('HAL_') and f.get("parameter_count", 0) == 0 and (name.endswith("IRQHandler") or name in {"SysTick_Handler", "PendSV_Handler", "SVC_Handler", "NMI_Handler", "HardFault_Handler", "MemManage_Handler", "BusFault_Handler", "UsageFault_Handler"}):
                kind = "ISR"
            elif name == "main":
                kind = "MAIN"
            if kind:
                cid = "auto:" + name + ":" + digest(fid)[:8]
                contexts[cid] = dict(id=cid, kind=kind, discovery="name_convention")
                roots[cid].add(fid)
        seen_registrations = set()
        for reg in facts["registrations"]:
            fid = reg["function_id"]
            if fid not in funcs:
                issues.append(dict(kind="TASK_ENTRY_WITHOUT_DEFINITION", target_function_id=fid,
                                   file=reg["file"], line=reg["line"]))
                continue
            key = (fid, reg["file"], reg["offset"], reg.get('kind'), reg.get('context_id'),
                   reg.get('may_repeat') if reg.get('configured') else None)
            if (fid in matched and not reg.get('configured')) or fid in disabled or key in seen_registrations:
                continue
            seen_registrations.add(key)
            # FreeRTOS software timers and pended functions run serially in
            # one daemon task. Repeated enqueueing is not concurrent reentry.
            # Include the real kernel task registration when kernel source is
            # present, avoiding a second invented context for the same daemon.
            kernel_timer_task = (funcs[fid]['name'] == 'prvTimerTask'
                and funcs.get(reg.get('registered_by'), {}).get('name') == 'xTimerCreateTimerTask'
                and reg.get('api') in {'xTaskCreate', 'xTaskCreateStatic'})
            if reg.get('kind') in {'TIMER', 'DEFERRED'} or kernel_timer_task:
                cid = 'auto:freertos:timer_daemon'
                contexts.setdefault(cid, dict(id=cid, kind='TASK', discovery='freertos_timer_daemon',
                    reentrant=False, registrations=[], execution_note='FreeRTOS 定时器回调与延后执行函数共享同一个串行守护任务'))
                contexts[cid]['registrations'].append(reg)
                roots[cid].add(fid)
                continue
            kind = reg.get('kind', 'TASK')
            # A custom registration can explicitly group callbacks served by
            # one physical interrupt.  This prevents serial callback dispatch
            # from being incorrectly modeled as separate concurrent ISRs.
            cid = reg.get('context_id')
            if cid:
                existing = contexts.setdefault(cid, dict(id=cid, kind=kind, discovery='registered_entry',
                    reentrant=reg.get('may_repeat', kind == 'TASK'), registrations=[]))
                if existing['kind'] != kind:
                    issues.append(dict(kind='REGISTERED_CONTEXT_KIND_CONFLICT', context_id=cid, registration=reg))
                    continue
                existing.setdefault('registrations', []).append(reg)
                existing['reentrant'] = existing.get('reentrant', False) or reg.get('may_repeat', kind in {'TASK', 'CALLBACK'})
            else:
                ordinal = sum(key[0] == fid and key[1] == reg['file'] for key in seen_registrations)
                cid = "auto:" + kind.lower() + ":" + funcs[fid]["name"] + ":" + digest([fid, reg["file"], ordinal])[:12]
                contexts[cid] = dict(id=cid, kind=kind, discovery="task_registration", registration=reg,
                                     reentrant=reg.get("may_repeat", kind == 'TASK'))
            roots[cid].add(fid)
    from .physical import normalize_contexts
    contexts, roots = normalize_contexts(contexts, roots, graph, funcs, cfg, facts)
    from .call_graph import edge_context_graph, represent_paths
    context_graphs = edge_context_graph(graph, facts['calls'], contexts)
    bindings, paths = [], defaultdict(dict)
    for cid, entries in roots.items():
        queue = deque((entry, [entry]) for entry in sorted(entries))
        while queue:
            fid, path = queue.popleft()
            if cid in paths[fid]:
                continue
            paths[fid][cid] = path
            bindings.append(dict(function_id=fid, context_id=cid, binding_source=contexts[cid]["discovery"],
                                 path=path, call_depth=len(path) - 1))
            for callee in sorted(context_graphs[cid].get(fid, ())):
                queue.append((callee, path + [callee]))
    # Complete edge/root storage is linear in the graph. Small graphs keep
    # their historical explicit paths; large graphs mark those lists as
    # shortest witnesses, while every edge remains available for proof/review.
    all_paths, graph_evidence = represent_paths(context_graphs, roots, paths, cfg)
    # Iterative DFS exposes cycles without infinite context propagation or Python stack limits.
    colors, cycles = {}, set()
    for start in funcs:
        if colors.get(start):
            continue
        stack = [(start, iter(sorted(graph[start])))]
        colors[start] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                colors[node] = 2
                stack.pop()
            elif colors.get(nxt) == 1:
                cycles.add((node, nxt))
            elif not colors.get(nxt):
                colors[nxt] = 1
                stack.append((nxt, iter(sorted(graph[nxt]))))
    facts["context_bindings"] = bindings
    facts["contexts"] = list(contexts.values())
    facts["recursive_edges"] = [list(e) for e in sorted(cycles)]
    facts["all_call_paths"] = all_paths
    facts['context_call_graph'] = graph_evidence
    facts["unknowns"].extend(issues)
    return contexts, paths, facts["all_call_paths"]


def protection_assessment(accesses, events, contexts, facts, cfg, *, index=None):
    from .protection import assess
    return assess(accesses, events, contexts, facts, cfg, index=index)


def canonical_member_path(path):
    """Normalize extractor and points-to field spellings to one dotted path."""
    path = (path or '').strip().replace('\\', '/')
    if not path:
        return ''
    pieces = []
    for part in path.replace('/', '.').split('.'):
        if not part:
            continue
        if re.fullmatch(r'\[(?:\d+|\*|)\]', part) and pieces:
            pieces[-1] += part.replace('[]', '[*]')
        else:
            pieces.append(part)
    return '.'.join(pieces)


def member_symbol_id(root_symbol_id, field_path):
    return root_symbol_id + '::member::' + field_path


def canonicalize_member_resources(facts):
    """Promote record fields to independent concurrency-analysis resources.

    Extraction intentionally records the declaration which owns the storage.
    This pass turns a non-empty record ``access_path`` into a stable canonical
    member resource, while retaining the root as a UI-only container.  A
    whole-object access remains an explicit root fact and is copied as an
    inherited effect to every concrete descendant, so it cannot disappear from
    a member's risk analysis.
    """
    if facts.get('member_resources_canonicalized'):
        return
    roots = {v['symbol_id']: v for v in facts['variables']}
    records = {sid: v for sid, v in roots.items() if v.get('is_struct')}
    if not records:
        facts['member_resources_canonicalized'] = True
        return

    children_by_root = defaultdict(list)
    descendants = defaultdict(list)
    member_by_key = {}
    additions = []
    for root_sid, root in records.items():
        root['resource_kind'] = 'STRUCT_CONTAINER'
        root['canonical_path'] = root['qualified_name']
        definitions = {canonical_member_path(item.get('field_path')): item
                       for item in root.get('member_definitions', [])
                       if canonical_member_path(item.get('field_path'))}
        for field_path, field in sorted(definitions.items()):
            sid = member_symbol_id(root_sid, field_path)
            resource = dict(root)
            offset_bits = field.get('offset_bits')
            root_alignment = root.get('alignment_bytes')
            guaranteed_alignment = None
            if (isinstance(root_alignment, int) and root_alignment > 0
                    and isinstance(offset_bits, int) and offset_bits >= 0 and offset_bits % 8 == 0):
                guaranteed_alignment = gcd(root_alignment, offset_bits // 8)
            resource.update(symbol_id=sid, name=field.get('name') or field_path.rsplit('.', 1)[-1],
                            qualified_name=root['qualified_name'] + '.' + field_path,
                            kind='STRUCT_MEMBER', scope='member',
                            root_symbol_id=root_sid, root_symbol=root['qualified_name'],
                            field_path=field_path,
                            canonical_path=root['qualified_name'] + '.' + field_path,
                            resource_kind='STRUCT_MEMBER_CONTAINER' if field.get('is_struct') else 'STRUCT_MEMBER',
                            type=field.get('type') or root.get('type'),
                            size_bytes=field.get('size_bytes'), alignment_bytes=guaranteed_alignment,
                            declared_alignment_bytes=field.get('alignment_bytes'),
                            root_alignment_bytes=root_alignment,
                            is_const=bool(root.get('is_const') or field.get('is_const')),
                            is_volatile=bool(root.get('is_volatile') or field.get('is_volatile')),
                            is_atomic=bool(field.get('is_atomic')),
                            is_struct=bool(field.get('is_struct')),
                            is_bitfield_container=bool(field.get('is_bitfield')),
                            overlap_groups=field.get('union_groups', []), offset_bits=offset_bits,
                            member_definitions=[])
            additions.append(resource)
            member_by_key[(root_sid, field_path)] = resource
            children_by_root[root_sid].append(sid)
        for field_path, resource in [(p, member_by_key[(root_sid, p)]) for p in definitions]:
            if resource['resource_kind'] == 'STRUCT_MEMBER':
                descendants[(root_sid, field_path)] = [resource['symbol_id']]
        for field_path in definitions:
            descendants[(root_sid, field_path)] = [member_by_key[(root_sid, child)]['symbol_id']
                                                   for child in definitions
                                                   if child == field_path or child.startswith(field_path + '.') or child.startswith(field_path + '[')
                                                   if member_by_key[(root_sid, child)]['resource_kind'] == 'STRUCT_MEMBER']
        root['member_symbol_ids'] = children_by_root[root_sid]

    member_by_id = {resource['symbol_id']: resource for resource in additions}
    leaves_by_root = {root_sid: [sid for sid in children
                     if member_by_id[sid]['resource_kind'] == 'STRUCT_MEMBER']
                      for root_sid, children in children_by_root.items()}
    generated = []
    for access in facts['accesses']:
        if access.get('array_source_access'):
            continue
        root = records.get(access['symbol_id'])
        if root is None:
            access.setdefault('root_symbol_id', access['symbol_id'])
            access.setdefault('canonical_path', root_name(roots.get(access['symbol_id']), access['symbol_id']))
            continue
        original_sid = access['symbol_id']
        field_path = canonical_member_path(access.get('access_path'))
        access['root_symbol_id'] = original_sid
        access['root_symbol'] = root['qualified_name']
        if field_path and (original_sid, field_path) in member_by_key:
            target = member_by_key[(original_sid, field_path)]
            access.update(symbol_id=target['symbol_id'], field_path=field_path,
                          canonical_path=target['canonical_path'])
            if target['resource_kind'] == 'STRUCT_MEMBER_CONTAINER':
                access['access_scope'] = 'WHOLE_MEMBER_OBJECT_ACCESS'
                inherited_targets = descendants[(original_sid, field_path)]
            else:
                access['access_scope'] = 'MEMBER_ACCESS'
                inherited_targets = []
        else:
            access.update(canonical_path=root['qualified_name'], access_scope='WHOLE_OBJECT_ACCESS')
            inherited_targets = descendants[(original_sid, '')] = leaves_by_root[original_sid]
        if inherited_targets and access['access_kind'] in {'READ', 'WRITE', 'RMW', 'ADDRESS_TAKEN'}:
            for target_sid in inherited_targets:
                target = member_by_id[target_sid]
                # The large call-chain/protection payload is immutable after
                # context recovery. Share it across inherited member facts;
                # later passes assign per-access top-level fields instead of
                # mutating those nested witnesses.
                inherited = dict(access)
                inherited.update(symbol_id=target_sid, root_symbol_id=original_sid,
                                 root_symbol=root['qualified_name'], field_path=target['field_path'],
                                 canonical_path=target['canonical_path'],
                                 access_scope='INHERITED_WHOLE_OBJECT_ACCESS',
                                 inherited_from_access_id=access.get('access_id'),
                                 inherited_from_canonical_path=access['canonical_path'])
                inherited['access_id'] = 'A-' + digest([
                    access['access_id'], target_sid, 'INHERITED_WHOLE_OBJECT_ACCESS'])[:20]
                generated.append(inherited)

    facts['variables'].extend(additions)
    facts['variables'].sort(key=lambda row: row['symbol_id'])
    facts['accesses'].extend(generated)
    # A root-level uncertainty (address escape, missing source, DMA, ...) can
    # affect each member.  Preserve the original fact and add member-scoped
    # inherited evidence; this prevents a field from being marked safe merely
    # because the uncertainty was attached before canonicalization.
    inherited_unknowns = []
    for issue in facts['unknowns']:
        root_sid = issue.get('symbol_id')
        if root_sid not in records:
            continue
        for target_sid in leaves_by_root[root_sid]:
            target = member_by_id[target_sid]
            issue_path = canonical_member_path(issue.get('access_path'))
            from .storage import path_may_cover
            if issue_path and issue_path not in {'static_initializer'} and not path_may_cover(issue_path, target['field_path']):
                continue
            clone = dict(issue, symbol_id=target_sid, root_symbol_id=root_sid,
                         canonical_path=target['canonical_path'], inherited_object_uncertainty=True)
            inherited_unknowns.append(clone)
    facts['unknowns'].extend(inherited_unknowns)
    # Original IDs are already stable source-site identities. Re-numbering all
    # rows here used to leave inherited_from_access_id pointing at an ID that
    # no longer existed. Derived member effects use the source ID and member
    # identity above, so unrelated access ordering cannot change their IDs.
    facts['struct_containers'] = [v for v in facts['variables'] if v.get('resource_kind') == 'STRUCT_CONTAINER']
    facts['member_resources_canonicalized'] = True


def root_name(variable, fallback):
    return variable.get('qualified_name', fallback) if variable else fallback


def all_resolved_routes(access):
    complete = access.get('all_call_chains')
    if complete is None:
        complete = {cid: [path] for cid, path in access.get('call_chains', {}).items()}
    for context_id, routes in complete.items():
        for route in routes or []:
            yield context_id, route


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
    from .json_rows import RecordDicts
    participant_records = RecordDicts(maxsize=1)
    pair_records = RecordDicts(maxsize=2)
    def pair_record(**values):
        result = pair_records(tuple(values))
        for field, value in values.items():
            result[field] = value
        return result
    participant_keys = ('instance_id', 'context_id', 'access_id', 'access_kind',
                        'function_id', 'file', 'line', 'canonical_path',
                        'call_path_count', 'access_scope', 'inherited_from_canonical_path',
                        'call_path_count_kind')
    relation_by_contexts = {tuple(sorted(row['contexts'])): row for row in relations}
    instances = {}
    for access in accesses:
        if access_role(access.get('access_kind')) is None:
            continue
        for context_id, route in all_resolved_routes(access):
            key = (access.get('access_id'), context_id)
            instance = instances.get(key)
            if instance is None:
                # Defaults to setdefault are evaluated even on a hit. Keep
                # the first record exactly, without rebuilding it per route.
                instance = participant_records(participant_keys)
                # Insert individually: dict.update's empty-dict fast path can
                # discard CPython's split shared-key layout.
                for field, value in zip(participant_keys, (
                    'CI-' + digest(key)[:20], context_id, access.get('access_id'), access['access_kind'],
                    access['function_id'], access.get('file'), access.get('line'),
                    access.get('canonical_path'), 0, access.get('access_scope', 'MEMBER_ACCESS'),
                    access.get('inherited_from_canonical_path'))):
                    instance[field] = value
                instances[key] = instance
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
        selectors = {}
        def access_ids(cid):
            if cid not in selectors:
                _, writes, reads = grouped[cid]
                selectors[cid] = (sorted({row['access_id'] for row in reads}),
                                  sorted({row['access_id'] for row in writes}))
            return selectors[cid]
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
                # These complete selectors are read-only evidence. Reuse the
                # same context's lists instead of retaining them per pair.
                left_ids, right_ids = access_ids(left_cid), access_ids(right_cid)
                pairs.append(pair_record(
                    conflict_id='C-' + digest([left['instance_id'], right['instance_id'],
                                               left_cid, right_cid, 'CONTEXT_ACCESS_PRODUCT'])[:16],
                    representation='CONTEXT_ACCESS_PRODUCT',
                    access_reference='variable.accesses',
                    pair_generation=('COMBINATIONS_WITH_REPLACEMENT' if left_cid == right_cid
                                     else 'CROSS_PRODUCT'),
                    pair_rule='AT_LEAST_ONE_WRITE', pair_count=count,
                    participant_a_read_access_ids=left_ids[0],
                    participant_a_write_access_ids=left_ids[1],
                    participant_b_read_access_ids=right_ids[0],
                    participant_b_write_access_ids=right_ids[1],
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
            pairs.append(pair_record(conflict_id='C-' + digest([left['instance_id'], right['instance_id']])[:16],
                              participant_a=left, participant_b=right, relation=relation,
                              mhp=mhp, may_concurrent=possible, has_write_conflict=has_write, status=state,
                              path_combination_count=left['call_path_count'] * right['call_path_count'],
                              path_combination_count_kind=('EXACT_PATH_PRODUCT'
                                  if left['call_path_count_kind'] == right['call_path_count_kind'] == 'EXACT_PATH_COUNT'
                                  else 'WITNESS_PRODUCT')))
    return sorted(pairs, key=lambda pair: (not pair['may_concurrent'], not pair['has_write_conflict'],
                                           pair['participant_a']['context_id'], pair['participant_b']['context_id'],
                                           pair['conflict_id']))


def multi_field_coherence(variables, accesses_by_symbol, contexts, calls=(), bindings=()):
    """Find source-backed cross-field transactions on one storage root.

    Field sensitivity must not erase a protocol in which one executor publishes
    several fields and another consumes the same set.  Requiring at least two
    common fields in one writer function and one reader function avoids using
    names or project-specific allow/deny lists as a substitute for evidence.
    """
    from .evidence import access_role
    callers = defaultdict(set)
    for call in calls:
        if call.get('callee_function_id'):
            callers[call['callee_function_id']].add(call['caller_function_id'])
    caller_contexts = defaultdict(set)
    for binding in bindings:
        caller_contexts[binding['function_id']].add(binding['context_id'])
    def transactions(items, sites):
        # Equal physical domains and member sets have exactly the same
        # cross-field predicate for every function pair. Keep the full source
        # sets and count their Cartesian product without visiting each pair.
        buckets = {}
        for key, members in items.items():
            if len(members) < 2:
                continue
            signature = (key[0], frozenset(members))
            if signature not in buckets:
                buckets[signature] = dict(physical=key[0], members=signature[1],
                                         functions=set(), sites=defaultdict(set))
            bucket = buckets[signature]
            bucket['functions'].add(key[1])
            for sid in members:
                bucket['sites'][sid].update(sites[key][sid])
        for bucket in buckets.values():
            bucket['first'] = min(bucket['functions'])
        return buckets.values()
    roots = defaultdict(list)
    for variable in variables:
        if variable.get('root_symbol_id'):
            roots[variable['root_symbol_id']].append(variable)
    result = defaultdict(list)
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
        write_groups = tuple(transactions(writes, sites))
        read_groups = tuple(transactions(reads, sites))
        grouped = {}
        del writes, reads, sites
        for wi, writer in enumerate(write_groups):
            for ri, reader in enumerate(read_groups):
                if writer['physical'] == reader['physical']:
                    continue
                common = writer['members'] & reader['members']
                if len(common) < 2:
                    continue
                # A large cooperative call graph can have thousands of writer
                # and reader functions for the same physical context/member
                # set.  The cross product is an audit presentation detail, not
                # a new coherence fact.  Keep one source-backed group and its
                # exact pair count, functions, accesses and one concrete pair.
                key = (root_id, writer['physical'], reader['physical'], tuple(sorted(common)))
                evidence = grouped.get(key)
                if evidence is None:
                    evidence = grouped[key] = dict(kind='MULTI_FIELD_COHERENCE',
                        coherence_id='MC-' + digest(key)[:20],
                        root_symbol_id=root_id, writer_physical_context=writer['physical'],
                        reader_physical_context=reader['physical'], member_symbol_ids=list(key[3]),
                        writer_groups=set(), reader_groups=set(),
                        function_pair_count=0,
                        witness=dict(writer_function_id=writer['first'], reader_function_id=reader['first']),
                        reason='同一写入函数发布多个成员，另一物理上下文中的同一调用过程直接或经一层访问器读取这些成员。')
                evidence['function_pair_count'] += len(writer['functions']) * len(reader['functions'])
                evidence['writer_groups'].add(wi)
                evidence['reader_groups'].add(ri)
                candidate = (writer['first'], reader['first'])
                previous = (evidence['witness']['writer_function_id'],
                            evidence['witness']['reader_function_id'])
                if candidate < previous:
                    evidence['witness'] = dict(writer_function_id=writer['first'],
                                               reader_function_id=reader['first'])
        # Collect group references first. Repeated physical-context pairs can
        # otherwise hold millions of copies of identical complete source sets.
        # Materialized lists are shared read-only; JSON still contains every ID.
        def materialize(groups, indices, members, function_pool, access_pool):
            indices = frozenset(indices)
            if indices not in function_pool:
                function_pool[indices] = sorted({fid for i in indices for fid in groups[i]['functions']})
            key = (indices, tuple(members))
            if key not in access_pool:
                access_pool[key] = sorted({ident for i in indices for sid in members
                                          for ident in groups[i]['sites'][sid]})
            return function_pool[indices], access_pool[key]

        writer_functions, reader_functions, writer_sites, reader_sites = {}, {}, {}, {}
        for evidence in grouped.values():
            fields = evidence['member_symbol_ids']
            evidence['writer_function_ids'], evidence['writer_access_ids'] = materialize(
                write_groups, evidence.pop('writer_groups'), fields, writer_functions, writer_sites)
            evidence['reader_function_ids'], evidence['reader_access_ids'] = materialize(
                read_groups, evidence.pop('reader_groups'), fields, reader_functions, reader_sites)
            for sid in fields:
                result[sid].append(evidence)
    return {sid: sorted(rows, key=lambda row: (
                row['root_symbol_id'], row['writer_physical_context'],
                row['reader_physical_context'], row['member_symbol_ids']))
            for sid, rows in result.items()}


def validate_member_fact_consistency(facts):
    """Fail closed if member aggregates or complete-path counts were truncated."""
    access_by_symbol = defaultdict(list)
    for access in facts['accesses']:
        access_by_symbol[access['symbol_id']].append(access)
    for variable in facts['variables']:
        if variable.get('resource_kind') != 'STRUCT_MEMBER':
            continue
        accesses = variable.get('accesses', [])
        if {a['access_id'] for a in accesses} != {a['access_id'] for a in access_by_symbol[variable['symbol_id']]}:
            raise ValueError('成员访问聚合校验失败：' + variable['qualified_name'])
        expected_accesses = len(accesses)
        expected_paths = sum(1 for access in accesses for _ in all_resolved_routes(access))
        if variable.get('access_count') != expected_accesses or variable.get('resolved_call_path_count') != expected_paths:
            raise ValueError('成员调用链计数校验失败：' + variable['qualified_name'])


def compact_conflict_pair_storage(records):
    """Losslessly compact legacy per-route conflict rows during report refresh.

    Earlier facts may contain one pair for every route-product.  Merge those
    rows by the stable access/context participants and retain only their route
    counts.  The concrete routes remain in the referenced access facts, so the
    HTML link can still expand all of them exactly once.
    """
    for record in records:
        pairs = record.get('conflict_pairs', [])
        if not any('call_paths' in pair.get('participant_a', {}) or 'call_paths' in pair.get('participant_b', {})
                   for pair in pairs):
            continue
        grouped = {}
        for pair in pairs:
            left, right = pair['participant_a'], pair['participant_b']
            key = (left.get('access_id'), left.get('context_id'), right.get('access_id'), right.get('context_id'))
            target = grouped.setdefault(key, dict(pair, participant_a={key: value for key, value in left.items()
                                                                        if key not in {'call_paths', 'call_path'}},
                                                 participant_b={key: value for key, value in right.items()
                                                                if key not in {'call_paths', 'call_path'}},
                                                 _left_paths=set(), _right_paths=set()))
            target['_left_paths'].update(tuple(path) for path in left.get('call_paths', [left.get('call_path', [])]))
            target['_right_paths'].update(tuple(path) for path in right.get('call_paths', [right.get('call_path', [])]))
        compacted = []
        for pair in grouped.values():
            left_count, right_count = len(pair.pop('_left_paths')), len(pair.pop('_right_paths'))
            pair['participant_a']['call_path_count'] = left_count
            pair['participant_b']['call_path_count'] = right_count
            pair['path_combination_count'] = left_count * right_count
            compacted.append(pair)
        record['conflict_pairs'] = sorted(compacted, key=lambda pair: (
            not pair.get('may_concurrent'), not pair.get('has_write_conflict'), pair['conflict_id']))


def analyze(facts, cfg, coverage, root=None, source_reader=None):
    if any(u['kind'] in {'SOURCE_CHANGED_DURING_SCAN', 'HEADER_CHANGED_DURING_SCAN'} for u in facts['unknowns']):
        raise ValueError('源码在扫描期间发生变化；无法对不一致快照作安全证明，请重新扫描。')
    from .scan_diagnostics import start_stage
    from pathlib import Path
    project_root = Path(root or coverage.get('project_root', Path.cwd()))
    read_source = source_reader or Path.read_text
    from .missing_source import preprocess_failed_units, complete_identifiers
    preprocess_failed_units(facts)
    # Assembly startup/vector references are possible entries, not C callers.
    # Match whole identifiers conservatively across every branch. Macro/include
    # expansion is not implemented, so those sources retain an explicit gap.
    symbols_by_name = defaultdict(list)
    functions_by_name = defaultdict(list)
    for v in facts['variables']:
        if v.get('linkage') == 'EXTERNAL':
            symbols_by_name[v['name']].append(v['symbol_id'])
    for f in facts['functions']:
        if f.get('linkage') == 'EXTERNAL':
            functions_by_name[f['name']].append(f['function_id'])
    for file in coverage.get('assembly_sources', []):
        try:
            source = read_source(project_root / file,encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            facts['unknowns'].append(dict(kind='ASSEMBLY_SOURCE_REVIEW', file=file, message=str(exc)))
            continue
        if re.search(r'^\s*(?:\.macro\b|#\s*include\b)|##', source, re.M):
            facts['unknowns'].append(dict(kind='ASSEMBLY_SOURCE_REVIEW', file=file,
                message='汇编宏或包含文件尚未展开，不能证明入口/变量访问完整'))
        from .vectors import recover_assembly_vectors, recover_assembly_functions
        assembly_functions, assembly_calls = recover_assembly_functions(source, file, facts['functions'])
        facts['functions'].extend(assembly_functions)
        facts['calls'].extend(assembly_calls)
        for function in assembly_functions:
            functions_by_name[function['name']].append(function['function_id'])
        vector_entries, vector_gaps = recover_assembly_vectors(source, file, functions_by_name)
        facts.setdefault('assembly_vector_entries', []).extend(vector_entries)
        facts['unknowns'].extend(vector_gaps)
        # Comments describe startup behavior; they are not assembly references
        # or callers. Preserve line numbers while removing block/line comments.
        reference_source = re.sub(r'/\*.*?\*/', lambda m: '\n' * m[0].count('\n'), source, flags=re.S)
        for line, text in enumerate(reference_source.splitlines(), 1):
            text = re.split(r'//|\s@', text, maxsplit=1)[0]
            for name in sorted(set(re.findall(r'[A-Za-z_][A-Za-z_0-9]*', text))):
                for sid in symbols_by_name.get(name, ()):
                    facts['unknowns'].append(dict(kind='ASSEMBLY_SYMBOL_REFERENCE', symbol_id=sid,
                        file=file, line=line, source_text=text))
                for fid in functions_by_name.get(name, ()):
                    facts['unknowns'].append(dict(kind='ASSEMBLY_FUNCTION_REFERENCE', target_function_id=fid,
                        file=file, line=line, source_text=text))
    from .points_to import enrich
    facts['build_closure'] = coverage.get('build_closure', {})
    from .solver_reachability import prepare as prepare_pointer_solver_reachability
    prepare_pointer_solver_reachability(facts, cfg, coverage)
    start_stage('跨翻译单元指针与函数指针求解')
    enrich(facts, cfg)
    if any(u['kind'] == 'POINTS_TO_LIMIT' for u in facts['unknowns']):
        raise ValueError('POINTS_TO_LIMIT：别名求解未收敛，扫描失败；不对截断的访问集合生成安全结论。')
    from .vectors import recover_vector_entries, resolve_assembly_references
    recover_vector_entries(facts)
    resolve_assembly_references(facts)
    from .nonlocal_jumps import recover_nonlocal_jumps
    recover_nonlocal_jumps(facts)
    # Missing-source lexical references are candidates, never definite READ/
    # WRITE facts. Keep their file/line and bind them only to named variables.
    missing_files = set()
    missing_files.update(u.get('file') for u in facts['unknowns'] if u['kind']=='PARSE_FAILED' and u.get('file'))
    for file in sorted(missing_files):
        names = complete_identifiers(facts, file)
        text = ''
        if names is None:
            try:
                text = read_source(project_root / file,encoding='utf-8',errors='replace')
            except OSError:
                continue
            text = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"',
                          lambda m: '\n' * m[0].count('\n'), text, flags=re.S)
            names = set(re.findall(r'\b[A-Za-z_]\w*\b', text))
        for f in facts['functions']:
            if f['name'] in names and (f.get('linkage')=='EXTERNAL' or f['file']==file):
                facts['unknowns'].append(dict(kind='MISSING_SOURCE_CALLER', target_function_id=f['function_id'],
                    file=file, relation='possible_function_reference',
                    hint='未完整分析源码引用此函数，可能引入额外入口；补齐该文件后恢复调用边。'))
        for v in facts['variables']:
            if v['name'] in names and (v.get('linkage')=='EXTERNAL' or file in v.get('translation_units', [])):
                facts['unknowns'].append(dict(kind='SOURCE_NOT_IN_DATABASE' if file in coverage.get('unlisted_sources', []) else 'PARSE_FAILED',
                    symbol_id=v['symbol_id'], file=file, relation='possible_source_reference',
                    line=next((i for i,s in enumerate(text.splitlines(),1) if re.search(r'\b'+re.escape(v['name'])+r'\b',s)),None),
                    hint='未完整分析的源码引用了该变量；补齐编译数据库/解析参数后恢复访问。'))
    # Refine invocation-local pointer state by physical execution domain while
    # storage is still canonical at the root level. Global/static locations
    # remain shared, including foreground registration consumed by an IRQ.
    from .context_points import refine as refine_context_pointers
    seed_contexts, seed_paths, _ = context_graph(facts, cfg)
    start_stage('执行上下文指针与调用图分析')
    refine_context_pointers(facts, cfg, seed_contexts, seed_paths)
    # Pointer solving and missing-source checks intentionally work with storage
    # roots.  Only now promote record accesses to canonical member resources so
    # no field is confused with a similarly named identifier in unparsed code.
    from .storage import canonicalize_arrays, expand_member_arrays, propagate_overlapping_members
    start_stage('结构体字段、数组与重叠存储分析')
    canonicalize_arrays(facts)
    expand_member_arrays(facts)
    canonicalize_member_resources(facts)
    propagate_overlapping_members(facts)
    start_stage('调用图上下文恢复')
    known = {f['function_id'] for f in facts['functions']}
    summarized = {'memcpy', 'memmove', 'memset', 'memcmp', 'xTaskCreate', 'xTaskCreateStatic',
                  'osThreadNew', 'xTaskCreatePinnedToCore', '__disable_irq', '__enable_irq',
                  '__get_PRIMASK', '__set_PRIMASK', '__get_BASEPRI', '__set_BASEPRI',
                  '__set_BASEPRI_MAX', '__disable_fault_irq', '__enable_fault_irq'}
    from .protection import NEUTRAL
    summarized.update(NEUTRAL)
    summarized.update(s[k] for s in cfg.get('critical_sections', []) for k in ('enter','exit','save','restore') if k in s)
    external_sites = {(u.get('function_id'), u.get('file'), u.get('line'), u.get('callee'))
                      for u in facts['unknowns'] if u['kind'] == 'EXTERNAL_CALLEE'}
    for call in facts['calls']:
        site = (call['caller_function_id'], call['file'], call['line'], call.get('callee_name'))
        if (call['call_kind'] in {'DIRECT', 'INDIRECT_RESOLVED'} and call['callee_function_id'] not in known
                and call.get('callee_name') not in summarized and site not in external_sites):
            facts['unknowns'].append(dict(kind='EXTERNAL_CALLEE', function_id=site[0],
                file=site[1], line=site[2], callee=site[3]))
            external_sites.add(site)
    contexts, paths, all_call_paths = context_graph(facts, cfg)
    coverage['call_graph_representation'] = dict(
        representation=facts['context_call_graph']['representation'], complete=True,
        path_lists_complete=facts['context_call_graph']['path_lists_complete'],
        evidence='facts.json: context_call_graph, call_graph_slices, calls',
        note=facts['context_call_graph']['note'])
    from .nvic import recover as recover_nvic
    start_stage('NVIC 优先级与抢占关系分析')
    recover_nvic(facts, cfg)
    relations = preemption_relations(facts, contexts, cfg)
    start_stage('可达性与不完整证据关联')
    facts['assembly_references'] = facts.get('resolved_assembly_references', []) + [
        u for u in facts['unknowns'] if u['kind'] in
        {'ASSEMBLY_FUNCTION_REFERENCE', 'ASSEMBLY_SYMBOL_REFERENCE'}]
    # Establish reachability before scope filtering: a dependency can supply an
    # entry into a target function. Address-taken functions and attributed entry
    # points are possible roots even when no ordinary caller is present.
    graph = defaultdict(set)
    for call in facts['calls']:
        graph[call['caller_function_id']].add(call.get('callee_function_id'))
    failed_files = {u.get('file') for u in facts['unknowns'] if u['kind'] == 'PARSE_FAILED'}
    possible = set(paths)
    for issue in facts['unknowns'] + facts.get('resolved_pointer_facts', []):
        target = issue.get('target_function_id')
        if not target:
            continue
        owner = issue.get('function_id')
        if owner in known:
            graph[owner].add(target)
        else:
            possible.add(target)
    # libclang reports both constructor and always_inline as UNEXPOSED_ATTR.
    # Inspect the attribute's spelling when available; older saved extractions
    # can omit a header-inline root only when final link artifacts prove that
    # no body was emitted.  Calls and registrations remain independent roots.
    from .linker_symbols import linked_symbol_names
    linked_names = linked_symbol_names(coverage.get('build_closure', {}), project_root)
    non_entry_attributes = {'UNEXPOSED_ATTR', 'ALWAYS_INLINE_ATTR', 'NO_INLINE_ATTR',
                            'NORETURN_ATTR', 'PURE_ATTR', 'CONST_ATTR', 'HOT_ATTR', 'COLD_ATTR'}
    from .solver_reachability import BENIGN_ATTRIBUTE_WORDS
    non_entry_spellings = BENIGN_ATTRIBUTE_WORDS
    def has_entry_attribute(function):
        attributes = function.get('entry_attributes', [])
        spellings = function.get('attribute_spellings')
        for index, kind in enumerate(attributes):
            if kind != 'UNEXPOSED_ATTR':
                if kind not in non_entry_attributes:
                    return True
                continue
            # The final ELF is stronger than libclang's opaque attribute
            # tokens: a private header helper with no emitted symbol cannot
            # become an independent entry. Reachable inlined call sites are
            # still represented by their callers.
            if (linked_names is not None and function.get('is_static')
                    and re.search(r'\.(?:h|hh|hpp|hxx)$', function.get('file') or '', re.I)
                    and function.get('name') not in linked_names):
                continue
            if spellings is not None and index < len(spellings):
                words = set(re.findall(r'[A-Za-z_][A-Za-z_0-9]*', spellings[index]))
                if words and words <= non_entry_spellings:
                    continue
                return True
            return True
        return False
    possible.update(f['function_id'] for f in facts['functions']
                    if has_entry_attribute(f))
    # Unknown entry sources are local to the functions they can reference.
    # An opaque ordinary call is not an asynchronous caller of every symbol.
    if failed_files:
        possible.update(f['function_id'] for f in facts['functions']
                        if f.get('linkage') == 'EXTERNAL' or f.get('file') in failed_files)
    queue = deque(possible)
    while queue:
        caller = queue.popleft()
        for callee in graph[caller]:
            if callee and callee not in possible:
                possible.add(callee)
                queue.append(callee)
    incorrectly_pruned = possible.intersection(
        facts.get('pointer_solver_pruning', {}).get('pruned_function_ids', ()))
    if incorrectly_pruned:
        raise ValueError('Pointer solver reachability disagrees with execution entry proof: '
                         + ', '.join(sorted(incorrectly_pruned)[:8]))
    unreachable = {f['function_id'] for f in facts['functions'] if f['function_id'] not in possible
                   and contexts and f.get('file') not in failed_files}
    for f in facts['functions']:
        f['reachability'] = ('REACHABLE' if f['function_id'] in paths else
                             'PROVEN_UNREACHABLE' if f['function_id'] in unreachable else 'UNKNOWN_ENTRY')
    from .scope import AuditScope, select_facts
    start_stage('并发风险分类与保护证据')
    scope = AuditScope(project_root, cfg['analysis'])
    select_facts(facts, scope, coverage)
    by_var, events = defaultdict(list), defaultdict(list)
    for e in facts["protection_events"]:
        events[e["function_id"]].append(e)
    from .call_graph import AccessGraphSlices
    access_graph = AccessGraphSlices(facts, paths)
    compact_paths = not facts['context_call_graph']['path_lists_complete']
    for a in facts["accesses"]:
        allowed = a.get('allowed_contexts')
        access_paths = {cid: route for cid, route in paths.get(a['function_id'], {}).items()
                        if allowed is None or cid in allowed}
        a["contexts"] = sorted(access_paths)
        a['reachability'] = ('PROVEN_UNREACHABLE' if a['function_id'] in unreachable or a.get('context_proven_unreachable') else
                             'REACHABLE' if a['contexts'] else 'UNKNOWN_ENTRY')
        a["call_chains"] = access_paths
        a["all_call_chains"] = {cid: routes for cid, routes in all_call_paths.get(a["function_id"], {}).items()
                                if cid in access_paths}
        graph_slice = access_graph.for_function(a['function_id'])
        a['call_graph_slice'] = a['function_id']
        a['call_chain_representation'] = facts['context_call_graph']['representation']
        a['call_path_lists_complete'] = not compact_paths
        a['resolved_call_edge_count'] = len(graph_slice['call_edge_indices'])
        a['unresolved_call_edge_count'] = len(graph_slice['unresolved_issue_indices'])
        # Even a small path graph can have thousands of aliased access sites.
        # Share its full edge evidence once per accessor in both display modes;
        # the path lists above and every original call/issue remain available.
        a.pop('resolved_call_edges', None)
        a.pop('unresolved_call_edges', None)
        a['call_chain_cycles'] = graph_slice['recursive_edges']
        a["protection_evidence"] = [e for e in events[a["function_id"]] if e["event_kind"] in {"lock_enter", "lock_exit"}]
        by_var[a["symbol_id"]].append(a)
    facts['call_graph_slices'] = access_graph.cache
    snapshots = defaultdict(list)
    from .protection import MaskAnalysis, ProtectionIndex
    MaskAnalysis(facts, cfg).run()
    protection_index = ProtectionIndex(facts)
    from .stale_writeback import read_then_writeback_hints
    writeback_hints = defaultdict(list)
    for hint in read_then_writeback_hints(facts):
        writeback_hints[hint['symbol_id']].append(hint)
    for variable in facts['variables']:
        variable['concurrency_hints'] = writeback_hints[variable['symbol_id']]
    for s in facts["snapshots"]:
        snapshots[s["symbol_id"]].append(s)
    from .evidence import (CLASSIFIED_STATES, SCREENED_STATES, EvidenceIndex,
                           access_role, classify, fanout_diagnostics)
    evidence_index = EvidenceIndex(facts, coverage, cfg, unreachable)
    by_symbol = evidence_index.by_symbol
    findings = []
    # A zero-sized NOTYPE symbol assigned by the linker script is an address
    # boundary, not a C storage object.  Keep its source/ELF evidence in the
    # inventory, but never claim a variable SAFE merely because the synthetic
    # C declaration has no direct runtime load or store.
    variables_by_id = {row['symbol_id']: row for row in facts['variables']}
    live_roots = set()
    root_access_kinds = defaultdict(set)
    for access in facts['accesses']:
        owner = variables_by_id.get(access.get('symbol_id'), {})
        root_id = (owner.get('root_symbol_id') or owner.get('array_root_symbol_id')
                   or owner.get('symbol_id'))
        root_access_kinds[root_id].add(access.get('access_kind'))
        if access.get('reachability') != 'PROVEN_UNREACHABLE':
            live_roots.add(root_id)
    for variable in facts['variables']:
        root = variables_by_id.get(
            variable.get('root_symbol_id') or variable.get('array_root_symbol_id'), variable)
        if (not root.get('definition_file') and root.get('linkage') == 'EXTERNAL'
                and root.get('name') in evidence_index.linker_definitions):
            proof = evidence_index.linker_definitions[root['name']]
            variable.update(resource_kind='LINKER_ADDRESS_ANCHOR',
                            static_classification='NON_STORAGE',
                            audit_status='LINKER_ADDRESS_ANCHOR',
                            analysis_coverage='NOT_APPLICABLE',
                            coverage='NOT_APPLICABLE',
                            classification_reason='ELF 与 map 证实为零尺寸链接地址边界，不是独立 C 存储对象。',
                            linker_anchor_evidence=proof)
        elif (not root.get('definition_file') and root.get('linkage') == 'EXTERNAL'
              and root.get('is_weak') and linked_names is not None
              and root.get('name') not in linked_names
              and root_access_kinds[root['symbol_id']] <= {'ADDRESS_TAKEN'}):
            # An unresolved weak declaration evaluates to a null address in
            # this linked image. Address queries do not access a C object.
            variable.update(resource_kind='UNDEFINED_WEAK_SYMBOL',
                            static_classification='NON_STORAGE',
                            audit_status='UNDEFINED_WEAK_SYMBOL',
                            analysis_coverage='NOT_APPLICABLE', coverage='NOT_APPLICABLE',
                            classification_reason='最终 ELF 未定义该弱符号；源码仅取址，当前固件无对应存储对象。',
                            weak_symbol_evidence=dict(symbol=root['name'],
                                build_elf=coverage.get('build_closure', {}).get('elf'),
                                build_map=coverage.get('build_closure', {}).get('map')))
        elif (not root.get('definition_file') and root.get('linkage') == 'EXTERNAL'
              and linked_names is not None and root.get('name') not in linked_names
              and root['symbol_id'] not in live_roots):
            # A header declaration repeated in many parsed TUs is not a
            # variable in this firmware when no body can reach it and the
            # final linked ELF has no such symbol. Keep it in the inventory for
            # audit, outside the storage-classification denominator.
            variable.update(resource_kind='UNLINKED_DECLARATION',
                            static_classification='NON_STORAGE',
                            audit_status='UNLINKED_DECLARATION',
                            analysis_coverage='NOT_APPLICABLE',
                            coverage='NOT_APPLICABLE',
                            classification_reason='最终 ELF 无此符号，且全部源码访问均不可达；声明未形成当前固件存储。',
                            unlinked_declaration_evidence=dict(symbol=root['name'],
                                source_files=sorted({row.get('file') for row in root.get('declarations', ())
                                                     if row.get('file')}),
                                build_elf=coverage.get('build_closure', {}).get('elf')))
    coverage['linker_address_anchor_count'] = sum(
        row.get('resource_kind') == 'LINKER_ADDRESS_ANCHOR' for row in facts['variables'])
    coverage['unlinked_declaration_count'] = sum(
        row.get('resource_kind') == 'UNLINKED_DECLARATION' for row in facts['variables'])
    coverage['undefined_weak_symbol_count'] = sum(
        row.get('resource_kind') == 'UNDEFINED_WEAK_SYMBOL' for row in facts['variables'])
    analyzed_variables = [v for v in facts['variables']
                          if v.get('resource_kind') not in {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER',
                                                             'ARRAY_CONTAINER', 'LINKER_ADDRESS_ANCHOR',
                                                             'UNLINKED_DECLARATION', 'UNDEFINED_WEAK_SYMBOL'}
                          and v.get('coverage_source') not in {'supplemental', 'inactive_branch'}]
    coherence_by_symbol = multi_field_coherence(analyzed_variables, by_var, contexts,
                                                facts['calls'], facts['context_bindings'])
    facts['multi_field_coherence'] = list({id(row): row for rows in
        coherence_by_symbol.values() for row in rows}.values())
    from .initialization import prove_initialization, InitializationIndex
    initialization_index = InitializationIndex(facts, cfg)
    coherence_summaries = {}

    def summarize_coherence(row):
        ident = id(row)
        if ident not in coherence_summaries:
            coherence_summaries[ident] = dict(
                coherence_id=row['coherence_id'], root_symbol_id=row['root_symbol_id'],
                writer_physical_context=row['writer_physical_context'],
                reader_physical_context=row['reader_physical_context'],
                member_symbol_ids=row['member_symbol_ids'],
                function_pair_count=row['function_pair_count'],
                writer_access_count=len(row['writer_access_ids']),
                reader_access_count=len(row['reader_access_ids']),
                writer_access_ids=row['writer_access_ids'][:8],
                reader_access_ids=row['reader_access_ids'][:8],
                witness=row['witness'],
                full_evidence_reference='facts.json:multi_field_coherence')
        return coherence_summaries[ident]

    for v in analyzed_variables:
        sid = v["symbol_id"]
        all_accesses = by_var[sid]
        accesses = [a for a in all_accesses if a.get('reachability') != 'PROVEN_UNREACHABLE']
        readers = set(itertools.chain.from_iterable(a["contexts"] for a in accesses
            if access_role(a.get("access_kind")) == 'READ' or a.get('access_kind') == 'RMW'))
        writers = set(itertools.chain.from_iterable(a["contexts"] for a in accesses
            if access_role(a.get("access_kind")) == 'WRITE'))
        all_contexts = set(itertools.chain.from_iterable(a["contexts"] for a in accesses))
        physical_contexts = {contexts[c].get('physical_id') for c in all_contexts if c in contexts}
        physical_writers = {contexts[c].get('physical_id') for c in writers if c in contexts}
        variable_relations = [relation for relation in relations
                              if set(relation['contexts']) <= all_contexts]
        rules = {"GS-PARSE-INCOMPLETE"} if v.get("parse_status") == "FAILED" else set()
        uncertain = [u for u in by_symbol[sid] if u.get('function_id') not in unreachable]
        # Unknown edges above an access can introduce more contexts, even if one path is known.
        if any(not a["contexts"] for a in accesses):
            rules.add("GS-UNKNOWN-CONTEXT")
        if any(a["access_kind"] == "ADDRESS_TAKEN" or a.get("via_alias") for a in accesses) or uncertain:
            rules.add("GS-INDIRECT-ACCESS")
        if not accesses and not v["is_const"] and v.get('resource_kind') != 'STRUCT_MEMBER':
            rules.add("GS-NO-ACCESS-EVIDENCE")
        if not v["definition_file"]:
            rules.add("GS-DEFINITION-MISSING")
        if any(u["kind"] == "DMA_SHARED_REVIEW" for u in uncertain):
            rules.add("DMA_SHARED_REVIEW")
        reentrant = any(contexts[c].get("reentrant", False) for c in all_contexts)
        shared = len(physical_contexts) >= 2 or reentrant
        if shared and writers:
            rules.add("GS-MULTI-CONTEXT")
            if len(physical_writers) >= 2 or (reentrant and writers):
                rules.add("GS-MULTI-WRITER")
            if any(a["access_kind"] == "RMW" for a in accesses):
                rules.add("GS-RMW-INTERLEAVE")
            if snapshots[sid]:
                rules.add("GS-STALE-SNAPSHOT")
            if v["kind"] == "LOCAL_STATIC":
                rules.add("GS-LOCAL-STATIC-REENTRANT")
            if v["kind"] == "FILE_STATIC":
                rules.add("GS-FILE-STATIC-SHARED")
            word = cfg["project"].get("native_word_bits", 32) // 8
            if v["size_bytes"] is None or v["size_bytes"] > word or v["alignment_bytes"] is None or v["alignment_bytes"] < min(v["size_bytes"], word):
                rules.add("GS-TEAR-RISK")
            if v["is_struct"] or v["is_bitfield_container"]:
                rules.add("GS-STRUCT-INCONSISTENT")
        coherence_evidence = coherence_by_symbol.get(sid, [])
        coherence_summary = [summarize_coherence(row) for row in coherence_evidence]
        if coherence_evidence:
            rules.add('GS-MULTI-FIELD-COHERENCE')
        annotations = [r for r in cfg["resources"] if r.get("symbol_id", r.get("name")) in {sid, v["name"], v["qualified_name"]}]
        if any(r.get("owner_context") and writers - {r["owner_context"]} for r in annotations):
            rules.add("GS-OWNER-VIOLATION")
        declared = [p for p in cfg["protection"] if p.get("resource") in {sid, v["name"], v["qualified_name"]}]
        protection, protection_details, protection_note = protection_assessment(
            accesses, events, contexts, facts, cfg, index=protection_index)
        if protection == 'NOT_FOUND' and declared:
            protection = 'DETECTED'
            protection_note = '配置中声明了保护措施，但当前源码未找到可关联的保护操作，不能证明其覆盖访问窗口。'
        member_conflicts = conflict_pairs(accesses, variable_relations, contexts)
        init_proof = prove_initialization(v, accesses, facts, contexts, cfg, index=initialization_index)
        evidence = evidence_index.build(v, accesses, contexts, protection_details, init_proof)
        verdict = classify(evidence, accesses, contexts, member_conflicts, protection, protection_note,
            init_proof, variable=v, cfg=cfg, snapshots=snapshots[sid], coherence_evidence=coherence_evidence)
        static_classification = verdict['static_classification']
        classification_reason = verdict['classification_reason']
        coverage_reasons = verdict['coverage_reasons']
        coverage_status = verdict['analysis_coverage']
        blockers = verdict['screening_blockers']
        v.update(verdict)
        screened_reason = None
        if static_classification == 'SAFE_PROVEN':
            code = verdict['safe_reason_code']
            site_keys = {(a.get('function_id'), a.get('file'), a.get('offset'), a.get('access_path', ''), a['access_kind'])
                         for a in accesses if a['access_kind'] in {'READ', 'WRITE', 'RMW'}}
            screened_reason = {'SAFE_NO_RUNTIME_ACCESS': 'UNREACHABLE_ACCESSORS' if all_accesses else 'NO_RUNTIME_ACCESSES',
                'SAFE_READ_ONLY': 'ONLY_READS', 'SAFE_MULTI_CONTEXT_READ_ONLY': 'ONLY_READS',
                'SAFE_EFFECTIVE_PROTECTION': 'EFFECTIVE_IRQ_MASK'}.get(code,
                    'SINGLE_ACCESS_SITE' if len(site_keys)==1 and len(all_contexts)==1 else
                    'SINGLE_EXECUTION_CONTEXT' if len(all_contexts)==1 else code)
            rules.clear()
        elif static_classification == 'SHARED_NO_REVIEW':
            screened_reason = verdict['shared_reason_code']
            rules.clear()
        elif static_classification == 'UNKNOWN':
            rules.add('GS-COVERAGE-INCOMPLETE')
        elif not rules:
            rules.add('GS-MULTI-CONTEXT')
        audit_status = ('STATIC_SAFE_PROVEN' if static_classification == 'SAFE_PROVEN' else
                        'SHARED_NO_REVIEW' if static_classification == 'SHARED_NO_REVIEW' else 'REVIEW_REQUIRED')
        v.update(accesses=all_accesses, readers=sorted(readers), writers=sorted(writers), contexts=sorted(all_contexts),
                 protection_status=protection, annotations=annotations, audit_status=audit_status,
                 screening_reason=screened_reason, screening_blockers=sorted(blockers),
                 unreachable_access_count=len(all_accesses)-len(accesses), protection_details=protection_details,
                 protection_note=protection_note, analysis_coverage=coverage_status,
                  coverage_reasons=sorted(coverage_reasons), static_classification=static_classification,
                  classification_reason=classification_reason, concurrency_relations=variable_relations,
                  conflict_pairs=member_conflicts, access_count=len(all_accesses),
                  multi_field_coherence=coherence_summary,
                  resolved_call_path_count=sum(1 for access in all_accesses for _ in all_resolved_routes(access)))
        if not rules:
            continue
        high = {"GS-MULTI-WRITER", "GS-RMW-INTERLEAVE", "GS-LOCAL-STATIC-REENTRANT", "GS-STALE-SNAPSHOT",
                "GS-OWNER-VIOLATION", 'GS-MULTI-FIELD-COHERENCE'}
        level = "HIGH" if rules & high else "MEDIUM"
        if level == "HIGH" and any(r.get("business_critical") for r in annotations):
            level = "CRITICAL"
        finding = dict(finding_id="GS-" + digest([sid, sorted(rules), sorted(all_contexts)])[:16],
                       symbol_id=sid, variable_name=v["qualified_name"], rules=sorted(rules), risk_level=level,
                       confidence="MEDIUM" if shared else "LOW", status="NEED_OPENCODE_REVIEW",
                       protection_status=protection, declared_protection=declared, accesses=all_accesses,
                       definition=dict(file=v["definition_file"], line=v["definition_line"]),
                       context_pairs=[list(pair) for pair in itertools.combinations(sorted(all_contexts), 2)],
                        concurrency_relations=variable_relations, conflict_pairs=member_conflicts,
                       concurrency_reason="基于物理执行上下文与存储重叠形成冲突；优先级或保护待确认不覆盖已知冲突",
                       snapshots=snapshots[sid], uncertainties=uncertain,
                       screening_blockers=sorted(blockers),
                       configured_preemption=[p for p in cfg["preemption"] if {p["higher"], p["lower"]} <= all_contexts],
                       configured_concurrency=[p for p in cfg["concurrency"] if set(p["contexts"]) <= all_contexts],
                       protection_note=protection_note, protection_details=protection_details,
                       static_classification=static_classification,
                       coverage=coverage_status, coverage_reasons=coverage_reasons,
                       unknown_reason_codes=v.get('unknown_reason_codes', []),
                       blocking_evidence=v.get('blocking_evidence', []),
                       variable_evidence_slice=v.get('variable_evidence_slice'),
                        known_safe_annotations=[r for r in cfg["known_safe"] if r.get("resource") in {sid, v["name"], v["qualified_name"]}])
        findings.append(finding)
    # Parent records do not receive a root-level risk verdict: they only
    # summarize the independently analysed canonical members below them.
    members_by_root = defaultdict(list)
    for variable in analyzed_variables:
        if variable.get('root_symbol_id'):
            members_by_root[variable['root_symbol_id']].append(variable)
    for container in [v for v in facts['variables'] if v.get('resource_kind') in {'STRUCT_CONTAINER', 'ARRAY_CONTAINER'}]:
        members = members_by_root.get(container['symbol_id'], [])
        if container.get('resource_kind') == 'ARRAY_CONTAINER':
            members = [v for v in analyzed_variables if v.get('array_root_symbol_id') == container['symbol_id']]
            source_accesses = by_var[container['symbol_id']]
            by_var[container['symbol_id']] = list({a['access_id']:a for a in
                itertools.chain(source_accesses, *(member.get('accesses', []) for member in members))}.values())
        states = Counter(member.get('static_classification', 'UNKNOWN') for member in members)
        container.update(accesses=by_var[container['symbol_id']],
                         whole_object_accesses=by_var[container['symbol_id']],
                          member_count=len(members), member_status_counts=dict(
                              safe_proven=states['SAFE_PROVEN'], shared_no_review=states['SHARED_NO_REVIEW'],
                              suspect=states['SUSPECT'], unknown=states['UNKNOWN']),
                         audit_status='STRUCT_CONTAINER', screening_reason=None,
                         static_classification='CONTAINER', analysis_coverage='COMPLETE',
                         readers=sorted({c for m in members for c in m.get('readers', [])}),
                         writers=sorted({c for m in members for c in m.get('writers', [])}),
                         contexts=sorted({c for m in members for c in m.get('contexts', [])}),
                         classification_reason='结构体父节点只汇总成员；并发结论见各具体成员。')
    validate_member_fact_consistency(facts)
    coverage['project_diagnostics'] = [u for u in facts['unknowns'] if not u.get('symbol_id')]
    for v in facts['variables']:
        if v.get('coverage_source') in {'supplemental', 'inactive_branch'}:
            v.update(static_classification='OUT_OF_BUILD', audit_status='SUPPLEMENTAL_INVENTORY',
                     analysis_coverage='NOT_APPLICABLE', coverage='NOT_APPLICABLE', accesses=[],
                     classification_reason='未参与当前固件构建，仅保留声明盘点，不进入并发复核队列。')
    # Linker address boundaries and absent weak symbols remain in the audit
    # inventory, but are proven not to be storage in this linked image. Their
    # synthetic address references cannot be missing *storage* access contexts.
    unknown_entry_accesses = [a for a in facts['accesses']
        if not a['contexts'] and a.get('reachability') != 'PROVEN_UNREACHABLE']
    non_storage_unknown_entry_accesses = sum(
        variables_by_id.get(a.get('symbol_id'), {}).get('static_classification') == 'NON_STORAGE'
        for a in unknown_entry_accesses)
    unknown_accesses = len(unknown_entry_accesses) - non_storage_unknown_entry_accesses
    coverage['unreachable_functions'] = len(unreachable)
    coverage['unreachable_accesses'] = sum(a.get('reachability') == 'PROVEN_UNREACHABLE' for a in facts['accesses'])
    queued = {f['symbol_id'] for f in findings if f.get('symbol_id')}
    screened = {v['symbol_id'] for v in analyzed_variables if v.get('screening_reason')}
    ids = {v['symbol_id'] for v in analyzed_variables}
    if queued & screened or queued | screened != ids or len(ids) != len(analyzed_variables):
        raise ValueError('变量排查覆盖校验失败：每个变量必须唯一进入安全清单或逐项复核队列')
    coverage['variable_accountability'] = dict(total=len(ids), screened=len(screened),
        queued=len(queued), missing=0, duplicate_ids=0)
    for v in analyzed_variables:
        status = v.get('static_classification')
        if status not in CLASSIFIED_STATES:
            raise ValueError('变量缺少显式静态分类：' + v['symbol_id'])
        v['safe_reason'] = v.get('classification_reason') if status == 'SAFE_PROVEN' else None
        v['safe_evidence'] = (dict(proof=v.get('safe_reason_code'),
            access_ids=[a['access_id'] for a in v.get('accesses', [])],
            physical_contexts=v.get('variable_evidence_slice', {}).get('physical_contexts', []),
            contexts=v.get('contexts', []), protection_status=v.get('protection_status'),
            coverage=v.get('analysis_coverage'), initialization=v.get('initialization_proof'),
            context_exclusions=[proof for a in v.get('accesses', []) for proof in a.get('context_exclusions', [])],
            evidence_slice_symbol_id=v['symbol_id']) if status == 'SAFE_PROVEN' else None)
        v['unknown_reason'] = v.get('unknown_reason_codes', []) if status == 'UNKNOWN' else []
        v['required_context'] = [dict(kind=g['reason_code'], file=g.get('file'), line=g.get('line'),
            action=g['relevance']) for g in v.get('blocking_evidence', [])] if status == 'UNKNOWN' else []
        if status == 'SAFE_PROVEN' and (not v['safe_reason'] or not v.get('safe_reason_code') or not v.get('screening_reason')):
            raise ValueError('SAFE_PROVEN 缺少完整证明：' + v['symbol_id'])
        if status in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'} and v.get('blocking_evidence'):
            raise ValueError('筛除变量存在相关证据缺口：' + v['symbol_id'])
        if status == 'SHARED_NO_REVIEW' and (v.get('safe_reason_code') or not v.get('shared_reason_code')
                                             or not v.get('shared_evidence') or not v.get('screening_reason')):
            raise ValueError('SHARED_NO_REVIEW 缺少独立的严格门禁证据：' + v['symbol_id'])
    from .storage import add_disjoint_storage_proofs
    add_disjoint_storage_proofs(facts)
    coverage['safe_proof_distribution'] = dict(Counter(code for v in analyzed_variables
        for code in v.get('safe_reason_codes', [v['safe_reason_code']] if v.get('safe_reason_code') else [])))
    coverage['blocker_fanout'] = fanout_diagnostics(analyzed_variables,
        cfg['analysis'].get('max_unknown_fanout_debug', 50))
    coverage['safe_reason_distribution'] = dict(Counter(v['safe_reason_code'] for v in analyzed_variables if v.get('safe_reason_code')))
    coverage['shared_reason_distribution'] = dict(Counter(
        v['shared_reason_code'] for v in analyzed_variables if v.get('shared_reason_code')))
    coverage['unknown_reason_distribution'] = dict(Counter(code for v in analyzed_variables for code in v.get('unknown_reason_codes', [])))
    static_counts = Counter(v['static_classification'] for v in analyzed_variables)
    if set(static_counts) - CLASSIFIED_STATES or sum(static_counts.values()) != len(ids):
        raise ValueError('变量静态分类归账失败：TOTAL 必须等于 SAFE_PROVEN + SHARED_NO_REVIEW + SUSPECT + UNKNOWN')
    coverage['static_classification'] = dict(total=len(ids), safe_proven=static_counts['SAFE_PROVEN'],
        shared_no_review=static_counts['SHARED_NO_REVIEW'], suspect=static_counts['SUSPECT'],
        unknown=static_counts['UNKNOWN'])
    coverage['unknown_percent'] = round(100 * static_counts['UNKNOWN'] / max(1, len(ids)), 2)
    coverage['unknown_root_cause_analysis_required'] = coverage['unknown_percent'] > 10
    coverage['opencode_review_queue'] = len(queued)
    coverage['review_queue_percent'] = round(100 * len(queued) / max(1, len(ids)), 2)
    variant_inventory = sum(
        v.get('coverage_source') in {'supplemental', 'inactive_branch'}
        and v.get('resource_kind') not in {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER', 'ARRAY_CONTAINER'}
        for v in facts['variables'])
    coverage['review_rates'] = dict(
        rr_build=dict(numerator=len(queued), denominator=len(ids),
                      percent=coverage['review_queue_percent']),
        rr_all=dict(numerator=len(queued) + variant_inventory,
                    denominator=len(ids) + variant_inventory,
                    percent=round(100 * (len(queued) + variant_inventory)
                                  / max(1, len(ids) + variant_inventory), 2)),
        variant_inventory=variant_inventory)
    screened_states = {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}
    indirect_callers = {call.get('caller_function_id') for call in facts.get('calls', [])
                        if call.get('call_kind') == 'INDIRECT_RESOLVED'}

    def quality_row(code, description, predicate):
        matched = [v for v in analyzed_variables
                   if v.get('static_classification') in screened_states and predicate(v)]
        return dict(code=code, description=description, variable_count=len(matched),
                    variables=[dict(symbol_id=v['symbol_id'], name=v.get('qualified_name'),
                                    classification=v.get('static_classification')) for v in matched])

    eliminations = [
        quality_row('FOREGROUND_DOMAIN_COLLAPSE', '全部访问归入同一个 cooperative foreground 物理域。',
                    lambda v: v.get('safe_reason_code') == 'SAFE_SINGLE_FOREGROUND'),
        quality_row('SAME_IRQ_DOMAIN_COLLAPSE', '全部访问归入同一个 IRQ 向量，逻辑调用路径不形成自并发。',
                    lambda v: v.get('safe_reason_code') == 'SAFE_SINGLE_IRQ'),
        quality_row('READ_ONLY_PROOF', '所有运行期访问均为读取，跨上下文也不形成写冲突。',
                    lambda v: v.get('safe_reason_code') in {'SAFE_READ_ONLY', 'SAFE_MULTI_CONTEXT_READ_ONLY'}),
        quality_row('UNOBSERVED_WRITE_PROOF', '内部普通存储只有已覆盖的写入，没有读取、重叠别名或相关证据缺口。',
                    lambda v: v.get('safe_reason_code') == 'SAFE_UNOBSERVED_WRITES'),
        quality_row('INIT_RUNTIME_MHP', '初始化写与运行期访问已证明不同时发生。',
                    lambda v: v.get('safe_reason_code') == 'SAFE_INIT_ONLY_WRITE'),
        quality_row('EFFECTIVE_PROTECTION', '每个相关冲突访问窗口均有已证明有效的保护。',
                    lambda v: v.get('safe_reason_code') == 'SAFE_EFFECTIVE_PROTECTION'),
        quality_row('PAIRWISE_NON_INTERLEAVING', '物理上下文关系证明相关访问不能交错。',
                    lambda v: v.get('safe_reason_code') == 'SAFE_NON_INTERLEAVING'),
        quality_row('SINGLE_WRITER_GATE', '单一物理写者与纯读取观察者通过严格免复核门禁。',
                    lambda v: v.get('static_classification') == 'SHARED_NO_REVIEW'),
        quality_row('ALIAS_REFINEMENT', '已解析的 alias 访问保留为变量局部证据且未留下相关缺口。',
                    lambda v: any(a.get('via_alias') for a in v.get('accesses', []))
                              and not v.get('blocking_evidence')),
        quality_row('OBJECT_CONTEXT_REFINEMENT', '对象或调用点敏感分析排除了不可能到达该变量的上下文。',
                    lambda v: any(a.get('context_exclusions') for a in v.get('accesses', []))),
        quality_row('INDIRECT_CALL_RESOLUTION', '函数指针目标已静态恢复并继承调用者物理上下文。',
                    lambda v: bool(set(v.get('variable_evidence_slice', {}).get('function_ids', ()))
                                   & indirect_callers)),
        quality_row('SAME_PHYSICAL_CONTEXT_SERIALIZATION',
                    '不同逻辑入口映射到同一物理执行域，冲突对被证明串行。',
                    lambda v: any(p.get('relation', {}).get('physical_id') and not p.get('may_concurrent')
                                  for p in v.get('conflict_pairs', []))),
    ]
    suspect_reason_distribution = Counter()
    for finding in findings:
        if finding.get('static_classification') == 'SUSPECT':
            suspect_reason_distribution.update(finding.get('rules', []))
    coverage['classification_quality'] = dict(
        total=len(ids), safe_proven=static_counts['SAFE_PROVEN'],
        shared_no_review=static_counts['SHARED_NO_REVIEW'], suspect=static_counts['SUSPECT'],
        unknown=static_counts['UNKNOWN'], review_queue=len(queued),
        review_queue_percent=coverage['review_queue_percent'],
        review_rates=coverage['review_rates'],
        eliminations=[row for row in eliminations if row['variable_count']],
        suspect_reason_distribution=dict(suspect_reason_distribution),
        unknown_reason_distribution=coverage['unknown_reason_distribution'],
        blocker_fanout=coverage['blocker_fanout'],
        note='各排除机制可能作用于同一变量，贡献行彼此重叠，不能相加为变量总数。')
    coverage['struct_containers'] = sum(v.get('resource_kind') == 'STRUCT_CONTAINER' for v in facts['variables'])
    coverage["unknown_accesses"] = unknown_accesses
    coverage['non_storage_unknown_entry_accesses'] = non_storage_unknown_entry_accesses
    functions = [f for f in facts['functions'] if not scope.active or scope.contains(f['file'])]
    covered_functions = sum(f['function_id'] in paths for f in functions)
    coverage["functions_total"] = len(functions)
    coverage["functions_with_context"] = covered_functions
    coverage["context_coverage_percent"] = round(100 * covered_functions / max(1, len(functions)), 2)
    if scope.active:
        coverage['dependency_functions_total'] = len(facts['functions']) - len(functions)
    coverage["variables_total"] = len(facts["variables"])
    coverage["uncertainties_total"] = len(facts["unknowns"])
    inventory_kinds = Counter(v["kind"] for v in facts["variables"])
    coverage["inventory_by_kind"] = dict(inventory_kinds)
    coverage["supplemental_variables"] = sum(1 for v in facts["variables"] if v.get("coverage_source") in ("supplemental", "inactive_branch"))
    limitations = ["并发访问证据只来自当前编译配置；其他条件分支通过变体补充声明盘点，不作为实际构建访问。",
                   "调用证据保留全部入口、调用边和递归边；小图列出全部无环路径，大图只展示标记为见证的最短路径。图证据及安全证明均不截断；显式 max_call_paths 超限仍失败。",
                   "保护事件 DETECTED 不等于 EFFECTIVE；只有 CFG 全路径和竞争者模型均完整才可排除冲突。Ownership 与屏障本身不等于互斥。",
                   "指针与回调采用跨函数、字段及常量数组元素区分的保守目标集合；动态下标仅与同数组可能重叠元素合并。DMA 方向来自 HAL API 契约；生命周期和 Cache 协议仍须复核。",
                   "清单只包含全局变量、文件 static 和函数 static（含头文件实例与 C++ 静态成员）；普通局部变量、参数和结构体字段不作为共享对象盘点，但指针/别名指向它们的共享访问仍按目标对象分析。",
                   "补充声明不等于已完成并发分析；无法恢复的类型、宏或条件组合会保留覆盖缺口，不能宣称完整或安全。"]
    if coverage.get('audit_scope'):
        limitations.insert(0, '本次仅排查配置目录中定义的变量（排除目录优先）；范围外变量不作安全结论。依赖仍用于恢复目标变量的访问与调用链。')
    if cfg["analysis"].get("variable_scan"):
        limitations.append("为满足完整盘点要求，旧 variable_scan 的头文件/常量/变量类别过滤不生效，统一保留全部发现项。")
    incomplete = bool(coverage["translation_units_failed"] or coverage.get("unlisted_sources") or unknown_accesses
                      or facts["unknowns"] or any(not v["definition_file"] or v.get("coverage_source") in ("supplemental", "inactive_branch") for v in facts["variables"]))
    if cfg["project"].get("cm4_enabled") or cfg["project"].get("concurrency_model", "single_core_preemptive") != "single_core_preemptive":
        incomplete = True
        limitations.append("多核/其他调度模型尚未完整建模，必须复核共享内存、HSEM、Cache 和屏障。")
    return dict(analysis_status="INCOMPLETE" if incomplete else "MODELED_SCOPE_COMPLETE", coverage=coverage,
                findings=sorted(findings, key=lambda x: ({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}[x["risk_level"]], x["finding_id"])),
                limitations=limitations)
