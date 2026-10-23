import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_solver_stats import read_solver_stats


class SolverStatsReaderTests(unittest.TestCase):
    def read(self,value,chunk=19):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'facts.json'
            path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
            expected=hashlib.sha256(path.read_bytes()).hexdigest()
            return read_solver_stats(path,expected,chunk_bytes=chunk)

    def test_boundaries_unicode_and_escaped_source_do_not_lose_or_forge_metadata(self):
        value=dict(rows=[dict(source='"points_to_stats":{"complete":false} 中断')]*10,
                   points_to_stats=dict(complete=True,evaluations=123),
                   context_points_to_stats=dict(complete=True,reason='固定点完成'))
        for chunk in (1,19,64,65536):
            with self.subTest(chunk=chunk):
                result=self.read(value,chunk)
                self.assertTrue(result['all_complete'])
                self.assertTrue(result['hash_bound'])
                self.assertEqual(result['solver_summaries']['context_points_to_stats']['reason'],'固定点完成')

    def test_reaching_later_stage_is_not_a_complete_fixed_point(self):
        result=self.read(dict(points_to_stats=dict(complete=True),
                              context_points_to_stats=dict(complete=False,iterations=8)))
        self.assertFalse(result['all_complete'])

    def test_missing_non_boolean_and_ambiguous_metadata_are_rejected(self):
        cases=[dict(points_to_stats=dict(complete=True)),
               dict(points_to_stats=dict(complete=1),context_points_to_stats=dict(complete=True)),
               dict(nested=dict(points_to_stats=dict(complete=True)),
                    points_to_stats=dict(complete=True),context_points_to_stats=dict(complete=True))]
        for value in cases:
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.read(value)

    def test_checkpoint_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'facts.json'
            path.write_text(json.dumps(dict(points_to_stats=dict(complete=True),
                                           context_points_to_stats=dict(complete=True))))
            with self.assertRaisesRegex(ValueError,'hash differs'):
                read_solver_stats(path,'0'*64)
