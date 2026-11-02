from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report, import_report, sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.studio.history import history
from ecra.studio.server import create_app


class StudioHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra history 中文 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root/'data'
        self.a = self.scan('a', name='控制器 M7', core='M7', variant='Release', date='2026-10-31T23:30:00-02:00')
        self.b = self.scan('b', name='控制器 M4', core='M4', variant='Debug', date='2026-11-01T12:00:00Z', diff=True)
        self.c = self.scan('c', name='旧工程', date=None)
        self.before = {p:sha256(p) for p in self.data.glob('scans/*/scan.db')}

    def scan(self, sid, *, name='控制器', core=None, variant=None, date=None, diff=False, degraded=False):
        folder=self.data/'scans'/sid;folder.mkdir(parents=True)
        report=dict(generated_at=date, analysis_status='INCOMPLETE', git_commit='c'*40,
                    findings=[dict(symbol_id='object',classification='UNKNOWN')])
        if diff:
            report['git_diff']=dict(pin=dict(base_ref='release',current_ref='feature',base_sha='a'*40,head_sha='b'*40,include_uncommitted=False))
        publish_scan(folder/'scan.db',dict(variables=[dict(symbol_id='object',name='真实身份',static_classification='UNKNOWN')]),
            report,scan_id=sid,project_id='project-'+sid,profile_id='profile-'+sid,
            provenance=dict(display_identity=dict(project_name=name,project_core=core,configured_target='target-'+sid,build_variant=variant),legacy_degraded=degraded))
        provider=EvidenceProvider(folder/'scan.db');store=ReviewStore(folder/'reviews.db',provider.metadata())
        store.append('object',provider.fingerprint('object'),reviewer='历史检索测试声明',decision='NEED_MORE_EVIDENCE',comment='仅测试持久化',handling_status='TODO',expected_heads=[])
        return folder

    def assert_originals(self):
        for p,digest in self.before.items():
            self.assertEqual(sha256(p),digest)
        self.assertEqual(list((self.data/'work/history').iterdir()),[])

    def test_complete_composite_filters_literal_and_utc_dates_without_graph_restore(self):
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('unbounded graph reconstruction')):
            value=history(self.data,project='控制器',profile='Release',core='M7',git='ccc',scan_mode='FULL',date_from='2026-11-01',date_to='2026-11-01')
            self.assertEqual([i['scan_id'] for i in value['items']],['a'])
            self.assertEqual(value['items'][0]['recorded_at_utc'],'2026-11-01T01:30:00.000000+00:00')
            self.assertEqual(history(self.data,git='feature',scan_mode='DIFF')['items'][0]['scan_id'],'b')
            self.assertEqual(history(self.data,project='%')['total'],0)
            self.assertEqual(history(self.data,project="' OR 1=1 --")['total'],0)
            self.assertEqual(history(self.data,core='m7')['total'],0)
            self.assertEqual(history(self.data,profile='target-b')['total'],1)
        self.assert_originals()

    def test_pagination_stable_order_unknown_dates_last_and_clamp_removed_page(self):
        first=history(self.data,limit=1)
        self.assertEqual(first['total'],3);self.assertEqual(first['items'][0]['scan_id'],'b');self.assertEqual(first['next_offset'],1)
        second=history(self.data,offset=1,limit=1);self.assertEqual(second['items'][0]['scan_id'],'a')
        last=history(self.data,offset=999,limit=1)
        self.assertEqual(last['offset'],2);self.assertEqual(last['items'][0]['scan_id'],'c');self.assertIsNone(last['next_offset'])
        self.assertEqual(history(self.data,date_from='2020-01-01')['total'],2)
        self.assert_originals()

    def test_unpublished_skipped_broken_scan_visible_and_manifest_cannot_rebind_state(self):
        (self.c/'storage.json').write_text('{}','utf-8')
        broken=self.data/'scans/z-broken';broken.mkdir();(broken/'scan.db').write_bytes(b'not sqlite')
        manifest=dict(format='ECRA_LOCAL_SCAN',state='STATIC_VALIDATED',scan_id='forged',completed_at='2027-01-01T00:00:00Z')
        (self.a/'manifest.json').write_text(json.dumps(manifest),'utf-8')
        value=history(self.data)
        self.assertEqual({i['scan_id'] for i in value['items']},{'a','b','z-broken'})
        failures=history(self.data,state='FAILED')['items'];self.assertEqual(len(failures),2)
        self.assertTrue(all(not i['can_open'] and not i['can_confirm'] and i['error'] for i in failures))
        self.assert_originals()

    def test_bound_local_publish_date_source_missing_core_and_degraded_actions(self):
        provider=EvidenceProvider(self.a/'scan.db')
        manifest=dict(provider.metadata(),format='ECRA_LOCAL_SCAN',state='STATIC_VALIDATED',completed_at='2026-11-02T09:00:00Z')
        (self.a/'manifest.json').write_text(json.dumps(manifest),'utf-8')
        degraded=self.scan('degraded',degraded=True,date='2026-11-02T10:00:00Z')
        row=history(self.data,state='STATIC_VALIDATED')['items'][0]
        self.assertEqual(row['recorded_at_utc'],'2026-11-02T09:00:00.000000+00:00');self.assertEqual(row['date_source'],'本机发布完成时间')
        row=next(i for i in history(self.data)['items'] if i['scan_id']=='degraded')
        self.assertTrue(row['can_open']);self.assertFalse(row['can_confirm']);self.assertIsNone(row['identity']['project_core'])
        self.assertEqual(history(self.data,core='M7')['total'],1)
        self.assert_originals()

    def test_bad_bounds_dates_modes_rejected_before_scratch_and_auth_required(self):
        for kwargs in [dict(limit=101),dict(limit=True),dict(offset=-1),dict(offset=2**64),dict(project='x'*257),dict(scan_mode='full'),
                       dict(date_from='20261101'),dict(date_to='2026-02-30'),dict(date_from='2026-11-02',date_to='2026-11-01')]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):history(self.data,**kwargs)
        self.assertFalse((self.data/'work/history').exists())
        app=create_app(self.data,token='history-token',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345') as client:
            self.assertEqual(client.get('/api/history').status_code,401)
            headers={'X-ECRA-Session':'history-token'}
            self.assertEqual(client.get('/api/history',headers={**headers,'Host':'other'}).status_code,403)
            self.assertEqual(client.get('/api/history',headers={**headers,'Origin':'http://other'}).status_code,403)
            response=client.get('/api/history?scan_mode=DIFF',headers=headers)
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['items'][0]['scan_id'],'b')
            self.assertEqual(client.get('/api/history?date_from=no',headers=headers).status_code,400)

    def test_paged_selected_archive_export_import_retains_identity_and_every_human_event(self):
        selected=history(self.data,profile='profile-b')['items'][0]
        package=self.root/'history-selected.ecra-report';export_report(self.data/'scans'/selected['scan_id'],package)
        result=import_report(package,self.root/'other')
        self.assertEqual(result['scan_id'],'b')
        source=EvidenceProvider(self.b/'scan.db');other=EvidenceProvider(self.root/'other/scans/b/scan.db')
        self.assertEqual(source.metadata(),other.metadata())
        def events(folder):
            with closing(sqlite3.connect(str(folder/'reviews.db'))) as conn:return list(conn.execute('SELECT event_id,payload FROM events ORDER BY event_id'))
        self.assertEqual(events(self.b),events(self.root/'other/scans/b'))
        self.assertEqual(history(self.root/'other')['items'][0]['identity'],selected['identity'])
        self.assert_originals()

    def test_oversized_identity_and_naive_datetime_not_silently_used_for_filter(self):
        self.scan('oversized',name='长'*20000,core='M4',date='2026-11-02T10:00:00')
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('no full graph')):
            row=next(i for i in history(self.data)['items'] if i['scan_id']=='oversized')
        self.assertIsNone(row['recorded_at_utc']);self.assertIsNone(row['identity']['project_name'])
        self.assertTrue(row['identity']['oversized_fields']);self.assertEqual(history(self.data,date_from='2026-11-02')['total'],0)
        self.assert_originals()


if __name__=='__main__':unittest.main()
