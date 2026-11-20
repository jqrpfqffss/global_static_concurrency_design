"""Keep deterministic predefined-macro effects in the TU semantic signature."""
from collections import defaultdict, deque
import ctypes
from functools import cache
from itertools import islice
from pathlib import Path
import re

from clang import cindex as ci

from .common import digest


BUILTINS = frozenset({'__LINE__', '__FILE__', '__BASE_FILE__', '__COUNTER__'})
DYNAMIC_BUILTINS = frozenset({'__DATE__', '__TIME__', '__TIMESTAMP__'})


def sensitive_macros(definitions, builtins=BUILTINS):
    """Unbounded, cycle-safe dependency closure over complete macro tokens."""
    reverse = defaultdict(set)
    for name, identifiers in definitions:
        for identifier in identifiers:
            reverse[identifier].add(name)
    result = {name: {name} for name in builtins}
    pending = deque(builtins)
    while pending:
        name = pending.popleft()
        for parent in reverse[name]:
            previous = result.setdefault(parent, set())
            delta = result[name] - previous
            if delta:
                previous.update(delta)
                pending.append(parent)
    return result


def expanded_declaration(cursor, terse=False):
    lib = ci.conf.lib
    policy = lib.clang_getCursorPrintingPolicy
    policy.argtypes, policy.restype = [ci.Cursor], ctypes.c_void_p
    printed = lib.clang_getCursorPrettyPrinted
    printed.argtypes, printed.restype = [ci.Cursor, ctypes.c_void_p], ci._CXString
    printed.errcheck = ci._CXString.from_result
    dispose = lib.clang_PrintingPolicy_dispose
    dispose.argtypes, dispose.restype = [ctypes.c_void_p], None
    value = policy(cursor)
    try:
        if terse:
            set_property = lib.clang_PrintingPolicy_setProperty
            set_property.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
            set_property.restype = None
            set_property(value, 17, 1)  # CXPrintingPolicy_TerseOutput: omit the body
        return printed(cursor, value)
    finally:
        dispose(value)


def _file_position(location):
    # Expansion coordinates collapse all arguments of a forwarding macro to
    # its start. File coordinates identify the originating argument instead.
    get_location = ci.conf.lib.clang_getFileLocation
    pointer = ctypes.POINTER
    get_location.argtypes = [ci.SourceLocation, pointer(ci.c_object_p),
                             pointer(ctypes.c_uint), pointer(ctypes.c_uint), pointer(ctypes.c_uint)]
    get_location.restype = None
    file, offset = ci.c_object_p(), ctypes.c_uint()
    get_location(location, ctypes.byref(file), None, None, ctypes.byref(offset))
    return (ci.File(file).name if file else None, offset.value)


# Clang's preprocessor expands the clock in nested/pasted tokens even when no
# cursor for the resulting builtin survives. Observe argument prescan in a
# separate, body-skipping TU. The first argument is expanded, then discarded,
# leaving precisely the original string token (including for stringification
# and computed includes). Only the primary TU supplies ASTs and diagnostics.
# A private invalid paste is observable even under -w or a diagnostic pragma.
_CLOCK_PROBE = '__ecra_clock_probe_708cc8'
_ANALYSIS_EPOCH = '946684800'


def clock_context(arguments, extra_args=()):
    import os
    cc1 = [arguments[i + 1] for i, arg in enumerate(arguments[:-1]) if arg == '-Xclang']
    explicit = [cc1[i + 1] for i, arg in enumerate(cc1[:-1]) if arg == '-source-date-epoch']
    if explicit:
        replay = '-source-date-epoch' in extra_args
        return [], dict(source='ANALYSIS_ARGUMENT' if replay else 'COMPILE_ARGUMENT',
                        epoch=explicit[-1], bound=not replay)
    epoch = os.environ.get('SOURCE_DATE_EPOCH')
    if epoch is not None:
        # The environment of a later replay is not an archived build record.
        return [], dict(source='REPLAY_ENVIRONMENT', epoch=epoch, bound=False)
    return ['-Xclang', '-source-date-epoch', '-Xclang', _ANALYSIS_EPOCH], dict(
        source='ANALYSIS_EPOCH', epoch=_ANALYSIS_EPOCH, bound=False)


