"""A stop must interrupt a SQLite call, rather than wait for Python to return."""
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ecra.scan_diagnostics import ScanDiagnostics, interruptible_sqlite


class SQLiteScanStopTests(unittest.TestCase):
    def test_registered_connections_are_released_and_unrequested_errors_remain_errors(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'ECRA_JOB_STOP_FILE': str(Path(temp)/'stop')}):
            diagnostics=ScanDiagnostics(Path(temp)/'diagnostics')
            try:
                with sqlite3.connect(':memory:') as connection:
                    with interruptible_sqlite(connection):
                        self.assertEqual(connection.execute('SELECT 42').fetchone(),(42,))
                    self.assertEqual(diagnostics.sqlite_connections,set())
                    with self.assertRaisesRegex(sqlite3.OperationalError,'interrupted'):
                        with interruptible_sqlite(connection):
                            raise sqlite3.OperationalError('interrupted')
                    self.assertEqual(diagnostics.sqlite_connections,set())
            finally:diagnostics.close()

    def test_existing_stop_refuses_before_sql_and_does_not_leak_a_connection(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'ECRA_JOB_STOP_FILE': str(Path(temp)/'stop')}):
            diagnostics=ScanDiagnostics(Path(temp)/'diagnostics')
            try:
                (Path(temp)/'stop').write_text('test','ascii')
                with sqlite3.connect(':memory:') as connection:
                    with self.assertRaises(KeyboardInterrupt):
                        with interruptible_sqlite(connection):
                            self.fail('An already requested stop cannot start SQL')
                    self.assertEqual(diagnostics.sqlite_connections,set())
            finally:diagnostics.close()

    def test_publish_and_complete_validation_interrupt_busy_sql_keep_old_authority(self):
        code=r'''
import hashlib,json,os,sqlite3,sys,threading,time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from ecra.scan_store import publish_scan,EvidenceProvider
import ecra.scan_store as store
from ecra.scan_diagnostics import ScanDiagnostics
work=Path(sys.argv[1]);mode=sys.argv[2]
original=work/'old.db';publish_scan(original,{'variables':[]},{'findings':[]},scan_id='old',project_id='p')
before=hashlib.sha256(original.read_bytes()).hexdigest()
os.environ['ECRA_JOB_STOP_FILE']=str(work/'stop')
entered=threading.Event();finished=threading.Event()
stop_write_started=[None];stop_written=[False];interrupted_at=None
class BusyIntegrity(sqlite3.Connection):
 def execute(self,sql,*args,**kw):
  if sql=='PRAGMA integrity_check':
   entered.set()
   super().execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<1000000000) SELECT sum(x) FROM n').fetchone()
  return super().execute(sql,*args,**kw)
connect=sqlite3.connect
def factory(*args,**kw):return connect(*args,**dict(kw,factory=BusyIntegrity))
def request():
 while not finished.is_set():
  if entered.wait(.05):
   if finished.is_set():return
   # Measure the actual stop write, not old/new publication preparation.
   stop_write_started[0]=time.monotonic()
   (work/'stop').write_text('test','ascii')
   stop_written[0]=True
   return
thread=threading.Thread(target=request);thread.start()
d=ScanDiagnostics(work/'diagnostics');start=time.monotonic();stopped=False
try:
 if mode=='validate':
  with patch.object(store,'connect_readonly',lambda path:factory(path.resolve().as_uri()+'?mode=ro',uri=True)):
   EvidenceProvider(original).validate()
 else:
  with patch.object(store.sqlite3,'connect',factory):
   publish_scan(work/'new.db',{'variables':[]},{'findings':[]},scan_id='new',project_id='p')
except KeyboardInterrupt:stopped=True;interrupted_at=time.monotonic()
finally:finished.set();thread.join(timeout=6);d.close()
stop_seconds=interrupted_at-stop_write_started[0] if interrupted_at is not None and stop_write_started[0] is not None else None
result={'stopped':stopped,'entered':entered.is_set(),'seconds':time.monotonic()-start,'stop_written':stop_written[0],'stop_seconds':stop_seconds,'connections':len(d.sqlite_connections),'old_unchanged':before==hashlib.sha256(original.read_bytes()).hexdigest(),'new_published':(work/'new.db').exists(),'pending':len(list(work.glob('*.pending')))}
print(json.dumps(result))
'''
        root=Path(__file__).resolve().parents[1]
        for mode in ('publish','validate'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,temp,mode],cwd=root,
                    capture_output=True,text=True,encoding='utf-8',timeout=180)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                value=json.loads(result.stdout.strip().splitlines()[-1])
                self.assertTrue(value['entered']);self.assertTrue(value['stopped'])
                self.assertTrue(value['stop_written']);self.assertIsNotNone(value['stop_seconds'])
                self.assertGreaterEqual(value['stop_seconds'],0);self.assertLess(value['stop_seconds'],5)
                self.assertTrue(value['old_unchanged']);self.assertFalse(value['new_published'])
                self.assertEqual((value['connections'],value['pending']),(0,0))
