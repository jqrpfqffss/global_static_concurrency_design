"""Connect C setjmp continuations to resolved longjmp execution sources.

These are control transfers, not ordinary calls.  The matching jump buffer
limits the new edges to functions whose continuation can actually resume.
Unknown buffer identity remains a function-local execution-context gap.
"""

from collections import defaultdict, deque


SETJMP = {'setjmp', '_setjmp', 'sigsetjmp', '__sigsetjmp'}
LONGJMP = {'longjmp', '_longjmp', 'siglongjmp', '__longjmp'}
RUNTIME = {'READ', 'WRITE', 'RMW', 'WHOLE_OBJECT_READ', 'WHOLE_OBJECT_WRITE',
           'DMA_READ', 'DMA_WRITE'}


def _buffer(argument):
    """Exact static jump-buffer address, without a name-based guess."""
    if argument.get('op') == 'addr':
        argument = argument.get('value', {})
    if argument.get('op') == 'loc' and argument.get('id', '').startswith('obj:'):
        return argument['id']
    return None


def _suffix_calls(graph, site, known_functions):
    if not graph:
        return None
    nodes = {node['id']: node for node in graph.get('nodes', ())}
    starts = [node for node in nodes.values()
              if node.get('op') == 'call' and node.get('name') in SETJMP
              and node.get('file') == site.get('file')
              and node.get('offset') == site.get('offset')]
    if len(starts) != 1:
        return None
    seen, pending, callees = set(), deque(starts[0].get('successors', ())), {}
    while pending:
        ident = pending.popleft()
        if ident in seen:
            continue
        seen.add(ident)
        node = nodes.get(ident)
        if not node:
            return None
        # An unsupported expression *before* setjmp does not invalidate the
        # known continuation. An unknown operation reachable after it might
        # hide a call or jump, so that suffix cannot be closed.
        if node.get('op') == 'unknown':
            return None
        callee = node.get('callee') if node.get('op') == 'call' else None
        if callee in known_functions:
            callees[(callee, node.get('file'), node.get('offset'))] = node
        pending.extend(node.get('successors', ()))
    return list(callees.values())


def recover_nonlocal_jumps(facts):
    setjumps, longjumps, graphs = defaultdict(list), defaultdict(list), {}
    for graph in facts.get('control_flow', ()):
        graphs[graph['function_id']] = graph
    for call in facts.get('semantic_calls', ()):
        name = call.get('name')
        if name not in SETJMP | LONGJMP:
            continue
        arguments = call.get('arguments', ())
        buffer = _buffer(arguments[0]) if arguments else None
        (setjumps if name in SETJMP else longjumps)[buffer].append(call)
    if not setjumps or not longjumps:
        return

    known_functions = {row['function_id'] for row in facts.get('functions', ())}
    discovered, edges = [], set()
    for buffer, entries in setjumps.items():
        sources = longjumps.get(buffer, ()) if buffer is not None else ()
        unresolved_source = bool(longjumps.get(None)) or buffer is None
        for entry in entries:
            continuation = _suffix_calls(graphs.get(entry['function_id']), entry, known_functions)
            if continuation is None or unresolved_source:
                facts['unknowns'].append(dict(kind='UNRESOLVED_NONLOCAL_JUMP',
                    target_function_id=entry['function_id'], function_id=entry['function_id'],
                    file=entry.get('file'), line=entry.get('line'), offset=entry.get('offset'),
                    buffer_location=buffer,
                    reason='无法完整确定匹配 jump buffer 的非局部恢复路径或执行来源'))
            if not sources or continuation is None:
                continue
            for source in sources:
                for node in continuation:
                    callee = node['callee']
                    key = (source['function_id'], callee, source.get('file'), source.get('offset'),
                           entry.get('file'), entry.get('offset'))
                    if key in edges:
                        continue
                    edges.add(key)
                    row = dict(caller_function_id=source['function_id'],
                        callee_function_id=callee, callee_name=node.get('name'),
                        call_kind='NONLOCAL_JUMP_CONTINUATION',
                        file=node.get('file'), line=node.get('line'), offset=node.get('offset'),
                        source_text='setjmp continuation after matching longjmp',
                        nonlocal_jump_source=dict(file=source.get('file'), line=source.get('line'),
                                                  function_id=source['function_id']),
                        nonlocal_buffer_location=buffer)
                    facts['calls'].append(row)
                    discovered.append(row)
                # Direct accesses in the setjmp owner after its save point do
                # not gain a new caller edge. Mark their storage locally until
                # context propagation can represent source-site continuations.
                for access in facts.get('accesses', ()):
                    if (access.get('function_id') == entry['function_id']
                            and access.get('file') == entry.get('file')
                            and access.get('offset', -1) >= entry.get('offset', 0)
                            and access.get('access_kind') in RUNTIME):
                        facts['unknowns'].append(dict(kind='NONLOCAL_JUMP_CONTEXT',
                            symbol_id=access['symbol_id'], function_id=entry['function_id'],
                            file=access.get('file'), line=access.get('line'),
                            offset=access.get('offset'), buffer_location=buffer,
                            jump_source_function_id=source['function_id']))
    facts['nonlocal_jump_edges'] = discovered
