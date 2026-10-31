import hashlib
import tempfile
import unittest
from pathlib import Path

from ecra.common import write_json
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.studio.source_view import source_window


class SourceViewTests(unittest.TestCase):
    def test_line_location_is_archived_text_and_ide_requires_same_local_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);firmware=root/'firmware';firmware.mkdir()
            source=firmware/'main.c';text='// 中文\nint value;\nvalue++;\n'
            source.write_bytes(text.encode())
            scan=root/'data/scans/s1';scan.mkdir(parents=True)
            publish_scan(scan/'scan.db',dict(variables=[]),dict(findings=[]),scan_id='s1',project_id='p',
                provenance=dict(project_root=str(firmware),archived_sources=[dict(file='main.c',text=text,sha256=hashlib.sha256(text.encode()).hexdigest())]))
            write_json(scan/'manifest.json',dict(format='ECRA_LOCAL_SCAN'))
            provider=EvidenceProvider(scan/'scan.db')
            window=source_window(provider,'main.c',line=2,before=0,after=0)
            self.assertEqual(window['lines'],[dict(line=2,column=1,text='int value;',complete=True,selected=True)])
            self.assertTrue(window['ide']['available'])
            source.write_text('changed',encoding='utf-8')
            changed=source_window(provider,'main.c',line=2)
            self.assertFalse(changed['ide']['available'])
            self.assertTrue(any(row['text']=='int value;' for row in changed['lines']))
            write_json(scan/'manifest.json',dict(format='ECRA_REPORT'))
            source.write_bytes(text.encode())
            self.assertFalse(source_window(provider,'main.c')['ide']['available'])
            self.assertFalse(source_window(provider,'../../private.txt')['available'])

    def test_long_single_line_is_bounded_and_full_text_remains_addressable(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scan.db';text='中'*1000000+'\nnext line\n'
            publish_scan(path,dict(variables=[]),dict(findings=[]),scan_id='s1',project_id='p',
                provenance=dict(archived_sources=[dict(file='long.c',text=text)]))
            provider=EvidenceProvider(path)
            result=source_window(provider,'long.c')
            self.assertTrue(result['window_limited'])
            self.assertLessEqual(sum(len(row['text']) for row in result['lines']),262144)
            self.assertTrue(result['complete_file_available'])
            self.assertEqual(provider.node(result['text_node'])['total'],len(text.encode()))
            second=source_window(provider,'long.c',line=2,before=0,after=0)
            self.assertEqual(second['lines'][0]['text'],'next line')
