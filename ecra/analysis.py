from collections import Counter, defaultdict, deque
import copy
import fnmatch
import itertools
import re

from .common import digest


TABLES = ("variables", "functions", "accesses", "calls", "unknowns", "protection_events", "registrations", "snapshots",
          "pointer_constraints", "semantic_calls", "indirect_accesses", "irq_priority_events", "control_flow")

# Cortex-M 前台（reset/引导链）入口命名约定：这些名字经向量表第 0/1 项进入，
# 属于唯一的 foreground 串行执行域，绝不能按 *_handler 后缀误判成 ISR。
RESET_ENTRY_NAMES = {"main", "reset_handler", "Reset_Handler", "ResetHandler"}


def merge(parts):
    facts = {t: [] for t in TABLES}
    variables, functions = {}, {}
    for part in parts:
        for v in part.get("variables", []):
            sid = v["symbol_id"]
            if sid not in variables:
                variables[sid] = v
            else:
                old = variables[sid]
                if v.get("parse_status") == "FAILED":
                    old["parse_status"] = "FAILED"
                for field in ("declarations", "definitions", "translation_units"):
                    for item in v[field]:
                        if item not in old[field]:
                            old[field].append(item)
                if not old["definition_file"] and v["definition_file"]:
                    for field in ("definition_file", "definition_line", "initializer", "size_bytes", "alignment_bytes"):
                        old[field] = v[field]
                if old["type"] != v["type"]:
                    facts["unknowns"].append(dict(kind="TYPE_VARIANT", symbol_id=sid, types=[old["type"], v["type"]]))
        for f in part.get("functions", []):
            functions[f["function_id"]] = f
        for t in TABLES[2:]:
            facts[t].extend(part.get(t, []))
    facts["variables"] = sorted(variables.values(), key=lambda x: x["symbol_id"])
    facts["functions"] = sorted(functions.values(), key=lambda x: x["function_id"])
    for t in TABLES[2:]:
        facts[t] = list({digest(row): row for row in facts[t]}.values())
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
        called = {call.get("callee_function_id") for call in facts["calls"] if call.get("callee_function_id")}
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
            elif name in RESET_ENTRY_NAMES:
                # ARM 裸机前台入口约定（C 标准 main 与 Cortex-M reset 链的
                # libopencm3/newlib 命名）：reset 入口是前台串行起点，不是
                # 中断。必须先于小写 *_handler ISR 约定判断，否则
                # libopencm3 的 reset_handler（整个前台引导链）会被误判成
                # ISR 上下文，制造大量虚假的跨上下文冲突。
                kind = "MAIN"
            elif (not name.startswith('HAL_') and not name.startswith('__')
                  and f.get("parameter_count", 0) == 0
                  and fid not in called
                  and (re.fullmatch(r'[A-Za-z_]\w*_(isr|irq)', name, re.I)
                       or re.fullmatch(r'[a-z_][a-z0-9_]*_handler', name))):
                # 通用小写 handler 约定（libopencm3 的 usb_isr/tim2_isr 与
                # 全小写 sys_tick_handler，经 C 向量表进入）：仅在没有任何
                # 已解析调用边时按 ISR 入口建模。这只会增加（而非减少）
                # 执行上下文，方向保守。双下划线前缀是编译器内建（如
                # __disable_irq），不是向量表入口。
                kind = "ISR"
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
                    reentrant=False, registrations=[], execution_note='FreeRTOS timer callbacks and pended functions share one serial daemon task'))
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
            for callee in sorted(graph[fid]):
                queue.append((callee, path + [callee]))
    # ``paths`` deliberately remains the shortest witness map consumed by
    # older JSON clients.  A shortest witness is not, however, a complete
    # calling-chain record.  Preserve every resolved *acyclic* route in a
    # separate map for each access/report.  Recursive edges are represented by
    # ``recursive_edges`` below rather than attempting to enumerate an
    # infinite family of paths.
    all_paths = defaultdict(lambda: defaultdict(list))
    # 大型工程的调用图存在枢纽节点：无环路径枚举是组合爆炸的。默认上限
    # 保护内存；达到上限时记录显式 CALL_PATH_CAPPED 事实：展示链与组合
    # 计数退化为下界。分类本身不依赖该枚举（上下文与入口不确定性使用
    # 最短见证与函数级事实），因此不因截断而放大 false-safe。
    path_limit = cfg.get('analysis', {}).get('max_call_paths', 2_000_000)
    if type(path_limit) is not int or path_limit < 0:
        raise ValueError('analysis.max_call_paths 必须为非负整数；0 表示不限制。')
    capped_roots = set()
    produced = 0
    for cid, entries in roots.items():
        if path_limit and produced >= path_limit:
            capped_roots.add(cid)
            continue
        for entry in sorted(entries):
            stack = [(entry, [entry], iter(sorted(graph[entry])))]
            all_paths[entry][cid].append([entry])
            produced += 1
            capped = False
            while stack:
                node, route, successors = stack[-1]
                child = next(successors, None)
                if child is None:
                    stack.pop()
                    continue
                # A repeated node is a real recursive/cyclic route, but it
                # cannot form another finite resolved call chain.  The edge is
                # retained in facts["recursive_edges"] for presentation.
                if child in route:
                    continue
                if path_limit and produced >= path_limit:
                    capped = True
                    break
                child_route = route + [child]
                all_paths[child][cid].append(child_route)
                produced += 1
                stack.append((child, child_route, iter(sorted(graph[child]))))
            if capped:
                capped_roots.add(cid)
                break
    if capped_roots:
        issues.append(dict(kind='CALL_PATH_CAPPED', limit=path_limit,
                           context_ids=sorted(capped_roots),
                           hint='调用链枚举达到 max_call_paths 上限；展示链与组合计数为下界。分类使用入口级证据，不受该截断影响。'))
    for fid, per_context in all_paths.items():
        for cid, routes in per_context.items():
            # Stable de-duplication is useful when multiple configured entries
            # share an initial function.
            all_paths[fid][cid] = list({tuple(route): route for route in routes}.values())
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
    facts["all_call_paths"] = {fid: dict(per_context) for fid, per_context in all_paths.items()}
    facts["unknowns"].extend(issues)
    return contexts, paths, facts["all_call_paths"]


