import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ecra.scan_store import publish_scan
from ecra.review import _review_env


class EvidenceMCPTests(unittest.TestCase):
    def test_real_stdio_session_pages_complete_evidence_with_no_shell_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scan.db'
            publish_scan(path,dict(variables=[],values=list(range(407))),dict(findings=[]),scan_id='s',project_id='p')
            requests=[dict(jsonrpc='2.0',id=1,method='initialize',params=dict(protocolVersion='2025-06-18')),
                dict(jsonrpc='2.0',method='notifications/initialized'),dict(jsonrpc='2.0',id=2,method='tools/list')]
            for i,offset in enumerate((0,200,400)):
                requests.append(dict(jsonrpc='2.0',id=3+i,method='tools/call',params=dict(name='evidence',
                    arguments=dict(root='facts',path=['values'],offset=offset,limit=200))))
            requests.append(dict(jsonrpc='2.0',id=6,method='tools/call',params=dict(name='evidence',arguments=dict(database='C:/Windows/win.ini'))))
            result=subprocess.run([sys.executable,'-X','utf8','-B','-m','ecra.evidence_mcp','--database',str(path)],
                input='\n'.join(json.dumps(r) for r in requests)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            replies=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(len(replies),6)
            self.assertEqual(replies[0]['result']['protocolVersion'],'2025-06-18')
            values=[]
            for reply in replies[2:5]:
                self.assertFalse(reply['result']['isError'])
                page=json.loads(reply['result']['content'][0]['text']);self.assertEqual(page['total'],407)
                values.extend(item['value'] for item in page['items'])
            self.assertEqual(values,list(range(407)))
            self.assertIsNone(page['next_offset'])
            self.assertTrue(replies[-1]['result']['isError'])
            config=json.loads(_review_env([],evidence_database=path)['OPENCODE_CONFIG_CONTENT'])
            self.assertEqual(config['permission']['*'],'deny')
            self.assertNotIn('bash',config['permission'])
            self.assertNotIn('webfetch',config['permission'])
            self.assertEqual(config['permission']['ecra_evidence_*'],'allow')
            self.assertEqual(config['mcp']['ecra_evidence']['command'][-1],str(path))
            formatting=json.loads(_review_env([],format_only=True,evidence_database=path)['OPENCODE_CONFIG_CONTENT'])
            self.assertNotIn('mcp',formatting)
            self.assertNotIn('ecra_evidence_*',formatting['permission'])
