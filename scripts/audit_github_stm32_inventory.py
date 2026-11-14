"""Independently enumerate Clang storage declarations and compare scan roots.

The expected inventory comes only from libclang cursors. The default adapter
reuses ECRA's compilation/driver setup. Use --units for independently checked
Clang inputs so that this part of the audit does not rely on prepare().
"""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import ctypes
import json
import os
from pathlib import Path
import sqlite3
import sys

from clang import cindex


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {'FUNCTION_DECL', 'CXX_METHOD', 'CONSTRUCTOR', 'DESTRUCTOR', 'FUNCTION_TEMPLATE',
             'CONVERSION_FUNCTION', 'LAMBDA_EXPR'}
AST_LEAVES = {'TYPE_REF', 'NAMESPACE_REF', 'TEMPLATE_REF', 'DECL_REF_EXPR', 'MEMBER_REF_EXPR'}
DERIVED = {'STRUCT_MEMBER', 'STRUCT_MEMBER_CONTAINER', 'ARRAY_ELEMENT'}


def relative(path, root):
    resolved = Path(path).resolve()
    return (resolved.relative_to(root) if resolved.is_relative_to(root) else resolved).as_posix()


def location(cursor, root):
    loc = cursor.location
    return dict(file=relative(loc.file.name, root), line=loc.line, column=loc.column,
                offset=loc.offset) if loc.file else None


def owners(cursor, root):
    result = []
    parent = cursor.semantic_parent
    while parent is not None and parent.kind.name != 'TRANSLATION_UNIT':
        result.append(dict(kind=parent.kind.name, name=parent.spelling, usr=parent.get_usr(),
                           site=location(parent, root)))
        parent = parent.semantic_parent
    return list(reversed(result))


def unit_language(unit):
    """Use the input command, independently of ECRA's source admission."""
    option = None
    args = iter(unit['arguments'])
    for arg in args:
        if arg == '-x':
            option = next(args, None)
        elif arg.startswith('-x'):
            option = arg[2:]
    if option and option != 'none':
        if option in {'assembler', 'assembler-with-cpp'}:
            return 'asm'
        return 'c++' if '++' in option else 'c' if option in {'c', 'cpp-output', 'c-cpp-output', 'c-header'} else None
    suffix = Path(unit['source']).suffix
    if suffix == '.C' or suffix.lower() in {'.cc', '.cpp', '.cxx', '.c++', '.ii', '.mpp'}:
        return 'c++'
    if suffix.lower() in {'.c', '.i'}:
        return 'c'
    if suffix.lower() in {'.s', '.asm'}:
        return 'asm'
    return None


def walk_storage(tu, unit, root):
    """Keep lexical sites and distinguish definitions, declarations and C tentatives."""
    language = unit_language(unit)
    is_inlined = cindex.conf.lib.clang_Cursor_isFunctionInlined
    is_inlined.argtypes, is_inlined.restype = [cindex.Cursor], ctypes.c_uint
    pending = [tu.cursor]
    while pending:
        cursor = pending.pop()
        kind = cursor.kind.name
        if kind not in AST_LEAVES and not kind.endswith('_ATTR'):
            pending.extend(reversed(list(cursor.get_children())))
        if kind != 'VAR_DECL':
            continue
        site = location(cursor, root)
        if site is None:
            continue
        parent = cursor.semantic_parent
        lexical = cursor.lexical_parent
        storage = cursor.storage_class.name
        linkage = cursor.linkage.name
        local = parent is not None and parent.kind.name in FUNCTIONS
        thread_local = cursor.tls_kind.name != 'NONE'
        if local and storage not in {'STATIC', 'EXTERN', 'PRIVATEEXTERN'} and not thread_local:
            continue
        tentative = (language == 'c' and storage in {'NONE', 'STATIC'}
                     and parent is not None and parent.kind.name == 'TRANSLATION_UNIT'
                     and lexical is not None and lexical.kind.name == 'TRANSLATION_UNIT')
        # libclang can report false for a later declarator in a compound
        # declaration, e.g. the second variable in `static int a=1,b=2;`.
        # At block scope a `static` variable declaration defines its storage.
        definition = cursor.is_definition() or (local and storage == 'STATIC')
        scope = owners(cursor, root)
        slot = unit['source_file'] if linkage in {'INTERNAL', 'UNIQUE_EXTERNAL'} else None
        if local and linkage == 'NO_LINKAGE' and not (
                language == 'c++' and parent.linkage.name == 'EXTERNAL' and is_inlined(parent)):
            slot = unit['source_file']
        yield dict(site=site, usr=cursor.get_usr(), name=cursor.spelling,
                   qualified_name='::'.join([*(item['name'] for item in scope if item['name']), cursor.spelling]),
                   type=cursor.type.spelling, linkage=linkage, storage_class=storage, thread_local=thread_local,
                   enclosing_scope=scope, local=local, scope_instance=slot,
                   translation_unit=unit['source_file'], tu_id=unit.get('tu_id'),
                   definition=definition or tentative, tentative=tentative and not definition,
                   lexical_parent=lexical.kind.name if lexical is not None else None)


