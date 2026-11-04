"""Whole-root transfer must preserve evidence and refuse ambiguous publication."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256,export_report,import_report
from ecra.scan_store import publish_scan,EvidenceProvider
from ecra.storage_activity import DataActivity


class DataTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra 整套搬迁 ')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'原始 数据'
        self.target=self.base/'新数据 目标'
        self.folder=self.source/'scans/one';self.folder.mkdir(parents=True)
        publish_scan(self.folder/'scan.db',dict(variables=[dict(symbol_id='s',name='v',static_classification='UNKNOWN')]),
            dict(findings=[]),scan_id='one',project_id='p')
        self.provider=EvidenceProvider(self.folder/'scan.db')
        self.store=ReviewStore(self.folder/'reviews.db',self.provider.metadata())
        self.event=self.store.append('s',self.provider.fingerprint('s'),reviewer='搬迁验收声明',decision='CONFIRMED_RISK')
        self.static=sha256(self.provider.path)
        (self.source/'settings').mkdir(exist_ok=True)
        (self.source/'settings/device.json').write_text(json.dumps(dict(device='device-test')),'utf-8')
        (self.source/'opaque.bin').write_bytes(bytes(range(256))*100)

    def preview(self):
        from ecra.data_transfer import preview
        return preview(self.source,str(self.target))

    def transfer(self,**kwargs):
        from ecra.data_transfer import transfer
        return transfer(self.source,str(self.target),expected=self.preview()['revision'],**kwargs)

    def test_complete_copy_independent_human_edit_and_reexport_keep_original_bytes(self):
        result=self.transfer()
        self.assertEqual(result['state'],'COMPLETE')
        self.assertEqual(sha256(self.target/'scans/one/scan.db'),self.static)
        restored=ReviewStore(self.target/'scans/one/reviews.db',self.provider.metadata())
        self.assertEqual(restored.history(),[self.event])
        restored.append('s',self.provider.fingerprint('s'),reviewer='搬迁后声明',decision='NEED_MORE_EVIDENCE',expected_heads=[self.event['event_id']])
        package=self.base/'after.ecra-report';export_report(self.target/'scans/one',package)
        imported=import_report(package,self.base/'independent')
        again=ReviewStore(self.base/'independent/scans'/imported['scan_id']/'reviews.db',self.provider.metadata())
        self.assertEqual(again.history(),restored.history())
        self.assertEqual(self.store.history(),[self.event])
        self.assertEqual(sha256(self.provider.path),self.static)
        self.assertEqual((self.source/'opaque.bin').read_bytes(),(self.target/'opaque.bin').read_bytes())

    def test_active_writer_and_stale_preview_refuse_before_publication(self):
        from ecra.data_transfer import transfer
        plan=self.preview()
        with DataActivity(self.source):
            with self.assertRaisesRegex(ValueError,'正在'):
                transfer(self.source,str(self.target),expected=plan['revision'])
        (self.source/'opaque.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):
            transfer(self.source,str(self.target),expected=plan['revision'])
        self.assertFalse(self.target.exists())

    def test_interrupt_resume_verifies_ready_files_and_keeps_source(self):
        from ecra.data_transfer import transfer
        plan=self.preview();journal=[]
        def progress(value):
            if value.get('copied_files',0)==1:
                journal.append(value['journal']);raise InterruptedError('injected stop')
        with self.assertRaises(InterruptedError):
            transfer(self.source,str(self.target),expected=plan['revision'],progress=progress)
        self.assertFalse(self.target.exists())
        result=transfer(self.source,str(self.target),resume=journal[0])
        self.assertGreaterEqual(result['reused_files'],1)
        self.assertEqual(sha256(self.provider.path),self.static)

    def test_resume_rejects_source_change_and_target_conflict_without_overwrite(self):
        from ecra.data_transfer import transfer
        plan=self.preview();journal=[]
        def stop(value):
            if value.get('copied_files',0)==1:journal.append(value['journal']);raise InterruptedError()
        with self.assertRaises(InterruptedError):transfer(self.source,str(self.target),expected=plan['revision'],progress=stop)
        (self.source/'opaque.bin').write_bytes(b'new source')
        with self.assertRaisesRegex(ValueError,'变化'):
            transfer(self.source,str(self.target),resume=journal[0])
        self.target.mkdir();(self.target/'keep.txt').write_text('keep','utf-8')
        with self.assertRaises(ValueError):self.preview()
        self.assertEqual((self.target/'keep.txt').read_text('utf-8'),'keep')

    def test_short_space_and_mid_copy_source_change_never_publish(self):
        from ecra.data_transfer import transfer
        plan=self.preview()
        with patch('ecra.data_transfer.shutil.disk_usage',return_value=type('Usage',(),dict(free=1))()):
            with self.assertRaisesRegex(ValueError,'空间'):
                transfer(self.source,str(self.target),expected=plan['revision'])
        def mutate(value):
            if value.get('copied_files',0)==1:(self.source/'opaque.bin').write_bytes(b'concurrent foreign writer')
        with self.assertRaisesRegex(ValueError,'变化'):
            transfer(self.source,str(self.target),expected=plan['revision'],progress=mutate)
        self.assertFalse(self.target.exists())

    def test_active_profile_rebind_preserves_history_and_runtime_is_retained(self):
        profile=self.source/'projects/p/profiles/main.yaml';profile.parent.mkdir(parents=True)
        raw='# preserve comment\nversion: 1\nproject:\n  root: '+str(self.base/'firmware')+'\nanalysis:\n  output:\n    location: custom\n    custom_dir: '+str(self.source)+'\nreview: {}\n'
        profile.write_text(raw,'utf-8')
        history=profile.parent/'history/main-old.yaml';history.parent.mkdir();history.write_text(raw,'utf-8')
        tree=self.source/'projects/p/trees';tree.mkdir();(tree/'gitdir').write_text('old runtime pointer','utf-8')
        result=self.transfer()
        changed=(self.target/profile.relative_to(self.source)).read_text('utf-8')
        self.assertIn('# preserve comment',changed)
        import yaml
        self.assertEqual(yaml.safe_load(changed)['analysis']['output'],dict(location='user'))
        self.assertEqual((self.target/history.relative_to(self.source)).read_text('utf-8'),raw)
        self.assertEqual(profile.read_text('utf-8'),raw)
        self.assertFalse((self.target/'projects/p/trees').exists())
        self.assertTrue(result['retained_runtime'])

    def test_committed_wal_payload_is_preserved_without_checkpointing_source(self):
        path=self.source/'settings/test-wal.db'
        conn=sqlite3.connect(path)
        self.addCleanup(conn.close)
        conn.execute('PRAGMA journal_mode=WAL');conn.execute('PRAGMA wal_autocheckpoint=0')
        conn.execute('CREATE TABLE data(value TEXT)');conn.execute("INSERT INTO data VALUES ('committed in WAL')");conn.commit()
        original=sha256(path);wal=sha256(Path(str(path)+'-wal'))
        self.transfer()
        from contextlib import closing
        with closing(sqlite3.connect(self.target/'settings/test-wal.db')) as restored:
            self.assertEqual(restored.execute('SELECT value FROM data').fetchone()[0],'committed in WAL')
        self.assertEqual(sha256(path),original)
        self.assertEqual(sha256(Path(str(path)+'-wal')),wal)

    def test_api_writers_startup_and_background_job_leases_are_quiesced(self):
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        app=create_app(self.source,token='transfer-test',authority='testserver')
        client=TestClient(app,headers={'x-ecra-session':'transfer-test','origin':'http://testserver'})
        with DataActivity(self.source,exclusive=True,purpose='api'):
            self.assertEqual(client.get('/api/scans').status_code,409)
            self.assertEqual(client.get('/api/data-transfers').status_code,200)
            with self.assertRaisesRegex(ValueError,'正在'):
                create_app(self.source,token='another',authority='testserver')
        for purpose in ('scan-budget','cleanup-job','legacy-import','storage-policy'):
            with self.subTest(purpose=purpose),DataActivity(self.source,exclusive=True,purpose=purpose):
                with self.assertRaisesRegex(ValueError,'正在'):
                    self.transfer()

    def test_background_api_copy_publishes_complete_independent_root(self):
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        import time
        app=create_app(self.source,token='transfer-test',authority='testserver')
        client=TestClient(app,headers={'x-ecra-session':'transfer-test','origin':'http://testserver'})
        plan=client.post('/api/data-transfers/preview',json=dict(target=str(self.target)))
        self.assertEqual(plan.status_code,200,plan.text)
        started=client.post('/api/data-transfers',json=dict(target=str(self.target),revision=plan.json()['revision']))
        self.assertEqual(started.status_code,200,started.text)
        ident=started.json()['id'];deadline=time.monotonic()+30
        while True:
            result=client.get('/api/data-transfers/'+ident).json()
            if result['state'] in {'FAILED','INTERRUPTED','COMPLETE'}:break
            if time.monotonic()>deadline:self.fail('copy worker failed to finish')
            time.sleep(.02)
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertEqual(sha256(self.target/'scans/one/scan.db'),self.static)

    def test_real_process_termination_releases_lease_and_resumes_verified_files(self):
        from ecra.data_transfer import transfer
        import subprocess,sys,time
        signal=self.base/'committed.signal'
        script='''import json,sys,time\nfrom pathlib import Path\nfrom ecra.data_transfer import preview,transfer\ns,t,signal=sys.argv[1:]\ndef stop(v):\n if v.get("copied_files")==1:\n  Path(signal).write_text(json.dumps(v),encoding="utf-8")\n  time.sleep(120)\ntransfer(s,t,expected=preview(s,t)["revision"],progress=stop)\n'''
        process=subprocess.Popen([sys.executable,'-B','-X','utf8','-c',script,str(self.source),str(self.target),str(signal)],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+15
            while not signal.exists():
                if process.poll() is not None:self.fail(process.communicate()[1].decode('utf-8','replace'))
                if time.monotonic()>deadline:self.fail('child did not commit a file')
                time.sleep(.02)
            progress=json.loads(signal.read_text('utf-8'))
            process.kill();process.wait(timeout=10)
            self.assertFalse(self.target.exists())
            result=transfer(self.source,str(self.target),resume=progress['journal'])
            self.assertEqual(result['state'],'COMPLETE')
            self.assertGreaterEqual(result['reused_files'],1)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=10)
            if process.stderr:process.stderr.close()

    def test_crash_after_atomic_publication_recovers_without_overwriting_target(self):
        from ecra.data_transfer import transfer
        from ecra.common import write_json
        def fail_complete(path,value,*args,**kwargs):
            if value.get('format')=='ECRA_ROOT_TRANSFER_V1' and value.get('state')=='COMPLETE':
                raise OSError('injected loss after rename')
            return write_json(path,value,*args,**kwargs)
        with patch('ecra.data_transfer.write_json',side_effect=fail_complete):
            with self.assertRaises(OSError):self.transfer()
        from ecra.data_transfer import registry
        journal=next(registry(self.source).glob('*.json'))
        self.assertEqual(json.loads(journal.read_text('utf-8'))['state'],'PUBLISHING')
        result=transfer(self.source,str(self.target),resume=str(journal))
        self.assertTrue(result['recovered_after_publication'])
        self.assertEqual(sha256(self.target/'scans/one/scan.db'),self.static)

    def test_retired_input_paths_are_blocked_even_when_old_root_still_exists(self):
        from ecra.data_transfer import reject_retired_inputs
        self.transfer()
        for value in [str(self.source/'generated.h'),['gcc','-I'+str(self.source/'build')],
                dict(cmake=dict(args=['-DCUSTOM='+str(self.source/'old')]))]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'旧数据目录'):
                reject_retired_inputs(self.target,value)
        reject_retired_inputs(self.target,[str(self.base/'firmware/main.c'),str(self.target/'new-build')])
        import os
        if os.name=='nt':
            from ecra.data_transfer import _aliases
            old_alias=_aliases(self.source)[0]
            parked=self.base/'original-offline';self.source.rename(parked)
            try:
                with self.assertRaisesRegex(ValueError,'旧数据目录'):
                    reject_retired_inputs(self.target,['-I'+old_alias+'\\include'])
            finally:parked.rename(self.source)

    def test_stopped_task_config_is_derived_without_editing_original_snapshot(self):
        from ecra.data_transfer import relocated_task_config
        import hashlib,yaml
        folder=self.source/'work/tasks/stopped';folder.mkdir(parents=True)
        raw=('# keep original\nversion: 1\nanalysis:\n  output:\n    location: custom\n    custom_dir: '+str(self.source)+'\n').encode()
        config=folder/'semantics.yaml';config.write_bytes(raw)
        (folder/'task.json').write_text(json.dumps(dict(profile_revision=hashlib.sha256(raw).hexdigest())),'utf-8')
        self.transfer()
        moved=self.target/'work/tasks/stopped/semantics.yaml'
        derived,proof=relocated_task_config(self.target,moved,moved.read_bytes())
        self.assertEqual(yaml.safe_load(derived)['analysis']['output'],dict(location='user'))
        self.assertEqual(proof['source_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(moved.read_bytes(),raw);self.assertEqual(config.read_bytes(),raw)
        with self.assertRaisesRegex(ValueError,'配置已变化'):
            relocated_task_config(self.target,moved,raw+b'future: changed\n')
