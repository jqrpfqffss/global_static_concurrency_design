from concurrent.futures import ThreadPoolExecutor as RealPool
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ecra.cli import extraction_responses
from ecra.common import write_json


class BoundedExtractionTests(unittest.TestCase):
    def test_soft_pressure_reduces_admission_and_then_restores_parallelism_without_dropping_tus(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pressure=root/'pressure.json';write_json(pressure,dict(parallel_limit=1))
            units=[dict(tu_id=str(i),source_file=str(i)+'.c') for i in range(30)]
            submitted=[]
            class Pool(RealPool):
                def submit(self,fn,*args,**kwargs):
                    submitted.append(args[0]['tu_id']);return super().submit(fn,*args,**kwargs)
            def worker(argv,**kwargs):
                write_json(Path(argv[-1]),dict(parse_status='PARSED'));return SimpleNamespace(returncode=0,stderr='')
            with (patch.dict('os.environ',dict(ECRA_RESOURCE_PRESSURE_FILE=str(pressure),ECRA_EXTRACTION_WORKERS='4')),
                 patch('concurrent.futures.ThreadPoolExecutor',Pool),patch('ecra.cli.execute',worker)):
                seen=[]
                for unit,_,_ in extraction_responses(root,units,dict(analysis=dict(extraction_workers=1)),root,{},root,root):
                    seen.append(unit['tu_id'])
                    if len(seen)<5:self.assertEqual(len(submitted),len(seen))
                    if len(seen)==5:write_json(pressure,dict(parallel_limit=4))
                    if len(seen)==6:self.assertEqual(len(submitted),9)
            self.assertEqual(seen,[str(i) for i in range(30)])

    def test_slow_consumer_bounds_submissions_and_preserves_all_tu_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            units = [dict(tu_id=str(i), source_file=str(i)+'.c') for i in range(301)]
            submitted = []
            class Pool(RealPool):
                def submit(self, fn, *args, **kwargs):
                    submitted.append(args[0]['tu_id'])
                    return super().submit(fn, *args, **kwargs)
            def worker(argv, **kwargs):
                self.assertEqual(argv[3], 'ecra.extract')
                write_json(Path(argv[-1]), dict(parse_status='PARSED', accesses=[]))
                return SimpleNamespace(returncode=0, stderr='')
            with patch('concurrent.futures.ThreadPoolExecutor', Pool), patch('ecra.cli.execute', worker):
                stream = extraction_responses(root, units, dict(analysis=dict(extraction_workers=3)), root, {}, root, root)
                seen = []
                for unit, response, metadata in stream:
                    seen.append(unit['tu_id'])
                    self.assertTrue(response.is_file())
                    self.assertLessEqual(len(submitted), len(seen)+2,
                        'a paused/slow writer must prevent eager queue growth')
            self.assertEqual(seen, [str(i) for i in range(301)])

    def test_worker_crash_is_fatal_and_generator_close_stops_new_submissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            units = [dict(tu_id=str(i), source_file='a.c') for i in range(20)]
            with patch('ecra.cli.execute', return_value=SimpleNamespace(returncode=9, stderr='crash')):
                stream = extraction_responses(root, units, dict(analysis=dict(extraction_workers=2)), root, {}, root, root)
                with self.assertRaisesRegex(RuntimeError, '退出 9'):
                    next(stream)

