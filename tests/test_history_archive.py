import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import write_json
from ecra.history_archive import copy_snapshot_file


class HistoryArchiveTests(unittest.TestCase):
    def test_atomically_replaced_outputs_leave_complete_old_inodes(self):
        names = ('facts.json', 'facts.db', 'inventory/global_static_inventory.json',
                 'reports/global_static_concurrency.json', 'html_details/'+'a'*64+'.json',
                 'reports/root_cause_v2.json','inventory/global_static_inventory.md',
                 'reports/global_static_concurrency.md','reports/unknown_contexts.md')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'out';archive = Path(folder)/'archive'
            for name in names:
                source, saved = root/name, archive/name
                source.parent.mkdir(parents=True, exist_ok=True);saved.parent.mkdir(parents=True, exist_ok=True)
                write_json(source, dict(complete=['旧事实']*8))
                copy_snapshot_file(source, saved, root=root)
                self.assertTrue(os.path.samefile(source, saved))
                write_json(source, dict(complete=['新事实']*8))
                self.assertFalse(os.path.samefile(source, saved))
                self.assertIn('旧事实', saved.read_text(encoding='utf-8'))

    def test_mutable_pages_and_review_records_are_independent_copies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'out';root.mkdir()
            for name in ('index.html', 'queue.json', 'anchors.js'):
                source, saved = root/name, Path(folder)/name
                source.write_text('历史内容', encoding='utf-8')
                copy_snapshot_file(source, saved, root=root)
                self.assertFalse(os.path.samefile(source, saved))
                source.write_text('新内容', encoding='utf-8')
                self.assertEqual(saved.read_text(encoding='utf-8'), '历史内容')

    def test_unsupported_links_copy_without_losing_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'out';root.mkdir();source=root/'facts.json';saved=Path(folder)/'saved'
            source.write_bytes(b'complete evidence')
            with patch('ecra.history_archive.os.link', side_effect=OSError('unsupported')):
                copy_snapshot_file(source, saved, root=root)
            self.assertEqual(saved.read_bytes(), source.read_bytes())
            self.assertFalse(os.path.samefile(source, saved))

    def test_outside_files_never_use_immutable_link_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'root';root.mkdir();source=Path(folder)/'facts.json';saved=root/'saved'
            source.write_bytes(b'outside')
            copy_snapshot_file(source, saved, root=root)
            self.assertFalse(os.path.samefile(source, saved))


if __name__ == '__main__':
    unittest.main()