def enumerate_units(root, units):
    declarations, coverage = [], []
    original = Path.cwd()
    index = cindex.Index.create()
    try:
        for unit in units:
            source = unit['source']
            language = unit_language(unit)
            if language not in {'c', 'c++'}:
                raise ValueError('Unexpected unit language in actual Clang inputs: ' + source)
            os.chdir(unit['directory'])
            args = [arg for arg in unit['arguments'] if arg != source]
            if '-Wno-error=incompatible-function-pointer-types' not in args:
                args.append('-Wno-error=incompatible-function-pointer-types')
            report = dict(tu_id=unit.get('tu_id'), source_file=unit['source_file'], language=language)
            try:
                tu = index.parse(source, args=args)
            except cindex.TranslationUnitLoadError as exc:
                coverage.append(dict(report, status='FAILED', diagnostics=[dict(severity=4, message=str(exc))]))
                continue
            diagnostics = [dict(severity=d.severity, message=str(d)) for d in tu.diagnostics]
            maximum = max((row['severity'] for row in diagnostics), default=0)
            status = 'FAILED' if maximum >= 4 else 'PARTIAL' if maximum >= 3 else 'PARSED'
            coverage.append(dict(report, status=status, diagnostics=diagnostics,
                                 dependencies=sorted({relative(dep.include.name, root) for dep in tu.get_includes()})))
            declarations.extend(dict(row, parse_status=status) for row in walk_storage(tu, unit, root))
    finally:
        os.chdir(original)
    return declarations, coverage


def expected_key(row):
    """Clang USR is link identity; preserve physical sites when USR is absent."""
    return row['usr'] or (row['qualified_name'], *site_key(row['site'])), row['scope_instance']


def site_key(site):
    return site['file'], site['line'], site['column'], site.get('offset')


