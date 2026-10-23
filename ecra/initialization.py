"""Conservative CFG proof that initialization writes precede async activation."""
import re
from collections import defaultdict
from pathlib import Path

from .interrupts import irq_key
from .async_semantics import is_async_enable, async_irq_arg, canonical_cmsis_api
from .compilation import cmake_build_directory
from .input_snapshot import read_analysis_text, select_analysis_files


def constructor_map_directory(root,cfg):
    analysis = cfg.get('analysis',{})
    return cmake_build_directory(root,analysis) if 'cmake' in analysis else Path(root)/'build/ecra'


ENABLE = {'NVIC_EnableIRQ', 'HAL_NVIC_EnableIRQ'}
DISABLE = {'NVIC_DisableIRQ', 'HAL_NVIC_DisableIRQ'}
NEUTRAL = {
    'HAL_NVIC_SetPriority', 'NVIC_SetPriority',
    'HAL_NVIC_SetPriorityGrouping', 'NVIC_SetPriorityGrouping',
    'HAL_SYSTICK_Config', 'SysTick_Config',
    '__disable_irq', '__enable_irq', '__get_PRIMASK', '__set_PRIMASK',
    '__get_BASEPRI', '__set_BASEPRI', '__set_BASEPRI_MAX',
    '__DMB', '__DSB', '__ISB',
}
READS = {'READ', 'WHOLE_OBJECT_READ'}
WRITES = {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE'}


def _startup_constructor_proof(facts, cfg, reset_id, main_id):
    """Check calls before main and linked constructor entries for a reset proof.

    The assembly call graph records resolvable C functions. It cannot model
    __libc_init_array by itself; the linker map bounds the functions that
    routine may execute before main. An unrecognized constructor voids the
    assumption that target IRQs are still disabled at main entry.
    """
    entry = next((row for row in facts.get('vector_entries', ())
                  if row.get('function_id') == reset_id and row.get('slot') == 1), None)
    if not entry or not entry.get('file'):
        return dict(source='synthetic_or_unavailable_startup')
    if Path(entry['file']).suffix.lower() != '.s':
        return dict(source=entry['file'], startup_model='C reset handler AST and call graph')
    root_name = cfg.get('project', {}).get('root')
    if not root_name:
        return None
    root = Path(root_name)
    source = root / entry['file']
    try:
        assembly = read_analysis_text(source,encoding='utf-8',errors='replace')
    except OSError:
        return None
    before_main = assembly.split('bl main', 1)[0]
    calls = re.findall(r'^\s*bl(?:\.w)?\s+([A-Za-z_]\w*)\b', before_main, re.M)
    if 'main' not in re.findall(r'^\s*bl(?:\.w)?\s+(main)\b', assembly, re.M):
        return None
    known = {row['name'] for row in facts.get('functions', ())}
    if any(name not in known | {'__libc_init_array'} for name in calls):
        return None
    if '__libc_init_array' not in calls:
        return dict(source=str(source), calls=calls, constructors='none')
    build = constructor_map_directory(root,cfg)
    maps = select_analysis_files(build,'*.map')
    if len(maps) != 1:
        return None
    try:
        map_text = read_analysis_text(maps[0],encoding='utf-8',errors='replace')
    except OSError:
        return None
    sections = {}
    for section in ('preinit_array', 'init_array'):
        match = re.search(r'^\.' + section + r'\s+0x[0-9A-Fa-f]+\s+0x([0-9A-Fa-f]+)\s*$',
                          map_text, re.M)
        if not match:
            return None
        sections[section] = int(match.group(1), 16)
    if sections['preinit_array'] != 0:
        return None
    if sections['init_array']:
        contributors = re.findall(r'^[ \t]+\.init_array(?:\.[^\s]+)?[ \t]+0x[0-9A-Fa-f]+[ \t]+0x([0-9A-Fa-f]+)[ \t]+(\S+)',
                                  map_text, re.M)
        if (sections['init_array'] != 4 or len(contributors) != 1
                or int(contributors[0][0], 16) != 4
                or not contributors[0][1].replace('\\', '/').endswith('/crtbegin.o')):
            return None
    return dict(source=str(source), calls=calls, constructor_map=str(maps[0]),
                preinit_bytes=sections['preinit_array'], init_bytes=sections['init_array'],
                constructors='GCC crtbegin frame_dummy only')


def _phase_entries_closed(accesses, facts, contexts, cfg):
    """Reject phase proofs with an unmodelled executor before IRQ activation.

    A source access ID is shared by every invocation of its function.  Seeing
    that ID once during main initialization does not prove that another
    foreground entry cannot call it later.  Other asynchronous roots may also
    activate the target IRQ while main is writing, including NMI or an IRQ
    inherited from a bootloader.  Until their closure is proved inert, fail
    closed for the initialization optimization.
    """
    writers = [row for row in accesses if row.get('access_kind') in WRITES]
    if not writers:
        return True
    target_irq_contexts = {cid for row in accesses for cid in row.get('contexts', ())
                           if contexts.get(cid, {}).get('physical_kind') == 'IRQ'}
    roots = [row for row in facts.get('context_bindings', ()) if row.get('call_depth') == 0]
    call_graph = defaultdict(set)
    for call in facts.get('calls', ()):
        if call.get('callee_function_id'):
            call_graph[call['caller_function_id']].add(call['callee_function_id'])

    def reaches(start, target):
        seen, pending = set(), [start]
        while pending:
            fid = pending.pop()
            if fid == target:
                return True
            if fid in seen:
                continue
            seen.add(fid)
            pending.extend(call_graph.get(fid, set()) - seen)
        return False

    functions = {row['function_id']: row for row in facts.get('functions', ())}
    main_ids = {fid for fid, row in functions.items() if row.get('name') == 'main'}
    if len(main_ids) != 1:
        return False
    reset_ids = {row.get('function_id') for row in facts.get('vector_entries', ())
                 if row.get('kind') == 'MAIN' and row.get('slot') == 1}
    allowed = main_ids | reset_ids
    writer_functions = {row.get('function_id') for row in writers}
    enable_functions = {event.get('function_id') for event in facts.get('irq_priority_events', ())
                        if is_async_enable(event.get('api_name', ''), cfg)}
    function_ids = {row['function_id'] for row in facts.get('functions', ())}
    opaque_callers = {row.get('caller_function_id') for row in facts.get('calls', ())
                      if not row.get('callee_function_id') or row.get('callee_function_id') not in function_ids}
    def closure(start):
        seen, pending = set(), [start]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(call_graph.get(current, set()) - seen)
        return seen
    for call in facts.get('calls', ()):
        callee = call.get('callee_function_id')
        if (call.get('call_kind') == 'ASSEMBLY_LITERAL_CALL'
                and call.get('caller_function_id') in reset_ids and callee in main_ids):
            continue
        if (callee and (call.get('call_kind') == 'CONFIGURED' or call.get('offset') is None)
                and any(reaches(callee, writer) for writer in writer_functions)):
            # A configured or locationless edge contributes context reachability
            # but cannot be placed before the enable in a complete Clang CFG.
            return False
    for root in roots:
        cid = root.get('context_id')
        fid = root.get('function_id')
        kind = contexts.get(cid, {}).get('physical_kind')
        if kind not in {'FOREGROUND', None} and cid not in target_irq_contexts:
            reachable = closure(fid)
            if reachable & (writer_functions | enable_functions | opaque_callers):
                return False
        if contexts.get(cid, {}).get('physical_kind') != 'FOREGROUND':
            continue
        if fid not in allowed and any(reaches(fid, writer) for writer in writer_functions):
            return False
    return True


def _reachable(start, edges):
    reached, pending = set(), [start]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(edges.get(current, ()))
    return reached


def _node_for(site, nodes, operation=None):
    candidates = [node for node in nodes.values()
                  if (operation is None or node['op'] == operation)
                  and node['op'] not in {'entry', 'exit', 'join', 'branch'}
                  and node.get('file') == site.get('file')
                  and node.get('offset', -1) <= site.get('offset', -2) < node.get('end_offset', -1)]
    if not candidates:
        return None
    return min(candidates, key=lambda node: (node['end_offset'] - node['offset'], node['id']))['id']


def _interprocedural_initialization(variable, accesses, facts, contexts, cfg):
    """Prove a one-way INIT -> IRQ runtime phase across ordinary helpers.

    The abstract state is deliberately small: for every competing external
    IRQ it tracks the current enable state and a sticky ``runtime_started``
    bit. A target write is an initialization write only while every IRQ is
    definitely disabled and none has ever been enabled. Known helper calls are
    interpreted through their Clang CFG; opaque calls/stores invalidate the
    pre-runtime state on that path. This proves ordering from control flow, not
    source line order or a function-name convention.
    """
    runtime = [access for access in accesses if access.get('access_kind') in READS | WRITES]
    writers = [access for access in runtime if access['access_kind'] in WRITES]
    if not writers or not any(access['access_kind'] in READS for access in runtime):
        return None
    if any(not access.get('contexts') for access in runtime):
        return None

    functions = {function['function_id']: function for function in facts.get('functions', [])}
    ids = {context_id for access in runtime for context_id in access['contexts']}
    if any(contexts.get(context_id, {}).get('reentrant') for context_id in ids):
        return None

    def physical_kind(context_id):
        context = contexts.get(context_id, {})
        return context.get('physical_kind') or {
            'MAIN': 'FOREGROUND', 'FOREGROUND': 'FOREGROUND',
            'ISR': 'IRQ', 'IRQ': 'IRQ',
        }.get(context.get('kind'), context.get('kind'))

    foreground = {context_id for context_id in ids if physical_kind(context_id) == 'FOREGROUND'}
    irq_contexts = {context_id for context_id in ids if physical_kind(context_id) == 'IRQ'}
    if not foreground or not irq_contexts or ids != foreground | irq_contexts:
        return None
    # Runtime IRQ/DMA writers are real writers. INIT_ONLY may remove only
    # foreground writes that precede read-only asynchronous consumers.
    if any(not set(access['contexts']) <= foreground for access in writers):
        return None

    irq_by_context = defaultdict(set)
    for binding in facts.get('context_bindings', []):
        if binding.get('call_depth') != 0 or binding.get('context_id') not in irq_contexts:
            continue
        name = functions.get(binding.get('function_id'), {}).get('name', '')
        if not name.endswith('IRQHandler') or name.startswith('HAL_'):
            return None
        irq_by_context[binding['context_id']].add(irq_key(name))
    if any(len(irq_by_context[context_id]) != 1 for context_id in irq_contexts):
        return None
    irqs = sorted({next(iter(irq_by_context[context_id])) for context_id in irq_contexts})
    irq_index = {irq: index for index, irq in enumerate(irqs)}

    cfgs = {graph['function_id']: graph for graph in facts.get('control_flow', [])
            if graph.get('complete')}
    main_ids = [fid for fid, function in functions.items() if function.get('name') == 'main']
    if len(main_ids) != 1 or main_ids[0] not in cfgs:
        return None
    main_id = main_ids[0]

    call_graph = defaultdict(set)
    for call in facts.get('calls', []):
        if call.get('callee_function_id'):
            call_graph[call['caller_function_id']].add(call['callee_function_id'])

    def reaches(start, target):
        seen, pending = set(), [start]
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(call_graph.get(current, ()))
        return False

    reset_entries = {entry.get('function_id') for entry in facts.get('vector_entries', [])
                     if entry.get('kind') == 'MAIN' and entry.get('slot') == 1}
    reset_entries = {entry for entry in reset_entries if reaches(entry, main_id)}
    if len(reset_entries) == 1:
        # Assembly startup has a verified vector and call edges but no C CFG.
        # Check every known pre-main source for an enable before using the
        # architectural reset state at the main entry.
        reset_id = next(iter(reset_entries))
        pre_main = set()
        pending = [reset_id]
        while pending:
            fid = pending.pop()
            if fid in pre_main or fid == main_id:
                continue
            pre_main.add(fid)
            pending.extend(call_graph.get(fid, ()))
        startup_enable = any(event.get('function_id') in pre_main
                             and is_async_enable(event.get('api_name', ''), cfg)
                             for event in facts.get('irq_priority_events', ()))
        if startup_enable:
            return None
        function_ids = set(functions)
        if any(call.get('caller_function_id') in pre_main
               and call.get('callee_function_id') not in function_ids
               for call in facts.get('calls', ())):
            return None
        startup_evidence = _startup_constructor_proof(facts, cfg, reset_id, main_id)
        if startup_evidence is None:
            return None
        start_id = main_id
        initial = ((0,) * len(irqs), (False,) * len(irqs))
        reset_proven = True
    else:
        start_id = main_id
        initial = ((-1,) * len(irqs), (False,) * len(irqs))
        reset_proven = False
        startup_evidence = None

    writer_nodes = defaultdict(list)
    expected_writes = {access['access_id'] for access in writers}
    for access in writers:
        graph = cfgs.get(access['function_id'])
        if not graph:
            return None
        nodes = {node['id']: node for node in graph['nodes']}
        ident = _node_for(access, nodes)
        if ident is None:
            return None
        writer_nodes[(access['function_id'], ident)].append(access)

    switch_nodes = defaultdict(list)
    enable_events, disable_events = [], []
    for event in facts.get('irq_priority_events', []):
        if event.get('api_name') not in DISABLE and not is_async_enable(event.get('api_name', ''), cfg):
            continue
        graph = cfgs.get(event.get('function_id'))
        if not graph:
            continue
        ident = _node_for(event, {node['id']: node for node in graph['nodes']}, 'call')
        if ident is not None:
            switch_nodes[(event['function_id'], ident)].append(event)

    callees = defaultdict(set)
    for call in facts.get('calls', []):
        graph = cfgs.get(call.get('caller_function_id'))
        if not graph:
            continue
        ident = _node_for(call, {node['id']: node for node in graph['nodes']}, 'call')
        if ident is not None and call.get('callee_function_id'):
            callees[(call['caller_function_id'], ident)].add(call['callee_function_id'])

    writer_sites = {(access.get('file'), access.get('offset')) for access in writers}
    uncertain_store_sites = {(issue.get('file'), issue.get('offset'))
                             for issue in facts.get('unknowns', ())
                             if issue.get('kind') == 'UNRESOLVED_POINTEE'}
    opaque_store_nodes = set()
    for access in facts.get('indirect_accesses', []):
        mode = access.get('mode', access.get('access_kind'))
        if mode not in WRITES or (access.get('file'), access.get('offset')) in writer_sites:
            continue
        # A resolved indirect store to known peripheral storage is not an
        # arbitrary IRQ enable or alias of this variable. Unresolved stores
        # (including raw NVIC MMIO) remain phase barriers.
        if (access.get('file'), access.get('offset')) not in uncertain_store_sites:
            continue
        graph = cfgs.get(access.get('function_id'))
        if graph:
            ident = _node_for(access, {node['id']: node for node in graph['nodes']})
            if ident is not None:
                opaque_store_nodes.add((access['function_id'], ident))

    # Only calls in the backward slice of a target write or an async switch
    # can change this variable's phase. Complete, unrelated helpers need no
    # CFG; this matters for vendor delay/math helpers with unsupported syntax.
    reverse = defaultdict(set)
    opaque_callers = set()
    for call in facts.get('calls', []):
        caller, callee = call.get('caller_function_id'), call.get('callee_function_id')
        api_name = canonical_cmsis_api(call.get('callee_name', ''))
        if callee in functions and api_name not in NEUTRAL:
            reverse[callee].add(caller)
        elif not is_async_enable(api_name, cfg) and api_name not in NEUTRAL:
            opaque_callers.add(caller)
    relevant_functions = ({fid for fid, _ in writer_nodes}
                          | {fid for fid, _ in switch_nodes}
                          | {fid for fid, _ in opaque_store_nodes}
                          | opaque_callers)
    pending_relevant = list(relevant_functions)
    while pending_relevant:
        for caller in reverse.get(pending_relevant.pop(), ()):
            if caller not in relevant_functions:
                relevant_functions.add(caller)
                pending_relevant.append(caller)
    writer_relevant = {fid for fid, _ in writer_nodes}
    pending_writers = list(writer_relevant)
    while pending_writers:
        for caller in reverse.get(pending_writers.pop(), ()):
            if caller not in writer_relevant:
                writer_relevant.add(caller)
                pending_writers.append(caller)

    failure = []
    seen_writes = set()
    seen_enables, seen_disables = set(), set()
    visited_functions = set()
    cache = {}

    def unknown_transition(state):
        _current, runtime_started = state
        # An opaque operation may enable any asynchronous source. Preserve the
        # sticky phase bit so a later disable cannot turn a runtime write back
        # into an initialization write.
        return ((-1,) * len(irqs), tuple(True for _ in runtime_started))

    def event_transition(state, event):
        current, runtime_started = map(list, state)
        arguments = event.get('arguments', [])
        argument_index = (0 if event['api_name'] in DISABLE else
                          async_irq_arg(event['api_name'], cfg))
        spelling = (arguments[argument_index].strip()
                    if argument_index is not None and argument_index < len(arguments) else '')
        target = irq_key(spelling) if re.fullmatch(r'[A-Za-z_]\w*_IRQn', spelling) else None
        enable = is_async_enable(event['api_name'], cfg)
        if target not in irq_index:
            if target is None or enable:
                # Enabling another IRQ before a candidate write permits that
                # handler to enable a competing IRQ (directly or through a
                # helper). Unless its entire async closure is proved inert,
                # the target is no longer definitely disabled.
                current = [-1] * len(irqs)
                if enable:
                    runtime_started = [True] * len(irqs)
            return tuple(current), tuple(runtime_started)
        index = irq_index[target]
        current[index] = 1 if enable else 0
        if enable:
            runtime_started[index] = True
            seen_enables.add(target)
            enable_events.append(event)
        else:
            seen_disables.add(target)
            disable_events.append(event)
        return tuple(current), tuple(runtime_started)

    def interpret(function_id, entry_state, stack=()):
        key = function_id, entry_state
        if key in cache:
            return cache[key]
        if function_id in stack:
            failure.append('RECURSIVE_INITIALIZATION_CALL')
            return set()
        graph = cfgs.get(function_id)
        if not graph:
            if function_id not in writer_relevant and seen_writes == expected_writes:
                # This helper cannot reach another target write. Once every
                # competing source has started, its unsupported CFG cannot
                # invalidate the already established write-before-enable fact.
                return {entry_state}
            failure.append('MISSING_INITIALIZATION_CFG:' + str(function_id))
            return set()
        visited_functions.add(function_id)
        nodes = {node['id']: node for node in graph['nodes']}
        states = defaultdict(set)
        states[graph['entry']].add(entry_state)
        pending = [(graph['entry'], entry_state)]
        while pending and not failure:
            ident, state = pending.pop()
            node = nodes[ident]
            produced = {state}
            target_writes = writer_nodes.get((function_id, ident), ())
            if target_writes:
                for current, runtime_started in produced:
                    if any(value != 0 for value in current) or any(runtime_started):
                        failure.append('WRITE_MAY_OCCUR_AFTER_ASYNC_ENABLE')
                        break
                seen_writes.update(access['access_id'] for access in target_writes)
            if failure:
                break
            if (function_id, ident) in opaque_store_nodes:
                produced = {unknown_transition(state) for state in produced}
            node_events = switch_nodes.get((function_id, ident), ())
            if node_events:
                for event in node_events:
                    produced = {event_transition(state, event) for state in produced}
            elif node.get('op') == 'call':
                name = node.get('name')
                targets = callees.get((function_id, ident), set())
                if not targets and node.get('callee'):
                    targets = {node['callee']}
                if name in NEUTRAL:
                    pass
                elif targets:
                    returned = set()
                    for target in targets:
                        for state in produced:
                            if target not in functions:
                                returned.add(unknown_transition(state))
                            elif target in relevant_functions:
                                returned.update(interpret(target, state, stack + (function_id,)))
                            else:
                                returned.add(state)
                    produced = returned
                else:
                    produced = {unknown_transition(state) for state in produced}
            for successor in node.get('successors', ()):
                for state in produced:
                    if state not in states[successor]:
                        states[successor].add(state)
                        pending.append((successor, state))
        outputs = set(states.get(graph['exit'], ())) if not failure else set()
        cache[key] = outputs
        return outputs

    interpret(start_id, initial)
    if failure or seen_writes != expected_writes or seen_enables != set(irqs):
        return None
    if not reset_proven and seen_disables != set(irqs):
        return None
    return dict(proof='INIT_WRITES_BEFORE_ASYNC_ENABLE', function_id=main_id,
                entry_function_id=start_id, cfg_id=cfgs[start_id]['cfg_id'],
                write_access_ids=sorted(seen_writes),
                write_sites=[dict(function_id=fid, node_id=node,
                                  access_ids=sorted(access['access_id'] for access in rows))
                             for (fid, node), rows in sorted(writer_nodes.items())],
                irq_barriers=[dict(irq=irq,
                                   disables=[event for event in disable_events
                                             if irq_key((event.get('arguments') or [''])[0]) == irq],
                                   enables=[event for event in enable_events
                                            if (async_irq_arg(event['api_name'], cfg) is not None
                                                and async_irq_arg(event['api_name'], cfg) < len(event.get('arguments', ()))
                                                and irq_key(event['arguments'][async_irq_arg(event['api_name'], cfg)]) == irq)])
                              for irq in irqs],
                visited_functions=sorted(visited_functions),
                initial_state_evidence=('Verified Cortex-M reset vector entry; configurable NVIC IRQs start disabled'
                                        if reset_proven else
                                        'Explicit NVIC disable on every path to each initialization write'),
                startup_evidence=startup_evidence,
                limitation='Configurable external NVIC IRQ consumers; no DMA, SysTick, fault, or opaque pre-write path')


def prove_initialization(variable, accesses, facts, contexts, cfg):
    """Prove every target write occurs before competing async activation.

    Prefer the interprocedural CFG phase interpreter. The legacy direct-main
    dominance proof remains a conservative fallback for supported NVIC cases.
    """
    if not _phase_entries_closed(accesses, facts, contexts, cfg):
        return None
    interprocedural = _interprocedural_initialization(variable, accesses, facts, contexts, cfg)
    if interprocedural:
        return interprocedural
    runtime = [access for access in accesses if access.get('access_kind') in READS | WRITES]
    writers = [access for access in runtime if access['access_kind'] in WRITES]
    if not writers or not any(access['access_kind'] in READS for access in runtime):
        return None
    if any(not access.get('contexts') for access in runtime):
        return None
    functions = {function['function_id']: function for function in facts.get('functions', [])}
    writer_functions = {access['function_id'] for access in writers}
    if len(writer_functions) != 1:
        return None
    main_id = next(iter(writer_functions))
    if functions.get(main_id, {}).get('name') != 'main':
        return None
    ids = {context_id for access in runtime for context_id in access['contexts']}
    if any(contexts.get(context_id, {}).get('reentrant') for context_id in ids):
        return None
    main_contexts = {context_id for context_id in ids
                     if contexts.get(context_id, {}).get('kind') in {'MAIN', 'FOREGROUND'}}
    irq_contexts = {context_id for context_id in ids
                    if contexts.get(context_id, {}).get('kind') in {'ISR', 'IRQ'}}
    if not main_contexts or not irq_contexts or ids != main_contexts | irq_contexts:
        return None
    if any(not set(access['contexts']) <= main_contexts or access.get('conditional_ancestor')
           for access in writers):
        return None

    irq_by_context = defaultdict(set)
    for binding in facts.get('context_bindings', []):
        if binding.get('call_depth') != 0 or binding['context_id'] not in irq_contexts:
            continue
        name = functions.get(binding['function_id'], {}).get('name', '')
        # Configurable external IRQs only. SysTick/faults cannot be disabled
        # with NVIC_DisableIRQ, and have different activation semantics.
        if not name.endswith('IRQHandler') or name.startswith('HAL_'):
            return None
        irq_by_context[binding['context_id']].add(irq_key(name))
    if any(len(irq_by_context[context_id]) != 1 for context_id in irq_contexts):
        return None
    irqs = {next(iter(irq_by_context[context_id])) for context_id in irq_contexts}

    graph = next((graph for graph in facts.get('control_flow', [])
                  if graph['function_id'] == main_id), None)
    if not graph or not graph.get('complete'):
        return None
    nodes = {node['id']: node for node in graph['nodes']}
    edges = {ident: node['successors'] for ident, node in nodes.items()}
    reachable = _reachable(graph['entry'], edges)
    predecessors = defaultdict(set)
    for ident in reachable:
        for successor in edges.get(ident, ()):
            predecessors[successor].add(ident)
    dominators = {ident: {ident} if ident == graph['entry'] else set(reachable) for ident in reachable}
    changed = True
    while changed:
        changed = False
        for ident in reachable - {graph['entry']}:
            parents = predecessors[ident] & reachable
            common = set.intersection(*(dominators[parent] for parent in parents)) if parents else set()
            updated = {ident} | common
            if updated != dominators[ident]:
                dominators[ident] = updated
                changed = True
    write_nodes = {_node_for(access, nodes) for access in writers}
    if None in write_nodes or not write_nodes <= reachable:
        return None
    if any(ident in _reachable(successor, edges) for ident in write_nodes for successor in edges[ident]):
        return None

    switches = defaultdict(lambda: defaultdict(list))
    for event in facts.get('irq_priority_events', []):
        if event.get('api_name') not in ENABLE | DISABLE:
            continue
        arguments = event.get('arguments', [])
        argument = arguments[0].strip() if arguments else ''
        # A numerical/dynamic IRQ argument cannot be mapped to a physical
        # vector by spelling; do not guess that it targets an unrelated IRQ.
        if not re.fullmatch(r'[A-Za-z_]\w*_IRQn', argument):
            return None
        target = irq_key(argument)
        if target not in irqs:
            continue
        if event.get('function_id') != main_id or event.get('conditional_ancestor'):
            return None
        operation = 'enable' if event['api_name'] in ENABLE else 'disable'
        ident = _node_for(event, nodes, 'call')
        if ident is None or ident not in reachable:
            return None
        switches[target][operation].append((ident, event))
    barriers = []
    prefix = set()
    for irq in sorted(irqs):
        pair = switches[irq]
        if len(pair['disable']) != 1 or len(pair['enable']) != 1:
            return None
        disable_node, disable_event = pair['disable'][0]
        enable_node, enable_event = pair['enable'][0]
        if any(disable_node not in dominators[writer] or writer not in dominators[enable_node]
               for writer in write_nodes):
            return None
        if any(enable_node in _reachable(successor, edges) for successor in edges[enable_node]):
            return None
        prefix.update(_reachable(enable_node, predecessors) & reachable)
        barriers.append(dict(irq=irq, disable_node=disable_node, enable_node=enable_node,
                             disable=disable_event, enable=enable_event))
    for ident in prefix:
        node = nodes[ident]
        if node['op'] in {'unknown', 'invalidate_locals'}:
            return None
        if node['op'] == 'call' and node.get('name') not in NEUTRAL | ENABLE | DISABLE:
            return None
    # Direct memory-mapped peripheral stores can enable sources without an
    # NVIC API.  Unresolved indirect stores in the prefix invalidate proof.
    for access in facts.get('indirect_accesses', []):
        # Pointer extraction calls this field ``mode``; canonical direct
        # accesses use ``access_kind``. Accept either fact schema explicitly.
        mode = access.get('mode', access.get('access_kind'))
        if access.get('function_id') == main_id and mode in WRITES:
            ident = _node_for(access, nodes)
            if ident is None or ident in prefix:
                return None
    return dict(proof='INIT_WRITES_BEFORE_IRQ_ENABLE', function_id=main_id,
                cfg_id=graph['cfg_id'], write_node_ids=sorted(write_nodes),
                write_access_ids=[access['access_id'] for access in writers],
                irq_barriers=barriers, prefix_node_ids=sorted(prefix),
                initial_state_evidence='Explicit NVIC disable dominates every write; no reset-state assumption',
                limitation='Direct writes in main and ordinary NVIC IRQs only')
