from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.html_evidence import HtmlEvidence, DETAIL_SCRIPT, EXTERNAL_SCRIPT
from ecra.html_report import STYLE,deferred_detail
from scripts.compact_saved_html import main
from tests import test_html_evidence


class CompactSavedHtmlTests(unittest.TestCase):
    def test_complete_search_index_and_moved_anchors_survive_presentation_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'original';out=Path(folder)/'presentation';source.mkdir()
            text='SOURCE_SEARCH_COMPLETE_'+'源码'*10000
            legacy_script="\ndocument.addEventListener('toggle',e=>{const d=e.target;if(d.tagName!=='DETAILS'||!d.open)return;for(const f of d.querySelectorAll(':scope > iframe[data-ecra-src]'))if(!f.hasAttribute('src'))f.src=f.dataset.ecraSrc;},true);"
            legacy_script+='\nlet evidenceAnchorsPromise;'+EXTERNAL_SCRIPT.partition('\nlet evidenceAnchorsPromise;')[2]
            with HtmlEvidence(source,'fingerprint',STYLE,threshold=1000000) as evidence:
                ident=evidence.search(text)
                detail=deferred_detail('变量证据','<p id="proof-node">完整证据</p>')
                legacy=evidence.put('html',['<html><body>旧版完整证据</body></html>'])
                detail+='<details data-external-detail="1"><summary>旧版详情</summary><iframe data-ecra-src="html_details/'+legacy+'"></iframe></details>'
                html='<html><body><table><tr id="var-g" data-search-ref="'+ident+'"><td>'+detail+'</td></tr></table><script>'+legacy_script+'</script></body></html>'
                (source/'index.html').write_text(html,encoding='utf-8')
                evidence.register('index.html',html)
                evidence.graph(dict(functions={},calls=[],accesses={}), 'const graph={};')
                (source/'html_details/detail.js').write_text(DETAIL_SCRIPT+legacy_script+'const graph={};',encoding='utf-8')
                evidence.finish()
            original=(source/'html_details/search-index.js').read_bytes()
            with patch('sys.argv',['compact_saved_html','--source',str(source),'--output',str(out)]),redirect_stdout(io.StringIO()):main()
            script=(out/'html_details/search-index.js').read_text(encoding='utf-8')
            self.assertEqual(json.loads(script.split('=',1)[1].removesuffix(';'))[ident],text)
            self.assertEqual((source/'html_details/search-index.js').read_bytes(),original)
            proof=json.loads((out/'presentation-proof.json').read_text(encoding='utf-8'))
            self.assertEqual(proof['frame_scripts_refreshed'],1)
            self.assertEqual((out/'html_details/detail.js').read_text(encoding='utf-8'),DETAIL_SCRIPT+EXTERNAL_SCRIPT+'const graph={};')
            frames=test_html_evidence.HtmlEvidenceTests.FrameContexts();frames.feed((out/'index.html').read_text(encoding='utf-8'))
            self.assertEqual(frames.total,2)
            self.assertEqual(frames.active,0)
            script=(out/'html_details/anchors.js').read_text(encoding='utf-8')
            anchors=json.loads(script.split('=',1)[1].removesuffix(';'))
            self.assertEqual(anchors['var-g'],'index.html')
            self.assertNotEqual(anchors['proof-node'],'index.html')
            self.assertIn('id="proof-node"',(out/anchors['proof-node']).read_text(encoding='utf-8'))
            manifest=json.loads((out/'html_details/manifest.json').read_text(encoding='utf-8'))
            self.assertTrue(manifest['complete'])
            for name,record in manifest['files'].items():
                self.assertEqual(hashlib.sha256((out/'html_details'/name).read_bytes()).hexdigest(),record['sha256'])
