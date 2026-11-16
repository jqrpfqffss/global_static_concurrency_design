"""Keep deterministic predefined-macro effects in the TU semantic signature."""
from collections import defaultdict, deque
import ctypes
from functools import cache
from pathlib import Path
import re

from clang import cindex as ci

from .common import digest


BUILTINS = frozenset({'__LINE__', '__FILE__', '__BASE_FILE__', '__COUNTER__'})
DYNAMIC_BUILTINS = frozenset({'__DATE__', '__TIME__', '__TIMESTAMP__'})
CALLABLES = {'FUNCTION_DECL', 'CXX_METHOD'}
RUNTIME_STATEMENTS = {'COMPOUND_STMT', 'IF_STMT', 'SWITCH_STMT', 'CASE_STMT', 'DEFAULT_STMT',
                      'WHILE_STMT', 'DO_STMT', 'FOR_STMT', 'CXX_FOR_RANGE_STMT', 'LABEL_STMT',
                      'CXX_TRY_STMT', 'CXX_CATCH_STMT'}
COMPILE_TIME_DECL = re.compile(r'\b(?:constexpr|consteval)\b|\b_*(?:enable_if|diagnose_if)_*\s*\(')
STRING_TOKEN = re.compile(r'(?:u8?|U|L)?R?"')


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


def _string_literal(expression):
    while expression.kind.name in {'UNEXPOSED_EXPR', 'PAREN_EXPR'}:
        children = list(expression.get_children())
        if len(children) != 1:
            return None
        expression = children[0]
    return expression if expression.kind.name == 'STRING_LITERAL' else None


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


def _runtime_string_arguments(tu, files):
    declarations, candidates = defaultdict(list), defaultdict(list)

    def visit(node, parents):
        kind = node.kind.name
        if kind in CALLABLES:
            declarations[node.spelling].append(node)
        if kind == 'CALL_EXPR' and node.location.file and node.location.file.name in files:
            frames = iter(reversed(parents))
            parent = next(frames)
            while (parent.kind.name == 'PAREN_EXPR'
                   or (parent.kind.name in {'CSTYLE_CAST_EXPR', 'CXX_STATIC_CAST_EXPR'}
                       and parent.type.kind.name == 'VOID')):
                parent = next(frames)
            if parent.kind.name == 'COMPOUND_STMT':
                owner = next(p for p in frames if p.kind.name not in RUNTIME_STATEMENTS)
                # In particular, a GNU StmtExpr can consume the value of the
                # final expression in its compound statement.
                callee = node.referenced
                if owner.kind.name in CALLABLES and callee and callee.kind.name in CALLABLES:
                    for index, argument in enumerate(node.get_arguments()):
                        if argument.type.get_canonical().kind.name not in {'POINTER', 'CONSTANTARRAY'}:
                            continue
                        literal = _string_literal(argument)
                        if literal is None:
                            continue
                        start, end = literal.extent.start, literal.extent.end
                        file, first = _file_position(start)
                        end_file, last = _file_position(end)
                        if file and file == end_file:
                            candidates[file].append((first, last, start.offset, end.offset,
                                                     index, callee, owner))
        if not node.kind.is_preprocessing():
            for child in node.get_children():
                visit(child, (*parents, node))

    visit(tu.cursor, ())
    return candidates, declarations