@cache
def _clock_tokens(epoch):
    # Ask this libclang for its three spellings, including its TIMESTAMP
    # semantics. Keep this probe independent of source/-D redefinitions.
    source = 'const char *s[]={' + ','.join(sorted(DYNAMIC_BUILTINS)) + '};'
    unit = ci.Index.create().parse('ecra-clock.c',
        args=['-Xclang', '-source-date-epoch', '-Xclang', epoch],
        unsaved_files=[('ecra-clock.c', source)])
    return dict(zip(sorted(DYNAMIC_BUILTINS), (n.spelling for n in unit.cursor.walk_preorder()
                                              if n.kind.name == 'STRING_LITERAL')))


STRING_TOKEN = re.compile(r'(?:u8?|U|L)?R?"')


def _unparen(tokens):
    while tokens[:1] == ['('] and tokens[-1:] == [')']:
        tokens = tokens[1:-1]
    return tokens


def _comma_groups(tokens):
    groups = [[]]
    for token in tokens:
        if token == ',':
            groups.append([])
        else:
            groups[-1].append(token)
    return groups if tokens else []


def _forwarding_target(row):
    """Prove a single call with arguments forwarded at most once.

    A second use can be folded away or absent from the cursor tree (e.g. a
    type or attribute). Seeing one literal in a call does not prove safety.
    """
    function_like, _, *tokens = row
    if not function_like:
        return tokens[0] if len(tokens) == 1 and tokens[0].isidentifier() else None
    if tokens[:1] != ['('] or ')' not in tokens:
        return None
    end = tokens.index(')')
    parameters = _comma_groups(tokens[1:end])
    if any(len(group) != 1 for group in parameters):
        return None
    formals = {'__VA_ARGS__' if group[0] == '...' else group[0] for group in parameters}
    body = tokens[end + 1:]
    if body[-1:] == [';']:
        body = body[:-1]
    if body[:2] == ['do', '{'] and body[-6:] == [';', '}', 'while', '(', '0', ')']:
        body = body[2:-6]
    body = _unparen(body)
    if len(body) < 3 or not body[0].isidentifier() or body[1] != '(' or body[-1] != ')':
        return None
    if body[0] in formals:
        return None
    for group in _comma_groups(body[2:-1]):
        group = _unparen(group)
        if len(group) != 1:
            return None
        token = group[0]
        if token in formals:
            formals.remove(token)
        elif not (STRING_TOKEN.match(token) or token.isdecimal()):
            return None
    return body[0]