def protection_assessment(accesses, events, contexts, facts, cfg,
                          relation_index=None, mask_windows_by_symbol=None,
                          unmaskable_contexts=None):
    from .protection import assess
    return assess(accesses, events, contexts, facts, cfg,
                  relation_index=relation_index,
                  mask_windows_by_symbol=mask_windows_by_symbol,
                  unmaskable_contexts=unmaskable_contexts)


def canonical_member_path(path):
    """Normalize extractor and points-to field spellings to one dotted path."""
    path = (path or '').strip().replace('\\', '/')
    if not path:
        return ''
    pieces = []
    for part in path.replace('/', '.').split('.'):
        if not part:
            continue
        if part == '[]' and pieces:
            pieces[-1] += '[]'
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
            resource.update(symbol_id=sid, name=field.get('name') or field_path.rsplit('.', 1)[-1],
                            qualified_name=root['qualified_name'] + '.' + field_path,
                            kind='STRUCT_MEMBER', scope='member',
                            root_symbol_id=root_sid, root_symbol=root['qualified_name'],
                            field_path=field_path,
                            canonical_path=root['qualified_name'] + '.' + field_path,
                            resource_kind='STRUCT_MEMBER_CONTAINER' if field.get('is_struct') else 'STRUCT_MEMBER',
                            type=field.get('type') or root.get('type'),
                            size_bytes=field.get('size_bytes'), alignment_bytes=field.get('alignment_bytes'),
                            is_const=bool(field.get('is_const')), is_volatile=bool(field.get('is_volatile')),
                            is_struct=bool(field.get('is_struct')),
                            is_bitfield_container=bool(field.get('is_bitfield')),
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
                                                   if child == field_path or child.startswith(field_path + '.')
                                                   if member_by_key[(root_sid, child)]['resource_kind'] == 'STRUCT_MEMBER']
        root['member_symbol_ids'] = children_by_root[root_sid]

    additions_by_sid = {v['symbol_id']: v for v in additions}
    generated = []
    for access in facts['accesses']:
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
            inherited_targets = descendants[(original_sid, '')] = [sid for sid in children_by_root[original_sid]
                if member_by_key[(original_sid, sid.rsplit('::member::', 1)[1])]['resource_kind'] == 'STRUCT_MEMBER']
        if inherited_targets and access['access_kind'] in {'READ', 'WRITE', 'RMW'}:
            for target_sid in inherited_targets:
                target = additions_by_sid[target_sid]
                inherited = copy.deepcopy(access)
                inherited.update(symbol_id=target_sid, root_symbol_id=original_sid,
                                 root_symbol=root['qualified_name'], field_path=target['field_path'],
                                 canonical_path=target['canonical_path'],
                                 access_scope='INHERITED_WHOLE_OBJECT_ACCESS',
                                 inherited_from_access_id=access.get('access_id'),
                                 inherited_from_canonical_path=access['canonical_path'])
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
        for target_sid in descendants.get((root_sid, ''), []):
            clone = dict(issue, symbol_id=target_sid, root_symbol_id=root_sid,
                         canonical_path=additions_by_sid[target_sid]['canonical_path'],
                         inherited_object_uncertainty=True)
            inherited_unknowns.append(clone)
    facts['unknowns'].extend(inherited_unknowns)
    # Access identity must include target identity after one root fact becomes
    # several member effects.  Do this only once all generated records exist.
    for index, access in enumerate(facts['accesses']):
        access['access_id'] = 'A-' + digest([index, access])[:20]
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


