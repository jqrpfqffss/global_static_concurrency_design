"""Original summary functions vs metadata refresh; no model/G2 claim."""
import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import write_json
from ecra.native_consumers import runtime_inputs
from ecra.report import generate
from ecra.report_package import sha256
from ecra.scan_persistence import runtime,persist
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.workflow import clean_report,saved_run
from ecra.review_integrity import review_targets
from tests import test_canonical_scan as fixture
from tests.test_review_contract import answer_for


class NativeRefreshTests(unittest.TestCase):
    def real_scan(self):
        case=fixture.CanonicalScanTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        out,cfg=case.run_scan();return case,out,cfg

    def test_complete_runtime_payloads_equal_original_functions_across_semantic_statuses_and_diff(self):
        case,out,cfg=self.real_scan();provider=EvidenceProvider(out/'scan.db')
        facts=provider.load('facts');report=clean_report(provider.load('report'))
        for diff in (False,True):
            report=copy.deepcopy(report)
            if diff:report['git_diff']=dict(selected_symbol_ids=[facts['variables'][0]['symbol_id']],fallback_reasons=['保守扩大测试'])
            for status in ('PENDING','CONFIRMED','LIKELY','REVIEWED_SAFE','FALSE_POSITIVE','NEED_MORE_CONTEXT','TECH_FAILED'):
                with self.subTest(diff=diff,status=status):
                    old=case.base/('old-'+str(diff)+'-'+status);new=case.base/('new-'+str(diff)+'-'+status)
                    for destination in (old,new):
                        destination.mkdir();publish_scan(destination/'scan.db',facts,report,scan_id='s',project_id='p')
                    before=sha256(new/'scan.db')
                    reviews=[]
                    for finding in review_targets(report):
                        row=dict(finding_id=finding['finding_id'],state=status if status in {'PENDING','TECH_FAILED'} else 'DONE',
                            static_classification=finding.get('static_classification'))
                        if row['state']=='DONE':row.update(status=status,answer=answer_for(status,finding['finding_id']))
                        reviews.append(row)
                    full=copy.deepcopy(report);full['run_status']='REVIEW_COMPLETE'
                    generate(old,copy.deepcopy(facts),full,copy.deepcopy(reviews))
                    with patch.object(EvidenceProvider,'load',side_effect=AssertionError('Full authority reconstruction forbidden')):
                        small_facts,small_report=runtime_inputs(new);small_report['run_status']='REVIEW_COMPLETE'
                        generate(new,small_facts,small_report,copy.deepcopy(reviews),_runtime_only=True)
                    self.assertEqual(runtime(old),runtime(new))
                    self.assertEqual(sha256(new/'scan.db'),before)

    def test_real_saved_report_and_source_change_refresh_never_restore_full_authority(self):
        case,out,cfg=self.real_scan();before=sha256(out/'scan.db')
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('Full authority reconstruction forbidden')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIn(saved_run(case.root,case.config,render_only=True,_out=out),(0,1,2))
                (case.root/'main.c').write_text('int changed;\n',encoding='utf-8')
                self.assertEqual(saved_run(case.root,case.config,render_only=True,_out=out),2)
        self.assertEqual(sha256(out/'scan.db'),before)
        self.assertEqual(runtime(out)['report']['run_status'],'INCOMPLETE')

    def test_metadata_cannot_create_or_replace_a_missing_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);write_json(out/'storage.json',dict(version=1,scan_id='s',project_id='p'))
            with self.assertRaisesRegex(ValueError,'不能.*权威库'):
                generate(out,dict(variables=[]),{},[],_runtime_only=True)
            with self.assertRaisesRegex(ValueError,'不能.*静态事实'):
                persist(out,dict(variables=[]),{},[],_existing_only=True)
            self.assertFalse((out/'scan.db').exists());self.assertFalse((out/'reviews.db').exists())
