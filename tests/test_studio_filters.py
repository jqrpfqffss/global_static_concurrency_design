import tempfile
import unittest
from pathlib import Path

from ecra.human_reviews import ReviewStore
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.scan_persistence import append_runtime
from ecra.studio.query import QueryService


class StudioFilterTests(unittest.TestCase):
    def test_server_sorting_has_stable_pages_counts_and_independent_review_order(self):
        from ecra.report_package import sha256
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'data/scans/sorted';out.mkdir(parents=True)
            facts=dict(variables=[dict(symbol_id=str(index),name=name,definition_file=file,definition_line=line,
                static_classification=kind) for index,name,file,line,kind in [
                (0,'same','b.c',3,'SAFE_PROVEN'),(1,'zeta','a.c',9,'UNKNOWN'),
                (2,'same','a.c',2,'SUSPECT'),(3,'alpha','a.c',2,'UNKNOWN')]])
            publish_scan(out/'scan.db',facts,dict(findings=[]),scan_id='sorted',project_id='p')
            provider=EvidenceProvider(out/'scan.db');store=ReviewStore(out/'reviews.db',provider.metadata())
            store.append('2',provider.fingerprint('2'),reviewer='声明',decision='CONFIRMED_RISK',expected_heads=[])
            before=sha256(out/'scan.db');query=QueryService(out)
            ids=lambda **options:[row['symbol_id'] for row in query.symbols(**options)['items']]
            self.assertEqual(ids(),['2','1','3','0'])
            self.assertEqual(ids(sort='name'),['3','0','2','1'])
            self.assertEqual(ids(sort='name',order='desc'),['1','0','2','3'])
            self.assertEqual(ids(sort='definition'),['2','3','1','0'])
            self.assertEqual(ids(sort='review_priority'),['0','1','3','2'])
            first=query.symbols(sort='name',limit=2);second=query.symbols(sort='name',limit=2,offset=first['next_offset'])
            self.assertEqual([row['symbol_id'] for row in first['items']+second['items']],['3','0','2','1'])
            self.assertEqual(first['total'],second['total']);self.assertIsNone(second['next_offset'])
            self.assertEqual(ids(sort='definition',classification='UNKNOWN'),['3','1'])
            for options in [dict(sort='name; DROP TABLE symbols'),dict(order='desc;--'),dict(sort='unknown')]:
                with self.assertRaises(ValueError):query.symbols(**options)
            self.assertEqual(sha256(out/'scan.db'),before)

    def test_combined_filters_use_same_identity_and_independent_latest_decisions(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'data/scans/s1';out.mkdir(parents=True)
            facts=dict(variables=[dict(symbol_id=s,name=s,definition_file=file,static_classification='UNKNOWN',analysis_coverage=coverage)
                for s,file,coverage in [('x','a.c','PARTIAL'),('y','b.c','COMPLETE')]],
                accesses=[dict(symbol_id='x',function_id='main',contexts=['main','irq']),dict(symbol_id='y',function_id='worker',contexts=['irq'])])
            report=dict(findings=[dict(symbol_id=s,finding_id='f'+s) for s in ('x','y')],
                git_diff=dict(selected_symbol_ids=['x','y'],conservative_symbol_ids=['y'],pin=dict(base_ref='base',current_ref='HEAD'),impact_coverage='CONSERVATIVE'))
            publish_scan(out/'scan.db',facts,report,scan_id='s1',project_id='p')
            provider=EvidenceProvider(out/'scan.db');store=ReviewStore(out/'reviews.db',provider.metadata())
            store.append('x',provider.fingerprint('x'),reviewer='声明',decision='CONFIRMED_RISK',handling_status='FIXING',comment='待修复')
            append_runtime(out,report,[dict(finding_id='fx',state='TECH_FAILED'),dict(finding_id='fy',state='DONE')])
            query=QueryService(out)
            all_filters=dict(file='a.c',function='main',context='main',coverage='PARTIAL',classification='UNKNOWN',
                human_decision='CONFIRMED_RISK',handling_status='FIXING',ai_state='TECH_FAILED',diff='direct')
            self.assertEqual([row['symbol_id'] for row in query.symbols(**all_filters)['items']],['x'])
            for key,value in [('file','b.c'),('function','worker'),('context','unresolved'),('ai_state','DONE'),('diff','conservative'),('handling_status','CLOSED')]:
                changed=dict(all_filters,**{key:value});self.assertEqual(query.symbols(**changed)['total'],0,key)
            self.assertEqual(query.symbols(ai_state='DONE')['items'][0]['symbol_id'],'y')
            append_runtime(out,report,[dict(finding_id='fx',state='DONE'),dict(finding_id='fy',state='DONE')])
            self.assertEqual(query.symbols(ai_state='TECH_FAILED')['total'],0)
            self.assertEqual(query.symbols(ai_state='DONE')['total'],2)
            self.assertEqual(query.symbols(context="irq' OR 1=1 --")['total'],0)
            self.assertEqual(query.diff_summary()['conservative_symbol_ids_count'],1)