def conflict_pairs(accesses, relations, contexts, analysis_cfg=None):
    """Build member-level conflict groups without losing any full path.

    A Cartesian product of every left/right route is only a presentation
    expansion: it repeats the same complete routes thousands of times on a
    large firmware.  One group therefore stores the two access/context
    instances and *all* routes on both sides.  The UI expands both collections
    and reports their product count, retaining every possible pair while
    keeping facts and HTML proportional to the actual call graph.

    ``analysis_cfg['max_conflict_pairs']``（默认 2000，0 表示不限）限制单个
    变量生成的展示组合数：超过上限时按"写冲突优先"的顺序保留前 N 组，并
    返回截断诊断而不是静默丢失。分类不依赖该展示层枚举。
    """
    cap = (analysis_cfg or {}).get('max_conflict_pairs', 2000)
    if type(cap) is not int or cap < 0:
        raise ValueError('analysis.max_conflict_pairs 必须为非负整数；0 表示不限制。')
    relation_by_contexts = {tuple(sorted(row['contexts'])): row for row in relations}
    instances = {}
    for access in accesses:
        if access.get('access_kind') not in {'READ', 'WRITE', 'RMW'}:
            continue
        # Route counting uses the per-context route lists directly; iterating
        # every route only to count it is linear in the path explosion of hub
        # functions.
        complete = access.get('all_call_chains')
        if complete is None:
            complete = {cid: [path] for cid, path in access.get('call_chains', {}).items()}
        for context_id, routes in complete.items():
            route_count = len(routes or [])
            if not route_count:
                continue
            key = (access.get('access_id'), context_id)
            instance = instances.setdefault(key, dict(instance_id='CI-' + digest(key)[:20],
                context_id=context_id, access_id=access.get('access_id'), access_kind=access['access_kind'],
                function_id=access['function_id'], file=access.get('file'), line=access.get('line'),
                canonical_path=access.get('canonical_path'), call_path_count=0,
                access_scope=access.get('access_scope', 'MEMBER_ACCESS'),
                inherited_from_canonical_path=access.get('inherited_from_canonical_path')))
            # Full routes stay once in access.all_call_chains.  A conflict
            # participant references that evidence by access/context instead
            # of duplicating every route for every competing counterpart.
            instance['call_path_count'] += route_count
    pairs = []
    ordered = list(instances.values())
    # 写冲突实例优先配对，使截断保留的是最需要复核的组合。
    ordered.sort(key=lambda i: i['access_kind'] == 'READ')
    total_pairs = len(ordered) * (len(ordered) - 1) // 2
    capped = cap and total_pairs > cap
    for index, left in enumerate(ordered):
        if capped and len(pairs) >= cap:
            break
        for right in ordered[index + 1:]:
            if capped and len(pairs) >= cap:
                break
            # The exact same source access on the exact same route is one
            # access instance, not a self-conflict.  The same source point in
            # another context deliberately remains a distinct instance.
            if left['access_id'] == right['access_id'] and left['context_id'] == right['context_id']:
                continue
            if left['context_id'] == right['context_id']:
                relation = dict(contexts=[left['context_id']],
                                relation='MAY_REENTER' if contexts.get(left['context_id'], {}).get('reentrant') else 'SERIAL',
                                reason='同一执行上下文默认串行；显式可重入上下文另作并发候选。')
            else:
                relation = relation_by_contexts.get(tuple(sorted((left['context_id'], right['context_id']))),
                                                    dict(contexts=[left['context_id'], right['context_id']],
                                                         relation='UNKNOWN_PREEMPTION',
                                                         reason='未恢复两个执行上下文的关系。'))
            possible = relation['relation'] not in {'SERIAL'}
            has_write = left['access_kind'] in {'WRITE', 'RMW'} or right['access_kind'] in {'WRITE', 'RMW'}
            state = ('需确认' if possible and has_write else
                     '无写冲突' if possible else '忽略（同一串行上下文）')
            pairs.append(dict(conflict_id='C-' + digest([left['instance_id'], right['instance_id']])[:16],
                              participant_a=left, participant_b=right, relation=relation,
                              may_concurrent=possible, has_write_conflict=has_write, status=state,
                              path_combination_count=left['call_path_count'] * right['call_path_count']))
    diagnostic = None
    if capped:
        diagnostic = dict(kind='CONFLICT_PAIR_CAPPED', limit=cap, total_pair_count=total_pairs,
                          hint='底层并发组合展示达到 max_conflict_pairs 上限；已按写冲突优先保留，组合总数为下界。分类不依赖该展示枚举。')
    return sorted(pairs, key=lambda pair: (not pair['may_concurrent'], not pair['has_write_conflict'],
                                           pair['participant_a']['context_id'], pair['participant_b']['context_id'],
                                           pair['conflict_id'])), diagnostic


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
        # Per-access path counts are cached from all_call_chains in the
        # per-access loop; recounting every route here is quadratic on hub
        # functions and the cache already comes from the same source tables.
        expected_paths = sum(a.get('resolved_call_path_count',
                                   sum(1 for _ in all_resolved_routes(a))) for a in accesses)
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


