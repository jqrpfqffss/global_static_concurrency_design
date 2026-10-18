"""One libclang translation unit per worker process, with explicit uncertainty."""
import fnmatch
import ctypes
import os
import re
import sys
from itertools import islice
from pathlib import Path

from clang import cindex as ci

from .common import digest, read_json, relative, write_json


FUNCTIONS = {"FUNCTION_DECL", "CXX_METHOD", "CONSTRUCTOR", "DESTRUCTOR", "FUNCTION_TEMPLATE", "CONVERSION_FUNCTION"}
WRAPPERS = {"UNEXPOSED_EXPR", "PAREN_EXPR", "CSTYLE_CAST_EXPR", "CXX_STATIC_CAST_EXPR", "CXX_REINTERPRET_CAST_EXPR"}


def children(c):
    return list(c.get_children())


def declaration_section(cursor, section_macros=None):
    """Read a section attribute without version-specific pretty-print APIs.

    Attribute spelling is auxiliary metadata. A binding that cannot expose
    its tokens must never prevent extraction of the enclosing declaration.
    """
    try:
        for attribute in cursor.get_children():
            if not attribute.kind.name.endswith('_ATTR'):
                continue
            attribute_tokens = ' '.join(token.spelling for token in islice(attribute.get_tokens(), 128))
            match = re.search(r'\bsection\s*\(\s*"([^"\\]*)"\s*\)', attribute_tokens)
            if match:
                return match.group(1)
        spelling = ' '.join(token.spelling for token in islice(cursor.get_tokens(), 512)).split(' = ', 1)[0]
        match = re.search(r'\bsection\s*\(\s*"([^"\\]*)"\s*\)', spelling)
        if match:
            return match.group(1)
        for name, argument in (section_macros or {}).items():
            use = re.search(r'\b' + re.escape(name) + r'\s*\(([^)]*)\)', spelling)
            if not use:
                continue
            values = [value.strip() for value in use.group(1).split(',')]
            if argument < len(values) and re.fullmatch(r'"[^"\\]*"', values[argument]):
                return values[argument][1:-1]
    except Exception:
        # Attribute metadata is optional; an incompatible binding must not
        # abort the semantic AST/access extraction of this translation unit.
        pass
    return None


def walk(c):
    yield c
    for child in c.get_children():
        yield from walk(child)


def tokens(c, limit=None):
    stream = (token for token in c.get_tokens() if token.kind != ci.TokenKind.COMMENT)
    # Comments are never C expression tokens. libclang can include a comment
    # in a cursor's source range, and its Python binding decodes token text as
    # strict UTF-8 even when a valid target source uses a legacy byte there.
    return [token.spelling for token in (stream if limit is None else islice(stream, limit))]


def constant_value(cursor):
    """Ask Clang to evaluate macros/enum arithmetic, never Python eval."""
    lib = ci.conf.lib
    evaluate = lib.clang_Cursor_Evaluate
    evaluate.argtypes, evaluate.restype = [ci.Cursor], ctypes.c_void_p
    kind = lib.clang_EvalResult_getKind
    kind.argtypes, kind.restype = [ctypes.c_void_p], ctypes.c_int
    integer = lib.clang_EvalResult_getAsLongLong
    integer.argtypes, integer.restype = [ctypes.c_void_p], ctypes.c_longlong
    dispose = lib.clang_EvalResult_dispose
    dispose.argtypes, dispose.restype = [ctypes.c_void_p], None
    result = evaluate(cursor)
    if not result:
        return None
    try:
        return integer(result) if kind(result) == 1 else None
    finally:
        dispose(result)


def operator(c):
    # Read semantic operator kinds: macro expansion ranges do not reliably
    # provide the original operator token. These APIs exist in libclang 18+.
    if c.kind.name == "UNARY_OPERATOR":
        api = ci.conf.lib.clang_getCursorUnaryOperatorKind
        api.argtypes, api.restype = [ci.Cursor], ctypes.c_int
        return {1: "++", 2: "--", 3: "++", 4: "--", 5: "&", 6: "*", 7: "+", 8: "-", 9: "~", 10: "!"}.get(api(c), "")
    if c.kind.name in {"BINARY_OPERATOR", "COMPOUND_ASSIGNMENT_OPERATOR"}:
        api = ci.conf.lib.clang_getCursorBinaryOperatorKind
        api.argtypes, api.restype = [ci.Cursor], ctypes.c_int
        return {3: "*", 4: "/", 5: "%", 6: "+", 7: "-", 8: "<<", 9: ">>",
                11: "<", 12: ">", 13: "<=", 14: ">=", 15: "==", 16: "!=", 17: "&", 18: "^", 19: "|",
                20: "&&", 21: "||", 22: "=", 23: "*=", 24: "/=", 25: "%=", 26: "+=", 27: "-=",
                28: "<<=", 29: ">>=", 30: "&=", 31: "^=", 32: "|=", 33: ","}.get(api(c), "")
    return ""


def constant_condition(cursor):
    """Fold only side-effect-free integer expressions, never mutable objects."""
    cs = children(cursor)
    if len(cs) == 1 and (cursor.kind.name == 'PAREN_EXPR' or
            cursor.kind.name == 'UNEXPOSED_EXPR' and cursor.type.get_canonical() == cs[0].type.get_canonical()):
        return constant_condition(cs[0])
    operation = operator(cursor)
    if cursor.kind.name == 'BINARY_OPERATOR' and operation in {'&&', '||'} and len(cs) == 2:
        left, right = constant_condition(cs[0]), constant_condition(cs[1])
        if operation == '&&':
            return False if False in (left, right) else True if left is True and right is True else None
        return True if True in (left, right) else False if left is False and right is False else None
    if cursor.kind.name == 'UNARY_OPERATOR' and operation == '!' and len(cs) == 1:
        value = constant_condition(cs[0])
        return None if value is None else not value
    # Logical folding above establishes only the branch outcome. The CFG and
    # facts still retain evaluation of the condition, including side effects.
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


