from collections import Counter, defaultdict, deque
import fnmatch
import itertools
import re

from .common import digest


TABLES = ("variables", "functions", "accesses", "calls", "unknowns", "protection_events", "registrations", "snapshots",
          "pointer_constraints", "semantic_calls", "indirect_accesses")


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
    facts["unknowns"].extend(issues)
    return contexts, paths


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
    from .points_to import enrich
    enrich(facts, cfg)
    known = {f['function_id'] for f in facts['functions']}
    summarized = {'memcpy', 'memmove', 'memset', 'memcmp', 'xTaskCreate', 'xTaskCreateStatic',
                  'osThreadNew', 'xTaskCreatePinnedToCore'}
    external_sites = {(u.get('function_id'), u.get('file'), u.get('line'), u.get('callee'))
                      for u in facts['unknowns'] if u['kind'] == 'EXTERNAL_CALLEE'}
    for call in facts['calls']:
        site = (call['caller_function_id'], call['file'], call['line'], call.get('callee_name'))
        if (call['call_kind'] in {'DIRECT', 'INDIRECT_RESOLVED'} and call['callee_function_id'] not in known
                and call.get('callee_name') not in summarized and site not in external_sites):
            facts['unknowns'].append(dict(kind='EXTERNAL_CALLEE', function_id=site[0],
                file=site[1], line=site[2], callee=site[3]))
            external_sites.add(site)
    contexts, paths = context_graph(facts, cfg)
    entry_ids = {b['function_id'] for b in facts['context_bindings'] if b['call_depth'] == 0}
    facts['assembly_references'] = [u for u in facts['unknowns'] if u['kind'] in
                                   {'ASSEMBLY_FUNCTION_REFERENCE', 'ASSEMBLY_SYMBOL_REFERENCE'}]
    facts['unknowns'] = [u for u in facts['unknowns'] if not (u['kind'] == 'ASSEMBLY_FUNCTION_REFERENCE'
                         and u.get('target_function_id') in entry_ids)]
    # Establish reachability before scope filtering: a dependency can supply an
    # entry into a target function. Address-taken functions and attributed entry
    # points are possible roots even when no ordinary caller is present.
    graph = defaultdict(set)
    for call in facts['calls']:
        graph[call['caller_function_id']].add(call.get('callee_function_id'))
    reachability_gaps = {u['kind'] for u in facts['unknowns'] if u['kind'] in {
        'PARSE_FAILED', 'POINTS_TO_LIMIT', 'INLINE_ASSEMBLY', 'CPP_SEMANTICS_REVIEW',
        'MULTIPLE_BUILD_VARIANTS', 'SOURCE_CHANGED_DURING_SCAN', 'HEADER_CHANGED_DURING_SCAN',
        'UNMATCHED_CONTEXT', 'UNRESOLVED_CONFIG_CALL', 'UNRESOLVED_TASK_ENTRY',
        'CMSIS_V1_TASK_ENTRY', 'UNRESOLVED_REGISTERED_ENTRY', 'UNMATCHED_ENTRY_REGISTRATION',
        'ASSEMBLY_SOURCE_REVIEW'}}
    if coverage.get('translation_units_failed') or coverage.get('unlisted_sources'):
        reachability_gaps.add('BUILD_INCOMPLETE')
    possible = set(paths)
    possible.update(u['target_function_id'] for u in facts['unknowns'] if u.get('target_function_id'))
    possible.update(f['function_id'] for f in facts['functions'] if f.get('entry_attributes'))
    opaque_callers = {u.get('function_id') for u in facts['unknowns']
                      if u['kind'] in {'EXTERNAL_CALLEE', 'INLINE_ASSEMBLY'}}
    external_functions = {f['function_id'] for f in facts['functions'] if f.get('linkage') == 'EXTERNAL'}
    external_promoted = False
    queue = deque(possible)
    while queue:
        caller = queue.popleft()
        if caller in opaque_callers and not external_promoted:
            queue.extend(sorted(external_functions - possible))
            possible.update(external_functions)
            external_promoted = True
        for callee in graph[caller]:
            if callee and callee not in possible:
                possible.add(callee)
                queue.append(callee)
    unreachable = {f['function_id'] for f in facts['functions'] if f['function_id'] not in possible
                   and contexts and not reachability_gaps}
    for f in facts['functions']:
        f['reachability'] = ('REACHABLE' if f['function_id'] in paths else
                             'PROVEN_UNREACHABLE' if f['function_id'] in unreachable else 'UNKNOWN_ENTRY')
    from .scope import AuditScope, select_facts
    scope = AuditScope(project_root, cfg['analysis'])
    select_facts(facts, scope, coverage)
    by_var, events = defaultdict(list), defaultdict(list)
    for e in facts["protection_events"]:
        events[e["function_id"]].append(e)
    for a in facts["accesses"]:
        a["contexts"] = sorted(paths.get(a["function_id"], {}))
        a['reachability'] = ('PROVEN_UNREACHABLE' if a['function_id'] in unreachable else
                             'REACHABLE' if a['contexts'] else 'UNKNOWN_ENTRY')
        a["call_chains"] = paths.get(a["function_id"], {})
        a["protection_evidence"] = [e for e in events[a["function_id"]] if e["event_kind"] in {"lock_enter", "lock_exit"}]
        by_var[a["symbol_id"]].append(a)
    snapshots = defaultdict(list)
    for s in facts["snapshots"]:
        snapshots[s["symbol_id"]].append(s)
    # Pre-index uncertainties; avoid rescanning the entire gap list per variable
    # in large projects. Propagate upstream missing-entry evidence along ALL
    # graph edges, not only the shortest displayed witness.
    by_symbol, tainted = defaultdict(list), defaultdict(set)
    graph = defaultdict(set)
    for call in facts['calls']:
        if call.get('callee_function_id'):
            graph[call['caller_function_id']].add(call['callee_function_id'])
    global_gaps, external_gaps = set(), set()
    if coverage.get('translation_units_failed'):
        global_gaps.add('PARSE_FAILED')
    if coverage.get('unlisted_sources'):
        global_gaps.add('SOURCE_NOT_IN_DATABASE')
    if coverage.get('unlisted_headers'):
        global_gaps.add('HEADERS_NOT_INCLUDED')
    for u in facts['unknowns']:
        if u.get('symbol_id'):
            by_symbol[u['symbol_id']].append(u)
            continue
        kind = u['kind']
        if kind in {'PARSE_FAILED', 'POINTS_TO_LIMIT', 'MULTIPLE_BUILD_VARIANTS', 'SOURCE_CHANGED_DURING_SCAN',
                    'HEADER_CHANGED_DURING_SCAN', 'SOURCE_NOT_IN_DATABASE', 'HEADERS_NOT_INCLUDED',
                    'CPP_SEMANTICS_REVIEW', 'UNMATCHED_ENTRY_REGISTRATION', 'UNRESOLVED_REGISTERED_ENTRY',
                    'AMBIGUOUS_ENTRY_REGISTRATION', 'REGISTERED_CONTEXT_KIND_CONFLICT',
                    'ASSEMBLY_SOURCE_REVIEW', 'UNRESOLVED_CONFIG_CALL', 'UNMATCHED_CONTEXT'}:
            global_gaps.add(kind)
        if kind in {'EXTERNAL_CALLEE', 'INLINE_ASSEMBLY', 'UNRESOLVED_POINTEE'} and u.get('function_id') not in unreachable:
            external_gaps.add(kind)
        if kind == 'INLINE_ASSEMBLY' and u.get('function_id') not in unreachable:
            global_gaps.add(kind)
        fid = u.get('target_function_id') or u.get('function_id')
        if fid:
            tainted[fid].add(kind)
    queue = deque(tainted)
    while queue:
        fid = queue.popleft()
        for callee in graph[fid]:
            extra = tainted[fid] - tainted[callee]
            if extra:
                tainted[callee].update(extra)
                queue.append(callee)
    if cfg['project'].get('cm4_enabled') or cfg['project'].get('concurrency_model', 'single_core_preemptive') != 'single_core_preemptive':
        global_gaps.add('UNMODELED_CONCURRENCY')
    findings = []
    for v in facts["variables"]:
        sid = v["symbol_id"]
        # Supplemental variables come from files outside the compile database
        # or inactive conditional branches. They are inventory-only; without
        # the current build's macros and flags, their access evidence is not
        # comparable to compiled-code analysis.
        if v.get("coverage_source") in ("supplemental", "inactive_branch"):
            v.update(accesses=[], readers=[], writers=[], contexts=[], protection_status="NONE",
                     annotations=[], audit_status="SUPPLEMENTAL_INVENTORY",
                     screening_reason=None, screening_blockers=['ACCESS_NOT_ANALYZED'])
            site = next(iter(v.get('definitions', []) or v.get('declarations', [])), {})
            findings.append(dict(finding_id='GS-' + digest([sid, 'GS-SUPPLEMENTAL-UNANALYZED'])[:16],
                symbol_id=sid, variable_name=v['qualified_name'], rules=['GS-SUPPLEMENTAL-UNANALYZED'],
                risk_level='MEDIUM', confidence='LOW', status='NEED_OPENCODE_REVIEW',
                protection_status='UNKNOWN', accesses=[], uncertainties=[],
                definition=dict(file=v.get('definition_file') or site.get('file'),
                                line=v.get('definition_line') or site.get('line')),
                screening_blockers=['ACCESS_NOT_ANALYZED']))
            continue
        all_accesses = by_var[sid]
        accesses = [a for a in all_accesses if a['function_id'] not in unreachable]
        readers = set(itertools.chain.from_iterable(a["contexts"] for a in accesses if a["access_kind"] in {"READ", "RMW"}))
        writers = set(itertools.chain.from_iterable(a["contexts"] for a in accesses if a["access_kind"] in {"WRITE", "RMW"}))
        all_contexts = set(itertools.chain.from_iterable(a["contexts"] for a in accesses))
        rules = {"GS-PARSE-INCOMPLETE"} if v.get("parse_status") == "FAILED" else set()
        uncertain = [u for u in by_symbol[sid] if u.get('function_id') not in unreachable]
        # Unknown edges above an access can introduce more contexts, even if one path is known.
        if any(not a["contexts"] for a in accesses):
            rules.add("GS-UNKNOWN-CONTEXT")
        if any(a["access_kind"] == "ADDRESS_TAKEN" or a.get("via_alias") for a in accesses) or uncertain:
            rules.add("GS-INDIRECT-ACCESS")
        if not accesses and not v["is_const"]:
            rules.add("GS-NO-ACCESS-EVIDENCE")
        if not v["definition_file"]:
            rules.add("GS-DEFINITION-MISSING")
        if any(u["kind"] == "DMA_SHARED_REVIEW" for u in uncertain):
            rules.add("DMA_SHARED_REVIEW")
        reentrant = any(contexts[c].get("reentrant", False) for c in all_contexts)
        shared = len(all_contexts) >= 2 or reentrant
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
        annotations = [r for r in cfg["resources"] if r.get("symbol_id", r.get("name")) in {sid, v["name"], v["qualified_name"]}]
        if any(r.get("owner_context") and writers - {r["owner_context"]} for r in annotations):
            rules.add("GS-OWNER-VIOLATION")
        declared = [p for p in cfg["protection"] if p.get("resource") in {sid, v["name"], v["qualified_name"]}]
        source_protection = any(a["protection_evidence"] for a in accesses)
        protection = "PARTIAL" if source_protection else ("DECLARED_ONLY" if declared else "UNKNOWN")
        blockers = set(global_gaps)
        # Files outside the active build cannot name a non-escaped internal
        # object. Keep their inventory gaps, without poisoning every static.
        escaped = any(a['access_kind'] == 'ADDRESS_TAKEN' or a.get('via_alias') for a in accesses)
        if v.get('linkage') != 'EXTERNAL' and not escaped:
            blockers.difference_update({'SOURCE_NOT_IN_DATABASE', 'HEADERS_NOT_INCLUDED', 'PARSE_FAILED'})
            if v.get('parse_status') == 'FAILED':
                blockers.add('PARSE_FAILED')
        if v.get('linkage') == 'EXTERNAL':
            blockers.update(external_gaps)
        for a in accesses:
            local_gaps = tainted[a['function_id']]
            if v.get('linkage') != 'EXTERNAL' and not escaped:
                local_gaps = local_gaps - {'EXTERNAL_CALLEE', 'UNRESOLVED_POINTEE', 'POINTER_DEREFERENCE'}
            blockers.update(local_gaps)
        if not rules and blockers:
            rules.add('GS-COVERAGE-INCOMPLETE')
        # A variable can be conclusively removed from the *concurrency* queue
        # when all observed accesses were parsed, rooted and non-aliased, and
        # no conflicting pair exists. This is deliberately narrower than a
        # general "safe" claim: uncovered assembly/DMA/dynamic callbacks still
        # create a rule above and therefore cannot enter this branch.
        site_keys = {(a.get('function_id'), a.get('file'), a.get('offset'), a.get('access_path', ''), a.get('access_kind'))
                     for a in accesses if a['access_kind'] in {'READ', 'WRITE', 'RMW'}}
        screened_reason = None
        # Missing execution context is immaterial to read/read concurrency.
        # Missing writes, escaped addresses, hardware and incomplete parsing
        # remain blockers. A count of source sites alone is never a proof.
        only_reads = bool(accesses) and all(a['access_kind'] == 'READ' for a in accesses)
        effective_blockers = set(blockers)
        if only_reads:
            effective_blockers.difference_update({'FUNCTION_ADDRESS', 'INDIRECT_CALL'})
        proof_rules = rules - {'GS-NO-ACCESS-EVIDENCE', 'GS-UNKNOWN-CONTEXT', 'GS-COVERAGE-INCOMPLETE'}
        if not proof_rules and not uncertain and not escaped and not effective_blockers:
            if not accesses:
                screened_reason = 'UNREACHABLE_ACCESSORS' if all_accesses else 'NO_RUNTIME_ACCESSES'
            elif only_reads:
                screened_reason = 'ONLY_READS'
            elif len(site_keys) == 1 and len(all_contexts) == 1 and not reentrant and all(a['contexts'] for a in accesses):
                screened_reason = 'SINGLE_ACCESS_SITE'
            elif len(all_contexts) == 1 and not reentrant and all(a['contexts'] for a in accesses):
                screened_reason = 'SINGLE_EXECUTION_CONTEXT'
        if screened_reason:
            rules.clear()
            blockers = effective_blockers
        elif not rules:
            rules.add('GS-COVERAGE-INCOMPLETE')
        audit_status = 'SCREENED_NO_CONCURRENCY_RISK' if screened_reason else 'REVIEW_REQUIRED'
        v.update(accesses=all_accesses, readers=sorted(readers), writers=sorted(writers), contexts=sorted(all_contexts),
                 protection_status=protection, annotations=annotations, audit_status=audit_status,
                 screening_reason=screened_reason, screening_blockers=sorted(blockers),
                 unreachable_access_count=len(all_accesses)-len(accesses))
        if not rules:
            continue
        high = {"GS-MULTI-WRITER", "GS-RMW-INTERLEAVE", "GS-LOCAL-STATIC-REENTRANT", "GS-STALE-SNAPSHOT", "GS-OWNER-VIOLATION"}
        level = "HIGH" if rules & high else "MEDIUM"
        if level == "HIGH" and any(r.get("business_critical") for r in annotations):
            level = "CRITICAL"
        finding = dict(finding_id="GS-" + digest([sid, sorted(rules), sorted(all_contexts)])[:16],
                       symbol_id=sid, variable_name=v["qualified_name"], rules=sorted(rules), risk_level=level,
                       confidence="MEDIUM" if shared else "LOW", status="NEED_OPENCODE_REVIEW",
                       protection_status=protection, declared_protection=declared, accesses=all_accesses,
                       definition=dict(file=v["definition_file"], line=v["definition_line"]),
                       context_pairs=[list(pair) for pair in itertools.combinations(sorted(all_contexts), 2)],
                       concurrency_reason="保守建模：不同任务/中断/未知回调可交错；优先级、启动阶段和锁覆盖待复核",
                       snapshots=snapshots[sid], uncertainties=uncertain,
                       screening_blockers=sorted(blockers),
                       configured_preemption=[p for p in cfg["preemption"] if {p["higher"], p["lower"]} <= all_contexts],
                       configured_concurrency=[p for p in cfg["concurrency"] if set(p["contexts"]) <= all_contexts],
                       protection_note="PARTIAL 仅表示找到相关函数中的锁 API，未证明控制流覆盖或中断屏蔽范围。",
                       known_safe_annotations=[r for r in cfg["known_safe"] if r.get("resource") in {sid, v["name"], v["qualified_name"]}])
        findings.append(finding)
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
    screened = {v['symbol_id'] for v in facts['variables'] if v.get('screening_reason')}
    ids = {v['symbol_id'] for v in facts['variables']}
    if queued & screened or queued | screened != ids or len(ids) != len(facts['variables']):
        raise ValueError('变量排查覆盖校验失败：每个变量必须唯一进入安全清单或逐项复核队列')
    coverage['variable_accountability'] = dict(total=len(ids), screened=len(screened),
        queued=len(queued), missing=0, duplicate_ids=0)
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
                   "调用链展示每个上下文的一条最短证据链；完整直接调用图保存在 facts.json/facts.db。",
                   "保护事件和 owner 仅作证据，不证明临界区覆盖，也不会抑制候选。",
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
