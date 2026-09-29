"""Control-flow mask interpretation. Facts, derived states and proof stay distinct.

The lattice is a known register value or UNKNOWN. PRIMASK is one bit, never a
nesting counter. Calls use their CFG and all return paths; recursion, missing
bodies, unsupported control flow and unordered expressions invalidate proof.
"""
from collections import defaultdict, deque


NEUTRAL = {'__DMB', '__DSB', '__ISB', 'memcpy', 'memmove', 'memset', 'memcmp',
           'HAL_NVIC_SetPriority', 'NVIC_SetPriority', 'HAL_NVIC_SetPriorityGrouping',
           'NVIC_SetPriorityGrouping'}


def join(left, right):
    if left is None:
        return dict(right)
    return {key: left.get(key) if left.get(key) == right.get(key) else None
            for key in left.keys() | right.keys()}


class MaskAnalysis:
    def __init__(self, facts, cfg):
        self.facts, self.cfg = facts, cfg
        self.graphs = {g['function_id']: g for g in facts.get('control_flow', [])}
        self.by_function = defaultdict(list)
        self.observations = defaultdict(list)
        self.windows = defaultdict(list)
        self.effects = {}
        self.memo = {}
        # Caller stack affects recursive summaries. Every function able to
        # reach a recursive SCC retains the stack in its cache key; acyclic
        # descendants can reuse their exact (context,input-state) summary.
        # Otherwise a diamond call graph re-evaluates the same CFG along an
        # exponential number of identical caller paths.
        call_graph = {fid: {node.get('callee') for node in graph['nodes']
                           if node['op'] == 'call' and node.get('callee') in self.graphs}
                      for fid,graph in self.graphs.items()}
        reverse, colors, cycle_entries = defaultdict(set), {}, set()
        for caller, callees in call_graph.items():
            for callee in callees:
                reverse[callee].add(caller)
        for start in call_graph:
            if colors.get(start):
                continue
            colors[start] = 1
            stack = [(start,iter(call_graph[start]))]
            while stack:
                fid,children = stack[-1]
                child = next(children,None)
                if child is None:
                    colors[fid] = 2
                    stack.pop()
                elif colors.get(child) == 1:
                    cycle_entries.add(child)
                elif not colors.get(child):
                    colors[child] = 1
                    stack.append((child,iter(call_graph[child])))
        self.stack_sensitive = set(cycle_entries)
        pending = list(cycle_entries)
        while pending:
            for caller in reverse[pending.pop()] - self.stack_sensitive:
                self.stack_sensitive.add(caller)
                pending.append(caller)
        self.context_kinds = defaultdict(set)
        for access in facts['accesses']:
            if access['access_kind'] in {'READ','WRITE','RMW'}:
                for cid in access.get('contexts', []):
                    self.context_kinds[(access['symbol_id'],cid)].add(access['access_kind'])
        self.api = {
            '__disable_irq': ('irq', 'set', 1), '__enable_irq': ('irq', 'set', 0),
            '__get_PRIMASK': ('irq', 'get', None), '__set_PRIMASK': ('irq', 'restore', None),
            '__get_BASEPRI': ('base', 'get', None), '__set_BASEPRI': ('base', 'restore', None),
            '__set_BASEPRI_MAX': ('base', 'max', None),
        }
        for section in cfg.get('critical_sections', []):
            if section['type'] not in {'irq_mask', 'primask'}:
                continue
            for field, action, value in [('enter', 'set', 1), ('exit', 'set', 0),
                                         ('save', 'save', 1), ('restore', 'restore', None)]:
                if field in section:
                    self.api[section[field]] = ('irq', action, value)
        for access in facts['accesses']:
            self.by_function[access['function_id']].append(access)
        # A generic helper can touch different storage in different physical
        # contexts. Propagate touched objects separately for (function,context)
        # so an IRQ B invocation cannot create windows for IRQ A's pointee.
        self.touched = defaultdict(set)
        for fid, accesses in self.by_function.items():
            for access in accesses:
                if access['access_kind'] not in {'READ','WRITE','RMW'}:
                    continue
                for cid in access.get('contexts', []):
                    if 'allowed_contexts' not in access or cid in access['allowed_contexts']:
                        self.touched[(fid,cid)].add(access['symbol_id'])
        incoming = defaultdict(set)
        for fid, graph in self.graphs.items():
            for n in graph['nodes']:
                if n['op'] == 'call':
                    incoming[n.get('callee')].add(fid)
        permitted = {cid: {tuple(edge) for edge in edges}
                     for cid,edges in facts.get('context_call_graph', {}).get('edges', {}).items()}
        pending, queued = deque(self.touched), set(self.touched)
        while pending:
            callee,cid = pending.popleft()
            queued.discard((callee,cid))
            for caller in incoming.get(callee, ()):
                if cid in permitted and (caller,callee) not in permitted[cid]:
                    continue
                key = (caller,cid)
                additions = self.touched[(callee,cid)] - self.touched[key]
                if additions:
                    self.touched[key].update(additions)
                    if key not in queued:
                        pending.append(key)
                        queued.add(key)

    def value(self, expression, state):
        if 'constant' in expression:
            return expression['constant']
        if 'local' in expression:
            return state.get(expression['local'])
        api = self.api.get(expression.get('call'))
        if api and api[1] in {'get', 'save'}:
            return state.get(api[0])
        return None

    def transfer(self, node, before, cid, stack):
        state = dict(before)
        interruption = False
        if node['op'] == 'unknown':
            state = {key: None for key in state}
            state.update(irq=None, base=None)
            interruption = True
        elif node['op'] == 'assign':
            state[node['local']] = self.value(node['value'], before)
        elif node['op'] == 'invalidate_locals':
            state = {key: value if key in {'irq','base'} else None for key,value in state.items()}
        elif node['op'] == 'call':
            api = self.api.get(node['name'])
            if api:
                register, action, literal = api
                argument = self.value(next(iter(node['arguments']), {}), before)
                if action in {'set', 'save'}:
                    state[register] = literal
                elif action == 'restore':
                    state[register] = (argument & 1) if register == 'irq' and argument is not None else argument
                elif action == 'max':
                    previous = state.get('base')
                    state['base'] = (None if previous is None or argument is None else
                                     argument if previous == 0 else previous if argument == 0 else min(previous, argument))
            elif node['name'] in NEUTRAL:
                if node['name'] in {'memset','memcpy','memmove'}:
                    state = {key: value if key in {'irq','base'} else None for key,value in state.items()}
            elif node.get('callee') in self.graphs and node['callee'] not in stack and len(stack) < 48:
                graph = self.graphs[node['callee']]
                initial = dict(irq=before.get('irq'), base=before.get('base'))
                for parameter, argument in zip(graph['parameters'], node['arguments']):
                    initial[parameter] = self.value(argument, before)
                result, interruption = self.evaluate(node['callee'], initial, cid, stack)
                # A pointer parameter may modify a saved key. Until local
                # pointee effects are modeled, do not reuse pre-call values.
                state = {key: None for key in state}
                state.update(irq=result.get('irq'), base=result.get('base'))
            else:
                state = {key: None for key in state}
                state.update(irq=None, base=None)
                interruption = True
        return state, interruption

    def evaluate(self, fid, initial, cid, stack=()):
        key = (fid, cid, tuple(sorted(initial.items())), stack if fid in self.stack_sensitive else ())
        if key in self.memo:
            return self.memo[key]
        graph = self.graphs[fid]
        nodes = graph['nodes']
        if not graph['complete']:
            initial = dict(initial, irq=None, base=None)
        incoming, outgoing, interruptible = {}, {}, {}
        incoming[graph['entry']] = initial
        pending = deque([graph['entry']])
        steps = 0
        while pending:
            ident = pending.popleft()
            after, broken = self.transfer(nodes[ident], incoming[ident], cid, stack + (fid,))
            if not graph['complete']:
                after.update(irq=None, base=None)
                broken = True
            outgoing[ident] = after
            interruptible[ident] = broken
            for successor in nodes[ident]['successors']:
                merged = join(incoming.get(successor), after)
                if merged != incoming.get(successor):
                    incoming[successor] = merged
                    pending.append(successor)
            steps += 1
            if steps > max(1000, len(nodes) * 100):
                for state in incoming.values():
                    state.update(irq=None, base=None)
                break
        by_symbol = defaultdict(set)
        for access in self.by_function[fid]:
            if 'allowed_contexts' in access and cid not in access['allowed_contexts']:
                continue
            candidates = [n for n in nodes if n['op'] not in {'entry', 'exit', 'join', 'branch'}
                          and n['file'] == access['file']
                          and n['offset'] <= access.get('offset', -1) < n['end_offset']]
            if not candidates:
                observation = dict(context_id=cid, irq_state='UNKNOWN', basepri=None, cfg_id=graph['cfg_id'])
            else:
                chosen = min(candidates, key=lambda n: (n['end_offset'] - n['offset'], n['id']))
                ident = chosen['id']
                state = incoming.get(ident, {})
                observation = dict(context_id=cid, irq_state={0:'ENABLED', 1:'DISABLED'}.get(state.get('irq'), 'UNKNOWN'),
                                   basepri=state.get('base'), cfg_id=graph['cfg_id'], node_id=ident,
                                   reachable=ident in incoming, complete=graph['complete'])
                if access['access_kind'] in {'READ', 'WRITE', 'RMW'} and ident in incoming:
                    by_symbol[access['symbol_id']].add(ident)
            self.observations[access['access_id']].append(observation)
        # Include descendant accesses at their parent call sites. Otherwise
        # Read(); enable(); disable(); Write() hides the open window when
        # Read and Write live in different helper functions.
        child_sites = defaultdict(set)
        for n in nodes:
            if n['op'] == 'call' and n['id'] in incoming:
                for sid in self.touched.get((n.get('callee'),cid), set()):
                    child_sites[sid].add(n['id'])
        for sid, sites in child_sites.items():
            if self.context_kinds[(sid,cid)] == {'RMW'}:
                # Each self-contained RMW is a separate transaction; its
                # own callee window is checked using the inherited mask.
                continue
            combined = by_symbol[sid] | sites
            if len(combined) >= 2:
                by_symbol[sid] = combined
        # Check the whole access-to-access window, including calls that unmask
        # and restore. Protected endpoints alone are not a protected snapshot.
        reverse = defaultdict(set)
        for n in nodes:
            for successor in n['successors']:
                reverse[successor].add(n['id'])
        for sid, sites in by_symbol.items():
            can_reach = set(sites)
            todo = list(sites)
            while todo:
                for previous in reverse[todo.pop()]:
                    if previous not in can_reach:
                        can_reach.add(previous)
                        todo.append(previous)
            between = set(sites)
            # A sequence/loop of individually masked RMWs need not remain
            # masked between transactions. Separate READ/WRITE snapshots do.
            todo = [] if self.context_kinds[(sid,cid)] == {'RMW'} else list(sites)
            while todo:
                for successor in nodes[todo.pop()]['successors']:
                    if successor in can_reach and successor not in between:
                        between.add(successor)
                        todo.append(successor)
            mask_states = [incoming.get(i, {}) for i in between]
            self.windows[(sid, cid)].append(dict(function_id=fid, cfg_id=graph['cfg_id'],
                node_ids=sorted(between), complete=graph['complete'],
                primask=graph['complete'] and all(s.get('irq') == 1 for s in mask_states)
                        and not any(interruptible.get(i, False) for i in between),
                basepri_values=sorted({s['base'] for s in mask_states if s.get('base') is not None}),
                basepri_known=graph['complete'] and all(s.get('base') is not None for s in mask_states)
                              and not any(interruptible.get(i, False) for i in between)))
        final = outgoing.get(graph['exit'], dict(irq=None, base=None))
        broken = any(interruptible.values()) or any(state.get('irq') != 1 for state in incoming.values())
        result = (final, broken)
        self.memo[key] = result
        return result

    def run(self):
        for binding in self.facts['context_bindings']:
            if binding['call_depth'] == 0 and binding['function_id'] in self.graphs:
                self.evaluate(binding['function_id'], dict(irq=0, base=0), binding['context_id'])
        for access in self.facts['accesses']:
            access['mask_states'] = self.observations.get(access['access_id'], [])
        self.facts['mask_windows'] = [dict(symbol_id=sid, context_id=cid, **row)
            for (sid, cid), rows in self.windows.items() for row in rows]


