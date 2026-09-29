"""Serializable AST-derived control-flow facts (no safety verdicts here)."""
from .common import digest


def build_cfg(extractor, function):
    from .extract import children, operator, tokens, walk, constant_value, FUNCTIONS, WRAPPERS
    fid = extractor.fid(function)
    nodes = []
    unsupported = []

    def node(cursor, op='step', **data):
        ident = len(nodes)
        nodes.append(dict(id=ident, op=op, successors=[], **extractor.loc(cursor),
                          end_offset=cursor.extent.end.offset, **data))
        return ident

    def link(previous, following):
        for ident in previous:
            if following not in nodes[ident]['successors']:
                nodes[ident]['successors'].append(following)

    def value(cursor):
        number = constant_value(cursor)
        if number is not None:
            return dict(constant=number)
        cs = children(cursor)
        if cursor.kind.name in WRAPPERS and cs:
            return value(cs[-1])
        if cursor.kind.name == 'DECL_REF_EXPR' and cursor.referenced:
            if cursor.referenced.kind.name == 'ENUM_CONSTANT_DECL':
                return dict(constant=cursor.referenced.enum_value)
            if extractor.key(cursor.referenced) in extractor.symbols:
                # Mutable static storage may change in another context; it is
                # not a private saved-mask local, even after an assignment.
                return dict(unknown=True)
            return dict(local=extractor.key(cursor.referenced))
        if cursor.kind.name == 'INTEGER_LITERAL':
            try:
                return dict(constant=int(tokens(cursor)[0].rstrip('uUlL'), 0))
            except (ValueError, IndexError):
                pass
        if cursor.kind.name == 'CALL_EXPR':
            return dict(call=cursor.spelling)
        return dict(unknown=True)

    def expr(cursor, incoming):
        cs, kind = children(cursor), cursor.kind.name
        if kind in FUNCTIONS:
            return incoming
        if kind in {'CONDITIONAL_OPERATOR', 'BINARY_OPERATOR'} and (
                kind == 'CONDITIONAL_OPERATOR' or operator(cursor) in {'&&', '||'}):
            start = expr(cs[0], incoming)
            branch = node(cursor, 'branch')
            link(start, branch)
            ends = expr(cs[1], [branch])
            ends += expr(cs[2], [branch]) if len(cs) == 3 else [branch]
            return ends
        # C does not define operand/argument order. Invalidate any mask proof
        # for an expression mixing a call and an access or several calls.
        calls = [c for c in walk(cursor) if c.kind.name == 'CALL_EXPR']
        refs = extractor.refs(cursor)
        ambiguous = len(calls) > 1 or (calls and refs and kind != 'CALL_EXPR')
        if ambiguous:
            unsupported.append(dict(kind='UNSEQUENCED_EXPRESSION', **extractor.loc(cursor)))
            bad = node(cursor, 'unknown', reason='UNSEQUENCED_EXPRESSION')
            link(incoming, bad)
            incoming = [bad]
        if kind == 'CALL_EXPR':
            for arg in cursor.get_arguments():
                incoming = expr(arg, incoming)
            ref = cursor.referenced
            current = node(cursor, 'call', name=ref.spelling if ref else cursor.spelling,
                           callee=extractor.fid(ref) if ref and ref.kind.name in FUNCTIONS else None,
                           arguments=[value(a) for a in cursor.get_arguments()])
        elif kind == 'VAR_DECL':
            initializer = cs[-1] if cs else None
            before = value(initializer) if initializer else dict(unknown=True)
            # get/save APIs return the pre-call mask. Store before applying
            # the call transfer, including configured save-and-disable APIs.
            current = node(cursor, 'assign', local=extractor.key(cursor), value=before)
            link(incoming, current)
            return expr(initializer, [current]) if initializer else [current]
        elif kind == 'BINARY_OPERATOR' and operator(cursor) == '=' and len(cs) == 2:
            # Capture save-and-disable return values before the call changes
            # PRIMASK, exactly as for a declaration initializer.
            left = cs[0]
            if left.kind.name != 'DECL_REF_EXPR':
                incoming = expr(cs[1], incoming)
                incoming = expr(left, incoming)
                current = node(cursor, 'invalidate_locals')
                link(incoming, current)
                return [current]
            saved = value(cs[1])
            if 'call' in saved:
                current = node(cursor, 'assign', local=extractor.key(left.referenced) if left.referenced else '', value=saved)
                link(incoming, current)
                return expr(cs[0], expr(cs[1], [current]))
            incoming = expr(cs[1], incoming)
            incoming = expr(cs[0], incoming)
            left = cs[0]
            current = node(cursor, 'assign', local=extractor.key(left.referenced) if left.referenced else '',
                           value=value(cs[1]))
        elif kind == 'COMPOUND_ASSIGNMENT_OPERATOR' or (kind == 'UNARY_OPERATOR' and operator(cursor) in {'++','--'}):
            for child in cs:
                incoming = expr(child, incoming)
            refs = [c for c in walk(cursor) if c.kind.name=='DECL_REF_EXPR' and c.referenced]
            current = (node(cursor, 'assign', local=extractor.key(refs[0].referenced), value=dict(unknown=True))
                       if cs and cs[0].kind.name=='DECL_REF_EXPR' and refs else node(cursor, 'invalidate_locals'))
        else:
            for child in cs:
                incoming = expr(child, incoming)
            current = node(cursor)
        link(incoming, current)
        return [current]

    returns = []
    scopes = []

    def cleanup_declarations(cursor):
        cleanup_names = {'cleanup', '__cleanup__'}
        declarations = ([cursor] if cursor.kind.name == 'VAR_DECL' else
                        [child for child in children(cursor) if child.kind.name == 'VAR_DECL'])
        return [declaration for declaration in declarations if any(
            child.kind.name.endswith('_ATTR') and ('CLEANUP' in child.kind.name or cleanup_names.intersection(tokens(child)))
            for child in children(declaration)) or
            ('__attribute__' in tokens(declaration) and cleanup_names.intersection(tokens(declaration)))]

    def clean_scopes(incoming, selected):
        # GNU cleanup may restore PRIMASK/BASEPRI or call opaque code. Until
        # its exact effects are interpreted, invalidate only the state AFTER
        # this scope exit. Earlier and subsequently re-established masks are
        # still independently provable. Reverse declaration order is the
        # actual cleanup execution order.
        for scope in reversed(selected):
            for declaration in reversed(scope):
                cleanup = node(declaration, 'unknown', reason='CLEANUP_ATTRIBUTE',
                               cleanup_variable=extractor.key(declaration))
                link(incoming, cleanup)
                incoming = [cleanup]
        return incoming

    def for_parts(cursor, cs):
        # libclang omits empty for-header children. Recover only presence of
        # the three slots from balanced tokens, then bind the ordered AST
        # children. This also works for macro expansions whose child source
        # offsets all coincide at the invocation. Ambiguous headers fail
        # closed rather than mistaking an increment for the condition.
        stream = [token for token in cursor.get_tokens() if token.kind.name != 'COMMENT']
        begin = next((i for i, token in enumerate(stream) if token.spelling == 'for'), None)
        if begin is None or begin + 1 >= len(stream) or stream[begin + 1].spelling != '(':
            return None
        depth, groups = 1, [[]]
        for token in stream[begin + 2:]:
            spelling = token.spelling
            if spelling == '(':
                depth += 1
            elif spelling == ')':
                depth -= 1
                if depth == 0:
                    break
            if spelling == ';' and depth == 1:
                groups.append([])
            elif token.kind.name != 'COMMENT':
                groups[-1].append(spelling)
        if depth or len(groups) != 3 or not cs or len(cs) != 1 + sum(bool(group) for group in groups):
            return None
        ordered = iter(cs[:-1])
        return [next(ordered) if group else None for group in groups] + [cs[-1]]

    def constant_condition(cursor):
        # Only fold side-effect-free integer constant expressions. Clang can
        # also evaluate initialized const objects; their value is deliberately
        # not a basis for removing an execution edge (e.g. volatile MMIO).
        for child in walk(cursor):
            kind = child.kind.name
            if kind == 'CALL_EXPR' or (kind == 'DECL_REF_EXPR' and
                    (not child.referenced or child.referenced.kind.name != 'ENUM_CONSTANT_DECL')):
                return None
            if kind in {'COMPOUND_ASSIGNMENT_OPERATOR', 'UNARY_OPERATOR', 'BINARY_OPERATOR'} and (
                    operator(child) in {'++', '--', '=', '+=', '-=', '*=', '/=', '%=',
                                        '<<=', '>>=', '&=', '^=', '|='}):
                return None
        number = constant_value(cursor)
        return None if number is None else bool(number)

    def stmt(cursor, incoming, loop=None):
        kind, cs = cursor.kind.name, children(cursor)
        if kind == 'COMPOUND_STMT':
            scopes.append([])
            for child in cs:
                incoming = stmt(child, incoming, loop)
            incoming = clean_scopes(incoming, [scopes.pop()])
            return incoming
        if kind in {'DECL_STMT', 'VAR_DECL'} and scopes:
            scopes[-1].extend(cleanup_declarations(cursor))
        if kind == 'IF_STMT' and len(cs) in {2, 3}:
            branch = node(cs[0], 'branch')
            link(expr(cs[0], incoming), branch)
            return stmt(cs[1], [branch], loop) + (stmt(cs[2], [branch], loop) if len(cs) == 3 else [branch])
        if kind in {'WHILE_STMT', 'DO_STMT'} and len(cs) == 2:
            condition, body = (cs[0], cs[1]) if kind == 'WHILE_STMT' else (cs[1], cs[0])
            constant = constant_condition(condition)
            head, tail = node(cursor, 'join'), node(cursor, 'join')
            branch = node(condition, 'branch')
            if kind == 'WHILE_STMT':
                link(incoming, head)
                link(expr(condition, [head]), branch)
                link(stmt(body, [] if constant is False else [branch],
                          (tail, head, len(scopes))), head)
            else:
                body_head = node(body, 'join')
                link(incoming, body_head)
                link(stmt(body, [body_head], (tail, head, len(scopes))), head)
                link(expr(condition, [head]), branch)
                if constant is not False:
                    link([branch], body_head)
            if constant is not True:
                link([branch], tail)
            return [tail]
        if kind == 'FOR_STMT':
            parts = for_parts(cursor, cs)
            if parts is not None:
                initializer, condition, increment, body = parts
                # A for-init declaration lives through all iterations and is
                # destroyed on false-condition, break, or function return.
                scopes.append([])
                if initializer is not None:
                    incoming = stmt(initializer, incoming, loop)
                head, tail = node(cursor, 'join'), node(cursor, 'join')
                increment_head = node(cursor, 'join')
                link(incoming, head)
                if condition is not None:
                    branch = node(condition, 'branch')
                    link(expr(condition, [head]), branch)
                    constant = constant_condition(condition)
                    body_entry = [] if constant is False else [branch]
                    if constant is not True:
                        link([branch], tail)
                else:
                    # for(;;) has no fall-through edge. Only an actual break
                    # may reach tail; continue must still execute increment.
                    body_entry = [head]
                link(stmt(body, body_entry, (tail, increment_head, len(scopes))), increment_head)
                loop_back = expr(increment, [increment_head]) if increment is not None else [increment_head]
                link(loop_back, head)
                return clean_scopes([tail], [scopes.pop()])
        if kind == 'RETURN_STMT':
            exits = incoming
            for child in cs:
                exits = expr(child, exits)
            returns.extend(clean_scopes(exits, scopes))
            return []
        if kind in {'BREAK_STMT', 'CONTINUE_STMT'} and loop:
            exits = clean_scopes(incoming, scopes[loop[2]:])
            link(exits, loop[0 if kind == 'BREAK_STMT' else 1])
            return []
        if kind in {'GOTO_STMT', 'INDIRECT_GOTO_STMT', 'SWITCH_STMT', 'FOR_STMT',
                    'CXX_TRY_STMT', 'CXX_THROW_EXPR'} or 'ASM' in kind:
            unsupported.append(dict(kind=kind, **extractor.loc(cursor)))
            bad = node(cursor, 'unknown', reason=kind)
            link(incoming, bad)
            # Preserve all accesses; unsupported control flow blocks proof for
            # the entire function, rather than inventing valid CFG edges.
            return expr(cursor, [bad])
        return expr(cursor, incoming)

    entry = node(function, 'entry')
    bodies = [c for c in children(function) if c.kind.name == 'COMPOUND_STMT']
    ends = stmt(bodies[0], [entry]) if bodies else [entry]
    exit_node = node(function, 'exit')
    link(ends + returns, exit_node)
    return dict(function_id=fid, entry=entry, exit=exit_node, nodes=nodes,
                complete=bool(bodies) and not unsupported, unsupported=unsupported,
                parameters=[extractor.key(a) for a in function.get_arguments()],
                cfg_id='CFG-' + digest([extractor.tu_name, fid])[:20])
