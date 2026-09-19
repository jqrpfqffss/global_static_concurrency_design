"""One libclang translation unit per worker process, with explicit uncertainty."""
import fnmatch
import ctypes
import os
import sys
from pathlib import Path

from clang import cindex as ci

from .common import digest, read_json, relative, write_json


FUNCTIONS = {"FUNCTION_DECL", "CXX_METHOD", "CONSTRUCTOR", "DESTRUCTOR", "FUNCTION_TEMPLATE", "CONVERSION_FUNCTION"}
WRAPPERS = {"UNEXPOSED_EXPR", "PAREN_EXPR", "CSTYLE_CAST_EXPR", "CXX_STATIC_CAST_EXPR", "CXX_REINTERPRET_CAST_EXPR"}


def children(c):
    return list(c.get_children())


def walk(c):
    yield c
    for child in c.get_children():
        yield from walk(child)


def tokens(c):
    return [t.spelling for t in c.get_tokens()]


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


class Extractor:
    def __init__(self, request):
        self.root = Path(request["root"]).resolve()
        self.unit = request["unit"]
        self.cfg = request["config"]
        self.tu_name = self.unit["source_file"]
        self.variables, self.functions, self.symbols = {}, {}, {}
        self.accesses, self.calls, self.unknowns = [], [], []
        self.events, self.registrations, self.snapshots = [], [], []
        self.source_cache = {}
        self.local_counts = {}
        self.task_reference_sites = set()
        self.coverage_source = request.get("coverage_source", "compile_database")
        self.source_overrides = request.get("source_overrides", {})
        self.declaration_only = request.get("declaration_only", False)

    def loc(self, c):
        loc = c.location
        return dict(file=relative(loc.file.name, self.root) if loc.file else self.tu_name,
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
                f = dict(function_id=self.fid(c), name=c.spelling, qualified_name=c.displayname,
                         linkage=c.linkage.name, is_static=c.linkage.name == "INTERNAL",
                         entry_attributes=[ch.kind.name for ch in c.get_children()
                                           if ch.kind.name.endswith('_ATTR')],
                         parameter_count=sum(1 for _ in c.get_arguments()),
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
                defining = c.is_definition() or (c.storage_class.name != "EXTERN" and not local
                                                 and c.semantic_parent.kind.name == "TRANSLATION_UNIT"
                                                 and Path(self.unit["source"]).suffix.lower() == ".c")
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
                                  is_pointer=typ.kind.name in {"POINTER", "LVALUEREFERENCE", "RVALUEREFERENCE"},
                                  is_struct=typ.kind.name == "RECORD", is_bitfield_container=bitfield,
                                  declarations=[], definitions=[], translation_units=[self.tu_name],
                                  definition_file=None, definition_line=None, initializer=" ".join(tokens(c))[:500],
                                  coverage_source=self.coverage_source)
                    self.variables[sid] = record
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

    def refs(self, c):
        result = []
        for n in walk(c):
            if n.kind.name == "DECL_REF_EXPR" and n.referenced:
                sid = self.symbols.get(self.key(n.referenced))
                if sid:
                    result.append((sid, n))
        return result

    def access_mode(self, ref, ancestors, pointer=False):
        mode, path = "READ", []
        decay = False
        for parent, index in reversed(ancestors):
            k = parent.kind.name
            if k in WRAPPERS:
                if parent.type.get_canonical().kind.name == "POINTER" and ref.type.get_canonical().kind.name != "POINTER":
                    decay = True
                continue
            if k == "MEMBER_REF_EXPR":
                if pointer or "->" in tokens(parent):
                    return "READ", ".".join(reversed(path))
                path.append(parent.spelling)
                continue
            if k == "ARRAY_SUBSCRIPT_EXPR":
                if index != 0 or pointer:
                    return "READ", ".".join(reversed(path))
                decay = False  # The decayed base is consumed by an element access.
                path.append("[]")
                continue
            if k == "UNARY_OPERATOR":
                op = operator(parent)
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
                    if op == "=" and any(s == self.symbols.get(self.key(ref.referenced)) for s, _ in self.refs(children(parent)[1])):
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
        return mode, ".".join(reversed(path))

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
        common = dict(conditional_ancestor=conditional)
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
        aliases, snapshots = {}, {}
        all_nodes = list(walk(fn))
        # Flow-insensitive local pointer alias union: never claim a unique runtime target.
        for _ in range(3):
            for n in all_nodes:
                cs = children(n)
                local = None
                rhs = None
                if n.kind.name == "VAR_DECL" and n.storage_class.name != "STATIC" and cs:
                    local, rhs = n, cs[-1]
                elif n.kind.name == "BINARY_OPERATOR" and operator(n) == "=" and len(cs) == 2:
                    left = [x.referenced for x in walk(cs[0]) if x.kind.name == "DECL_REF_EXPR" and x.referenced]
                    if len(left) == 1 and left[0].kind.name == "VAR_DECL" and self.key(left[0]) not in self.symbols:
                        local, rhs = left[0], cs[1]
                if local is None:
                    continue
                direct = {s for s, _ in self.refs(rhs) if not self.variables[s]['is_pointer']}
                inherited = set()
                for x in walk(rhs):
                    if x.kind.name == "DECL_REF_EXPR" and x.referenced:
                        inherited |= aliases.get(self.key(x.referenced), set())
                key = self.key(local)
                if local.type.get_canonical().kind.name in {"POINTER", "LVALUEREFERENCE", "RVALUEREFERENCE"}:
                    if direct or inherited:
                        aliases.setdefault(key, set()).update(direct | inherited)
                elif direct:
                    snapshots.setdefault(key, set()).update(direct)

        def visit(c, ancestors):
            k = c.kind.name
            if c != fn and k in FUNCTIONS:
                return
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
                # Explicit library argument semantics, with address escape retained separately.
                semantics = {"memcpy": {0: "WRITE", 1: "READ"}, "memmove": {0: "WRITE", 1: "READ"},
                             "memset": {0: "WRITE"}, "memcmp": {0: "READ", 1: "READ"}}.get(name, {})
                for i, arg in enumerate(args):
                    found = {s for s, _ in self.refs(arg)}
                    for x in walk(arg):
                        if x.kind.name == "DECL_REF_EXPR" and x.referenced:
                            found |= aliases.get(self.key(x.referenced), set())
                    if i in semantics:
                        for sid in found:
                            # A pointer object is read; its pointee remains an alias uncertainty.
                            if not self.variables[sid]["is_pointer"]:
                                self.add_access(sid, arg, fid, semantics[i], via_api=name, parse_confidence_override="conservative")
                    if name and "DMA" in name.upper() and found:
                        for sid in found:
                            # Passing the pointer's value does not make its own
                            # storage a DMA buffer. The solver models pointees,
                            # including &pointer when that is the real buffer.
                            if not self.variables[sid]['is_pointer']:
                                self.issue("DMA_SHARED_REVIEW", c, fid, symbol_id=sid, api=name)
            if k == "DECL_REF_EXPR" and c.referenced:
                key = self.key(c.referenced)
                sid = self.symbols.get(key)
                if sid:
                    mode, path = self.access_mode(c, ancestors, self.variables[sid]["is_pointer"])
                    self.add_access(sid, c, fid, mode, access_path=path,
                                    conditional_ancestor=any(parent.kind.name in {'IF_STMT', 'SWITCH_STMT', 'FOR_STMT',
                                                                                   'WHILE_STMT', 'DO_STMT', 'CONDITIONAL_OPERATOR'}
                                                               for parent, _ in ancestors))
                    if mode == "ADDRESS_TAKEN":
                        self.issue("ADDRESS_ESCAPE", c, fid, symbol_id=sid)
                elif key in snapshots:
                    for original in snapshots[key]:
                        self.snapshots.append(dict(symbol_id=original, function_id=fid, local_name=c.spelling,
                                                   **self.loc(c), source_text=self.source(c), confidence="conservative"))
                if key in aliases:
                    for parent, index in reversed(ancestors):
                        if parent.kind.name in WRAPPERS:
                            continue
                        if (parent.kind.name == "UNARY_OPERATOR" and operator(parent) == "*") or parent.kind.name in {"ARRAY_SUBSCRIPT_EXPR", "MEMBER_REF_EXPR"}:
                            above = ancestors[:ancestors.index((parent, index))]
                            mode, path = self.access_mode(c, above, False)
                            for original in aliases[key]:
                                self.add_access(original, c, fid, mode, access_path=path, via_alias=c.spelling,
                                                parse_confidence_override="conservative",
                                                conditional_ancestor=any(parent.kind.name in {'IF_STMT', 'SWITCH_STMT', 'FOR_STMT',
                                                                                               'WHILE_STMT', 'DO_STMT', 'CONDITIONAL_OPERATOR'}
                                                                           for parent, _ in ancestors))
                        break
            if (k == "UNARY_OPERATOR" and operator(c) == "*") or (k == "MEMBER_REF_EXPR" and "->" in tokens(c)):
                self.issue("POINTER_DEREFERENCE", c, fid)
            if k == "ARRAY_SUBSCRIPT_EXPR":
                cs = children(c)
                if cs and not any(self.variables[s]["is_array"] for s, _ in self.refs(cs[0])):
                    self.issue("POINTER_SUBSCRIPT", c, fid)
            if "ASM" in k:
                self.issue("INLINE_ASSEMBLY", c, fid)
            for i, ch in enumerate(c.get_children()):
                visit(ch, ancestors + [(c, i)])
        visit(fn, [])

    def run(self):
        os.chdir(self.unit["directory"])
        if self.cfg["analysis"].get("libclang_file"):
            ci.Config.set_library_file(self.cfg["analysis"]["libclang_file"])
        index = ci.Index.create()
        unsaved = [(path, content) for path, content in self.source_overrides.items()]
        tu = index.parse(self.unit["source"], args=self.unit["arguments"],
                         unsaved_files=unsaved,
                         options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        diagnostics = [dict(severity=d.severity, message=str(d)) for d in tu.diagnostics]
        self.declare(tu.cursor)
        parse_status = "FAILED" if any(d["severity"] >= 3 for d in diagnostics) else "PARSED"
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
                    self.issue("FUNCTION_ADDRESS", c, target_function_id=self.fid(c.referenced))
        includes = sorted({str(Path(i.include.name).resolve()) for i in tu.get_includes()})
        for a in self.accesses:
            a["parse_confidence"] = a.pop("parse_confidence_override", a["parse_confidence"])
            a["access_id"] = "A-" + digest([self.tu_name, a])[:20]
        from .pointer_extract import PointerExtractor
        pointer_facts = PointerExtractor(self).run(tu.cursor)
        return dict(variables=list(self.variables.values()), functions=list(self.functions.values()),
                    accesses=self.accesses, calls=self.calls, unknowns=self.unknowns,
                    protection_events=self.events, registrations=self.registrations, snapshots=self.snapshots,
                    diagnostics=diagnostics, includes=includes, **pointer_facts,
                    parse_status="FAILED" if any(d["severity"] >= 3 for d in diagnostics) else "PARSED")


def main():
    request = read_json(sys.argv[1])
    try:
        result = Extractor(request).run()
    except Exception as exc:
        result = dict(parse_status="FAILED", diagnostics=[dict(severity=4, message=f"{type(exc).__name__}: {exc}")])
    write_json(sys.argv[2], result)


if __name__ == "__main__":
    main()
