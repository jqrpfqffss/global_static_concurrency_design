from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.studio.comparison import compare_archives
from ecra.studio.server import create_app


class StudioComparisonTests(unittest.TestCase):
    """Declared database fixtures; no native/G1/performance acceptance claim."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ecra comparison 中文 ')
        self.addCleanup(self.tmp.cleanup);self.data=Path(self.tmp.name)/'data'

    def scan(self, sid, variables=None, *, project='p', profile='release', facts=None, report=None, degraded=False):
        folder=self.data/'scans'/sid;folder.mkdir(parents=True)
        publish_scan(folder/'scan.db',facts or dict(variables=variables or [self.symbol('s')]),
                     report or dict(findings=[],analysis_status='INCOMPLETE'),scan_id=sid,project_id=project,
                     profile_id=profile,provenance=dict(legacy_degraded=degraded))
        provider=EvidenceProvider(folder/'scan.db');store=ReviewStore(folder/'reviews.db',provider.metadata())
        first=provider.symbols(limit=1)['items'][0]['symbol_id']
        store.append(first,provider.fingerprint(first),reviewer='测试声明',decision='NEED_MORE_EVIDENCE')
        return folder

    @staticmethod
    def symbol(sid, classification='UNKNOWN'):
        return dict(symbol_id=sid,name='相同显示名',static_classification=classification,definition_file='a.c',definition_line=3)

    def test_identical_archived_facts_and_report_do_not_inherit_or_modify_decisions(self):
        a=self.scan('a');b=self.scan('b');before={p:sha256(p) for p in self.data.glob('scans/*/*')}
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('No full graph restore')):
            value=compare_archives(a,b)
        self.assertEqual(value['counts'],{'EVIDENCE_IDENTICAL':1});self.assertEqual(value['items'][0]['symbol_id'],'s')
        self.assertTrue(value['profile_equal']);self.assertIn('不自动继承',value['note'])
        self.assertEqual({p:sha256(p) for p in before},before)

    def test_exact_canonical_identity_not_name_and_classification_change(self):
        a=self.scan('a',[self.symbol('tu:a::static'),self.symbol('shared','SUSPECT')])
        b=self.scan('b',[self.symbol('tu:b::static'),self.symbol('shared','SAFE')])
        value=compare_archives(a,b);rows={row['symbol_id']:row for row in value['items']}
        self.assertEqual(rows['tu:a::static']['change'],'NOT_OBSERVED');self.assertIsNone(rows['tu:a::static']['after_node'])
        self.assertEqual(rows['tu:b::static']['change'],'ADDED');self.assertIsNone(rows['tu:b::static']['before_node'])
        self.assertEqual(rows['shared']['change'],'EVIDENCE_CHANGED')
        self.assertEqual((rows['shared']['before_classification'],rows['shared']['after_classification']),('SUSPECT','SAFE'))
        self.assertIn('不等于已修复',value['note'])

    def test_any_full_context_or_report_change_conservatively_changes_all_shared_objects(self):
        facts=dict(variables=[self.symbol('s')],calls=[dict(caller='main',callee='f'),dict(caller='irq',callee='f')])
        a=self.scan('a',facts=facts);b=self.scan('b',facts=dict(facts,calls=list(reversed(facts['calls']))))
        c=self.scan('c',facts=facts,report=dict(findings=[],analysis_status='INCOMPLETE',nvic=dict(unknown=True)))
        self.assertEqual(compare_archives(a,b)['counts'],{'EVIDENCE_CHANGED':1})
        self.assertEqual(compare_archives(a,c)['counts'],{'EVIDENCE_CHANGED':1})
        self.assertFalse(next(row for row in compare_archives(a,b)['roots'] if row['name']=='facts')['identical'])

    def test_literal_search_filtered_totals_and_stable_page_direction(self):
        a=self.scan('a',[self.symbol('A'),self.symbol('B'),self.symbol('c_%')])
        b=self.scan('b',[self.symbol('B'),self.symbol('D'),self.symbol('c_%')])
        first=compare_archives(a,b,limit=2);last=compare_archives(a,b,offset=first['next_offset'],limit=2)
        self.assertEqual([row['symbol_id'] for row in first['items']+last['items']],['A','B','D','c_%'])
        self.assertEqual(first['total'],4);self.assertIsNone(last['next_offset'])
        self.assertEqual(compare_archives(a,b,search='_%')['total'],1)
        self.assertEqual(compare_archives(a,b,change='ADDED')['total'],1)
        self.assertEqual(compare_archives(a,b,search="' OR 1=1--")['total'],0)
        self.assertEqual(compare_archives(b,a,change='ADDED')['items'][0]['symbol_id'],'A')

    def test_different_project_same_scan_degraded_pending_and_wrong_binding_rejected(self):
        a=self.scan('a');b=self.scan('b',project='other');c=self.scan('c',degraded=True);d=self.scan('d')
        for left,right in [(a,a),(a,b),(a,c)]:
            with self.subTest(right=right.name),self.assertRaises(ValueError):compare_archives(left,right)
        (d/'storage.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'未发布'):compare_archives(a,d)
        binding=EvidenceProvider(d/'scan.db').metadata()
        (d/'manifest.json').write_text(json.dumps(dict(binding,format='ECRA_LOCAL_SCAN',state='FAILED')))
        with self.assertRaisesRegex(ValueError,'未校验'):compare_archives(a,d)
        (d/'manifest.json').write_text(json.dumps(dict(binding,format='ECRA_LOCAL_SCAN',state='STATIC_VALIDATED',facts_hash='0'*64)))
        with self.assertRaisesRegex(ValueError,'不一致'):compare_archives(a,d)
        (d/'storage.json').unlink();(d/'manifest.json').unlink();moved=d.with_name('different-id');d.rename(moved)
        with self.assertRaisesRegex(ValueError,'身份不一致'):compare_archives(a,moved)

    def test_profile_boundary_and_validation_never_become_current_source_proof(self):
        a=self.scan('a');b=self.scan('b',profile='debug');self.assertFalse(compare_archives(a,b)['profile_equal'])
        self.assertIn('不表示当前源码有效',compare_archives(a,b)['note'])
        for kwargs in [dict(limit=0),dict(limit=101),dict(offset=-1),dict(offset=2**63),dict(search='x'*257),dict(change='SAFE')]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):compare_archives(a,b,**kwargs)

    def test_authenticated_api_rejects_paths_and_preserves_all_original_bytes(self):
        a=self.scan('a');b=self.scan('b');before={p:sha256(p) for p in self.data.glob('scans/*/*')}
        with TestClient(create_app(self.data,token='test-token',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345') as client:
            self.assertEqual(client.get('/api/history/compare?base=a&current=b').status_code,401)
            client.headers['x-ecra-session']='test-token'
            result=client.get('/api/history/compare',params=dict(base='a',current='b',limit=1))
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['total'],1)
            for bad in ['../a','a/../../outside','missing']:
                self.assertEqual(client.get('/api/history/compare',params=dict(base=bad,current='b')).status_code,400)
        self.assertEqual({p:sha256(p) for p in before},before)

    def test_twenty_thousand_object_page_is_bounded_without_full_graph_loading(self):
        variables=[self.symbol('fixture::'+str(i).zfill(5)) for i in range(20007)]
        a=self.scan('a',variables);b=self.scan('b',variables)
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('No full graph restore')):
            value=compare_archives(a,b,offset=20000,limit=50)
        self.assertEqual(value['total'],20007);self.assertEqual(len(value['items']),7)
        self.assertEqual(value['counts'],{'EVIDENCE_IDENTICAL':20007});self.assertIsNone(value['next_offset'])


if __name__=='__main__':unittest.main()
