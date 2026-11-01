import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.studio.server import create_app


class StudioAPITests(unittest.TestCase):
    def test_real_builtin_sample_api_is_idempotent_authenticated_and_preserves_existing_scan(self):
        from ecra.report_package import sha256
        original=self.data/'scans/scan-api/scan.db';before=sha256(original)
        descriptor=self.client.get('/api/bootstrap').json()['sample'];self.assertTrue(descriptor['available'],descriptor)
        self.assertEqual(self.client.post('/api/sample/open',json={},headers={'x-ecra-session':'bad'}).status_code,401)
        first=self.client.post('/api/sample/open',json={});self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['scan_id'],descriptor['scan_id'])
        again=self.client.post('/api/sample/open',json={});self.assertEqual(again.status_code,200,again.text);self.assertTrue(again.json()['repeated'])
        self.assertEqual(sha256(original),before)
        self.assertEqual(self.client.get('/api/scans').json()['items'][0]['mode'],'OFFLINE_ARCHIVE')

    def test_directory_picker_is_authenticated_read_only_and_bound_to_selected_project(self):
        root=Path(self.tmp.name)/'固件, 目录';root.mkdir();(root/'Drivers, HAL').mkdir()
        file=root/'original.c';file.write_text('int original;','utf-8');before=(file.read_bytes(),file.stat().st_mtime_ns,root.stat().st_mtime_ns)
        payload=dict(path=str(root),root=str(root),limit=1)
        response=self.client.post('/api/profiles/directories',json=payload)
        self.assertEqual(response.status_code,200,response.text);value=response.json()
        self.assertEqual(value['items'][0]['relative'],'Drivers, HAL');self.assertEqual(value['relative'],'.')
        self.assertEqual(value['total'],1)
        self.assertEqual(self.client.post('/api/profiles/directories',json=dict(path=str(root.parent),root=str(root))).status_code,400)
        self.assertEqual(self.client.post('/api/profiles/directories',json=payload,headers={'x-ecra-session':'bad'}).status_code,401)
        self.assertEqual(before,(file.read_bytes(),file.stat().st_mtime_ns,root.stat().st_mtime_ns))

    def test_context_form_api_keeps_full_backup_and_refuses_shared_or_invalid_origins(self):
        import copy
        import yaml
        from tests.test_context_forms import RAW
        state=self.client.post('/api/profiles/form',json=dict(yaml=RAW)).json()
        self.assertTrue(state['contexts_editable']);rows=copy.deepcopy(state['form']['contexts'])
        rows[1]['functions']=['New_IRQHandler','New_IRQHandler']
        result=self.client.post('/api/profiles/form-merge',json=dict(yaml=RAW,changes=dict(contexts=rows,system_headers='on')))
        self.assertEqual(result.status_code,200,result.text);value=result.json();expected=yaml.safe_load(RAW)
        expected['contexts'][1]['functions']=rows[1]['functions'];expected['analysis']['auto_system_includes']=True
        self.assertEqual(yaml.safe_load(value['yaml']),expected)
        original=self.client.get('/api/profiles/drafts/'+value['backup']['id'])
        self.assertEqual(original.json()['yaml'],RAW)
        backup_files={p.name:p.read_bytes() for p in (self.data/'settings/profile-drafts').glob('*.yaml')}
        rows[0]['origin_id']='forged'
        shared='contexts: [{id: main, kind: MAIN, functions: &f [main]}]\nfuture: *f\n'
        for raw,changes in [(RAW,dict(contexts=rows)),(shared,dict(contexts=[]))]:
            refused=self.client.post('/api/profiles/form-merge',json=dict(yaml=raw,changes=changes))
            self.assertEqual(refused.status_code,400,refused.text)
        self.assertEqual(backup_files,{p.name:p.read_bytes() for p in (self.data/'settings/profile-drafts').glob('*.yaml')})

    def test_host_commit_pressure_blocks_new_task_without_altering_valid_scan_or_firmware(self):
        from ecra.report_package import sha256
        fw=Path(self.tmp.name)/'firmware';fw.mkdir()
        raw=json.dumps(dict(version=1,project=dict(root=str(fw)),analysis=dict(output=dict(location='user'))))
        saved=self.client.post('/api/profiles',json=dict(yaml=raw));self.assertEqual(saved.status_code,200,saved.text)
        profile=saved.json();before=sha256(self.provider.path)
        with patch('ecra.scan_diagnostics.memory',return_value=dict(system_physical_available_bytes=42*1024**3,
                system_commit_bytes=95*1024**3,system_commit_limit_bytes=96*1024**3)):
            refused=self.client.post('/api/tasks',json=dict(project_id=profile['project_id'],profile_id=profile['id'],revision=profile['revision']))
        self.assertEqual(refused.status_code,400,refused.text);self.assertIn('提交额度',refused.json()['error'])
        self.assertEqual(self.client.get('/api/tasks').json()['items'],[])
        self.assertEqual(sha256(self.provider.path),before);self.assertEqual(list(fw.iterdir()),[])

    def test_profile_form_roundtrip_backup_survives_reopen_and_bad_edits_preserve_source(self):
        import hashlib
        fw=Path(self.tmp.name)/'firmware';fw.mkdir()
        raw='# 完整原文\r\nversion: 1\r\nproject:\r\n  name: "原配置"\r\n  root: '+json.dumps(str(fw))+'\r\nanalysis:\r\n  output: {location: user}\r\n  compile_database: "compile_commands.json"\r\nextra: {literal: "on", unknown: [true, 7]} # 未知字段\r\n'
        state=self.client.post('/api/profiles/form',json=dict(yaml=raw))
        self.assertEqual(state.status_code,200,state.text)
        self.assertTrue(state.json()['editable'])
        result=self.client.post('/api/profiles/form-merge',json=dict(yaml=raw,changes=dict(project_name='已同步配置',include_dirs=['Src,用户目录',' Path with spaces '])))
        self.assertEqual(result.status_code,200,result.text)
        value=result.json();identity=hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(value['backup']['id'],identity)
        self.assertIn('# 未知字段',value['yaml'])
        saved=self.client.post('/api/profiles',json=dict(yaml=value['yaml']))
        self.assertEqual(saved.status_code,200,saved.text)
        reopened=self.client.get('/api/profiles').json()['items'][0]
        self.assertEqual(reopened['yaml'],value['yaml']);self.assertEqual(reopened['name'],'已同步配置')
        other=TestClient(create_app(self.data,token='test-token',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345',headers={'x-ecra-session':'test-token','origin':'http://127.0.0.1:12345'})
        restored=other.get('/api/profiles/drafts/'+identity)
        self.assertEqual(restored.status_code,200,restored.text);self.assertEqual(restored.json()['yaml'],raw)
        backup=self.data/'settings/profile-drafts'/(identity+'.yaml')
        self.assertEqual(backup.read_bytes(),raw.encode())
        for changes in [dict(unknown='no'),dict(include_dirs=['bad\npath'])]:
            refused=other.post('/api/profiles/form-merge',json=dict(yaml=raw,changes=changes))
            self.assertEqual(refused.status_code,400,refused.text)
            self.assertEqual(backup.read_bytes(),raw.encode())
            self.assertEqual(other.get('/api/profiles').json()['items'][0]['yaml'],value['yaml'])
        self.assertEqual(other.get('/api/profiles/drafts/not-a-hash').status_code,400)
        backup.write_bytes(b'corrupt existing backup')
        self.assertEqual(other.get('/api/profiles/drafts/'+identity).status_code,400)
        self.assertEqual(other.post('/api/profiles/form-merge',json=dict(yaml=raw,changes=dict(project_name='retry'))).status_code,400)
        self.assertEqual(backup.read_bytes(),b'corrupt existing backup')
        self.assertFalse(list(backup.parent.glob('*.pending')));self.assertEqual(list(fw.iterdir()),[])

    def test_coverage_endpoints_exact_identity_and_independent_position_survive_reopen(self):
        from ecra.report_package import sha256
        path=self.data/'scans/coverage-api';path.mkdir()
        publish_scan(path/'scan.db',dict(variables=[dict(symbol_id=s,name='same',translation_units=['a.c']) for s in ['id','id-long']],
            translation_units=[dict(source_file='a.c',parse_status='FAILED'),dict(source_file='zero.c',parse_status='PARSED')],
            unknowns=[dict(kind='PARSE_FAILED',symbol_id='id',file='a.c')]),
            dict(analysis_status='INCOMPLETE',coverage=dict(blocker_fanout=[dict(kind='PARSE_FAILED',symbol_ids=['id-long','id'],blocker_fanout=2)])),
            scan_id='coverage-api',project_id='p')
        before=sha256(path/'scan.db');base='/api/scans/coverage-api'
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full graph restored')):
            self.assertEqual(self.client.get(base+'/coverage').json()['tu_records'],2)
            self.assertEqual(self.client.get(base+'/coverage/groups').json()['items'][0]['raw'],'PARSE_FAILED')
            self.assertEqual(self.client.get(base+'/coverage/issues').json()['total'],1)
            page=self.client.get(base+'/coverage/blockers').json();node=page['items'][0]['node']
            self.assertEqual(self.client.get(base+'/coverage/related',params=dict(node=node,offset=1,limit=1)).json()['items'][0]['symbol_id'],'id')
            zero=self.client.get(base+'/coverage/tus?zero_only=true').json()
            self.assertEqual(zero['items'][0]['summary']['source_file'],'zero.c')
            self.assertEqual(self.client.get(base+'/symbols',params=dict(symbol_id='id')).json()['total'],1)
            self.assertEqual(self.client.get(base+'/symbol',params=dict(symbol_id='id-long')).json()['symbol_id'],'id-long')
            self.assertEqual(self.client.get(base+'/symbol',params=dict(symbol_id='id-')).status_code,400)
            for suffix in ['/coverage/issues?limit=201','/coverage/related?node=-1','/coverage/tus?offset=-1']:
                self.assertEqual(self.client.get(base+suffix).status_code,400,suffix)
            position=dict(tab='blockers',offsets=dict(blockers=0),selected=dict(node=node,source='blockers'))
            self.assertTrue(self.client.put(base+'/coverage/position',json=position).json()['saved'])
            self.assertEqual(self.client.get(base+'/coverage/position').json(),position)
        provider=EvidenceProvider(path/'scan.db');reopened=ReviewStore(path/'reviews.db',provider.metadata())
        self.assertEqual(reopened.position('coverage'),position)
        self.assertIsNone(reopened.position('workbench'))
        self.assertEqual(sha256(path/'scan.db'),before)

    def test_legacy_unicode_and_numeric_precision_survive_the_actual_json_response(self):
        target=self.data/'scans/typed';target.mkdir()
        publish_scan(target/'scan.db',dict(probe=dict(unpaired='\ud800',large=2**80+1,negative=-0.0)),{},scan_id='typed',project_id='p')
        provider=EvidenceProvider(target/'scan.db')
        node=provider.resolve('facts',['probe'])
        response=self.client.get('/api/scans/typed/nodes/'+str(node))
        self.assertEqual(response.status_code,200,response.text)
        result={row['key']:row for row in response.json()['items']}
        self.assertEqual(result['unpaired']['value'],'\ud800')
        self.assertEqual(result['unpaired']['display_json'],'"\\ud800"')
        self.assertEqual(result['large']['exact_value'],str(2**80+1))
        self.assertEqual(result['negative']['exact_value'],'-0.0')
        self.assertEqual(result['negative']['binary_value'],'-0x0.0p+0')

    def test_storage_sampling_tolerates_live_temp_removal_without_masking_import_errors(self):
        from ecra.workspace import no_links
        temporary=self.data/'work/transient';temporary.mkdir(parents=True)
        def racing(path):
            if Path(path).name=='transient':raise FileNotFoundError('temporary directory was removed by its owner')
            return no_links(path)
        with patch('ecra.studio.server.no_links',side_effect=racing):
            response=self.client.get('/api/storage')
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['sampling_partial'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra API ')
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)/'data'
        path = self.data/'scans/scan-api'; path.mkdir(parents=True)
        publish_scan(path/'scan.db', dict(variables=[dict(symbol_id='s',name='真实变量',static_classification='SUSPECT')],
            accesses=[dict(symbol_id='s', access_kind='RMW',file='a.c',line=3)]), dict(findings=[]), scan_id='scan-api',project_id='p')
        self.provider = EvidenceProvider(path/'scan.db')
        ReviewStore(path/'reviews.db',self.provider.metadata())
        self.client = TestClient(create_app(self.data,token='test-token',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345',
            headers={'x-ecra-session':'test-token','origin':'http://127.0.0.1:12345'})

    def test_loopback_host_origin_token_and_csrf_boundaries(self):
        self.assertEqual(self.client.get('/api/scans').status_code,200)
        for headers,status in [({'x-ecra-session':'wrong'},401),({'host':'evil.test'},403),({'origin':'https://evil.test'},403)]:
            self.assertEqual(self.client.get('/api/scans',headers=headers).status_code,status)
        self.assertEqual(self.client.post('/api/scans/scan-api/human',headers={'origin':'null'},json={}).status_code,403)

    def test_pagination_count_and_decision_commit_survive_reopening(self):
        result = self.client.get('/api/scans/scan-api/symbols?limit=1').json()
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['name'],'真实变量')
        request = dict(symbol_id='s',fingerprint=self.provider.fingerprint('s'),decision='CONFIRMED_RISK',reviewer='声明',expected_heads=[])
        response = self.client.post('/api/scans/scan-api/human',json=request)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['saved'])
        self.assertEqual(self.client.post('/api/scans/scan-api/human',json=request).status_code,409)
        self.assertEqual(self.client.get('/api/scans/scan-api/summary').json()['human_counts']['CONFIRMED_RISK'],1)
        self.assertEqual(self.client.get('/api/scans/scan-api/symbols?human_decision=PENDING').json()['total'],0)
        self.assertEqual(self.client.get('/api/scans/scan-api/symbols?human_decision=CONFIRMED_RISK').json()['total'],1)
        reopened = ReviewStore(self.data/'scans/scan-api/reviews.db',self.provider.metadata())
        self.assertEqual(reopened.current('s',self.provider.fingerprint('s'))['decision'],'CONFIRMED_RISK')
        self.assertEqual(self.client.get('/api/scans/scan-api/symbols?limit=99999').status_code,400)
        self.assertEqual(self.client.get('/api/scans/scan-api/symbols',params={'sort':'name; DROP TABLE symbols'}).status_code,400)
        sorted_page=self.client.get('/api/scans/scan-api/symbols?sort=name&order=desc').json()
        self.assertEqual(sorted_page['sort'],'name');self.assertEqual(sorted_page['order'],'desc')
        self.assertEqual(sorted_page['total'],1)

    def test_real_package_upload_and_export_use_same_protocol(self):
        package = Path(self.tmp.name)/'result.ecra-report'
        export_report(self.data/'scans/scan-api',package)
        response = self.client.post('/api/import',content=package.read_bytes())
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['repeated'])
        result = self.client.post('/api/scans/scan-api/export',json={'kind':'full'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertGreater(len(self.client.get(result.json()['download']).content),100)

    def test_profile_preserves_raw_yaml_unknown_fields_and_comments(self):
        fw = Path(self.tmp.name)/'firmware'; fw.mkdir()
        raw = f'# 人工注释不能丢失\nversion: 1\nproject:\n  root: {json.dumps(str(fw))}\nanalysis: {{}}\nfuture_custom: {{keep: true}}\nreview: {{enabled: false}}\n'
        checked = self.client.post('/api/profiles/check',json={'yaml':raw})
        self.assertEqual(checked.status_code,200,checked.text)
        self.assertFalse(checked.json()['ready_for_scan'])
        saved = self.client.post('/api/profiles',json={'yaml':raw})
        self.assertEqual(saved.status_code,200,saved.text)
        reopened = self.client.get('/api/profiles').json()['items'][0]
        self.assertEqual(reopened['yaml'],raw)
        self.assertEqual(list(fw.iterdir()),[])
        # Concurrent stale editor cannot overwrite another saved revision.
        self.assertEqual(self.client.post('/api/profiles',json={'yaml':raw,'id':saved.json()['id'],'revision':'bad'}).status_code,409)

    def test_unsafe_source_modes_rejected_with_actionable_error(self):
        fw = Path(self.tmp.name)/'firmware'; fw.mkdir()
        raw = json.dumps(dict(version=1,project=dict(root=str(fw)),analysis=dict(output=dict(location='project'))))
        response = self.client.post('/api/profiles/check',json={'yaml':raw})
        self.assertEqual(response.status_code,400,response.text)
        self.assertIn('独立',response.json()['error'])
        self.assertEqual(list(fw.iterdir()),[])
