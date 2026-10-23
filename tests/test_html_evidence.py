import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from html.parser import HTMLParser

from ecra.html_evidence import CURRENT, HtmlEvidence
from ecra.html_report import STYLE, deferred_detail, raw


class HtmlEvidenceTests(unittest.TestCase):
    def test_all_evidence_preserved_offline_with_complete_anchor_and_asset_map(self):
        payload = [dict(access_id=f'A-{n}', source='中文 <&> "源码"', targets=list(range(20))) for n in range(1000)]
        original = copy.deepcopy(payload)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            with HtmlEvidence(out, 'scan-fingerprint', STYLE, threshold=1024) as evidence:
                debug = raw(payload, '完整访问')
                detail = deferred_detail('全部证据', '<p id="proof-1">'+('x'*5000)+'</p>'
                    '<a href="#var-1">变量</a><a href="reports/test.json">机器事实</a>'
                    '<a href="facts.json">完整事实</a><a href="inventory/global_static_inventory.md">清单</a>'+debug)
                evidence.graph(dict(functions={}, calls=[], accesses={}),
                               "const graph=JSON.parse(document.getElementById('call-graph').textContent);")
                evidence.register('index.html', '<tr id="var-1"></tr>')
                evidence.finish()
            self.assertEqual(payload, original)
            self.assertNotIn('x'*5000, detail)
            class Frames(HTMLParser):
                frames = []
                def handle_starttag(self, tag, attrs):
                    if tag == 'iframe':
                        self.frames.append(dict(attrs))
            parser = Frames(); parser.feed(detail)
            self.assertEqual(len(parser.frames), 1)
            self.assertNotIn('src', parser.frames[0])
            target = out/parser.frames[0]['data-ecra-src']
            text = target.read_text(encoding='utf-8')
            self.assertIn('x'*5000, text)
            self.assertIn('href="../reports/test.json"', text)
            self.assertIn('href="../facts.json"', text)
            self.assertIn('href="../inventory/global_static_inventory.md"', text)
            json_name = re.search(r'href="html_details/([a-f0-9]+\.json)"', debug)[1]
            self.assertIn('href="'+json_name+'"', text)
            self.assertEqual(json.loads((out/'html_details'/json_name).read_text(encoding='utf-8')), payload)
            anchors = (out/'html_details/anchors.js').read_text(encoding='utf-8')
            self.assertIn('"proof-1":"html_details/'+target.name+'"', anchors)
            self.assertIn('"var-1":"index.html"', anchors)
            manifest = json.loads((out/'html_details/manifest.json').read_text(encoding='utf-8'))
            self.assertTrue(manifest['complete'])
            for name, record in manifest['files'].items():
                data = (out/'html_details'/name).read_bytes()
                self.assertEqual(record['bytes'], len(data))
                self.assertEqual(record['sha256'], hashlib.sha256(data).hexdigest())
            self.assertIsNone(CURRENT.get())

    def test_failure_keeps_sidecar_manifest_invalid_and_restores_context(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(MemoryError):
                with HtmlEvidence(folder, 'failed-scan', STYLE):
                    raw(list(range(1000)))
                    raise MemoryError('controlled-html-failure')
            self.assertIsNone(CURRENT.get())
            manifest = json.loads((Path(folder)/'html_details/manifest.json').read_text())
            self.assertFalse(manifest['complete'])


if __name__ == '__main__':
    unittest.main()
