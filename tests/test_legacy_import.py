from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from ecra import legacy_import
from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report, import_report, sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.shared_json import write as write_shared
from ecra.studio.server import create_app
from ecra.studio.migration_jobs import MigrationJobs
from ecra.storage_activity import DataActivity
from ecra.workspace import WorkspaceResolver


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA 旧归档 '); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.root=self.base/'firmware'; self.root.mkdir()
        self.old=self.root/'.ecra'; self.old.mkdir(); (self.old/'reports').mkdir(); (self.old/'review').mkdir()
        self.data=self.base/'new-data'
        self.facts=dict(variables=[dict(symbol_id='identity', name='old_global', static_classification='UNKNOWN')],
            accesses=[dict(symbol_id='identity', access_kind='RMW', file='a.c', line=3)], order=[True,1,-0.0,'中文'])
        self.report=dict(findings=[dict(finding_id='f',symbol_id='identity',summary='归档不等于源码重新证明')])
        write_shared(self.old/'facts.json',self.facts,threshold=0)
        write_shared(self.old/legacy_import.REPORT,self.report,threshold=0)
        # This deliberately is not executable SQLite. Migration must preserve
        # opaque legacy bytes rather than execute arbitrary schema from it.
        (self.old/'facts.db').write_bytes(b'SQLite format 3\0untrusted old bytes')
        (self.old/'run.json').write_text(json.dumps(dict(project_root=str(self.root))),encoding='utf-8')
        (self.old/'scan_state.json').write_text(json.dumps(dict(schema=1,project_root=str(self.root),fingerprint='old-proof')),encoding='utf-8')
        (self.old/'review/answer.txt').write_text('旧复核回复\n<script>window.injected=true</script>',encoding='utf-8')
        (self.old/'unknown.bin').write_bytes(bytes(range(256))*100)

    def original_hashes(self):
        return {file.relative_to(self.root).as_posix():sha256(file) for file in self.root.rglob('*') if file.is_file()}

    def convert(self,**kwargs):
        return legacy_import.convert(self.old,self.root,self.data,**kwargs)

    def test_shared_conversion_preserves_every_logical_field_all_old_bytes_and_originals(self):
        before=self.original_hashes(); result=self.convert()
        self.assertEqual(self.original_hashes(),before)
        scan=self.data/'scans'/result['scan_id']; provider=EvidenceProvider(scan/'scan.db')
        self.assertEqual(provider.metadata()['state'],'LEGACY_READ_ONLY')
        from scripts.validate_studio_baseline import strict_difference
        self.assertIsNone(strict_difference(provider.load('facts'),self.facts))
        self.assertIsNone(strict_difference(provider.load('report'),self.report))
        sources=provider.load('provenance')['legacy_inputs']
        self.assertEqual({row['file'] for row in sources},{file.relative_to(self.old).as_posix() for file in self.old.rglob('*') if file.is_file()})
        for row in sources:
            if row['disposition']=='OPAQUE_AUDIT_PRESERVED':
                self.assertEqual((scan/'evidence'/row['sha256']).read_bytes(),(self.old/row['file']).read_bytes())
        self.assertFalse((scan/'facts.json').exists()); self.assertFalse((scan/'facts.db').exists())
        self.assertFalse((scan/'reports').exists())
        reviews=ReviewStore(scan/'reviews.db',provider.metadata())
        self.assertEqual(reviews.current('identity',provider.fingerprint('identity'))['decision'],'PENDING')
        package=self.base/'migrated.ecra-report'; export_report(scan,package)
        imported=import_report(package,self.base/'viewer')
        viewed=self.base/'viewer/scans'/imported['scan_id']
        self.assertEqual(EvidenceProvider(viewed/'scan.db').roots(),provider.roots())
        for file in (scan/'evidence').iterdir(): self.assertEqual(sha256(viewed/'evidence'/file.name),file.name)

    def test_repeated_import_keeps_existing_human_decision_and_static_bytes(self):
        first=self.convert(); scan=self.data/'scans'/first['scan_id']; provider=EvidenceProvider(scan/'scan.db')
        human=ReviewStore(scan/'reviews.db',provider.metadata())
        event=human.append('identity',provider.fingerprint('identity'),decision='CONFIRMED_RISK',reviewer='人工',expected_heads=[])
        before=sha256(scan/'scan.db'); second=self.convert()
        self.assertTrue(second['repeated']); self.assertEqual(first['scan_id'],second['scan_id'])
        self.assertEqual(sha256(scan/'scan.db'),before)
        self.assertEqual(human.history('identity')[0]['event_id'],event['event_id'])
        self.assertEqual(len(list((self.data/'scans').iterdir())),1)
        self.assertEqual(list((self.data/'work/legacy').glob('*/archive')),[],
            'verified repeated imports must not accumulate duplicate authorities')

    def test_wrong_ownership_missing_facts_and_live_wal_are_explicit_failures(self):
        other=self.base/'other'; other.mkdir()
        with self.assertRaisesRegex(ValueError,'归属'):
            legacy_import.inspect(self.old,other,self.data)
        (self.old/'facts.json').unlink()
        with self.assertRaisesRegex(ValueError,'不能无损恢复'):
            self.convert()
        write_shared(self.old/'facts.json',self.facts,threshold=0)
        (self.old/'facts.db-wal').write_bytes(b'pending WAL')
        with self.assertRaisesRegex(ValueError,'恢复文件'):
            self.convert()
        self.assertFalse((self.data/'scans').exists())

    def test_historical_checkpoint_hash_mismatch_is_not_imported_as_valid_history(self):
        state=json.loads((self.old/'scan_state.json').read_text(encoding='utf-8'))
        state['facts_sha256']='0'*64
        (self.old/'scan_state.json').write_text(json.dumps(state),encoding='utf-8')
        before=self.original_hashes()
        with self.assertRaisesRegex(ValueError,'旧检查点与归档字节不一致'):
            self.convert()
        self.assertEqual(self.original_hashes(),before)
        self.assertFalse((self.data/'scans').exists())

    def test_package_cannot_drop_original_bytes_by_removing_optional_audit_index(self):
        import zipfile
        result=self.convert();scan=self.data/'scans'/result['scan_id']
        package=self.base/'full.ecra-report';export_report(scan,package)
        dropped='evidence/'+sha256(self.old/'unknown.bin')
        corrupt=self.base/'missing-original.ecra-report'
        with zipfile.ZipFile(package) as reader,zipfile.ZipFile(corrupt,'w',zipfile.ZIP_DEFLATED) as writer:
            manifest=json.loads(reader.read('manifest.json'));manifest.pop('audit_index')
            manifest['files'].pop(dropped)
            writer.writestr('manifest.json',json.dumps(manifest))
            for name in reader.namelist():
                if name not in {'manifest.json',dropped}:writer.writestr(name,reader.read(name))
        with self.assertRaisesRegex(ValueError,'旧归档审计原字节缺失'):
            import_report(corrupt,self.base/'viewer')
        self.assertFalse((self.base/'viewer/scans'/result['scan_id']).exists())

    def test_changed_copied_source_cannot_be_published_or_damage_prior_scan(self):
        existing=self.data/'scans/prior';existing.mkdir(parents=True)
        publish_scan(existing/'scan.db',{}, {},scan_id='prior',project_id='prior')
        before=(existing/'scan.db').read_bytes(); changed=False
        def modify(info):
            nonlocal changed
            if info['stage']=='VALIDATING' and not changed:
                changed=True; (self.old/'facts.json').write_text('{"variables":[]}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'旧目录已变化'):
            self.convert(progress=modify)
        self.assertEqual((existing/'scan.db').read_bytes(),before)
        self.assertEqual([p.name for p in (self.data/'scans').iterdir()],['prior'])
        failed=next((self.data/'work/legacy').glob('*/migration.json'))
        self.assertEqual(json.loads(failed.read_text(encoding='utf-8'))['state'],'FAILED')

    def test_exact_existing_workspace_identity_is_checked_and_owner_bytes_retained(self):
        owned=self.base/'old-tool-data'
        ws=WorkspaceResolver.resolve(self.root,dict(output=dict(location='custom',custom_dir=str(owned)))).initialize()
        import shutil
        target=Path(ws.results_root)
        shutil.copytree(self.old,target,dirs_exist_ok=True)
        plan=legacy_import.inspect(target,self.root,self.data)
        self.assertEqual(plan['project_id'],ws.project_id); self.assertEqual(plan['source_kind'],'TOOL_WORKSPACE')
        result=legacy_import.convert(target,self.root,self.data)
        root=EvidenceProvider(self.data/'scans'/result['scan_id']/'scan.db').load('provenance')
        self.assertIn('owner/project.json',[entry['file'] for entry in root['legacy_inputs']])
        marker=Path(ws.project_workspace)/'project.json'; owner=json.loads(marker.read_text(encoding='utf-8'))
        owner['project_id']='wrong'; marker.write_text(json.dumps(owner),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'归属校验失败'):
            legacy_import.inspect(target,self.root,self.data)

    def test_real_api_job_and_bounded_opaque_artifacts_are_safe_and_persistent(self):
        client=TestClient(create_app(self.data,token='t',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345',
            headers={'x-ecra-session':'t','origin':'http://127.0.0.1:12345'})
        payload=dict(source=str(self.old),project_root=str(self.root))
        plan=client.post('/api/migrations/preview',json=payload); self.assertEqual(plan.status_code,200,plan.text)
        request=dict(payload,revision=plan.json()['revision'])
        bad=client.post('/api/migrations',json=dict(request,revision='stale'))
        self.assertEqual(bad.status_code,400,bad.text)
        started=client.post('/api/migrations',json=request); self.assertEqual(started.status_code,200,started.text)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            job=client.get('/api/migrations/'+started.json()['id']).json()
            if job['state']!='RUNNING':break
            time.sleep(.02)
        self.assertEqual(job['state'],'COMPLETE',job)
        scan=job['scan_id']; prefix='/api/scans/'+scan
        self.assertTrue(client.get(prefix+'/summary').json()['legacy_warning'])
        entries=client.get(prefix+'/legacy-files').json()['items']
        text=next(x for x in entries if x['file']=='review/answer.txt')
        preview=client.get(prefix+'/legacy-file',params=dict(ordinal=text['ordinal'],limit=16384)).json()
        self.assertIn('<script>',preview['text']); self.assertEqual(preview['encoding'],'utf-8')
        binary=next(x for x in entries if x['file']=='unknown.bin')
        value=client.get(prefix+'/legacy-file',params=dict(ordinal=binary['ordinal'],limit=50)).json()
        self.assertEqual(value['encoding'],'hex'); self.assertEqual(value['next_offset'],50)
        self.assertLess(len(json.dumps(value)),3000)
        self.assertEqual(client.get(prefix+'/legacy-files?limit=999').status_code,400)
        self.assertEqual(client.get(prefix+'/legacy-file?ordinal=-1').status_code,400)
        self.assertEqual(MigrationJobs(self.data).get(job['id'])['state'],'COMPLETE')

    def test_live_process_lease_prevents_false_restart_recovery(self):
        jobs=MigrationJobs(self.data)
        ident='active-job'; item=dict(id=ident,state='RUNNING',started='now')
        with jobs.connect() as conn:
            conn.execute('INSERT INTO jobs VALUES (?,?,?,?)',(ident,'now','RUNNING',json.dumps(item)))
        with DataActivity(self.data,exclusive=True,purpose='legacy-import'):
            self.assertEqual(MigrationJobs(self.data).get(ident)['state'],'RUNNING')
        recovered=MigrationJobs(self.data).get(ident)
        self.assertEqual(recovered['state'],'INTERRUPTED'); self.assertIn('原数据保留',recovered['error'])


if __name__=='__main__': unittest.main()
