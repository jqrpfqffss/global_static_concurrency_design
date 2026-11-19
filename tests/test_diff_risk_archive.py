"""Real fixed-ref publication of risk proofs and three-way impact accounting."""
import contextlib
import io
import json
from pathlib import Path
import unittest

from ecra.common import digest
from ecra.diff_review import DiffReviewEvidence
from ecra.report_package import export_report, import_report
from ecra.scan_store import EvidenceProvider
from ecra.studio.query import QueryService
from ecra.workflow import checked_scan, saved_run
from tests import test_canonical_scan as fixtures
from tests.test_diff_risk_contract import PROTECTED


class RiskArchiveTests(unittest.TestCase):
    setUp = fixtures.CanonicalScanTests.setUp
    pinned_diff_project = fixtures.CanonicalScanTests.pinned_diff_project
    run_scan = fixtures.CanonicalScanTests.run_scan

    def test_real_closure_survives_native_scan_reopen_and_portable_export(self):
        git, _ = self.pinned_diff_project()
        # One definite fix, one unsupported-flow uncertainty, and one proven
        # independent private object must survive the same real archive.
        tail = ('int check;static int quiet;void Work(void){for(int i=0;i<1;i++)check++;}'
                'void USART2_IRQHandler(void){quiet++;}')
        baseline_source = ('int shared;void Work(void);void main(void){shared++;}'
                           'void ISR(void){shared++;Work();}') + tail
        (self.root/'main.c').write_text(baseline_source, 'utf-8')
        git('add', 'main.c'); git('commit', '-m', 'three impact classes baseline')
        git('branch', '-f', 'base')
        current_source = ('void Work(void);' + PROTECTED.replace('void ISR(void){shared++;}',
            'void ISR(void){shared++;Work();}') + tail).replace('i<1', 'i<2')
        (self.root/'main.c').write_text(current_source, 'utf-8')
        git('add', 'main.c'); git('commit', '-m', 'complete critical section')
        cfg = json.loads(self.config.read_text('utf-8'))
        cfg['analysis']['git_diff']['verify_against_full'] = True
        self.config.write_text(json.dumps(cfg), 'utf-8')
        before = git('status', '--porcelain')
        out, cfg = self.run_scan()
        facts, report, _ = checked_scan(self.root, out, cfg, self.config)
        diff = report['git_diff']
        impact = diff['impacts']['c:@shared']
        self.assertEqual(impact['risk_transition']['matrix_case'], 'R04', impact['risk_transition'])
        self.assertEqual(diff['deleted_variables'], [])
        self.assertEqual(diff['change_counts']['counts_as_risk_resolution'], 1)
        self.assertEqual(diff['impact_counts'], dict(DEFINITE=1, UNCERTAIN=1, EXCLUDED=1))
        self.assertEqual(diff['impacts']['c:@check']['impact_class'], 'UNCERTAIN')
        quiet = next(v['symbol_id'] for v in facts['variables'] if v['name'] == 'quiet')
        self.assertEqual(diff['impacts'][quiet]['impact_class'], 'EXCLUDED')
        self.assertEqual(set(diff['selected_symbol_ids']), {'c:@shared', 'c:@check'})
        current = next(v for v in facts['variables'] if v['symbol_id'] == 'c:@shared')
        self.assertEqual(current['impact'], impact)
        self.assertEqual(impact['risk_transition']['closure']['current_proof'], current['safe_evidence'])
        self.assertEqual(git('status', '--porcelain'), before)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(self.root, self.config, render_only=True), (0, 1, 2))
        package = self.base/'risk-proof.ecra-report'
        export_report(out, package)
        destination = self.base/'other-computer'
        imported = import_report(package, destination)
        restored = destination/'scans'/imported['scan_id']
        provider = EvidenceProvider(restored/'scan.db')
        self.assertEqual(provider.load('report', ['git_diff']), diff)
        self.assertEqual(QueryService(restored).diff_summary()['change_counts'], diff['change_counts'])
        self.assertEqual(QueryService(restored).diff_summary()['impact_counts'], diff['impact_counts'])
        self.assertEqual(provider.load('report', ['git_diff', 'object_accounting']), diff['object_accounting'])
        self.assertEqual(impact['impact_class'], 'DEFINITE')
        self.assertTrue(QueryService(restored).diff_changes('accounting')['items'])
        baseline = QueryService(restored, baseline=True).evidence
        original = next(v for v in baseline.load('facts', ['variables']) if v['symbol_id'] == 'c:@shared')
        for link in impact['risk_transition']['closure']['correspondences']:
            reference = link['base_conflict']
            self.assertEqual(reference['sha256'], digest(original['conflict_pairs'][reference['index']]))
        # Readable proof is not a new manual-review state or permission.
        with self.assertRaises(KeyError):
            DiffReviewEvidence(restored).require_deleted('c:@shared')
        self.assertIsNone(DiffReviewEvidence(restored).baseline())
        self.assertFalse(list(self.data.rglob('facts.json')))


if __name__ == '__main__':
    unittest.main()
