"""Flow-insensitive, inclusion-based pointer and callback constraints.

Object fields have separate abstract locations; array elements share one location.
Call arguments and results propagate across translation units. May-targets are
evidence of possible accesses, never proof of a particular runtime target.
"""
from collections import defaultdict
import fnmatch

from .common import digest


class Solver:
    def __init__(self, facts, cfg=None):
        self.facts = facts
        self.cfg = cfg or {}
        self.points = defaultdict(set)
        self.functions = {f['function_id']: f for f in facts['functions']}
        self.variables = {v['symbol_id']: v for v in facts['variables']}
        self.objects = {'obj:' + s: s for s in self.variables}
        self.changed = False
        self.matched_registration_specs = set()

    def locations(self, e):
        op = e.get('op')
        if op == 'loc':
            return {e['id']}
        if op == 'deref':
            return {p for p in self.value(e['value']) if not p.startswith('fn:')}
        if op == 'field':
            return {p + '/' + e['field'] for p in self.locations(e['base'])}
        if op == 'union':
            return set().union(*(self.locations(x) for x in e['items']))
        return set()

    def value(self, e):
        op = e.get('op')
        if op == 'addr':
            return self.locations(e['value'])
        if op == 'function':
            return {'fn:' + e['id']}
        if op == 'union':
            return set().union(*(self.value(x) for x in e['items']))
        if op in {'loc', 'deref', 'field'}:
            return set().union(*(self.points[p] for p in self.locations(e)))
        return set()

    def update(self, left, right):
        vals = self.value(right)
        for loc in self.locations(left):
            previous = len(self.points[loc])
            self.points[loc].update(vals)
            self.changed |= len(self.points[loc]) != previous

    def targets(self, call):
        direct = call.get('target')
        return {direct} if direct else {p[3:] for p in self.value(call['expression']) if p.startswith('fn:')}

    def symbol(self, location):
        # Field paths use '/', USRs can themselves contain slashes in filenames.
        while location:
            if location in self.objects:
                return self.objects[location]
            location = location.rpartition('/')[0]
        return None

    def add_access(self, locations, record, mode, **extra):
        for loc in sorted(locations):
            sid = self.symbol(loc)
            if sid is None:
                continue
            row = dict(symbol_id=sid, function_id=record['function_id'],
                       file=record['file'], line=record['line'], column=record.get('column', 0),
                       offset=record.get('offset', 0), source_text=record.get('source_text', ''),
                       access_kind=mode, access_path=loc[len('obj:' + sid):],
                       parse_confidence='conservative', via_alias='interprocedural points-to', **extra)
            row['access_id'] = 'A-' + digest(row)[:20]
            self.facts['accesses'].append(row)

    # 标准分配器：返回值 = 独立抽象堆对象（按调用站点）。FreeRTOS/ CMSIS
    # 常见封装一并覆盖；项目私有名可经 analysis.heap_allocators 补充。
    DEFAULT_HEAP_ALLOCATORS = {'malloc', 'calloc', 'realloc', 'aligned_alloc',
                               'pvPortMalloc', 'pvPortMallocUint32', 'osMemAlloc'}

    def heap_allocators(self):
        names = set(self.DEFAULT_HEAP_ALLOCATORS)
        extra = (self.cfg or {}).get('analysis', {}).get('heap_allocators') or []
        if isinstance(extra, str):
            extra = [extra]
        names.update(extra)
        return names

    def solve(self):
        calls = self.facts.get('semantic_calls', [])
        allocators = self.heap_allocators()
        # 分配站点种子：在不动点迭代前注入，使赋值链（p = malloc(); q = p;）
        # 正常传播。每个调用站点一个抽象堆对象，字段敏感机制按 heap:N/field
        # 自然分离；dev->cb = fn 与 t->tc = &ctrl 由此可被解引用恢复。
        for call in calls:
            if call.get('name') in allocators and call.get('result', {}).get('id'):
                site = 'heap:' + str(call.get('file') or '?') + ':' + str(call.get('offset', 0))
                self.points[call['result']['id']].add(site)
        # Monotone finite inclusion system. A resource cap must be an explicit
        # incompleteness fact; no silent fixed number of propagation passes.
        for iteration in range(1000):
            self.changed = False
            for c in self.facts.get('pointer_constraints', []):
                self.update(c['left'], c['right'])
            for call in calls:
                for target in self.targets(call):
                    for i, arg in enumerate(call['arguments']):
                        self.update(dict(op='loc', id=target + ':param:' + str(i)), arg)
                    self.update(call['result'], dict(op='loc', id=target + ':return'))
            if not self.changed:
                break
        else:
            self.facts['unknowns'].append(dict(kind='POINTS_TO_LIMIT', iterations=1000))
        for call in calls:
            targets = self.targets(call)
            if not call.get('target') and not targets:
                # The callee is unresolvable: any object/function address in
                # the arguments escapes into code we cannot analyze. This is
                # the transitive escape path (resolved wrapper -> opaque call)
                # that call-site range checks cannot see.
                for arg in call['arguments']:
                    for target in self.value(arg):
                        if target.startswith('obj:'):
                            sid = self.symbol(target[4:])
                            if sid:
                                self.facts['unknowns'].append(dict(
                                    kind='UNRESOLVED_CALL_ESCAPE', symbol_id=sid,
                                    function_id=call['function_id'], file=call['file'],
                                    line=call['line'], api=call.get('name', ''),
                                    hint='该变量地址作为参数流入了目标无法解析的间接调用'))
                        elif target.startswith('fn:'):
                            self.facts['unknowns'].append(dict(
                                kind='UNRESOLVED_CALL_TARGET_FN', target_function_id=target[3:],
                                function_id=call['function_id'], file=call['file'], line=call['line'],
                                api=call.get('name', ''), hint='该函数地址作为参数流入了目标无法解析的间接调用'))
            if not call.get('target'):
                for target in sorted(targets):
                    self.facts['calls'].append(dict(caller_function_id=call['function_id'],
                        callee_function_id=target, callee_name=self.functions.get(target, {}).get('name', target),
                        call_kind='INDIRECT_RESOLVED', file=call['file'], line=call['line'],
                        offset=call['offset'], confidence='may_target'))
            name = call['name']
            args = call['arguments']
            semantics = {'memcpy': {0: 'WRITE', 1: 'READ'}, 'memmove': {0: 'WRITE', 1: 'READ'},
                         'memset': {0: 'WRITE'}, 'memcmp': {0: 'READ', 1: 'READ'}}.get(name, {})
            for i, mode in semantics.items():
                if i < len(args):
                    self.add_access(self.value(args[i]), call, mode, via_api=name)
            self.registrations(call)
            self.dma(call)
        for index, spec in enumerate(self.cfg.get('entry_registrations', [])):
            if index not in self.matched_registration_specs:
                self.facts['unknowns'].append(dict(kind='UNMATCHED_ENTRY_REGISTRATION', api=spec['api'],
                    hint='配置的注册 API 未匹配当前构建的调用；核对名称、宏展开及构建变体'))
        self._attribute_indirect_accesses()
        self.facts['pointer_targets'] = [dict(location=k, targets=sorted(v)) for k, v in sorted(self.points.items()) if v]
        # Exact direct calls are retained; resolved edges augment their evidence.
        self.facts['accesses'] = list({a['access_id']: a for a in self.facts['accesses']}.values())

    # -- 对象敏感访问归属（object-sensitive attribution） ---------------------

    def _build_call_site_bindings(self, calls):
        """每个 (被调函数, 参数序号) → 调用点索引列表。

        固定点收敛后计算：参数绑定取调用点实参表达式的指向集，而不是
        形参的全局合并集——这是实例分离（huart1/huart2/...）的依据。
        站点身份用 semantic_calls 的行索引表示，保证同一调用点对所有
        形参的绑定可以组合。
        """
        bindings = defaultdict(list)
        for site_index, call in enumerate(calls):
            targets = self.targets(call)
            if not targets:
                continue
            arg_locs = [frozenset(self.value(arg)) for arg in call['arguments']]
            for target in targets:
                for i in range(len(arg_locs)):
                    bindings[(target, i)].append(site_index)
        self._site_by_index = [(call['function_id'], arg_locs)
                               for call in calls for arg_locs in [[frozenset(self.value(a)) for a in call['arguments']]]]
        return bindings

    def _collect_param_refs(self, expr, found):
        op = expr.get('op')
        if op == 'loc':
            ident = expr.get('id', '')
            if ':param:' in ident:
                fid, index = ident.rsplit(':param:', 1)
                if index.isdigit():
                    found.add((fid, int(index)))
        elif op == 'addr':
            self._collect_param_refs(expr['value'], found)
        elif op == 'deref':
            self._collect_param_refs(expr['value'], found)
        elif op == 'field':
            self._collect_param_refs(expr['base'], found)
        elif op == 'union':
            for item in expr.get('items', []):
                self._collect_param_refs(item, found)

    def _eval_value(self, expr, env):
        op = expr.get('op')
        if op == 'addr':
            return self._eval_locations(expr['value'], env)
        if op == 'function':
            return {'fn:' + expr['id']}
        if op == 'union':
            result = set()
            for item in expr.get('items', []):
                result |= self._eval_value(item, env)
            return result
        if op == 'loc' and expr.get('id') in env:
            # 调用点绑定：形参的值就是实参指向集，不能再查形参的全局合并表。
            return set(env[expr['id']])
        if op in {'loc', 'deref', 'field'}:
            # 与 value() 同构：值 = 各位置的指向集（多跳解引用逐级查表）。
            result = set()
            for p in self._eval_locations(expr, env):
                result |= self.points.get(p, set())
            return result
        return set()

    def _eval_locations(self, expr, env):
        op = expr.get('op')
        if op == 'loc':
            ident = expr.get('id', '')
            if ident in env:
                return {p for p in env[ident] if not p.startswith('fn:')}
            return {ident}
        if op == 'deref':
            return {p for p in self._eval_value(expr['value'], env) if not p.startswith('fn:')}
        if op == 'field':
            return {p + '/' + expr['field'] for p in self._eval_locations(expr['base'], env)}
        if op == 'union':
            result = set()
            for item in expr.get('items', []):
                result |= self._eval_locations(item, env)
            return result
        return set()

    def _attribute_indirect_accesses(self):
        """按调用点参数绑定归属指针访问（Section 8/10：对象敏感）。

        共享 HAL 处理函数（UART_Receive_IT(huart) 等）经形参写入各实例
        对象；旧模型把形参的全局合并指向集 + 被调函数的调用者并集上下文
        记到每个实例上，制造跨实例假双写者/假一致性。这里按每个调用点的
        实参指向集重新求值访问表达式，访问行归属调用者函数（上下文随
        调用点走），实例之间不再互相污染。形参无任何已解析调用绑定时
        保守保留全局合并行。
        """
        calls = self.facts.get('semantic_calls', [])
        bindings = self._build_call_site_bindings(calls)
        for item in self.facts.get('indirect_accesses', []):
            param_refs = {(fid, i) for (fid, i) in
                          (self._param_refs_of(item) or set()) if fid == item['function_id']}
            if not param_refs:
                self._emit_union_row(item)
                continue
            # 同一被调函数内按调用点分组：所有引用形参在该调用点都必须有绑定。
            site_sets = [set(bindings.get(ref, ())) for ref in param_refs]
            common_sites = set.intersection(*site_sets) if site_sets else set()
            if not common_sites:
                self._emit_union_row(item)
                continue
            emitted = False
            for site_index in sorted(common_sites):
                caller, arg_locs = self._site_by_index[site_index]
                env = {item['function_id'] + ':param:' + str(i): arg_locs[i]
                       for (_fid, i) in param_refs if i < len(arg_locs)}
                locs = self._eval_locations(item['location'], env)
                if not locs:
                    continue
                self.add_access(locs, dict(item, function_id=caller), item['mode'])
                emitted = True
            if not emitted:
                # 所有调用点实参都未解析出对象：保留缺口语义。
                self._emit_union_row(item)

    def _param_refs_of(self, item):
        found = set()
        self._collect_param_refs(item['location'], found)
        return found
        # 旧的全局合并行不再生成：per-site 行已覆盖有绑定的形参；无绑定
        # 形参经 _emit_union_row 保守保留。

    def _emit_union_row(self, item):
        targets = self.locations(item['location'])
        self.add_access(targets, item, item['mode'])
        if not targets:
            # Known automatic/parameter storage is a resolved object too. It is
            # intentionally absent from the global/static inventory; that must
            # not become a project-wide unknown write to exported globals.
            self.facts['unknowns'].append(dict(kind='UNRESOLVED_POINTEE',
                function_id=item['function_id'], file=item['file'], line=item['line']))

    def registrations(self, call):
        specs = {
            'xTaskCreate': dict(callback_arg=0, kind='TASK'),
            'xTaskCreateStatic': dict(callback_arg=0, kind='TASK'),
            'osThreadNew': dict(callback_arg=0, kind='TASK'),
            'xTaskCreatePinnedToCore': dict(callback_arg=0, kind='TASK'),
            'xTimerCreate': dict(callback_arg=4, kind='TIMER'),
            'xTimerCreateStatic': dict(callback_arg=4, kind='TIMER'),
            'xTimerPendFunctionCall': dict(callback_arg=0, kind='DEFERRED'),
            'xTimerPendFunctionCallFromISR': dict(callback_arg=0, kind='DEFERRED'),
            # CMSIS dynamic-vector programming is a real interrupt entry even
            # when the target function does not use the IRQHandler name.
            'NVIC_SetVector': dict(callback_arg=1, kind='ISR', may_repeat=False),
        }
        matched = []
        for index, item in enumerate(self.cfg.get('entry_registrations', [])):
            if fnmatch.fnmatchcase(call['name'], item.get('api', '')):
                self.matched_registration_specs.add(index)
                matched.append(item)
        if len(matched) > 1:
            self.facts['unknowns'].append(dict(kind='AMBIGUOUS_ENTRY_REGISTRATION',
                api=call['name'], function_id=call['function_id'], file=call['file'], line=call['line'], specs=matched))
        # Preserve every declared possible context; overlapping rules must not
        # silently let the last YAML item hide an entry.
        selected = matched or ([specs[call['name']]] if call['name'] in specs else [])
        for spec in selected:
            self.register_entry(call, spec, configured=bool(matched))

    def register_entry(self, call, spec, configured=False):
        i, kind = spec['callback_arg'], spec['kind']
        targets = sorted(v[3:] for v in self.value(call['arguments'][i]) if v.startswith('fn:')) if i < len(call['arguments']) else []
        if not targets:
            self.facts['unknowns'].append(dict(kind='UNRESOLVED_REGISTERED_ENTRY', api=call['name'],
                callback_arg=i, function_id=call['function_id'], file=call['file'], line=call['line'],
                hint='无法恢复注册回调；补齐赋值/包装实现或配置 contexts 中的真实入口'))
        for target in targets:
            self.facts['registrations'].append(dict(function_id=target, kind=kind,
                api=call['name'], registered_by=call['function_id'],
                may_repeat=spec.get('may_repeat', kind in {'TASK', 'CALLBACK'}), context_id=spec.get('context_id'),
                configured=configured,
                file=call['file'], line=call['line'], offset=call['offset'], discovery='points_to'))

    def dma(self, call):
        # Standard HAL buffer argument contracts, not variable-name heuristics.
        specs = {'HAL_UART_Receive_DMA': (1, 'WRITE', 'rx'), 'HAL_UART_Transmit_DMA': (1, 'READ', 'tx'),
                 'HAL_SPI_Receive_DMA': (1, 'WRITE', 'rx'), 'HAL_SPI_Transmit_DMA': (1, 'READ', 'tx'),
                 'HAL_ADC_Start_DMA': (1, 'WRITE', 'rx')}
        if call['name'] not in specs:
            return
        i, mode, direction = specs[call['name']]
        if len(call['arguments']) <= i:
            return
        targets = self.value(call['arguments'][i])
        if not any(self.symbol(p) for p in targets):
            self.facts['unknowns'].append(dict(kind='UNRESOLVED_DMA_BUFFER', function_id=call['function_id'],
                file=call['file'], line=call['line'], api=call['name']))
            return
        fid = 'hardware:' + digest([call['function_id'], call['file'], call['offset']])[:20]
        self.facts['functions'].append(dict(function_id=fid, name=call['name'], qualified_name=call['name'],
            file=call['file'], line=call['line'], synthetic='DMA contract', linkage='HARDWARE', is_static=False))
        self.facts.setdefault('hardware_contexts', []).append(dict(id='dma_' + direction, kind='DMA',
            direction=direction, function_id=fid, api=call['name'], file=call['file'], line=call['line']))
        self.add_access(targets, dict(call, function_id=fid), mode, via_api=call['name'],
                        hardware=True, registration_function=call['function_id'])
        for loc in targets:
            sid = self.symbol(loc)
            if sid:
                self.facts['unknowns'].append(dict(kind='DMA_SHARED_REVIEW', symbol_id=sid,
                    function_id=call['function_id'], file=call['file'], line=call['line'], api=call['name'],
                    hint='DMA contract identifies memory direction; lifetime/cache/ownership require review'))


def enrich(facts, cfg=None):
    if facts.get('pointer_model_applied'):
        return
    Solver(facts, cfg).solve()
    facts['pointer_model_applied'] = True
