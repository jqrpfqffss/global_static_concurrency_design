"""Map logical entry labels onto physical execution domains."""
from collections import defaultdict

from .evidence import PhysicalExecutionContext
from dataclasses import asdict


def normalize_contexts(contexts, roots, graph, funcs, cfg, facts):
    contexts = dict(contexts)
    # A pattern matching several vector symbols describes several hardware
    # IRQs. A configuration label is not proof that they are one executor.
    for cid, context in list(contexts.items()):
        if context['kind'] not in {'ISR', 'IRQ'} or context.get('vector') or context.get('irq'):
            continue
        vectors = sorted(fid for fid in roots[cid] if fid in funcs and (
            funcs[fid]['name'].endswith('IRQHandler') or funcs[fid]['name'] in {
                'SysTick_Handler', 'PendSV_Handler', 'SVC_Handler', 'NMI_Handler', 'HardFault_Handler',
                'MemManage_Handler', 'BusFault_Handler', 'UsageFault_Handler'}))
        if len(vectors) > 1:
            remainder = roots[cid] - set(vectors)
            roots[cid] = {vectors[0]} | remainder
            contexts[cid] = dict(context, vector=funcs[vectors[0]]['name'])
            for fid in vectors[1:]:
                new_id = cid + ':' + funcs[fid]['name']
                contexts[new_id] = dict(context, id=new_id, vector=funcs[fid]['name'])
                roots[new_id] = {fid}
    foreground_roots = {fid for cid in contexts if contexts[cid]['kind'] in {'MAIN', 'FOREGROUND'}
                        for fid in roots[cid]}
    foreground_reachable, todo = set(foreground_roots), list(foreground_roots)
    while todo:
        for child in graph[todo.pop()] - foreground_reachable:
            foreground_reachable.add(child)
            todo.append(child)
    executor_reachable = {fid for cid, c in contexts.items() if c['kind'] != 'CALLBACK' for fid in roots[cid]}
    todo = list(executor_reachable)
    while todo:
        for child in graph[todo.pop()] - executor_reachable:
            executor_reachable.add(child)
            todo.append(child)
    physical, aliases = {}, {}
    for cid, context in contexts.items():
        kind = context['kind']
        entries = roots[cid]
        if (kind == 'CALLBACK' and entries and entries <= executor_reachable
                and not context.get('asynchronous') and not context.get('reentrant')):
            # A synchronous callback inherits every caller, including IRQs.
            # Its descriptive label must not create another asynchronous root.
            continue
        cooperative = (kind in {'TASK', 'CALLBACK'} and entries and entries <= foreground_reachable
                       and not context.get('reentrant') and not context.get('asynchronous')
                       and context.get('discovery') == 'configured')
        if kind in {'MAIN', 'FOREGROUND'} or cooperative:
            ident = 'FOREGROUND'
        elif kind in {'ISR', 'IRQ'}:
            vectors = sorted({funcs[f]['name'] for f in entries if f in funcs})
            hardware_vectors = [v for v in vectors if v.endswith('IRQHandler') or v in {
                'SysTick_Handler', 'PendSV_Handler', 'SVC_Handler', 'NMI_Handler', 'HardFault_Handler',
                'MemManage_Handler', 'BusFault_Handler', 'UsageFault_Handler'}]
            ident = 'IRQ:' + str(context.get('vector') or context.get('irq') or
                (hardware_vectors[0] if len(hardware_vectors) == 1 else cid))
        elif kind == 'DMA':
            ident = 'DMA:' + str(context.get('channel') or context.get('stream') or cid)
        elif kind in {'CALLBACK', 'UNKNOWN_CONTEXT'}:
            ident = 'UNKNOWN_CONTEXT:' + cid
        else:
            ident = 'EXTERNAL_ASYNC:' + cid
        context['physical_id'] = ident
        context['physical_kind'] = ident.split(':', 1)[0]
        context['cooperative_foreground'] = bool(cooperative)
        # The hardware does not recursively preempt the same active vector.
        if ident.startswith('IRQ:'):
            context['reentrant'] = False
        group = physical.setdefault(ident, PhysicalExecutionContext(ident, context['physical_kind']))
        group.logical_context_ids.append(cid)
        group.entry_functions.extend(sorted(entries))
        aliases[cid] = ident
    # Preserve a familiar logical identifier for compatibility while merging
    # all roots of the same physical executor before call-path propagation.
    output, normalized_roots = {}, defaultdict(set)
    logical_map = {}
    for ident, group in physical.items():
        preferred = next((c for c in group.logical_context_ids if contexts[c]['kind'] in {'MAIN', 'FOREGROUND'}),
                         group.logical_context_ids[0])
        output[preferred] = dict(contexts[preferred], aliases=group.logical_context_ids)
        if ident == 'FOREGROUND':
            output[preferred]['kind'] = 'MAIN'
            output[preferred]['reentrant'] = False
        elif ident.startswith('IRQ:'):
            output[preferred]['kind'] = 'ISR'
        for cid in group.logical_context_ids:
            logical_map[cid] = preferred
            # A cooperative task is an ordinary callee, not another root.
            if not contexts[cid].get('cooperative_foreground'):
                normalized_roots[preferred].update(roots[cid])
    facts['physical_contexts'] = [asdict(group) for group in physical.values()]
    facts['logical_context_map'] = logical_map
    return output, normalized_roots
