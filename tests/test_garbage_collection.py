import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ecra import garbage_collection as gc
from ecra.common import write_json
from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.storage_activity import DataActivity


class GarbageCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra GC 中文 ');self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name).resolve()/'data'
        self.scan=self.data/'scans/s1';self.scan.mkdir(parents=True)
        self.objects=self.scan/'evidence';self.objects.mkdir()
        self.kept=self.object(b'permanent cited evidence')
        self.discard=self.object(b'unreferenced duplicate')
        publish_scan(self.scan/'scan.db',dict(variables=[dict(symbol_id='x',name='x',static_classification='UNKNOWN')],
            evidence_reference=self.kept.name),dict(findings=[]),scan_id='s1',project_id='p')
        self.provider=EvidenceProvider(self.scan/'scan.db')
        self.store=ReviewStore(self.scan/'reviews.db',self.provider.metadata())
        write_json(self.scan/'manifest.json',dict(format='ECRA_LOCAL_SCAN',scan_id='s1',scan_sha256=sha256(self.scan/'scan.db')))
        self.before=sha256(self.scan/'scan.db')

    def object(self,raw):
        hashed=hashlib.sha256(raw).hexdigest();path=self.objects/hashed;path.write_bytes(raw);return path

    def test_preview_quarantine_restore_and_purge_keep_static_and_human_proof(self):
        self.store.append('x',self.provider.fingerprint('x'),decision='CONFIRMED_RISK',reviewer='声明',comment='保留此审计')
        original=self.store.history()
        preview=gc.preview(self.data)
        self.assertEqual(preview['files'],1)
        self.assertEqual(preview['items'][0]['relative'],self.discard.relative_to(self.data).as_posix())
        self.assertTrue(self.discard.exists())
        moved=gc.quarantine(self.data,preview['id']);self.assertEqual(moved['state'],'QUARANTINED')
        self.assertFalse(self.discard.exists());self.assertTrue(self.kept.exists())
        gc.restore(self.data,preview['id']);self.assertTrue(self.discard.exists())
        second=gc.preview(self.data);gc.quarantine(self.data,second['id']);gc.purge(self.data,second['id'])
        self.assertFalse(self.discard.exists());self.assertTrue(self.kept.exists())
        self.assertEqual(sha256(self.scan/'scan.db'),self.before)
        self.assertEqual(self.store.history(),original)
        self.provider.validate(deep=True)

    def test_new_human_reference_invalidates_preview_and_late_reference_restores_trash(self):
        preview=gc.preview(self.data)
        event=self.store.append('x',self.provider.fingerprint('x'),decision='NEED_MORE_EVIDENCE',reviewer='声明',comment=self.discard.name)
        with self.assertRaisesRegex(ValueError,'变化'):
            gc.quarantine(self.data,preview['id'])
        self.assertTrue(self.discard.exists())
        another=self.object(b'late reference')
        preview=gc.preview(self.data);gc.quarantine(self.data,preview['id'])
        self.store.append('x',self.provider.fingerprint('x'),decision='NEED_MORE_EVIDENCE',reviewer='声明',comment=another.name,expected_heads=[event['event_id']])
        gc.purge(self.data,preview['id'])
        self.assertTrue(another.exists())

    def test_move_failure_rolls_back_all_prior_moves(self):
        self.object(b'another unreachable object')
        preview=gc.preview(self.data)
        rename=Path.rename;calls=[]
        def failing(path,target):
            if '/trash/' in Path(target).as_posix():
                calls.append(path)
                if len(calls)==2:raise PermissionError('injected sharing violation')
            return rename(path,target)
        with patch.object(Path,'rename',failing):
            with self.assertRaisesRegex(PermissionError,'sharing violation'):
                gc.quarantine(self.data,preview['id'])
        self.assertEqual(gc.status(self.data,preview['id'])['state'],'RESTORED')
        self.assertTrue(self.discard.exists());self.assertTrue(self.kept.exists())
        self.assertEqual(sha256(self.scan/'scan.db'),self.before)

    def test_cross_process_shared_activity_blocks_exclusive_cleanup(self):
        code='from ecra.storage_activity import DataActivity;from pathlib import Path;import sys\ntry:\n with DataActivity(Path(sys.argv[1]),exclusive=True):pass\nexcept ValueError:raise SystemExit(42)'
        with DataActivity(self.data),DataActivity(self.data):
            result=subprocess.run([sys.executable,'-B','-c',code,str(self.data)],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,42,result.stderr)
            with self.assertRaises(ValueError):
                with DataActivity(self.data,exclusive=True):pass
        with DataActivity(self.data,exclusive=True):
            with self.assertRaises(ValueError):
                with DataActivity(self.data):pass

    def test_tampered_preview_cannot_move_a_referenced_object_or_outside_file(self):
        preview=gc.preview(self.data)
        path=self.data/'work/gc'/preview['id']/'preview.db'
        with sqlite3.connect(path) as conn:
            conn.execute('UPDATE candidates SET relative=?,sha256=?',(self.kept.relative_to(self.data).as_posix(),self.kept.name))
        with self.assertRaises(ValueError):gc.quarantine(self.data,preview['id'])
        self.assertTrue(self.kept.exists())

    def test_actual_process_exit_between_move_and_journal_commit_can_restore(self):
        preview=gc.preview(self.data)
        code='''from pathlib import Path
import os,sys
from ecra import garbage_collection as gc
original=Path.rename
def exit_after_move(path,target):
 result=original(path,target)
 if '/trash/' in Path(target).as_posix():os._exit(99)
 return result
Path.rename=exit_after_move
gc.quarantine(Path(sys.argv[1]),sys.argv[2])
'''
        result=subprocess.run([sys.executable,'-B','-c',code,str(self.data),preview['id']],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,99,result.stderr)
        self.assertFalse(self.discard.exists())
        self.assertEqual(gc.status(self.data,preview['id'])['state'],'MOVING')
        gc.restore(self.data,preview['id'])
        self.assertTrue(self.discard.exists());self.assertTrue(self.kept.exists())
        self.assertEqual(sha256(self.scan/'scan.db'),self.before)

    def test_resolver_results_and_git_baseline_cache_layout_are_the_owned_candidates(self):
        from ecra.workspace import WorkspaceResolver
        root=Path(self.temp.name)/'firmware';root.mkdir()
        ws=WorkspaceResolver.resolve(root,dict(output=dict(location='custom',custom_dir=str(self.data)))).initialize()
        paths=[]
        for cache in (Path(ws.cache_root)/'formal/tu-v1',Path(ws.results_root)/'git_diff/artifacts/base/cache/tu-v1'):
            cache.mkdir(parents=True)
            path=cache/(hashlib.sha256(str(cache).encode()).hexdigest()+'.facts');path.write_bytes(b'disposable cache');paths.append(path)
        wrong=Path(ws.project_workspace)/'cache/tu-v1';wrong.mkdir(parents=True)
        protected=wrong/('a'*64+'.facts');protected.write_bytes(b'unknown layout must not be deleted')
        plan=gc.preview(self.data)
        proposed={row['relative'] for row in plan['items']}
        self.assertTrue(all(path.relative_to(self.data).as_posix() in proposed for path in paths))
        self.assertNotIn(protected.relative_to(self.data).as_posix(),proposed)
        gc.quarantine(self.data,plan['id']);gc.restore(self.data,plan['id'])
        self.assertTrue(all(path.is_file() for path in paths));self.assertTrue(protected.is_file())

    def test_unfinished_native_task_and_partial_cli_scan_preserve_committed_tu_cache(self):
        from ecra.workspace import WorkspaceResolver
        root=Path(self.temp.name)/'firmware';root.mkdir()
        ws=WorkspaceResolver.resolve(root,dict(output=dict(location='custom',custom_dir=str(self.data)))).initialize()
        cache=Path(ws.cache_root)/'formal/tu-v1';cache.mkdir(parents=True)
        path=cache/('a'*64+'.facts');path.write_bytes(b'350 committed TUs must survive')
        plan=gc.preview(self.data);gc.quarantine(self.data,plan['id'])
        task=self.data/'work/tasks/stopped/task.json'
        write_json(task,dict(mode='scan',project_id=ws.project_id,state='INTERRUPTED'))
        gc.purge(self.data,plan['id'])
        self.assertTrue(path.exists(),'a late checkpoint must restore quarantined cache')
        self.assertNotIn(path.relative_to(self.data).as_posix(),{row['relative'] for row in gc.preview(self.data)['items']})
        write_json(task,dict(mode='scan',project_id=ws.project_id,state='COMPLETE'))
        partial=self.data/'scans/failed-native';partial.mkdir()
        write_json(partial/'storage.json',dict(project_id=ws.project_id,scan_id='failed-native'))
        self.assertNotIn(path.relative_to(self.data).as_posix(),{row['relative'] for row in gc.preview(self.data)['items']})
