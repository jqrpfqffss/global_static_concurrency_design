"""Removed dirty Diff is explicit; the ordinary frozen full path still works."""
import contextlib
import io
import unittest
from unittest.mock import patch

from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.report_package import sha256
from ecra.scan_persistence import run_canonical
from ecra.scan_store import EvidenceProvider
from scripts.compare_native_graphs import compare
from tests import test_frozen_scan_pipeline as fixtures


class FrozenDirtyDiffTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.FrozenScanPipelineTests(methodName='runTest')
        # Keep this legacy full-mode Git capture below Windows' admin-path
        # limit even when pytest assigns a two-digit fixture directory.
        import tempfile
        temporary = tempfile.TemporaryDirectory
        with patch.object(tempfile, 'TemporaryDirectory', side_effect=lambda *a, **kw:
                          temporary(*a, **dict(kw, prefix='fr-'))):
            self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        raw = read_json(self.case.config)
        raw['analysis']['git_diff'] = dict(enabled=False, current_ref='HEAD', include_uncommitted=True)
        write_json(self.case.config, raw)
        self.case.cfg, _ = load_config(self.case.root, self.case.config)

    def test_legacy_dirty_diff_requires_explicit_migration_without_capturing_or_writing_source(self):
        case = self.case
        before = {str(p): sha256(p) for p in case.root.rglob('*') if p.is_file()}
        raw = read_json(case.config)
        raw['analysis']['git_diff']['enabled'] = True
        write_json(case.config, raw)
        with patch('ecra.dirty_inputs.capture_inputs', side_effect=AssertionError('No capture for unsupported Diff')):
            with self.assertRaisesRegex(ValueError, 'include_uncommitted: false'):
                run_canonical(case.root, case.config, no_review=True)
        self.assertEqual({str(p): sha256(p) for p in case.root.rglob('*') if p.is_file()}, before)
        self.assertFalse((case.data/'scans').exists())

    def test_public_full_dirty_scan_keeps_complete_frozen_inputs_and_original_bytes(self):
        case = self.case
        before = {str(p): sha256(p) for p in case.root.rglob('*') if p.is_file()}
        automatic = case.scan('full-automatic')
        identity = read_json(automatic/'input_closure.json')['frozen_view']
        descriptor = {key: identity[key] for key in ('file', 'sha256')}
        replay = case.scan('full-replay', descriptor)
        self.assertTrue(compare(automatic/'scan.db', replay/'scan.db')['passed'])
        self.assertFalse(EvidenceProvider(automatic/'scan.db').load('report').get('git_diff'))
        self.assertEqual({str(p): sha256(p) for p in case.root.rglob('*') if p.is_file()}, before)

    def test_private_frozen_descriptor_cannot_reenable_dirty_diff(self):
        case = self.case
        descriptor = case.capture()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'Diff 只支持'):
            run_canonical(case.root, case.config, no_review=True, scan_mode='diff', _compiler_view=descriptor)

    def test_explicit_full_override_preserves_the_previous_non_diff_behavior(self):
        case = self.case
        raw = read_json(case.config)
        raw['analysis']['git_diff']['enabled'] = True
        write_json(case.config, raw)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            code = run_canonical(case.root, case.config, no_review=True, scan_id='explicit-full', scan_mode='full')
        self.assertIn(code, (0, 1, 2), log.getvalue())
        self.assertFalse(EvidenceProvider(case.data/'scans/explicit-full/scan.db').load('report').get('git_diff'))


if __name__ == '__main__':
    unittest.main()
