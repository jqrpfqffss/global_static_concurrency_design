"""Audit a saved report without loading its HTML/JSON evidence into one object.

This is a static artifact audit, not a browser rendering test. It verifies all
sidecar hashes, local resource links, variable rows and JSON/SQLite row counts.
The optional Node check parses JavaScript syntax without opening a browser.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
from itertools import zip_longest
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecra.common import digest
from ecra.json_rows import RowReader


def fact_values(path):
    """Stream rows and pool entries; a large pool dict is never decoded whole."""
    from ecra.shared_json import encoded
    if encoded(path):
        from ecra.json_rows import rows
        for key, value, is_array in rows(path):
            if key == 'pointer_target_sets':
                for item in value.items():
                    yield key, item, False
            else:
                yield key, value, is_array
        return
    with path.open(encoding='utf-8-sig') as stream:
        reader = RowReader(stream)
        reader.take('{')
        seen = set()
        while reader.peek() != '}':
            key = reader.value()
            if not isinstance(key, str) or key in seen:
                raise ValueError('Invalid or repeated fact table')
            seen.add(key)
            reader.take(':')
            if key == 'pointer_target_sets':
                reader.take('{')
                while reader.peek() != '}':
                    ident = reader.value()
                    reader.take(':')
                    yield key, (ident, reader.value()), False
                    if reader.peek() == '}':
                        break
                    reader.take(',')
                reader.take('}')
            elif reader.peek() == '[':
                reader.take('[')
                while reader.peek() != ']':
                    yield key, reader.value(), True
                    if reader.peek() == ']':
                        break
                    reader.take(',')
                reader.take(']')
            else:
                yield key, reader.value(), False
            if reader.peek() == '}':
                break
            reader.take(',')
        reader.take('}')
        if reader.peek():
            raise ValueError('Trailing data in facts JSON')


def audit_fact_database(path, source, index):
    """Compare every fact count, atom, pool entry and encoded reference."""
    counts, metadata = Counter(), {}
    index.execute('CREATE TABLE atoms (id INTEGER PRIMARY KEY, target TEXT)')
    index.execute('CREATE TABLE pools (id TEXT PRIMARY KEY, data TEXT)')
    atom_count = 0
    with index:
        for table, value, is_array in fact_values(path):
            if table == 'pointer_target_atoms':
                index.execute('INSERT INTO atoms VALUES (?,?)', (atom_count, value))
                atom_count += 1
            elif table == 'pointer_target_sets':
                ident, encoded = value
                index.execute('INSERT INTO pools VALUES (?,?)',
                              (ident, json.dumps(encoded, ensure_ascii=False, separators=(',', ':'))))
            elif table in {'pointer_target_encoding', 'pointer_target_block_bits',
                           'points_to_stats', 'context_points_to_stats'}:
                metadata[table] = value
            elif is_array and isinstance(value, dict):
                counts[table] += 1
    tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    differences = {}
    from ecra.shared_json import DatabasePool
    database_pool = DatabasePool(source)
    for table in tables - {'findings', 'review_safe_samples', 'pointer_target_atoms', 'pointer_target_sets'} - DatabasePool.TABLES:
        actual = source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if actual != counts[table]:
            differences[table] = dict(json=counts[table], sqlite=actual)
    for table in counts.keys() - tables:
        differences[table] = dict(json=counts[table], sqlite=None)
    errors, error_count = [], 0

    def error(kind, value):
        nonlocal error_count
        error_count += 1
        if len(errors) < 20:
            errors.append(dict(kind=kind, value=value))

    pool_count = index.execute('SELECT COUNT(*) FROM pools').fetchone()[0]
    pool_tables = {'pointer_target_atoms', 'pointer_target_sets'}
    if (pool_count or atom_count or pool_tables & tables) and not pool_tables <= tables:
        error('missing_sqlite_pool_tables', sorted(pool_tables - tables))
    elif pool_tables <= tables:
        for expected, actual in zip_longest(index.execute('SELECT id,target FROM atoms ORDER BY id'),
                source.execute('SELECT target_index,target FROM pointer_target_atoms ORDER BY target_index')):
            if expected != actual:
                error('atom_mismatch', dict(expected=expected, actual=actual))
        index.execute('CREATE TABLE pool_sizes (id TEXT PRIMARY KEY, count INTEGER)')
        for expected, actual in zip_longest(index.execute('SELECT id,data FROM pools ORDER BY id'),
                source.execute('SELECT target_set_id,encoding,block_bits,data FROM pointer_target_sets ORDER BY target_set_id')):
            if expected is None or actual is None or expected[0] != actual[0]:
                error('pool_identity_mismatch', [expected[0] if expected else None, actual[0] if actual else None])
                continue
            ident, encoded = expected[0], json.loads(expected[1])
            if (encoded != json.loads(actual[3]) or actual[1] != metadata.get('pointer_target_encoding')
                    or actual[2] != metadata.get('pointer_target_block_bits')):
                error('pool_content_mismatch', ident)
            try:
                count, max_bit = 0, 0
                if metadata.get('pointer_target_encoding') == 'INTERNED_BITMAP_V1':
                    bits = int(encoded, 16)
                    if bits < 0:
                        raise ValueError('negative bitmap')
                    count, max_bit = bits.bit_count(), bits.bit_length()
                elif (metadata.get('pointer_target_encoding') == 'INTERNED_BLOCK_BITMAP_V2'
                      and metadata.get('pointer_target_block_bits') == 4096):
                    previous = -1
                    for block, payload in encoded:
                        bits = int(payload, 16)
                        if type(block) is not int or block <= previous or not 0 < bits < (1 << 4096):
                            raise ValueError('invalid or unordered block')
                        previous = block
                        count += bits.bit_count()
                        max_bit = block * 4096 + bits.bit_length()
                else:
                    raise ValueError('unsupported pointer encoding')
                if max_bit > atom_count:
                    raise ValueError('bitmap references missing atom')
                index.execute('INSERT INTO pool_sizes VALUES (?,?)', (ident, count))
            except (TypeError, ValueError):
                error('invalid_bitmap', ident)
    if 'pointer_targets' in tables:
        columns = {r[1] for r in source.execute('PRAGMA table_info(pointer_targets)')}
        if 'target_set_id' in columns:
            for location, ident, count in source.execute('SELECT location,target_set_id,target_count '
                    'FROM pointer_targets WHERE target_set_id IS NOT NULL'):
                size = (index.execute('SELECT count FROM pool_sizes WHERE id=?', (ident,)).fetchone()
                        if pool_tables <= tables else None)
                if size is None or size[0] != count:
                    error('pool_reference_or_cardinality', dict(location=location, target_set_id=ident))
    solver_summaries = {key: metadata[key] for key in ('points_to_stats', 'context_points_to_stats')
                        if key in metadata}
    return dict(row_counts=dict(counts), differences=differences, solver_summaries=solver_summaries,
                solver_fixed_points_complete=all(solver_summaries.get(key, {}).get('complete') is True
                    for key in ('points_to_stats', 'context_points_to_stats')),
                pools=dict(atoms=atom_count, sets=pool_count, error_count=error_count, errors=errors),
                shared_json_pool_nodes=len(database_pool.nodes))


class Document(HTMLParser):
    def __init__(self, path, connection):
        super().__init__(convert_charrefs=True)
        self.path, self.connection = path, connection
        self.ids, self.links, self.scripts = [], [], []
        self.script, self.inline = False, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr' and attrs.get('id', '').startswith('var-'):
            self.ids.append((attrs['id'],))
        for key in ('href', 'src', 'data-ecra-src'):
            value = attrs.get(key)
            if not value:
                continue
            uri = urlsplit(value)
            if uri.scheme or uri.netloc or not uri.path:
                continue
            target = (self.path.parent/unquote(uri.path)).resolve()
            self.links.append((str(target), str(self.path)))
        if tag == 'script':
            self.script = not attrs.get('src') and attrs.get('type', '').lower() not in {'application/json', 'application/ld+json'}
            self.inline = []
        if len(self.ids) + len(self.links) >= 256:
            self.flush()

    def handle_data(self, data):
        if self.script:
            self.inline.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script:
            self.scripts.append(''.join(self.inline))
            self.inline, self.script = [], False

    def flush(self):
        self.connection.executemany('INSERT OR IGNORE INTO variable_rows VALUES (?)', self.ids)
        self.connection.executemany('INSERT OR IGNORE INTO resources VALUES (?,?)', self.links)
        self.ids.clear(); self.links.clear()


def report_selection(folder):
    """Read the persisted, version-bound presentation scope, never infer it from HTML."""
    state_file = folder/'scan_state.json'
    state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.is_file() else {}
    if state.get('scan_mode', 'full') == 'full':
        return None
    if state.get('scan_mode') != 'diff':
        raise ValueError('无法识别保存的扫描模式')
    from ecra.json_rows import rows
    delta, fingerprint = None, None
    for key, value, is_array in rows(folder/'reports/global_static_concurrency.json'):
        if key == 'git_diff':
            delta = value
        elif key == 'fingerprint':
            fingerprint = value
    selected = delta.get('selected_symbol_ids') if isinstance(delta, dict) else None
    if (not isinstance(selected, list) or any(not isinstance(sid, str) for sid in selected)
            or len(set(selected)) != len(selected)
            or fingerprint != state.get('fingerprint')
            or digest(delta.get('pin')) != digest(state.get('git_diff_pin'))):
        raise ValueError('保存的差异范围或比较版本无效，禁止推断为全量或空差异')
    return set(selected)


def audit(folder, *, check_json=True, node=None):
    folder = Path(folder).resolve()
    begin = time.monotonic()
    checks, result = {}, {'browser_rendering': 'NOT_EXECUTED', 'output': str(folder)}
    validity = json.loads((folder/'result_validity.json').read_text(encoding='utf-8'))
    completion = json.loads((folder/'diagnostics/completion.json').read_text(encoding='utf-8'))
    checks['analysis_valid'] = validity.get('analysis_valid') is True and completion.get('analysis_valid') is True
    checks['snapshot_verified'] = validity.get('snapshot_status') == completion.get('snapshot_status') == 'VERIFIED'
    checks['fingerprint'] = validity.get('fingerprint') == completion.get('fingerprint')
    manifest_file = folder/'html_details/manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.is_file() else None
    bad_assets = []
    if manifest:
        checks['sidecars_complete'] = manifest.get('complete') is True
        checks['sidecar_fingerprint'] = manifest.get('fingerprint') == completion.get('fingerprint')
        for name, record in manifest['files'].items():
            path = folder/'html_details'/name
            sha = hashlib.sha256()
            if path.is_file():
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(65536), b''):
                        sha.update(block)
            if not path.is_file() or path.stat().st_size != record['bytes'] or sha.hexdigest() != record['sha256']:
                bad_assets.append(name)
        checks['sidecar_hashes'] = not bad_assets
        result['sidecars'] = dict(files=len(manifest['files']), bytes=sum(r['bytes'] for r in manifest['files'].values()),
                                  max_detail_chars=manifest.get('max_detail_chars'), bad=bad_assets)
    with tempfile.TemporaryDirectory(prefix='ecra artifact audit ') as temp, \
            closing(sqlite3.connect(f'{(folder/"facts.db").as_uri()}?mode=ro', uri=True)) as source, \
            closing(sqlite3.connect(str(Path(temp)/'audit.db'))) as index:
        index.execute('CREATE TABLE variable_rows (id TEXT PRIMARY KEY)')
        index.execute('CREATE TABLE resources (target TEXT, source TEXT, PRIMARY KEY(target,source))')
        index.execute('CREATE TABLE expected_rows (id TEXT PRIMARY KEY)')
        selected = report_selection(folder)
        inventory_ids = {row[0] for row in source.execute('SELECT symbol_id FROM variables')}
        checks['selected_scope_valid'] = selected is None or selected <= inventory_ids
        expected_ids = inventory_ids if selected is None else selected
        index.executemany('INSERT INTO expected_rows VALUES (?)',
                          (('var-'+digest(sid)[:20],) for sid in expected_ids))
        paths = [folder/name for name in ('index.html', 'opencode_review.html', 'classification_quality.html')]
        if manifest:
            paths += [folder/'html_details'/name for name in manifest['files'] if name.endswith('.html')]
        missing_documents, script_errors = [], []
        script_count = 0
        for path in paths:
            if not path.is_file():
                missing_documents.append(str(path)); continue
            document = Document(path, index)
            with path.open(encoding='utf-8') as stream:
                for chunk in iter(lambda: stream.read(65536), ''):
                    document.feed(chunk)
            document.close(); document.flush()
            if node:
                for script in document.scripts:
                    candidate = Path(temp)/'inline.js'
                    candidate.write_text(script, encoding='utf-8')
                    proc = subprocess.run([node, '--check', str(candidate)], capture_output=True, text=True, encoding='utf-8')
                    script_count += 1
                    if proc.returncode:
                        script_errors.append(dict(file=str(path), error=proc.stderr))
        if node and manifest:
            for name in manifest['files']:
                if name.endswith('.js'):
                    proc = subprocess.run([node, '--check', str(folder/'html_details'/name)], capture_output=True, text=True, encoding='utf-8')
                    script_count += 1
                    if proc.returncode:
                        script_errors.append(dict(file=name, error=proc.stderr))
        missing_resources = [dict(target=target, source=origin) for target, origin in index.execute('SELECT target,source FROM resources')
                             if not Path(target).is_file()]
        checks['html_documents'] = not missing_documents
        checks['local_resources'] = not missing_resources
        absent = index.execute('SELECT COUNT(*) FROM (SELECT id FROM expected_rows EXCEPT SELECT id FROM variable_rows)').fetchone()[0]
        extra = index.execute('SELECT COUNT(*) FROM (SELECT id FROM variable_rows EXCEPT SELECT id FROM expected_rows)').fetchone()[0]
        checks['every_variable_present'] = absent == extra == 0
        result['html'] = dict(documents=len(paths), missing_documents=missing_documents, missing_resources=missing_resources,
                              variables=len(inventory_ids), expected_visible_variables=len(expected_ids),
                              scope='FULL_BUILD' if selected is None else 'CURRENT_GIT_DIFF', absent=absent, extra=extra,
                              javascript_checks=script_count, javascript_errors=script_errors)
        if node:
            checks['javascript_syntax'] = not script_errors
            result['node_version'] = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip()
        if check_json:
            result['json'] = audit_fact_database(folder/'facts.json', source, index)
            checks['json_sqlite_counts'] = not result['json']['differences']
            checks['pointer_pool_integrity'] = result['json']['pools']['error_count'] == 0
            checks['solver_fixed_points'] = result['json']['solver_fixed_points_complete']
        checks['sqlite_integrity'] = source.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    result.update(checks=checks, passed=all(checks.values()), seconds=time.monotonic()-begin,
                  json_executed=check_json, fingerprint=completion.get('fingerprint'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--skip-json', action='store_true')
    parser.add_argument('--javascript', action='store_true')
    args = parser.parse_args()
    node = shutil.which('node') if args.javascript else None
    if args.javascript and node is None:
        parser.error('Node is required for the requested syntax check')
    result = audit(args.folder, check_json=not args.skip_json, node=node)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'], seconds=result['seconds'], output=str(args.output))))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
