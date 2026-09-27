"""Conservative CFG proof that initialization writes precede IRQ activation.

This first implementation deliberately requires an explicit NVIC disable in
main.  Reaching main does not establish reset NVIC state: a bootloader, startup
routine, or constructor may already have enabled an interrupt.  SysTick, DMA,
faults, opaque calls in the initialization prefix, and helper-function writes
are not covered by this proof.
"""
import re
from collections import defaultdict

from .interrupts import irq_key


ENABLE = {'NVIC_EnableIRQ', 'HAL_NVIC_EnableIRQ'}
DISABLE = {'NVIC_DisableIRQ', 'HAL_NVIC_DisableIRQ'}
NEUTRAL = {
    'HAL_NVIC_SetPriority', 'NVIC_SetPriority',
    'HAL_NVIC_SetPriorityGrouping', 'NVIC_SetPriorityGrouping',
    '__disable_irq', '__enable_irq', '__get_PRIMASK', '__set_PRIMASK',
    '__get_BASEPRI', '__set_BASEPRI', '__set_BASEPRI_MAX',
    '__DMB', '__DSB', '__ISB',
}
READS = {'READ', 'WHOLE_OBJECT_READ'}
WRITES = {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE'}


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


def prove_initialization(variable, accesses, facts, contexts, cfg):
    """Return an inspectable proof, or None without weakening classification.

    Every writer must be in an acyclic, unconditional part of main.  For each
    competing IRQ, an explicit disable must dominate every writer, and every
    writer must dominate the unique enable.  No unresolved call or pointer
    write may occur in the entry-to-enable prefix.  Runtime read loops after
    enable are permitted; a loop containing a writer is rejected.
    """
    runtime = [access for access in accesses if access.get('access_kind') in READS | WRITES]
    writers = [access for access in runtime if access['access_kind'] in WRITES]
    if not writers or not any(access['access_kind'] in READS for access in runtime):
        return None
    if any(access.get('access_kind') == 'ADDRESS_TAKEN' for access in accesses):
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
        if access.get('function_id') == main_id and access.get('access_kind') in WRITES:
            ident = _node_for(access, nodes)
            if ident is None or ident in prefix:
                return None
    return dict(proof='INIT_WRITES_BEFORE_IRQ_ENABLE', function_id=main_id,
                cfg_id=graph['cfg_id'], write_node_ids=sorted(write_nodes),
                write_access_ids=[access['access_id'] for access in writers],
                irq_barriers=barriers, prefix_node_ids=sorted(prefix),
                initial_state_evidence='Explicit NVIC disable dominates every write; no reset-state assumption',
                limitation='Direct writes in main and ordinary NVIC IRQs only')
