"""Actual native extraction proves the independent graph dies before current merge."""
import weakref
from unittest.mock import patch
import unittest

from ecra.common import read_json, write_json
from ecra.report_package import sha256
from tests import test_native_diff_summary_cache as native_fixture


class NativeSequentialVerificationTests(unittest.TestCase):
    def setUp(self):
        self.case = native_fixture.NativeDiffSummaryCacheTests()
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        cfg = read_json(self.case.config); cfg['analysis']['git_diff']['verify_against_full'] = True
        write_json(self.case.config, cfg)

    def hooks(self, scan_id, *, corrupt=False):
        import ecra.cli as cli
        import ecra.analysis as analysis
        from ecra.input_snapshot import SOURCE_READS
        original = analysis.merge
        target = self.case.data/'scans'/scan_id
        references, events = [], []
        class Graph(dict): pass
        def current():
            snapshot = SOURCE_READS.get()
            return snapshot is not None and snapshot.diagnostics.parent == target
        def independent(parts):
            value = original(parts)
            if current():
                graph = Graph(value); references.append(weakref.ref(graph)); events.append('independent')
                return graph
            return value
        def cached(parts):
            if current():
                references_on_disk=list((self.case.data/'work/diff-comparison').glob('full-reference-*/summary.json'))
                self.assertEqual(len(references_on_disk),1)
                self.reference_sha=sha256(references_on_disk[0])
                self.assertTrue(references); self.assertTrue(all(ref() is None for ref in references))
                events.append('current')
            value = original(parts)
            if current() and corrupt:
                next(v for v in value['variables'] if v['name']=='shared')['semantic_digest'] = 'INJECTED_CACHE_CORRUPTION'
            return value
        return patch.object(analysis, 'merge', new=independent), patch.object(cli, 'merge', new=cached), events

    def test_original_independent_extraction_runs_before_current_graph(self):
        first, second, events = self.hooks('sequential')
        with first, second: out = self.case.scan('sequential')
        self.assertEqual(events, ['independent','current'])
        result = read_json(out/'reports/global_static_concurrency.json')['git_diff']['full_verification']
        self.assertEqual(result['state'], 'PASSED'); self.assertEqual(result['reextracted_units'], 2)
        self.assertEqual(len(list((out/'workers/full-verification').glob('*.request.json'))), 2)
        self.assertEqual(read_json(out/'diagnostics/full-verification-summary-proof.json')['sha256'],self.reference_sha)
        self.assertEqual(list((self.case.data/'work/diff-comparison').glob('full-reference-*/summary.json')),[])
        self.assertFalse((out/'git_diff/full-verification.summary.json').exists())

    def test_corrupt_current_facts_block_publication_and_preserve_previous_scan(self):
        previous = self.case.scan('prior'); before = sha256(previous/'scan.db')
        first, second, events = self.hooks('corrupted', corrupt=True)
        with first, second: failed = self.case.scan('corrupted', success=False)
        self.assertEqual(events, ['independent','current'])
        diagnostic = read_json(failed/'diagnostics/git-diff-verification-failed.json')
        self.assertNotEqual(diagnostic['expected'], diagnostic['actual'])
        self.assertEqual(sha256(previous/'scan.db'), before)
        self.assertFalse((failed/'manifest.json').exists())
