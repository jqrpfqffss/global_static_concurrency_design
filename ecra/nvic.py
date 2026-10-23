"""Context-sensitive NVIC initialization evidence and conservative lifetime proof.

The interpreter uses only AST IR. Each branch joins equal values; unknown data,
recursion, opaque calls and runtime reconfiguration cannot establish safety.
Source configuration is retained independently of the effective-state proof.
"""
import copy
from collections import defaultdict
from .common import digest


PRIORITY = {'HAL_NVIC_SetPriority', 'NVIC_SetPriority'}
GROUP = {'HAL_NVIC_SetPriorityGrouping', 'NVIC_SetPriorityGrouping'}
ENABLE = {'HAL_NVIC_EnableIRQ', 'NVIC_EnableIRQ'}
DISABLE = {'HAL_NVIC_DisableIRQ', 'NVIC_DisableIRQ'}
APIS = PRIORITY | GROUP | ENABLE | DISABLE


_STATE_TABLES = ('mem', 'priority', 'enabled', 'masks')
_STATE_SCALARS = {int, str, float, bool, bytes, type(None)}


def copy_state(state):
    """Copy branch containers without walking each immutable scalar twice.

    Retain deepcopy and its shared memo for extended values and nested exits,
    preserving aliases/cycles and isolation exactly as a full deepcopy.
    """
    result = state.copy()
    memo = {id(state): result}
    for name in _STATE_TABLES:
        if name not in state:
            continue
        table = state[name]
        if (type(table) is dict and set(map(type, table)).issubset(_STATE_SCALARS)
                and set(map(type, table.values())).issubset(_STATE_SCALARS)):
            if id(table) not in memo:
                memo[id(table)] = table.copy()
            result[name] = memo[id(table)]
        else:
            result[name] = copy.deepcopy(table, memo)
    for name, value in state.items():
        if name not in _STATE_TABLES:
            result[name] = copy.deepcopy(value, memo)
    return result


def recover(facts, cfg):
    if 'nvic_programs' not in facts or not facts['nvic_programs']:
        return
    engine = Interpreter(facts, cfg)
    engine.run()


