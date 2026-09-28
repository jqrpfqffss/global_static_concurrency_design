"""Flow-insensitive, inclusion-based pointer and callback constraints.

Object fields and constant array elements have separate abstract locations.
Call arguments and results propagate across translation units. May-targets are
evidence of possible accesses, never proof of a particular runtime target.
"""
from collections import defaultdict, deque
from functools import lru_cache
import copy
import fnmatch
import re
import os
import sys

from .common import digest


def resolve_linkage(parts):
    """Select ELF strong definitions before their body facts are merged.

    C USRs intentionally identify all declarations of one external symbol.
    Keeping accesses from an overridden weak body under that same USR would
    execute both implementations in the call graph. Resolve by linkage only,
    independent of project, callback name, and input-file ordering.
    """
    strong = {f['function_id'] for part in parts for f in part.get('functions', [])
              if not f.get('is_weak')}
    result = []
    for source in parts:
        overridden = {f['function_id'] for f in source.get('functions', [])
                      if f.get('is_weak') and f['function_id'] in strong}
        if not overridden:
            result.append(source)
            continue
        part = copy.deepcopy(source)
        part['functions'] = [f for f in part.get('functions', []) if f['function_id'] not in overridden]
        for table in ('accesses', 'unknowns', 'protection_events', 'irq_priority_events',
                      'snapshots', 'control_flow', 'pointer_constraints', 'semantic_calls', 'indirect_accesses'):
            part[table] = [r for r in part.get(table, []) if r.get('function_id') not in overridden]
        part['calls'] = [r for r in part.get('calls', []) if r.get('caller_function_id') not in overridden]
        part['registrations'] = [r for r in part.get('registrations', []) if r.get('registered_by') not in overridden]
        part['variables'] = [v for v in part.get('variables', []) if v.get('owner_function_id') not in overridden]
        result.append(part)
    return result


