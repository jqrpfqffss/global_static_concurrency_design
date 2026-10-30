"""Keep deterministic predefined-macro effects in the TU semantic signature."""
from collections import defaultdict, deque
import ctypes
from pathlib import Path

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


def dynamic_input_abstraction(tu, definitions, root):
    """Accept only clock-independent raw facts for immutable string metadata.

    String bytes are not inferred by the analyzer. Numeric/layout uses, or
    references which Clang could fold in this TU, require real preprocessed
    build inputs; accepting the extraction clock would permit stale proofs.
    """
    sensitive = sensitive_macros(definitions, DYNAMIC_BUILTINS)
    uses = [cursor for cursor in tu.cursor.get_children()
            if cursor.kind.name == 'MACRO_INSTANTIATION' and cursor.spelling in sensitive]
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
        expression = children[0]
        while expression.kind.name in {'UNEXPOSED_EXPR', 'PAREN_EXPR'}:
            children = list(expression.get_children())
            if len(children) != 1:
                break
            expression = children[0]
        if expression.kind.name == 'STRING_LITERAL':
            candidates.append((node, expression))
    accepted, records = set(), []
    root = Path(root).resolve()
    for use in uses:
        match = next((node for node, expression in candidates
            if expression.extent.start.file and use.location.file
            and expression.extent.start.file.name == use.location.file.name
            and expression.extent.start.offset <= use.location.offset < expression.extent.end.offset), None)
        if match is None:
            raise ValueError('动态预定义宏用于运行逻辑或存储布局，无法绑定实际构建时刻，已停止提取：'
                             +use.spelling+' @ '+str(use.location))
        accepted.add(match.get_usr())
        file = Path(use.location.file.name).resolve()
        records.append(dict(kind='IMMUTABLE_STRING_METADATA', macro=use.spelling,
            builtins=sorted(sensitive[use.spelling]), declaration_usr=match.get_usr(),
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
