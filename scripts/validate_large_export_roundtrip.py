"""Validate an actual exported firmware archive in a separate offline data root.

Does not rescan firmware or invoke any AI review. The production importer checks
every payload hash, graph node, projection and review event before publication.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecra.human_reviews import ReviewStore
from ecra.report_package import import_report, sha256
from ecra.scan_store import EvidenceProvider, connect_readonly
from ecra.studio.source_view import source_window


def roots(path):
    with closing(connect_readonly(path)) as conn:
        return [tuple(row) for row in conn.execute(
            'SELECT r.name,n.kind,n.hash,n.length FROM roots r JOIN nodes n ON r.node=n.id ORDER BY r.name')]


def review_rows(path):
    result = {}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        for table in ('binding', 'events', 'predecessors', 'ai_events', 'ai_snapshots', 'prior_decisions'):
            digest = hashlib.sha256(); count = 0
            columns = len(conn.execute('PRAGMA table_info('+table+')').fetchall())
            for row in conn.execute('SELECT * FROM '+table+' ORDER BY '+','.join(str(i+1) for i in range(columns))):
                digest.update(json.dumps(row, ensure_ascii=True, separators=(',',':')).encode()); digest.update(b'\n'); count += 1
            result[table] = dict(rows=count, sha256=digest.hexdigest())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'package', 'data-root', 'result'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--completed-job', type=Path,
        help='Verify a completed real UI import from the recorded durable job, without importing twice')
    args = parser.parse_args()
    result = dict(passed=False, source=str(args.source), package=str(args.package), destination=str(args.data_root),
                  scope='Existing real firmware scan; independent local data root, not a physical second computer; no rescan or AI review')
    def save():
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    try:
        if args.data_root.exists() and not args.completed_job:
            raise ValueError('Use a fresh destination to demonstrate independent import')
        source = EvidenceProvider(args.source/'scan.db'); binding = source.metadata()
        result.update(binding=binding, source_roots=roots(source.path), review_tables_before=review_rows(args.source/'reviews.db'))
        with zipfile.ZipFile(args.package) as package:
            manifest = json.loads(package.read('manifest.json'))
            result['payload_files'] = len(manifest['files'])
        save(); print('Importing complete package through production importer', flush=True)
        started = time.monotonic()
        last_progress = [0.0]
        def progress(change):
            if change.get('validated_task'):
                result.setdefault('validation_tasks', []).append(change['validated_task'])
                save()
            if change.get('stage') and change['stage'] != result.get('validation_stage'):
                result['validation_stage'] = change['stage']
                result.setdefault('validation_stages', []).append(dict(stage=change['stage'], seconds=round(time.monotonic()-started, 3)))
                save()
                print('Import: '+change['message'], flush=True)
            if change and time.monotonic()-last_progress[0] >= 5:
                result['progress'] = change
                last_progress[0] = time.monotonic(); save()
        if args.completed_job:
            receipt = json.loads(args.completed_job.read_text(encoding='utf-8'))
            job = receipt['job']
            assert job['state']=='COMPLETE' and job['result']['integrity_verified']
            imported=job['result']
            assert imported['scan_id']==manifest['scan_id'] and not imported['repeated']
            result.update(import_seconds=job['elapsed_seconds'], timing_includes_browser_upload=True,
                          validation_stages=receipt['stages'], validation_tasks=job.get('validated_tasks'),
                          completed_job=str(args.completed_job))
        else:
            imported = import_report(args.package, args.data_root, progress=progress)
            result['import_seconds'] = round(time.monotonic()-started, 3)
        result['import_result'] = imported
        result['validation_stage'] = 'COMPARE_RESTORED_DATA'; save()
        destination = args.data_root/'scans'/imported['scan_id']; restored = EvidenceProvider(destination/'scan.db')
        assert restored.metadata() == binding
        assert roots(restored.path) == result['source_roots']
        result['review_tables_after'] = review_rows(destination/'reviews.db')
        assert result['review_tables_after'] == result['review_tables_before']
        source_objects = {path.name for path in (args.source/'evidence').iterdir()}
        restored_objects = {path.name for path in (destination/'evidence').iterdir()}
        assert source_objects <= restored_objects
        for name in restored_objects:
            assert sha256(destination/'evidence'/name)==name
            if name in source_objects: assert sha256(args.source/'evidence'/name)==name
        result['evidence_bytes_verified']=True
        result.update(evidence_objects=len(restored_objects), symbols=restored.symbols(limit=1)['total'],
                      package_bytes=args.package.stat().st_size, package_sha256=sha256(args.package),
                      restored_database_sha256=sha256(restored.path), source_database_sha256=sha256(source.path))
        assert result['restored_database_sha256'] == manifest['files']['scan.db']['sha256']
        result['database_byte_equal'] = result['restored_database_sha256'] == result['source_database_sha256']
        assert result['database_byte_equal']
        original_manifest = args.source/'manifest.json'
        if original_manifest.is_file():
            recorded = json.loads(original_manifest.read_text('utf-8')).get('scan_sha256')
            if recorded:
                assert result['source_database_sha256'] == recorded
                result['source_matches_original_scan_receipt'] = True
        # Display archived source without the original firmware tree.
        candidates = restored.symbols(classification='UNKNOWN', limit=200)['items'] or restored.symbols(limit=200)['items']
        symbol = next(row for row in candidates if row.get('definition_file'))
        window = source_window(restored, symbol['definition_file'], line=symbol.get('definition_line') or 1)
        assert window['available'] and window['lines']
        assert not window['ide']['available']
        result['archived_source_window'] = window
        reviews = ReviewStore(destination/'reviews.db', binding)
        previous = reviews.history(); fingerprint = restored.fingerprint(symbol['symbol_id'])
        event = reviews.append(symbol['symbol_id'], fingerprint, decision='NEED_MORE_EVIDENCE',
            reviewer='isolated offline export acceptance', comment='Continue investigation after import; software test only.',
            expected_heads=[head['event_id'] for head in reviews.current(symbol['symbol_id'], fingerprint)['heads']])
        after = reviews.history()
        assert len(after) == len(previous)+1 and event in after and all(row in after for row in previous)
        result.update(continued_review_event=event, original_events_preserved=len(previous),
                      passed=True, validation_stage='COMPLETE')
        save(); print('PASS: complete evidence, reviews, archived source and continued confirmation', flush=True)
    except BaseException as exc:
        result['error'] = repr(exc); save(); raise


if __name__ == '__main__':
    main()