class Solver:
    def __init__(self, facts, cfg=None):
        self.facts = facts
        self.cfg = cfg or {}
        self.points = defaultdict(set)
        self.slots_by_shape = defaultdict(set)
        self.descendant_slots = defaultdict(set)
        self.unknown_points = defaultdict(set)
        self.readers = defaultdict(set)
        self.current_task = None
        self.pending = deque()
        self.enqueued = set()
        self.unresolved_copies = []
        self.functions = {f['function_id']: f for f in facts['functions']}
        self.variables = {v['symbol_id']: v for v in facts['variables']}
        self.objects = {'obj:' + s: s for s in self.variables}
        self.section_starts = {}
        for sid, variable in self.variables.items():
            if variable['name'].startswith('__start_'):
                section = variable['name'][len('__start_'):]
                entries = ['obj:' + s for s, v in self.variables.items() if v.get('linker_section') == section]
                if entries:
                    self.section_starts['obj:' + sid] = set(entries)
        self.changed = False
        self.matched_registration_specs = set()

    @staticmethod
    @lru_cache(maxsize=65536)
    def shape(location):
        return re.sub(r'/\[(?:-?\d+|\*)\]', '/[*]', location)

    def add_points(self, location, values):
        if not values:
            return
        fresh = location not in self.points
        if fresh:
            self.slots_by_shape[self.shape(location)].add(location)
            ancestor = location
            while '/' in ancestor:
                ancestor = ancestor.rpartition('/')[0]
                self.descendant_slots[ancestor].add(location)
                self.schedule('descendants:' + ancestor)
        previous = len(self.points[location])
        self.points[location].update(values)
        self.unknown_points[location].update(v for v in values if v.startswith('unknown:'))
        self.changed |= len(self.points[location]) != previous
        if len(self.points[location]) != previous:
            self.schedule(location)
            self.schedule('shape:' + self.shape(location))

    def watch(self, location):
        if self.current_task is not None:
            self.readers[location].add(self.current_task)

    def schedule(self, location):
        for task in self.readers.get(location, ()):
            if task not in self.enqueued:
                self.pending.append(task)
                self.enqueued.add(task)

    @staticmethod
    def overlaps(left, right):
        a, b = left.split('/'), right.split('/')
        return len(a) == len(b) and all(x == y or x == '[*]' and y.startswith('[')
                                       or y == '[*]' and x.startswith('[') for x, y in zip(a, b))

    def locations(self, e):
        op = e.get('op')
        if op == 'loc':
            return self.section_starts.get(e['id'], {e['id']})
        if op == 'deref':
            return {p for p in self.value(e['value']) if not p.startswith('fn:')}
        if op == 'field':
            return {p if p.startswith('unknown:') else p + ('/[0]' if p in self.objects and self.variables[self.objects[p]].get('array_element_is_struct')
                         else '') + '/' + e['field'] for p in self.locations(e['base'])}
        if op == 'index':
            result = set()
            for base in self.locations(e['base']):
                if base.startswith('unknown:'):
                    # An opaque allocation has unknown subobjects already.
                    # Appending .next/.next/... invents an infinite lattice.
                    result.add(base)
                    continue
                sid = self.objects.get(base)
                if sid and self.variables[sid].get('linker_section') and not self.variables[sid].get('is_array'):
                    # A linker-collected section of individual records is one
                    # logical table although every registration has its own
                    # C declaration. Its dynamic index may select any record.
                    result.add(base)
                    continue
                match = re.search(r'/\[(-?\d+|\*)\]$', base)
                index = e['index']
                # Subscripting a pointer to an element adds an offset to that
                # element; it must not invent another array dimension.
                if match and e['base'].get('op') == 'deref':
                    index = str(int(match[1]) + int(index)) if '*' not in {match[1], index} else '*'
                    base = base[:match.start()]
                result.add(base + '/[' + index + ']')
            return result
        if op == 'union':
            return set().union(*(self.locations(x) for x in e['items']))
        return set()

    def value(self, e):
        op = e.get('op')
        if op == 'addr':
            return self.locations(e['value'])
        if op == 'function':
            return {'fn:' + e['id']}
        if op == 'unknown':
            return {'unknown:' + e['id']}
        if op == 'offset':
            result = set()
            for base in self.value(e['value']):
                if base.startswith('unknown:') or e['index'] == '0':
                    result.add(base)
                    continue
                match = re.search(r'/\[(-?\d+|\*)\]$', base)
                sid = self.objects.get(base)
                if match:
                    index = str(int(match[1]) + int(e['index'])) if '*' not in {match[1], e['index']} else '*'
                    result.add(base[:match.start()] + '/[' + index + ']')
                elif sid and self.variables[sid].get('is_array'):
                    result.add(base + '/[' + e['index'] + ']')
                elif sid and self.variables[sid].get('linker_section'):
                    result.add(base)
                else:
                    # Non-array pointer arithmetic lacks a proven extent.
                    # Preserve the may-object and an explicit missing fact.
                    result.update({base, 'unknown:offset:' + base})
            return result
        if op == 'union':
            return set().union(*(self.value(x) for x in e['items']))
        if op in {'loc', 'deref', 'field', 'index'}:
            result = set()
            for loc in self.locations(e):
                self.watch(loc)
                if loc.startswith('unknown:'):
                    result.add(loc)
                if e['op'] == 'deref' and loc in self.objects and self.variables[self.objects[loc]].get('is_array'):
                    loc += '/[0]'
                    self.watch(loc)
                result.update(self.points.get(loc, ()))
                ancestor = loc
                while '/' in ancestor:
                    ancestor = ancestor.rpartition('/')[0]
                    self.watch(ancestor)
                    result.update(self.unknown_points.get(ancestor, ()))
                if '/[' in loc:
                    self.watch('shape:' + self.shape(loc))
                    for other in tuple(self.slots_by_shape.get(self.shape(loc), ())):
                        values = self.points[other]
                        if other != loc and self.overlaps(loc, other):
                            result.update(values)
            return result
        return set()

    def update(self, left, right, aggregate=False, aggregate_paths=None):
        vals = self.value(right)
        for loc in self.locations(left):
            self.add_points(loc, vals)
            if aggregate:
                if aggregate_paths is None:
                    # Old extraction schemas have no finite record layout.
                    # Never infer one from an allocator's evolving descendants.
                    self.add_points(loc, {'unknown:aggregate-layout:' + loc})
                    continue
                for source in self.locations(right):
                    for suffix in aggregate_paths:
                        slot = source if source.startswith('unknown:') else source + suffix
                        destination = loc if loc.startswith('unknown:') else loc + suffix
                        self.add_points(destination, self.value(dict(op='loc', id=slot)))

    def targets(self, call):
        direct = call.get('target')
        return {direct} if direct else {p[3:] for p in self.value(call['expression']) if p.startswith('fn:')}

    def copy_memory(self, call):
        destinations = self.value(call['arguments'][0])
        sources = self.value(call['arguments'][1])
        layouts = call.get('argument_pointee_paths', [])
        sizes = call.get('argument_pointee_sizes', [])
        constants = call.get('argument_values', [])
        layout = layouts[1] if len(layouts) > 1 else None
        extent = sizes[1] if len(sizes) > 1 else None
        count = constants[2] if len(constants) > 2 else None
        # Only a whole, typed copy supplies a finite layout. Byte slices and
        # cast buffers retain a variable-local provenance gap; their evolving
        # descendants must never be treated as a recursive record definition.
        if layout is None or extent is None or count != extent:
            for destination in destinations:
                if not destination.startswith('unknown:'):
                    self.add_points(destination, {'unknown:byte-copy:' + call['result']['id']})
            if call not in self.unresolved_copies:
                self.unresolved_copies.append(call)
            return
        direct, fields = set(), defaultdict(set)
        for source in sources:
            self.watch(source)
            direct.update(self.points.get(source, ()))
            if source.startswith('unknown:'):
                direct.add(source)
                continue
            for suffix in layout:
                fields[suffix].update(self.value(dict(op='loc', id=source + suffix)))
        # Union source summaries once, rather than constructing every
        # destination x source x field tuple on each solver iteration.
        for destination in destinations:
            self.add_points(destination, direct)
            if destination.startswith('unknown:'):
                for values in fields.values():
                    self.add_points(destination, values | {destination})
            else:
                for suffix, values in fields.items():
                    self.add_points(destination + suffix, values)

    @lru_cache(maxsize=65536)
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
        constraints = self.facts.get('pointer_constraints', [])
        tasks = [('constraint', c) for c in constraints] + [('call', c) for c in calls]
        self.pending.extend(range(len(tasks)))
        self.enqueued.update(range(len(tasks)))
        evaluations = 0
        # Re-evaluate only equations whose actual read locations changed.
        # Dynamic dereferences/aggregate descendants add dependencies as the
        # monotone graph grows; this computes the same inclusion fixed point.
        while self.pending:
            task = self.pending.popleft()
            self.enqueued.remove(task)
            self.current_task = task
            kind, item = tasks[task]
            if kind == 'constraint':
                c = item
                self.update(c['left'], c['right'], c.get('aggregate', False), c.get('aggregate_paths'))
            else:
                call = item
                targets = self.targets(call)
                if (call.get('returns_pointer') or call.get('returns_aggregate')) and (not targets or any(t not in self.functions for t in targets)):
                    self.update(call['result'], dict(op='unknown', id=call['result']['id']))
                for target in targets:
                    for i, arg in enumerate(call['arguments']):
                        aggregates = call.get('argument_aggregates', [])
                        layouts = call.get('argument_aggregate_paths', [])
                        self.update(dict(op='loc', id=target + ':param:' + str(i)), arg,
                                    i < len(aggregates) and aggregates[i], layouts[i] if i < len(layouts) else None)
                    self.update(call['result'], dict(op='loc', id=target + ':return'),
                                call.get('returns_aggregate', False), call.get('return_aggregate_paths'))
                if call.get('name') in {'memcpy', 'memmove'} and len(call['arguments']) >= 2:
                    self.copy_memory(call)
            evaluations += 1
            if os.environ.get('ECRA_SOLVER_TRACE') and evaluations % 10000 == 0:
                print('points-to evaluations', evaluations, 'pending', len(self.pending), 'slots', len(self.points),
                      'values', sum(map(len, self.points.values())), file=sys.stderr, flush=True)
            if evaluations > max(10000, len(tasks) * 1000):
                self.facts['unknowns'].append(dict(kind='POINTS_TO_LIMIT', evaluations=evaluations))
                break
        self.current_task = None
        self.facts['points_to_stats'] = dict(equations=len(tasks), evaluations=evaluations,
            locations=len(self.points), targets=sum(map(len, self.points.values())), complete=not bool(self.pending))
        for call in calls:
            targets = self.targets(call)
            values = self.value(call['expression']) if not call.get('target') else set()
            call['resolved_targets'] = sorted(targets)
            call['target_coverage'] = ('COMPLETE' if targets and not any(v.startswith('unknown:') for v in values)
                                       else 'PARTIAL')
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
            if not targets or any(p.startswith('unknown:') for p in targets):
                self.facts['unknowns'].append(dict(kind='UNRESOLVED_POINTEE',
                    function_id=item['function_id'], file=item['file'], line=item['line'],
                    offset=item.get('offset'), may_target_symbol_ids=sorted({self.symbol(p) for p in targets if self.symbol(p)})))
                for target in targets:
                    sid = self.symbol(target)
                    if sid:
                        self.facts['unknowns'].append(dict(kind='UNRESOLVED_POINTEE', symbol_id=sid,
                            access_path=target[len('obj:' + sid):], function_id=item['function_id'],
                            file=item['file'], line=item['line'], offset=item.get('offset'),
                            reason='Known may-target shares pointer provenance with an opaque target'))
        self.resolve_evidence(calls)
        self.facts['pointer_targets'] = [dict(location=k, targets=sorted(v)) for k, v in sorted(self.points.items()) if v]
        # Exact direct calls are retained; resolved edges augment their evidence.
        self.facts['accesses'] = list({a['access_id']: a for a in self.facts['accesses']}.values())

    def reachable_pointer_values(self, initial):
        """Follow pointers/aggregate fields that an opaque consumer can read."""
        result, pending = set(), list(initial)
        while pending:
            loc = pending.pop()
            if loc in result:
                continue
            result.add(loc)
            if loc.startswith('fn:'):
                # An opaque callback consumer can call a getter and obtain
                # every address returned by that function. Escaping the entry
                # therefore also escapes its resolved return pointees.
                returned = loc[3:] + ':return'
                for slot, values in self.points.items():
                    if slot == returned or slot.startswith(returned + '/'):
                        pending.extend(values - result)
                continue
            if loc.startswith('unknown:'):
                continue
            candidates = {loc} | self.descendant_slots.get(loc, set()) | self.slots_by_shape.get(self.shape(loc), set())
            for slot in candidates:
                values = self.points.get(slot, set())
                if slot == loc or slot.startswith(loc + '/') or self.overlaps(slot, loc):
                    pending.extend(values - result)
        return result

    def copied_pointer_values(self, sources):
        """Values copied out of storage, excluding its uncopied address."""
        values = set()
        for source in sources:
            candidates = {source} | self.descendant_slots.get(source, set()) | self.slots_by_shape.get(self.shape(source), set())
            for slot in candidates:
                if slot == source or slot.startswith(source + '/') or self.overlaps(slot, source):
                    values.update(self.points.get(slot, ()))
        return self.reachable_pointer_values(values)

    def resolve_evidence(self, calls):
        """Retain gaps only at actual opaque consumers, with exact targets.

        An address in a local alias/table is ordinary pointer evidence. An
        external call, unresolved store or externally visible callback slot is
        an escape. Keep partially resolved calls visible even when may-target
        edges were successfully recovered.
        """
        escapes, escaped_functions = [], set()
        safe_apis = {'memcpy', 'memmove', 'memset', 'memcmp', '__disable_irq', '__enable_irq',
                     '__get_PRIMASK', '__set_PRIMASK', '__get_BASEPRI', '__set_BASEPRI',
                     '__set_BASEPRI_MAX', '__disable_fault_irq', '__enable_fault_irq',
                     'HAL_NVIC_SetPriority', 'NVIC_SetPriority', 'HAL_NVIC_EnableIRQ', 'NVIC_EnableIRQ',
                     'HAL_NVIC_DisableIRQ', 'NVIC_DisableIRQ', 'NVIC_SetPriorityGrouping',
                     'HAL_NVIC_SetPriorityGrouping', 'SysTick_Config', 'HAL_SYSTICK_Config',
                     'xTaskCreate', 'xTaskCreateStatic', 'osThreadNew', 'xTaskCreatePinnedToCore',
                     'xTimerCreate', 'xTimerCreateStatic', 'xTimerPendFunctionCall',
                     'xTimerPendFunctionCallFromISR', 'NVIC_SetVector',
                     'HAL_UART_Receive_DMA', 'HAL_UART_Transmit_DMA', 'HAL_SPI_Receive_DMA',
                     'HAL_SPI_Transmit_DMA', 'HAL_ADC_Start_DMA'}
        for spec in self.cfg.get('critical_sections', []):
            safe_apis.update(spec[key] for key in ('enter', 'exit', 'save', 'restore') if key in spec)

        def escape(values, site, reason):
            for value in sorted(self.reachable_pointer_values(values)):
                if value.startswith('fn:'):
                    target = value[3:]
                    escaped_functions.add(target)
                    escapes.append(dict(kind='FUNCTION_ADDRESS', target_function_id=target,
                        function_id=site.get('function_id', ''), file=site.get('file'), line=site.get('line'),
                        offset=site.get('offset'), reason=reason, actual_escape=True))
                    continue
                sid = self.symbol(value)
                if sid:
                    escapes.append(dict(kind='INLINE_ASSEMBLY' if site.get('inline_assembly') else 'ADDRESS_ESCAPE', symbol_id=sid,
                        access_path=value[len('obj:' + sid):], function_id=site.get('function_id', ''),
                        file=site.get('file'), line=site.get('line'), offset=site.get('offset'),
                        reason=reason, actual_escape=True))

        resolved_sites = set()
        for call in calls:
            targets = self.targets(call)
            if not call.get('target') and call.get('target_coverage') == 'COMPLETE':
                resolved_sites.add((call['function_id'], call['file'], call['offset']))
            contracted = call['name'] in safe_apis or any(fnmatch.fnmatchcase(call['name'], spec['api'])
                for spec in self.cfg.get('entry_registrations', []))
            if call['name'] in {'memcpy', 'memmove'} and len(call['arguments']) >= 2:
                destinations = self.value(call['arguments'][0])
                if not destinations or any(p.startswith('unknown:') for p in destinations):
                    escape(self.copied_pointer_values(self.value(call['arguments'][1])), call,
                           'Pointer contents copied to an unresolved destination')
                if call in self.unresolved_copies:
                    escape(self.copied_pointer_values(self.value(call['arguments'][1])), call,
                           'Untyped aggregate copy has unresolved pointer contents')
            if not contracted and (call.get('target_coverage') == 'PARTIAL' or any(t not in self.functions for t in targets)):
                values = set().union(*(self.value(arg) for arg in call['arguments']))
                escape(values, call, 'Pointer argument reaches code without an analyzable implementation')
        for constraint in self.facts.get('pointer_constraints', []):
            locations = self.locations(constraint['left'])
            if constraint['left'].get('op') in {'deref', 'field', 'index'} and (
                    not locations or any(p.startswith('unknown:') for p in locations)):
                escape(self.value(constraint['right']), constraint, 'Pointer value stored through an unresolved destination')
        incomplete_build = (bool(self.facts.get('build_closure', {}).get('missing_objects'))
                            or any(u['kind'] == 'PARSE_FAILED' for u in self.facts['unknowns'])
                            or any(u.get('parse_status') == 'FAILED' for u in self.facts.get('translation_units', [])))
        for location, values in list(self.points.items()) if incomplete_build else ():
            sid = self.symbol(location)
            if sid and self.variables[sid].get('linkage') == 'EXTERNAL':
                # Missing linked code can name an exported pointer slot and
                # obtain its pointees/callbacks. With a complete closure,
                # visibility alone is not an extra asynchronous consumer.
                variable = self.variables[sid]
                escape(values, dict(file=variable.get('definition_file'),
                    line=variable.get('definition_line')), 'Missing linked code may consume an exported pointer slot')

        self.facts['address_escapes'] = list({digest(e): e for e in escapes}.values())
        resolved, remaining = [], []
        represented_functions = {value[3:] for values in self.points.values() for value in values if value.startswith('fn:')}
        represented_functions.update(target for call in calls for target in self.targets(call))
        represented_functions.update(reg['function_id'] for reg in self.facts.get('registrations', []))
        dynamic_sites = {(item['function_id'], item['file'], item.get('offset')): self.locations(item['location'])
                         for item in self.facts.get('indirect_accesses', [])}
        for issue in self.facts['unknowns']:
            kind = issue['kind']
            site = (issue.get('function_id'), issue.get('file'), issue.get('offset'))
            clear = kind in {'ADDRESS_ESCAPE', 'STATIC_INITIALIZER_REFERENCE'} and not issue.get('actual_escape')
            clear |= kind == 'INDIRECT_CALL' and site in resolved_sites
            clear |= (kind == 'FUNCTION_ADDRESS' and issue.get('target_function_id') in represented_functions
                      and issue.get('target_function_id') not in escaped_functions)
            if kind in {'POINTER_SUBSCRIPT', 'POINTER_DEREFERENCE'}:
                targets = dynamic_sites.get(site, set())
                clear |= bool(targets) and not any(p.startswith('unknown:') for p in targets)
            (resolved if clear else remaining).append(issue)
        self.facts['resolved_pointer_facts'] = resolved
        self.facts['unknowns'] = list({digest(e): e for e in remaining + self.facts['address_escapes']}.values())

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
        self.facts.setdefault('hardware_contexts', []).append(dict(id='DMA:' + digest([call['name'], call['file'], call['offset']])[:20], kind='DMA',
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
