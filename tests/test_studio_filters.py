import tempfile
import unittest
from pathlib import Path

from ecra.human_reviews import ReviewStore
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.scan_persistence import append_runtime
from ecra.studio.query import QueryService


class StudioFilterTests(unittest.TestCase):
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