def assess(accesses, events, contexts, facts, cfg):
    relevant = [a for a in accesses if a['access_kind'] in {'READ', 'WRITE', 'RMW'}]
    ids = {c for a in relevant for c in a.get('contexts', [])}
    mains = {c for c in ids if contexts[c]['kind'] == 'MAIN'}
    isrs = {c for c in ids if contexts[c]['kind'] == 'ISR'}
    related = {a['function_id'] for a in relevant}
    for a in relevant:
        graph_slice = facts.get('call_graph_slices', {}).get(a.get('call_graph_slice'))
        if graph_slice is not None:
            related.update(graph_slice['function_ids'])
        else:
            for paths in a.get('all_call_chains', {}).values():
                related.update(f for path in paths for f in path)
    detected = [e for fid in related for e in events.get(fid, [])]
    details = [dict(access_id=a['access_id'], file=a['file'], line=a['line'],
                    states=a.get('mask_states', [])) for a in relevant]
    if not detected:
        return 'NOT_FOUND', details, '未发现关联路径上的同步或中断屏蔽操作。'
    if all(e.get('protection_type') == 'barrier' for e in detected):
        return 'INEFFECTIVE', details, 'DMB/DSB/ISB 只约束内存或指令顺序，不屏蔽中断，也不提供互斥。'
    windows = [w for w in facts.get('mask_windows', []) if relevant and
               w['symbol_id'] == relevant[0]['symbol_id'] and w['context_id'] in mains]
    funcs = {f['function_id']: f for f in facts['functions']}
    unmaskable = any(funcs.get(b['function_id'], {}).get('name') in {'NMI_Handler', 'HardFault_Handler'}
                     for b in facts['context_bindings'] if b['call_depth'] == 0 and b['context_id'] in isrs)
    unmaskable |= any(contexts[c].get('unmaskable') for c in isrs)
    main_accesses = [a for a in relevant if set(a.get('contexts', [])) & mains]
    complete = all(a.get('contexts') for a in relevant) and all(
        any(s['context_id'] == c and s.get('complete') for s in a.get('mask_states', []))
        for a in main_accesses for c in set(a['contexts']) & mains)
    isr_pairs = [r for r in facts.get('preemption_relations', []) if set(r['contexts']) <= isrs]
    participants = bool(mains and isrs) and ids == mains | isrs and not unmaskable
    participants &= all(r['relation'] == 'SERIAL' for r in isr_pairs)
    primask = bool(windows) and all(w['primask'] for w in windows)
    if complete and participants and primask:
        return 'EFFECTIVE', details, 'CFG 全路径和被调函数证明完整访问窗口持续 PRIMASK=DISABLED；竞争方仅为可屏蔽 ISR。'
    base_found = any(e.get('protection_type') == 'basepri' for e in detected)
    if base_found:
        from .interrupts import basepri_status
        status, reason = basepri_status(windows, isrs, facts, cfg)
        if status == 'EFFECTIVE' and not (complete and participants):
            return 'UNRESOLVED', details, 'BASEPRI 阈值已解析，但参与者或 CFG 覆盖不足。'
        return status, details, reason
    states = [s for a in main_accesses for s in a.get('mask_states', []) if s['context_id'] in mains]
    if states and any(s['irq_state'] == 'UNKNOWN' for s in states):
        if all(s.get('complete') for s in states) and not any(e['event_kind']=='primask_set' for e in detected):
            return 'PARTIAL', details, 'CFG 分支汇合不能保证每条路径都持续屏蔽中断。'
        return 'UNRESOLVED', details, '分支汇合、未知调用或不支持的控制流阻断了 PRIMASK 状态证明。'
    if unmaskable:
        return 'INEFFECTIVE', details, 'PRIMASK 不能屏蔽 NMI/HardFault 竞争方。'
    if primask and len(isrs) > 1:
        return 'UNRESOLVED', details, 'MAIN 已屏蔽，但 ISR 之间的冲突尚未排除。'
    if any(s['irq_state'] == 'DISABLED' for s in states) or any(e['event_kind'] == 'lock_exit' for e in detected):
        return 'PARTIAL', details, '检测到屏蔽操作，但未持续覆盖完整 READ→MODIFY→WRITE 窗口。'
    return 'DETECTED', details, '发现保护操作，尚无完整冲突窗口的有效性证明。'
