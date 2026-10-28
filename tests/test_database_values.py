from contextlib import closing,redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ecra.common import write_json
from ecra.report import write_database
from scripts.verify_database_values import verify


class DatabaseValuesTests(unittest.TestCase):
    def fixture(self,folder):
        folder=Path(folder);(folder/'reports').mkdir()
        payload=dict(values=[True,1,-0.0,0.0,'中文',{'field':[3,2,2]}])
        facts=dict(variables=[dict(symbol_id='g',enabled=True,payload=payload),
            dict(symbol_id='s',enabled=False,payload=payload)],accesses=[],functions=[])
        report=dict(findings=[dict(finding_id='F1',symbol_id='g',evidence=payload)],review_safe_samples=[])
        write_json(folder/'facts.json',facts);write_json(folder/'reports/global_static_concurrency.json',report)
        write_database(folder/'facts.db',facts,report,shared_threshold=0)
        return folder

    def test_all_nested_values_and_sqlite_scalar_mapping(self):
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
            result=verify(self.fixture(folder))
            self.assertTrue(result['complete'])
            self.assertFalse(result['native_acceptance'])
            self.assertFalse(result['safety_report_valid'])
            self.assertEqual(result['rows']['variables'],2)
            self.assertEqual(result['rows']['findings'],1)
            self.assertGreaterEqual(result['nested_json_cells'],3)

    def test_valid_database_and_equal_counts_cannot_hide_changed_evidence(self):
        for wrong in [[1,True,-0.0,0.0,'中文',{'field':[3,2,2]}],
                      [True,1,-0.0,0.0,'中文',{'field':[2,3,2]}],
                      [True,1,0.0,0.0,'中文',{'field':[3,2,2]}]]:
            with self.subTest(wrong=wrong),tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
                path=self.fixture(folder)
                with closing(sqlite3.connect(path/'facts.db')) as db,db:
                    db.execute('UPDATE variables SET payload=? WHERE symbol_id=?',
                        (json.dumps(dict(values=wrong),ensure_ascii=False),'g'))
                    self.assertEqual(db.execute('SELECT count(*) FROM variables').fetchone()[0],2)
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                with self.assertRaisesRegex(ValueError,'数据库完整证据不一致'):
                    verify(path)
