import json
import tempfile
import unittest
from pathlib import Path
from ecra.review import parse_answer


class RealFormatTests(unittest.TestCase):
    def test_explanation_before_fenced_final_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'a.c').write_text('int shared;\n')
            answer=dict(finding_id='test',status='CONFIRMED',evidence=[dict(file='a.c',line=1)],
                        **{k:'source-backed explanation' for k in ('reason','interleaving','protection','impact','fix','verification')})
            event=dict(type='text',part=dict(text='Finished source review.\n```json\n'+json.dumps(answer)+'\n```'))
            self.assertEqual(parse_answer(json.dumps(event),'test',root),answer)
            event['part']['text']='JSON 输出:\n\n'+json.dumps(answer)
            self.assertEqual(parse_answer(json.dumps(event),'test',root),answer)
            answer['evidence'][0]['line']=999
            event['part']['text']='Explanation\n```json\n'+json.dumps(answer)+'\n```'
            with self.assertRaises(ValueError): parse_answer(json.dumps(event),'test',root)
