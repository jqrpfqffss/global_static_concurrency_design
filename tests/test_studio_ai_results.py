"""Original OpenCode outcome groups, readable symbols and bounded UI queries."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra.decisions import review_category
from ecra.scan_persistence import ai_page, append_runtime, runtime
from ecra.scan_store import EvidenceProvider, publish_scan


class StudioAIResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra AI results ')
        self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)/'data';self.out=self.data/'scans/ai-results';self.out.mkdir(parents=True)
        statuses=['CONFIRMED','LIKELY','REVIEWED_SAFE','FALSE_POSITIVE','NEED_MORE_CONTEXT',
                  'REVIEWED_SAFE','REVIEWED_SAFE','REVIEWED_SAFE']
        states=['DONE']*5+['TECH_FAILED','STALE','PENDING']
        variables=[dict(symbol_id='s'+str(i),name='变量'+str(i),static_classification='SUSPECT',
                        definition_file='Src/模块.c',definition_line=i+1) for i in range(len(states))]
        findings=[dict(finding_id='f'+str(i),symbol_id=v['symbol_id']) for i,v in enumerate(variables)]
        findings.append(dict(finding_id='gap'))
        publish_scan(self.out/'scan.db',dict(variables=variables),dict(findings=findings),scan_id='ai-results',project_id='p')
        self.rows=[dict(finding_id='f'+str(i),state=state,status=status,answer=dict(reason='原始依据'+str(i)))
                   for i,(state,status) in enumerate(zip(states,statuses))]
        self.rows.append(dict(finding_id='gap',state='DONE',status='NEED_MORE_CONTEXT'))
        append_runtime(self.out,{},self.rows)

    def test_original_verdict_groups_keep_failed_stale_and_pending_safety_unresolved(self):
        page=ai_page(self.out)
        self.assertEqual(page['groups'],dict(confirmed=1,likely=1,safe=2,unresolved=5))
        self.assertEqual(page['all_total'],9)
        self.assertEqual([r['outcome'] for r in page['items']],[review_category(r) for r in self.rows])
        safe=ai_page(self.out,outcome='safe')
        self.assertEqual([r['finding_id'] for r in safe['items']],['f2','f3'])

    def test_readable_names_sources_and_independent_gaps_are_lossless_projections(self):
        before=hashlib.sha256((self.out/'scan.db').read_bytes()).hexdigest()
        original=runtime(self.out)
        page=ai_page(self.out)
        self.assertEqual(page['items'][2]['name'],'变量2')
        self.assertEqual(page['items'][2]['definition_file'],'Src/模块.c')
        self.assertEqual(page['items'][2]['definition_line'],3)
        self.assertEqual(page['items'][2]['answer'],self.rows[2]['answer'])
        self.assertIsNone(page['items'][-1]['symbol_id'])
        self.assertEqual(runtime(self.out),original)
        self.assertEqual(hashlib.sha256((self.out/'scan.db').read_bytes()).hexdigest(),before)

    def test_filters_search_and_pages_apply_to_full_ledger_before_limit(self):
        page=ai_page(self.out,limit=1,outcome='safe',search='模块')
        self.assertEqual(page['total'],2);self.assertEqual(page['next_offset'],1)
        next_page=ai_page(self.out,offset=1,limit=1,outcome='safe',search='模块')
        self.assertEqual(next_page['items'][0]['name'],'变量3');self.assertIsNone(next_page['next_offset'])
        self.assertEqual(ai_page(self.out,search='变量7')['items'][0]['finding_id'],'f7')
        self.assertEqual(ai_page(self.out,search='s6')['items'][0]['name'],'变量6')
        self.assertEqual(ai_page(self.out,outcome='confirmed',search='变量7')['total'],0)

    def test_latest_event_and_snapshot_watermark_exclude_superseded_and_unpublished_verdicts(self):
        changed=[dict(row,state='DONE',status='REVIEWED_SAFE') if row['finding_id']=='f0' else row for row in self.rows]
        append_runtime(self.out,{},changed)
        self.assertEqual(ai_page(self.out)['groups']['safe'],3)
        with closing(sqlite3.connect(self.out/'reviews.db')) as conn,conn:
            row=dict(finding_id='f1',state='DONE',status='CONFIRMED')
            conn.execute('INSERT INTO ai_events(ordinal,finding_id,state,hash,payload) VALUES (?,?,?,?,?)',
                         (1,'f1','DONE','unpublished',json.dumps(row)))
        self.assertEqual(ai_page(self.out)['groups']['confirmed'],0)
        self.assertEqual(ai_page(self.out)['groups']['likely'],1)

    def test_current_paging_never_reconstructs_complete_facts_or_review_ledger(self):
        original=runtime
        def bounded(out,*,with_reviews=True):
            self.assertFalse(with_reviews,'current event paging must not load every receipt')
            return original(out,with_reviews=with_reviews)
        with patch('ecra.scan_persistence.runtime',side_effect=bounded),patch.object(EvidenceProvider,'load',side_effect=AssertionError('full evidence reconstruction')):
            self.assertEqual(len(ai_page(self.out,limit=1)['items']),1)

    def test_safe_sample_only_targets_also_show_variable_identity(self):
        out=self.data/'scans/sample-only';out.mkdir()
        publish_scan(out/'scan.db',dict(variables=[dict(symbol_id='safe-symbol',name='已筛除样本',static_classification='SAFE_PROVEN')]),
                     dict(findings=[],review_safe_samples=[dict(finding_id='sample-fid',symbol_id='safe-symbol')]),scan_id='sample-only',project_id='p')
        append_runtime(out,{},[dict(finding_id='sample-fid',state='DONE',status='REVIEWED_SAFE')])
        page=ai_page(out,outcome='safe')
        self.assertEqual(page['items'][0]['name'],'已筛除样本')
        self.assertEqual(page['items'][0]['symbol_id'],'safe-symbol')

    def test_legacy_snapshot_uses_identical_outcome_names_and_search(self):
        with closing(sqlite3.connect(self.out/'reviews.db')) as conn,conn:
            conn.execute('INSERT INTO ai_snapshots(hash,payload) VALUES (?,?)',('legacy',json.dumps(dict(reviews=self.rows))))
        page=ai_page(self.out,search='变量2',outcome='safe')
        self.assertEqual(page['groups']['safe'],2);self.assertEqual(page['total'],1)
        self.assertEqual(page['items'][0]['name'],'变量2')

    @unittest.skipUnless(importlib.util.find_spec('httpx') or importlib.util.find_spec('httpx2'),
                         'TestClient is a development dependency; Portable HTTP/UI is checked with a real server')
    def test_api_validates_filters_and_authenticates_result_queries(self):
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        client=TestClient(create_app(self.data,token='test-token',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345',
                          headers={'x-ecra-session':'test-token','origin':'http://127.0.0.1:12345'})
        url='/api/scans/ai-results/ai'
        response=client.get(url,params=dict(outcome='safe',search='变量',limit=1))
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['total'],2)
        self.assertEqual(client.get(url,headers={'x-ecra-session':'bad'}).status_code,401)
        for params in [dict(outcome='SAFE'),dict(search='x'*257),dict(limit=99999),dict(offset=-1)]:
            self.assertEqual(client.get(url,params=params).status_code,400)


if __name__=='__main__':unittest.main()
