import json
from pathlib import Path
import tempfile
import unittest

from ecra.common import write_json
from ecra.shared_json import write
from scripts.validate_large_report import report_selection


class ReportScopeTests(unittest.TestCase):
    def test_full_scope_does_not_infer_selection_from_html(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            write_json(root/'scan_state.json', dict(scan_mode='full'))
            self.assertIsNone(report_selection(root))

    def test_plain_and_shared_reports_preserve_empty_and_selected_scope(self):
        for threshold in (0, 2**30):
            for selected in ([], ['g']):
                with self.subTest(threshold=threshold, selected=selected), tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);(root/'reports').mkdir()
                    pin=dict(head_sha='HEAD', base_sha='BASE')
                    write_json(root/'scan_state.json', dict(scan_mode='diff', fingerprint='F', git_diff_pin=pin))
                    write(root/'reports/global_static_concurrency.json', dict(findings=[dict(v='all evidence')],
                        git_diff=dict(selected_symbol_ids=selected, pin=pin), fingerprint='F'), threshold=threshold)
                    self.assertEqual(report_selection(root), set(selected))

    def test_inconsistent_or_duplicate_scope_cannot_pass_as_empty(self):
        for selected, fingerprint, pin in ((['g','g'],'F',{}), ([True],'F',{}), ([], 'OLD', {}), ([], 'F', dict(base='OLD'))):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'reports').mkdir()
                write_json(root/'scan_state.json', dict(scan_mode='diff', fingerprint='F', git_diff_pin={}))
                write_json(root/'reports/global_static_concurrency.json', dict(
                    git_diff=dict(selected_symbol_ids=selected, pin=pin), fingerprint=fingerprint))
                with self.assertRaises(ValueError):report_selection(root)


if __name__ == '__main__':
    unittest.main()
