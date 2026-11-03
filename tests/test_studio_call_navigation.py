from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.studio.query import QueryService


class CallNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA legacy graph navigation ')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def make(self,name,calls):
        out=self.root/'data/scans'/name
        functions=[dict(function_id='tu::a.c::helper',name='helper',file='a.c',line=1),
                   dict(function_id='tu::b.c::helper',name='helper',file='b.c',line=2),
                   dict(function_id='sink',name='sink',file='sink.c',line=3)]
        publish_scan(out/'scan.db',dict(variables=[],functions=functions,calls=calls),dict(findings=[]),scan_id=name,project_id='p')
        return out

    def test_historical_aliases_use_exact_projected_identity_without_merging_duplicate_callsites(self):
        calls=[dict(caller_id='tu::a.c::helper',callee_id='sink',file='a.c',line=11),
               dict(caller='tu::b.c::helper',callee='sink',file='b.c',line=22),
               dict(caller_function_id='tu::a.c::helper',caller_id='tu::b.c::helper',callee_function_id='sink',file='a.c',line=33),
               dict(caller_id='tu::a.c::helper',callee_id='sink',file='a.c',line=44)]
        out=self.make('current',calls);before=(out/'scan.db').read_bytes();query=QueryService(out)
        page=query.call_neighbors('sink',direction='upstream',limit=2)
        self.assertEqual((page['total'],page['next_offset']),(4,2));all_rows=page['items']+query.call_neighbors('sink',direction='upstream',offset=2,limit=2)['items']
        self.assertEqual([r['neighbor_id'] for r in all_rows],['tu::a.c::helper','tu::b.c::helper','tu::a.c::helper','tu::a.c::helper'])
        self.assertEqual([r['summary']['line'] for r in all_rows],[11,22,33,44])
        self.assertEqual([r['definitions'][0]['summary']['file'] for r in all_rows],['a.c','b.c','a.c','a.c'])
        down=query.call_neighbors('tu::a.c::helper',direction='downstream');self.assertEqual(down['total'],3)
        self.assertEqual([r['neighbor_id'] for r in down['items']],['sink']*3)
        self.assertEqual(query.call_neighbors('tu::b.c::helper',direction='downstream')['total'],1)
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        with TestClient(create_app(self.root/'data',token='legacy-call-navigation-test')) as client:
            response=client.get('/api/scans/current/call-neighbors',params=dict(function_id='sink',direction='upstream',limit=2),
                headers={'Host':'127.0.0.1:8765','X-ECRA-Session':'legacy-call-navigation-test'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual([r['neighbor_id'] for r in response.json()['items']],['tu::a.c::helper','tu::b.c::helper'])
        self.assertEqual((out/'scan.db').read_bytes(),before);EvidenceProvider(out/'scan.db').validate(deep=True)

    def test_v1_engine_field_fallback_still_navigates_without_rewriting_original_archive(self):
        current=self.make('new',[dict(caller_function_id='tu::a.c::helper',callee_function_id='sink',file='a.c',line=11)])
        out=self.root/'v1';out.mkdir();schema=Path(__file__).with_name('fixtures').joinpath('v23_scan_schema.sql').read_text('utf-8')
        with closing(sqlite3.connect(out/'scan.db',uri=True)) as conn,conn:
            conn.executescript(schema);conn.execute('PRAGMA user_version=1')
            conn.execute('ATTACH DATABASE ? AS original',((current/'scan.db').resolve().as_uri()+'?mode=ro',))
            for table in ['nodes','edges','roots','records','symbols','projects','profiles','scans']:
                conn.execute('INSERT INTO '+table+' SELECT * FROM original.'+table)
            conn.execute('UPDATE records SET source_id=NULL,target_id=NULL')
        EvidenceProvider(out/'scan.db').validate(deep=True);before=(out/'scan.db').read_bytes();query=QueryService(out)
        up=query.call_neighbors('sink',direction='upstream');down=query.call_neighbors('tu::a.c::helper',direction='downstream')
        self.assertEqual(up['items'][0]['neighbor_id'],'tu::a.c::helper');self.assertEqual(down['items'][0]['neighbor_id'],'sink')
        self.assertEqual(up['items'][0]['definitions'][0]['summary']['file'],'a.c')
        self.assertEqual((out/'scan.db').read_bytes(),before)


if __name__=='__main__':unittest.main()
