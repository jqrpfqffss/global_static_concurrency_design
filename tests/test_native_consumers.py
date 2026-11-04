"""Exact old digest/status contracts without complete native reconstruction."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ecra.native_consumers import clean_report_digest,status_report
from ecra.scan_store import publish_scan,EvidenceProvider
from ecra.workflow import clean_report,status,saved_report_digest,read_saved_json
from tests import test_canonical_scan as fixtures


class NativeConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA streamed report ');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)

    def publish(self,report,name='case'):
        path=self.base/name/'scan.db';path.parent.mkdir()
        publish_scan(path,dict(variables=[],accesses=[]),report,scan_id=name,project_id='p')
        return path

    def digest(self,path):
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full reconstruction forbidden')):
            return clean_report_digest(path,work=self.base/'scratch')

    def test_existing_clean_report_digest_all_fields_scalar_types_order_and_shared_nodes(self):
        shared=dict(flag=True,number=1,zero=-0.0,positive=0.0,huge=2**160,
                    text='引号"\n反斜杠\\\t😀',array=[False,0,None,''])
        report=dict(findings=[dict(finding_id='F-1',status='CONFIRMED',review={'answer':'old'},
                    static_classification='UNKNOWN',evidence=[shared,shared]),
                    dict(finding_id='F-2',accesses=[shared],z_after_status=3)],coverage={},
                    analysis_status='INCOMPLETE',nested=dict(z=shared,a=shared),
                    generated_at='retained',fingerprint='retained',review_summary={'ignored':True})
        expected=saved_report_digest(clean_report(report),encoding='ECRA_MERKLE_V1')
        self.assertEqual(self.digest(self.publish(report)),expected)
        for key,value in [('flag',1),('zero',0.0),('array',[0,False,None,'']),('text','different')]:
            with self.subTest(key=key):
                other=copy.deepcopy(report);other['nested']['z'][key]=value
                actual=self.digest(self.publish(other,'changed-'+key))
                self.assertNotEqual(actual,expected)
                self.assertEqual(actual,saved_report_digest(clean_report(other),encoding='ECRA_MERKLE_V1'))

    def test_large_utf8_strings_cross_chunk_boundaries_and_no_scratch_files_remain(self):
        text=('"\\\n\t漢😀é'*(1024**2//5))+'tail'
        report=dict(findings=[dict(finding_id='F-1',proof=text)],coverage={},analysis_status='INCOMPLETE')
        path=self.publish(report)
        self.assertEqual(self.digest(path),saved_report_digest(clean_report(report),encoding='ECRA_MERKLE_V1'))
        self.assertEqual(list((self.base/'scratch').iterdir()),[])

    def test_finding_status_key_insertion_order_and_empty_findings_match_old_cleaning(self):
        for index,fields in enumerate([{},dict(a=1,z=2),dict(status='DONE'),dict(review_state='DONE',x=1),
                                      {'statu':1,'status':False,'status_after':2,'😀':3}]):
            report=dict(findings=[fields],coverage={},analysis_status='INCOMPLETE')
            self.assertEqual(self.digest(self.publish(report,'keys-'+str(index))),
                             saved_report_digest(clean_report(report),encoding='ECRA_MERKLE_V1'))
        report=dict(findings=[],coverage={},analysis_status='COMPLETE')
        self.assertEqual(self.digest(self.publish(report,'empty')),saved_report_digest(clean_report(report),encoding='ECRA_MERKLE_V1'))

    def test_shared_finding_in_other_locations_retains_opaque_review_fields(self):
        finding=dict(finding_id='F-1',status='CONFIRMED',review={'answer':'retained outside findings'})
        report=dict(findings=[finding,finding],coverage={},analysis_status='INCOMPLETE',other=finding)
        self.assertEqual(self.digest(self.publish(report)),saved_report_digest(clean_report(report),encoding='ECRA_MERKLE_V1'))

    def test_bad_scalar_length_is_rejected_without_truncating_the_value(self):
        path=self.publish(dict(findings=[],coverage={},analysis_status='INCOMPLETE',proof='whole value'))
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE nodes SET length=1 WHERE kind='str' AND value=?",(b'whole value',))
        with self.assertRaisesRegex(ValueError,'字节长度无效'):self.digest(path)

    def test_status_projection_keeps_every_identity_and_diff_selection_without_payloads(self):
        findings=[dict(finding_id='F-'+str(i),symbol_id='s'+str(i),static_classification='UNKNOWN',
                       accesses=[dict(payload='large evidence')]) for i in range(1203)]
        report=dict(findings=findings,review_safe_samples=[dict(finding_id='SAFE-1',symbol_id='safe',static_classification='SAFE_PROVEN')],
                    coverage=dict(variables_total=1204),analysis_status='INCOMPLETE',
                    git_diff=dict(selected_symbol_ids=['s'+str(i) for i in range(1203)]),risk_summary={})
        path=self.publish(report)
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full reconstruction forbidden')):
            result=status_report(path.parent)
        self.assertEqual(len(result['findings']),1203)
        self.assertEqual(result['findings'][-1]['finding_id'],'F-1202')
        self.assertTrue(all(set(row)=={'finding_id','symbol_id','static_classification'} for row in result['findings']))
        self.assertEqual(result['git_diff']['selected_symbol_ids'],report['git_diff']['selected_symbol_ids'])
        self.assertEqual(result['risk_summary'],{})

    def test_actual_native_status_and_reverification_never_restore_facts_or_report(self):
        fixture=fixtures.CanonicalScanTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        out,cfg=fixture.run_scan()
        # Original full-object consumer/codec are the independent oracle.
        # Only the new helpers are replaced here; the actual run below forbids
        # every full-root reconstruction.
        with patch('ecra.native_consumers.status_report',side_effect=lambda folder:read_saved_json(folder/'reports/global_static_concurrency.json')), \
             patch('ecra.native_consumers.clean_report_digest',side_effect=lambda database,**_:saved_report_digest(
                 clean_report(read_saved_json(database.parent/'reports/global_static_concurrency.json')),encoding='ECRA_MERKLE_V1')):
            with contextlib.redirect_stdout(io.StringIO()):expected=status(fixture.root,fixture.config)
        before=(out/'scan.db').read_bytes()
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full reconstruction forbidden')):
            with contextlib.redirect_stdout(io.StringIO()):actual=status(fixture.root,fixture.config)
        self.assertEqual(actual,expected)
        self.assertTrue(actual['resumable'])
        self.assertNotIn('HTML',actual['next_action'])
        self.assertEqual((out/'scan.db').read_bytes(),before)
        (fixture.root/'main.c').write_bytes(b'int changed_input;')
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full reconstruction forbidden')):
            actual=status(fixture.root,fixture.config)
        self.assertFalse(actual['resumable']);self.assertFalse(actual['review_complete'])

    def test_canonical_legacy_in_firmware_is_viewed_but_never_reverified_or_written(self):
        fixture=fixtures.CanonicalScanTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        out,_=fixture.run_scan();legacy=fixture.root/'.ecra';shutil.copytree(out,legacy)
        raw=json.loads(fixture.config.read_text('utf-8'));raw['analysis']['output']=dict(location='project')
        fixture.config.write_text(json.dumps(raw),'utf-8')
        from ecra.report_package import sha256
        before={str(p):sha256(p) for p in fixture.root.rglob('*') if p.is_file()}
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full reconstruction forbidden')), \
             patch('ecra.native_consumers.status_report',side_effect=AssertionError('legacy runtime must migrate before SQLite opens')), \
             patch('ecra.workflow.read_queue',side_effect=AssertionError('legacy runtime must migrate before SQLite opens')):
            info=status(fixture.root,fixture.config)
        self.assertFalse(info['resumable']);self.assertIn('迁移',info['next_action'])
        self.assertEqual({str(p):sha256(p) for p in fixture.root.rglob('*') if p.is_file()},before)

    def test_scratch_junction_is_rejected_before_any_target_write(self):
        target=self.base/'foreign';target.mkdir();alias=self.base/'scratch-alias'
        if os.name=='nt':
            from ecra.portable import _junction
            _junction(alias,target)
        else:alias.symlink_to(target,target_is_directory=True)
        self.addCleanup(alias.rmdir if os.name=='nt' else alias.unlink)
        path=self.publish(dict(findings=[],coverage={},analysis_status='INCOMPLETE'))
        with self.assertRaises(ValueError):clean_report_digest(path,work=alias)
        self.assertEqual(list(target.iterdir()),[])

    @unittest.skipUnless(os.name=='nt','Windows owned Job commit proof')
    def test_complete_large_shared_report_digest_in_actual_192mib_child(self):
        from ecra.studio.process_budget import ProcessBudget
        from ecra.studio.write_guard import OwnedProcess
        text='漢😀"\\\n'*(4*1024**2)
        tree=dict(leaf=[True,1,-0.0,None,text])
        for _ in range(26):tree=dict(left=tree,right=tree)
        report=dict(findings=[dict(finding_id='F-1',proof=tree)],coverage={},analysis_status='INCOMPLETE')
        path=self.publish(report,'bounded')
        expected=saved_report_digest(clean_report(report),encoding='ECRA_MERKLE_V1')
        program=self.base/'read-digest.py'
        program.write_text('from pathlib import Path\nimport sys\nfrom ecra.native_consumers import clean_report_digest\n'
            'actual=clean_report_digest(Path(sys.argv[1]),work=Path(sys.argv[2]))\n'
            'assert actual==sys.argv[3],(actual,sys.argv[3])\nprint(actual,flush=True)\n','utf-8')
        budget=ProcessBudget(192*1024**2);process=None
        try:
            with (self.base/'child.log').open('wb') as log:
                tool=Path(__file__).resolve().parents[1]
                process=OwnedProcess([sys.executable,'-B',str(program),str(path),str(self.base/'scratch'),expected],
                    cwd=tool,env=dict(os.environ,PYTHONPATH=str(tool),PYTHONDONTWRITEBYTECODE='1'),log=log)
                budget.assign(process);process.resume();code=process.wait(timeout=180)
            self.assertEqual(code,0,(self.base/'child.log').read_text('utf-8',errors='replace'))
            self.assertLessEqual(budget.sample()['peak_job_commit_bytes'],192*1024**2)
        finally:
            budget.close()
            if process is not None:
                if process.poll() is None:process.wait(timeout=10)
                process.close()


if __name__=='__main__':unittest.main()
