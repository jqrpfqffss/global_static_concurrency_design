"""Small serializable C IR for NVIC value flow, built from the selected Clang AST.

This is evidence, not a second C parser. Unsupported expressions stay unknown.
Storage identities and field offsets come from Clang, including CMSIS macros.
"""
from .async_semantics import canonical_cmsis_api


def program(ex, fn):
    from .extract import children, operator, constant_value, walk, FUNCTIONS, WRAPPERS

    def integer_type(c):
        kind = c.type.get_canonical().kind.name
        if kind in {'BOOL','UCHAR','CHAR_U','USHORT','UINT','ULONG','ULONGLONG',
                    'SCHAR','CHAR_S','SHORT','INT','LONG','LONGLONG','ENUM'}:
            return dict(bits=c.type.get_size()*8, unsigned=kind in {'BOOL','UCHAR','CHAR_U','USHORT','UINT','ULONG','ULONGLONG'}, boolean=kind=='BOOL')
        return None

    def expression(c):
        cs, kind = children(c), c.kind.name
        if kind in WRAPPERS and cs:
            if (c.type.get_canonical().kind.name == 'POINTER'
                    and cs[-1].type.get_canonical().kind.name in {'CONSTANTARRAY', 'INCOMPLETEARRAY'}):
                return dict(op='&', args=[expression(cs[-1])])
            folded = constant_value(c)
            if folded is not None and not any(x.kind.name == 'DECL_REF_EXPR' for x in cs):
                return dict(op='const', value=folded)
            nested = expression(cs[-1])
            target = integer_type(c)
            if target and c.type.get_canonical() != cs[-1].type.get_canonical():
                return dict(op='cast', value=nested, **target)
            return nested
        if kind == 'DECL_REF_EXPR' and c.referenced:
            ref = c.referenced
            if ref.kind.name == 'ENUM_CONSTANT_DECL':
                return dict(op='const', value=ref.enum_value, name=ref.spelling)
            return dict(op='ref', key=ex.key(ref))
        if kind == 'MEMBER_REF_EXPR' and cs:
            field = c.referenced
            offset = field.get_field_offsetof() if field and field.kind.name == 'FIELD_DECL' else -1
            return dict(op='member', base=expression(cs[0]), name=c.spelling,
                        pointer=cs[0].type.get_canonical().kind.name == 'POINTER', offset=offset)
        if kind == 'ARRAY_SUBSCRIPT_EXPR' and len(cs) == 2:
            return dict(op='index', base=expression(cs[0]), index=expression(cs[1]),
                        size=max(1, c.type.get_size()))
        if kind in {'BINARY_OPERATOR', 'COMPOUND_ASSIGNMENT_OPERATOR', 'UNARY_OPERATOR'}:
            result = dict(op=operator(c), args=[expression(ch) for ch in cs],
                        store_size=cs[0].type.get_size() if cs else -1, **ex.loc(c))
            target = integer_type(c)
            return dict(op='cast', value=result, **target) if target and operator(c) not in {'=', '++', '--', '&', '*'} else result
        if kind == 'CALL_EXPR':
            ref = c.referenced
            return dict(op='call', name=canonical_cmsis_api(ref.spelling if ref else c.spelling),
                        callee=ex.fid(ref) if ref and ref.kind.name in FUNCTIONS else None,
                        unsequenced=sum(n.kind.name == 'CALL_EXPR' for n in walk(c)) > 2,
                        args=[expression(a) for a in c.get_arguments()], **ex.loc(c))
        if kind == 'CONDITIONAL_OPERATOR' and len(cs) == 3:
            return dict(op='select', args=[expression(ch) for ch in cs])
        if kind == 'INIT_LIST_EXPR':
            return dict(op='init', args=[expression(ch) for ch in cs])
        folded = constant_value(c)
        return dict(op='const', value=folded) if folded is not None else dict(op='unknown')

    def statement(c):
        cs, kind = children(c), c.kind.name
        loc = ex.loc(c)
        if kind in {'COMPOUND_STMT', 'DECL_STMT'}:
            return dict(op='block', body=[statement(ch) for ch in cs])
        if kind == 'VAR_DECL':
            init = cs[-1] if cs and cs[-1].kind.name not in {'TYPE_REF', 'TEMPLATE_REF'} else None
            fields = [f.spelling for f in c.type.get_canonical().get_declaration().get_children() if f.kind.name == 'FIELD_DECL']
            return dict(op='declare', key=ex.key(c), size=c.type.get_size(), fields=fields,
                        value=expression(init) if init else dict(op='unknown'), **loc)
        if kind == 'IF_STMT' and len(cs) in {2, 3}:
            return dict(op='if', condition=expression(cs[0]), yes=statement(cs[1]),
                        no=statement(cs[2]) if len(cs) == 3 else dict(op='block', body=[]), **loc)
        if kind in {'WHILE_STMT', 'DO_STMT', 'FOR_STMT'}:
            condition = cs[0] if kind == 'WHILE_STMT' and cs else cs[-1] if kind == 'DO_STMT' and cs else None
            body = cs[0] if kind == 'DO_STMT' and cs else cs[-1] if cs else None
            return dict(op='loop', condition=expression(condition) if condition else dict(op='unknown'),
                        post_test=kind == 'DO_STMT',
                        body=statement(body) if body else dict(op='block', body=[]), **loc)
        if kind == 'RETURN_STMT':
            return dict(op='return', value=expression(cs[0]) if cs else dict(op='unknown'), **loc)
        if kind in {'SWITCH_STMT', 'GOTO_STMT', 'INDIRECT_GOTO_STMT', 'CXX_TRY_STMT'}:
            # Keep all enclosed configurations, but none is unconditional.
            return dict(op='unsupported', body=[statement(ch) for ch in cs], **loc)
        if kind in {'CASE_STMT', 'DEFAULT_STMT', 'LABEL_STMT'}:
            return dict(op='block', body=[statement(ch) for ch in cs])
        return dict(op='expr', value=expression(c), **loc)

    body = next((ch for ch in fn.get_children() if ch.kind.name == 'COMPOUND_STMT'), None)
    incomplete = any(c.kind.name in {'GOTO_STMT','INDIRECT_GOTO_STMT','BREAK_STMT','CONTINUE_STMT',
                                     'GCC_ASM_STMT','MS_ASM_STMT','CXX_TRY_STMT'} for c in walk(fn))
    return dict(function_id=ex.fid(fn), parameters=[ex.key(p) for p in fn.get_arguments()],
                incomplete_control_flow=incomplete,
                body=statement(body) if body else dict(op='block', body=[]))


