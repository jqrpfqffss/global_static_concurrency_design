"""Synthetic transport/citation checks, not real model reasoning acceptance."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess,run
import sys
import tempfile
import unittest
from unittest.mock import patch

from ecra.review import _review_env,collect_evidence,review_all,verify_receipt
from ecra.review_contract import validate_source_evidence
from ecra.review_sources import ArchivedSources,source_scope,read_source
from ecra.scan_store import EvidenceProvider,publish_scan
from tests.test_review_contract import answer_for


class ArchivedReviewSourceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.out=self.root/'external-data/scans/s'
        self.text='int shared; // 中文\nvoid IRQ(void){shared++;}\n'+'// 中'*7000+'\n'
        self.sha=hashlib.sha256(self.text.encode()).hexdigest()
        self.facts=dict(variables=[],contexts=[],functions=[],calls=[])
        self.report=dict(findings=[dict(finding_id=f,variable_name='shared',static_classification='SUSPECT',accesses=[]) for f in ('F','G')],coverage={},limitations=[])
        publish_scan(self.out/'scan.db',self.facts,self.report,scan_id='s',project_id='p',
            provenance=dict(archived_sources=[dict(file='app.c',text=self.text,sha256=self.sha)]))
        self.provider=EvidenceProvider(self.out/'scan.db')
        (self.root/'app.c').write_text('int live_changed;\n',encoding='utf-8')

    def test_real_stdio_source_pages_use_archive_even_with_different_live_bytes(self):
        ref=self.provider.archived_source('app.c');offset=0;requests=[];expected=[]
        while True:
            page=self.provider.text(ref['text_node'],offset=offset,limit=16384)
            requests.append(dict(jsonrpc='2.0',id=len(requests),method='tools/call',params=dict(name='source',arguments=dict(file='app.c',offset=offset))))
            expected.append(page['value']);offset=page['next_offset']
            if offset is None:break
        requests.append(dict(jsonrpc='2.0',id=100,method='tools/call',params=dict(name='source',arguments=dict(file='../../private.c'))))
        requests.append(dict(jsonrpc='2.0',id=101,method='tools/call',params=dict(name='source',arguments=dict(file='app.c',limit=20000))))
        proc=run([sys.executable,'-B','-X','utf8','-m','ecra.evidence_mcp','--database',str(self.out/'scan.db')],
            input='\n'.join(json.dumps(r) for r in requests)+'\n',text=True,encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr)
        rows=[json.loads(line)['result'] for line in proc.stdout.splitlines()]
        pages=[json.loads(row['content'][0]['text']) for row in rows[:-2]]
        self.assertEqual(''.join(page['value'] for page in pages),self.text)
        self.assertTrue(all(page['sha256']==self.sha and not page['missing_context'] for page in pages))
        self.assertTrue(json.loads(rows[-2]['content'][0]['text'])['missing_context'])
        self.assertTrue(rows[-1]['isError'])

    def test_citations_and_source_hashes_use_archive_inside_explicit_worker_scopes(self):
        archived=ArchivedSources(self.root,self.provider)
        def worker(_):
            with source_scope(archived):
                evidence=[dict(file='app.c',line=1,quote='int shared;')]
                validate_source_evidence(evidence,self.root,required=True,require_quotes=True)
                self.assertEqual(read_source(self.root/'app.c'),(self.text,self.sha))
                with self.assertRaisesRegex(ValueError,'归档缺少'):
                    read_source(self.root/'missing.c')
                return collect_evidence(self.root,dict(evidence=evidence))
        with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(worker,range(4)))
        self.assertTrue(all(row[0]['sha256']==self.sha and row[0]['lines'][0]['text']=='int shared; // 中文' for row in rows))
        self.assertIn('live_changed',read_source(self.root/'app.c')[0])

    def test_canonical_parallel_review_and_independent_receipt_use_archived_source(self):
        cfg=dict(review=dict(enabled=True,retries=0,workers=2),analysis={})
        def respond(argv,**kwargs):
            packet=json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
            answer=answer_for(fid=packet['finding_id'])
            answer['evidence']=[dict(file='app.c',line=2,claim='仅用于协议测试')]
            permissions=json.loads(kwargs['env']['OPENCODE_CONFIG_CONTENT'])['permission']
            self.assertNotIn('*.c',permissions['read'])
            self.assertNotIn('*app.c',permissions['read'])
            return CompletedProcess(argv,0,json.dumps(answer,ensure_ascii=False),'')
        with patch('ecra.review.resolve_command',return_value=['synthetic-test-executor']),patch('ecra.review.execute',side_effect=respond):
            rows=review_all(self.root,self.out,cfg,self.facts,self.report,'scan',progress=lambda text:None)
        self.assertEqual([row['state'] for row in rows],['DONE','DONE'],[(r['finding_id'],r.get('error')) for r in rows])
        for row in rows:
            self.assertEqual(row['source_evidence'][0]['sha256'],self.sha)
            self.assertEqual(verify_receipt(self.root,self.out/'review',row)['finding_id'],row['finding_id'])

    def test_archived_only_permissions_allow_exact_documents_and_no_source_globs(self):
        packet=self.out/'review/packet.json'
        config=json.loads(_review_env([packet],evidence_database=self.out/'scan.db',archived_sources_only=True)['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(config['permission']['read'][str(packet)],'allow')
        self.assertEqual(config['permission']['read']['*'],'deny')
        self.assertNotIn('*packet.json',config['permission']['read'])
        self.assertNotIn('*.h',config['permission']['read'])
        self.assertEqual(config['permission']['ecra_evidence_*'],'allow')
