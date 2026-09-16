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

    def solve(self):
        calls = self.facts.get('semantic_calls', [])
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
        for item in self.facts.get('indirect_accesses', []):
            targets = self.locations(item['location'])
            self.add_access(targets, item, item['mode'])
            # Known automatic/parameter storage is a resolved object too. It is
            # intentionally absent from the global/static inventory; that must
            # not become a project-wide unknown write to exported globals.
            if not targets:
                self.facts['unknowns'].append(dict(kind='UNRESOLVED_POINTEE',
                    function_id=item['function_id'], file=item['file'], line=item['line']))
        self.facts['pointer_targets'] = [dict(location=k, targets=sorted(v)) for k, v in sorted(self.points.items()) if v]
        # Exact direct calls are retained; resolved edges augment their evidence.
        self.facts['accesses'] = list({a['access_id']: a for a in self.facts['accesses']}.values())

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
