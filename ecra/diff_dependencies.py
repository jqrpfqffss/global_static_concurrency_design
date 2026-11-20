"""AST value/control dependencies for Diff, independent of safety verdicts.

The extractor records source sites, never guesses their storage targets. The
summary binds those sites to the analyser's final member/array/alias accesses.
Unsupported flow remains an explicit function-level uncertainty.
"""
from collections import defaultdict
from bisect import bisect_left

from .common import digest


SCHEMA = 1


def extract_dependencies(extractor, function):
    from .extract import children, clock_unknown, constant_value, operator, FUNCTIONS, WRAPPERS
    fid = extractor.fid(function)
    effects, issues, environment = [], set(), {}
    values, value_ids = [], {}

    def site(cursor):
        return dict(extractor.loc(cursor), offset=cursor.extent.start.offset,
                    end_offset=max(cursor.extent.end.offset, cursor.location.offset + 1),
                    storage_refs=[dict(root=sid, path=path) for sid, path in extractor.reference_paths(cursor)
                                  if not extractor.variables[sid].get('is_pointer')])

    def value(signature, sources=(), sites=()):
        # Store an expression DAG: repeated local assignments such as x=x+x
        # must not expand the entire previous expression twice at every use.
        key = digest(signature)
        if key not in value_ids:
            value_ids[key] = len(values)
            values.append(signature)
        unique = lambda rows: list({digest(row): row for row in rows}.values())
        return dict(signature={'dependency_value': value_ids[key]},
                    sources=unique(sources), sites=unique(sites))

    def combine(tag, values):
        return value([tag, *[v['signature'] for v in values]],
                     [s for v in values for s in v['sources']],
                     [s for v in values for s in v['sites']])

    def effect(kind, cursor, expression, guards, **extra):
        combined = combine(kind, [expression, *guards])
        control = combine('control', guards)
        effects.append(dict(kind=kind, site=site(cursor), signature=combined['signature'],
                            sources=combined['sources'], reads=combined['sites'],
                            control_sources=control['sources'], control_reads=control['sites'], **extra))

    def local(cursor):
        while cursor.kind.name in WRAPPERS and len(children(cursor)) == 1:
            cursor = children(cursor)[0]
        if cursor.kind.name == 'DECL_REF_EXPR' and cursor.referenced:
            key = extractor.key(cursor.referenced)
            if key not in extractor.symbols and cursor.referenced.kind.name in {'VAR_DECL', 'PARM_DECL'}:
                return key
        return None

    def expression(cursor, guards=(), write=False):
        kind, cs, op = cursor.kind.name, children(cursor), operator(cursor)
        if kind in WRAPPERS and len(cs) == 1:
            return combine([kind, dict(type=cursor.type.get_canonical().spelling)], [expression(cs[0], guards, write)])
        if kind in {'INTEGER_LITERAL', 'CHARACTER_LITERAL', 'CXX_BOOL_LITERAL_EXPR'}:
            number = constant_value(cursor)
            if number is None:
                issues.add('UNRESOLVED_LITERAL')
            return value([kind, number, dict(type=cursor.type.get_canonical().spelling)])
        if kind in {'FLOATING_LITERAL', 'STRING_LITERAL'}:
            # Clang pretty printing is expanded; source token ranges of a
            # macro can contain unrelated declarations or the macro name only.
            from .macro_semantics import expanded_declaration
            symbolic = getattr(cursor.translation_unit, 'clock_text', {}).get(cursor.hash)
            spelling = symbolic or expanded_declaration(cursor)
            if not spelling:
                issues.add('UNRESOLVED_LITERAL')
            return value([kind, spelling, dict(type=cursor.type.get_canonical().spelling)])
        if kind == 'DECL_REF_EXPR' and cursor.referenced:
            ref = cursor.referenced
            if ref.kind.name in FUNCTIONS:
                return value(['function', extractor.fid(ref)])
            if ref.kind.name == 'ENUM_CONSTANT_DECL':
                if clock_unknown(cursor):
                    issues.add('DYNAMIC_PREDEFINED_INPUT')
                    return value(['unknown_enum', ref.spelling])
                return value(['constant', ref.enum_value])
            key = extractor.key(ref)
            if key in extractor.symbols:
                return value(['storage', extractor.symbols[key]], sites=[] if write else [site(cursor)])
            if key in environment:
                return environment[key]
            issues.add('UNBOUND_LOCAL_VALUE')
            return value(['unknown_local', ref.spelling])
        if kind in {'MEMBER_REF_EXPR', 'ARRAY_SUBSCRIPT_EXPR'} or kind == 'UNARY_OPERATOR' and op == '*':
            # The analyser, including its pointer solver, resolves the actual
            # storage. Index/pointer values also influence which cell is used.
            indirect = kind == 'UNARY_OPERATOR' or bool(cs and cs[0].type.get_canonical().kind.name == 'POINTER')
            inner = [expression(c, guards, i == 0 and not indirect) for i, c in enumerate(cs)]
            result = combine([kind, cursor.spelling, op], inner)
            if not write:
                result['sites'].append(site(cursor))
            return result
        if kind == 'CALL_EXPR':
            ref = cursor.referenced
            target = extractor.fid(ref) if ref and ref.kind.name in FUNCTIONS else None
            arguments = [expression(arg, guards) for arg in cursor.get_arguments()]
            if not target:
                issues.add('INDIRECT_CALL_DEPENDENCY')
                # Final resolved call edges still retain the dependency; only
                # the activation/value binding here is unproved.
                target = 'unresolved:' + cursor.spelling
            effect('call', cursor, value(['callee', target]), guards, target=target)
            for index, argument in enumerate(arguments):
                effect('argument', cursor, argument, guards, target=target, parameter=index)
            return value(['return', target, dict(type=cursor.type.get_canonical().spelling), [a['signature'] for a in arguments]],
                         sources=[dict(kind='return', function=target)])
        if kind in {'BINARY_OPERATOR', 'COMPOUND_ASSIGNMENT_OPERATOR'} and op in {
                '=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>='} and len(cs) == 2:
            target = local(cs[0])
            right = expression(cs[1], guards)
            left = expression(cs[0], guards, op == '=')
            result = combine(op, [left, right])
            if target:
                environment[target] = combine('assigned', [right, *guards]) if op == '=' else combine('assigned', [result, *guards])
            else:
                effect('write', cursor, result, guards, writes=[site(cs[0])])
            return result
        if kind == 'UNARY_OPERATOR' and op in {'++', '--'} and cs:
            result = combine(op, [expression(cs[0], guards)])
            target = local(cs[0])
            if target:
                environment[target] = combine('assigned', [result, *guards])
            else:
                effect('write', cursor, result, guards, writes=[site(cs[0])])
            return result
        if kind == 'UNARY_OPERATOR' and op == '&' and cs:
            # Address flow is resolved by points-to facts, not scalar dataflow.
            return combine('address', [expression(cs[0], guards, True)])
        if kind == 'BINARY_OPERATOR' and op == ',' and len(cs) == 2:
            expression(cs[0], guards)
            return expression(cs[1], guards)
        if kind == 'BINARY_OPERATOR' and op in {'&&', '||'} and len(cs) == 2:
            if any(operator(n) in {'=', '+=', '-=', '++', '--'} for n in _walk(cs[1])):
                issues.add('CONDITIONAL_LOCAL_VALUE_FLOW')
            first = expression(cs[0], guards)
            return combine(op, [first, expression(cs[1], [*guards, first])])
        if kind == 'CONDITIONAL_OPERATOR' and len(cs) == 3:
            if any(operator(n) in {'=', '+=', '-=', '++', '--'} for branch in cs[1:] for n in _walk(branch)):
                issues.add('CONDITIONAL_LOCAL_VALUE_FLOW')
            condition = expression(cs[0], guards)
            return combine(kind, [condition, expression(cs[1], [*guards, condition]),
                                  expression(cs[2], [*guards, condition])])
        if kind in {'BINARY_OPERATOR', 'UNARY_OPERATOR'} and op:
            return combine([kind, op, dict(type=cursor.type.get_canonical().spelling)], [expression(c, guards) for c in cs])
        if kind in {'UNARY_EXPR', 'CXX_UNARY_EXPR'}:
            number = constant_value(cursor)
            if number is not None:
                return value(['constant', number])
        if kind in {'INIT_LIST_EXPR', 'COMPOUND_LITERAL_EXPR'}:
            return combine(kind, [expression(c, guards) for c in cs])
        issues.add('UNSUPPORTED_EXPRESSION:' + kind)
        return combine(['unsupported', kind], [expression(c, guards) for c in cs
                       if c.kind.is_expression()])

    def statement(cursor, guards=()):
        kind, cs = cursor.kind.name, children(cursor)
        if kind == 'COMPOUND_STMT':
            for i, child in enumerate(cs):
                if child.kind.name == 'RETURN_STMT' and i != len(cs) - 1:
                    issues.add('EARLY_EXIT_FLOW')
                statement(child, guards)
        elif kind == 'DECL_STMT':
            for child in cs:
                statement(child, guards)
        elif kind == 'VAR_DECL':
            key = extractor.key(cursor)
            if key in extractor.symbols:
                return  # Static initialization is a storage-declaration fact.
            initial = expression(cs[-1], guards) if cs and cs[-1].kind.is_expression() else value(['uninitialized'])
            if initial['sites']:
                effect('observe', cursor, initial, guards)
            environment[key] = combine(['local', dict(type=cursor.type.get_canonical().spelling)], [initial, *guards])
        elif kind == 'IF_STMT' and len(cs) in {2, 3}:
            condition = expression(cs[0], guards)
            effect('observe', cs[0], condition, guards)
            before = dict(environment)
            statement(cs[1], [*guards, combine('if_true', [condition])])
            yes = dict(environment)
            environment.clear()
            environment.update(before)
            if len(cs) == 3:
                statement(cs[2], [*guards, combine('if_false', [condition])])
            for key in sorted(before.keys() | yes.keys() | environment.keys()):
                a, b = yes.get(key, value(['uninitialized'])), environment.get(key, value(['uninitialized']))
                environment[key] = a if a == b else combine('branch_join', [condition, a, b])
            if any(n.kind.name == 'RETURN_STMT' for branch in cs[1:] for n in _walk(branch)):
                issues.add('EARLY_EXIT_FLOW')
        elif kind == 'RETURN_STMT':
            result = combine(['return', dict(type=function.result_type.get_canonical().spelling)],
                             [expression(c, guards) for c in cs])
            effect('return', cursor, result, guards, target=fid)
        elif kind == 'NULL_STMT':
            pass
        elif kind.endswith('_STMT'):
            issues.add('UNSUPPORTED_FLOW:' + kind)
            # Retain readable witnesses, but the function cannot claim a
            # complete dependence proof for loops/gotos/exceptional control.
            for child in cs:
                statement(child, guards)
        else:
            result = expression(cursor, guards)
            if result['sites']:
                effect('observe', cursor, result, guards)

    def _walk(cursor):
        yield cursor
        for child in children(cursor):
            yield from _walk(child)

    for index, parameter in enumerate(function.get_arguments()):
        environment[extractor.key(parameter)] = value(['parameter', index, dict(type=parameter.type.get_canonical().spelling)],
            sources=[dict(kind='parameter', function=fid, index=index)])
    for body in children(function):
        if body.kind.name == 'COMPOUND_STMT':
            statement(body)
    return dict(schema=SCHEMA, complete=not issues, issues=sorted(issues), effects=effects, values=values)


