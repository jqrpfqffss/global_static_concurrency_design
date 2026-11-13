"""Fast exports transport every byte of published scans and a live review snapshot."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from ecra.human_reviews import ReviewStore
from ecra.operation_progress import OperationCancelled
from ecra.report_package import export_report, import_report, sha256, snapshot
from ecra.scan_store import EvidenceProvider, publish_scan


class SealedExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.scan = self.root/'source'; self.scan.mkdir()
        publish_scan(self.scan/'scan.db', dict(variables=[dict(symbol_id='s', name='g', static_classification='UNKNOWN')],
                     exact=[True, 2**90, -0.0, '中文', ['duplicate', 'duplicate']]),
                     dict(findings=[]), scan_id='sealed', project_id='p')
        self.provider = EvidenceProvider(self.scan/'scan.db'); self.binding = self.provider.validate(deep=True)
        self.reviews = ReviewStore(self.scan/'reviews.db', self.binding)
        self.event = self.reviews.append('s', self.provider.fingerprint('s'), decision='NEED_MORE_EVIDENCE', reviewer='before export')
        self.receipt = dict(self.binding, format='ECRA_LOCAL_SCAN', version=1, state='STATIC_VALIDATED', scan_sha256=sha256(self.provider.path))
        (self.scan/'manifest.json').write_text(json.dumps(self.receipt), encoding='utf-8')
        evidence = self.scan/'evidence'; evidence.mkdir()
        raw = b'complete original evidence bytes\n'
        (evidence/hashlib.sha256(raw).hexdigest()).write_bytes(raw)

    def test_sealed_export_streams_exact_static_bytes_and_new_review_snapshot(self):
        package = self.root/'fast.ecra-report'; stages = []; snapshots = []
        latest = self.reviews.append('s', self.provider.fingerprint('s'), decision='NEED_MORE_EVIDENCE',
                                    reviewer='latest before click', expected_heads=[self.event['event_id']])
        def measured(source, *args, **kwargs):
            snapshots.append(Path(source).name)
            return snapshot(source, *args, **kwargs)
        with patch.object(EvidenceProvider, 'validate', side_effect=AssertionError('published graph was revalidated')), \
                patch('ecra.report_package.snapshot', measured):
            manifest = export_report(self.scan, package, compression='deflate', progress=lambda change: stages.append(change))
        self.assertEqual(snapshots, ['reviews.db'])
        self.assertEqual(manifest['files']['scan.db']['sha256'], self.receipt['scan_sha256'])
        self.assertFalse(any(change.get('stage') in {'VERIFY_GRAPH','VERIFY_PROJECTIONS','SNAPSHOT'} for change in stages))
        with zipfile.ZipFile(package) as zipped:
            self.assertEqual(zipped.read('scan.db'), self.provider.path.read_bytes())
            for name, record in manifest['files'].items():
                self.assertEqual(hashlib.sha256(zipped.read(name)).hexdigest(), record['sha256'])
        target = self.root/'receiver'; import_report(package, target)
        restored = target/'scans/sealed'
        self.assertEqual(EvidenceProvider(restored/'scan.db').load('facts'), self.provider.load('facts'))
        self.assertEqual(ReviewStore(restored/'reviews.db', self.binding).history(), [self.event, latest])
        # A successfully imported local archive has the same byte-bound reuse;
        # the receiving importer above still performed independent deep checks.
        with patch.object(EvidenceProvider, 'validate', side_effect=AssertionError('imported graph was revalidated')):
            export_report(restored, self.root/'again.ecra-report', compression='deflate')

    def test_changed_static_or_cas_bytes_never_publish_a_fast_package(self):
        for part in ('static', 'evidence'):
            with self.subTest(part=part):
                target = self.provider.path if part == 'static' else next((self.scan/'evidence').iterdir())
                before = target.read_bytes()
                try:
                    if part == 'static':
                        with sqlite3.connect(target) as conn:
                            conn.execute("UPDATE scans SET state='STATIC_VALIDATED'")
                    else:
                        target.write_bytes(b'x'*len(before))
                    package = self.root/(part+'.ecra-report')
                    with self.assertRaisesRegex(ValueError, '摘要不一致|证据对象损坏'):
                        export_report(self.scan, package, compression='deflate')
                    self.assertFalse(package.exists())
                    self.assertFalse(list(self.root.glob('ecra export *')))
                    self.assertEqual(self.reviews.history(), [self.event])
                finally:
                    target.write_bytes(before)

    def test_repeat_import_reuses_only_freshly_verified_identical_bytes(self):
        package=self.root/'repeat.ecra-report'; export_report(self.scan,package,compression='deflate')
        target=self.root/'receiver'; import_report(package,target)
        destination=target/'scans/sealed'; calls=[]; validate=EvidenceProvider.validate
        def checked(provider,*args,**kwargs):
            calls.append(provider.path)
            return validate(provider,*args,**kwargs)
        with patch.object(EvidenceProvider,'validate',checked):
            result=import_report(package,target)
        self.assertTrue(result['repeated']);self.assertTrue(result['integrity_verified'])
        self.assertEqual(len(calls),1)  # Incoming bytes independently deep-checked.
        self.assertEqual((destination/'scan.db').read_bytes(),(self.scan/'scan.db').read_bytes())
        # A different physical DB is independently checked, even if the roots
        # match; no publisher or old import receipt can bypass that check.
        with closing(sqlite3.connect(destination/'scan.db')) as conn,conn:
            conn.execute('PRAGMA application_id=123')
        calls.clear()
        with patch.object(EvidenceProvider,'validate',checked): import_report(package,target)
        self.assertEqual(len(calls),2)

    def test_static_read_lock_blocks_writers_but_review_snapshot_stays_consistent(self):
        during = []
        def progress(change):
            if change.get('stage') != 'COMPRESS': return
            with closing(sqlite3.connect(self.provider.path, timeout=.01)) as writer:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    writer.execute("UPDATE scans SET state='STATIC_VALIDATED'"); writer.commit()
                writer.rollback()
            during.append(self.reviews.append('s', self.provider.fingerprint('s'), decision='NEED_MORE_EVIDENCE',
                          reviewer='after snapshot', expected_heads=[self.event['event_id']]))
        package = self.root/'concurrent.ecra-report'
        export_report(self.scan, package, compression='deflate', progress=progress)
        self.assertEqual(len(during), 1)
        import_report(package, self.root/'receiver')
        self.assertEqual(ReviewStore(self.root/'receiver/scans/sealed/reviews.db', self.binding).history(), [self.event])
        self.assertEqual(len(self.reviews.history()), 2)
        self.assertEqual(sha256(self.provider.path), self.receipt['scan_sha256'])

    def test_wal_main_file_is_never_exported_without_its_committed_rows(self):
        with closing(sqlite3.connect(self.provider.path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL'); writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute("UPDATE scans SET state='STATIC_VALIDATED'"); writer.commit()
            self.assertTrue(Path(str(self.provider.path)+'-wal').stat().st_size)
            stages = []; package = self.root/'wal.ecra-report'
            export_report(self.scan, package, compression='deflate', progress=lambda change: stages.append(change))
            self.assertTrue(any(change.get('stage') == 'VERIFY_GRAPH' for change in stages))
            import_report(package, self.root/'receiver')
            self.assertEqual(EvidenceProvider(self.root/'receiver/scans/sealed/scan.db').metadata()['state'], 'STATIC_VALIDATED')

    def test_unknown_receipt_keeps_deep_checks_and_identity_mismatch_is_rejected(self):
        manifest = self.scan/'manifest.json'
        self.receipt['project_id'] = 'wrong'; manifest.write_text(json.dumps(self.receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '身份'):
            export_report(self.scan, self.root/'identity.ecra-report')
        manifest.unlink()
        with sqlite3.connect(self.provider.path) as conn:
            conn.execute("UPDATE symbols SET static_classification='SAFE_PROVEN'")
        with self.assertRaisesRegex(ValueError, '投影'):
            export_report(self.scan, self.root/'unsealed.ecra-report')

    def test_unknown_schema_is_rejected_before_reading_a_replaced_metadata_view(self):
        with sqlite3.connect(self.provider.path) as conn:
            conn.execute('ALTER TABLE scans RENAME TO real_scans')
            conn.execute("CREATE VIEW scans AS SELECT load_extension('never-run')")
        with self.assertRaisesRegex(ValueError, '结构'):
            export_report(self.scan, self.root/'malicious.ecra-report')

    def test_cancelling_a_sealed_stream_releases_read_lock_and_never_publishes(self):
        stage = [None]; package = self.root/'cancelled.ecra-report'
        def progress(change):
            stage[0] = change.get('stage', stage[0])
            if stage[0] == 'COMPRESS' and change.get('completed', 0):
                raise OperationCancelled('stop actual sealed stream')
        with self.assertRaises(OperationCancelled):
            export_report(self.scan, package, compression='deflate', progress=progress)
        self.assertFalse(package.exists())
        self.assertFalse(list(self.root.glob('ecra export *')))
        self.assertEqual(sha256(self.provider.path), self.receipt['scan_sha256'])
        self.assertEqual(self.reviews.history(), [self.event])
        with closing(sqlite3.connect(self.provider.path, timeout=.01)) as writer:
            writer.execute('BEGIN EXCLUSIVE'); writer.rollback()


if __name__ == '__main__': unittest.main()
