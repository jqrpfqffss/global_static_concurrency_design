"""Parallel import checks must reject the same corruptions and release readers."""
from contextlib import closing
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra.import_validation import validate_imported_database
from ecra.operation_progress import OperationCancelled
from ecra.scan_store import EvidenceProvider, publish_scan


def _abrupt_worker_exit():
    import os
    os._exit(9)


class ImportValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'scan.db'
        publish_scan(self.path, dict(variables=[dict(symbol_id='s', name='中文', static_classification='UNKNOWN')],
            values=[dict(value=i, shared=[True, -0.0, '边界']) for i in range(100)]),
            dict(findings=[]), scan_id='parallel', project_id='p')

    def check(self, progress=None):
        return validate_imported_database(self.path, parallel_threshold=0, progress=progress)

    def test_parallel_checks_exact_bytes_and_all_nodes(self):
        before = self.path.read_bytes(); updates = []
        expected = EvidenceProvider(self.path).validate(deep=True)
        self.assertEqual(self.check(updates.append), expected)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(updates[-1]['completed'], updates[-1]['total'])
        self.assertEqual(updates[-1]['graph_completed'], updates[-1]['graph_total'])

    def test_graph_projection_and_out_of_range_orphan_are_each_rejected(self):
        original = self.path.read_bytes()
        for sql, error in [
                ("UPDATE nodes SET value=x'7461696c' WHERE kind='str' AND length=0", '字节长度'),
                ("UPDATE symbols SET name='forged'", '投影'),
                ("INSERT INTO edges VALUES (-999,0,NULL,-1000)", '引用')]:
            with self.subTest(sql=sql):
                self.path.write_bytes(original)
                with closing(sqlite3.connect(self.path)) as conn, conn:
                    if 'length=0' in sql:
                        node=EvidenceProvider(self.path).resolve('facts', ['values',0,'shared',2])
                        conn.execute('UPDATE nodes SET value=? WHERE id=?', (sqlite3.Binary(b'unhashed tail'),node))
                    else: conn.execute(sql)
                with self.assertRaisesRegex(ValueError, error): self.check()

    def test_cancel_releases_workers_and_database_lock(self):
        before = self.path.read_bytes(); calls = [0]
        previous = {p.pid for p in multiprocessing.active_children()}
        def cancel(change):
            if not change:
                calls[0] += 1
                if calls[0] >= 2: raise OperationCancelled('test cancellation')
        with self.assertRaises(OperationCancelled): self.check(cancel)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, previous)
        with closing(sqlite3.connect(self.path, timeout=.2)) as conn:
            conn.execute('BEGIN EXCLUSIVE'); conn.rollback()

    def test_wal_retains_single_snapshot_validation(self):
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            with writer: writer.execute("UPDATE scans SET state='STATIC_VALIDATED'")
            states=[]
            result=self.check(lambda change: states.append(change.get('stage')))
            self.assertEqual(result['state'], 'STATIC_VALIDATED')
            self.assertIn('VERIFY_GRAPH', states)
            self.assertNotIn('VERIFY_ALL', states)

    def test_worker_exit_fails_without_hanging_or_leaking_readers(self):
        context=multiprocessing.get_context('spawn')
        class ExitContext:
            Event=context.Event
            Pipe=context.Pipe
            def Process(self, **kwargs):
                return context.Process(target=_abrupt_worker_exit)
        before={p.pid for p in multiprocessing.active_children()}
        with patch('ecra.import_validation.multiprocessing.get_context', return_value=ExitContext()):
            with self.assertRaisesRegex(ValueError, '意外退出'):
                self.check()
        self.assertEqual({p.pid for p in multiprocessing.active_children()},before)
        with closing(sqlite3.connect(self.path,timeout=.2)) as conn:
            conn.execute('BEGIN EXCLUSIVE');conn.rollback()


if __name__ == '__main__': unittest.main()