class _AccessSites:
    """Locate an AST interval, retaining the original access/witness order."""
    def __init__(self, rows, cid):
        self.files, self.fallback = defaultdict(list), defaultdict(list)
        for ordinal, row in enumerate(rows):
            access = row[1]
            file, offset = cid(access.get('file')), access.get('offset', -1)
            if type(offset) is int:
                self.files[file].append((offset, ordinal, row))
            else:
                # Preserve the original range check/error for unusual scalar
                # types instead of silently coercing or dropping observations.
                self.fallback[file].append((ordinal, row))
        for entries in self.files.values():
            entries.sort()

    def matching(self, file, start, end):
        entries = self.files.get(file, ())
        lo, hi = bisect_left(entries, (start, -1)), bisect_left(entries, (end, -1))
        selected = [(ordinal, row) for _, ordinal, row in entries[lo:hi]]
        selected.extend(self.fallback.get(file, ()))
        selected.sort(key=lambda item: item[0])
        return (row for _, row in selected)


def bind_dependencies(functions, variables, cid, normalize):
    """Bind AST operands to complete analysed storage, without positional hashes."""
    accesses = defaultdict(list)

    def uncertain_access(access, variable):
        path = variable.get('array_index') or variable.get('field_path') or ''
        possible = ('[*]' in (access.get('access_path') or '')
            or '[*]' in (access.get('storage_index') or '') or '[*]' in path
            or access.get('access_scope') == 'OVERLAPPING_ARRAY_ACCESS' or bool(access.get('via_api'))
            or bool(access.get('via_alias') and (access.get('alias_target_count') != 1
                                               or access.get('alias_has_unknown_target'))))
        if access.get('access_scope') == 'OVERLAPPING_MEMBER_ACCESS':
            possible |= not (variable.get('overlap_groups') and '[*]' not in path)
        return possible

    def uncertainty_reasons(access, variable):
        result = []
        if any('[*]' in (item or '') for item in (access.get('access_path'), access.get('storage_index'),
                variable.get('array_index'), variable.get('field_path'))):
            result.append('DYNAMIC_STORAGE_INDEX')
        if access.get('via_api'):
            result.append('API_EFFECT_NOT_EXACT')
        if access.get('via_alias') and (access.get('alias_target_count') != 1 or access.get('alias_has_unknown_target')):
            result.append('POINTER_TARGET_NOT_UNIQUE_OR_COMPLETE')
        if access.get('access_scope') in {'OVERLAPPING_ARRAY_ACCESS', 'OVERLAPPING_MEMBER_ACCESS'}:
            result.append('STORAGE_OVERLAP_NOT_PROVEN')
        return result if uncertain_access(access, variable) else []

    for sid, variable in variables.items():
        rows = variable.pop('_dependency_accesses', [])
        variable['impact_accesses'] = sorted((dict(sha256=digest(normalize(
            {key: value for key, value in access.items() if key != 'protection_evidence'})),
            certainty='UNCERTAIN' if uncertain_access(access, variable) else 'DEFINITE') for access in rows),
            key=lambda row: (row['sha256'], row['certainty']))
        if variable.get('container'):
            continue
        for access in rows:
            accesses[cid(access.get('function_id'))].append((sid, access))

    for fid, function in functions.items():
        program = function.pop('_dependency_program', None)
        if not program or program.get('schema') != SCHEMA:
            continue
        rows, covered = [], set()
        signatures = []
        sites_index = _AccessSites(accesses[fid], cid)

        def signature(value):
            if isinstance(value, dict) and set(value) == {'dependency_value'}:
                return signatures[value['dependency_value']]
            if isinstance(value, list):
                return [signature(v) for v in value]
            return value

        for expression in program.get('values', []):
            signatures.append(digest(normalize(signature(expression))))

        def resolve(sites, modes):
            found = {}
            clean_path = lambda path: (path or '').replace('/', '.').strip('.').replace('.[', '[')
            for site in sites:
                site_aliases = set()
                for sid, access in sites_index.matching(cid(site.get('file')), site['offset'], site['end_offset']):
                    if (access.get('access_kind') not in modes
                            or not site['offset'] <= access.get('offset', -1) < site['end_offset']):
                        continue
                    # Several expanded macro operands can share one source
                    # offset. Their AST roots/member paths disambiguate them;
                    # coincident locations alone are not an influence proof.
                    if site.get('storage_refs'):
                        path = clean_path((access.get('storage_index') or '') + '.' + (access.get('access_path') or ''))
                        if not any((sid == cid(ref['root']) or sid.startswith(cid(ref['root']) + '::'))
                                   and clean_path(ref['path']) == path for ref in site['storage_refs']):
                            continue
                    covered.add((sid, access.get('access_id')))
                    if access.get('via_alias'):
                        site_aliases.add(sid)
                    uncertain = uncertain_access(access, variables[sid])
                    previous = found.get(sid)
                    if previous is None or previous['certainty'] == 'UNCERTAIN' and not uncertain:
                        found[sid] = dict(node=['variable', sid], certainty='UNCERTAIN' if uncertain else 'DEFINITE',
                                          access_id=access.get('access_id'), file=cid(access.get('file')),
                                          line=access.get('line'), access_kind=access.get('access_kind'),
                                          uncertainty_reasons=uncertainty_reasons(access, variables[sid]))
                if not site.get('storage_refs') and len(site_aliases) > 1:
                    groups = [set(variables[sid].get('overlap_groups') or []) for sid in sorted(site_aliases)]
                    same_root = len({variables[sid]['root'] for sid in site_aliases}) == 1
                    if not (same_root and set.intersection(*groups)):
                        # Multiple expanded pointer operations can share a
                        # location even when each solver result is singleton.
                        # Without an operand binding these are possible edges.
                        for sid in site_aliases:
                            found[sid]['certainty'] = 'UNCERTAIN'
                            found[sid]['uncertainty_reasons'] = sorted(set(found[sid]['uncertainty_reasons']) | {'AMBIGUOUS_SOURCE_SITE'})
            return [found[sid] for sid in sorted(found)]

        for effect in program['effects']:
            reads = resolve(effect.get('reads', []), {'READ', 'RMW', 'WHOLE_OBJECT_READ'})
            writes = resolve(effect.get('writes', []), {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE'})
            inputs = reads + [dict(node=([s['kind'], cid(s['function']), s['index']] if 'index' in s
                                         else [s['kind'], cid(s['function'])]), certainty='DEFINITE')
                              for s in effect['sources']]
            controls = resolve(effect.get('control_reads', []), {'READ', 'RMW', 'WHOLE_OBJECT_READ'})
            control_nodes = {tuple(row['node']) for row in controls} | {
                tuple([s['kind'], cid(s['function']), s['index']] if 'index' in s
                      else [s['kind'], cid(s['function'])]) for s in effect.get('control_sources', [])}
            inputs = [dict(row, dependency_kind='CONTROL' if tuple(row['node']) in control_nodes else 'DATA')
                      for row in inputs]
            outputs = list(writes)
            kind, target = effect['kind'], cid(effect.get('target'))
            if kind in {'return', 'call', 'argument'}:
                outputs.append(dict(node=(['parameter', target, effect['parameter']] if kind == 'argument'
                                           else ['entry' if kind == 'call' else 'return', target]), certainty='DEFINITE'))
            rows.append(dict(kind=kind, signature=digest(normalize(signature(effect['signature']))),
                inputs=inputs, outputs=outputs, observed=reads + writes,
                witness=dict(function=fid, file=cid(effect['site'].get('file')), line=effect['site'].get('line'))))
        missing = sorted({sid for sid, access in accesses[fid]
            if access.get('access_kind') in {'READ', 'WRITE', 'RMW', 'WHOLE_OBJECT_READ', 'WHOLE_OBJECT_WRITE'}
            and (sid, access.get('access_id')) not in covered})
        function['dependencies'] = dict(schema=SCHEMA, source_digest=function['digest'],
            complete=program['complete'] and not missing, issues=program['issues'],
            unmapped_symbol_ids=missing, effects=rows,
            semantic_digest=digest([dict(kind=row['kind'], signature=row['signature'],
                inputs=[dict(node=r['node'], certainty=r['certainty'], dependency_kind=r['dependency_kind']) for r in row['inputs']],
                outputs=[dict(node=r['node'], certainty=r['certainty']) for r in row['outputs']],
                observed=[dict(node=r['node'], certainty=r['certainty']) for r in row['observed']]) for row in rows]))
