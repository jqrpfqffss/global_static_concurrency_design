from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.studio.directories import browse


class DirectoryBrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ecra-dir-')
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'固件, 工程';self.root.mkdir();self.root=self.root.resolve()

    def test_all_sorted_directory_pages_and_exact_relative_paths_without_source_reads_or_writes(self):
        import hashlib
        for i in range(137):(self.root/f'目录, {i:03d}').mkdir()
        original=self.root/'source.c';original.write_text('int value;','utf-8')
        before=(hashlib.sha256(original.read_bytes()).hexdigest(),original.stat().st_mtime_ns,self.root.stat().st_mtime_ns)
        names=[];after=None
        while True:
            # The selector has no reason to open file contents.
            with patch('builtins.open',side_effect=AssertionError('Directory browsing must not read source content')):
                page=browse(str(self.root),root=str(self.root),limit=23,after=after)
            self.assertEqual(page['total'],137);self.assertLessEqual(len(page['items']),23)
            self.assertIsNone(page['parent']);self.assertEqual(page['relative'],'.');self.assertFalse(page['changed'])
            for row in page['items']:
                self.assertEqual(row['relative'],row['name']);self.assertEqual(row['path'],str(self.root/row['name']))
            names.extend(row['name'] for row in page['items']);after=page['next_after']
            if after is None:break
        self.assertEqual(names,sorted(names,key=lambda value:(value.casefold(),value)));self.assertEqual(len(set(names)),137)
        self.assertEqual(before,(hashlib.sha256(original.read_bytes()).hexdigest(),original.stat().st_mtime_ns,self.root.stat().st_mtime_ns))

    def test_name_search_is_explicitly_current_level_and_parent_stays_bound(self):
        (self.root/'中断, 空格').mkdir();(self.root/'Drivers').mkdir();(self.root/'Drivers'/'中断 deeper').mkdir()
        page=browse(str(self.root),root=str(self.root),search='中断')
        self.assertEqual([row['name'] for row in page['items']],['中断, 空格']);self.assertEqual(page['total'],1)
        child=browse(str(self.root/'Drivers'),root=str(self.root))
        self.assertEqual(child['parent'],str(self.root));self.assertEqual(child['relative'],'Drivers')
        with self.assertRaisesRegex(ValueError,'超出'):browse(str(self.root.parent),root=str(self.root))
        with self.assertRaisesRegex(ValueError,'超出'):browse(str(self.root/'..'),root=str(self.root))

    def test_link_entries_are_visible_but_never_followed(self):
        outer=Path(self.tmp.name)/'outside';outer.mkdir();link=self.root/'junction-like'
        try:link.symlink_to(outer,target_is_directory=True)
        except OSError as exc:self.skipTest('Host cannot create an owned symlink: '+str(exc))
        page=browse(str(self.root),root=str(self.root));self.assertEqual(page['counts']['links'],1)
        row=next(row for row in page['items'] if row['name']==link.name)
        self.assertFalse(row['selectable']);self.assertIn('不跟随',row['reason'])
        with self.assertRaisesRegex(ValueError,'Junction'):browse(str(link),root=str(self.root))
        self.assertEqual(list(outer.iterdir()),[])

    def test_actual_directory_change_during_enumeration_requires_refresh(self):
        import os
        (self.root/'before').mkdir();original=os.scandir
        class ChangingScan:
            def __enter__(inner):inner.stream=original(self.root);return inner
            def __iter__(inner):
                yield from inner.stream
                (self.root/'created-during-list').mkdir()
            def __exit__(inner,*args):inner.stream.close()
        with patch('ecra.studio.directories.os.scandir',side_effect=lambda path:ChangingScan()):page=browse(str(self.root))
        self.assertTrue(page['changed']);self.assertIn('刷新',page['notice'])
        self.assertFalse(browse(str(self.root))['changed'])

    def test_bad_arguments_missing_paths_and_files_fail_without_making_anything(self):
        before=list(self.root.iterdir())
        for kwargs in [dict(path='relative'),dict(path=str(self.root/'missing')),dict(path=1),dict(root=''),dict(limit=True),dict(limit=101),dict(after=0),dict(search=None)]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):browse(**kwargs)
        file=self.root/'not-a-directory';file.write_text('unchanged','utf-8')
        with self.assertRaises(ValueError):browse(str(file))
        self.assertEqual(list(self.root.iterdir()),before+[file])

    def test_drive_inventory_does_not_automatically_enumerate_any_drive(self):
        with patch('ecra.studio.directories.os.scandir',side_effect=AssertionError('No automatic drive traversal')):value=browse()
        self.assertEqual(value['mode'],'roots');self.assertIsNone(value['path']);self.assertTrue(value['items'])
        self.assertTrue(all(Path(row['path']).is_absolute() for row in value['items']))


if __name__=='__main__':unittest.main()
