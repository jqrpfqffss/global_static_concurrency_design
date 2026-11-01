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