def has_entry_label(cursor):
    return any(child.kind.name in {'LABEL_STMT', 'CASE_STMT', 'DEFAULT_STMT'} for child in walk(cursor))


class Extractor:
    def __init__(self, request):
        self.root = Path(request["root"]).resolve()
        self.unit = request["unit"]
        self.cfg = request["config"]
        self.tu_name = self.unit["source_file"]
        self.variables, self.functions, self.symbols = {}, {}, {}
        self.accesses, self.calls, self.unknowns = [], [], []
        self.events, self.irq_priority_events, self.registrations, self.snapshots = [], [], [], []
        self.control_flow = []
        self.source_cache = {}
        self.relative_paths = {}
        self.local_counts = {}
        self.task_reference_sites = set()
        self.coverage_source = request.get("coverage_source", "compile_database")
        self.source_overrides = request.get("source_overrides", {})
        self.declaration_only = request.get("declaration_only", False)

    def loc(self, c):
        loc = c.location
        filename = loc.file.name if loc.file else None
        if filename is not None and filename not in self.relative_paths:
            self.relative_paths[filename] = relative(filename, self.root)
        return dict(file=self.relative_paths[filename] if filename is not None else self.tu_name,
                    line=loc.line, column=loc.column, offset=loc.offset)

    def source(self, c):
        loc = self.loc(c)
        p = self.root / loc["file"]
        if str(p) not in self.source_cache:
            try:
                self.source_cache[str(p)] = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                self.source_cache[str(p)] = []
        lines = self.source_cache[str(p)]
        return lines[loc["line"] - 1][:500] if 0 < loc["line"] <= len(lines) else ""

    def key(self, c):
        return c.get_usr() or f"{c.kind.name}:{self.loc(c)}:{c.spelling}"

    def fid(self, c):
        usr = c.get_usr() or c.spelling
        internal = c.linkage.name == "INTERNAL"
        return (f"tu::{self.tu_name}::" if internal else "") + usr

    def interesting(self, c):
        return bool(c.location.file)

    def issue(self, kind, c, function_id="", **extra):
        self.unknowns.append(dict(kind=kind, function_id=function_id, **self.loc(c),
                                  source_text=self.source(c), **extra))

    def declare(self, c, function=None):
        k = c.kind.name
        if k in FUNCTIONS:
            function = c
            if c.is_definition():
                attributes = [ch for ch in c.get_children() if ch.kind.name.endswith('_ATTR')]
                f = dict(function_id=self.fid(c), name=c.spelling, qualified_name=c.displayname,
                         linkage=c.linkage.name, is_static=c.linkage.name == "INTERNAL",
                         is_weak=bool(re.search(r'\b(?:__weak|weak)\b', self.source(c).split(c.spelling, 1)[0])) or any(ch.kind.name in {'WEAK_ATTR', 'WEAK_IMPORT_ATTR'}
                                     or (ch.kind.name.endswith('_ATTR') and tokens(ch, 1) == ['weak'])
                                     for ch in c.get_children()),
                         translation_unit=self.tu_name,
                         entry_attributes=[ch.kind.name for ch in attributes],
                         # Macro expansion can make an opaque attribute's
                         # token extent span a whole header. Its leading
                         # spelling identifies the attribute without copying
                         # thousands of unrelated macro tokens into every TU.
                         attribute_spellings=[' '.join(tokens(ch, 4)) for ch in attributes],
                         parameter_count=sum(1 for _ in c.get_arguments()),
                         return_type_kind=c.result_type.get_canonical().kind.name,
                         is_variadic=c.type.kind.name == 'FUNCTIONPROTO' and c.type.is_function_variadic(),
                         **self.loc(c), end_line=c.extent.end.line, end_offset=c.extent.end.offset)
                self.functions[f["function_id"]] = f
                if k != "FUNCTION_DECL":
                    self.issue("CPP_SEMANTICS_REVIEW", c, f["function_id"])
        if k == "VAR_DECL":
            # A block-scope extern is a global declaration too.
            local = function is not None and c.storage_class.name != "EXTERN"
            if not local or c.storage_class.name == "STATIC":
                key = self.key(c)
                if key not in self.symbols:
                    if local:
                        name_key = (self.fid(function), c.spelling)
                        ordinal = self.local_counts.get(name_key, 0)
                        self.local_counts[name_key] = ordinal + 1
                        sid = f"local::{name_key[0]}::{c.spelling}::{ordinal}"
                        kind = "LOCAL_STATIC"
                    else:
                        sid = self.fid(c)
                        kind = "FILE_STATIC" if c.linkage.name == "INTERNAL" else "GLOBAL"
                    self.symbols[key] = sid
                sid = self.symbols[key]
                typ = c.type.get_canonical()
                decl = self.loc(c)
                weak_decl = any(ch.kind.name in {'WEAK_ATTR', 'WEAK_IMPORT_ATTR'}
                                or (ch.kind.name.endswith('_ATTR') and 'weak' in tokens(ch, 4))
                                for ch in c.get_children())
                defining = c.is_definition() or (c.storage_class.name != "EXTERN" and (
                    local and c.storage_class.name == "STATIC" or
                    not local and c.semantic_parent.kind.name == "TRANSLATION_UNIT"
                    and Path(self.unit["source"]).suffix.lower() == ".c"))
                record = self.variables.get(sid)
                if record is None:
                    size, align = typ.get_size(), typ.get_align()
                    is_array = "ARRAY" in typ.kind.name
                    type_decl = typ.get_declaration()
                    bitfield = any(ch.kind.name == "FIELD_DECL" and ch.is_bitfield() for ch in type_decl.get_children())
                    record = dict(symbol_id=sid, name=c.spelling, qualified_name=(function.spelling + "::" if local else "") + c.spelling,
                                  kind="LOCAL_STATIC" if local else ("FILE_STATIC" if c.linkage.name == "INTERNAL" else "GLOBAL"),
                                  scope="function" if local else "file", storage_class=c.storage_class.name,
                                  linkage=c.linkage.name, type=c.type.spelling, size_bytes=size if size >= 0 else None,
                                  alignment_bytes=align if align >= 0 else None,
                                  is_const=typ.is_const_qualified() or (is_array and typ.element_type.is_const_qualified()),
                                  is_volatile=typ.is_volatile_qualified(), is_array=is_array,
                                  is_atomic=typ.kind.name == 'ATOMIC',
                                  array_size=typ.element_count if typ.kind.name == 'CONSTANTARRAY' else None,
                                  owner_function_id=self.fid(function) if local else None,
                                  is_pointer=typ.kind.name in {"POINTER", "LVALUEREFERENCE", "RVALUEREFERENCE"},
                                  is_struct=typ.kind.name == "RECORD", is_bitfield_container=bitfield,
                                  is_union=type_decl.kind.name == 'UNION_DECL',
                                  is_weak=weak_decl,
                                  declarations=[], definitions=[], translation_units=[self.tu_name],
                                  definition_file=None, definition_line=None, initializer=" ".join(tokens(c))[:500],
                                  coverage_source=self.coverage_source)
                    if record['is_struct']:
                        # The inventory owns storage at the root symbol, while
                        # concurrency evidence must be attached to the concrete
                        # field which is read or written.  Keep the declared
                        # field layout here so analysis can also represent a
                        # field affected only by a whole-object operation.
                        record['member_definitions'] = self.record_members(typ)
                    if is_array:
                        element = typ.element_type.get_canonical()
                        record.update(array_element_type=element.spelling,
                                      array_element_size_bytes=max(0, element.get_size()),
                                      array_element_alignment_bytes=max(0, element.get_align()),
                                      array_element_is_const=element.is_const_qualified(),
                                      array_element_is_volatile=element.is_volatile_qualified(),
                                      array_element_is_atomic=element.kind.name == 'ATOMIC',
                                      array_element_is_struct=element.kind.name == 'RECORD',
                                      array_element_is_union=element.get_declaration().kind.name == 'UNION_DECL')
                        if element.kind.name == 'RECORD':
                            record['member_definitions'] = self.record_members(element)
                    self.variables[sid] = record
                else:
                    record['is_weak'] = record.get('is_weak', False) or weak_decl
                if defining:
                    size, align = typ.get_size(), typ.get_align()
                    record.update(type=c.type.spelling, initializer=' '.join(tokens(c))[:500],
                                  size_bytes=size if size >= 0 else None,
                                  alignment_bytes=align if align >= 0 else None)
                    if 'ARRAY' in typ.kind.name:
                        record['array_size'] = typ.element_count if typ.kind.name == 'CONSTANTARRAY' else None
                    if any(attr.kind.name.endswith('_ATTR') for attr in c.get_children()):
                        section = declaration_section(c, self.section_macros)
                        if section:
                            record['linker_section'] = section
                if decl not in record["declarations"]:
                    record["declarations"].append(decl)
                if defining and decl not in record["definitions"]:
                    record["definitions"].append(decl)
                    record["definition_file"], record["definition_line"] = decl["file"], decl["line"]
            # Ordinary automatic locals are per-invocation storage, not shared
            # objects; they are intentionally not inventoried. Parameters and
            # struct/union fields are likewise excluded. Child traversal below
            # still descends into every declaration scope.
        for child in c.get_children():
            # Include project and actually included vendor headers; no name-based filtering.
            if self.interesting(child):
                self.declare(child, function)

    def record_members(self, typ, prefix='', seen=(), base_offset_bits=0, union_groups=()):
        """Return declared field paths for a record, including nested records.

        A record field which is itself a record is retained as a container and
        its children are retained as concrete analysis targets.  The ``seen``
        guard makes self-referential declarations finite; pointer fields are
        leaves because their pointee is not inline storage.
        """
        canonical = typ.get_canonical()
        declaration = canonical.get_declaration()
        key = declaration.get_usr() or declaration.hash
        if canonical.kind.name != 'RECORD' or key in seen:
            return []
        if declaration.kind.name == 'UNION_DECL':
            union_groups = (*union_groups, prefix.rstrip('.') or '$root')
        rows = []
        for field in declaration.get_children():
            if field.kind.name != 'FIELD_DECL':
                continue
            field_type = field.type.get_canonical()
            path = prefix + field.spelling
            size, align = field_type.get_size(), field_type.get_align()
            is_record = field_type.kind.name == 'RECORD'
            offset_bits = field.get_field_offsetof()
            absolute_offset = base_offset_bits + offset_bits if offset_bits >= 0 and base_offset_bits is not None else None
            is_array = 'ARRAY' in field_type.kind.name
            rows.append(dict(field_path=path, name=field.spelling, type=field.type.spelling,
                             size_bytes=size if size >= 0 else None,
                             alignment_bytes=align if align >= 0 else None,
                             is_struct=is_record,
                             is_union=field_type.get_declaration().kind.name == 'UNION_DECL',
                             is_array=is_array,
                             array_size=field_type.element_count if field_type.kind.name == 'CONSTANTARRAY' else None,
                             offset_bits=absolute_offset,
                             bit_width=field.get_bitfield_width() if field.is_bitfield() else None,
                             union_groups=list(union_groups),
                             is_const=field_type.is_const_qualified(),
                             is_volatile=field_type.is_volatile_qualified(),
                             is_atomic=field_type.kind.name == 'ATOMIC',
                             is_bitfield=field.is_bitfield()))
            if is_record:
                rows.extend(self.record_members(field_type, path + '.', (*seen, key), absolute_offset, union_groups))
            if is_array:
                element = field_type.element_type.get_canonical()
                rows[-1].update(array_element_type=element.spelling,
                                array_element_size_bytes=max(0, element.get_size()),
                                array_element_is_struct=element.kind.name == 'RECORD')
                if element.kind.name == 'RECORD':
                    rows.extend(self.record_members(element, path + '[*].', (*seen, key), absolute_offset, union_groups))
        return rows

    def refs(self, c):
        result = []
        for n in walk(c):
            if n.kind.name == "DECL_REF_EXPR" and n.referenced:
                sid = self.symbols.get(self.key(n.referenced))
                if sid:
                    result.append((sid, n))
        return result

    def reference_paths(self, c):
        """Return root-symbol/member-path pairs below ``c``.

        ``refs`` intentionally remains a small helper for alias discovery.
        Assignment classification, however, has to distinguish
        ``cfg.limit`` from ``cfg.period`` even though they share the same root
        declaration.  This walker is deliberately local to the expression so
        an outer assignment cannot change the read nature of a RHS reference.
        """
        result = []

        def visit(node, ancestors):
            if node.kind.name == 'DECL_REF_EXPR' and node.referenced:
                sid = self.symbols.get(self.key(node.referenced))
                if sid:
                    _, path = self.access_mode(node, ancestors,
                                                self.variables[sid]['is_pointer'])
                    result.append((sid, path))
            for index, child in enumerate(node.get_children()):
                visit(child, ancestors + [(node, index)])

        visit(c, [])
        return result

    def access_mode(self, ref, ancestors, pointer=False, pointee=False):
        mode, path = "READ", []
        decay = False
        for parent, index in reversed(ancestors):
            k = parent.kind.name
            if k in WRAPPERS:
                wrapped = children(parent)
                child_type = (wrapped[index].type.get_canonical().kind.name
                              if 0 <= index < len(wrapped) else '')
                if (parent.type.get_canonical().kind.name == "POINTER"
                        and "ARRAY" in child_type):
                    decay = True
                continue
            if k == "MEMBER_REF_EXPR":
                # A direct reference to a pointer variable is an access to the
                # pointer object, not proof of an access to its pointee.  When
                # processing a resolved alias we deliberately pass
                # ``pointer=False`` so both ``.`` and ``->`` preserve the
                # pointee's concrete member path.
                if pointer:
                    return "READ", ".".join(path)
                path.append(parent.spelling)
                pointer = parent.type.get_canonical().kind.name == 'POINTER'
                continue
            if k == "ARRAY_SUBSCRIPT_EXPR":
                if index != 0 or pointer:
                    return "READ", ".".join(path)
                decay = False  # The decayed base is consumed by an element access.
                indices = children(parent)
                value = constant_value(indices[1]) if len(indices) > 1 else None
                path.append('[' + (str(value) if value is not None else '*') + ']')
                pointer = parent.type.get_canonical().kind.name == 'POINTER'
                continue
            if k == "UNARY_OPERATOR":
                op = operator(parent)
                if op == "*" and pointee:
                    # For a resolved local alias, this star selects the
                    # pointee; the write/read operator is one level above.
                    continue
                if op in {"++", "--"}:
                    mode = "RMW"
                elif op == "&":
                    mode = "ADDRESS_TAKEN"
                else:
                    mode = "READ"
                break
            if k in {"BINARY_OPERATOR", "COMPOUND_ASSIGNMENT_OPERATOR"}:
                op = operator(parent)
                if index == 0 and op in {"=", "+=", "-=", "*=", "/=", "%=", "|=", "&=", "^=", "<<=", ">>="}:
                    mode = "WRITE" if op == "=" else "RMW"
                    # RMW is a property of one canonical access path, not of a
                    # storage root.  ``config.limit = config.period * 2`` is a
                    # WRITE of limit plus a READ of period; only an RHS read of
                    # the exact same member can make this left side RMW.
                    if op == "=" and any(s == self.symbols.get(self.key(ref.referenced)) and rhs_path == ".".join(path)
                                           for s, rhs_path in self.reference_paths(children(parent)[1])):
                        mode = "RMW"
                break
            if k == "CALL_EXPR":
                if not path and self.variables.get(self.symbols.get(self.key(ref.referenced)), {}).get("is_array"):
                    mode = "ADDRESS_TAKEN"
                break
            if k in {"CXX_UNARY_EXPR", "UNARY_EXPR"} and tokens(parent)[:1] in (["sizeof"], ["alignof"], ["_Alignof"]):
                return None, ""
            break
        if mode == "READ" and decay:
            mode = "ADDRESS_TAKEN"
        return mode, ".".join(path)

    def add_access(self, sid, c, fid, mode, **extra):
        if mode is None:
            return
        self.accesses.append(dict(symbol_id=sid, function_id=fid, access_kind=mode,
                                  **self.loc(c), source_text=self.source(c), parse_confidence="exact", **extra))

    def protection_event(self, name, fid, cursor, ancestors=()):
        """Record the *kind* of a synchronization API without claiming it works.

        CMSIS names are facts even when a project did not populate legacy
        ``api_patterns``.  Project wrappers require an explicit
        ``critical_sections`` declaration; a lock-looking name is never enough.
        """
        conditional = any(parent.kind.name in {'IF_STMT', 'SWITCH_STMT', 'FOR_STMT', 'WHILE_STMT',
                                               'DO_STMT', 'CONDITIONAL_OPERATOR'} for parent, _ in ancestors)
        common = dict(conditional_ancestor=conditional,
                      arguments=[' '.join(tokens(arg)) for arg in cursor.get_arguments()])
        builtin = {
            '__disable_irq': ('lock_enter', 'primask'),
            '__enable_irq': ('lock_exit', 'primask'),
            '__get_PRIMASK': ('primask_get', 'primask'),
            '__set_PRIMASK': ('primask_set', 'primask'),
            '__get_BASEPRI': ('basepri_get', 'basepri'),
            '__set_BASEPRI': ('basepri_set', 'basepri'),
            '__set_BASEPRI_MAX': ('basepri_set', 'basepri'),
            '__disable_fault_irq': ('lock_enter', 'faultmask'),
            '__enable_fault_irq': ('lock_exit', 'faultmask'),
            '__DMB': ('barrier', 'barrier'),
            '__DSB': ('barrier', 'barrier'),
            '__ISB': ('barrier', 'barrier'),
        }.get(name)
        if builtin:
            event_kind, protection_type = builtin
            self.events.append(dict(function_id=fid, event_kind=event_kind, api_name=name,
                                    protection_type=protection_type, configured=False, **common, **self.loc(cursor)))
            return
        for section in self.cfg.get('critical_sections', []):
            if name == section.get('enter'):
                self.events.append(dict(function_id=fid, event_kind='lock_enter', api_name=name,
                                        protection_type=section['type'], configured=True, **common, **self.loc(cursor)))
                return
            if name == section.get('exit'):
                self.events.append(dict(function_id=fid, event_kind='lock_exit', api_name=name,
                                        protection_type=section['type'], configured=True, **common, **self.loc(cursor)))
                return
            if name == section.get('save'):
                self.events.append(dict(function_id=fid, event_kind='lock_enter', api_name=name,
                                        protection_type=section['type'], save_restore=True,
                                        configured=True, **common, **self.loc(cursor)))
                return
            if name == section.get('restore'):
                self.events.append(dict(function_id=fid, event_kind='lock_exit', api_name=name,
                                        protection_type=section['type'], save_restore=True,
                                        configured=True, **common, **self.loc(cursor)))
                return
        for event_kind, pats in self.cfg.get("api_patterns", {}).items():
            if any(fnmatch.fnmatchcase(name or "", p) for p in pats):
                self.events.append(dict(function_id=fid, event_kind=event_kind, api_name=name,
                                        protection_type='configured_api', configured=False, **common, **self.loc(cursor)))
                return

    def function_body(self, fn):
        fid = self.fid(fn)
        snapshots = {}
        all_nodes = list(walk(fn))
        # A deliberately small value-flow model: unchanged scalar parameters
        # may be forwarded to another call or stored. Never infer this from
        # the callee's name, nor from a write unrelated to its argument.
        parameters = {self.key(p): i for i, p in enumerate(fn.get_arguments())
                      if p.type.get_canonical().kind.name in {'BOOL', 'CHAR_U', 'UCHAR', 'CHAR_S',
                          'SCHAR', 'USHORT', 'SHORT', 'UINT', 'INT', 'ULONG', 'LONG',
                          'ULONGLONG', 'LONGLONG', 'ENUM', 'FLOAT', 'DOUBLE'}}
        for node in all_nodes:
            operands = children(node)
            if node.kind.name in {'BINARY_OPERATOR', 'COMPOUND_ASSIGNMENT_OPERATOR'} and operator(node) in {
                    '=', '+=', '-=', '*=', '/=', '%=', '|=', '&=', '^=', '<<=', '>>='}:
                changed = operands[:1]
            elif node.kind.name == 'UNARY_OPERATOR' and operator(node) in {'++', '--', '&'}:
                changed = operands
            else:
                continue
            for operand in changed:
                for ref in walk(operand):
                    if ref.kind.name == 'DECL_REF_EXPR' and ref.referenced:
                        parameters.pop(self.key(ref.referenced), None)

        def value_source(node):
            while node.kind.name in WRAPPERS and len(children(node)) == 1:
                node = children(node)[0]
            if node.kind.name == 'DECL_REF_EXPR' and node.referenced:
                index = parameters.get(self.key(node.referenced))
                if index is not None:
                    return dict(parameter_index=index)
            if (node.kind.name not in {'DECL_REF_EXPR', 'MEMBER_REF_EXPR', 'ARRAY_SUBSCRIPT_EXPR'}
                    or node.type.get_canonical().kind.name in {'POINTER', 'RECORD', 'INCOMPLETEARRAY', 'CONSTANTARRAY'}
                    or '->' in tokens(node)):
                return None
            refs = self.refs(node)
            if len(refs) == 1:
                return dict(read_site=self.loc(refs[0][1]))
            return None
        # Snapshot facts describe value copies used later in a writeback or
        # decision. Pointer aliases are deliberately excluded here: the
        # PointerExtractor/Solver is the single source of indirect accesses,
        # with exact subobject and pointer-slot load semantics. The former
        # flow-insensitive alias union confused pointer containers with their
        # pointees and manufactured whole-object writes.
        for n in all_nodes:
            cs = children(n)
            local = rhs = None
            if n.kind.name == "VAR_DECL" and n.storage_class.name != "STATIC" and cs:
                local, rhs = n, cs[-1]
            elif n.kind.name == "BINARY_OPERATOR" and operator(n) == "=" and len(cs) == 2:
                left = [x.referenced for x in walk(cs[0])
                        if x.kind.name == "DECL_REF_EXPR" and x.referenced]
                if len(left) == 1 and left[0].kind.name == "VAR_DECL" and self.key(left[0]) not in self.symbols:
                    local, rhs = left[0], cs[1]
            if (local is None or local.type.get_canonical().kind.name in
                    {"POINTER", "LVALUEREFERENCE", "RVALUEREFERENCE"}):
                continue
            direct = {s for s, _ in self.refs(rhs) if not self.variables[s]['is_pointer']}
            if direct:
                snapshots.setdefault(self.key(local), set()).update(direct)

        def visit(c, ancestors):
            k = c.kind.name
            if c != fn and k in FUNCTIONS:
                return
            if k == 'BINARY_OPERATOR' and operator(c) == '=':
                operands = children(c)
                if len(operands) == 2:
                    destination, source = operands
                    peripheral_addresses = sorted({value for node in walk(destination)
                        if node.kind.name == 'INTEGER_LITERAL'
                        for value in [constant_value(node)]
                        if value is not None and 0x40000000 <= value <= 0x5fffffff})
                    if peripheral_addresses:
                        def published(node, parents):
                            if node.kind.name == 'DECL_REF_EXPR' and node.referenced:
                                sid = self.symbols.get(self.key(node.referenced))
                                if sid:
                                    mode, path = self.access_mode(
                                        node, parents, self.variables[sid]['is_pointer'])
                                    if mode == 'ADDRESS_TAKEN':
                                        self.issue('UNRESOLVED_DMA_BUFFER', c, fid,
                                            symbol_id=sid, access_path=path,
                                            mmio_address=peripheral_addresses[0],
                                            reason='Object address published to a peripheral register; hardware access direction and lifetime are unresolved')
                            for index, child in enumerate(node.get_children()):
                                published(child, parents + [(node, index)])
                        published(source, [])
            if k == "CALL_EXPR":
                ref = c.referenced
                direct = ref is not None and ref.kind.name in FUNCTIONS
                callee = self.fid(ref) if direct else None
                name = ref.spelling if direct else c.spelling
                self.calls.append(dict(caller_function_id=fid, callee_function_id=callee,
                                       callee_name=name, call_kind="DIRECT" if direct else "INDIRECT", **self.loc(c)))
                if not direct:
                    self.issue("INDIRECT_CALL", c, fid)
                args = list(c.get_arguments())
                values = [dict(argument_index=i, **source) for i, arg in enumerate(args)
                          if (source := value_source(arg)) is not None]
                if direct and values:
                    self.calls[-1]['value_arguments'] = values
                task_arg = {"xTaskCreate": 0, "xTaskCreateStatic": 0, "osThreadNew": 0,
                            "xTaskCreatePinnedToCore": 0}.get(name)
                if task_arg is not None and args:
                    targets = [x for x in walk(args[task_arg]) if x.kind.name == "DECL_REF_EXPR"
                               and x.referenced and x.referenced.kind.name in FUNCTIONS]
                    for reference in targets:
                        target = reference.referenced
                        self.task_reference_sites.add((self.loc(reference)["file"], reference.location.offset, self.fid(target)))
                        self.registrations.append(dict(function_id=self.fid(target), kind="TASK", api=name,
                                                       registered_by=fid,
                                                       may_repeat=fn.spelling != "main" or any(p.kind.name in {"FOR_STMT", "WHILE_STMT", "DO_STMT"} for p, _ in ancestors),
                                                       **self.loc(c)))
                    if not targets:
                        self.issue("UNRESOLVED_TASK_ENTRY", c, fid, api=name)
                if name == "osThreadCreate":
                    self.issue("CMSIS_V1_TASK_ENTRY", c, fid, hint="配置 osThreadDef 中的真实入口")
                self.protection_event(name, fid, c, ancestors)
                # NVIC configuration is a direct source fact, not a guessed
                # property of an IRQHandler name.  Preserve raw argument
                # tokens so analysis can use literal, reproducible cases and
                # report all other cases as unresolved.
                from .async_semantics import is_async_enable, canonical_cmsis_api
                api_name = canonical_cmsis_api(name)
                if is_async_enable(api_name, self.cfg) or api_name in {'HAL_NVIC_SetPriority', 'NVIC_SetPriority', 'HAL_NVIC_SetPriorityGrouping',
                            'NVIC_SetPriorityGrouping', 'NVIC_EnableIRQ', 'HAL_NVIC_EnableIRQ',
                            'NVIC_DisableIRQ', 'HAL_NVIC_DisableIRQ', 'SysTick_Config',
                            'HAL_SYSTICK_Config'}:
                    self.irq_priority_events.append(dict(function_id=fid, api_name=api_name,
                        raw_api_name=name,
                        arguments=[' '.join(tokens(arg)) for arg in args],
                        argument_values=[constant_value(arg) for arg in args],
                        conditional_ancestor=any(p.kind.name in {'IF_STMT','WHILE_STMT','FOR_STMT','SWITCH_STMT','DO_STMT','CONDITIONAL_OPERATOR'}
                            or (p.kind.name=='BINARY_OPERATOR' and operator(p) in {'&&','||'}) for p, _ in ancestors),
                        **self.loc(c)))
                # Explicit library argument semantics, with address escape retained separately.
                from .common import libc_pointer_modes
                semantics = libc_pointer_modes(name, len(args))
                for i, arg in enumerate(args):
                    found = {s for s, _ in self.refs(arg)}
                    paths_by_symbol = {}
                    for target_sid, target_path in self.reference_paths(arg):
                        paths_by_symbol.setdefault(target_sid, set()).add(target_path)
                    if i in semantics:
                        for sid in found:
                            # A pointer object is read; its pointee remains an alias uncertainty.
                            if not self.variables[sid]["is_pointer"]:
                                # Library APIs inherit the exact field path in
                                # their argument.  Only ``&config`` is a
                                # WHOLE_OBJECT_ACCESS; ``&config.period`` must
                                # remain a write/read of that one member.
                                for target_path in paths_by_symbol.get(sid, {''}):
                                    self.add_access(sid, arg, fid, semantics[i], access_path=target_path,
                                                    via_api=name, parse_confidence_override="conservative")
            if k == "DECL_REF_EXPR" and c.referenced:
                key = self.key(c.referenced)
                sid = self.symbols.get(key)
                if sid:
                    mode, path = self.access_mode(c, ancestors, self.variables[sid]["is_pointer"])
                    value_flow = {}
                    if mode == 'WRITE':
                        for parent, index in reversed(ancestors):
                            if parent.kind.name == 'BINARY_OPERATOR' and operator(parent) == '=' and index == 0:
                                source = value_source(children(parent)[1])
                                if source and 'parameter_index' in source:
                                    value_flow['writeback_parameter_index'] = source['parameter_index']
                                break
                            if parent.kind.name not in WRAPPERS | {'MEMBER_REF_EXPR', 'ARRAY_SUBSCRIPT_EXPR'}:
                                break
                    self.add_access(sid, c, fid, mode, access_path=path,
                                    **value_flow,
                                    conditional_ancestor=any(parent.kind.name in {'IF_STMT', 'SWITCH_STMT', 'FOR_STMT',
                                                                                   'WHILE_STMT', 'DO_STMT', 'CONDITIONAL_OPERATOR'}
                                                               for parent, _ in ancestors))
                    # Taking an address is not itself an escape. The pointer
                    # solver follows this value to actual opaque consumers.
                elif key in snapshots:
                    for original in snapshots[key]:
                        self.snapshots.append(dict(symbol_id=original, function_id=fid, local_name=c.spelling,
                                                   **self.loc(c), source_text=self.source(c), confidence="conservative"))
            if (k == "UNARY_OPERATOR" and operator(c) == "*") or (k == "MEMBER_REF_EXPR" and "->" in tokens(c)):
                self.issue("POINTER_DEREFERENCE", c, fid)
            if k == "ARRAY_SUBSCRIPT_EXPR":
                cs = children(c)
                if cs and not any(self.variables[s]["is_array"] for s, _ in self.refs(cs[0])):
                    self.issue("POINTER_SUBSCRIPT", c, fid)
            if "ASM" in k:
                self.issue("INLINE_ASSEMBLY", c, fid)
                explicit = {sid for sid, _ in self.refs(c)}
                literals = ' '.join(token for token in tokens(c) if token.startswith('"'))
                identifiers = set(re.findall(r'\b[A-Za-z_]\w*\b', literals))
                explicit.update(sid for sid, variable in self.variables.items()
                                if variable['name'] in identifiers)
                for sid in sorted(explicit):
                    self.issue('INLINE_ASSEMBLY', c, fid, symbol_id=sid,
                               reason='Inline assembly explicitly references this storage or operand')
                for target, function in self.functions.items():
                    if function['name'] in identifiers:
                        self.issue('ASSEMBLY_FUNCTION_REFERENCE', c, fid, target_function_id=target,
                                   reason='Inline assembly explicitly names this function')
            for i, ch in enumerate(c.get_children()):
                visit(ch, ancestors + [(c, i)])
        visit(fn, [])
        from .controlflow import build_cfg
        self.control_flow.append(build_cfg(self, fn))

    def run(self):
        os.chdir(self.unit["directory"])
        if self.cfg["analysis"].get("libclang_file"):
            ci.Config.set_library_file(self.cfg["analysis"]["libclang_file"])
        index = ci.Index.create()
        unsaved = [(path, content) for path, content in self.source_overrides.items()]
        # GCC accepts some legacy function-pointer assignments that recent
        # Clang treats as errors by default. Keep the diagnostic as a warning
        # so its AST and pointer flow remain available for conservative audit.
        clang_args = [*self.unit["arguments"], '-Wno-error=incompatible-function-pointer-types']
        tu = index.parse(self.unit["source"], args=clang_args,
                         unsaved_files=unsaved,
                         options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        diagnostics = [dict(severity=d.severity, message=str(d),
                            file=(relative(d.location.file.name, self.root)
                                  if d.location.file else None),
                            line=d.location.line, column=d.location.column)
                       for d in tu.diagnostics]
        self.section_macros = {}
        for macro in tu.cursor.get_children():
            if macro.kind.name != 'MACRO_DEFINITION':
                continue
            try:
                spelling = [token.spelling for token in islice(macro.get_tokens(), 128)]
            except Exception:
                continue
            if 'section' not in spelling or len(spelling) < 5 or spelling[1] != '(':
                continue
            closing = spelling.index(')') if ')' in spelling else 0
            parameters = [value for value in spelling[2:closing] if value != ',']
            match = re.search(r'\bsection\s*\(\s*([A-Za-z_]\w*)\s*\)', ' '.join(spelling))
            if match and match.group(1) in parameters:
                self.section_macros[macro.spelling] = parameters.index(match.group(1))
        self.declare(tu.cursor)
        # A Clang error can coexist with a traversable AST. Its affected
        # declarations/calls remain explicit evidence gaps; it is not a
        # translation-unit-wide PARSE_FAILED taint.
        parse_status = ("FAILED" if any(d['severity'] >= 4 for d in diagnostics) else
                        "PARTIAL" if any(d["severity"] >= 3 for d in diagnostics) else "PARSED")
        for v in self.variables.values():
            v["parse_status"] = parse_status
        if self.declaration_only:
            return dict(variables=list(self.variables.values()), parse_status=parse_status,
                        diagnostics=diagnostics,
                        includes=sorted({str(Path(i.include.name).resolve()) for i in tu.get_includes()}))
        def bodies(c):
            if c.kind.name in FUNCTIONS and c.is_definition():
                self.function_body(c)
                return
            for ch in c.get_children():
                if self.interesting(ch):
                    bodies(ch)
        bodies(tu.cursor)
        # A recoverable parser error may leave only one function's body
        # incomplete. Attach its coverage gap to variables actually named in
        # that source region, never to every variable of the translation unit.
        for diagnostic in diagnostics:
            if diagnostic['severity'] < 3 or not diagnostic.get('file'):
                continue
            owners = [function for function in self.functions.values()
                      if function.get('file') == diagnostic['file']
                      and function.get('line', 0) <= diagnostic['line'] <= function.get('end_line', -1)]
            missing_header = ('file not found' in diagnostic['message']
                              or 'No such file' in diagnostic['message'])
            if not owners and not missing_header:
                continue
            owner = (min(owners, key=lambda row: row['end_line'] - row['line'])
                     if owners else None)
            source_path = self.root / diagnostic['file']
            try:
                lines = source_path.read_text(encoding='utf-8', errors='replace').splitlines()
                body = ('\n'.join(lines[owner['line'] - 1:owner['end_line']])
                        if owner else '\n'.join(lines))
            except OSError:
                continue
            for symbol_id, variable in self.variables.items():
                if (variable.get('linkage') == 'EXTERNAL'
                        or diagnostic['file'] in variable.get('translation_units', ())):
                    if re.search(r'\b' + re.escape(variable['name']) + r'\b', body):
                        self.unknowns.append(dict(kind='PARTIAL_PARSE_REGION', symbol_id=symbol_id,
                            function_id=owner['function_id'] if owner else '', file=diagnostic['file'],
                            line=diagnostic['line'], diagnostic=diagnostic['message'],
                            relation=('variable_identifier_in_partial_function' if owner else
                                      'variable_identifier_in_partially_preprocessed_tu')))
        # Static-duration initializer address references are not function bodies,
        # but can expose a variable through global pointers and callback tables.
        def initializers(c, in_function=False):
            in_function = in_function or c.kind.name in FUNCTIONS
            if not in_function and c.kind.name == "VAR_DECL":
                for sid, ref in self.refs(c):
                    self.add_access(sid, ref, "", "ADDRESS_TAKEN", access_path="static_initializer")
                    self.issue("STATIC_INITIALIZER_REFERENCE", ref, symbol_id=sid)
            for ch in c.get_children():
                if self.interesting(ch):
                    initializers(ch, in_function)
        initializers(tu.cursor)
        # FreeRTOS/CMSIS critical APIs are often macros whose expanded call
        # has a different name. Keep the invocation itself as unverified evidence.
        for c in tu.cursor.get_children():
            if c.kind.name != "MACRO_INSTANTIATION":
                continue
            loc = self.loc(c)
            owners = [f for f in self.functions.values() if f["file"] == loc["file"]
                      and f["offset"] <= loc["offset"] <= f["end_offset"]]
            for event_kind, patterns in self.cfg.get("api_patterns", {}).items():
                if any(fnmatch.fnmatchcase(c.spelling, pattern) for pattern in patterns):
                    for f in owners:
                        self.events.append(dict(function_id=f["function_id"], event_kind=event_kind,
                                                api_name=c.spelling, macro=True, **loc))
        macro_definitions = {c.spelling: tokens(c)[1:] for c in tu.cursor.get_children()
                             if c.kind.name == 'MACRO_DEFINITION'}

        def macro_integer(name, seen=(), definition=None):
            if name in seen:
                return None
            values = [value for value in (macro_definitions.get(name, []) if definition is None else definition)
                      if value not in {'(', ')'}]
            if len(values) != 1:
                return None
            token = values[0]
            if re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*', token):
                digits = re.sub(r'[uUlL]+$', '', token)
                try:
                    return int(digits, 16 if digits.lower().startswith('0x') else 8 if len(digits) > 1 and digits.startswith('0') else 10)
                except ValueError:
                    return None
            return macro_integer(token, (*seen, name))

        # This CMSIS device-header constant describes the selected MCU. It is
        # extracted per actual translation unit, so analysis can reject
        # conflicting device headers instead of guessing a global default.
        for c in tu.cursor.get_children():
            if c.kind.name == 'MACRO_DEFINITION' and c.spelling == '__NVIC_PRIO_BITS':
                raw = tokens(c)[1:]
                value = macro_integer(c.spelling, definition=raw)
                self.irq_priority_events.append(dict(function_id='', api_name='CMSIS_NVIC_PRIO_BITS',
                    arguments=[' '.join(raw)], argument_values=[value],
                    translation_unit=self.tu_name, conditional_ancestor=False, **self.loc(c)))
        # Function addresses outside call expressions can hide callbacks and vectors.
        direct_sites = {(call["file"], call["offset"], call["callee_function_id"]) for call in self.calls}
        for c in walk(tu.cursor):
            if c.kind.name == "DECL_REF_EXPR" and c.referenced and c.referenced.kind.name in FUNCTIONS:
                # Direct call sites were recorded at the function-name location.
                if (self.loc(c)["file"], c.location.offset, self.fid(c.referenced)) not in direct_sites:
                    # Still retain registrations as facts; automatic root discovery
                    # resolves this particular function-address use.
                    if (self.loc(c)["file"], c.location.offset, self.fid(c.referenced)) in self.task_reference_sites:
                        continue
                    loc = self.loc(c)
                    owner = next((f['function_id'] for f in self.functions.values()
                                  if f['file'] == loc['file'] and f['offset'] <= loc['offset'] <= f['end_offset']), '')
                    self.issue("FUNCTION_ADDRESS", c, owner, target_function_id=self.fid(c.referenced))
        includes = sorted({str(Path(i.include.name).resolve()) for i in tu.get_includes()})
        for a in self.accesses:
            a["parse_confidence"] = a.pop("parse_confidence_override", a["parse_confidence"])
            a["access_id"] = "A-" + digest([self.tu_name, a])[:20]
        from .pointer_extract import PointerExtractor
        pointer_facts = PointerExtractor(self).run(tu.cursor)
        return dict(variables=list(self.variables.values()), functions=list(self.functions.values()),
                    accesses=self.accesses, calls=self.calls, unknowns=self.unknowns,
                    protection_events=self.events, irq_priority_events=self.irq_priority_events,
                    control_flow=self.control_flow,
                    registrations=self.registrations, snapshots=self.snapshots,
                    diagnostics=diagnostics, includes=includes, **pointer_facts,
                    parse_status=parse_status)


def main():
    request = read_json(sys.argv[1])
    try:
        result = Extractor(request).run()
    except Exception as exc:
        result = dict(parse_status="FAILED", diagnostics=[dict(severity=4, message=f"{type(exc).__name__}: {exc}")])
    write_json(sys.argv[2], result)


if __name__ == "__main__":
    main()
