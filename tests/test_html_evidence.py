import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from html.parser import HTMLParser

from ecra.html_evidence import CURRENT, HtmlEvidence
from ecra.html_report import STYLE, deferred_detail, raw, write_html, anchor


class HtmlEvidenceTests(unittest.TestCase):
    class FrameContexts(HTMLParser):
        def __init__(self):
            super().__init__();self.depth=0;self.total=0;self.active=0
        def handle_starttag(self,tag,attrs):
            if tag=='template':self.depth+=1
            if tag=='iframe':
                self.total+=1
                if not self.depth:self.active+=1
        def handle_endtag(self,tag):
            if tag=='template':self.depth-=1

    def report_model(self, count):
        variables=[dict(symbol_id='g'+str(i),name='g'+str(i),qualified_name='g'+str(i),kind='GLOBAL',
            definition_file='app.c',definition_line=i+1,type='unsigned',size_bytes=4,alignment_bytes=4,
            is_const=False,is_volatile=False,translation_units=['app.c'],readers=[],writers=[],accesses=[],
            static_classification='SAFE_PROVEN',analysis_coverage='COMPLETE',safe_reason='单一执行上下文',
            extra_debug=dict(marker='ONLY_COLLAPSED_EVIDENCE_'+str(i))) for i in range(count)]
        return dict(variables=variables,functions=[],calls=[],contexts=[],unknowns=[],translation_units=[]), \
            dict(findings=[],coverage={},analysis_status='COMPLETE',run_status='STATIC_SCAN_SAVED',limitations=[])

    def test_many_individually_small_details_do_not_enter_initial_html(self):
        facts,report=self.report_model(1000)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);write_html(out,facts,report,[])
            main=(out/'index.html').read_text(encoding='utf-8')
            self.assertIn('data-external-detail="1"',main)
            self.assertNotIn('ONLY_COLLAPSED_EVIDENCE_',main)
            self.assertNotIn('data-detail-template="1"',main)
            frames=self.FrameContexts();frames.feed(main)
            self.assertGreaterEqual(frames.total,1000)
            self.assertEqual(frames.active,0,'折叠证据不得预先占用浏览上下文')
            for variable in facts['variables']:
                self.assertIn('id="'+anchor('var-',variable['symbol_id'])+'"',main)
            documents=[p.read_text(encoding='utf-8') for p in (out/'html_details').glob('*.html')]
            self.assertTrue(any('ONLY_COLLAPSED_EVIDENCE_0' in text for text in documents))
            self.assertTrue(any('ONLY_COLLAPSED_EVIDENCE_999' in text for text in documents))
            self.assertTrue(json.loads((out/'html_details/manifest.json').read_text())['complete'])

    def test_small_report_retains_inline_details_and_original_interaction(self):
        facts,report=self.report_model(2)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);write_html(out,facts,report,[])
            main=(out/'index.html').read_text(encoding='utf-8')
            self.assertIn('ONLY_COLLAPSED_EVIDENCE_0',main)
            self.assertIn('data-detail-template="1"',main)
            self.assertFalse((out/'html_details').exists())

    def test_debug_links_complete_slice_and_coherence_without_copying_their_sources(self):
        facts,report=self.report_model(2)
        variable=facts['variables'][0]
        variable['multi_field_coherence']=[dict(sources=['COMPLETE_COHERENCE_SOURCE']*4000)]
        variable['variable_evidence_slice']=dict(function_ids=[],physical_contexts=[],
            complete_sources=['COMPLETE_SLICE_SOURCE']*4000)
        original=copy.deepcopy(facts)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);write_html(out,facts,report,[])
            text=(out/'index.html').read_text(encoding='utf-8')
            self.assertNotIn('COMPLETE_COHERENCE_SOURCE',text)
            self.assertNotIn('COMPLETE_SLICE_SOURCE',text)
            self.assertIn('variable_evidence_slice',text)
            self.assertIn('multi_field_coherence',text)
            self.assertIn('facts.json',text)
        self.assertEqual(facts,original)

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
