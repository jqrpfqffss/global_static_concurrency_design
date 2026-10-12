"""Independently compare Clang static-storage definitions with ECRA roots."""

import json
import sys
from pathlib import Path

from clang import cindex

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecra.compilation import prepare
from ecra.config import load_config
from ecra.scope import AuditScope


def main(root: Path, config_path: Path) -> None:
    root, config_path = root.resolve(), config_path.resolve()
    cfg, _ = load_config(root, config_path)
    scope = AuditScope(root, cfg['analysis'])
    units, _ = prepare(root, cfg)
    expected = set()
    failures = []

    def walk(cursor, owner=None):
        if cursor.kind == cindex.CursorKind.FUNCTION_DECL and cursor.is_definition():
            owner = cursor.spelling
        if cursor.kind == cindex.CursorKind.VAR_DECL:
            local = owner is not None
            defining = cursor.is_definition() or cursor.storage_class != cindex.StorageClass.EXTERN
            if defining and (not local or cursor.storage_class == cindex.StorageClass.STATIC):
                source = cursor.location.file
                if source and scope.contains(Path(source.name)):
                    path = Path(source.name).resolve().relative_to(root).as_posix()
                    expected.add((path, cursor.location.line, cursor.spelling, owner or ''))
        for child in cursor.get_children():
            walk(child, owner)

    for unit in units:
        args = [a for a in unit['arguments'] if a != unit['source']]
        try:
            tu = cindex.Index.create().parse(unit['source'], args=args)
            walk(tu.cursor)
        except Exception as exc:
            failures.append(f"{unit['source_file']}: {exc}")

    facts = json.loads((root / '.ecra/facts.json').read_text(encoding='utf-8'))
    actual = set()
    for var in facts['variables']:
        if (var['kind'] not in {'GLOBAL', 'FILE_STATIC', 'LOCAL_STATIC'}
                or not var.get('definition_file')
                or '::element::' in var['symbol_id'] or '::member::' in var['symbol_id']):
            continue
        owner = var['qualified_name'].split('::', 1)[0] if var['kind'] == 'LOCAL_STATIC' else ''
        actual.add((var['definition_file'], var['definition_line'], var['name'], owner))
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    result = dict(translation_units=len(units), expected_roots=len(expected), actual_roots=len(actual),
                  missing=missing, extra=extra, parse_failures=failures)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if missing or extra or failures:
        sys.exit(1)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
