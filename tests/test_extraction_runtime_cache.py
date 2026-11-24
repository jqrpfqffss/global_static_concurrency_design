import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ecra.input_snapshot import file_record
from ecra.path_io import filesystem_path
from ecra.tu_cache import TUCache
from ecra.common import read_json


class ExtractionRuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra runtime cache ')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'a.c';self.source.write_bytes(b'int x;\n')
        self.unit=dict(tu_id='one',source_file='a.c',directory=str(self.root),original_arguments=[sys.executable])
        self.snapshot=SimpleNamespace(preprocessor={'one':{'signature':'unchanged'}},dependencies={'one':[str(self.source)]},
                                      before={str(self.source):file_record(self.source)},assert_valid=lambda:None)
        self.cfg=dict(analysis={},project=dict(root=str(self.root)))

    def cache(self):
        return TUCache(self.root/'cache',self.cfg,self.snapshot)

    @unittest.skipUnless(os.name == 'nt', 'requires the Windows path limit')
    def test_store_and_restore_verified_facts_on_long_windows_paths(self):
        directory = self.root / ('c' * max(1, 218 - len(str(self.root))))
        filesystem_path(directory).mkdir()
        self.addCleanup(shutil.rmtree, filesystem_path(directory))
        payload = self.root / 'raw.json'
        payload.write_bytes(b'{"accesses":[{"access_id":"a"}]}')
        metadata = dict(parse_status='PARSED', input_snapshot={'sealed': True})
        with patch.dict(os.environ, PYTHONHASHSEED='0'):
            cache = TUCache(directory, self.cfg, self.snapshot)
            key = cache.key(self.unit)
            self.assertGreater(len(str(directory / (key + '.pending'))), 260)
            cache.store(self.unit, payload, metadata)
            output = directory / ('r' * 60 + '.json')
            receipt = directory / ('m' * 60 + '.json')
            self.assertTrue(TUCache(directory, self.cfg, self.snapshot).restore(self.unit, output, receipt))
            self.assertEqual(filesystem_path(output).read_bytes(), payload.read_bytes())
            self.assertEqual(read_json(filesystem_path(receipt)), metadata)

    def test_copy_fallback_must_match_source_before_publishing_or_returning_hit(self):
        cache = self.cache()
        source = self.root/'worker.json'
        source.write_bytes(b'original verified facts')
        meta = dict(parse_status='PARSED', input_snapshot={'sealed': True})
        output = self.root/'restored.json'
        receipt = self.root/'restored.meta.json'

        def corrupt(source, destination):
            Path(destination).write_bytes(b'incomplete copy')

        with patch('ecra.tu_cache.os.link', side_effect=OSError('different volume')):
            with patch('ecra.tu_cache.shutil.copyfile', side_effect=corrupt):
                with self.assertRaisesRegex(ValueError, '摘要'):
                    cache.store(self.unit, source, meta)
            self.assertEqual(list(cache.folder.iterdir()), [])
            self.assertEqual(source.read_bytes(), b'original verified facts')
            authority = cache.store(self.unit, source, meta)
            with patch('ecra.tu_cache.shutil.copyfile', side_effect=corrupt):
                self.assertFalse(cache.restore(self.unit, output, receipt))
            self.assertFalse(output.exists())
            self.assertEqual(authority.read_bytes(), source.read_bytes())

    def test_restore_does_not_expose_a_writable_cache_link_when_metadata_fails(self):
        cache = self.cache()
        source = self.root/'worker.json'
        source.write_bytes(b'sealed')
        meta = dict(parse_status='PARSED', input_snapshot={'sealed': True})
        authority = cache.store(self.unit, source, meta)
        output = self.root/'slot.json'
        with patch('ecra.tu_cache.write_json', side_effect=OSError('full')):
            self.assertFalse(cache.restore(self.unit, output, self.root/'slot.meta.json'))
        output.write_bytes(b'retry extractor')
        self.assertEqual(authority.read_bytes(), b'sealed')

    def test_default_worker_seed_matches_explicit_zero_and_does_not_mutate_parent_environment(self):
        with patch.dict(os.environ):
            os.environ.pop('PYTHONHASHSEED',None);os.environ.pop('SOURCE_DATE_EPOCH',None)
            first=self.cache().key(self.unit);self.assertNotIn('PYTHONHASHSEED',os.environ)
            os.environ['PYTHONHASHSEED']='0';self.assertEqual(self.cache().key(self.unit),first)
            os.environ['PYTHONHASHSEED']='';self.assertEqual(self.cache().key(self.unit),first)

    def test_changed_seed_or_source_date_cannot_restore_old_cached_inventory_or_delete_it(self):
        with patch.dict(os.environ):
            os.environ['PYTHONHASHSEED']='0';os.environ.pop('SOURCE_DATE_EPOCH',None)
            cache=self.cache();payload=self.root/'raw.json';payload.write_bytes(b'{"accesses":[{"access_id":"a"},{"access_id":"b"}]}')
            metadata=dict(parse_status='PARSED',input_snapshot={'sealed':True})
            cache.store(self.unit,payload,metadata)
            before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.folder.iterdir()}
            for updates in [dict(PYTHONHASHSEED='1'),dict(SOURCE_DATE_EPOCH='1793577600')]:
                with self.subTest(updates=updates),patch.dict(os.environ,updates):
                    changed=self.cache()
                    self.assertNotEqual(changed.key(self.unit),cache.key(self.unit))
                    self.assertFalse(changed.restore(self.unit,self.root/'restored.json',self.root/'metadata.json'))
                    self.assertFalse((self.root/'restored.json').exists())
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.folder.iterdir()})
            self.assertTrue(self.cache().restore(self.unit,self.root/'restored.json',self.root/'metadata.json'))
            self.assertEqual((self.root/'restored.json').read_bytes(),payload.read_bytes())

    def test_pre_clock_model_cache_cannot_supply_a_safe_result(self):
        from ecra.workflow import engine_digest
        with patch('ecra.tu_cache.engine_digest', return_value='pre-clock-model'):
            old = self.cache()
            payload = self.root/'before.json'
            payload.write_text('{"variables":[],"dynamic_predefined_inputs":[]}')
            old.store(self.unit, payload, dict(parse_status='PARSED', input_snapshot={'sealed':True}))
        current = self.cache()
        self.assertEqual(current.engine, engine_digest())
        self.assertNotEqual(current.key(self.unit), old.key(self.unit))
        self.assertFalse(current.restore(self.unit, self.root/'after.json', self.root/'after.meta.json'))
        self.assertTrue((old.folder/(old.key(self.unit)+'.facts')).is_file())

    def test_explicit_random_seed_cannot_reuse_a_different_runs_inventory(self):
        with patch.dict(os.environ,PYTHONHASHSEED='random'):
            first=self.cache();payload=self.root/'random.json';payload.write_bytes(b'{"accesses":["original-order"]}')
            first.store(self.unit,payload,dict(parse_status='PARSED',input_snapshot={'sealed':True}))
            before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in first.folder.iterdir()}
            self.assertFalse(self.cache().restore(self.unit,self.root/'different-run.json',self.root/'different-meta.json'))
            self.assertTrue(first.restore(self.unit,self.root/'same-run.json',self.root/'same-meta.json'))
            self.assertEqual((self.root/'same-run.json').read_bytes(),payload.read_bytes())
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in first.folder.iterdir()})


if __name__=='__main__':unittest.main()
