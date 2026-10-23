"""Explain every changed variable field in two saved fact databases.

Large values are identified by a complete SHA-256 and byte size; their full
contents remain in the named database row. No classification change is omitted.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def value(raw):
    if isinstance(raw, str) and raw.startswith(('[', '{')):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def evidence(raw):
    if isinstance(raw, str) and len(raw) > 16384:
        encoded = raw.encode('utf-8')
        return dict(sha256=hashlib.sha256(encoded).hexdigest(), bytes=len(encoded), full_value='retained in database')
    return value(raw)


def compare(before, after):
    result = dict(before=str(before), after=str(after), changed=[], removed=[], added=[],
                  classification_changes=[], scope='every variable field, no omitted variables')
    with closing(sqlite3.connect(f'{before.resolve().as_uri()}?mode=ro', uri=True)) as first, \
            closing(sqlite3.connect(f'{after.resolve().as_uri()}?mode=ro', uri=True)) as second:
        first.row_factory = second.row_factory = sqlite3.Row
        first_ids = {r[1]: r[0] for r in first.execute('SELECT rowid,symbol_id FROM variables')}
        second_ids = {r[1]: r[0] for r in second.execute('SELECT rowid,symbol_id FROM variables')}
        result['removed'] = sorted(first_ids.keys()-second_ids.keys())
        result['added'] = sorted(second_ids.keys()-first_ids.keys())
        result['counts'] = dict(before=len(first_ids), after=len(second_ids))
        for symbol in sorted(first_ids.keys() & second_ids.keys()):
            a = first.execute('SELECT * FROM variables WHERE rowid=?', (first_ids[symbol],)).fetchone()
            b = second.execute('SELECT * FROM variables WHERE rowid=?', (second_ids[symbol],)).fetchone()
            changes = {}
            for key in sorted(set(a.keys()) | set(b.keys())):
                av = a[key] if key in a.keys() else None
                bv = b[key] if key in b.keys() else None
                if av == bv or value(av) == value(bv):
                    continue
                changes[key] = dict(before=evidence(av), after=evidence(bv))
            if changes:
                record = dict(symbol_id=symbol, qualified_name=b['qualified_name'], fields=changes,
                              before_rowid=first_ids[symbol], after_rowid=second_ids[symbol])
                result['changed'].append(record)
                if 'static_classification' in changes:
                    result['classification_changes'].append(record)
        result['unknown_kinds'] = {}
        result['type_variants'] = {}
        for label, db in [('before', first), ('after', second)]:
            result['unknown_kinds'][label] = {r[0]: r[1] for r in db.execute('SELECT kind,COUNT(*) FROM unknowns GROUP BY kind')}
            result['type_variants'][label] = [dict(r) for r in db.execute("SELECT * FROM unknowns WHERE kind='TYPE_VARIANT'")]
    result['identical'] = not any(result[k] for k in ('changed', 'removed', 'added'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.before, args.after)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(changed=len(result['changed']), classification_changes=len(result['classification_changes']),
                          added=len(result['added']), removed=len(result['removed']), output=str(args.output))))
    return 0 if result['identical'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
