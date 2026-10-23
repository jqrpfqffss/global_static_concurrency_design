"""Compare all raw fact arrays in two real worker-output collections.

With --explain-parse-status, variable parse_status is reported separately;
all remaining variable fields and every relationship stay strictly compared.
Parser diagnostics are metadata, not silently counted as AST equivalence.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys
import sqlite3
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecra.analysis import TABLES
from ecra.json_rows import rows


def fingerprint(path, index, explain_parse_status=False):
    counts, statuses = Counter(), Counter()
    metadata, diagnostics = {}, []
    def records():
        for key, row, is_array in rows(path):
            if key in TABLES and is_array:
                if key == 'variables':
                    statuses[row.get('parse_status')] += 1
                    if explain_parse_status:
                        row = dict(row)
                        row.pop('parse_status', None)
                counts[key] += 1
                yield key, hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                    separators=(',', ':')).encode('utf-8')).digest()
            elif key == 'parse_status':
                metadata[key] = row
            elif key == 'diagnostics' and is_array:
                diagnostics.append(row)
    with index:
        index.execute('DELETE FROM hashes')
        index.executemany('INSERT INTO hashes VALUES (?,?)', records())
    hashes = {}
    for key in TABLES:
        sha = hashlib.sha256()
        for record in index.execute('SELECT digest FROM hashes WHERE table_name=? ORDER BY digest', (key,)):
            sha.update(record[0])
        hashes[key] = dict(count=counts[key], sha256=sha.hexdigest())
    return dict(tables=hashes, parse_status=metadata.get('parse_status'),
                variable_parse_status=dict(statuses), diagnostics=diagnostics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--explain-parse-status', action='store_true')
    args = parser.parse_args()
    def files(folder):
        return {p.name: p for p in folder.glob('TU-*.response.json') if '.dependencies.' not in p.name}
    first, second = files(args.before), files(args.after)
    result = dict(before=str(args.before), after=str(args.after), missing=sorted(first.keys()-second.keys()),
                  added=sorted(second.keys()-first.keys()), units=[],
                  normalized_fields=['variables.parse_status'] if args.explain_parse_status else [],
                  boundary='Every raw AST relationship and variable identity/value is compared. '
                           'Explicitly normalized parse state and parser diagnostics are reported separately; '
                           'this does not establish equality of later safety proofs. Top-level table row order is '
                           'normalized as a multiset with duplicates preserved; nested list order remains strict.')
    with tempfile.TemporaryDirectory(prefix='ecra raw fact comparison ') as folder, \
            closing(sqlite3.connect(str(Path(folder)/'rows.db'))) as index:
        index.execute('PRAGMA cache_size=-2048')
        index.execute('PRAGMA temp_store=FILE')
        index.execute('CREATE TABLE hashes(table_name TEXT, digest BLOB)')
        index.execute('CREATE INDEX fact_order ON hashes(table_name,digest)')
        for name in sorted(first.keys() & second.keys()):
            a = fingerprint(first[name], index, args.explain_parse_status)
            b = fingerprint(second[name], index, args.explain_parse_status)
            result['units'].append(dict(file=name, relationships_identical=a['tables'] == b['tables'],
                                    tables={key: dict(before=a['tables'][key], after=b['tables'][key],
                                                     identical=a['tables'][key] == b['tables'][key]) for key in TABLES},
                                    before_parse_status=a['parse_status'], after_parse_status=b['parse_status'],
                                    before_variable_parse_status=a['variable_parse_status'],
                                    after_variable_parse_status=b['variable_parse_status'],
                                    before_diagnostics=a['diagnostics'], after_diagnostics=b['diagnostics']))
    result['relationships_identical'] = bool(result['units']) and not result['missing'] and not result['added'] and all(
        unit['relationships_identical'] for unit in result['units'])
    result['parser_state_identical'] = all(unit['before_parse_status'] == unit['after_parse_status'] and
        unit['before_diagnostics'] == unit['after_diagnostics'] and
        unit['before_variable_parse_status'] == unit['after_variable_parse_status'] for unit in result['units'])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(relationships_identical=result['relationships_identical'],
                         parser_state_identical=result['parser_state_identical'], units=len(result['units']),
                         output=str(args.output))))
    return 0 if result['relationships_identical'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
