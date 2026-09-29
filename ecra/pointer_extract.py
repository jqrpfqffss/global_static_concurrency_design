"""Serialize Clang pointer expressions without retaining native AST objects."""
import ast
import re
from .extract import FUNCTIONS, WRAPPERS, children, operator, walk, constant_value, tokens, constant_condition, has_entry_label


class PointerExtractor:
    def __init__(self, extractor):
        self.e = extractor
        self.constraints, self.calls, self.accesses = [], [], []
        self.function = ''
        self.parameters = {}
        self.atomic_macros = {}
        self.layout_cache = {}
        self.extent_cache = {}
        self.stable_pointer_parameters = {}
        self.path_conditions = []
        self.guard_sites = {}
        self.condition_cache = {}
        self.storage = {}
        self.variadic_expression_cache = {}
        self.constant_regions = []

    def is_variadic_expression(self, node):
        if node.kind.name == 'VA_ARG_EXPR':
            return True
        if node.kind.name != 'UNEXPOSED_EXPR':
            return False
        if node not in self.variadic_expression_cache:
            self.variadic_expression_cache[node] = tokens(node, 1) == ['__builtin_va_arg']
        return self.variadic_expression_cache[node]

    def storage_definition(self, location, typ):
        canonical = typ.get_canonical()
        declaration = canonical.get_declaration()
        key = (canonical.kind.name, canonical.spelling, declaration.get_usr() or declaration.hash)
        extents = self.extent_cache.get(key, {})
        def arrays(current, prefix='', seen=()):
            current = current.get_canonical()
            if 'ARRAY' in current.kind.name:
                extents[prefix] = current.element_count if current.kind.name == 'CONSTANTARRAY' else None
                arrays(current.element_type, prefix + '/[*]', seen)
            elif current.kind.name == 'RECORD':
                declaration = current.get_declaration()
                key = declaration.get_usr() or declaration.hash
                if key not in seen:
                    for field in declaration.get_children():
                        if field.kind.name == 'FIELD_DECL':
                            arrays(field.type, prefix + '/' + field.spelling, (*seen, key))
        if key not in self.extent_cache:
            arrays(typ)
            self.extent_cache[key] = extents
        self.storage[location] = dict(location=location, function_id=self.function,
            paths=self.aggregate_paths(typ),
            array_extents=extents,
            array_size=canonical.element_count if canonical.kind.name == 'CONSTANTARRAY' else None)

    def stable_parameters(self, function):
        parameters = {self.key(p) for p in function.get_arguments()
                      if p.type.get_canonical().kind.name == 'POINTER'}
        if not parameters:
            return parameters
        for node in walk(function):
            cs = children(node)
            if 'ASM' in node.kind.name:
                return set()
            if node.kind.name == 'BINARY_OPERATOR' and operator(node) == '=' and cs:
                target = self.unwrap(cs[0])
                if target.kind.name == 'DECL_REF_EXPR' and target.referenced:
                    parameters.discard(self.key(target.referenced))
            if node.kind.name in {'UNARY_OPERATOR', 'COMPOUND_ASSIGNMENT_OPERATOR'} and cs:
                if node.kind.name == 'COMPOUND_ASSIGNMENT_OPERATOR' or operator(node) in {'&', '++', '--'}:
                    target = self.unwrap(cs[0])
                    if target.kind.name == 'DECL_REF_EXPR' and target.referenced:
                        parameters.discard(self.key(target.referenced))
        return parameters

    def conditions(self, ancestors):
        result = []
        if not self.stable_pointer_parameters.get(self.function):
            return result
        for parent, index in ancestors:
            if parent.kind.name != 'IF_STMT' or index not in {1, 2}:
                continue
            key = (self.function, parent, index)
            if key in self.condition_cache:
                result.extend(self.condition_cache[key])
                continue
            self.condition_cache[key] = []
            cs = children(parent)
            if len(cs) not in {2, 3}:
                continue
            condition = self.unwrap(cs[0])
            if condition.kind.name != 'BINARY_OPERATOR' or operator(condition) not in {'==', '!='}:
                continue
            operands = children(condition)
            if len(operands) != 2:
                continue
            left, right = map(self.value, operands)
            if right.get('op') == 'loc' and right.get('id') in self.stable_pointer_parameters.get(self.function, set()):
                left, right = right, left
            if (left.get('op') != 'loc' or left.get('id') not in self.stable_pointer_parameters.get(self.function, set())
                    or right.get('op') != 'addr'):
                continue
            location = right.get('value', {})
            # A direct static object/member address is invariant. Mutable
            # pointer values, arbitrary pointer arithmetic and null tests do
            # not supply a disjoint-address proof here.
            while location.get('op') in {'field', 'index'}:
                location = location['base']
            if location.get('op') != 'loc' or not location.get('id', '').startswith('obj:'):
                continue
            row = dict(parameter=left, target=right,
                equals=(operator(condition) == '==') == (index == 1), **self.e.loc(condition))
            self.condition_cache[key] = [row]
            result.append(row)
        return result

    def aggregate_paths(self, typ):
        """Finite inline storage layout; pointer fields are terminal leaves.

        A may-alias allocation can hold several C types. Copying every dynamic
        points-to descendant would incorrectly embed all those types into each
        other and generate paths such as pin/pin/pin indefinitely. The source
        language only copies the fields of the declared aggregate value.
        """
        canonical = typ.get_canonical()
        declaration_type = canonical
        while 'ARRAY' in declaration_type.kind.name:
            declaration_type = declaration_type.element_type.get_canonical()
        declaration = declaration_type.get_declaration()
        key = (canonical.kind.name, canonical.spelling, declaration.get_usr() or declaration.hash)
        if key in self.layout_cache:
            return self.layout_cache[key]

        def fields(current, prefix='', seen=()):
            current = current.get_canonical()
            if 'ARRAY' in current.kind.name:
                element = prefix + '/[*]'
                return [element] + fields(current.element_type, element, seen)
            if current.kind.name != 'RECORD':
                return [prefix] if prefix else []
            declaration = current.get_declaration()
            identity = declaration.get_usr() or declaration.hash
            if identity in seen:
                return []
            result = []
            for field in declaration.get_children():
                if field.kind.name != 'FIELD_DECL':
                    continue
                path = prefix + '/' + field.spelling
                result.append(path)
                result.extend(fields(field.type, path, (*seen, identity)))
            return result

        result = sorted(set(fields(canonical)))
        self.layout_cache[key] = result
        return result

    def pointee_layout(self, node):
        """Recover an argument's typed extent before a C void-pointer cast."""
        original = self.unwrap(node)
        typ = original.type.get_canonical()
        if 'ARRAY' not in typ.kind.name:
            if typ.kind.name not in {'POINTER', 'LVALUEREFERENCE', 'RVALUEREFERENCE'}:
                return None, None
            typ = typ.get_pointee().get_canonical()
        if typ.kind.name in {'VOID', 'FUNCTIONPROTO', 'FUNCTIONNOPROTO', 'INVALID'}:
            return None, None
        size = typ.get_size()
        return self.aggregate_paths(typ), size if size >= 0 else None

    def constraint(self, left, right, node):
        self.constraints.append(dict(left=left, right=right, function_id=self.function,
                                     path_conditions=list(self.path_conditions),
                                     aggregate=node.type.get_canonical().kind.name == 'RECORD',
                                     aggregate_paths=self.aggregate_paths(node.type)
                                         if node.type.get_canonical().kind.name == 'RECORD' else [],
                                     **self.e.loc(node)))

    def cleanup_call(self, declaration):
        """Represent GNU's implicit scope-exit call using ordinary C linkage."""
        names = set()
        for attribute in children(declaration):
            if not attribute.kind.name.endswith('_ATTR'):
                continue
            spelling = tokens(attribute)
            for index, token in enumerate(spelling[:-2]):
                if token.strip('_') == 'cleanup' and spelling[index + 1] == '(':
                    names.add(spelling[index + 2])
        for name in sorted(names):
            candidates = [f for f in self.e.functions.values() if f['name'] == name]
            if not candidates:
                candidates = [dict(function_id='unresolved-cleanup:' + name, name=name)]
            for callee in candidates:
                location = self.e.loc(declaration)
                self.calls.append(dict(function_id=self.function, target=callee['function_id'],
                    expression=dict(op='function', id=callee['function_id']), name=name,
                    arguments=[dict(op='addr', value=dict(op='loc', id=self.key(declaration)))],
                    argument_values=[None], argument_aggregates=[False], argument_aggregate_paths=[[]],
                    result=dict(op='loc', id='cleanup:' + self.e.tu_name + ':' + str(location['offset'])),
                    returns_pointer=False, returns_aggregate=False, return_aggregate_paths=[],
                    path_conditions=list(self.path_conditions), implicit_call='GNU_CLEANUP',
                    source_text=self.e.source(declaration), **location))
                self.e.calls.append(dict(caller_function_id=self.function, callee_function_id=callee['function_id'],
                    callee_name=name, call_kind='IMPLICIT_CLEANUP', **location))

    def assembly_branches(self, node, expressions):
        """Resolve literal ARM branches to exact void(void) function operands.

        Other operands, register-indirect transfers, returned values and data
        uses remain opaque. The CFG still treats assembly as an unknown mask
        operation; a recovered call edge is not a protection proof.
        """
        template = []
        for token in tokens(node):
            if token == ':':
                break
            if token.startswith('"'):
                try:
                    template.append(ast.literal_eval(token))
                except (ValueError, SyntaxError):
                    return set()
        assembly = ''.join(template)
        uses = re.findall(r'(?<!%)%(?:[A-Za-z])?(\d+)', assembly)
        branches = []
        for instruction in re.split(r'[;\n]', assembly):
            match = re.fullmatch(r'\s*(?:b|bx|bl|blx)\s+%(\d+)\s*(?:@[^\n]*)?', instruction)
            if match:
                branches.append(match[1])
        resolved = set()
        for index, expression in enumerate(expressions):
            operand = str(index)
            value = self.value(expression)
            callee = self.e.functions.get(value.get('id')) if value.get('op') == 'function' else None
            if (not callee or callee.get('parameter_count') != 0 or callee.get('return_type_kind') != 'VOID'
                    or not uses.count(operand) or uses.count(operand) != branches.count(operand)):
                continue
            location = self.e.loc(node)
            self.calls.append(dict(function_id=self.function, target=callee['function_id'],
                expression=value, name=callee['name'], arguments=[],
                result=dict(op='loc', id='asm-branch:' + self.e.tu_name + ':' + str(location['offset']) + ':' + operand),
                returns_pointer=False, returns_aggregate=False, implicit_call='ARM_LITERAL_BRANCH',
                path_conditions=list(self.path_conditions), source_text=self.e.source(node), **location))
            self.e.calls.append(dict(caller_function_id=self.function, callee_function_id=callee['function_id'],
                callee_name=callee['name'], call_kind='IMPLICIT_ASM_BRANCH', **location))
            resolved.add(index)
        return resolved

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
            if self.is_variadic_expression(node):
                break
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
        if k in {'COMPOUND_LITERAL_EXPR', 'CXX_TEMPORARY_OBJECT_EXPR'}:
            return self.value(node)
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
        if k == 'StmtExpr' or k == 'STMT_EXPR':
            # GNU statement expressions take the value of the final
            # expression statement, including calls inside registration
            # macros. Earlier statements still emit normal constraints.
            body = children(cs[-1]) if cs and cs[-1].kind.name == 'COMPOUND_STMT' else []
            if body and body[-1].kind.is_expression():
                return self.value(body[-1])
        if self.is_variadic_expression(node) and cs:
            operand = next((child for child in cs if child.kind.is_expression()), None)
            payload = dict(op='va_arg', value=self.value(operand) if operand is not None else dict(op='empty'))
            if node.type.get_canonical().kind.name == 'RECORD':
                storage = self.result(node)
                self.storage_definition(storage['id'], node.type)
                for path in self.aggregate_paths(node.type):
                    # The unordered variadic may-set contains pointer payloads
                    # from every argument. Keep those in every record field
                    # until argument position/type refinement is available.
                    self.constraints.append(dict(left=dict(op='loc', id=storage['id'] + path),
                        right=payload, function_id=self.function, path_conditions=list(self.path_conditions),
                        **self.e.loc(node)))
                return storage
            # Addresses may travel through uintptr_t before a later cast.
            return payload
        if k in {'COMPOUND_LITERAL_EXPR', 'CXX_TEMPORARY_OBJECT_EXPR'}:
            initializer = next((child for child in cs if child.kind.name == 'INIT_LIST_EXPR'), None)
            if initializer is not None:
                loc = self.e.loc(node)
                storage = dict(op='loc', id='literal:' + self.e.tu_name + ':' + loc['file'] + ':' + str(loc['offset']))
                self.storage_definition(storage['id'], node.type)
                self.initializer(storage, node.type, initializer)
                return storage
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
        if k == 'BINARY_OPERATOR' and operator(node) == ',' and len(cs) == 2:
            return self.value(cs[1])
        if k == 'BINARY_OPERATOR' and operator(node) in {'+', '-'}:
            return dict(op='union', items=[self.value(c) for c in cs])
        if k == 'BINARY_OPERATOR' and operator(node) == '=' and len(cs) == 2:
            return self.value(cs[1])
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
            if k in WRAPPERS:
                continue
            if k in {'MEMBER_REF_EXPR', 'ARRAY_SUBSCRIPT_EXPR'} and index == 0:
                # Inline members/elements are one storage path, emitted by
                # the outer expression. Crossing a pointer consumes its value
                # without modifying the pointer object itself.
                base = self.unwrap(children(parent)[0])
                return 'READ' if base.type.get_canonical().kind.name == 'POINTER' else None
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
        previous_conditions = self.path_conditions
        if k in FUNCTIONS:
            if not node.is_definition():
                return
            self.function = self.e.fid(node)
            self.stable_pointer_parameters[self.function] = self.stable_parameters(node)
            self.storage_definition(self.function + ':return', node.result_type)
        self.path_conditions = self.conditions(ancestors) if self.function else []
        if self.path_conditions:
            loc = self.e.loc(node)
            self.guard_sites[(self.function, loc['file'], loc['offset'])] = list(self.path_conditions)
        if k in {'VAR_DECL', 'PARM_DECL'}:
            self.storage_definition(self.key(node), node.type)
        if k == 'IF_STMT' and len(cs) in {2, 3} and self.function:
            truth = constant_condition(cs[0])
            discarded = cs[1] if truth is False else cs[2] if truth is True and len(cs) == 3 else None
            if discarded is not None and not has_entry_label(discarded):
                start, end = discarded.extent.start, discarded.extent.end
                # Macro expansion ranges can collapse onto the same token.
                # Never use such a range to discard neighboring live facts.
                if start.offset >= cs[0].extent.end.offset and end.offset > start.offset:
                    self.constant_regions.append(dict(self.e.loc(discarded), function_id=self.function,
                        offset=start.offset, end_offset=end.offset,
                        condition=self.e.loc(cs[0]), value=truth, proof='CONSTANT_DISCARDED_BRANCH'))
        if k == 'VAR_DECL' and cs:
            if self.function:
                self.cleanup_call(node)
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
            self.storage_definition(self.result(node)['id'], node.type)
            ref = node.referenced
            direct = ref is not None and ref.kind.name in FUNCTIONS
            arguments = list(node.get_arguments())
            pointee_layouts = [self.pointee_layout(arg) for arg in arguments]
            self.calls.append(dict(function_id=self.function, target=self.e.fid(ref) if direct else None,
                path_conditions=list(self.path_conditions),
                expression=self.value(cs[0]) if cs else dict(op='empty'), name=ref.spelling if direct else node.spelling,
                arguments=[self.value(arg) for arg in arguments], result=self.result(node),
                argument_values=[constant_value(arg) for arg in arguments],
                argument_pointee_paths=[layout[0] for layout in pointee_layouts],
                argument_pointee_sizes=[layout[1] for layout in pointee_layouts],
                argument_aggregates=[arg.type.get_canonical().kind.name == 'RECORD' for arg in arguments],
                argument_aggregate_paths=[self.aggregate_paths(arg.type)
                    if arg.type.get_canonical().kind.name == 'RECORD' else [] for arg in arguments],
                returns_pointer=node.type.get_canonical().kind.name in {'POINTER', 'LVALUEREFERENCE', 'RVALUEREFERENCE'},
                returns_aggregate=node.type.get_canonical().kind.name == 'RECORD',
                return_aggregate_paths=self.aggregate_paths(node.type)
                    if node.type.get_canonical().kind.name == 'RECORD' else [],
                source_text=self.e.source(node), **self.e.loc(node)))
        if 'ASM' in k and self.function:
            expressions = [child for child in cs if child.kind.is_expression()]
            branches = self.assembly_branches(node, expressions)
            self.calls.append(dict(function_id=self.function, target=None,
                expression=dict(op='unknown', id='asm:' + str(node.location.offset)), name='<inline assembly>',
                arguments=[self.value(expr) for index, expr in enumerate(expressions) if index not in branches],
                result=self.result(node), returns_pointer=False, inline_assembly=True,
                source_text=self.e.source(node), **self.e.loc(node)))
        def has_dereference(expression):
            return (expression.get('op') == 'deref'
                    or any(has_dereference(v) for v in expression.values() if isinstance(v, dict)))
        dynamic = (k in {'MEMBER_REF_EXPR', 'ARRAY_SUBSCRIPT_EXPR'}
                   or k == 'UNARY_OPERATOR' and operator(node) == '*')
        dynamic = (dynamic and node.type.get_canonical().kind.name not in {'FUNCTIONPROTO', 'FUNCTIONNOPROTO'}
                   and has_dereference(self.lvalue(node)))
        if dynamic and self.function:
            mode = self.mode(ancestors)
            if mode:
                self.accesses.append(dict(location=self.lvalue(node), mode=mode, function_id=self.function,
                    path_conditions=list(self.path_conditions),
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
        self.path_conditions = previous_conditions

    def run(self, cursor):
        for node in cursor.get_children():
            if node.kind.name == 'MACRO_INSTANTIATION' and node.spelling.startswith('atomic_'):
                loc = self.e.loc(node)
                self.atomic_macros[(loc['file'], loc['offset'])] = node.spelling
        self.visit(cursor)
        for row in self.e.accesses + self.e.calls + self.e.unknowns:
            owner = row.get('function_id', row.get('caller_function_id'))
            key = (owner, row.get('file'), row.get('offset'))
            if key in self.guard_sites:
                row['path_conditions'] = self.guard_sites[key]
        return dict(pointer_constraints=self.constraints, semantic_calls=self.calls, indirect_accesses=self.accesses,
                    pointer_storage=list(self.storage.values()), constant_regions=self.constant_regions)