def analyze(facts, cfg, coverage, root=None):
    from pathlib import Path
    project_root = Path(root or coverage.get('project_root', Path.cwd()))
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
            source = (project_root / file).read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            facts['unknowns'].append(dict(kind='ASSEMBLY_SOURCE_REVIEW', file=file, message=str(exc)))
            continue
        if re.search(r'^\s*(?:\.macro\b|#\s*include\b)|##', source, re.M):
            facts['unknowns'].append(dict(kind='ASSEMBLY_SOURCE_REVIEW', file=file,
                message='汇编宏或包含文件尚未展开，不能证明入口/变量访问完整'))
        for line, text in enumerate(source.splitlines(), 1):
            for name in sorted(set(re.findall(r'[A-Za-z_][A-Za-z_0-9]*', text))):
                for sid in symbols_by_name.get(name, ()):
                    facts['unknowns'].append(dict(kind='ASSEMBLY_SYMBOL_REFERENCE', symbol_id=sid,
                        file=file, line=line, source_text=text))
                for fid in functions_by_name.get(name, ()):
                    facts['unknowns'].append(dict(kind='ASSEMBLY_FUNCTION_REFERENCE', target_function_id=fid,
                        file=file, line=line, source_text=text))
    # Function addresses handed to inline assembly (e.g. ``asm("bx %0" ::
    # "r"(next_stage))``) are callable/jumpable from that asm block. The edge
    # is conservative in the safe direction: it only adds reachable execution
    # contexts. If the same address also flows to genuinely asynchronous code,
    # the existing indirect/escape mechanisms still mark that separately.
    asm_ranges = defaultdict(list)
    for u in facts['unknowns']:
        if u.get('kind') == 'INLINE_ASSEMBLY' and u.get('offset') is not None:
            asm_ranges[u.get('file')].append(
                (u['offset'], u.get('end_offset') or u['offset'], u.get('function_id')))
    if asm_ranges:
        func_names = {f['function_id']: f['name'] for f in facts['functions']}
        existing_edges = {(c.get('caller_function_id'), c.get('file'), c.get('offset'),
                           c.get('callee_function_id')) for c in facts['calls']}
        for u in facts['unknowns']:
            if (u.get('kind') != 'FUNCTION_ADDRESS' or u.get('target_function_id') is None
                    or u.get('offset') is None):
                continue
            for start, end, caller in asm_ranges.get(u.get('file'), ()):
                if caller is None or not start <= u['offset'] <= end:
                    continue
                edge = (caller, u.get('file'), u['offset'], u['target_function_id'])
                if edge not in existing_edges:
                    existing_edges.add(edge)
                    facts['calls'].append(dict(
                        caller_function_id=caller, callee_function_id=u['target_function_id'],
                        callee_name=func_names.get(u['target_function_id'], ''),
                        call_kind='ASSEMBLY', file=u.get('file'), line=u.get('line'),
                        offset=u['offset']))
                break
    from .points_to import enrich
    enrich(facts, cfg)
    # Missing-source lexical references are candidates, never definite READ/
    # WRITE facts. Keep their file/line and bind them only to named variables.
    missing_files = set(coverage.get('unlisted_sources', []))
    missing_files.update(u.get('file') for u in facts['unknowns'] if u['kind']=='PARSE_FAILED' and u.get('file'))
    for file in sorted(missing_files):
        try:
            text = (project_root / file).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        text = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"', lambda m: '\n' * m[0].count('\n'), text, flags=re.S)
        names = {name for name in re.findall(r'\b[A-Za-z_]\w*\b', text)}
        for f in facts['functions']:
            if f['name'] in names and (f.get('linkage')=='EXTERNAL' or f['file']==file):
                facts['unknowns'].append(dict(kind='MISSING_SOURCE_CALLER', target_function_id=f['function_id'],
                    file=file, relation='possible_function_reference',
                    hint='未完整分析源码引用此函数，可能引入额外入口；补齐该文件后恢复调用边。'))
        for v in facts['variables']:
            if v['name'] in names and (v.get('linkage')=='EXTERNAL' or file in v.get('translation_units', [])):
                facts['unknowns'].append(dict(kind='SOURCE_NOT_IN_DATABASE' if file in coverage.get('unlisted_sources', []) else 'PARSE_FAILED',
                    symbol_id=v['symbol_id'], file=file, relation='possible_source_reference',
                    line=next((i for i,s in enumerate(text.splitlines(),1) if re.search(r'\b'+re.escape(v['name'])+r'\b',s)),1),
                    hint='未完整分析的源码引用了该变量；补齐编译数据库/解析参数后恢复访问。'))
    # Pointer solving and missing-source checks intentionally work with storage
    # roots.  Only now promote record accesses to canonical member resources so
    # no field is confused with a similarly named identifier in unparsed code.
    canonicalize_member_resources(facts)
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
    relations = preemption_relations(facts, contexts, cfg)
    # The full relation matrix is quadratic in the context count (every IRQ
    # vector is a context). Per-variable scans over it are the analysis-time
    # bottleneck on large firmwares; index it once and materialize each
    # variable's rows from its own (few) context pairs instead.
    relation_by_pair = {tuple(sorted(r['contexts'])): r for r in relations}
    entry_ids = {b['function_id'] for b in facts['context_bindings'] if b['call_depth'] == 0}
    facts['assembly_references'] = [u for u in facts['unknowns'] if u['kind'] in
                                    {'ASSEMBLY_FUNCTION_REFERENCE', 'ASSEMBLY_SYMBOL_REFERENCE'}]
    facts['unknowns'] = [u for u in facts['unknowns'] if not (u['kind'] == 'ASSEMBLY_FUNCTION_REFERENCE'
                         and u.get('target_function_id') in entry_ids)]
    # Conflict-based classification model. Physical execution domains,
    # variable-local escape evidence, entry uncertainty and per-function
    # deadness are established BEFORE scope filtering: dependencies outside
    # the audit scope still contribute call-graph reachability for variables
    # inside the scope.
    from .classify import ClassificationModel
    model = ClassificationModel(facts, contexts, relations, paths, cfg, coverage)
    unreachable = model.dead_functions
    for f in facts['functions']:
        f['reachability'] = ('REACHABLE' if f['function_id'] in paths else
                             'PROVEN_UNREACHABLE' if f['function_id'] in unreachable else 'UNKNOWN_ENTRY')
    from .scope import AuditScope, select_facts
    scope = AuditScope(project_root, cfg['analysis'])
    select_facts(facts, scope, coverage)
    by_var, events = defaultdict(list), defaultdict(list)
    for e in facts["protection_events"]:
        events[e["function_id"]].append(e)
    # Edge and cycle evidence depends only on the access's function. Index the
    # global tables once and cache per function: a full scan per access is
    # quadratic on large firmwares (30k accesses x 150k unknowns).
    calls_by_caller = defaultdict(list)
    for c in facts["calls"]:
        if c.get("callee_function_id"):
            calls_by_caller[c["caller_function_id"]].append(c)
    unresolved_edge_kinds = {'INDIRECT_CALL', 'EXTERNAL_CALLEE', 'MISSING_SOURCE_CALLER',
                             'UNRESOLVED_REGISTERED_ENTRY'}
    unresolved_by_fid = defaultdict(list)
    for u in facts['unknowns']:
        if u.get('kind') not in unresolved_edge_kinds:
            continue
        indexed = set()
        for fid in (u.get('function_id'), u.get('target_function_id')):
            if fid and fid not in indexed:
                indexed.add(fid)
                unresolved_by_fid[fid].append(u)
    cycles_by_node = defaultdict(list)
    for edge in facts['recursive_edges']:
        cycles_by_node[edge[0]].append(edge)
    function_evidence = {}
    route_ancestors_by_function = {}

    def _function_evidence(fid):
        evidence = function_evidence.get(fid)
        if evidence is None:
            chains = paths.get(fid, {})
            all_chains = all_call_paths.get(fid, {})
            ancestors = {f for routes in all_chains.values() for route in routes for f in route}
            ancestors.add(fid)
            resolved = [c for caller in sorted(ancestors) for c in calls_by_caller.get(caller, ())
                        if c.get("callee_function_id") in ancestors]
            unresolved, seen_rows = [], set()
            for f in sorted(ancestors):
                for u in unresolved_by_fid.get(f, ()):
                    if id(u) not in seen_rows:
                        seen_rows.add(id(u))
                        unresolved.append(u)
            cycles = [e for f in sorted(ancestors) for e in cycles_by_node.get(f, ())
                      if e[1] in ancestors]
            contexts = sorted(chains)
            evidence = dict(contexts=contexts,
                reachability=('PROVEN_UNREACHABLE' if fid in unreachable else
                              'REACHABLE' if contexts else 'UNKNOWN_ENTRY'),
                call_chains=chains, all_call_chains=all_chains,
                resolved_call_path_count=sum(len(routes) for routes in all_chains.values()),
                resolved_call_edges=resolved, unresolved_call_edges=unresolved,
                call_chain_cycles=cycles,
                protection_evidence=[e for e in events.get(fid, ())
                                     if e["event_kind"] in {"lock_enter", "lock_exit"}])
            function_evidence[fid] = evidence
            # Protection assessment needs the same route-ancestor union per
            # variable; re-walking every route per variable is quadratic on
            # large call graphs. Derived data, deliberately kept out of facts
            # so reports never serialize this cache.
            route_ancestors_by_function[fid] = frozenset(ancestors)
        return evidence

    for a in facts["accesses"]:
        evidence = _function_evidence(a["function_id"])
        a["contexts"] = evidence['contexts']
        a['reachability'] = evidence['reachability']
        a["call_chains"] = evidence['call_chains']
        a["all_call_chains"] = evidence['all_call_chains']
        a['resolved_call_path_count'] = evidence['resolved_call_path_count']
        a['resolved_call_edges'] = evidence['resolved_call_edges']
        a['unresolved_call_edges'] = evidence['unresolved_call_edges']
        a['call_chain_cycles'] = evidence['call_chain_cycles']
        a["protection_evidence"] = evidence['protection_evidence']
        by_var[a["symbol_id"]].append(a)
    snapshots = defaultdict(list)
    from .protection import MaskAnalysis
    MaskAnalysis(facts, cfg).run()
    # Per-variable assessment lookups, indexed once instead of rescanning the
    # full windows / bindings tables for every variable.
    mask_windows_by_symbol = defaultdict(list)
    for w in facts.get('mask_windows', []):
        mask_windows_by_symbol[w['symbol_id']].append(w)
    _funcs_by_id = {f['function_id']: f for f in facts['functions']}
    unmaskable_contexts = {b['context_id'] for b in facts['context_bindings']
                           if b['call_depth'] == 0
                           and _funcs_by_id.get(b['function_id'], {}).get('name')
                           in {'NMI_Handler', 'HardFault_Handler'}}
    for s in facts["snapshots"]:
        snapshots[s["symbol_id"]].append(s)
    # Variable-bound uncertainties are indexed per symbol. Project-wide
    # unknowns (function pointers, unresolved callees, parse gaps elsewhere)
    # no longer taint every variable: the ClassificationModel decides, per
    # variable, whether such a fact actually enters that variable's evidence
    # slice (address escape, alias reachability, entry uncertainty).
    by_symbol = defaultdict(list)
    for u in facts['unknowns']:
        if u.get('symbol_id'):
            by_symbol[u['symbol_id']].append(u)
    # 多字段一致性（multi-field coherence）：同一 root struct 下，一个物理域
    # 写 ≥2 个成员（整体写经继承也算逐成员写），另一物理域在**同一函数内**
    # 成对读取其中 ≥2 个成员 → 该成员对可能被撕裂读取（value+valid 协议
    # 模式）。只标记真实参与跨域读对的成员，不扩大到整个 root。
    domain_member_writes = defaultdict(lambda: defaultdict(set))          # root -> domain -> {sid}
    domain_fn_member_reads = defaultdict(lambda: defaultdict(set))        # root -> (domain, fn) -> {sid}
    for member_sid, access_rows in by_var.items():
        member_var = model.variables.get(member_sid)
        root_sid = member_var.get('root_symbol_id') if member_var else None
        if not root_sid:
            continue
        for a in access_rows:
            if a.get('access_kind') not in {'READ', 'WRITE', 'RMW'}:
                continue
            for cid in a.get('contexts', ()):
                domain = model.domain[cid]
                if a['access_kind'] == 'READ':
                    domain_fn_member_reads[root_sid][(domain, a['function_id'])].add(member_sid)
                else:
                    domain_member_writes[root_sid][domain].add(member_sid)
    coherent_members = set()
    for root_sid, per_domain in domain_member_writes.items():
        for writer_domain, written in per_domain.items():
            if len(written) < 2:
                continue
            for (reader_domain, _fn), read_set in domain_fn_member_reads.get(root_sid, {}).items():
                torn_pair = read_set & written
                if reader_domain != writer_domain and len(torn_pair) >= 2:
                    coherent_members |= torn_pair
    model.coherent_members = coherent_members
    findings = []
    analyzed_variables = [v for v in facts['variables']
                          if v.get('resource_kind') not in {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER'}]
    from .protection import set_route_ancestors
    set_route_ancestors(route_ancestors_by_function, facts)
    for v in analyzed_variables:
        sid = v["symbol_id"]
        # Supplemental variables come from files outside the compile database
        # or inactive conditional branches. They are inventory-only; without
        # the current build's macros and flags, their access evidence is not
        # comparable to compiled-code analysis.
        if v.get("coverage_source") in ("supplemental", "inactive_branch"):
            v.update(accesses=[], readers=[], writers=[], contexts=[], protection_status="NONE",
                     annotations=[], audit_status="SUPPLEMENTAL_INVENTORY",
                     screening_reason=None, safe_reason_code=None, screening_blockers=['ACCESS_NOT_ANALYZED'],
                     analysis_coverage='PARTIAL', coverage_reasons=['ACCESS_NOT_ANALYZED'],
                     static_classification='UNKNOWN', gap_evidence=[], pending_confirmation=[],
                     access_count=0, resolved_call_path_count=0, unreachable_access_count=0,
                     classification_reason='该声明来自未编译源码或非活动条件分支，访问尚未按当前构建分析。')
            site = next(iter(v.get('definitions', []) or v.get('declarations', [])), {})
            findings.append(dict(finding_id='GS-' + digest([sid, 'GS-SUPPLEMENTAL-UNANALYZED'])[:16],
                symbol_id=sid, variable_name=v['qualified_name'], rules=['GS-SUPPLEMENTAL-UNANALYZED'],
                risk_level='MEDIUM', confidence='LOW', status='NEED_OPENCODE_REVIEW',
                protection_status='UNKNOWN', accesses=[], uncertainties=[],
                definition=dict(file=v.get('definition_file') or site.get('file'),
                                line=v.get('definition_line') or site.get('line')),
                screening_blockers=['ACCESS_NOT_ANALYZED'], static_classification='UNKNOWN'))
            continue
        all_accesses = by_var[sid]
        accesses = [a for a in all_accesses if a['function_id'] not in unreachable]
        readers = set(itertools.chain.from_iterable(a["contexts"] for a in accesses if a["access_kind"] in {"READ", "RMW"}))
        writers = set(itertools.chain.from_iterable(a["contexts"] for a in accesses if a["access_kind"] in {"WRITE", "RMW"}))
        all_contexts = set(itertools.chain.from_iterable(a["contexts"] for a in accesses))
        variable_relations = [relation_by_pair[pair] for pair in
                              itertools.combinations(sorted(all_contexts), 2)]
        uncertain = [u for u in by_symbol[sid] if u.get('function_id') not in unreachable]
        reentrant = any(contexts[c].get("reentrant", False) for c in all_contexts)
        shared = len(all_contexts) >= 2 or reentrant
        annotations = [r for r in cfg["resources"] if r.get("symbol_id", r.get("name")) in {sid, v["name"], v["qualified_name"]}]
        owner_violation = any(r.get("owner_context") and writers - {r["owner_context"]} for r in annotations)
        declared = [p for p in cfg["protection"] if p.get("resource") in {sid, v["name"], v["qualified_name"]}]
        protection, protection_details, protection_note = protection_assessment(
            accesses, events, contexts, facts, cfg,
            relation_index=relation_by_pair,
            mask_windows_by_symbol=mask_windows_by_symbol,
            unmaskable_contexts=unmaskable_contexts)
        if protection == 'NOT_FOUND' and declared:
            protection = 'DETECTED'
            protection_note = '配置中声明了保护措施，但当前源码未找到可关联的保护操作，不能证明其覆盖访问窗口。'
        # ---- Conflict-based four-class classification (see ecra.classify) ----
        # DESTRUCTIVE CONFLICT => SUSPECT (even with unresolved priority/protection);
        # SINGLE WRITER + READ-ONLY OTHERS + atomic width => SHARED_NO_REVIEW;
        # relevant slice gap => UNKNOWN; otherwise SAFE_PROVEN with proof.
        result = model.classify(v, accesses, uncertain, protection)
        static_classification = result['classification']
        if owner_violation and static_classification in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}:
            static_classification = 'SUSPECT'
            result = dict(result, classification='SUSPECT',
                          reason='违反配置声明的上下文所有权：存在声明所有者之外的写入上下文。')
        gap_codes = sorted({g['code'] for g in result['gaps']})
        coverage_reasons = list(gap_codes)
        coverage_status = 'COMPLETE' if not coverage_reasons else 'PARTIAL'
        # Conflict-shape rules only describe SUSPECT findings (risk ranking);
        # they never decide SAFE/UNKNOWN by themselves.
        rules = set()
        if static_classification == 'SUSPECT':
            if shared and writers:
                rules.add("GS-MULTI-CONTEXT")
                if len(writers) >= 2 or (reentrant and writers):
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
            if owner_violation:
                rules.add("GS-OWNER-VIOLATION")
            for destructive_reason in result.get('destructive') or ():
                if 'CPU↔DMA' in destructive_reason:
                    rules.add("GS-DMA-RACE")
                elif '多字段一致性' in destructive_reason:
                    rules.add("GS-MULTI-FIELD-COHERENCE")
                elif '位域' in destructive_reason:
                    rules.add("GS-STRUCT-INCONSISTENT")
        if static_classification in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}:
            safe_code = result['safe_code']
            from .classify import SAFE_LABELS
            # 已筛除变量没有需要复核的冲突组合：证明/无复核结论本身就是结果，
            # 展示层笛卡尔组合对热点只读/单域变量是纯开销。
            v.update(accesses=all_accesses, readers=sorted(readers), writers=sorted(writers), contexts=sorted(all_contexts),
                     protection_status=protection, annotations=annotations,
                     audit_status='SCREENED_NO_CONCURRENCY_RISK',
                     screening_reason=safe_code, safe_reason_code=safe_code, screening_blockers=[],
                     unreachable_access_count=len(all_accesses)-len(accesses), protection_details=protection_details,
                     protection_note=protection_note, analysis_coverage=coverage_status,
                     coverage_reasons=[], static_classification=static_classification,
                     classification_reason=SAFE_LABELS[safe_code] + '（' + result['reason'] + '）',
                     concurrency_relations=variable_relations, conflict_pairs=[],
                     conflict_pairs_capped=None,
                     access_count=len(all_accesses), gap_evidence=[],
                     shared_no_review_evidence=result.get('shared_evidence'),
                     resolved_call_path_count=sum(a['resolved_call_path_count'] for a in all_accesses))
            continue
        member_conflicts, conflict_cap_info = conflict_pairs(all_accesses, variable_relations, contexts,
                                                             cfg['analysis'])
        pending = []
        if static_classification == 'SUSPECT':
            if protection in {'DETECTED', 'PARTIAL', 'UNRESOLVED'}:
                pending.append('保护有效性待确认')
            if any(r['relation'] == 'UNKNOWN_PREEMPTION' for r in variable_relations):
                pending.append('抢占优先级待确认')
        classification_reason = result['reason'] + (('；' + '；'.join(pending)) if pending else '')
        if static_classification == 'UNKNOWN':
            finding_rules = sorted(set(['GS-COVERAGE-INCOMPLETE'] + gap_codes))
            risk_level, confidence = 'MEDIUM', 'LOW'
        else:
            finding_rules = sorted(rules) or ['GS-MULTI-CONTEXT']
            high = {"GS-MULTI-WRITER", "GS-RMW-INTERLEAVE", "GS-LOCAL-STATIC-REENTRANT", "GS-STALE-SNAPSHOT", "GS-OWNER-VIOLATION"}
            risk_level = "HIGH" if rules & high else "MEDIUM"
            if risk_level == "HIGH" and any(r.get("business_critical") for r in annotations):
                risk_level = "CRITICAL"
            confidence = "MEDIUM" if shared else "LOW"
        v.update(accesses=all_accesses, readers=sorted(readers), writers=sorted(writers), contexts=sorted(all_contexts),
                 protection_status=protection, annotations=annotations, audit_status='REVIEW_REQUIRED',
                 screening_reason=None, safe_reason_code=None, screening_blockers=gap_codes,
                 unreachable_access_count=len(all_accesses)-len(accesses), protection_details=protection_details,
                 protection_note=protection_note, analysis_coverage=coverage_status,
                 coverage_reasons=coverage_reasons, static_classification=static_classification,
                 classification_reason=classification_reason, concurrency_relations=variable_relations,
                 conflict_pairs=member_conflicts, conflict_pairs_capped=conflict_cap_info,
                 access_count=len(all_accesses),
                 gap_evidence=result['gaps'], pending_confirmation=pending,
                 resolved_call_path_count=sum(a['resolved_call_path_count'] for a in all_accesses))
        finding = dict(finding_id="GS-" + digest([sid, finding_rules, sorted(all_contexts)])[:16],
                       symbol_id=sid, variable_name=v["qualified_name"], rules=finding_rules, risk_level=risk_level,
                       confidence=confidence, status="NEED_OPENCODE_REVIEW",
                       protection_status=protection, declared_protection=declared, accesses=all_accesses,
                       definition=dict(file=v["definition_file"], line=v["definition_line"]),
                       context_pairs=[list(pair) for pair in itertools.combinations(sorted(all_contexts), 2)],
                        concurrency_relations=variable_relations, conflict_pairs=member_conflicts,
                        conflict_pairs_capped=conflict_cap_info,
                        concurrency_reason=classification_reason,
                       snapshots=snapshots[sid], uncertainties=uncertain,
                       screening_blockers=gap_codes, pending_confirmation=pending,
                       configured_preemption=[p for p in cfg["preemption"] if {p["higher"], p["lower"]} <= all_contexts],
                       configured_concurrency=[p for p in cfg["concurrency"] if set(p["contexts"]) <= all_contexts],
                       protection_note=protection_note, protection_details=protection_details,
                       static_classification=static_classification,
                        known_safe_annotations=[r for r in cfg["known_safe"] if r.get("resource") in {sid, v["name"], v["qualified_name"]}])
        findings.append(finding)
    # Parent records do not receive a root-level risk verdict: they only
    # summarize the independently analysed canonical members below them.
    members_by_root = defaultdict(list)
    for variable in analyzed_variables:
        if variable.get('root_symbol_id'):
            members_by_root[variable['root_symbol_id']].append(variable)
    for container in [v for v in facts['variables'] if v.get('resource_kind') == 'STRUCT_CONTAINER']:
        members = members_by_root.get(container['symbol_id'], [])
        states = Counter(member.get('static_classification', 'UNKNOWN') for member in members)
        container.update(accesses=by_var[container['symbol_id']],
                         whole_object_accesses=by_var[container['symbol_id']],
                         member_count=len(members), member_status_counts=dict(
                             safe=states['SAFE_PROVEN'], no_review=states['SHARED_NO_REVIEW'],
                             suspect=states['SUSPECT'], unknown=states['UNKNOWN']),
                         audit_status='STRUCT_CONTAINER', screening_reason=None,
                         static_classification='CONTAINER', analysis_coverage='COMPLETE',
                         classification_reason='结构体父节点只汇总成员；并发结论见各具体成员。')
    validate_member_fact_consistency(facts)
    # Non-variable blind spots also enter OpenCode, rather than only reviewing known shared objects.
    gap_groups = defaultdict(list)
    for u in facts['unknowns']:
        if not u.get('symbol_id'):
            gap_groups[(u['kind'],u.get('file'))].append(u)
    for (kind,file), issues in gap_groups.items():
        fids = sorted({u.get('function_id') or u.get('target_function_id') for u in issues
                       if u.get('function_id') or u.get('target_function_id')})
        finding = dict(finding_id="GAP-" + digest([kind,file,issues])[:16], symbol_id=None, variable_name=kind,
                       rules=[kind], risk_level="MEDIUM", confidence="LOW", status="NEED_OPENCODE_REVIEW",
                       protection_status="UNKNOWN", accesses=[], uncertainties=issues,
                       occurrence_count=len(issues),function_ids=fids,
                       definition=dict(file=file, line=issues[0].get("line")), function_id=fids[0] if len(fids)==1 else None)
        if scope.active and file and not scope.contains(file):
            finding.update(scope_role='dependency_evidence',
                concurrency_reason='目标变量的依赖证据缺口：该范围外代码只用于恢复访问与调用链，不排查其自身变量。')
        findings.append(finding)
    unknown_accesses = sum(not a["contexts"] and a['function_id'] not in unreachable for a in facts["accesses"])
    coverage['unreachable_functions'] = len(unreachable)
    coverage['unreachable_accesses'] = sum(a['function_id'] in unreachable for a in facts['accesses'])
    queued = {f['symbol_id'] for f in findings if f.get('symbol_id')}
    screened = {v['symbol_id'] for v in analyzed_variables if v.get('screening_reason')}
    ids = {v['symbol_id'] for v in analyzed_variables}
    if queued & screened or queued | screened != ids or len(ids) != len(analyzed_variables):
        raise ValueError('变量排查覆盖校验失败：每个变量必须唯一进入安全清单或逐项复核队列')
    coverage['variable_accountability'] = dict(total=len(ids), screened=len(screened),
        queued=len(queued), missing=0, duplicate_ids=0)
    for v in analyzed_variables:
        status = v.get('static_classification')
        if status not in {'SAFE_PROVEN', 'SHARED_NO_REVIEW', 'SUSPECT', 'UNKNOWN'}:
            raise ValueError('变量缺少显式静态分类：' + v['symbol_id'])
        v['safe_reason'] = v.get('classification_reason') if status == 'SAFE_PROVEN' else None
        v['safe_evidence'] = (dict(proof=v.get('screening_reason'), proof_code=v.get('safe_reason_code'),
            access_ids=[a['access_id'] for a in v.get('accesses', [])],
            contexts=v.get('contexts', []), protection_status=v.get('protection_status'),
            coverage=v.get('analysis_coverage')) if status == 'SAFE_PROVEN' else None)
        v['unknown_reason'] = v.get('coverage_reasons', []) if status == 'UNKNOWN' else []
        v['blocking_evidence'] = ([dict(g['evidence'], reason_code=g['code'])
                                   for g in v.get('gap_evidence', [])] if status == 'UNKNOWN' else [])
        from .classify import RECOVERY_ACTIONS
        v['required_context'] = [dict(kind=k, action=RECOVERY_ACTIONS.get(k,
            '按关联阻塞证据补齐源码、调用目标或硬件配置并重新分析。')) for k in v['unknown_reason']]
        if status == 'SAFE_PROVEN' and (not v['safe_reason'] or not v.get('screening_reason') or v['analysis_coverage'] != 'COMPLETE'):
            raise ValueError('SAFE_PROVEN 缺少完整证明：' + v['symbol_id'])
        if status == 'SHARED_NO_REVIEW' and (not v.get('screening_reason') or not v.get('shared_no_review_evidence')):
            raise ValueError('SHARED_NO_REVIEW 缺少完整证据：' + v['symbol_id'])
    static_counts = Counter(v['static_classification'] for v in analyzed_variables)
    if set(static_counts) - {'SAFE_PROVEN', 'SHARED_NO_REVIEW', 'SUSPECT', 'UNKNOWN'} or sum(static_counts.values()) != len(ids):
        raise ValueError('变量静态分类归账失败：TOTAL 必须等于 SAFE_PROVEN + SHARED_NO_REVIEW + SUSPECT + UNKNOWN')
    coverage['static_classification'] = dict(total=len(ids), proven=static_counts['SAFE_PROVEN'],
        no_review=static_counts['SHARED_NO_REVIEW'], suspect=static_counts['SUSPECT'],
        unknown=static_counts['UNKNOWN'])
    # Reason distributions + UNKNOWN fanout diagnostics (Section 19/26):
    # 诊断目标而非通过标准；超过阈值的 fanout 标记为疑似过度传播。
    from .classify import unknown_fanout_report
    fanout_debug = cfg['analysis'].get('max_unknown_fanout_debug', 0)
    if type(fanout_debug) is not int or fanout_debug < 0:
        raise ValueError('analysis.max_unknown_fanout_debug 必须是非负整数')
    fanout_threshold = fanout_debug or max(1, round(0.1 * len(analyzed_variables)))
    coverage['blocker_fanout'] = unknown_fanout_report(analyzed_variables, fanout_threshold)
    coverage['unknown_reason_distribution'] = {row['reason']: row['variables']
                                               for row in coverage['blocker_fanout']}
    coverage['safe_reason_distribution'] = dict(Counter(
        v.get('safe_reason_code') for v in analyzed_variables
        if v.get('static_classification') in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'} and v.get('safe_reason_code')))
    # 分类质量统计：原始共享写候选 → 最终各精化规则的降噪贡献（Section 14）。
    # raw 候选 = 存在 ≥2 个物理域访问且至少一方写的变量（旧引擎的 SUSPECT 口径）。
    raw_shared_write = 0
    for v in analyzed_variables:
        domains_seen = {model.domain.get(cid, cid) for cid in (v.get('contexts') or [])}
        if len(domains_seen) >= 2 and (v.get('writers') or []):
            raw_shared_write += 1
    proven_by_code = Counter(v.get('safe_reason_code') for v in analyzed_variables
                             if v.get('static_classification') == 'SAFE_PROVEN')
    coverage['classification_quality'] = dict(
        total=len(ids),
        raw_shared_write_candidates=raw_shared_write,
        safe_proven=static_counts['SAFE_PROVEN'],
        shared_no_review=static_counts['SHARED_NO_REVIEW'],
        suspect=static_counts['SUSPECT'],
        unknown=static_counts['UNKNOWN'],
        review_rate=round(100 * (static_counts['SUSPECT'] + static_counts['UNKNOWN']) / max(1, len(ids)), 2),
        refinements=dict(
            single_foreground=proven_by_code['SAFE_SINGLE_FOREGROUND'],
            read_only=proven_by_code['SAFE_READ_ONLY'] + proven_by_code['SAFE_MULTI_CONTEXT_READ_ONLY'],
            no_runtime_access=proven_by_code['SAFE_NO_RUNTIME_ACCESS'],
            single_irq=proven_by_code['SAFE_SINGLE_IRQ'],
            single_context=proven_by_code['SAFE_SINGLE_CONTEXT'],
            non_interleaving=proven_by_code['SAFE_NON_INTERLEAVING'],
            effective_protection=proven_by_code['SAFE_EFFECTIVE_PROTECTION'],
            init_only_write=proven_by_code['SAFE_INIT_ONLY_WRITE'],
            single_writer_no_review=static_counts['SHARED_NO_REVIEW'],
        ))
    coverage['struct_containers'] = sum(v.get('resource_kind') == 'STRUCT_CONTAINER' for v in facts['variables'])
    coverage["unknown_accesses"] = unknown_accesses
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
                   "调用链展示全部已解析无环函数路径；各调用点与递归边保存在调用图。显式路径上限超出时扫描失败，不返回截断结论。",
                   "保护事件 DETECTED 不等于 EFFECTIVE；只有 CFG 全路径和竞争者模型均完整才可排除冲突。Ownership 与屏障本身不等于互斥。",
                   "指针与回调采用跨函数、字段区分的保守目标集合；数组下标合并，不证明具体运行目标。DMA 方向来自 HAL API 契约；生命周期和 Cache 协议仍须复核。",
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
