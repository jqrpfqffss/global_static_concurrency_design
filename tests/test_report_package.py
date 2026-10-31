import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report, import_report, export_delta, import_delta
from ecra.scan_store import publish_scan, EvidenceProvider


class ReportPackageTests(unittest.TestCase):
    def test_mutating_a_later_convenience_receipt_cannot_mutate_archived_object(self):
        from ecra.scan_persistence import archive_audit
        from ecra.report_package import sha256
        folder=self.scan/'review';folder.mkdir()
        source=folder/'latest.prompt.txt';source.write_text('original immutable receipt',encoding='utf-8')
        before=sha256(source)
        archive_audit(self.scan)
        source.write_text('new review overwrote the convenience name',encoding='utf-8')
        self.assertEqual(sha256(self.scan/'evidence'/before),before)
        self.assertEqual((self.scan/'evidence'/before).read_text(encoding='utf-8'),'original immutable receipt')
        archive_audit(self.scan)
        self.assertEqual(sha256(self.scan/'evidence'/before),before)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra 包 中文 ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.scan = self.base/'source'; self.scan.mkdir()
        publish_scan(self.scan/'scan.db', dict(variables=[dict(symbol_id='s', name='g', static_classification='UNKNOWN')],
            future_evidence=['<script>alert(1)</script>', [1, 1, True, -0.0]]), dict(findings=[]), scan_id='scan-1', project_id='project-1')
        self.provider = EvidenceProvider(self.scan/'scan.db')
        self.binding = self.provider.validate()
        self.reviews = ReviewStore(self.scan/'reviews.db', self.binding)
        self.event = self.reviews.append('s', self.provider.fingerprint('s'), decision='CONFIRMED_SAFE', reviewer='声明工程师', comment='依据引用')
        self.package = self.base/'完整结果.ecra-report'
        export_report(self.scan, self.package)

    def test_complete_package_offline_roundtrip_can_continue_and_reexport(self):
        target = self.base/'第二电脑'
        self.assertFalse((target/'scans').exists())
        result = import_report(self.package, target)
        dest = target/'scans/scan-1'
        other = EvidenceProvider(dest/'scan.db')
        self.assertEqual(other.load('facts'), self.provider.load('facts'))
        reviews = ReviewStore(dest/'reviews.db', other.validate())
        reviews.append('s', other.fingerprint('s'), decision='CONFIRMED_RISK', reviewer='另一电脑声明', comment='新依据', expected_heads=[self.event['event_id']])
        second = self.base/'再导出.ecra-report'; export_report(dest, second)
        import_report(second, self.base/'第三电脑')
        third = ReviewStore(self.base/'第三电脑/scans/scan-1/reviews.db', self.binding)
        self.assertEqual(len(third.history()), 2)
        self.assertEqual(third.current('s', other.fingerprint('s'))['decision'], 'CONFIRMED_RISK')
        self.assertTrue(import_report(self.package, target)['repeated'])
        self.assertEqual(len(reviews.history()), 2)

    def test_delta_repeated_import_does_not_erase_offline_conflict(self):
        target = self.base/'other'
        import_report(self.package, target)
        other = target/'scans/scan-1'
        a = self.reviews.append('s', self.provider.fingerprint('s'), decision='CONFIRMED_RISK', reviewer='A', expected_heads=[self.event['event_id']])
        bstore = ReviewStore(other/'reviews.db', self.binding)
        bstore.append('s', self.provider.fingerprint('s'), decision='NEED_MORE_EVIDENCE', reviewer='B', expected_heads=[self.event['event_id']])
        delta = self.base/'人工.ecra-review-delta'; export_delta(self.scan, delta)
        self.assertEqual(import_delta(delta, other)['imported_events'], 1)
        self.assertEqual(import_delta(delta, other)['imported_events'], 0)
        self.assertTrue(bstore.current('s', self.provider.fingerprint('s'))['conflict'])

    def test_zip_slip_duplicate_symlink_and_bomb_rejected_without_publication(self):
        import stat
        for case in ('../escape', 'duplicate', 'link', 'bomb'):
            package = self.base/(case.replace('/', '_')+'.zip')
            with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
                if case == 'link':
                    info = zipfile.ZipInfo('scan.db'); info.external_attr = (stat.S_IFLNK | 0o777)<<16
                    zipped.writestr(info, 'outside')
                elif case == 'duplicate':
                    zipped.writestr('scan.db', 'a'); zipped.writestr('SCAN.DB', 'b')
                elif case == 'bomb':
                    zipped.writestr('scan.db', '0'*200000)
                else:
                    zipped.writestr(case, 'evil')
            target = self.base/('bad-'+case.replace('/', '_'))
            with self.assertRaises(ValueError):
                import_report(package, target, max_bytes=100000)
            self.assertFalse((target/'scans').exists())
        self.assertFalse((self.base/'escape').exists())

    def test_tampered_hash_or_unknown_schema_cannot_change_valid_archive(self):
        target = self.base/'valid'; import_report(self.package, target)
        before = (target/'scans/scan-1/scan.db').read_bytes()
        bad = self.base/'tampered.zip'
        with zipfile.ZipFile(self.package) as zipped, zipfile.ZipFile(bad, 'w') as out:
            for name in zipped.namelist():
                data = zipped.read(name)
                if name == 'manifest.json':
                    manifest = json.loads(data); manifest['schema_version'] = 999
                    data = json.dumps(manifest).encode()
                out.writestr(name, data)
        with self.assertRaisesRegex(ValueError, '版本'):
            import_report(bad, target)
        self.assertEqual((target/'scans/scan-1/scan.db').read_bytes(), before)

    def test_unknown_sql_trigger_rejected_before_any_writable_open(self):
        with sqlite3.connect(self.scan/'scan.db') as conn:
            conn.execute('CREATE VIEW malicious AS SELECT load_extension(\'evil\')')
        bad = self.base/'sql.zip'
        with zipfile.ZipFile(self.package) as zipped, zipfile.ZipFile(bad, 'w') as out:
            manifest = json.loads(zipped.read('manifest.json'))
            data = (self.scan/'scan.db').read_bytes()
            manifest['files']['scan.db'] = dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            out.writestr('manifest.json', json.dumps(manifest))
            out.writestr('scan.db', data)
            out.writestr('reviews.db', zipped.read('reviews.db'))
        with self.assertRaisesRegex(ValueError, '结构'):
            import_report(bad, self.base/'sql-target')

    def test_export_does_not_overwrite_existing_package(self):
        before = self.package.read_bytes()
        with self.assertRaises(FileExistsError):
            export_report(self.scan, self.package)
        self.assertEqual(self.package.read_bytes(), before)