def declarations(ex, cursor):
    """Zero initialization is valid only for actual definitions, never externs."""
    from .extract import children, constant_value, FUNCTIONS
    result, irqs = [], []
    def visit(c):
        if c.kind.name in FUNCTIONS:
            return
        if c.kind.name == 'ENUM_CONSTANT_DECL' and c.spelling.endswith('_IRQn'):
            irqs.append(dict(name=c.spelling, value=c.enum_value, **ex.loc(c)))
        if c.kind.name == 'VAR_DECL' and (c.is_definition() or c.storage_class.name != 'EXTERN'):
            cs = children(c)
            initial = cs[-1] if cs and cs[-1].kind.name not in {'TYPE_REF', 'TEMPLATE_REF'} else None
            value = constant_value(initial) if initial else 0
            result.append(dict(key=ex.key(c), value=value, zero=initial is None, size=c.type.get_size(),
                               volatile=c.type.is_volatile_qualified(), **ex.loc(c)))
        for ch in c.get_children():
            visit(ch)
    visit(cursor)
    return result, irqs


def macro_value(definitions, name, seen=()):
    """Evaluate integer macro arithmetic without eval or host code execution."""
    import ast
    import re
    from .nvic import Interpreter
    if name in seen or name not in definitions:
        return None
    values = []
    for token in definitions[name]:
        if re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*', token):
            digits = re.sub(r'[uUlL]+$', '', token)
            values.append(str(int(digits, 16 if digits.lower().startswith('0x') else 8 if len(digits) > 1 and digits.startswith('0') else 10)))
        elif re.fullmatch(r'[A-Za-z_]\w*', token):
            nested = macro_value(definitions, token, (*seen, name))
            if nested is None:
                return None
            values.append('(' + str(nested) + ')')
        elif token in {'(', ')', '+', '-', '*', '/', '%', '~', '&', '|', '^', '<<', '>>'}:
            values.append(token)
        else:
            return None
    operators = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/', ast.Mod: '%',
                 ast.BitAnd: '&', ast.BitOr: '|', ast.BitXor: '^', ast.LShift: '<<', ast.RShift: '>>'}
    def solve(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return Interpreter.binary(operators[type(node.op)], solve(node.left), solve(node.right))
        if isinstance(node, ast.UnaryOp):
            value = solve(node.operand)
            if value is not None:
                return -value if isinstance(node.op, ast.USub) else value if isinstance(node.op, ast.UAdd) else ~value if isinstance(node.op, ast.Invert) else None
        return None
    try:
        return solve(ast.parse(' '.join(values), mode='eval').body)
    except (SyntaxError, ValueError, RecursionError):
        return None
