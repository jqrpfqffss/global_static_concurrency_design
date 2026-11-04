"""Real API/uploads and owned derived tasks; explicit small storage fixtures."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time
import unittest

from fastapi.testclient import TestClient

from ecra.common import write_json
from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.studio.server import create_app
from tests import test_multicore_pinned_inputs as pinned
from tests import test_multicore_publication as fixtures


class MulticoreWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pinned.PinnedMulticoreInputTests.setUpClass.__func__(cls)

    def setUp(self):
        pinned.PinnedMulticoreInputTests.setUp(self)
        self.rows=[];self.source_scans=[]
        for variant,config in self.inputs:
            raw=json.loads(config.read_text('utf-8'));raw['project']['root']=str(self.root)
            write_json(config,raw);payload=config.read_bytes();compressed=gzip.compress(payload,mtime=0)
            hashed=hashlib.sha256(compressed).hexdigest();ident='workflow-'+variant
            folder=self.data/'scans'/ident;folder.mkdir(parents=True);(folder/'evidence').mkdir()
            (folder/'evidence'/hashed).write_bytes(compressed)
            binding=EvidenceProvider(self.selected_folders[0]/'scan.db').metadata()
            file=config.as_posix()
            publish_scan(folder/'scan.db',copy.deepcopy(self.facts),dict(findings=[]),scan_id=ident,
                project_id=binding['project_id'],profile_id='profile-'+variant,
                provenance=dict(project_root=str(self.root),
                    display_identity=dict(config_file=file,config_sha256=sha256(config)),
                    archived_sources=[dict(file=file,sha256=sha256(config),raw_object=hashed,codec='gzip',size=len(payload))]))
            provider=EvidenceProvider(folder/'scan.db');binding=provider.metadata()
            store=ReviewStore(folder/'reviews.db',binding)
            sid=provider.symbols()['items'][0]['symbol_id']
            store.append(sid,provider.fingerprint(sid),reviewer='原输入测试声明',decision='NEED_MORE_EVIDENCE')
            write_json(folder/'manifest.json',dict(binding,format='ECRA_LOCAL_SCAN',version=1,scan_sha256=sha256(folder/'scan.db')))
            self.rows.append(dict(variant=variant,scan_id=ident));self.source_scans.append(folder)
        self.app=create_app(self.data,token='workflow-test',authority='testserver')
        self.client=TestClient(self.app,headers={'X-ECRA-Session':'workflow-test','Origin':'http://testserver'})
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.regions=[dict(start='0x38000000',size='0x10000')]

    def upload(self,payload=None):
        result=self.client.post('/api/multicore/elf?name=actual-linked.elf',content=fixtures.linked_elf() if payload is None else payload)
        self.assertEqual(result.status_code,200,result.text)
        return result.json()['id']

    def preview(self):
        inputs=[dict(row,elf_id=self.upload()) for row in self.rows]
        result=self.client.post('/api/multicore/preview',json=dict(inputs=inputs,regions=self.regions))
        self.assertEqual(result.status_code,200,result.text);return result.json(),inputs

    def wait_task(self,identity):
        deadline=time.monotonic()+40
        while True:
            row=self.client.get('/api/tasks/'+identity).json()
            if row['state'] not in {'RUNNING','STOP_REQUESTED'}:
                while self.app.state.task_manager.active is not None and time.monotonic()<deadline:time.sleep(.05)
                return row
            if time.monotonic()>deadline:self.fail('owned multicore task did not finish')
            time.sleep(.1)

    def test_archived_configs_survive_live_profile_change_and_real_owned_job_publishes(self):
        before={str(p):sha256(p) for folder in self.source_scans for p in folder.rglob('*') if p.is_file()}
        plan,_=self.preview()
        self.assertEqual(plan['stage'],'INPUT_SELECTION_FIXED')
        self.inputs[0][1].write_text('live profile changed after native scan\n','utf-8')
        result=self.client.post('/api/multicore/start',json=dict(id=plan['id'],revision=plan['revision'],resources=dict(preset='low')))
        self.assertEqual(result.status_code,200,result.text)
        task=self.wait_task(result.json()['id']);self.assertEqual(task['state'],'COMPLETE',task)
        self.assertEqual(task['mode'],'multicore');self.assertEqual(task['checkpoint_mode'],'RETRY_DERIVATION_FROM_FIXED_INPUTS')
        self.assertTrue(task['published']);self.assertEqual(task['budget_bytes'],8*1024**3)
        out=self.data/'scans'/task['scan_id'];provider=EvidenceProvider(out/'scan.db')
        self.assertEqual(provider.load('report')['analysis_status'],'INCOMPLETE')
        self.assertEqual([row['binding']['scan_id'] for row in provider.load('provenance')['components']],
                         [row['scan_id'] for row in self.rows])
        self.assertEqual({str(p):sha256(p) for folder in self.source_scans for p in folder.rglob('*') if p.is_file()},before)
        repeated=self.client.post('/api/multicore/start',json=dict(id=plan['id'],revision=plan['revision']))
        self.assertEqual(repeated.status_code,400);self.assertIn('已提交',repeated.json()['error'])

    def test_prechecked_manifest_change_is_failed_by_worker_and_retry_keeps_same_fixed_inputs(self):
        plan,_=self.preview();manifest=self.source_scans[0]/'manifest.json'
        original=manifest.read_bytes();manifest.write_bytes(original+b'\n')
        result=self.client.post('/api/multicore/start',json=dict(id=plan['id'],revision=plan['revision']))
        self.assertEqual(result.status_code,200,result.text);failed=self.wait_task(result.json()['id'])
        self.assertEqual(failed['state'],'FAILED');self.assertIn('预检查后变化',failed['error']);self.assertFalse(failed['published'])
        manifest.write_bytes(original)
        result=self.client.post('/api/tasks/'+failed['id']+'/retry')
        self.assertEqual(result.status_code,200,result.text);recovered=self.wait_task(result.json()['id'])
        self.assertEqual(recovered['state'],'COMPLETE',recovered)
        self.assertNotEqual(recovered['scan_id'],failed['scan_id'])
        self.assertFalse((self.data/'scans'/failed['scan_id']/'manifest.json').exists())

    def test_invalid_header_and_broken_elf_structure_never_publish_valid_results(self):
        result=self.client.post('/api/multicore/elf',content=b'not an elf')
        self.assertEqual(result.status_code,400);self.assertIn('ARM',result.json()['error'])
        broken=fixtures.linked_elf()[:20]
        inputs=[dict(row,elf_id=self.upload(broken)) for row in self.rows]
        result=self.client.post('/api/multicore/preview',json=dict(inputs=inputs,regions=self.regions))
        self.assertEqual(result.status_code,200,result.text);plan=result.json()
        result=self.client.post('/api/multicore/start',json=dict(id=plan['id'],revision=plan['revision']))
        failed=self.wait_task(result.json()['id'])
        self.assertEqual(failed['state'],'FAILED');self.assertIn('结构不完整',failed['error']);self.assertFalse(failed['published'])

    def test_missing_archive_config_bad_regions_and_stale_plan_fail_before_start(self):
        plan,inputs=self.preview()
        result=self.client.post('/api/multicore/start',json=dict(id=plan['id'],revision='stale'))
        self.assertEqual(result.status_code,400)
        for regions in [[],[dict(start='0x100000000',size='1')],[dict(start='-1',size='4')],
                        [dict(start='0',size='0')],[dict(start=True,size='4')]]:
            result=self.client.post('/api/multicore/preview',json=dict(inputs=inputs,regions=regions))
            self.assertEqual(result.status_code,400,result.text)
        inputs[0]['scan_id']='selected-CM7'  # Existing graph has a hash only, no original config bytes.
        result=self.client.post('/api/multicore/preview',json=dict(inputs=inputs,regions=self.regions))
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.app.state.task_manager.list(),[])

    def test_shared_scan_budget_rejects_start_then_same_fixed_plan_can_be_submitted(self):
        from ecra.storage_activity import DataActivity
        plan,_=self.preview();request=dict(id=plan['id'],revision=plan['revision'])
        with DataActivity(self.data,exclusive=True,purpose='scan-budget'):
            blocked=self.client.post('/api/multicore/start',json=request)
            self.assertEqual(blocked.status_code,400)
        self.assertEqual(self.app.state.task_manager.list(),[])
        result=self.client.post('/api/multicore/start',json=request)
        self.assertEqual(result.status_code,200,result.text)
        completed=self.wait_task(result.json()['id']);self.assertEqual(completed['state'],'COMPLETE',completed)

    def test_oversized_config_object_is_rejected_before_a_full_object_read(self):
        plan,inputs=self.preview()
        folder=self.source_scans[0]
        blob=next((folder/'evidence').iterdir())
        with blob.open('ab') as stream:stream.write(b'X'*(5*1024**2))
        result=self.client.post('/api/multicore/preview',json=dict(inputs=inputs,regions=self.regions))
        self.assertEqual(result.status_code,400)
        self.assertIn('5MiB',result.json()['error'])
        self.assertEqual(self.app.state.task_manager.list(),[])


if __name__=='__main__':unittest.main()
