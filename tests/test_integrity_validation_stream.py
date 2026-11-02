"""Independent frozen verifier acceptance, complete negative graphs and SQL cost."""
from contextlib import closing
import hashlib
import inspect
import random
import shutil
import sqlite3
import tempfile
import textwrap
from pathlib import Path
import unittest
from unittest.mock import patch

import ecra.scan_store as store
from tests.fixtures import v3cf_validate as original


class IntegrityValidationStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.path=self.base/'valid.db'
        store.publish_scan(self.path,dict(variables=[],future=dict(values=[0,1,2],text='',flag=False)),
                           dict(findings=[]),scan_id='s',project_id='p')

    def accepted(self,path,validator):
        try:validator(store.EvidenceProvider(path),deep=True)
        except Exception:return False
        return True

    def both(self,path,expected):
        before=path.read_bytes()
        self.assertEqual(self.accepted(path,original.validate_original),expected)
        self.assertEqual(self.accepted(path,store.EvidenceProvider.validate),expected)
        self.assertEqual(path.read_bytes(),before)

    def rehash(self,path):
        """An adversary recomputes ALL ancestors, so codec tests reach the leaf."""
        with closing(sqlite3.connect(path)) as conn,conn:
            cache={}
            def visit(ident):
                if ident in cache:return cache[ident]
                kind,value,length=conn.execute('SELECT kind,value,length FROM nodes WHERE id=?',(ident,)).fetchone()
                hasher=store._hash_start(kind,length)
                if kind in {'object','list'}:
                    for key,child in conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(ident,)).fetchall():
                        store._hash_edge(hasher,key,visit(child))
                else:hasher.update(value)
                digest=hasher.hexdigest();conn.execute('UPDATE nodes SET hash=? WHERE id=?',(digest,ident));cache[ident]=digest;return digest
            for name,ident in conn.execute('SELECT name,node FROM roots').fetchall():
                digest=visit(ident)
                if name in {'facts','report'}:conn.execute('UPDATE scans SET '+name+'_hash=?',(digest,))

    def test_frozen_reference_has_exact_original_lf_source(self):
        source=textwrap.dedent(inspect.getsource(original.validate_original)).replace('def validate_original(','def validate(',1)
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),original.ORIGINAL_LF_SHA256)
        self.assertEqual(original.ORIGINAL_LF_SHA256,'2ae0baba1580a5d7392fc6a1ef47c86edc48632fc756328c5ffb42ea4633be13')

    def test_seeded_complete_graphs_match_original_for_types_orders_and_duplicates(self):
        rng=random.Random(21023)
        for index in range(20):
            value=[None,False,0,-0.0,2**90,'😀','\ud800','same','same']
            rng.shuffle(value);path=self.base/('seed-'+str(index)+'.db')
            store.publish_scan(path,dict(variables=[],future={str(i):[value[:],dict(z=rng.randrange(30),a=[]) ] for i in range(20)}),dict(findings=[]),scan_id='s',project_id='p')
            with self.subTest(seed=index):self.both(path,True)

    def test_all_edge_and_metadata_corruptions_stay_rejected(self):
        provider=store.EvidenceProvider(self.path);array=provider.resolve('facts',['future','values']);scalar=provider.resolve('facts',['future','values',0])
        cases=[('missing','DELETE FROM edges WHERE parent=? AND ordinal=1',(array,)),
               ('gap','UPDATE edges SET ordinal=9 WHERE parent=? AND ordinal=0',(array,)),
               ('extra','INSERT INTO edges VALUES (?,99,NULL,?)',(array,scalar)),
               ('key','UPDATE edges SET key=\'illegal\' WHERE parent=? AND ordinal=0',(array,)),
               ('scalar-edge','INSERT INTO edges VALUES (?,0,NULL,?)',(scalar,scalar)),
               ('kind','UPDATE nodes SET kind=\'unknown\' WHERE id=?',(scalar,)),
               ('type',"UPDATE nodes SET value='0' WHERE id=?",(scalar,)),
               ('length','UPDATE nodes SET length=0.5 WHERE id=?',(scalar,)),
               ('hash','UPDATE nodes SET hash=? WHERE id=?',('z'*64,scalar)),
               ('hash-blob','UPDATE nodes SET hash=? WHERE id=?',(sqlite3.Binary(b'\x00'*32),scalar))]
        for name,sql,args in cases:
            with self.subTest(name=name):
                path=self.base/(name+'.db');shutil.copyfile(self.path,path)
                with closing(sqlite3.connect(path)) as conn,conn:conn.execute(sql,args)
                self.both(path,False)

    def test_rehashed_noncanonical_codecs_and_actual_scalar_boundaries_are_not_blessed(self):
        for name,kind,payload in [('int-leading-zero','int',b'00'),('int-plus','int',b'+1'),
            ('null-tail','null',b'x'),('bool-tail','bool',b'00'),('float-decimal','float',b'1.0'),('utf8','str',b'\xff')]:
            with self.subTest(name=name):
                path=self.base/(name+'.db');shutil.copyfile(self.path,path);node=store.EvidenceProvider(path).resolve('facts',['future','text'])
                with closing(sqlite3.connect(path)) as conn,conn:conn.execute('UPDATE nodes SET kind=?,value=?,length=? WHERE id=?',(kind,sqlite3.Binary(payload),len(payload),node))
                self.rehash(path);self.both(path,False)
        for length in [0,4096,4097,1024**2,1024**2+1]:
            with self.subTest(length=length):
                path=self.base/('boundary-'+str(length)+'.db')
                store.publish_scan(path,dict(variables=[],future='x'*length),dict(findings=[]),scan_id='s',project_id='p');self.both(path,True)
                node=store.EvidenceProvider(path).resolve('facts',['future'])
                with closing(sqlite3.connect(path)) as conn,conn:
                    raw=conn.execute('SELECT value FROM nodes WHERE id=?',(node,)).fetchone()[0]
                    conn.execute('UPDATE nodes SET value=? WHERE id=?',(sqlite3.Binary(raw+b'tail'),node))
                self.both(path,False)

    def test_duplicate_keys_beyond_acceleration_bound_use_complete_sql_check(self):
        for size in [4096,4097,5000]:
            with self.subTest(size=size):
                path=self.base/('keys-'+str(size)+'.db')
                store.publish_scan(path,dict(variables=[],future={str(i):i for i in range(size)}),dict(findings=[]),scan_id='s',project_id='p')
                self.both(path,True);ident=store.EvidenceProvider(path).resolve('facts',['future'])
                with closing(sqlite3.connect(path)) as conn,conn:conn.execute('UPDATE edges SET key=\'0\' WHERE parent=? AND ordinal=?',(ident,size-1))
                # Keep the root/ancestors consistent; the duplicate itself must fail.
                self.rehash(path);self.both(path,False)

    def test_projection_rows_and_root_binding_still_have_complete_checks(self):
        for name,sql in [('projection',"INSERT INTO records VALUES ('facts','future',99,1,NULL,NULL,NULL,NULL)"),
                         ('root',"UPDATE scans SET facts_hash='fake'")]:
            with self.subTest(name=name):
                path=self.base/(name+'.db');shutil.copyfile(self.path,path)
                with closing(sqlite3.connect(path)) as conn,conn:conn.execute(sql)
                self.both(path,False)

    def test_complete_source_sql_reads_are_streamed_instead_of_per_node(self):
        path=self.base/'capacity.db'
        store.publish_scan(path,dict(variables=[],future={str(i):dict(value=str(i),items=['same',i]) for i in range(6000)}),dict(findings=[]),scan_id='s',project_id='p')
        connect=store.connect_readonly;counts=[]
        for validator in [original.validate_original,store.EvidenceProvider.validate]:
            count=[0]
            def connection(p):
                conn=connect(p)
                def trace(_):count[0]+=1
                conn.set_trace_callback(trace);return conn
            with patch.object(store,'connect_readonly',connection),patch.object(original,'connect_readonly',connection):
                validator(store.EvidenceProvider(path),deep=True)
            counts.append(count[0])
        self.assertGreater(counts[0],30000);self.assertLess(counts[1],counts[0]//10)

    def test_real_wal_commit_during_validation_keeps_one_read_snapshot(self):
        connect=store.connect_readonly
        for index,validator in enumerate([original.validate_original,store.EvidenceProvider.validate]):
            with self.subTest(validator=index):
                path=self.base/('snapshot-'+str(index)+'.db');shutil.copyfile(self.path,path)
                with closing(sqlite3.connect(path)) as db:db.execute('PRAGMA journal_mode=WAL')
                ident=store.EvidenceProvider(path).resolve('facts',['future','text']);committed=[];errors=[]
                def connection(p):
                    conn=connect(p)
                    def trace(sql):
                        if sql.startswith('SELECT id,hash,kind,length,') and not committed and not errors:
                            try:
                                with closing(sqlite3.connect(path)) as writer,writer:
                                    writer.execute('UPDATE nodes SET value=? WHERE id=?',(sqlite3.Binary(b'corrupt concurrent tail'),ident))
                                committed.append(True)
                            except Exception as exc:errors.append(str(exc))
                    conn.set_trace_callback(trace);return conn
                with patch.object(store,'connect_readonly',connection),patch.object(original,'connect_readonly',connection):
                    validator(store.EvidenceProvider(path),deep=True)
                self.assertEqual(errors,[]);self.assertEqual(committed,[True])
                self.assertFalse(self.accepted(path,store.EvidenceProvider.validate))


if __name__=='__main__':unittest.main()
