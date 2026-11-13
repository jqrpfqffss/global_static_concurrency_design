"""Slow archive export must not occupy an HTTP request or lose its result."""
import errno
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ecra.human_reviews import ReviewStore
from ecra.operation_progress import OperationCancelled, sqlite_progress
from ecra.report_package import export_report, import_report, sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.storage_activity import DataActivity, DataBusy
from ecra.studio.export_jobs import ExportJobs
from ecra.studio.server import create_app


class ExportJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.data = self.root/'data'
        self.scan = self.data/'scans'/'scan'; self.scan.mkdir(parents=True)
        publish_scan(self.scan/'scan.db', dict(variables=[dict(symbol_id='s', name='counter', static_classification='UNKNOWN')]),
                     dict(findings=[]), scan_id='scan', project_id='project')
        self.provider = EvidenceProvider(self.scan/'scan.db')
        self.reviews = ReviewStore(self.scan/'reviews.db', self.provider.metadata())
        self.event = self.reviews.append('s', self.provider.fingerprint('s'), decision='NEED_MORE_EVIDENCE', reviewer='export test', comment='keep full history')
        self.app = create_app(self.data, token='test', authority='127.0.0.1:12345')
        self.client = TestClient(self.app, base_url='http://127.0.0.1:12345',
                                 headers={'X-ECRA-Session':'test', 'Origin':'http://127.0.0.1:12345'})
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def start(self, **payload):
        response = self.client.post('/api/scans/scan/export-jobs', json=payload)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def finish(self, ident):
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            job = self.client.get('/api/export-jobs/'+ident).json()
            if job['state'] not in {'RUNNING','CANCELLING'}:
                return job
            time.sleep(.03)
        self.fail('export did not finish')

    def test_slow_export_returns_immediately_survives_new_view_and_roundtrips(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set(); self.assertTrue(release.wait(10))
            return export_report(*args, **kwargs)
        with patch('ecra.studio.export_jobs.export_report', slow):
            try:
                started = time.monotonic(); job = self.start(kind='full')
                self.assertLess(time.monotonic()-started, 2)
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.client.get('/api/export-jobs').json()['items'][0]['id'], job['id'])
                self.assertEqual(self.client.get('/api/scans').status_code, 200)
                self.assertEqual(self.start(kind='full')['id'], job['id'])
                other_view = ExportJobs(self.data)
                self.assertEqual(other_view.get(job['id'])['state'], 'RUNNING')
                with self.assertRaises(DataBusy):
                    with DataActivity(self.data, exclusive=True): pass
                other = self.client.post('/api/scans/scan/export-jobs', json=dict(kind='full',compression='compact'))
                self.assertEqual(other.status_code, 400)
            finally:
                release.set()
            result = self.finish(job['id']); self.assertEqual(result['state'], 'COMPLETE', result)
        self.assertEqual(result['result']['compression'], 'deflate')
        package = self.data/'exports'/result['result']['filename']
        import_report(package, self.root/'other-computer')
        restored = self.root/'other-computer/scans/scan'
        self.assertEqual(EvidenceProvider(restored/'scan.db').metadata(), self.provider.metadata())
        self.assertEqual(ReviewStore(restored/'reviews.db', self.provider.metadata()).history(), [self.event])
        self.assertEqual(ExportJobs(self.data).get(job['id'])['result'], result['result'])
        with DataActivity(self.data, exclusive=True): pass
        grant = self.client.post(result['result']['download']+'/ticket').json()
        self.assertEqual(self.client.get(grant['download']).content, package.read_bytes())

    def test_cancel_cleans_private_partial_and_keeps_original(self):
        entered, release = threading.Event(), threading.Event()
        original = {name:sha256(self.scan/name) for name in ('scan.db','reviews.db')}
        def slow(*args, **kwargs):
            progress = kwargs['progress']
            def at_snapshot(change):
                if change.get('stage') == 'SNAPSHOT':
                    entered.set(); self.assertTrue(release.wait(10))
                progress(change)
            kwargs['progress'] = at_snapshot
            return export_report(*args, **kwargs)
        with patch('ecra.studio.export_jobs.export_report', slow):
            try:
                job = self.start(); self.assertTrue(entered.wait(2))
                response = self.client.post('/api/export-jobs/'+job['id']+'/cancel')
                self.assertEqual(response.json()['state'], 'CANCELLING')
            finally:
                release.set()
            self.assertEqual(self.finish(job['id'])['state'], 'CANCELLED')
        self.assertEqual(list((self.data/'exports').iterdir()), [])
        self.assertEqual(original, {name:sha256(self.scan/name) for name in original})
        with DataActivity(self.data, exclusive=True): pass

    def test_failure_is_durable_and_stale_running_job_recovers(self):
        with patch('ecra.studio.export_jobs.export_report', side_effect=OSError(errno.ENOSPC,'disk full')):
            job = self.start(); failed = self.finish(job['id'])
        self.assertEqual(failed['state'], 'FAILED'); self.assertIn('disk full', failed['error'])
        self.assertFalse((self.data/'exports'/(job['id']+'.ecra-report')).exists())
        jobs = self.app.state.export_jobs
        with jobs.connect() as conn:
            job.update(state='RUNNING'); jobs.save(conn, job)
        restarted = ExportJobs(self.data)
        self.assertEqual(restarted.get(job['id'])['state'], 'INTERRUPTED')

    def test_authentication_and_bad_requests_do_not_launch_jobs(self):
        path = '/api/scans/scan/export-jobs'
        self.assertEqual(self.client.post(path,json={},headers={'X-ECRA-Session':''}).status_code,401)
        self.assertEqual(self.client.post(path,json={},headers={'Origin':'http://other.invalid'}).status_code,403)
        for payload in [dict(kind=[]),dict(kind='other'),dict(compression='other'),dict(compression=[])]:
            self.assertEqual(self.client.post(path,json=payload).status_code,400)
        self.assertEqual(self.client.get('/api/export-jobs').json()['items'],[])

    def test_sqlite_work_can_be_cancelled_during_one_long_statement(self):
        def stop(_): raise OperationCancelled('cancelled')
        with sqlite3.connect(':memory:') as conn:
            with self.assertRaises(OperationCancelled), sqlite_progress(conn, stop):
                conn.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000000) SELECT sum(x) FROM n').fetchone()
            self.assertEqual(conn.execute('SELECT 1').fetchone(), (1,))

    def test_cancel_during_compression_never_publishes_a_partial_archive(self):
        stage = [None]; compressed = []
        def progress(change):
            stage[0] = change.get('stage', stage[0])
            if stage[0] == 'COMPRESS' and change.get('completed', 0):
                compressed.append(change['completed'])
                raise OperationCancelled('cancel mid-stream')
        target = self.root/'cancelled.ecra-report'
        with self.assertRaises(OperationCancelled):
            export_report(self.scan, target, compression='deflate', progress=progress)
        self.assertTrue(compressed)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('ecra export *')))
        self.assertEqual(self.reviews.history(), [self.event])

    def test_sqlite_heartbeat_runs_even_inside_a_single_long_opcode(self):
        cancel = threading.Event()
        def stop(_):
            cancel.set()
            raise OperationCancelled('cancel single opcode')
        with sqlite3.connect(':memory:') as conn:
            # A single UDF opcode models integrity_check's long internal loop:
            # no instruction-count callback can run while it is executing.
            conn.create_function('blocking_opcode', 0, lambda: int(cancel.wait(3)))
            with self.assertRaises(OperationCancelled), sqlite_progress(conn, stop):
                conn.execute('SELECT blocking_opcode()').fetchone()
            self.assertTrue(cancel.is_set())


if __name__ == '__main__': unittest.main()