def actual_roots(scan_dir):
    """Read only declaration fields from the authority, even for huge graphs."""
    fields = ('symbol_id', 'name', 'qualified_name', 'kind', 'resource_kind', 'linkage', 'type',
              'definition_file', 'definitions', 'declarations', 'translation_units')
    if (scan_dir/'scan.db').is_file():
        from ecra.native_consumers import _child, _root, _small_value
        from ecra.scan_store import connect_readonly
        with closing(connect_readonly(scan_dir/'scan.db')) as conn:
            pool = _child(conn, _root(conn, 'facts'), 'variables')
            return [{key: _small_value(conn, value) for key, value in conn.execute(
                'SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal', (node,)) if key in fields}
                for (node,) in conn.execute('SELECT child FROM edges WHERE parent=? ORDER BY ordinal', (pool,))]
    with closing(sqlite3.connect((scan_dir/'facts.db').as_uri()+'?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        available = {row[1] for row in conn.execute('PRAGMA table_info(variables)')}
        rows = [dict(row) for row in conn.execute('SELECT ' + ','.join(key for key in fields if key in available)
                                                 + ' FROM variables')]
        from ecra.shared_json import DatabasePool
        pool = DatabasePool(conn)
        for row in rows:
            for key in ('definitions','translation_units','declarations'):
                if isinstance(row.get(key), str):
                    row[key] = pool.loads(row[key])
        return rows


def compare(expected, actual, contains):
    roots = defaultdict(list)
    for row in expected:
        if row['definition'] and not row['thread_local']:
            roots[expected_key(row)].append(row)
    roots = {key: rows for key, rows in roots.items() if all(contains(row['site']['file']) for row in rows)}
    by_site = defaultdict(set)
    for row in actual:
        if (row.get('root_symbol_id') or row.get('array_root_symbol_id') or row.get('resource_kind') in DERIVED
                or '::member::' in row['symbol_id'] or '::element::' in row['symbol_id']):
            continue
        for site in row.get('definitions') or []:
            by_site[(row['name'], site_key(site))].add(row['symbol_id'])
    by_id = {row['symbol_id']: row for row in actual}
    matches, missing, ambiguous = [], [], []
    units_by_path = defaultdict(set)
    for row in expected:
        units_by_path[row['translation_unit']].add(row['tu_id'])
    for (usr, instance), definitions in roots.items():
        candidates = set()
        for row in definitions:
            site_matches = by_site[(row['name'], site_key(row['site']))]
            candidates.update(sid for sid in site_matches
                              if by_id[sid].get('linkage', row['linkage']) == row['linkage']
                              and (instance is None or instance in (by_id[sid].get('translation_units') or [])))
        identity = dict(usr=usr, instance=instance, definitions=definitions)
        if instance is not None and len(units_by_path[instance]) > 1:
            ambiguous.append(dict(identity, candidates=sorted(candidates), reason='MULTIPLE_COMMANDS_FOR_SAME_TU_PATH'))
            continue
        if not candidates:
            missing.append(identity)
        elif len(candidates) != 1:
            ambiguous.append(dict(identity, candidates=sorted(candidates)))
        else:
            matches.append(dict(identity, symbol_id=candidates.pop()))
    counted = Counter(row['symbol_id'] for row in matches)
    collapsed = {sid: count for sid, count in counted.items() if count > 1}
    present = {sid for values in by_site.values() for sid in values}
    extras = sorted(present - counted.keys() - {sid for row in ambiguous for sid in row['candidates']})
    return dict(expected_roots=len(roots), actual_defined_roots=len(present), matches=matches,
                missing=missing, ambiguous=ambiguous, coalesced_distinct_roots=collapsed,
                extra=[by_id[sid] for sid in extras])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('config', type=Path)
    parser.add_argument('--units', type=Path, help='Explicit JSON array of verified effective Clang commands')
    parser.add_argument('--scan-dir', type=Path)
    parser.add_argument('--stage', type=Path, help='A recorded stage with compact rows instead of the published scan')
    parser.add_argument('--expected-only', action='store_true')
    parser.add_argument('--expected', type=Path, help='Reuse a separately generated independent AST receipt')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root, config = args.root.resolve(), args.config.resolve()
    sys.path.insert(0, str(ROOT))
    from ecra.config import load_config
    from ecra.scope import AuditScope
    cfg, _ = load_config(root, config)
    scope = AuditScope(root, cfg['analysis'])
    if cfg['analysis'].get('libclang_file'):
        cindex.Config.set_library_file(cfg['analysis']['libclang_file'])
    if args.expected:
        result = json.loads(args.expected.read_bytes())
    else:
        if args.units:
            units = json.loads(args.units.read_bytes())
        else:
            from ecra.compilation import prepare
            units, _ = prepare(root, cfg, build_firmware=False)
        if not units:
            raise ValueError('No Clang inputs supplied')
        known_tus = [unit['tu_id'] for unit in units]
        if len(set(known_tus)) != len(known_tus):
            raise ValueError('Repeated translation-unit identities in audit inputs')
        expected, coverage = enumerate_units(root, units)
        result = dict(translation_units=len(units), parse_counts=Counter(row['status'] for row in coverage),
                      declarations=expected, coverage=coverage,
                      command_source=str(args.units.resolve()) if args.units else 'ECRA prepare()',
                      scope_source='ECRA AuditScope, separate from AST enumeration')
    if not args.expected_only:
        if args.stage:
            actual = json.loads(args.stage.read_bytes())
        else:
            from ecra.workflow import output_path
            actual = actual_roots(args.scan_dir.resolve() if args.scan_dir else output_path(root, cfg))
        result.update(compare(result['declarations'], actual, scope.contains))
    # Preserve all observed sites and diagnostics. An incomplete AST cannot
    # certify inventory completeness even if its recovered roots match.
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(payload, encoding='utf-8')
    else:
        sys.stdout.write(payload)
    return int(result['parse_counts'].get('FAILED', 0) > 0 or result['parse_counts'].get('PARTIAL', 0) > 0
               or any(result.get(key) for key in ('missing', 'ambiguous', 'coalesced_distinct_roots', 'extra')))


if __name__ == '__main__':
    raise SystemExit(main())
