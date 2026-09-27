"""Serialize Clang pointer expressions without retaining native AST objects."""
from .extract import FUNCTIONS, WRAPPERS, children, operator, walk, constant_value


class PointerExtractor:
    def __init__(self, extractor):
        self.e = extractor
        self.constraints, self.calls, self.accesses = [], [], []
        self.function = ''
        self.parameters = {}
        self.atomic_macros = {}

    def constraint(self, left, right, node):
        self.constraints.append(dict(left=left, right=right, function_id=self.function,
                                     aggregate=node.type.get_canonical().kind.name == 'RECORD',
                                     **self.e.loc(node)))

    def key(self, decl):
        if decl.kind.name == 'PARM_DECL':
            parent = decl.semantic_parent
            for i, p in enumerate(parent.get_arguments()):
                if p == decl:
                    return self.e.fid(parent) + ':param:' + str(i)
        sid = self.e.symbols.get(self.e.key(decl))
        return 'obj:' + sid if sid else 'local:' + self.e.tu_name + ':' + self.e.key(decl)

    def unwrap(self, node):
        while node.kind.name in WRAPPERS:
            # A cast to a typedef can contain TYPE_REF children before its
            # operand. Count expression children, not all AST children, or
            # `(WireByte *)&object` loses the pointee entirely.
            operands = [c for c in children(node) if c.kind.is_expression()]
            if len(operands) != 1:
                break
            node = operands[0]
        return node

    def lvalue(self, node):
        node = self.unwrap(node)
        k, cs = node.kind.name, children(node)
        if k == 'DECL_REF_EXPR' and node.referenced:
            return dict(op='loc', id=self.key(node.referenced))
        if k == 'UNARY_OPERATOR' and operator(node) == '*' and cs:
            return dict(op='deref', value=self.value(cs[0]))
        if k == 'MEMBER_REF_EXPR' and cs:
            base = self.unwrap(cs[0])
            if base.type.get_canonical().kind.name == 'POINTER':
                loc = dict(op='deref', value=self.value(cs[0]))
            else:
                loc = self.lvalue(cs[0])
            return dict(op='field', base=loc, field=node.spelling)
        if k == 'ARRAY_SUBSCRIPT_EXPR' and cs:
            index = constant_value(cs[1]) if len(cs) > 1 else None
            return dict(op='index', base=dict(op='deref', value=self.value(cs[0])),
                        index=str(index) if index is not None else '*')
        return dict(op='empty')

    def value(self, node):
        typ = node.type.get_canonical().kind.name
        node = self.unwrap(node)
        k, cs = node.kind.name, children(node)
        if k == 'DECL_REF_EXPR' and node.referenced and node.referenced.kind.name in FUNCTIONS:
            return dict(op='function', id=self.e.fid(node.referenced))
        if k == 'UNARY_OPERATOR' and operator(node) == '&' and cs:
            operand = self.unwrap(cs[0])
            if operand.kind.name == 'DECL_REF_EXPR' and operand.referenced and operand.referenced.kind.name in FUNCTIONS:
                return dict(op='function', id=self.e.fid(operand.referenced))
            return dict(op='addr', value=self.lvalue(cs[0]))
        if k == 'UNARY_OPERATOR' and operator(node) == '*' and cs:
            if node.type.get_canonical().kind.name in {'FUNCTIONPROTO', 'FUNCTIONNOPROTO'}:
                return self.value(cs[0])
        if k == 'CALL_EXPR':
            return self.result(node)
        if k in {'DECL_REF_EXPR', 'MEMBER_REF_EXPR', 'ARRAY_SUBSCRIPT_EXPR', 'UNARY_OPERATOR'}:
            loc = self.lvalue(node)
            if 'ARRAY' in node.type.get_canonical().kind.name:
                return dict(op='addr', value=loc)
            return loc
        if k in {'CONDITIONAL_OPERATOR', 'BINARY_CONDITIONAL_OPERATOR', 'INIT_LIST_EXPR'}:
            return dict(op='union', items=[self.value(c) for c in cs])
        if k == 'BINARY_OPERATOR' and operator(node) in {'+', '-'} and len(cs) == 2:
            pointer = next((i for i, child in enumerate(cs)
                            if child.type.get_canonical().kind.name == 'POINTER'
                            or 'ARRAY' in child.type.get_canonical().kind.name), None)
            if pointer is not None:
                amount = constant_value(cs[1 - pointer])
                if operator(node) == '-' and amount is not None:
                    amount = -amount
                return dict(op='offset', value=self.value(cs[pointer]),
                            index=str(amount) if amount is not None else '*')
        if k == 'BINARY_OPERATOR' and operator(node) in {'+', '-', ','}:
            return dict(op='union', items=[self.value(c) for c in cs])
        if typ in {'POINTER', 'LVALUEREFERENCE', 'RVALUEREFERENCE'}:
            # Preserve incomplete provenance even when a second assignment
            # supplies known may-targets for the same pointer.
            if constant_value(node) == 0:
                return dict(op='empty')
            return dict(op='unknown', id=self.e.tu_name + ':' + str(node.location.offset))
        return dict(op='empty')

    def result(self, node):
        loc = self.e.loc(node)
        return dict(op='loc', id='call:' + self.e.tu_name + ':' + loc['file'] + ':' + str(loc['offset']))

    def initializer(self, loc, typ, node):
        node = self.unwrap(node)
        if node.kind.name == 'INIT_LIST_EXPR':
            cs = children(node)
            canonical = typ.get_canonical()
            if canonical.kind.name == 'RECORD':
                fields = [f for f in canonical.get_declaration().get_children() if f.kind.name == 'FIELD_DECL']
                position = 0
                for init in cs:
                    parts = children(init)
                    designators = [c for c in parts if c.kind.name == 'MEMBER_REF']
                    if designators:
                        selected, selected_type = loc, canonical
                        for depth, member in enumerate(designators):
                            members = [f for f in selected_type.get_declaration().get_children() if f.kind.name == 'FIELD_DECL']
                            field = next((f for f in members if f.spelling == member.spelling), None)
                            if field is None:
                                break
                            if depth == 0:
                                position = fields.index(field) + 1
                            selected = dict(op='field', base=selected, field=field.spelling)
                            selected_type = field.type.get_canonical()
                        else:
                            self.initializer(selected, selected_type, parts[-1])
                            continue
                        self.e.issue('UNSUPPORTED_POINTER_INITIALIZER', init, self.function)
                    elif position < len(fields):
                        field = fields[position]
                        self.initializer(dict(op='field', base=loc, field=field.spelling), field.type, init)
                        position += 1
                return
            if 'ARRAY' in canonical.kind.name:
                position = 0
                for init in cs:
                    parts = children(init)
                    # Clang exposes designated [index] initializers as an
                    # unexposed expression containing the index and value.
                    if init.kind.name == 'UNEXPOSED_EXPR' and len(parts) > 1:
                        designated = constant_value(parts[0])
                        if designated is not None:
                            position, init = designated, parts[-1]
                    self.initializer(dict(op='index', base=loc, index=str(position)), canonical.element_type, init)
                    position += 1
                return
        self.constraint(loc, self.value(node), node)

    def mode(self, ancestors):
        for parent, index in reversed(ancestors):
            k = parent.kind.name
            if k in WRAPPERS or k == 'MEMBER_REF_EXPR' or k == 'ARRAY_SUBSCRIPT_EXPR' and index == 0:
                continue
            if k == 'UNARY_OPERATOR':
                op = operator(parent)
                return 'ADDRESS_TAKEN' if op == '&' else ('RMW' if op in {'++', '--'} else 'READ')
            if k in {'UNARY_EXPR', 'CXX_UNARY_EXPR'}:
                return None
            if k in {'BINARY_OPERATOR', 'COMPOUND_ASSIGNMENT_OPERATOR'} and index == 0:
                op = operator(parent)
                if op == '=':
                    return 'WRITE'
                if op in {'+=','-=','*=','/=','%=','<<=','>>=','&=','^=','|='}:
                    return 'RMW'
            return 'READ'
        return 'READ'

    def visit(self, node, ancestors=()):
        k, cs = node.kind.name, children(node)
        previous = self.function
        if k in FUNCTIONS:
            if not node.is_definition():
                return
            self.function = self.e.fid(node)
        if k == 'VAR_DECL' and cs:
            init = next((c for c in reversed(cs) if c.kind.is_expression()), None)
            if init:
                self.initializer(dict(op='loc', id=self.key(node)), node.type, init)
        if k == 'BINARY_OPERATOR' and operator(node) == '=' and len(cs) == 2:
            right = self.value(cs[1])
            if right.get('op') == 'offset' and self.lvalue(cs[0]) == right['value']:
                # A flow-insensitive recurrence p=p+1 can visit an arbitrary
                # number of elements. Widen once instead of silently stopping
                # at a fixed propagation count or inventing an unbounded set.
                right['index'] = '*'
            self.constraint(self.lvalue(cs[0]), right, node)
        if k == 'UNARY_OPERATOR' and operator(node) in {'++', '--'} and cs and cs[0].type.get_canonical().kind.name == 'POINTER':
            self.constraint(self.lvalue(cs[0]), dict(op='offset', value=self.value(cs[0]), index='*'), node)
        if k == 'RETURN_STMT' and cs and self.function:
            self.constraint(dict(op='loc', id=self.function + ':return'), self.value(cs[0]), cs[0])
        if k == 'CALL_EXPR' and self.function:
            ref = node.referenced
            direct = ref is not None and ref.kind.name in FUNCTIONS
            self.calls.append(dict(function_id=self.function, target=self.e.fid(ref) if direct else None,
                expression=self.value(cs[0]) if cs else dict(op='empty'), name=ref.spelling if direct else node.spelling,
                arguments=[self.value(arg) for arg in node.get_arguments()], result=self.result(node),
                argument_aggregates=[arg.type.get_canonical().kind.name == 'RECORD' for arg in node.get_arguments()],
                returns_pointer=node.type.get_canonical().kind.name in {'POINTER', 'LVALUEREFERENCE', 'RVALUEREFERENCE'},
                returns_aggregate=node.type.get_canonical().kind.name == 'RECORD',
                source_text=self.e.source(node), **self.e.loc(node)))
        if 'ASM' in k and self.function:
            expressions = [child for child in cs if child.kind.is_expression()]
            self.calls.append(dict(function_id=self.function, target=None,
                expression=dict(op='unknown', id='asm:' + str(node.location.offset)), name='<inline assembly>',
                arguments=[self.value(expr) for expr in expressions],
                result=self.result(node), returns_pointer=False, inline_assembly=True,
                source_text=self.e.source(node), **self.e.loc(node)))
        dynamic = (k == 'UNARY_OPERATOR' and operator(node) == '*'
                   and node.type.get_canonical().kind.name not in {'FUNCTIONPROTO', 'FUNCTIONNOPROTO'})
        if k in {'MEMBER_REF_EXPR', 'ARRAY_SUBSCRIPT_EXPR'} and cs:
            dynamic |= self.unwrap(cs[0]).type.get_canonical().kind.name == 'POINTER'
        if dynamic and self.function:
            mode = self.mode(ancestors)
            if mode:
                self.accesses.append(dict(location=self.lvalue(node), mode=mode, function_id=self.function,
                    source_text=self.e.source(node), **self.e.loc(node)))
        # Clang ATOMIC_EXPR has operation in tokens, not a callee reference.
        atomic_tokens = [t.spelling for t in node.get_tokens()] if k == 'UNEXPOSED_EXPR' and len(cs) > 1 else []
        atomic_name = atomic_tokens[0] if atomic_tokens else ''
        atomic_shape = (k == 'UNEXPOSED_EXPR' and len(cs) >= 2 and
                        cs[0].type.get_canonical().kind.name == 'POINTER' and
                        cs[0].type.get_canonical().get_pointee().kind.name == 'ATOMIC')
        if (k == 'ATOMIC_EXPR' or atomic_shape or atomic_name.startswith(('__c11_atomic_', '__atomic_', 'atomic_'))) and cs and self.function:
            node_loc = self.e.loc(node)
            macro_name = self.atomic_macros.get((node_loc['file'], node_loc['offset']), '')
            spelling = self.e.source(node)
            toks = [t.spelling for t in node.get_tokens()]
            names = [s for s in toks if 'atomic_' in s]
            name = names[0] if names else macro_name
            mode = 'READ' if 'load' in name or len(cs) == 2 else ('WRITE' if 'store' in name or node.type.kind.name == 'VOID' else 'RMW')
            self.accesses.append(dict(location=dict(op='deref', value=self.value(cs[0])), mode=mode,
                function_id=self.function, source_text=spelling, atomic=True, **self.e.loc(node)))
        for i, child in enumerate(cs):
            if self.e.interesting(child):
                self.visit(child, (*ancestors, (node, i)))
        self.function = previous

    def run(self, cursor):
        for node in cursor.get_children():
            if node.kind.name == 'MACRO_INSTANTIATION' and node.spelling.startswith('atomic_'):
                loc = self.e.loc(node)
                self.atomic_macros[(loc['file'], loc['offset'])] = node.spelling
        self.visit(cursor)
        return dict(pointer_constraints=self.constraints, semantic_calls=self.calls, indirect_accesses=self.accesses)
