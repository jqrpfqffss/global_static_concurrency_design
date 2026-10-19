"""Flow-insensitive, inclusion-based pointer and callback constraints.

Object fields and constant array elements have separate abstract locations.
Call arguments and results propagate across translation units. May-targets are
evidence of possible accesses, never proof of a particular runtime target.
"""
from collections import Counter, defaultdict, deque, OrderedDict
from functools import lru_cache
import copy
import fnmatch
import re
import os
import sys

from .common import digest
from .target_set import TargetPool, TargetSet


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
                      'snapshots', 'control_flow', 'pointer_constraints', 'semantic_calls', 'indirect_accesses', 'pointer_storage',
                      'constant_regions', 'nvic_programs'):
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
        self.target_pool = TargetPool()
        self.recent_targets = deque(maxlen=12)
        if os.environ.get('ECRA_SOLVER_TRACE_HOT'):
            self.target_pool.on_new_target = self.trace_new_target
        self.points = defaultdict(self.target_pool.make)
        self.slots_by_shape = defaultdict(set)
        self.descendant_slots = defaultdict(set)
        self.unknown_points = defaultdict(self.target_pool.make)
        self.readers = defaultdict(set)
        self.load_cache = {}
        self.load_dependencies = defaultdict(set)
        # Pointer offsets are pure functions of their exact input target set,
        # index, and this solver's immutable storage layout.  A large call
        # graph can revisit the same offset after an unrelated slot changes;
        # retain a small per-solution image instead of re-projecting every
        # pointee on each such revisit.  Reading the child expression still
        # installs the current task's dependencies before consulting this.
        self.offset_images = OrderedDict()
        self.offset_prefixes = {}
        # Field/index projections are monotone within one solution. Cache the
        # projected locations and visit only newly discovered bases when a
        # pointer equation is woken again.
        self.location_images = {}
        self.update_images = {}
        self.current_task = None
        self.pending = deque()
        self.enqueued = set()
        self.recent_locations = deque(maxlen=12)
        self.unresolved_copies = []
        self.pruned_functions = set(facts.get('pointer_solver_pruning', {}).get('pruned_function_ids', ()))
        self.active_constraints = []
        self.active_indirect_accesses = []
        self.functions = {f['function_id']: f for f in facts['functions']}
        self.variables = {v['symbol_id']: v for v in facts['variables']}
        self.objects = {'obj:' + s: s for s in self.variables}
        self.storage_definitions = {}
        for row in facts.get('pointer_storage', []):
            if row.get('function_id') in self.pruned_functions:
                continue
            location = row['location']
            if location not in self.storage_definitions:
                self.storage_definitions[location] = dict(row, paths=set(row['paths']),
                    array_extents=dict(row.get('array_extents', {})))
            else:
                # An incomplete extern declaration must not erase the actual
                # definition's layout, regardless of worker completion order.
                definition = self.storage_definitions[location]
                definition['paths'].update(row['paths'])
                for prefix, size in row.get('array_extents', {}).items():
                    if size is not None or prefix not in definition['array_extents']:
                        definition['array_extents'][prefix] = size
                if row.get('array_size') is not None:
                    definition['array_size'] = row['array_size']
        self.storage_definitions = {location: dict(row, paths={path[:end] for path in row['paths']
            for end in [len(path)] + [i for i, char in enumerate(path) if char == '/' and i]})
            for location, row in self.storage_definitions.items()}
        self.storage_paths = {}
        for base, sid in self.objects.items():
            variable = self.variables[sid]
            paths = {''}
            for member in variable.get('member_definitions', []):
                path = re.sub(r'\[\*\]', '', member['field_path']).replace('.', '/')
                paths.add(path)
            self.storage_paths[base] = paths
        self.section_starts = {}
        # Instance caches must die with a solution. A class-level lru_cache
        # retains old Solver instances (and their complete facts/points sets)
        # across context-refinement passes.
        self.storage_base = lru_cache(maxsize=65536)(self.storage_base)
        self.storage_location = lru_cache(maxsize=65536)(self.storage_location)
        self.symbol = lru_cache(maxsize=65536)(self.symbol)
        self.escape_closures = {}
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
            if os.environ.get('ECRA_SOLVER_TRACE_HOT'):
                task = self.current_task
                source = self.tasks[task] if task is not None and hasattr(self, 'tasks') else None
                self.recent_locations.append((location, task, source[0] if source else None,
                    source[1].get('file') if source else None,
                    source[1].get('line') if source else None))
            self.slots_by_shape[self.shape(location)].add(location)
            ancestor = location
            while '/' in ancestor:
                ancestor = ancestor.rpartition('/')[0]
                self.descendant_slots[ancestor].add(location)
                self.notify_change('descendants:' + ancestor)
        points = self.points[location]
        previous = points.bits
        points.update(values)
        if points.bits != previous:
            self.unknown_points[location].bits = points.bits & self.target_pool.unknown_mask
            self.changed = True
            self.escape_closures.clear()
            self.notify_change(location)
            self.notify_change('shape:' + self.shape(location))

    def trace_new_target(self, value):
        match = re.search(r'/\[(-?\d+)\]$', value)
        if match and int(match[1]) >= 8:
            task = self.current_task
            source = self.tasks[task] if task is not None and hasattr(self, 'tasks') else None
            self.recent_targets.append((value, task, source[0] if source else None,
                source[1].get('file') if source else None,
                source[1].get('line') if source else None))

    def notify_change(self, location):
        # A cached load depends on points, overlap summaries, ancestor opaque
        # values, and newly created wildcard/descendant slots. Invalidate all
        # those dependencies before waking equations, including new locations.
        for key in tuple(self.load_dependencies.get(location, ())):
            _, dependencies = self.load_cache.pop(key)
            for dependency in dependencies:
                self.load_dependencies[dependency].discard(key)
            self.schedule(key)
        self.schedule(location)

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

    def storage_base(self, location):
        while location:
            if location in self.objects or location in self.storage_definitions:
                return location
            location = location.rpartition('/')[0]
        return None

    def storage_location(self, location):
        """Keep named storage within its finite declared subobject layout.

        Casts/container arithmetic can create an overlapping view for which
        no field offset is proven. Represent that view by one may-overlap
        location, retaining the original object and an explicit alias gap.
        """
        base = self.storage_base(location)
        if base is None:
            return location
        suffix = location[len(base):]
        if '/$overlap' in suffix:
            return base + '/$overlap'
        if base in self.storage_definitions:
            definition = self.storage_definitions[base]
            if suffix and self.shape(suffix) not in definition['paths']:
                return base + '/$overlap'
            extents = dict(definition.get('array_extents', {}))
            extents.setdefault('', definition.get('array_size'))
            for match in reversed(list(re.finditer(r'/\[(-?\d+)\]', suffix))):
                size = extents.get(self.shape(suffix[:match.start()]))
                if size is not None and not 0 <= int(match[1]) < size:
                    return base + '/$overlap'
                if size is None:
                    # Every unknown dimension gets a finite summary, not an
                    # unbounded sequence of offsets or a whole-object cast.
                    suffix = suffix[:match.start()] + '/[*]' + suffix[match.end():]
            return base + suffix
        sid = self.objects[base]
        fields = re.sub(r'/\[(?:-?\d+|\*)\]', '', suffix).strip('/')
        if fields not in self.storage_paths[base] or suffix.count('/[') > 1 + len(fields.split('/')):
            return base + '/$overlap'
        size = self.variables[sid].get('array_size')
        if size and suffix.startswith('/['):
            match = re.match(r'/\[(-?\d+)\]', suffix)
            if match and not 0 <= int(match[1]) < size:
                return base + '/$overlap'
        return location

    def locations(self, e):
        op = e.get('op')
        if op == 'loc':
            return self.target_pool.make(
                self.section_starts.get(e['id'], {self.storage_location(e['id'])}))
        if op == 'deref':
            pointees = self.value(e['value'])
            return TargetSet(self.target_pool, pointees.bits & ~self.target_pool.function_mask)
        if op == 'field':
            bases = self.locations(e['base'])
            result, fresh = self._location_projection(e, bases)
            for base in fresh:
                if base.startswith('unknown:'):
                    result.add(base)
                    continue
                array = (base in self.objects and self.variables[self.objects[base]].get('array_element_is_struct')
                         or '/[*]' in self.storage_definitions.get(base, {}).get('paths', ()))
                result.add(self.storage_location(base + ('/[0]' if array else '') + '/' + e['field']))
            self.location_images[id(e)] = (e, bases.bits, result.bits)
            return result
        if op == 'index':
            bases = self.locations(e['base'])
            result, fresh = self._location_projection(e, bases)
            for base in fresh:
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
                result.add(self.storage_location(base + '/[' + index + ']'))
            self.location_images[id(e)] = (e, bases.bits, result.bits)
            return result
        if op == 'union':
            result = self.target_pool.make()
            for item in e['items']:
                result.update(self.locations(item))
            return result
        return self.target_pool.make()

    def _location_projection(self, expression, bases):
        image = self.location_images.get(id(expression))
        if image is not None and image[0] is expression and image[1] & bases.bits == image[1]:
            return (TargetSet(self.target_pool, image[2]),
                    TargetSet(self.target_pool, bases.bits & ~image[1]))
        return self.target_pool.make(), bases

    def value(self, e):
        op = e.get('op')
        if op == 'va_arg':
            return self.variadic_values(e['value'])
        if op == 'addr':
            return self.target_pool.make(self.locations(e['value']))
        if op == 'function':
            return self.target_pool.make({'fn:' + e['id']})
        if op == 'unknown':
            return self.target_pool.make({'unknown:' + e['id']})
        if op == 'offset':
            pointees = self.value(e['value'])
            # In the inclusion solver a particular expression's pointees can
            # only grow. Project only newly discovered bases: re-walking its
            # entire (potentially very large) set on every equation wakeup is
            # unnecessary. Retain the expression object to make its id stable
            # even for a temporary expression outside the merged facts.
            site = id(e)
            prefix = self.offset_prefixes.get(site)
            if (prefix is not None and prefix[0] == e['index']
                    and prefix[1] & pointees.bits == prefix[1]):
                if prefix[1] == pointees.bits:
                    return TargetSet(self.target_pool, prefix[2])
                bases = TargetSet(self.target_pool, pointees.bits & ~prefix[1])
                result = TargetSet(self.target_pool, prefix[2])
            else:
                bases = pointees
                result = self.target_pool.make()
            key = (pointees.bits, e['index'])
            cached = self.offset_images.get(key)
            if cached is not None:
                self.offset_images.move_to_end(key)
                self.offset_prefixes[site] = (e['index'], pointees.bits, cached.bits, e)
                return cached.copy()
            for base in bases:
                if base.startswith('unknown:') or e['index'] == '0':
                    result.add(base)
                    continue
                if base.startswith('fn:'):
                    # Function designators are not C storage objects. An
                    # arithmetic view of one cannot become another known
                    # callback or a recursive field of the function address.
                    # Preserve a stable opaque target for the relevant call/
                    # alias gap instead of inventing fn/.../$overlap/... .
                    if e['index'] == '*':
                        # An unknown offset includes zero, which retains the
                        # original callable target as one possibility.
                        result.add(base)
                    result.add('unknown:function-offset:' + base[3:])
                    continue
                match = re.search(r'/\[(-?\d+|\*)\]$', base)
                sid = self.objects.get(base)
                if match:
                    index = str(int(match[1]) + int(e['index'])) if '*' not in {match[1], e['index']} else '*'
                    result.add(self.storage_location(base[:match.start()] + '/[' + index + ']'))
                elif sid and self.variables[sid].get('is_array'):
                    result.add(base + '/[' + e['index'] + ']')
                elif sid and self.variables[sid].get('linker_section'):
                    result.add(base)
                else:
                    # A cast byte pointer may advance across the object
                    # representation. The owning storage's overlap summary
                    # already denotes every possible member in that object;
                    # adding an opaque pointee here would turn this *known*
                    # object-local traversal into a false UNKNOWN for every
                    # member it can read. Arithmetic outside the original C
                    # object is not a defined cross-object access.
                    result.update({base, self.storage_location(base + '/$overlap')})
            self.offset_prefixes[site] = (e['index'], pointees.bits, result.bits, e)
            self.offset_images[key] = result.copy()
            if len(self.offset_images) > 128:
                self.offset_images.popitem(last=False)
            return result
        if op == 'union':
            result = self.target_pool.make()
            for item in e['items']:
                result.update(self.value(item))
            return result
        if op in {'loc', 'deref', 'field', 'index'}:
            result = self.target_pool.make()
            for loc in self.locations(e):
                result.update(self.load_location(loc, op == 'deref'))
            return result
        return self.target_pool.make()

    def load_location(self, location, decay=False):
        key = ('load', location, decay)
        self.watch(key)
        if key not in self.load_cache:
            result, dependencies = self.compute_load(location, decay)
            self.load_cache[key] = result, dependencies
            for dependency in dependencies:
                self.load_dependencies[dependency].add(key)
        return self.load_cache[key][0]

    def compute_load(self, location, decay=False):
        result = self.target_pool.make()
        dependencies = {location}
        if location.startswith('unknown:'):
            result.add(location)
        base = self.storage_base(location)
        if base:
            summary = base + '/$overlap'
            dependencies.add(summary)
            result.update(self.points.get(summary, ()))
            if location == summary:
                result.add('unknown:overlap:' + self.objects.get(base, base))
                dependencies.add('descendants:' + base)
                for child in self.descendant_slots.get(base, ()):
                    dependencies.add(child)
                    result.update(self.points[child])
        if decay and location in self.objects and self.variables[self.objects[location]].get('is_array'):
            location += '/[0]'
            dependencies.add(location)
        result.update(self.points.get(location, ()))
        ancestor = location
        while '/' in ancestor:
            ancestor = ancestor.rpartition('/')[0]
            dependencies.add(ancestor)
            result.update(self.unknown_points.get(ancestor, ()))
        if '/[' in location:
            indices = list(re.finditer(r'/\[-?\d+\]', location))
            if indices and '/[*]' not in location and len(indices) <= 5:
                # A fixed element can overlap only itself and the finite set
                # of slots obtained by replacing some of its indices with
                # wildcards. Watch those exact slots even before they exist.
                # Sibling concrete elements cannot alter this load and must
                # not repeatedly wake its readers in a large table.
                candidates = {location}
                for match in reversed(indices):
                    candidates.update(candidate[:match.start()] + '/[*]' + candidate[match.end():]
                                      for candidate in tuple(candidates))
                dependencies.update(candidates)
                for other in candidates - {location}:
                    result.update(self.points.get(other, ()))
            else:
                # A wildcard query can overlap arbitrarily many concrete
                # elements, including ones created after this load.
                dependencies.add('shape:' + self.shape(location))
                for other in self.slots_by_shape.get(self.shape(location), ()):
                    if other != location and self.overlaps(location, other):
                        result.update(self.points[other])
        return result, dependencies

    def update(self, left, right, aggregate=False, aggregate_paths=None, cache_key=None):
        vals = self.value(right)
        if not vals and not aggregate:
            return
        locations = self.locations(left)
        if cache_key is not None and not aggregate:
            previous = self.update_images.get(cache_key)
            self.update_images[cache_key] = (locations.bits, vals.bits)
            if previous is not None and (previous[0] & locations.bits == previous[0]
                                         and previous[1] & vals.bits == previous[1]):
                # This equation already propagated old values to old targets.
                # Grow each side of the product once; dependencies were read
                # above even when both deltas are empty.
                fresh_values = TargetSet(self.target_pool, vals.bits & ~previous[1])
                fresh_locations = TargetSet(self.target_pool, locations.bits & ~previous[0])
                if fresh_values:
                    for loc in TargetSet(self.target_pool, locations.bits & previous[0]):
                        self.add_points(loc, fresh_values)
                for loc in fresh_locations:
                    self.add_points(loc, vals)
                return
        for loc in locations:
            self.add_points(loc, vals)
            if aggregate:
                if aggregate_paths is None:
                    # Old extraction schemas have no finite record layout.
                    # Never infer one from an allocator's evolving descendants.
                    self.add_points(loc, {'unknown:aggregate-layout:' + loc})
                    continue
                for source in self.locations(right):
                    for suffix in aggregate_paths:
                        slot = source if source.startswith('unknown:') else self.storage_location(source + suffix)
                        destination = loc if loc.startswith('unknown:') else self.storage_location(loc + suffix)
                        self.add_points(destination, self.value(dict(op='loc', id=slot)))

    def targets(self, call):
        direct = call.get('target')
        return {direct} if direct else {p[3:] for p in self.value(call['expression']) if p.startswith('fn:')}

    def parameter_location(self, target, index, call):
        return target + ':param:' + str(index)

    def variadic_values(self, expression):
        # A va_list is an ABI record on ARM and an array on some hosts. Array
        # decay supplies its address; record copies already carry its values.
        if expression.get('op') == 'addr':
            result = self.target_pool.make()
            for location in self.locations(expression['value']):
                result.update(self.value(dict(op='loc', id=location)))
            return result
        return self.value(expression)

    def return_location(self, target, call):
        return target + ':return'

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
        direct, fields = self.target_pool.make(), defaultdict(self.target_pool.make)
        for source in sources:
            self.watch(source)
            direct.update(self.points.get(source, ()))
            if source.startswith('unknown:'):
                direct.add(source)
                continue
            for suffix in layout:
                fields[suffix].update(self.value(dict(op='loc', id=self.storage_location(source + suffix))))
        # Union source summaries once, rather than constructing every
        # destination x source x field tuple on each solver iteration.
        for destination in destinations:
            self.add_points(destination, direct)
            if destination.startswith('unknown:'):
                for values in fields.values():
                    self.add_points(destination, values | {destination})
            else:
                for suffix, values in fields.items():
                    self.add_points(self.storage_location(destination + suffix), values)

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
                       access_kind=mode, access_path='' if loc.endswith('/$overlap') else loc[len('obj:' + sid):],
                       parse_confidence='conservative', via_alias='interprocedural points-to', **extra)
            row['access_id'] = 'A-' + digest(row)[:20]
            self.facts['accesses'].append(row)

    def solve(self):
        calls = [row for row in self.facts.get('semantic_calls', [])
                 if row.get('function_id') not in self.pruned_functions]
        constraints = [row for row in self.facts.get('pointer_constraints', [])
                       if row.get('function_id') not in self.pruned_functions]
        self.active_constraints = constraints
        self.active_indirect_accesses = [row for row in self.facts.get('indirect_accesses', [])
                                         if row.get('function_id') not in self.pruned_functions]
        tasks = [('constraint', c) for c in constraints] + [('call', c) for c in calls]
        self.tasks = tasks
        self.pending.extend(range(len(tasks)))
        self.enqueued.update(range(len(tasks)))
        evaluations = 0
        trace_hot = bool(os.environ.get('ECRA_SOLVER_TRACE_HOT'))
        hot_tasks = Counter() if trace_hot else None
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
                self.update(c['left'], c['right'], c.get('aggregate', False),
                            c.get('aggregate_paths'), cache_key=('constraint', task))
            else:
                call = item
                targets = self.targets(call)
                if (call.get('returns_pointer') or call.get('returns_aggregate')) and (not targets or any(t not in self.functions for t in targets)):
                    self.update(call['result'], dict(op='unknown', id=call['result']['id']),
                                cache_key=('opaque_return', task))
                for target in targets:
                    function = self.functions.get(target)
                    if function is None:
                        # Opaque callees have no body equations that can read
                        # parameter slots. Their escapes, API effects and
                        # unknown returns are handled at the call site below.
                        continue
                    for i, arg in enumerate(call['arguments']):
                        aggregates = call.get('argument_aggregates', [])
                        layouts = call.get('argument_aggregate_paths', [])
                        self.update(dict(op='loc', id=self.parameter_location(target, i, call)), arg,
                                    i < len(aggregates) and aggregates[i], layouts[i] if i < len(layouts) else None,
                                    cache_key=('argument', task, target, i))
                        if function.get('is_variadic') and i >= function['parameter_count']:
                            variadic_slot = self.parameter_location(target, 'varargs', call)
                            self.update(dict(op='loc', id=variadic_slot), arg,
                                        i < len(aggregates) and aggregates[i], layouts[i] if i < len(layouts) else None,
                                        cache_key=('vararg', task, target, i))
                            if i < len(aggregates) and aggregates[i] and i < len(layouts):
                                for source in self.locations(arg):
                                    for suffix in layouts[i]:
                                        field = source if source.startswith('unknown:') else self.storage_location(source + suffix)
                                        self.add_points(variadic_slot, self.value(dict(op='loc', id=field)))
                    self.update(call['result'], dict(op='loc', id=self.return_location(target, call)),
                                call.get('returns_aggregate', False), call.get('return_aggregate_paths'),
                                cache_key=('return', task, target))
                if call.get('name') in {'memcpy', 'memmove'} and len(call['arguments']) >= 2:
                    self.copy_memory(call)
                if call.get('name') in {'__builtin_va_start', '__builtin_stdarg_start', '__builtin_va_copy'} and call['arguments']:
                    if call['name'] == '__builtin_va_copy' and len(call['arguments']) > 1:
                        values = self.variadic_values(call['arguments'][1])
                    else:
                        values = self.value(dict(op='loc', id=self.parameter_location(call['function_id'], 'varargs', call)))
                    argument = call['arguments'][0]
                    destinations = self.locations(argument['value']) if argument.get('op') == 'addr' else self.locations(argument)
                    for destination in destinations:
                        self.add_points(destination, values)
            if trace_hot:
                hot_tasks[task] += 1
            evaluations += 1
            if os.environ.get('ECRA_SOLVER_TRACE') and evaluations % 10000 == 0:
                print('points-to evaluations', evaluations, 'pending', len(self.pending), 'slots', len(self.points),
                      'values', sum(map(len, self.points.values())), file=sys.stderr, flush=True)
            if trace_hot and evaluations % 100000 == 0:
                active = []
                for index, count in hot_tasks.most_common(8):
                    task_kind, row = tasks[index]
                    active.append(dict(task=index, count=count, kind=task_kind,
                                       file=row.get('file'), line=row.get('line'),
                                       name=row.get('name'),
                                       left_op=row.get('left', {}).get('op'),
                                       right_op=row.get('right', {}).get('op'),
                                       source=re.sub(r'\s+', ' ', row.get('source_text', ''))[:100]))
                largest = sorted(self.points.items(), key=lambda pair: len(pair[1]), reverse=True)[:8]
                print('points-to hotspots', evaluations, 'tasks', active,
                      'largest_slots', [(location, len(values)) for location, values in largest],
                      'recent_locations', list(self.recent_locations),
                      'recent_targets', list(self.recent_targets),
                      'highest_array_indices', sorted(((max(map(int, re.findall(r'/\[(-?\d+)\]', location))), location)
                          for location in self.points if re.search(r'/\[-?\d+\]', location)), reverse=True)[:6],
                      file=sys.stderr, flush=True)
                hot_tasks.clear()
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
            from .common import libc_pointer_modes
            semantics = libc_pointer_modes(name, len(args))
            for i, mode in semantics.items():
                if i < len(args):
                    self.add_access(self.value(args[i]), call, mode, via_api=name)
            self.registrations(call)
            self.dma(call)
        for index, spec in enumerate(self.cfg.get('entry_registrations', [])):
            if index not in self.matched_registration_specs:
                self.facts['unknowns'].append(dict(kind='UNMATCHED_ENTRY_REGISTRATION', api=spec['api'],
                    hint='配置的注册 API 未匹配当前构建的调用；核对名称、宏展开及构建变体'))
        for item in self.active_indirect_accesses:
            targets = self.locations(item['location'])
            self.add_access(targets, item, item['mode'])
            # Known automatic/parameter storage is a resolved object too. It is
            # intentionally absent from the global/static inventory; that must
            # not become a project-wide unknown write to exported globals.
            # ``/$overlap`` is a finite may-touch-any-member view of a *known*
            # root storage object. add_access above records that whole-object
            # effect for every canonical member. It is not evidence of an
            # additional, unidentified pointee. An actual opaque target keeps
            # its ``unknown:`` tag and remains a variable-local blocker.
            if not targets or any(p.startswith('unknown:') for p in targets):
                self.facts['unknowns'].append(dict(kind='UNRESOLVED_POINTEE',
                    function_id=item['function_id'], file=item['file'], line=item['line'],
                    offset=item.get('offset'), may_target_symbol_ids=sorted({self.symbol(p) for p in targets if self.symbol(p)})))
                for target in targets:
                    sid = self.symbol(target)
                    if sid:
                        self.facts['unknowns'].append(dict(kind='UNRESOLVED_POINTEE', symbol_id=sid,
                            access_path='' if target.endswith('/$overlap') else target[len('obj:' + sid):], function_id=item['function_id'],
                            file=item['file'], line=item['line'], offset=item.get('offset'),
                            reason='已知候选目标与不透明目标具有共同的指针来源'))
        self.resolve_evidence(calls)
        rows, sets, identifiers = [], {}, {}
        compressed = self.facts['points_to_stats']['targets'] > 100000
        for location, values in sorted(self.points.items()):
            if not values:
                continue
            if not compressed or len(values) <= 32:
                rows.append(dict(location=location, targets=sorted(values)))
                continue
            if values.bits not in identifiers:
                encoded = format(values.bits, 'x')
                ident = 'PTS-' + digest(encoded)[:20]
                identifiers[values.bits] = ident
                sets[ident] = encoded
            rows.append(dict(location=location, target_set_id=identifiers[values.bits], target_count=len(values)))
        self.facts['pointer_targets'] = rows
        if sets:
            self.facts.update(pointer_target_encoding='INTERNED_BITMAP_V1',
                              pointer_target_atoms=self.target_pool.values, pointer_target_sets=sets)
        # Exact direct calls are retained; resolved edges augment their evidence.
        self.facts['accesses'] = list({a['access_id']: a for a in self.facts['accesses']}.values())

    def escaped_return_slots(self, function):
        returned = function + ':return'
        return {returned} | self.descendant_slots.get(returned, set())

    def reachable_pointer_values(self, initial):
        """Follow pointers/aggregate fields that an opaque consumer can read."""
        pending = self.target_pool.make(initial)
        key = pending.bits
        if key in self.escape_closures:
            return self.escape_closures[key].copy()
        result = self.target_pool.make()
        while pending:
            frontier, pending = pending, self.target_pool.make()
            result.update(frontier)
            for loc in frontier:
                if loc.startswith('fn:'):
                    # Opaque consumers can call a getter and obtain its return
                    # pointees, including context-specific return slots.
                    for slot in self.escaped_return_slots(loc[3:]):
                        pending.update(self.points.get(slot, ()))
                    continue
                if loc.startswith('unknown:'):
                    continue
                candidates = {loc} | self.descendant_slots.get(loc, set()) | self.slots_by_shape.get(self.shape(loc), set())
                for slot in candidates:
                    if slot == loc or slot.startswith(loc + '/') or self.overlaps(slot, loc):
                        pending.update(self.points.get(slot, ()))
            pending.bits &= ~result.bits
        if len(self.escape_closures) >= 64:
            self.escape_closures.clear()
        self.escape_closures[key] = result.copy()
        return result

    def copied_pointer_values(self, sources):
        """Values copied out of storage, excluding its uncopied address."""
        values = self.target_pool.make()
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
        from .common import LIBC_POINTER_MODES
        safe_apis = set(LIBC_POINTER_MODES) | {'__disable_irq', '__enable_irq',
                     '__builtin_va_start', '__builtin_stdarg_start', '__builtin_va_copy', '__builtin_va_end',
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
                        access_path='' if value.endswith('/$overlap') else value[len('obj:' + sid):], function_id=site.get('function_id', ''),
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
        for constraint in self.active_constraints:
            locations = self.locations(constraint['left'])
            if constraint['left'].get('op') in {'deref', 'field', 'index'} and (
                    not locations or any(p.startswith('unknown:') for p in locations)):
                left, right = constraint['left'], constraint['right']
                if (left.get('op') == 'field' and left.get('field') == 'VTOR'
                        and right.get('op') == 'addr'
                        and right.get('value', {}).get('op') == 'loc'):
                    # ARM Cortex-M VTOR consumes the address of a vector
                    # table, not an unknown software callback destination.
                    # Only a proven vector-section object qualifies; the
                    # separate vector recovery pass still reports incomplete
                    # slots as UNRESOLVED_VECTOR_ENTRY.
                    from .vectors import SECTIONS
                    table_location = right['value']['id']
                    table_sid = self.objects.get(table_location)
                    if table_sid and self.variables[table_sid].get('linker_section') in SECTIONS:
                        continue
                escape(self.value(constraint['right']), constraint, 'Pointer value stored through an unresolved destination')
        missing_objects = bool(self.facts.get('build_closure', {}).get('missing_objects'))
        failed_files = {u.get('file') for u in self.facts['unknowns'] if u['kind'] == 'PARSE_FAILED'}
        failed_files.update(u.get('source_file') for u in self.facts.get('translation_units', [])
                            if u.get('parse_status') == 'FAILED')
        incomplete_build = missing_objects or bool(failed_files)
        from .missing_source import may_reference
        for location, values in list(self.points.items()) if incomplete_build else ():
            sid = self.symbol(location)
            if sid and self.variables[sid].get('linkage') == 'EXTERNAL':
                # Missing linked code can name an exported pointer slot and
                # obtain its pointees/callbacks. With a complete closure,
                # visibility alone is not an extra asynchronous consumer.
                variable = self.variables[sid]
                if missing_objects or any(file is None or may_reference(
                        self.facts, file, variable.get('name')) for file in failed_files):
                    escape(values, dict(file=variable.get('definition_file'),
                        line=variable.get('definition_line')),
                        'Missing linked code may consume an exported pointer slot')

        self.facts['address_escapes'] = list({digest(e): e for e in escapes}.values())
        resolved, remaining = [], []
        stored = self.target_pool.make()
        for values in self.points.values():
            stored.update(values)
        stored.bits &= self.target_pool.function_mask
        represented_functions = {value[3:] for value in stored}
        represented_functions.update(target for call in calls for target in self.targets(call))
        represented_functions.update(reg['function_id'] for reg in self.facts.get('registrations', []))
        dynamic_sites = {(item['function_id'], item['file'], item.get('offset')): self.locations(item['location'])
                         for item in self.active_indirect_accesses}
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
                    hint='DMA 语义已确定内存访问方向；生命周期、缓存与所有权仍需复核'))


def enrich(facts, cfg=None):
    if facts.get('pointer_model_applied'):
        return
    Solver(facts, cfg).solve()
    facts['pointer_model_applied'] = True