def clock_expansions(ex, index, args, unsaved, catalog, clock):
    tu = ex.translation_unit
    # Token paste can synthesize even the *name* of another macro. Avoid a
    # second parse of TUs without plausible expansion sites.
    dependencies = [(name, {t for row in rows for t in row[2:]})
                    for name, rows in catalog.items()]
    sensitive = sensitive_macros(dependencies, DYNAMIC_BUILTINS | {'##', '%:%:'})
    invocations = {(c.location.file.name, c.location.offset): c for c in tu.cursor.get_children()
                   if c.kind.name == 'MACRO_INSTANTIATION' and c.location.file}
    candidate = next((c for c in invocations.values() if c.spelling in sensitive or
                      (any(row[0] for row in catalog.get(c.spelling, ())) and
                       any(t.spelling in sensitive for t in c.get_tokens() if t.kind.name == 'IDENTIFIER'))), None)
    if candidate is None:
        return []

    def trace_gap(reason):
        loc = candidate.location
        return [dict(kind='PREPROCESSING_TRACE_GAP', form='PREPROCESSING', scope='BUILD',
                     file=ex.relative(loc.file.name), offset=loc.offset, line=loc.line,
                     column=loc.column, range_start=loc.line, range_end=loc.line,
                     translation_unit=ex.tu_name, macro=candidate.spelling, builtins=[],
                     clock=dict(clock), analysis_tokens={}, single_text_use=False,
                     value_coverage='EXPANSION_COVERAGE_UNKNOWN',
                     reason='无法定位全部实际展开；保留已观察的证据，编译期和运行期影响范围待确认。' + reason)]
    # Replay sealed primary Clang buffers, including headers and unsaved files.
    from .input_snapshot import clang_file_contents
    files = {ex.unit['source'], *(inc.include.name for inc in tu.get_includes())}
    buffers = dict(unsaved)
    for filename in files:
        data = clang_file_contents(tu, filename)
        if data is not None:
            buffers[filename] = data
    try:
        values = _clock_tokens(clock['epoch'])
    except ci.TranslationUnitLoadError as error:
        return trace_gap(str(error))
    if set(values) != DYNAMIC_BUILTINS:
        return trace_gap('Clang 未返回完整的预定义字符串类型和值。')
    probe = _CLOCK_PROBE
    while any(name.startswith(probe) for name in catalog):
        probe += '_'
    flags = [f'-D{probe}_paste(a,b)=a##b', f'-D{probe}_second(a,b)=b',
             f'-D{probe}_observe(a,b)={probe}_second(a,b)']
    markers = {}

    def marker(name, definition=None):
        ident = f'{probe}_{len(markers)}'
        markers[ident] = name, definition
        return f'{probe}_observe({probe}_paste({ident},+),)'

    for builtin, value in values.items():
        flags.append(f'-D{builtin}={marker(builtin)} {value}')

    # Annotate actual redefinitions too. An unused marker expands to no
    # tokens. Clang itself handles #undef, conditionals, argument prescan,
    # stringification and push_macro/pop_macro. Never edit the primary TU.
    changes = defaultdict(list)
    for definition in tu.cursor.get_children():
        if definition.kind.name != 'MACRO_DEFINITION' or definition.spelling not in DYNAMIC_BUILTINS:
            continue
        if not definition.location.file:
            continue
        tokens = [t for t in definition.get_tokens() if t.kind.name != 'COMMENT']
        end = 0
        if ci.conf.lib.clang_Cursor_isMacroFunctionLike(definition):
            end = next(i for i, t in enumerate(tokens) if t.spelling == ')')
        loc = definition.location
        binding = dict(name=definition.spelling, file=ex.relative(loc.file.name), line=loc.line,
                       tokens=[t.spelling for t in tokens])
        changes[loc.file.name].append((tokens[end].extent.end.offset, marker(definition.spelling, binding)))
    for file, edits in changes.items():
        data = buffers.get(file)
        if data is None:
            return trace_gap('无法取得宏定义的编译器输入缓冲区：' + ex.relative(file))
        for offset, tag in sorted(set(edits), reverse=True):
            data = data[:offset] + b' ' + tag.encode('ascii') + b' ' + data[offset:]
        buffers[file] = data
    extra = ex.cfg['analysis'].get('extra_args', ())
    analysis_defines = {arg if i and extra[i-1] == '-D' else arg[2:]
                        for i, arg in enumerate(extra) if (i and extra[i-1] == '-D') or arg.startswith('-D')}
    replay_args = list(args)
    for i, arg in enumerate(args):
        separate = i > 0 and args[i - 1] == '-D'
        if not separate and not arg.startswith('-D'):
            continue
        definition = arg if separate else arg[2:]
        head, sep, body = definition.partition('=')
        name = head.split('(', 1)[0]
        if name in DYNAMIC_BUILTINS:
            origin = '<analysis.extra_args>' if definition in analysis_defines else '<command-line>'
            tag = marker(name, dict(name=name, file=origin, spelling=definition))
            replay_args[i] = ('' if separate else '-D') + head + '=' + tag + ' ' + (body if sep else '1')
    try:
        trace = index.parse(ex.unit['source'], args=[*flags, *replay_args, '-w', '-Wno-fatal-errors',
                            '-ferror-limit=0', '-fmacro-backtrace-limit=0'], unsaved_files=list(buffers.items()),
                            options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    except ci.TranslationUnitLoadError as error:
        return trace_gap(str(error))
    sites = {}
    marker_token = re.compile("'" + re.escape(probe) + r"_(\d+)\+'")
    for diagnostic in trace.diagnostics:
        match = marker_token.search(diagnostic.spelling)
        if diagnostic.severity == ci.Diagnostic.Fatal:
            return trace_gap(diagnostic.spelling)
        if not match or not diagnostic.location.file:
            continue
        binding_key = probe + '_' + match[1]
        if binding_key not in markers:
            continue
        name, binding = markers[binding_key]
        loc = diagnostic.location
        filename = loc.file.name
        offset = (tu.get_location(filename, (loc.line, loc.column)).offset
                  if filename in changes else loc.offset)
        cursor = invocations.get((filename, offset))
        key = ex.relative(filename), offset
        row = sites.setdefault(key, dict(file=key[0], line=loc.line, column=loc.column,
            offset=offset, macro=cursor.spelling if cursor else name,
            builtins=set(), translation_unit=ex.tu_name))
        if binding is None:
            row['builtins'].add(name)
        elif binding not in row.setdefault('definitions', []):
            row['definitions'].append(binding)

    @cache
    def single_text(name, forwarding=False):
        pending, seen = [name], set()
        while pending:
            current = pending.pop()
            if current in seen or current in DYNAMIC_BUILTINS:
                continue
            seen.add(current)
            for definition in catalog.get(current, ()):
                if forwarding:
                    target = _forwarding_target(definition)
                    if not target:
                        return False
                    pending.append(target)
                else:
                    body = _unparen(definition[2:])
                    if definition[0] or not body or any(not (STRING_TOKEN.match(t) or t.isidentifier()) for t in body):
                        return False
                    pending.extend(t for t in body if t.isidentifier())
        return True

    # Only this precision proof needs wrapper inspection. All other forms
    # still produce ordinary facts and a conservative dependency scope.
    spans = defaultdict(list)
    for (file, start), invocation in invocations.items():
        if catalog.get(invocation.spelling):
            spans[ex.relative(file)].append((start, invocation.extent.end.offset, invocation.spelling))
    # Sweep enclosing invocations once per file, including nested wrappers.
    last_file = None
    for key, row in sorted(sites.items()):
        file, offset = key
        if file != last_file:
            remaining = iter(sorted(spans[file]))
            following = next(remaining, None)
            active = []
            last_file = file
        active = [(end, name) for end, name in active if offset < end]
        while following is not None and following[0] < offset:
            _, end, name = following
            if offset < end:
                active.append((end, name))
            following = next(remaining, None)
        names = sorted(row['builtins'])
        row['single_text_use'] = single_text(row['macro']) and all(
            single_text(name, forwarding=True) for _, name in active)
        row.update(builtins=names, clock=dict(clock) if names else dict(source='MACRO_DEFINITION',
                   bound=True), analysis_tokens={name: values[name] for name in names},
                   value_coverage='STRING_CONTENT_UNKNOWN' if names and not clock['bound'] else 'BUILD_INPUT')
        if any(d['file'] == '<analysis.extra_args>' for d in row.get('definitions', ())):
            row.update(clock=dict(source='ANALYSIS_MACRO_DEFINITION', bound=False),
                       value_coverage='ANALYSIS_DEFINITION_UNKNOWN')
    return [row for _, row in sorted(sites.items())]


def model_clock_inputs(ex, records):
    """Bind expansion sites before any integer evaluation or CFG pruning."""
    ex.translation_unit.clock_trace_incomplete = any(r.get('kind') == 'PREPROCESSING_TRACE_GAP' for r in records)
    records = [r for r in records if r.get('kind') != 'PREPROCESSING_TRACE_GAP']
    from bisect import bisect_left, bisect_right
    from .extract import FUNCTIONS
    by_file = defaultdict(dict)
    for row in records:
        by_file[row['file']][row['offset']] = row
    offsets = {file: sorted(rows) for file, rows in by_file.items()}
    paths = defaultdict(list)
    literal_paths = defaultdict(list)
    references = defaultdict(list)
    declarations = defaultdict(list)
    unknown_declarations = set()
    declaration_sites = defaultdict(list)
    consumers = defaultdict(set)
    structural_inputs = set()
    unknown_nodes = set()
    ex.translation_unit.clock_unknown_nodes = unknown_nodes
    ex.translation_unit.clock_text = {}
    if not records:
        return

    def visit(node, path):
        kind = node.kind.name
        if node.kind.is_preprocessing():
            return
        start, end = node.extent.start, node.extent.end
        if start.file:
            file = ex.relative(start.file.name)
            positions = offsets.get(file, ())
            for offset in positions[bisect_left(positions, start.offset):bisect_left(positions, end.offset)]:
                paths[file, offset] = max(paths[file, offset], path + [node], key=len)
        if kind in FUNCTIONS and ex.language == 'c++':
            declarations[ex.fid(node)].append(node)
        if kind == 'DECL_REF_EXPR' and node.referenced:
            references[ex.key(node.referenced)].append(path + [node])
        if kind == 'STRING_LITERAL':
            first, last = node.extent.start, node.extent.end
            # Forwarded arguments can have zero-width expansion ranges.
            filename, a = _file_position(first)
            end_file, b = _file_position(last)
            if filename and filename == end_file:
                file = ex.relative(filename)
                positions = offsets.get(file, ())
                for offset in positions[bisect_left(positions,a):bisect_right(positions,b)]:
                    literal_paths[file, offset].append((a, path + [node]))
        previous_enumerator = None
        for child in node.get_children():
            if kind == 'ENUM_DECL' and child.kind.name == 'ENUM_CONSTANT_DECL':
                # An implicit enumerator depends on its predecessor without
                # a DECL_REF_EXPR in Clang's tree.
                if previous_enumerator and not any(n.kind.is_expression() for n in child.get_children()):
                    references[ex.key(previous_enumerator)].append(path + [node, child])
                previous_enumerator = child
            visit(child, path + [node])

    constexpr = re.compile(r'\b(?:constexpr|consteval|enable_if|diagnose_if)\b')

    @cache
    def compile_time_decl(node):
        return constexpr.search(expanded_declaration(node, terse=True)) is not None

    def selects_structure(path):
        for index, node in enumerate(path):
            kind = node.kind.name
            if 'ASM' in kind or kind.endswith(('_ATTR', '_TEMPLATE')) or kind in {
                    'ENUM_CONSTANT_DECL', 'TYPE_ALIAS_DECL', 'TYPEDEF_DECL', 'STATIC_ASSERT'}:
                return True
            if ex.language != 'c++':
                continue
            if kind in {'DECL_REF_EXPR','MEMBER_REF_EXPR'} and node.referenced and index+1 < len(path):
                # Explicit template argument expressions are descendants of the
                # callee designator, even after overload resolution.
                if node.referenced.get_num_template_arguments() >= 0:
                    return True
            if kind == 'IF_STMT' and 'constexpr' in [t.spelling for t in islice(node.get_tokens(), 3)]:
                return True
            if kind == 'CALL_EXPR' and node.referenced and node.referenced.kind.name in FUNCTIONS:
                if compile_time_decl(node.referenced):
                    return True
            if kind == 'VAR_DECL':
                if compile_time_decl(node):
                    return True
                typ = node.type.get_canonical()
                if typ.kind.name == 'CONSTANTARRAY' or typ.get_num_template_arguments() >= 0:
                    init = ci.conf.lib.clang_Cursor_getVarDeclInitializer
                    init.argtypes, init.restype = [ci.Cursor], ci.Cursor
                    if init(node) not in path[index+1:]:
                        return True
        return False

    visit(ex.translation_unit.cursor, [])
    for row in records:
        key = row['file'], row['offset']
        path = paths[key]
        candidates = literal_paths[key]
        first = max((a for a, _ in candidates), default=None)
        literals = [branch for a, branch in candidates if a == first]
        branches = literals or [path]
        fn = next((n for n in reversed(path) if n.kind.name in FUNCTIONS), None)
        variable = next((n for n in reversed(path) if n.kind.name == 'VAR_DECL'), None)
        if fn is not None:
            row.update(function_id=ex.fid(fn), function=fn.spelling)
        if variable is not None and ex.key(variable) in ex.symbols:
            row.update(symbol_id=ex.symbols[ex.key(variable)], variable=variable.spelling)
        row.update(kind='EXPRESSION' if fn is not None else 'DECLARATION',
                   form=path[-1].kind.name if path else 'PREPROCESSING',
                   scope='FUNCTION' if fn is not None else 'BUILD',
                   range_start=path[-1].extent.start.line if path else row['line'],
                   range_end=path[-1].extent.end.line if path else row['line'])
        if variable is not None and literals and all(
                variable in branch and all(n.kind.name in {'PAREN_EXPR','UNEXPOSED_EXPR','STRING_LITERAL','INIT_LIST_EXPR',
                                    'CSTYLE_CAST_EXPR','CXX_STATIC_CAST_EXPR'}
                    for n in branch[branch.index(variable)+1:])
                for branch in literals):
            row.update(kind='STRING_INITIALIZER', scope='STORAGE' if row.get('symbol_id') else 'FUNCTION')
        # Use the compiler's actual expression type including concatenation.
        # Multiple uses of one argument may reach different consumers.
        if literals:
            row['literal_types'] = sorted({p[-1].type.spelling for p in literals})
        calls, size_only = [], bool(literals)
        for branch in branches:
            top = len(branch) - 1
            while top > 0 and branch[top-1].kind.name in {'UNEXPOSED_EXPR','PAREN_EXPR'}:
                top -= 1
            parent = branch[top-1] if top else None
            is_size = bool(parent and parent.kind.name == 'CXX_UNARY_EXPR'
                           and next((t.spelling for t in parent.get_tokens()), '') == 'sizeof')
            size_only &= is_size
            if parent and parent.kind.name == 'CALL_EXPR' and parent.referenced:
                for i, argument in enumerate(parent.get_arguments()):
                    if argument == branch[top]:
                        calls.append((parent, i))
            if row['value_coverage'] == 'STRING_CONTENT_UNKNOWN':
                unknown_nodes.update(n.hash for n in (branch[top:] if is_size else branch))
        if size_only and len(literals) == 1 and row['single_text_use']:
            row.update(kind='LITERAL_SIZE', scope='TYPE_ONLY')
        elif literals and len(calls) == len(branches) == 1 and fn is not None:
            call, i = calls[0]
            callee = call.referenced
            if callee.kind.name == 'CXX_METHOD' and callee.is_virtual_method():
                row['scope'] = 'BUILD'  # The selected override can consume the argument.
            elif callee.kind.name in FUNCTIONS:
                row.update(kind='STRING_ARGUMENT', callee_function_id=ex.fid(callee),
                           callee_name=callee.spelling, argument_index=i)
        # A wrapper may both forward an argument and consume it in a type or
        # attribute which has disappeared from the AST. Keep that gap explicit.
        structural = (not path or any(selects_structure(branch) for branch in [path, *literals]) or
                      (ex.language == 'c++' and (not row['single_text_use'] or any(compile_time_decl(n)
                       for n in [fn, *declarations.get(row.get('callee_function_id'), ())] if n is not None))))
        if (structural and row['scope'] != 'TYPE_ONLY') or row['value_coverage'] == 'ANALYSIS_DEFINITION_UNKNOWN':
            row['scope'] = 'BUILD'
        if not literals and fn is not None and not any(n.kind.name == 'STRING_LITERAL' for n in path):
            row['scope'] = 'BUILD'  # Clang may have erased the selected operand.
        if not row['single_text_use'] and row['scope'] == 'STORAGE':
            row['scope'] = 'FUNCTION' if fn is not None else 'BUILD'
        if row['scope'] != 'TYPE_ONLY' and row['value_coverage'] != 'BUILD_INPUT':
            unknown_nodes.update(n.hash for n in path)
        if path:
            row['form'] = next((n.kind.name for n in reversed(path) if n.kind.name not in
                {'PAREN_EXPR','UNEXPOSED_EXPR','STRING_LITERAL'}), row['form'])
        if row['value_coverage'] != 'BUILD_INPUT' and row['scope'] != 'TYPE_ONLY':
            for n in path:
                if n.kind.is_declaration() and n.kind.name not in FUNCTIONS:
                    key = ex.key(n)
                    unknown_declarations.add(key)
                    declaration_sites[key].append(row)
        for branch in literals:
            ex.translation_unit.clock_text[branch[-1].hash] = [row['macro'], row['builtins']]
        row['reason'] = ('宏值由编译输入指定' if row['value_coverage'] == 'BUILD_INPUT' else
            '字符串字节未知，sizeof 使用实际数组类型' if row['scope'] == 'TYPE_ONLY' else
            '真实构建的字符串字节未知；Clang 可能已选择类型、属性或编译期分派' if row['scope'] == 'BUILD' else
            '真实构建的字符串字节未知；保留调用、读写和可能的访问路径')

    # References to a folded constant need the same guard as the original
    # expression. Traverse declaration dependencies to a fixed point.
    pending = list(unknown_declarations)
    while pending:
        source = pending.pop()
        for path in references.pop(source, ()):
            if selects_structure(path):
                structural_inputs.add(source)
            unknown_nodes.update(n.hash for n in path)
            for n in path:
                if n.kind.is_declaration() and n.kind.name not in FUNCTIONS:
                    key = ex.key(n)
                    consumers[key].add(source)
                    if key not in unknown_declarations:
                        unknown_declarations.add(key)
                        pending.append(key)

    # Walk back from structural consumers to the clock sites feeding them.
    # In f<K>() the selected specialization can be the only one in this AST.
    pending = list(structural_inputs)
    while pending:
        key = pending.pop()
        for row in declaration_sites[key]:
            row.update(scope='BUILD', reason='未知构建输入经声明传入编译期求值；所选实例、类型或布局可能变化')
        for source in consumers[key] - structural_inputs:
            structural_inputs.add(source)
            pending.append(source)


def unused_clock_argument(row, functions):
    if row['kind'] != 'STRING_ARGUMENT' or not row['single_text_use'] or row['scope'] == 'BUILD':
        return False
    body = functions.get(row['callee_function_id'], {})
    index = row['argument_index']
    return (index in body.get('unused_parameters', ()) or
            body.get('unused_variadic_tail') and index >= body['parameter_count'])


def bind_clock_signatures(facts):
    """Bind observed values to the owning consumers, after cross-TU linkage."""
    if not facts['dynamic_predefined_inputs']:
        return
    functions = {f['function_id']: f for f in facts['functions']}
    targets = {v['symbol_id']: v for v in facts['variables']}
    targets.update(functions)
    for row in facts['dynamic_predefined_inputs']:
        if row['scope'] == 'TYPE_ONLY' or unused_clock_argument(row, functions):
            continue
        # Even when an input is bound a changed value may select a different
        # path, specialization or layout. Preserve the origin in this digest.
        for key in ('symbol_id', 'function_id'):
            target = targets.get(row.get(key))
            if target is not None:
                target['consumed_macros_digest'] = digest([target.get('consumed_macros_digest'),
                    row['kind'], row['scope'], row['clock']['source'], row['analysis_tokens'], row.get('definitions')])


def bind_clock_gaps(facts):
    """Bind uncertainty to canonical storage after pointer/call resolution.

    Follow writable storage into its readers, possible callees and consumed
    returns. A missing compile-time dispatch has no complete call/alias graph,
    so retain a build-scope blocker in that case.
    """
    rows = [r for r in facts.get('dynamic_predefined_inputs', ())
            if r['value_coverage'] != 'BUILD_INPUT' and r['scope'] != 'TYPE_ONLY']
    if not rows:
        return
    functions = {f['function_id']: f for f in facts['functions']}
    variables = {v['symbol_id'] for v in facts['variables']}
    edges, touches = defaultdict(set), defaultdict(set)
    calls = defaultdict(list)
    for call in facts['calls']:
        caller, target = call['caller_function_id'], call.get('callee_function_id')
        calls[caller].append(call)
        if target in functions:
            edges[caller].add(target)
            if call.get('result_used', True):
                edges[target].add(caller)
    for a in facts['accesses']:
        f, sid, mode = a['function_id'], a['symbol_id'], a['access_kind']
        touches[f].add(sid)
        if mode not in {'WRITE','WHOLE_OBJECT_WRITE'}:
            edges[sid].add(f)
        if mode not in {'READ','WHOLE_OBJECT_READ'}:
            edges[f].add(sid)
    # Consumer fields for indirect/escaped static initialization can be
    # incomplete; retain the source scope when an address has no body owner.
    unsafe_config = {e.get('function_id') for e in facts['irq_priority_events'] + facts['protection_events']}
    closures = {}
    for row in rows:
        owner, sid = row.get('function_id'), row.get('symbol_id')
        scope, seed = row['scope'], owner
        if scope == 'STORAGE':
            seed = sid
            if seed and not edges[seed] and row['kind'] == 'STRING_INITIALIZER':
                continue
        if row['kind'] == 'STRING_ARGUMENT' and row['single_text_use'] and scope != 'BUILD':
            target = row['callee_function_id']
            if unused_clock_argument(row, functions):
                continue
            seed = target if target in functions else owner
        key = scope, seed
        if key not in closures:
            seen, affected, pending = set(), set(), [seed] if seed else []
            broad = scope == 'BUILD'
            configuration = False
            while pending and not broad:
                current = pending.pop()
                if not current:
                    broad = True  # address flows through a static initializer
                    break
                if current in seen:
                    continue
                seen.add(current)
                if current in unsafe_config:
                    configuration = True
                if current in variables:
                    affected.add(current)
                affected.update(touches[current])
                if any(c['call_kind'].startswith('INDIRECT') and not c.get('callee_function_id')
                       for c in calls[current]):
                    broad = True
                pending.extend(edges[current] - seen)
            if broad:
                affected = variables
            closures[key] = affected, configuration, broad
        affected, configuration, broad = closures[key]
        gap = dict(row, kind='DYNAMIC_PREDEFINED_INPUT', use_kind=row['kind'],
                   scope='BUILD' if broad else 'INTERRUPT_CONFIGURATION' if configuration else scope,
                   reason=f"{row['macro']} ({', '.join(row['builtins'])}) · {row['form']} · "
                          + (row.get('variable') or row.get('function') or row['translation_unit'])
                          + ' · ' + row['reason'])
        if configuration:
            gap['reason'] += '；相关中断或保护配置无法在真实构建时间下确认'
        gap['source_symbol_id'] = gap.pop('symbol_id', None)
        if not broad:
            gap['symbol_ids'] = sorted(affected)
        facts['unknowns'].append(gap)


def presumed_location(location):
    """Respect #line, whose logical line/file differ from physical coordinates."""
    function = ci.conf.lib.clang_getPresumedLocation
    function.argtypes = [ci.SourceLocation, ctypes.POINTER(ci._CXString),
                         ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
    function.restype = None
    filename, line, column = ci._CXString(), ctypes.c_uint(), ctypes.c_uint()
    function(location, ctypes.byref(filename), ctypes.byref(line), ctypes.byref(column))
    return ci._CXString.from_result(filename), line.value


def update_signature(signature, cursors, definitions, root, tu_name, sensitive=None):
    sensitive = sensitive if sensitive is not None else sensitive_macros(definitions)
    root = Path(root).resolve()
    for cursor in cursors:
        if cursor.kind.name != 'MACRO_INSTANTIATION':
            continue
        needed = sensitive.get(cursor.spelling)
        if not needed:
            continue
        record = dict(kind='DETERMINISTIC_PREDEFINED_EXPANSION', macro=cursor.spelling,
                      builtins=sorted(needed))
        if needed & {'__LINE__', '__FILE__'}:
            filename, line = presumed_location(cursor.location)
            if '__LINE__' in needed:
                record['line'] = line
            if '__FILE__' in needed:
                path = Path(filename)
                record['file'] = (path.resolve().relative_to(root).as_posix()
                    if path.is_absolute() and path.resolve().is_relative_to(root) else filename)
        if '__BASE_FILE__' in needed:
            record['base_file'] = tu_name
        # Record order/count captures __COUNTER__; physical line/column does
        # not change its expansion and must not cause comment-only impacts.
        signature.update(digest(record).encode('ascii'))


def function_signatures(functions, cursors, catalog, definitions, root, tu_name,
                        counter_environment_digest=None):
    """Consumed macro definitions and predefined values per source consumer.

    Retain all redefinitions of a consumed name conservatively. Parameter
    identifiers are removed from dependency edges just as in the TU signature.
    No unused header definition can change an unrelated function signature.
    """
    import hashlib
    from .common import relative
    by_file = defaultdict(list)
    for function in functions:
        by_file[function['file']].append(function)
    dependencies = defaultdict(set)
    for name, children in definitions:
        dependencies[name].update(children)
    # Include command-line definitions, whose locations have no file.
    for name, rows in catalog.items():
        if name not in dependencies:
            dependencies[name].update(token for row in rows for token in row[1:] if token in catalog)
    sensitive = sensitive_macros(list(dependencies.items()))
    uses = defaultdict(list)
    counter_positions = defaultdict(list)
    counter_index = 0
    for cursor in cursors:
        if cursor.kind.name != 'MACRO_INSTANTIATION' or not cursor.location.file:
            continue
        file = relative(cursor.location.file.name, root)
        counter = '__COUNTER__' in sensitive.get(cursor.spelling, ())
        for function in by_file.get(file, ()):
            if function['offset'] <= cursor.location.offset <= function['end_offset']:
                uses[function['function_id']].append(cursor)
                if counter:
                    counter_positions[function['function_id']].append(counter_index)
        if counter:
            counter_index += 1
    counter_scope = digest([counter_environment_digest,
        [(name, catalog.get(name, [])) for name in sorted(sensitive) if '__COUNTER__' in sensitive[name]]])
    closures = {}
    for functions_in_file in by_file.values():
        for function in functions_in_file:
            signature = hashlib.sha256()
            for name in sorted({c.spelling for c in uses[function['function_id']]}):
                if name not in closures:
                    seen, pending = set(), [name]
                    while pending:
                        current = pending.pop()
                        if current in seen:
                            continue
                        seen.add(current)
                        pending.extend(child for child in dependencies[current] if child in catalog)
                    closures[name] = digest([(key, catalog.get(key, [])) for key in sorted(seen)])
                signature.update(closures[name].encode('ascii'))
            update_signature(signature, uses[function['function_id']], definitions, root, tu_name, sensitive)
            if counter_positions[function['function_id']]:
                # A preceding expansion/redefinition may change this value
                # without editing its consumer. Keep TU ordering dependence.
                signature.update(digest([counter_scope, counter_positions[function['function_id']]]).encode('ascii'))
            function['consumed_macros_digest'] = signature.hexdigest()