class Interpreter:
    def __init__(self, facts, cfg):
        self.facts, self.cfg = facts, cfg
        self.functions = {f['function_id']: f for f in facts['functions']}
        self.programs = {p['function_id']: p for p in facts['nvic_programs']}
        self.enums = {e['name']: e['value'] for e in facts.get('nvic_irq_definitions', [])}
        self.by_value = defaultdict(list)
        for name, value in self.enums.items():
            self.by_value[value].append(name)
        widths = {e['argument_values'][0] for e in facts.get('irq_priority_events', [])
                  if e.get('api_name') == 'CMSIS_NVIC_PRIO_BITS'}
        configured = cfg.get('project', {}).get('nvic_priority_bits')
        self.bits = next(iter(widths)) if len(widths) == 1 else configured if not widths else None
        if type(self.bits) is not int or not 1 <= self.bits <= 8 or configured is not None and widths and configured != self.bits:
            self.bits = None
        self.events, self.barriers, self.trace = [], [], []
        self.steps, self.limit = 0, 100000
        self.globals = {v['key']: v for v in facts.get('nvic_globals', [])}
        self.sizes = {key: v.get('size', -1) for key, v in self.globals.items()}
        self.neutral = {'__DMB', '__DSB', '__ISB', '__NOP', '__WFI', '__WFE', '__SEV',
                        '__get_IPSR', '__get_CONTROL', 'NVIC_ClearPendingIRQ', 'HAL_NVIC_ClearPendingIRQ',
                        'NVIC_SetPendingIRQ', 'HAL_NVIC_SetPendingIRQ', '__get_MSP', '__set_MSP',
                        'strlen', 'strnlen', 'strcmp', 'strncmp', 'strchr', 'strrchr'}

    def location(self, node, chain):
        return dict(file=node.get('file'), line=node.get('line'), offset=node.get('offset'),
                    function_id=chain[-1]['function_id'] if chain else '',
                    call_chain=copy.deepcopy(chain))

    @staticmethod
    def join(a, b):
        result = copy_state(a)
        for table in ('mem', 'priority', 'enabled', 'masks'):
            result[table] = {k: a[table].get(k) if a[table].get(k) == b[table].get(k) else None
                             for k in a[table].keys() | b[table].keys()}
        if a.get('group') != b.get('group'):
            result['group'] = None
        result['opaque'] = a['opaque'] or b['opaque']
        result['incomplete_flow'] = a.get('incomplete_flow', False) or b.get('incomplete_flow', False)
        return result

    def address(self, expr, state):
        op = expr.get('op')
        if op == 'ref':
            return expr['key']
        if op == 'member':
            base = self.value(expr['base'], state) if expr['pointer'] else self.address(expr['base'], state)
            if isinstance(base, str) and base.startswith('@'):
                base = base[1:]
            if isinstance(base, str):
                return base + '.' + expr['name']
            if type(base) is int and expr['offset'] >= 0:
                return base + expr['offset'] // 8
        if op == 'index':
            base = self.value(expr['base'], state)
            idx = self.value(expr['index'], state)
            if isinstance(base, str) and base.startswith('@'):
                return base[1:] + '[' + (str(idx) if type(idx) is int else '*') + ']'
            if type(base) is int and type(idx) is int:
                return base + idx * expr['size']
        if op == '*' and expr.get('args'):
            base = self.value(expr['args'][0], state)
            return base[1:] if isinstance(base, str) and base.startswith('@') else base
        return None

    def read(self, address, state):
        if address in state['mem']:
            return state['mem'][address]
        if isinstance(address, str):
            root = address.split('.', 1)[0]
            if root + '.$default' in state['mem']:
                return state['mem'][root + '.$default']
            if self.globals.get(root, {}).get('zero') and not self.globals[root]['volatile'] and not state['opaque']:
                return 0
        if address == 0xE000ED0C and type(state['group']) is int:
            return state['group'] << 8
        return None

    def value(self, expr, state):
        op, args = expr.get('op'), expr.get('args', [])
        if op == 'const':
            return expr.get('value')
        if op == 'cast':
            value = self.value(expr['value'], state)
            if type(value) is not int or expr['bits'] < 1:
                return None
            if expr.get('boolean'):
                return int(bool(value))
            if expr['unsigned']:
                return value & ((1 << expr['bits']) - 1)
            return value if -(1 << (expr['bits'] - 1)) <= value < (1 << (expr['bits'] - 1)) else None
        if op in {'ref', 'member', 'index'}:
            return self.read(self.address(expr, state), state)
        if op == '&' and len(args) == 1:
            address = self.address(args[0], state)
            return '@' + address if isinstance(address, str) else address
        if op == '*':
            return self.read(self.address(expr, state), state)
        if op == 'select':
            cond = self.value(args[0], state)
            if cond is not None:
                return self.value(args[1] if cond else args[2], state)
            before = copy_state(state)
            self.conditions = self.conditions + [dict(conditional_expression=True, proven=False)]
            left = self.value(args[1], state)
            left_state = copy_state(state)
            state.update(before)
            right = self.value(args[2], state)
            state.update(self.join(left_state, state))
            return left if left == right else None
        if op in {'&&', '||'} and len(args) == 2:
            left = self.value(args[0], state)
            if left is not None:
                if op == '&&' and not left:
                    return 0
                if op == '||' and left:
                    return 1
                right = self.value(args[1], state)
                return int(bool(right)) if right is not None else None
            before = copy_state(state)
            self.conditions = self.conditions + [dict(short_circuit=True, proven=False)]
            right = self.value(args[1], state)
            state.update(self.join(before, state))
            return 0 if op == '&&' and right == 0 else 1 if op == '||' and right is not None and bool(right) else None
        if op == 'call':
            return self.call(expr, state, self.chain, self.conditions, self.phase)
        if op in {'=', '+=', '-=', '|=', '&=', '^=', '<<=', '>>='} and len(args) == 2:
            address = self.address(args[0], state)
            right = self.value(args[1], state)
            if address == 0xE000ED0C and right is None:
                known, partial = self.known_bits(args[1], state)
                if known & 0xFFFF0700 == 0xFFFF0700:
                    right = partial
            if op != '=':
                right = self.binary(op[:-1], self.read(address, state), right)
            if address is not None:
                state['mem'][address] = right
                if type(address) is int:
                    self.register(address, right, expr, state)
            else:
                # An unresolved store can alias a handle or NVIC register.
                state['mem'] = {k: None for k in state['mem']}
                self.barriers.append(dict(callee='未解析的间接写入', phase=self.phase,
                                          **self.location(expr, self.chain)))
                state['group'] = None
                state['priority'] = {k: None for k in state['priority']}
                state['enabled'] = {k: None for k in state['enabled']}
            return right
        if op in {'++', '--'} and args:
            address = self.address(args[0], state)
            val = self.binary('+' if op == '++' else '-', self.read(address, state), 1)
            if address is not None:
                state['mem'][address] = val
            return val
        if len(args) == 1:
            val = self.value(args[0], state)
            if type(val) is int:
                return {'!': lambda: int(not val), '~': lambda: ~val, '-': lambda: -val, '+': lambda: val}.get(op, lambda: None)()
        if len(args) == 2:
            return self.binary(op, self.value(args[0], state), self.value(args[1], state))
        return None

    def known_bits(self, expr, state):
        """Recover AIRCR key/PRIGROUP even when unrelated read bits are unknown."""
        if expr.get('op') == 'cast' and expr.get('unsigned') and 0 < expr.get('bits', 0) <= 32:
            known, value = self.known_bits(expr['value'], state)
            mask = (1 << expr['bits']) - 1
            return (known & mask) | (~mask & 0xFFFFFFFF), value & mask
        if expr.get('op') in {'|', '&'} and len(expr.get('args', [])) == 2:
            lk, lv = self.known_bits(expr['args'][0], state)
            rk, rv = self.known_bits(expr['args'][1], state)
            if expr['op'] == '|':
                ones = (lk & lv) | (rk & rv)
                zeros = (lk & ~lv) & (rk & ~rv)
                return (ones | zeros) & 0xFFFFFFFF, ones & 0xFFFFFFFF
            zeros = (lk & ~lv) | (rk & ~rv)
            ones = (lk & lv) & (rk & rv)
            return (ones | zeros) & 0xFFFFFFFF, ones & 0xFFFFFFFF
        if expr.get('op') in {'call', '=', '++', '--'}:
            return 0, 0
        value = self.value(expr, state)
        return (0xFFFFFFFF, value & 0xFFFFFFFF) if type(value) is int else (0, 0)

    @staticmethod
    def binary(op, left, right):
        if left is None or right is None:
            return None
        if op in {'==', '!='}:
            return int((left == right) if op == '==' else (left != right))
        if type(left) is not int or type(right) is not int:
            return None
        try:
            return {'+': lambda: left + right, '-': lambda: left - right, '*': lambda: left * right,
                    '/': lambda: int(left / right), '%': lambda: left % right,
                    '<<': lambda: left << right if 0 <= right < 64 else None,
                    '>>': lambda: left >> right if 0 <= right < 64 else None,
                    '&': lambda: left & right, '|': lambda: left | right, '^': lambda: left ^ right,
                    '<': lambda: int(left < right), '>': lambda: int(left > right),
                    '<=': lambda: int(left <= right), '>=': lambda: int(left >= right),
                    '&&': lambda: int(bool(left) and bool(right)), '||': lambda: int(bool(left) or bool(right)),
                    ',': lambda: right}.get(op, lambda: None)()
        except (ArithmeticError, ValueError):
            return None

    def event(self, name, values, node, state, irq=None):
        row = dict(api_name=name, argument_values=values, irq_number=irq, phase=self.phase,
                   conditions=copy.deepcopy(self.conditions), validity='CONFIRMED' if not self.conditions and not state.get('incomplete_flow') else 'CONDITIONAL',
                   grouping=state['group'], priority_bits=self.bits, **self.location(node, self.chain))
        row['event_id'] = 'NVIC-' + digest(row)[:20]
        self.events.append(row)
        return row

    def configure(self, name, values, node, state):
        irq = values[0] if values and type(values[0]) is int else None
        row = self.event(name, values, node, state, irq if name not in GROUP else None)
        if name in GROUP:
            state['group'] = values[0] & 7 if values and type(values[0]) is int else None
            row['configured_grouping'] = state['group']
        elif name in PRIORITY:
            pre = values[1] if len(values) > 1 else None
            sub = values[2] if len(values) > 2 else None
            logical = None
            group = state['group']
            if name == 'HAL_NVIC_SetPriority':
                row.update(configured_preemption=pre, configured_subpriority=sub)
            if self.bits and type(pre) is int:
                if name == 'HAL_NVIC_SetPriority':
                    if type(group) is int and type(sub) is int:
                        pre_bits = min(self.bits, 7 - group)
                        sub_bits = self.bits - pre_bits
                        logical = ((pre & ((1 << pre_bits) - 1)) << sub_bits) | (sub & ((1 << sub_bits) - 1))
                else:
                    logical = pre & ((1 << self.bits) - 1)
                    if type(group) is int:
                        sub_bits = self.bits - min(self.bits, 7 - group)
                        row.update(configured_preemption=logical >> sub_bits,
                                   configured_subpriority=logical & ((1 << sub_bits) - 1))
            row['logical_priority'] = logical
            if irq is None:
                state['priority'] = {k: None for k in state['priority']}
            else:
                state['priority'][irq] = logical
        else:
            if irq is None:
                state['enabled'] = {k: None for k in state['enabled']}
            else:
                state['enabled'][irq] = name in ENABLE
        return None

    def register(self, address, value, node, state):
        # Only architecture-defined addresses, sizes and AIRCR write key give
        # enough semantics. Peripheral register names alone are insufficient.
        if address == 0xE000ED0C:
            if type(value) is int and value >> 16 == 0x5FA:
                self.configure('NVIC_SetPriorityGrouping', [(value >> 8) & 7], node, state)
            else:
                state['group'] = None
                self.event('SCB_AIRCR_UNRESOLVED', [value], node, state)
        elif 0xE000E400 <= address < 0xE000E4F0:
            width = node.get('store_size', 1)
            for byte in range(width if width in {1, 2, 4} else 1):
                logical = ((value >> (8 * byte)) & 255) >> (8 - self.bits) if type(value) is int and self.bits else None
                self.configure('NVIC_SetPriority', [address - 0xE000E400 + byte, logical], node, state)
        elif 0xE000E100 <= address < 0xE000E120 or 0xE000E180 <= address < 0xE000E1A0:
            enable = address < 0xE000E180
            base = 0xE000E100 if enable else 0xE000E180
            if type(value) is int:
                for bit in range(32):
                    if value & (1 << bit):
                        self.configure('NVIC_EnableIRQ' if enable else 'NVIC_DisableIRQ',
                                       [(address - base) * 8 + bit], node, state)
            else:
                state['enabled'] = {k: None for k in state['enabled']}

    def call(self, node, state, chain, conditions, phase):
        self.chain, self.conditions, self.phase = chain, conditions, phase
        values = [self.value(a, state) for a in node.get('args', [])]
        if node.get('unsequenced'):
            values = [None for _ in values]
            state['mem'] = {k: None for k in state['mem']}
        name = node.get('name', '')
        if name in {'NVIC_GetPriorityGrouping', 'HAL_NVIC_GetPriorityGrouping'}:
            return state['group']
        if name == 'NVIC_EncodePriority' and len(values) == 3 and self.bits and all(type(v) is int for v in values):
            group, pre, sub = values
            pre_bits = min(self.bits, 7 - (group & 7))
            sub_bits = self.bits - pre_bits
            return ((pre & ((1 << pre_bits) - 1)) << sub_bits) | (sub & ((1 << sub_bits) - 1))
        if name in {'memset', 'memcpy', 'memmove', 'memcmp'}:
            if name == 'memcmp':
                return None
            destination = values[0] if values else None
            if isinstance(destination, str) and destination.startswith('@'):
                key = destination[1:]
                state['mem'] = {k: v for k, v in state['mem'].items() if k != key and not str(k).startswith(key + '.')}
                if (name == 'memset' and len(values) > 2 and values[1] == 0
                        and type(values[2]) is int and self.sizes.get(key, -1) > 0 and values[2] >= self.sizes[key]):
                    state['mem'][key + '.$default'] = 0
                return destination
        if name in APIS:
            return self.configure(name, values, node, state)
        if name in {'NVIC_Init', 'NVIC_PriorityGroupConfig'}:
            if name == 'NVIC_PriorityGroupConfig':
                return self.configure('NVIC_SetPriorityGrouping', [values[0] >> 8 if values and type(values[0]) is int else None], node, state)
            addr = values[0][1:] if values and isinstance(values[0], str) and values[0].startswith('@') else None
            def field(key):
                return self.read(addr + '.' + key, state) if addr else None
            irq, pre, sub, enabled = (field(k) for k in ('NVIC_IRQChannel', 'NVIC_IRQChannelPreemptionPriority',
                                                        'NVIC_IRQChannelSubPriority', 'NVIC_IRQChannelCmd'))
            if enabled is not None:
                if enabled:
                    self.configure('HAL_NVIC_SetPriority', [irq, pre, sub], node, state)
                return self.configure('NVIC_EnableIRQ' if enabled else 'NVIC_DisableIRQ', [irq], node, state)
            # In the standard peripheral library only the enabled branch
            # programs priority. An unresolved command must join both paths.
            original = copy_state(state)
            self.conditions = conditions + [dict(nvic_init_command_unknown=True)]
            self.configure('HAL_NVIC_SetPriority', [irq, pre, sub], node, state)
            self.configure('NVIC_EnableIRQ', [irq], node, state)
            disabled = copy_state(original)
            self.configure('NVIC_DisableIRQ', [irq], node, disabled)
            state.update(self.join(state, disabled))
            return None
        mask = {'__disable_irq': ('PRIMASK', 1), '__enable_irq': ('PRIMASK', 0),
                '__disable_fault_irq': ('FAULTMASK', 1), '__enable_fault_irq': ('FAULTMASK', 0)}
        if name in mask or name.startswith(('__set_PRIMASK', '__set_BASEPRI', '__set_FAULTMASK')):
            key, val = mask.get(name, (name.replace('__set_', ''), values[0] if values else None))
            if name == '__set_BASEPRI_MAX':
                key = 'BASEPRI'
                previous = state['masks'].get(key)
                val = None if previous is None or val is None else val if previous == 0 else previous if val == 0 else min(previous, val)
            elif key in {'PRIMASK', 'FAULTMASK'} and type(val) is int:
                val &= 1
            state['masks'][key] = val
            self.event(name, values, node, state)
            return None
        if name.startswith('__get_') and name[6:] in {'PRIMASK', 'BASEPRI', 'FAULTMASK'}:
            return state['masks'].get(name[6:])
        if name in self.neutral or name.startswith(('__CLZ', '__REV', '__LDREX', '__STREX')):
            return None
        callee = node.get('callee')
        if callee in self.programs and callee not in {c['function_id'] for c in chain} and len(chain) < 48:
            frame = dict(function_id=callee, function=self.functions.get(callee, {}).get('name'),
                         file=node.get('file'), line=node.get('line'))
            program = self.programs[callee]
            if program.get('incomplete_control_flow'):
                state['incomplete_flow'] = True
                self.barriers.append(dict(callee='控制流或汇编效果尚未完全建模', phase=phase, **self.location(node, chain)))
            for key, val in zip(program['parameters'], values):
                state['mem'][key] = val
            result, returned, val = self.execute(program['body'], state, chain + [frame], conditions, phase)
            for exit_state in result.pop('possible_exits', []):
                result = self.join(result, exit_state)
            state.update(result)
            self.chain, self.conditions, self.phase = chain, conditions, phase
            return val
        self.barriers.append(dict(callee=name, phase=phase, **self.location(node, chain)))
        state['opaque'] = True
        state['group'] = None
        state['priority'] = {k: None for k in state['priority']}
        state['enabled'] = {k: None for k in state['enabled']}
        state['mem'] = {k: None for k in state['mem']}
        state['masks'] = {k: None for k in state['masks']}
        return None

    def execute(self, node, state, chain, conditions, phase):
        self.steps += 1
        self.chain, self.conditions, self.phase = chain, conditions, phase
        if self.steps > self.limit:
            state['opaque'] = True
            state['priority'] = {k: None for k in state['priority']}
            return state, True, None
        op = node['op']
        if op == 'block':
            exits = []
            for child in node['body']:
                state, returned, val = self.execute(child, state, chain, conditions, phase)
                exits.extend(state.pop('possible_exits', []))
                if returned:
                    for exit_state in exits:
                        state = self.join(state, exit_state)
                    return state, True, val
            for exit_state in exits:
                state.setdefault('possible_exits', []).append(exit_state)
        elif op == 'expr':
            self.value(node['value'], state)
        elif op == 'declare':
            self.sizes[node['key']] = node.get('size', -1)
            state['mem'][node['key']] = self.value(node['value'], state)
            if node['value'].get('op') == 'init':
                state['mem'][node['key'] + '.$default'] = 0
                for field, value in zip(node.get('fields', []), node['value'].get('args', [])):
                    state['mem'][node['key'] + '.' + field] = self.value(value, state)
        elif op == 'return':
            return state, True, self.value(node['value'], state)
        elif op == 'if':
            cond = self.value(node['condition'], state)
            if cond is not None:
                guard = dict(file=node.get('file'), line=node.get('line'), outcome=bool(cond), proven=True)
                # Proven guards are source evidence, not unresolved conditions.
                before = len(self.events)
                result = self.execute(node['yes'] if cond else node['no'], state, chain, conditions, phase)
                for event in self.events[before:]:
                    event.setdefault('proven_guards', []).append(guard)
                return result
            guard = dict(file=node.get('file'), line=node.get('line'), outcome=True, proven=False)
            a, ar, av = self.execute(node['yes'], copy_state(state), chain, conditions + [guard], phase)
            b, br, bv = self.execute(node['no'], copy_state(state), chain, conditions + [dict(guard, outcome=False)], phase)
            if ar != br:
                continuing, terminated = (b, a) if ar else (a, b)
                continuing.setdefault('possible_exits', []).append(terminated)
                return continuing, False, None
            return self.join(a, b), ar and br, av if av == bv else None
        elif op == 'loop':
            cond = self.value(node['condition'], state)
            if node.get('post_test') and cond == 0:
                return self.execute(node['body'], state, chain, conditions, phase)
            if cond != 0:
                loop_phase = 'RUNTIME' if self.functions.get(chain[-1]['function_id'], {}).get('name') == 'main' else phase
                other, _, _ = self.execute(node['body'], copy_state(state), chain,
                    conditions + [dict(file=node.get('file'), line=node.get('line'), loop=True)], loop_phase)
                if loop_phase == 'RUNTIME':
                    return state, True, None
                state = self.join(state, other)
        elif op == 'unsupported':
            other = copy_state(state)
            for child in node['body']:
                other, _, _ = self.execute(child, other, chain, conditions + [dict(unsupported=True)], phase)
            state = self.join(state, other)
        return state, False, None

    def run(self):
        state = dict(mem={key: v['value'] for key, v in self.globals.items() if not v['volatile']},
                     group=None, priority={}, enabled={}, masks={}, opaque=False)
        mains = [fid for fid, fn in self.functions.items() if fn['name'] == 'main' and fid in self.programs]
        if len(mains) == 1:
            fid = mains[0]
            state['incomplete_flow'] = self.programs[fid].get('incomplete_control_flow', False)
            state, _, _ = self.execute(self.programs[fid]['body'], state,
                [dict(function_id=fid, function='main', file=self.functions[fid]['file'], line=self.functions[fid]['line'])], [], 'INITIALIZATION')
            for exit_state in state.pop('possible_exits', []):
                state = self.join(state, exit_state)
        # Other execution roots can reconfigure NVIC after initialization. Walk
        # each with the initialized handles, never invent callback sources.
        roots = {b['function_id'] for b in self.facts.get('context_bindings', []) if b['call_depth'] == 0} - set(mains)
        for fid in sorted(roots):
            if fid in self.programs:
                if self.programs[fid].get('incomplete_control_flow'):
                    self.barriers.append(dict(callee='异步入口存在尚未完全建模的控制流或汇编', phase='RUNTIME',
                        function_id=fid, file=self.functions[fid]['file'], line=self.functions[fid]['line'], call_chain=[]))
                self.execute(self.programs[fid]['body'], copy_state(state),
                    [dict(function_id=fid, function=self.functions[fid]['name'], file=self.functions[fid]['file'], line=self.functions[fid]['line'])], [], 'RUNTIME')
        self.facts['nvic_resolved_events'] = list({digest(e): e for e in self.events}.values())
        self.facts['nvic_lifecycle_barriers'] = list({digest(e): e for e in self.barriers}.values())
        runtime = [e for e in self.events if e['phase'] == 'RUNTIME']
        runtime_opaque = any(e['phase'] == 'RUNTIME' for e in self.barriers)
        runtime_group = runtime_opaque or self.steps > self.limit or any(e['api_name'] in GROUP or e['api_name'] == 'SCB_AIRCR_UNRESOLVED' for e in runtime)
        numbers = set(self.enums.values()) | {e['irq_number'] for e in self.events if e.get('irq_number') is not None}
        rows = []
        for number in sorted(numbers):
            names = sorted(self.by_value.get(number, []))
            exceptions = {-14: 'NMI_Handler', -13: 'HardFault_Handler', -12: 'MemManage_Handler',
                          -11: 'BusFault_Handler', -10: 'UsageFault_Handler', -5: 'SVC_Handler',
                          -4: 'DebugMon_Handler', -2: 'PendSV_Handler', -1: 'SysTick_Handler'}
            vector_names = [exceptions[number]] if number in exceptions else [name[:-5] + '_IRQHandler' for name in names]
            vector_names = sorted(set(vector_names) | {self.functions[e['function_id']]['name']
                for e in self.facts.get('vector_entries', []) if e.get('slot') == number + 16 and e.get('function_id') in self.functions})
            events = [e for e in self.events if e.get('irq_number') == number and e['api_name'] in APIS - GROUP]
            if not events and not any(f['name'] in vector_names for f in self.functions.values()):
                continue
            configured = [e for e in events if e['api_name'] in PRIORITY]
            dynamic = runtime_group or any(e['api_name'] in PRIORITY and e.get('irq_number') in {None, number} for e in runtime)
            logical, group = state['priority'].get(number), state['group']
            effective = logical is not None and type(group) is int and self.bits is not None and not dynamic and not state.get('incomplete_flow')
            sub_bits = self.bits - min(self.bits, 7 - group) if self.bits and type(group) is int else None
            last = configured[-1] if configured else {}
            source_groups = sorted({e['configured_grouping'] for e in self.events
                                    if e['api_name'] in GROUP and e.get('configured_grouping') is not None})
            root_functions = {fid for fid, fn in self.functions.items() if fn['name'] in vector_names}
            context_ids = {b['context_id'] for b in self.facts.get('context_bindings', [])
                           if b['call_depth'] == 0 and b['function_id'] in root_functions}
            vector_evidence = [e for e in self.facts.get('vector_entries', []) if e.get('slot') == number + 16]
            rows.append(dict(irq_number=number, irqn=names, vectors=vector_names,
                source_groupings=source_groups,
                source_declarations=[e for e in self.facts.get('irq_priority_events', [])
                    if e.get('api_name') in PRIORITY and (e.get('argument_values') or [None])[0] == number],
                context_ids=sorted(context_ids), vector_evidence=vector_evidence,
                mapping_validity='VECTOR_TABLE' if vector_evidence else 'BUILD_ENUM_AND_HANDLER_CONVENTION',
                execution_paths=[dict(b, functions=[self.functions.get(fid, {}).get('name', fid) for fid in b.get('path', [])])
                                 for b in self.facts.get('context_bindings', []) if b['context_id'] in context_ids],
                priority_bits=self.bits, grouping=group, preemption_bits=self.bits - sub_bits if sub_bits is not None else None,
                subpriority_bits=sub_bits, logical_priority=logical,
                preemption_priority=logical >> sub_bits if logical is not None and sub_bits is not None else None,
                subpriority=logical & ((1 << sub_bits) - 1) if logical is not None and sub_bits is not None else None,
                source_configurations=configured, configuration_events=events,
                configured_preemption=last.get('configured_preemption'), configured_subpriority=last.get('configured_subpriority'),
                enabled=state['enabled'].get(number), enable_scope='主初始化路径结束时；触发条件需另行核对。',
                enable_validity='UNRESOLVED' if runtime_opaque or any(e['api_name'] in ENABLE | DISABLE and e.get('irq_number') in {None, number} for e in runtime) else 'INITIALIZATION_ONLY',
                effective_validity='CONFIRMED' if effective else 'UNRESOLVED', runtime_reconfiguration=dynamic,
                preemption_validity='CONFIRMED' if effective and source_groups == [group]
                    and all(e.get('logical_priority') == logical for e in configured) else 'UNRESOLVED',
                reason=('已沿实际调用链、实参和分支恢复初始化优先级；未发现可达的运行期优先级改写。'
                        if effective else '源码配置证据单独保留；分组、分支合流、不可见调用或运行期重配置使有效优先级尚无法完全证明。'),
                masks=state['masks'], mapping_evidence=[e for e in self.facts.get('nvic_irq_definitions', []) if e['value'] == number]))
        self.facts['nvic_priorities'] = rows
        self.facts['nvic_recovery'] = dict(priority_bits=self.bits, grouping=state['group'],
            masks=state['masks'], steps=self.steps, budget_exhausted=self.steps > self.limit,
            note='源码配置、初始化合流结果和运行期有效性分别记录；使能不代表已触发。')