def dynamic_input_abstraction(tu, definitions, root, catalog):
    """Accept clock-independent facts for metadata or full runtime string arguments.

    String bytes are not inferred by the analyzer. Numeric/layout uses, or
    references which Clang could fold in this TU, require real preprocessed
    build inputs; accepting the extraction clock would permit stale proofs.
    """
    sensitive = sensitive_macros(definitions, DYNAMIC_BUILTINS)
    invocations = [cursor for cursor in tu.cursor.get_children() if cursor.kind.name == 'MACRO_INSTANTIATION']
    uses = [cursor for cursor in invocations if cursor.spelling in sensitive and cursor.location.file]
    if not uses:
        return []
    candidates = []
    nodes = list(tu.cursor.walk_preorder())
    for node in nodes:
        if (node.kind.name != 'VAR_DECL' or node.semantic_parent is None
                or node.semantic_parent.kind.name not in {'TRANSLATION_UNIT', 'NAMESPACE'}):
            continue
        kind = node.type.get_canonical()
        if (kind.kind.name != 'POINTER' or not kind.is_const_qualified()
                or not kind.get_pointee().is_const_qualified()
                or kind.get_pointee().get_canonical().kind.name not in {'CHAR_S', 'CHAR_U', 'SCHAR', 'UCHAR'}):
            continue
        children = [child for child in node.get_children() if not child.kind.name.endswith('_ATTR')]
        if len(children) != 1:
            continue
        expression = _string_literal(children[0])
        if expression is not None:
            candidates.append((node, expression))

    @cache
    def runtime_arguments():
        return _runtime_string_arguments(tu, {use.location.file.name for use in uses})

    @cache
    def compile_time(declaration):
        return COMPILE_TIME_DECL.search(expanded_declaration(declaration, terse=True)) is not None

    @cache
    def proven_macro(name, forwarding=False):
        pending, seen = [name], set(DYNAMIC_BUILTINS) if not forwarding else set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            if not catalog.get(current):
                return False
            for row in catalog[current]:
                if forwarding:
                    target = _forwarding_target(row)
                    if not target:
                        return False
                    if target in catalog:
                        pending.append(target)
                else:
                    body = _unparen(row[2:])
                    if row[0] or not body:
                        return False
                    pending.extend(token for token in body if not STRING_TOKEN.match(token))
        return True

    @cache
    def invocation_spans(file):
        return [(c.extent.start.offset, c.extent.end.offset, c.spelling) for c in invocations
                if c.location.file and c.location.file.name == file]

    def runtime_use(use):
        location = use.location
        file, offset = location.file.name, location.offset
        spans = invocation_spans(file)
        wrappers = [(start, end) for start, end, _ in spans if start < offset < end]
        # A literal written in a macro body can have the entire invocation
        # as its extent. Only a literal originating in the actual argument
        # can account for a builtin passed to that macro.
        argument_start = max((start for start, _ in wrappers), default=-1)
        arguments, declarations = runtime_arguments()
        # The end of a forwarded literal may point to the start of its last
        # token, including the zero-width span of a lone forwarded builtin.
        matches = [arg for arg in arguments[file] if argument_start < arg[0] <= offset <= arg[1]]
        if not matches:
            return None, '需要独立运行期调用的完整字符串实参或不可变字符串元数据'
        if len(matches) != 1 or not proven_macro(use.spelling):
            return None, '无法唯一确认宏展开后的字符串实参用途'
        first, last, expansion_first, expansion_last, index, callee, owner = matches[0]
        # Within a wrapper, other macro arguments can alter the expansion
        # before it reaches the callee. Require proof for those macros too.
        for start, end in wrappers:
            first, last = min(first, start), max(last, end - 1)
        for start, _, name in spans:
            if first <= start <= last or start in (expansion_first, expansion_last):
                if not (proven_macro(name) or (wrappers and proven_macro(name, forwarding=True))):
                    return None, f'无法唯一确认包装宏 {name} 展开后的字符串实参用途'
        if (callee.spelling.startswith('__builtin_') or compile_time(owner) or compile_time(callee)
                or any(compile_time(d) for d in declarations[callee.spelling])):
            return None, f'调用 {callee.spelling} 可能参与编译期求值'
        return dict(kind='RUNTIME_STRING_ARGUMENT', callee_usr=callee.get_usr(),
                    callee_name=callee.spelling, argument_index=index), None

    accepted, records = set(), []
    root = Path(root).resolve()
    for use in uses:
        match = next((node for node, expression in candidates
            if expression.extent.start.file and use.location.file
            and expression.extent.start.file.name == use.location.file.name
            and expression.extent.start.offset <= use.location.offset < expression.extent.end.offset), None)
        if match is not None:
            accepted.add(match.get_usr())
            record = dict(kind='IMMUTABLE_STRING_METADATA', declaration_usr=match.get_usr())
        else:
            record, reason = runtime_use(use)
            if record is None:
                raise ValueError('动态预定义宏用于运行逻辑或存储布局，无法绑定实际构建时刻，已停止提取：'
                                 + use.spelling + ' @ ' + str(use.location) + '；' + reason)
        file = Path(use.location.file.name).resolve()
        records.append(dict(record, macro=use.spelling, builtins=sorted(sensitive[use.spelling]),
            file=file.relative_to(root).as_posix() if file.is_relative_to(root) else str(file),
            line=use.location.line, column=use.location.column,
            value_coverage='STRING_CONTENT_UNKNOWN'))
    for node in nodes:
        if node.kind.name == 'DECL_REF_EXPR' and node.referenced and node.referenced.get_usr() in accepted:
            raise ValueError('动态预定义字符串在定义 TU 内被引用，可能参与常量折叠；需要真实预处理构建输入，已停止提取：'
                             +str(node.location))
    return records


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
