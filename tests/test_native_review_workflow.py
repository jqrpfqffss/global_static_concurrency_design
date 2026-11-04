"""Canonical review lifecycle with synthetic transport, not model reasoning."""
import contextlib
import io
import json
from pathlib import Path
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from ecra.common import read_json,write_json
from ecra.report_package import export_report,import_report,sha256
from ecra.scan_persistence import runtime
from ecra.scan_store import EvidenceProvider
from ecra.workflow import saved_run
from tests import test_canonical_scan as fixtures
from tests.test_review_contract import answer_for


class NativeReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        case=fixtures.CanonicalScanTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups);self.case=case
        (case.root/'main.c').write_text('int shared,other;\nvoid ISR(void){shared++;other++;}\nint main(void){shared++;other++;return shared+other;}\n',encoding='utf-8')
        raw=read_json(case.config);raw['review'].update(workers=2,retries=0);write_json(case.config,raw)
        self.out,self.cfg=case.run_scan();self.before=sha256(self.out/'scan.db');self.calls=[]

    def response(self,argv,**kwargs):
        packet=read_json(Path(argv[argv.index('--file')+1]));fid=packet['finding_id'];self.calls.append(fid)
        value=answer_for(fid=fid,variable=packet['variable']['qualified_name'])
        value['evidence']=[dict(file='main.c',line=2,claim='仅用于协议自动化测试的真实访问位置。')]
        return CompletedProcess(argv,0,json.dumps(value,ensure_ascii=False),'')

    def review(self,respond=None,**options):
        with (patch.object(EvidenceProvider,'load',side_effect=AssertionError('Whole authority reconstruction forbidden')),
              patch('ecra.review.resolve_command',return_value=['synthetic-test-executor']),
              patch('ecra.review.execute',side_effect=respond or self.response),contextlib.redirect_stdout(io.StringIO())):
            return saved_run(self.case.root,self.case.config,_out=self.out,**options)

    def test_parallel_review_failed_only_resume_receipts_package_and_static_bytes(self):
        failed=[]
        def first(argv,**kwargs):
            packet=read_json(Path(argv[argv.index('--file')+1]))
            if packet['variable']['qualified_name']=='other':
                failed.append(packet['finding_id']);self.calls.append(packet['finding_id'])
                return CompletedProcess(argv,1,'synthetic transport failure, not a semantic verdict','')
            return self.response(argv,**kwargs)
        from ecra.scan_diagnostics import ScanDiagnostics
        diagnostics=ScanDiagnostics(self.case.base/'review-diagnostics');diagnostics.consumer='REVIEW'
        try:
            self.assertIn(self.review(first),(0,1,2))
            self.assertEqual((diagnostics.completed_units,diagnostics.total_units),(2,2))
            self.assertIn('复核后完整输入重验',diagnostics.current['stage'])
        finally:diagnostics.close()
        initial=runtime(self.out)['reviews']
        self.assertEqual(sum(row['state']=='TECH_FAILED' for row in initial),1)
        self.assertEqual(sum(row['state']=='DONE' for row in initial),1)
        self.calls=[];self.assertIn(self.review(failed_only=True),(0,1,2));self.assertEqual(self.calls,failed)
        self.assertTrue(all(row['state']=='DONE' for row in runtime(self.out)['reviews']))
        self.assertEqual(sha256(self.out/'scan.db'),self.before)
        package=self.case.base/'reviewed.ecra-report';export_report(self.out,package)
        imported=import_report(package,self.case.base/'offline');restored=self.case.base/'offline/scans'/imported['scan_id']
        self.assertEqual(runtime(restored)['reviews'],runtime(self.out)['reviews'])

    def test_interrupt_and_rereview_keep_history_and_original_authority(self):
        raw=read_json(self.case.config);raw['review']['workers']=1;write_json(self.case.config,raw)
        self.assertEqual(self.review(lambda *args,**kwargs:(_ for unused in ()).throw(KeyboardInterrupt())),130)
        self.assertEqual(runtime(self.out)['report']['run_status'],'INTERRUPTED')
        self.assertEqual(sha256(self.out/'scan.db'),self.before)
        self.assertIn(self.review(),(0,1,2))
        self.assertTrue(all(row['state']=='DONE' for row in runtime(self.out)['reviews']))
        self.assertEqual(sha256(self.out/'scan.db'),self.before)
