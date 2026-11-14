"""Import requests release the browser, retain progress and publish only valid data."""
import errno
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from ecra.human_reviews import ReviewStore
from ecra.operation_progress import OperationCancelled
from ecra.report_package import export_report, import_report, sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.storage_activity import DataActivity, DataBusy
from ecra.studio.import_jobs import ImportJobs, MAX_UPLOAD_BYTES, UploadDisconnected
from ecra.studio.server import create_app


class ImportJobTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.data = self.root/'receiver'
        self.scan = self.root/'sender/scans/scan'; self.scan.mkdir(parents=True)
        publish_scan(self.scan/'scan.db', dict(variables=[dict(symbol_id='s', name='counter', static_classification='UNKNOWN')]),
                     dict(findings=[]), scan_id='scan', project_id='project')
        self.provider = EvidenceProvider(self.scan/'scan.db')
        self.reviews = ReviewStore(self.scan/'reviews.db', self.provider.metadata())
        self.event = self.reviews.append('s', self.provider.fingerprint('s'), decision='NEED_MORE_EVIDENCE',
                                         reviewer='import test', comment='preserve complete human history')
        self.package = self.root/'valid.ecra-report'; export_report(self.scan, self.package, compression='deflate')
        self.app = create_app(self.data, token='test', authority='127.0.0.1:12345')
        self.jobs = self.app.state.import_jobs
        self.client = TestClient(self.app, base_url='http://127.0.0.1:12345',
                                 headers={'X-ECRA-Session':'test', 'Origin':'http://127.0.0.1:12345'})
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def start(self, content=None, **headers):
        response = self.client.post('/api/import-jobs', content=self.package.read_bytes() if content is None else content,
                                    headers={'X-Filename':quote('完整结果.ecra-report'), **headers})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def finish(self, ident):
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            job = self.client.get('/api/import-jobs/'+ident).json()
            if job['state'] not in {'UPLOADING','RUNNING','CANCELLING'}:
                # Terminal state is durable before lease cleanup finishes.
                for thread in list(self.jobs.threads): thread.join(timeout=2)
                return job
            time.sleep(.03)
        self.fail('import did not finish')

    def test_returns_before_validation_refresh_retains_progress_and_manual_history(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            kwargs['progress'](dict(stage='VERIFY_DATABASE', message='校验数据库', completed=1, total=5, unit='items'))
            entered.set(); self.assertTrue(release.wait(10))
            return import_report(*args, **kwargs)
        with patch('ecra.studio.import_jobs.import_report', slow):
            try:
                before = time.monotonic(); job = self.start(**{'X-Upload-Id':'a'*32})
                self.assertLess(time.monotonic()-before, 2)
                self.assertEqual(job['id'], 'a'*32)
                self.assertEqual(job['filename'], '完整结果.ecra-report')
                self.assertTrue(entered.wait(2))
                restored_view = ImportJobs(self.data)
                self.assertEqual(restored_view.get(job['id'])['stage'], 'VERIFY_DATABASE')
                self.assertEqual(self.client.get('/api/import-jobs').json()['items'][0]['id'], job['id'])
                self.assertEqual(self.client.get('/api/scans').status_code, 200)
                self.assertFalse((self.data/'scans/scan').exists())
                self.assertEqual(self.client.post('/api/import-jobs',content=b'blocked').status_code,400)
                with self.assertRaises(DataBusy):
                    with DataActivity(self.data, exclusive=True): pass
            finally:
                release.set()
            completed = self.finish(job['id'])
        self.assertEqual(completed['state'],'COMPLETE',completed)
        self.assertTrue(completed['result']['integrity_verified'])
        self.assertEqual(completed['result']['imported_events'],1)
        target = self.data/'scans/scan'
        with zipfile.ZipFile(self.package) as archive:
            self.assertEqual(sha256(target/'scan.db'), hashlib.sha256(archive.read('scan.db')).hexdigest())
        reviews = ReviewStore(target/'reviews.db', self.provider.metadata())
        self.assertEqual(reviews.history(),[self.event])
        reviews.append('s',self.provider.fingerprint('s'),reviewer='other computer',decision='NEED_MORE_EVIDENCE',
                       expected_heads=[self.event['event_id']],comment='continue after import')
        self.assertEqual(len(reviews.history()),2)
        self.assertEqual(ImportJobs(self.data).get(job['id'])['result'],completed['result'])
        self.assertEqual(list(self.jobs.uploads.iterdir()),[])
        with DataActivity(self.data,exclusive=True): pass

    def test_cancel_during_validation_removes_upload_without_publication(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set(); self.assertTrue(release.wait(10))
            kwargs['progress'](dict(stage='VERIFY_DATABASE',message='校验数据库'))
            self.fail('cancel should raise before publication')
        with patch('ecra.studio.import_jobs.import_report',slow):
            try:
                job=self.start();self.assertTrue(entered.wait(2))
                self.assertEqual(self.client.post('/api/import-jobs/'+job['id']+'/cancel').json()['state'],'CANCELLING')
            finally:release.set()
            self.assertEqual(self.finish(job['id'])['state'],'CANCELLED')
        self.assertFalse((self.data/'scans/scan').exists())
        self.assertEqual(self.reviews.history(),[self.event])
        self.assertEqual(list(self.jobs.uploads.iterdir()),[])
        with DataActivity(self.data,exclusive=True):pass

    def test_upload_cancel_and_disconnect_release_private_files_and_locks(self):
        upload=self.jobs.begin_upload('pending.ecra-report',10)
        upload.path.write_bytes(b'partial')
        self.jobs.cancel(upload.item['id'])
        with self.assertRaises(OperationCancelled):self.jobs.upload_progress(upload,7,force=True)
        self.jobs.abort_upload(upload,OperationCancelled('browser disconnected'))
        self.assertEqual(self.jobs.get(upload.item['id'])['state'],'CANCELLED')
        self.assertFalse(upload.path.parent.exists())
        with DataActivity(self.data,exclusive=True):pass

    def test_explicit_upload_cancel_survives_following_socket_disconnect(self):
        upload=self.jobs.begin_upload('cancelled.ecra-report',10)
        upload.path.write_bytes(b'partial')
        self.jobs.cancel(upload.item['id'])
        self.jobs.abort_upload(upload,UploadDisconnected('上传连接已断开，请重新选择完整结果包'))
        result=self.jobs.get(upload.item['id'])
        self.assertEqual(result['state'],'CANCELLED')
        self.assertIn('已取消导入上传',result['error'])
        self.assertNotIn('连接已断开',result['error'])
        self.assertFalse(upload.path.parent.exists())
        self.assertFalse((self.data/'scans/scan').exists())
        with DataActivity(self.data,exclusive=True):pass

    def test_unrequested_upload_disconnect_remains_failure(self):
        upload=self.jobs.begin_upload('disconnected.ecra-report',10)
        upload.path.write_bytes(b'partial')
        self.jobs.abort_upload(upload,UploadDisconnected('上传连接已断开，请重新选择完整结果包'))
        result=self.jobs.get(upload.item['id'])
        self.assertEqual(result['state'],'FAILED')
        self.assertIn('连接已断开',result['error'])
        self.assertFalse(upload.path.parent.exists())
        self.assertFalse((self.data/'scans/scan').exists())
        with DataActivity(self.data,exclusive=True):pass

    def test_http_upload_disconnect_uses_persisted_cancel_intent(self):
        for requested in (False,True):
            with self.subTest(requested=requested):
                ident=('c' if requested else 'd')*32
                async def interrupted_stream(request):
                    yield b'partial'
                    if requested:self.jobs.cancel(ident)
                    raise ClientDisconnect()
                with patch('starlette.requests.Request.stream',interrupted_stream):
                    response=self.client.post('/api/import-jobs',content=b'incomplete',
                                              headers={'X-Upload-Id':ident})
                self.assertEqual(response.status_code,400,response.text)
                result=self.jobs.get(ident)
                self.assertEqual(result['state'],'CANCELLED' if requested else 'FAILED')
                self.assertIn('已取消导入上传' if requested else '连接已断开',result['error'])
                self.assertEqual(list(self.jobs.uploads.iterdir()),[])
                self.assertFalse((self.data/'scans/scan').exists())
                with DataActivity(self.data,exclusive=True):pass

    def test_cancel_intent_does_not_hide_upload_validation_or_disk_failure(self):
        for error in (ValueError('上传长度与结果包声明不一致'),OSError(errno.ENOSPC,'disk full')):
            with self.subTest(error=error):
                upload=self.jobs.begin_upload('invalid.ecra-report',10)
                upload.path.write_bytes(b'partial')
                self.jobs.cancel(upload.item['id'])
                self.jobs.abort_upload(upload,error)
                result=self.jobs.get(upload.item['id'])
                self.assertEqual(result['state'],'FAILED')
                self.assertIn(str(error),result['error'])
                self.assertFalse(upload.path.parent.exists())
                with DataActivity(self.data,exclusive=True):pass

    def test_late_upload_abort_preserves_terminal_result(self):
        for requested in (False,True):
            with self.subTest(requested=requested):
                upload=self.jobs.begin_upload('late.ecra-report',10)
                upload.path.write_bytes(b'partial')
                if requested:self.jobs.cancel(upload.item['id'])
                self.jobs.abort_upload(upload,UploadDisconnected('connection lost'))
                original=self.jobs.get(upload.item['id'])
                self.jobs.abort_upload(upload,ValueError('late unrelated error'))
                self.assertEqual(self.jobs.cancel(upload.item['id']),original)
                self.assertEqual(self.jobs.get(upload.item['id']),original)
                with DataActivity(self.data,exclusive=True):pass

    def test_service_stop_reason_survives_upload_cleanup(self):
        upload=self.jobs.begin_upload('stopped.ecra-report',10)
        reason='服务退出，导入上传已停止；已有扫描与人工记录保留。'
        self.jobs.abort_upload(upload,OperationCancelled(reason))
        result=self.jobs.get(upload.item['id'])
        self.assertEqual(result['state'],'CANCELLED')
        self.assertEqual(result['error'],reason)

    def test_late_abort_cannot_replace_a_published_import(self):
        content=self.package.read_bytes()
        upload=self.jobs.begin_upload('published.ecra-report',len(content))
        upload.path.write_bytes(content)
        self.jobs.finish_upload(upload,len(content))
        original=self.finish(upload.item['id'])
        self.assertEqual(original['state'],'COMPLETE')
        self.jobs.abort_upload(upload,UploadDisconnected('late browser disconnect'))
        self.assertEqual(self.jobs.get(upload.item['id']),original)
        self.assertTrue((self.data/'scans/scan/scan.db').is_file())
        self.assertEqual(ReviewStore(self.data/'scans/scan/reviews.db',self.provider.metadata()).history(),[self.event])

    def test_bad_zip_failure_and_stale_upload_recovery_are_durable(self):
        job=self.start(b'PK invalid archive')
        failed=self.finish(job['id']);self.assertEqual(failed['state'],'FAILED')
        self.assertEqual(failed['code'],'INVALID_REPORT_ARCHIVE')
        self.assertIn('本次未发布',failed['error'])
        upload=self.jobs.begin_upload('interrupted.ecra-report')
        upload.path.write_bytes(b'partial');upload.leases.close()
        restarted=ImportJobs(self.data)
        self.assertEqual(restarted.get(upload.item['id'])['state'],'INTERRUPTED')
        original=restarted.get(upload.item['id'])
        self.jobs.abort_upload(upload,UploadDisconnected('late old connection cleanup'))
        self.assertEqual(restarted.get(upload.item['id']),original)
        self.assertFalse(upload.path.parent.exists())
        self.assertFalse((self.data/'scans/scan').exists())

    def test_disk_error_is_saved_and_upload_removed(self):
        with patch('ecra.studio.import_jobs.import_report',side_effect=OSError(errno.ENOSPC,'disk full')):
            failed=self.finish(self.start()['id'])
        self.assertEqual(failed['state'],'FAILED');self.assertIn('disk full',failed['error'])
        self.assertEqual(list(self.jobs.uploads.iterdir()),[])

    def test_service_close_cancels_worker_and_releases_data_root(self):
        entered=threading.Event()
        def until_stopped(*args,**kwargs):
            entered.set()
            while True:
                kwargs['progress']({})
                time.sleep(.02)
        with patch('ecra.studio.import_jobs.import_report',until_stopped):
            job=self.start();self.assertTrue(entered.wait(2))
            before=time.monotonic();self.jobs.close()
            self.assertLess(time.monotonic()-before,2)
            self.assertEqual(self.jobs.get(job['id'])['state'],'CANCELLED')
        self.assertEqual(list(self.jobs.uploads.iterdir()),[])
        self.assertFalse((self.data/'scans/scan').exists())
        with DataActivity(self.data,exclusive=True):pass

    def test_upload_flush_failure_removes_private_file_and_releases_data_root(self):
        with patch('os.fsync',side_effect=OSError(errno.ENOSPC,'disk full while flushing upload')):
            response=self.client.post('/api/import-jobs',content=self.package.read_bytes())
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(self.jobs.history()['items'][0]['state'],'FAILED')
        self.assertEqual(list(self.jobs.uploads.iterdir()),[])
        with DataActivity(self.data,exclusive=True):pass

    def test_existing_job_id_does_not_replace_history_or_its_uploaded_file(self):
        upload=self.jobs.begin_upload('original.ecra-report',ident='b'*32)
        upload.path.write_bytes(b'partial')
        self.jobs.abort_upload(upload,OperationCancelled('cancel fixture'))
        original=self.jobs.get(upload.item['id'])
        with self.assertRaisesRegex(ValueError,'已存在'):
            self.jobs.begin_upload('new.ecra-report',ident='b'*32)
        self.assertEqual(self.jobs.get(upload.item['id']),original)
        self.assertEqual(list(self.jobs.uploads.iterdir()),[])

    def test_authentication_input_limits_and_identifiers_cannot_create_jobs(self):
        self.assertEqual(self.client.post('/api/import-jobs',content=b'',headers={'X-ECRA-Session':''}).status_code,401)
        self.assertEqual(self.client.post('/api/import-jobs',content=b'',headers={'Origin':'http://other.invalid'}).status_code,403)
        for headers in ({'Content-Length':str(MAX_UPLOAD_BYTES+1)},{'Content-Length':'invalid'},
                        {'X-Upload-Id':'../elsewhere'},{'X-Filename':'x'*4097}):
            self.assertEqual(self.client.post('/api/import-jobs',content=b'',headers=headers).status_code,400)
        self.assertEqual(self.client.get('/api/import-jobs').json()['items'],[])
        self.assertEqual(list(self.jobs.uploads.iterdir()),[])

    def test_existing_malformed_manifest_is_not_merged(self):
        imported=import_report(self.package,self.data)
        target=self.data/'scans'/imported['scan_id'];manifest=target/'manifest.json'
        manifest.write_text('[]',encoding='utf-8')
        original={name:sha256(target/name) for name in ('scan.db','reviews.db')}
        failed=self.finish(self.start()['id'])
        self.assertEqual(failed['state'],'FAILED');self.assertIn('新的独立数据目录',failed['error'])
        self.assertEqual(manifest.read_text(encoding='utf-8'),'[]')
        self.assertEqual({name:sha256(target/name) for name in original},original)


if __name__ == '__main__':unittest.main()
