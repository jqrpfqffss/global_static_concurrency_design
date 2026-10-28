from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from ecra.common import write_json
from ecra.report import write_database
from ecra.shared_json import write,logical_digest
from scripts.verify_replayed_report import verify


class ReplayedReportTests(unittest.TestCase):
    def prepare(self,root):
        folder=root/'rendered';(folder/'reports').mkdir(parents=True)
        facts=dict(accesses=[],variables=[dict(symbol_id='g',flag=True)],
                   points_to_stats=dict(complete=True),context_points_to_stats=dict(complete=True))
        report=dict(findings=[],coverage={},analysis_status='INCOMPLETE')
        write(folder/'facts.json',facts,threshold=0)
        write(folder/'reports/global_static_concurrency.json',report,threshold=0)
        write_database(folder/'facts.db',facts,report,shared_threshold=0)
        write_json(folder/'result_validity.json',dict(analysis_valid=False))
        write_json(root/'replay-result.json',dict(full_scan_acceptance=False,safety_report_valid=False,
            full_analysis_complete=True,report_generation_complete=True,solver_fixed_points_complete=True))
        write_json(root/'render-proof.json',dict(complete=True,facts_logical_digest=logical_digest(facts),
            static_report_logical_digest=logical_digest(report),fact_counts=dict(accesses=0,variables=1),
            classifications={},variable_accountability={}))
        return facts

    def test_complete_roundtrip_and_sqlite_remain_controlled_only(self):
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
            root=Path(folder);self.prepare(root);result=verify(root)
            self.assertTrue(result['complete'])
            self.assertFalse(result['native_acceptance'])
            self.assertFalse(result['safety_report_valid'])
            self.assertEqual(result['database']['differences'],{})

    def test_hidden_scalar_type_change_cannot_pass_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
            root=Path(folder);facts=self.prepare(root);facts['variables'][0]['flag']=1
            write(root/'rendered/facts.json',facts,threshold=0)
            with self.assertRaisesRegex(ValueError,'往返不一致'):verify(root)

    def test_valid_safety_label_is_rejected_for_controlled_artifacts(self):
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
            root=Path(folder);self.prepare(root)
            write_json(root/'rendered/result_validity.json',dict(analysis_valid=True))
            with self.assertRaisesRegex(ValueError,'不能冒充'):verify(root)


if __name__=='__main__':unittest.main()
