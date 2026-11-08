"""Bad display/archive metadata must not conceal independently valid work."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from fastapi.testclient import TestClient

from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report,sha256
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.studio.server import create_app,DISPLAY_MANIFEST_LIMIT


class StudioManifestErrorTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='ecra manifest boundary ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.data=self.root/'data'
        self.paths={};self.providers={};self.stores={}
        for sid in ('bad','healthy'):
            path=self.data/'scans'/sid;path.mkdir(parents=True)
            publish_scan(path/'scan.db',dict(variables=[dict(symbol_id='s',name='shared',static_classification='UNKNOWN')]),
                         dict(findings=[dict(symbol_id='s',finding_id='f')]),scan_id=sid,project_id='project-'+sid)
            provider=EvidenceProvider(path/'scan.db');store=ReviewStore(path/'reviews.db',provider.metadata())
            store.append('s',provider.fingerprint('s'),reviewer='isolated fixture',decision='CONFIRMED_RISK',comment='protocol test, not engineering sign-off')
            self.paths[sid]=path;self.providers[sid]=provider;self.stores[sid]=store
        self.originals={sid:(sha256(self.paths[sid]/'scan.db'),self.stores[sid].history()) for sid in self.paths}
        self.original_review_hashes={sid:sha256(self.paths[sid]/'reviews.db') for sid in self.paths}
        self.manifest=self.paths['bad']/'manifest.json'
        app=create_app(self.data,token='manifest-test',authority='testserver')
        self.client=TestClient(app,headers={'x-ecra-session':'manifest-test','origin':'http://testserver'},raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def valid_manifest(self,**changes):
        # Both native and derived finalize paths emit this publication state;
        # it intentionally differs from the immutable DB's UNVERIFIED binding.
        value=dict(self.providers['bad'].metadata(),format='ECRA_LOCAL_SCAN',version=1)
        value.update(state='STATIC_VALIDATED',**changes)
        return value

    def assert_originals(self):
        for sid,(static,events) in self.originals.items():
            self.assertEqual(sha256(self.paths[sid]/'scan.db'),static)
            self.assertEqual(self.stores[sid].history(),events)
            self.assertEqual(sha256(self.paths[sid]/'reviews.db'),self.original_review_hashes[sid])

    def assert_bad_manifest_is_isolated(self,raw):
        self.manifest.write_bytes(raw)
        result=self.client.get('/api/scans');self.assertEqual(result.status_code,200,result.text)
        rows={item['scan_id']:item for item in result.json()['items']}
        self.assertEqual(rows['bad']['state'],'FAILED')
        self.assertFalse(rows['bad']['can_open'])
        self.assertIn('清单',rows['bad']['error']);self.assertIn('保留',rows['bad']['error'])
        self.assertNotEqual(rows['healthy']['state'],'FAILED')
        self.assertTrue(rows['healthy']['can_open'])
        history=self.client.get('/api/history');self.assertEqual(history.status_code,200,history.text)
        entries={item['scan_id']:item for item in history.json()['items']}
        self.assertEqual(entries['bad']['state'],'FAILED')
        self.assertFalse(entries['bad']['can_open']);self.assertFalse(entries['bad']['can_confirm'])
        self.assertIn('清单',entries['bad']['error'])
        self.assertTrue(entries['healthy']['can_open'])
        detail=self.client.get('/api/scans/bad/summary')
        self.assertEqual(detail.status_code,400,detail.text)
        self.assertIn('清单',detail.json()['error'])
        self.assertEqual(self.client.get('/api/scans/healthy/summary').status_code,200)
        self.assertEqual(self.manifest.read_bytes(),raw)
        self.assert_originals()

    def test_wrong_json_container_and_syntax_are_isolated_for_list_and_detail(self):
        for raw in (b'[]',b'null',b'1',b'"text"',b'{truncated',b'\xff'):
            with self.subTest(raw=raw):self.assert_bad_manifest_is_isolated(raw)

    def test_identity_state_format_and_version_cannot_rebind_display_status(self):
        good=self.valid_manifest()
        cases=[dict(good,scan_id='healthy'),dict(good,project_id='other'),dict(good,facts_hash='0'*64),
               dict(good,report_hash='0'*64),dict(good,state=None),dict(good,state=[]),dict(good,state=''),
               dict(good,state='UNVERIFIED'),dict(good,state='COMPLETE'),dict(good,state='INCOMPLETE'),
               dict(good,format=[]),dict(good,format='FUTURE_FORMAT'),dict(good,version=True),dict(good,version=999),
               {k:v for k,v in good.items() if k!='state'}]
        for value in cases:
            with self.subTest(value=value):self.assert_bad_manifest_is_isolated(json.dumps(value).encode())

    def test_oversized_manifest_is_bounded_and_valid_local_and_imported_manifests_still_open(self):
        self.assert_bad_manifest_is_isolated(b' '*(DISPLAY_MANIFEST_LIMIT+1))
        portable=dict(self.providers['bad'].metadata(),format='ECRA_REPORT',version=1)
        portable.pop('state')  # ordinary exported packages do not require it
        for value,mode in [(self.valid_manifest(extra_future={'preserved':True},run_state='INCOMPLETE'),'LOCAL_SNAPSHOT'),
                           (portable,'OFFLINE_ARCHIVE'),(dict(portable,state='STATIC_VALIDATED'),'OFFLINE_ARCHIVE')]:
            with self.subTest(mode=mode):
                raw=json.dumps(value).encode();self.manifest.write_bytes(raw)
                catalog=self.client.get('/api/scans');self.assertEqual(catalog.status_code,200,catalog.text)
                row=next(item for item in catalog.json()['items'] if item['scan_id']=='bad')
                self.assertEqual(row['mode'],mode);self.assertTrue(row['can_open'])
                detail=self.client.get('/api/scans/bad/summary');self.assertEqual(detail.status_code,200,detail.text)
                self.assertEqual(detail.json()['mode'],mode)
                self.assertEqual(detail.json()['binding']['state'],'STATIC_VALIDATED' if mode=='LOCAL_SNAPSHOT' else 'UNVERIFIED')
                history=self.client.get('/api/history');self.assertEqual(history.status_code,200,history.text)
                entry=next(item for item in history.json()['items'] if item['scan_id']=='bad')
                self.assertEqual(entry['mode'],mode);self.assertTrue(entry['can_open'])
                self.assertEqual(entry['state'],'STATIC_VALIDATED' if mode=='LOCAL_SNAPSHOT' else 'UNVERIFIED')
                self.assertEqual(self.manifest.read_bytes(),raw)
                self.assert_originals()

    def test_history_and_list_share_the_accepted_four_mib_manifest_budget(self):
        value=dict(self.providers['bad'].metadata(),format='ECRA_REPORT',version=1,
                   extra_future_metadata='x'*(1024*1024+16))
        raw=json.dumps(value).encode();self.assertGreater(len(raw),1024*1024)
        self.assertLess(len(raw),DISPLAY_MANIFEST_LIMIT);self.manifest.write_bytes(raw)
        for path in ('/api/scans','/api/history'):
            response=self.client.get(path);self.assertEqual(response.status_code,200,response.text)
            row=next(item for item in response.json()['items'] if item['scan_id']=='bad')
            self.assertEqual(row['state'],'UNVERIFIED');self.assertTrue(row['can_open'])
        self.assertEqual(self.client.get('/api/scans/bad/summary').status_code,200)
        self.assertEqual(self.manifest.read_bytes(),raw);self.assert_originals()

    def archive(self,manifest):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_STORED) as package:
            package.writestr('manifest.json',manifest)
        return buffer.getvalue()

    def test_bad_zip_truncated_zip_and_crc_have_actionable_import_errors_without_publication(self):
        valid=self.archive(b'{"format":"ECRA_REPORT"}')
        modified=bytearray(valid);start=valid.index(b'{"format":"ECRA_REPORT"}');modified[start]^=1
        for raw in (b'PK intentionally damaged package',valid[:-20],bytes(modified)):
            with self.subTest(size=len(raw)):
                response=self.client.post('/api/import',content=raw)
                self.assertEqual(response.status_code,400,response.text);error=response.json()
                self.assertEqual(error['code'],'INVALID_REPORT_ARCHIVE')
                self.assertIn('导入阶段',error['error']);self.assertIn('未发布',error['error'])
                self.assertIn('已有扫描与人工记录保留',error['error']);self.assertIn('重新获取完整',error['error'])
                self.assertTrue(error['detail']);self.assertNotIn('manifest-test',response.text)
                self.assertEqual({p.name for p in (self.data/'scans').iterdir()},{'bad','healthy'})
                self.assert_originals()

    def test_archive_json_container_error_is_not_an_internal_error_and_normal_import_remains_idempotent(self):
        for raw in (b'[]',b'null',b'"object expected"',b'{broken'):
            with self.subTest(raw=raw):
                response=self.client.post('/api/import',content=self.archive(raw))
                self.assertEqual(response.status_code,400,response.text)
                self.assertIn('结果包导入阶段',response.json()['error']);self.assertIn('保留',response.json()['error'])
                self.assert_originals()
        package=self.root/'valid.ecra-report';export_report(self.paths['healthy'],package)
        response=self.client.post('/api/import',content=package.read_bytes())
        self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.json()['repeated'])
        self.assert_originals()

    def test_import_into_an_existing_broken_manifest_refuses_merge_with_clear_independent_root_recovery(self):
        package=self.root/'backup.ecra-report';export_report(self.paths['bad'],package)
        before=package.read_bytes();raw=b'[]';self.manifest.write_bytes(raw)
        response=self.client.post('/api/import',content=before)
        self.assertEqual(response.status_code,400,response.text)
        message=response.json()['error'];self.assertIn('导入阶段',message);self.assertIn('本次未合并',message)
        self.assertIn('新的独立数据目录',message);self.assertIn('人工记录保留',message)
        self.assertEqual(self.manifest.read_bytes(),raw);self.assertEqual(package.read_bytes(),before)
        self.assert_originals()

    def test_legacy_manifest_does_not_adopt_a_state_or_identity_outside_its_db_binding(self):
        # The converter has two offline states. A display manifest cannot
        # promote either to a current-source publication or another identity.
        good=dict(self.providers['bad'].metadata(),format='ECRA_LEGACY_IMPORT',version=1)
        for value in (dict(good,state='STATIC_VALIDATED'),dict(good,state='LEGACY_READ_ONLY'),
                      dict(good,state='COMPLETE'),dict(good,state=None),
                      {key:item for key,item in good.items() if key!='state'},
                      dict(good,scan_id='healthy'),dict(good,project_id='other'),dict(good,facts_hash='0'*64)):
            with self.subTest(value=value):
                self.assert_bad_manifest_is_isolated(json.dumps(value).encode())

    def assert_legacy_api_contract(self,client,scan_id,*,degraded):
        state='UNVERIFIED' if degraded else 'LEGACY_READ_ONLY'
        catalog=client.get('/api/scans');self.assertEqual(catalog.status_code,200,catalog.text)
        row=next(item for item in catalog.json()['items'] if item['scan_id']==scan_id)
        self.assertEqual(row['state'],state);self.assertEqual(row['mode'],'OFFLINE_ARCHIVE');self.assertTrue(row['can_open'])
        summary=client.get('/api/scans/'+scan_id+'/summary')
        self.assertEqual(summary.status_code,200,summary.text);value=summary.json()
        self.assertEqual(value['binding']['state'],state)
        self.assertEqual(value['mode'],'OFFLINE_ARCHIVE');self.assertEqual(value['legacy_degraded'],degraded)
        self.assertEqual(value['can_confirm'],not degraded);self.assertFalse(value['can_review'])
        self.assertTrue(value['legacy_warning'])
        self.assertEqual(value['static_counts'],{} if degraded else {'UNKNOWN':1})
        self.assertEqual(value['total'],0 if degraded else 1)
        history=client.get('/api/history');self.assertEqual(history.status_code,200,history.text)
        item=next(row for row in history.json()['items'] if row['scan_id']==scan_id)
        self.assertTrue(item['can_open']);self.assertEqual(item['state'],state)
        self.assertEqual(item['can_confirm'],not degraded);self.assertEqual(item['mode'],'OFFLINE_ARCHIVE')
        if degraded:
            denied=client.post('/api/scans/'+scan_id+'/human',json=dict(symbol_id='invented',
                reviewer='isolated fixture',decision='CONFIRMED_SAFE',comment='must remain forbidden'))
            self.assertEqual(denied.status_code,400,denied.text)
            self.assertIn('未验证原件',denied.json()['error'])

    def test_actual_full_and_degraded_legacy_publishers_list_detail_history_and_package_roundtrip(self):
        from tests.test_legacy_import import LegacyImportTests
        for degraded in (False,True):
            with self.subTest(degraded=degraded):
                case=LegacyImportTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
                if degraded:(case.old/'facts.json').unlink()
                originals=case.original_hashes()
                # The real synchronous converter has fully returned before
                # browsing or teardown. No deadline can delete its active lease.
                result=case.convert(allow_degraded=degraded)
                scan=case.data/'scans'/result['scan_id'];provider=EvidenceProvider(scan/'scan.db')
                manifest=(scan/'manifest.json').read_bytes();static=sha256(scan/'scan.db')
                self.assertEqual(json.loads(manifest)['format'],'ECRA_LEGACY_IMPORT')
                self.assertEqual(provider.metadata()['state'],'UNVERIFIED' if degraded else 'LEGACY_READ_ONLY')
                with TestClient(create_app(case.data,token='legacy-publisher',authority='testserver'),
                    headers={'x-ecra-session':'legacy-publisher','origin':'http://testserver'}) as client:
                    self.assert_legacy_api_contract(client,scan.name,degraded=degraded)
                package=case.base/'legacy.ecra-report';export_report(scan,package)
                with zipfile.ZipFile(package) as archive:
                    self.assertEqual(json.loads(archive.read('manifest.json'))['format'],'ECRA_REPORT')
                viewer=case.base/'independent-viewer'
                with TestClient(create_app(viewer,token='legacy-package',authority='testserver'),
                    headers={'x-ecra-session':'legacy-package','origin':'http://testserver'}) as client:
                    imported=client.post('/api/import',content=package.read_bytes())
                    self.assertEqual(imported.status_code,200,imported.text)
                    self.assert_legacy_api_contract(client,scan.name,degraded=degraded)
                self.assertEqual(EvidenceProvider(viewer/'scans'/scan.name/'scan.db').roots(),provider.roots())
                self.assertEqual(case.original_hashes(),originals)
                self.assertEqual(sha256(scan/'scan.db'),static);self.assertEqual((scan/'manifest.json').read_bytes(),manifest)

    def assert_actual_publisher_opens(self,data,out):
        provider=EvidenceProvider(out/'scan.db');binding=provider.metadata()
        raw=(out/'manifest.json').read_bytes();manifest=json.loads(raw)
        self.assertEqual(binding['state'],'UNVERIFIED')
        self.assertEqual(manifest['state'],'STATIC_VALIDATED');self.assertEqual(manifest['run_state'],'INCOMPLETE')
        before=sha256(out/'scan.db')
        with TestClient(create_app(data,token='publisher-test',authority='testserver'),
                        headers={'x-ecra-session':'publisher-test'}) as client:
            summary=client.get('/api/scans/'+out.name+'/summary')
            self.assertEqual(summary.status_code,200,summary.text)
            self.assertEqual(summary.json()['binding']['state'],'STATIC_VALIDATED')
            rows=client.get('/api/scans').json()['items']
            row=next(row for row in rows if row['scan_id']==out.name)
            self.assertEqual(row['state'],'STATIC_VALIDATED');self.assertTrue(row['can_open'])
            history=client.get('/api/history');self.assertEqual(history.status_code,200,history.text)
            row=next(row for row in history.json()['items'] if row['scan_id']==out.name)
            self.assertEqual(row['state'],'STATIC_VALIDATED');self.assertTrue(row['can_open'])
        self.assertEqual(sha256(out/'scan.db'),before);self.assertEqual((out/'manifest.json').read_bytes(),raw)

    def test_actual_native_publisher_retains_unverified_db_and_validates_local_manifest_separately(self):
        from tests import test_canonical_scan as fixtures
        case=fixtures.CanonicalScanTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        out,_=case.run_scan()
        self.assert_actual_publisher_opens(case.data,out)

    def test_actual_derived_publisher_retains_unverified_db_and_validates_local_manifest_separately(self):
        from tests import test_multicore_publication as fixtures
        cls=fixtures.MulticorePublicationTests;cls.setUpClass();self.addCleanup(cls.doClassCleanups)
        case=cls(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        out,_=case.run_combine(name='derived-state-positive')
        self.assert_actual_publisher_opens(case.data,out)


if __name__=='__main__':unittest.main()
