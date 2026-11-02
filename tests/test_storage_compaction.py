from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra import storage_policy as policy
from ecra.storage_activity import DataActivity
from ecra.storage_compaction import ScanStorage
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.storage_usage import measure


class StoragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA space policy ');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'data'

    def test_default_read_is_side_effect_free_and_active_scan_snapshot_is_fixed(self):
        self.assertEqual(policy.status(self.root)['mode'],'auto');self.assertFalse(self.root.exists())
        fixed=policy.snapshot(self.root)
        with DataActivity(self.root):
            saved=policy.save(self.root,mode='off',revision='missing')
        self.assertTrue(saved['saved']);self.assertEqual(fixed['mode'],'auto');self.assertEqual(policy.snapshot(self.root)['mode'],'off')

    def test_conflicts_unknown_fields_and_exact_prior_bytes_are_preserved(self):
        first=policy.save(self.root,mode='off',revision='missing');file=self.root/'settings/storage-policy.json'
        value=json.loads(file.read_bytes());value['future']={'ordered':[2,1,2]};file.write_text(json.dumps(value),'utf-8');old=file.read_bytes()
        with self.assertRaises(policy.PolicyConflict):policy.save(self.root,mode='auto',revision=first['revision'])
        revision=hashlib.sha256(old).hexdigest();policy.save(self.root,mode='auto',revision=revision)
        self.assertEqual(json.loads(file.read_bytes())['future'],value['future'])
        self.assertEqual((self.root/'settings/storage-policy-backups'/(revision+'.json')).read_bytes(),old)
        with DataActivity(self.root,exclusive=True,purpose='storage-policy'):
            with self.assertRaises(policy.PolicyConflict):policy.save(self.root,mode='off',revision=policy.status(self.root)['revision'])

    def test_corrupt_unknown_or_boolean_schema_never_silently_becomes_auto(self):
        file=self.root/'settings/storage-policy.json';file.parent.mkdir(parents=True)
        for raw in [b'broken',b'{"format":"ECRA_STORAGE_POLICY","version":true,"mode":"auto"}',
                    b'{"format":"ECRA_STORAGE_POLICY","version":1,"mode":["auto"]}']:
            file.write_bytes(raw);state=policy.status(self.root);self.assertFalse(state['valid'])
            with self.assertRaises(ValueError):policy.snapshot(self.root)
            with self.assertRaises(ValueError):policy.save(self.root,mode='off',revision=state['revision'])
            self.assertEqual(file.read_bytes(),raw)
            result=policy.save(self.root,mode='off',revision=state['revision'],repair=True);self.assertTrue(result['valid'])
            self.assertEqual((file.parent/'storage-policy-backups'/(state['revision']+'.json')).read_bytes(),raw)
        for bad in [None,[],True,'future']:
            with self.assertRaises(ValueError):policy.save(self.root,mode=bad,revision='missing')

    def test_snapshot_cannot_be_applied_to_another_data_root(self):
        with self.assertRaises(ValueError):policy.snapshot(self.root/'other',policy.snapshot(self.root))

    def test_actual_api_roundtrip_conflicts_and_corrupt_repair(self):
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        headers={'Host':'127.0.0.1:8765','Origin':'http://127.0.0.1:8765','X-ECRA-Session':'private-test-session'}
        with TestClient(create_app(self.root,token='private-test-session')) as client:
            first=client.get('/api/storage/policy',headers=headers).json();self.assertEqual(first['mode'],'auto')
            saved=client.post('/api/storage/policy',headers=headers,json=dict(mode='off',revision=first['revision']))
            self.assertEqual(saved.status_code,200);self.assertTrue(saved.json()['saved'])
            self.assertEqual(client.get('/api/storage/policy',headers=headers).json()['mode'],'off')
            self.assertEqual(client.post('/api/storage/policy',headers=headers,json=dict(mode='auto',revision=first['revision'])).status_code,409)
            self.assertEqual(client.post('/api/storage/policy',headers=headers,json=dict(mode=['auto'],revision=first['revision'])).status_code,400)
            file=self.root/'settings/storage-policy.json';file.write_bytes(b'broken preserved settings')
            invalid=client.get('/api/storage/policy',headers=headers).json();self.assertFalse(invalid['valid'])
            self.assertEqual(client.post('/api/storage/policy',headers=headers,json=dict(mode='auto',revision=invalid['revision'])).status_code,400)
            repaired=client.post('/api/storage/policy',headers=headers,json=dict(mode='auto',revision=invalid['revision'],repair=True));self.assertTrue(repaired.json()['valid'])
            self.assertIn('allocated_bytes',client.get('/api/storage',headers=headers).json())


@unittest.skipUnless(os.name=='nt','Actual Windows file compression required')
class ActualFileCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA 实际空间 ');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'data'
        self.out=self.root/'scans/scan';self.out.mkdir(parents=True);self.cache=self.root/'projects/p/cache/formal'
        self.storage=ScanStorage(self.root,self.out,self.cache,policy.snapshot(self.root))
        from ecra.windows_storage import WindowsFiles
        self.files=WindowsFiles()
        if not self.files.compression_supported(self.out):self.skipTest('Actual NTFS <=4KiB compression volume unavailable')

    def raw(self):
        p=self.out/'workers/TU-1.response.json';p.parent.mkdir(exist_ok=True);p.write_bytes(b'{"complete":"' + b'ordered duplicate evidence '*30000+b'"}')
        return p

    def test_real_compression_preserves_every_byte_identity_and_allocation(self):
        source=self.raw();before=source.read_bytes();row=self.storage.compress(source,'worker')
        self.assertEqual(row['status'],'COMPRESSED');self.assertTrue(row['byte_verified']);self.assertEqual(source.read_bytes(),before)
        self.assertEqual(row['before']['identity'],row['after']['identity']);self.assertLess(row['after']['allocated_bytes'],row['before']['allocated_bytes'])
        self.assertEqual(row['after_sha256'],hashlib.sha256(before).hexdigest());self.assertEqual(len(self.storage.receipt.read_text().splitlines()),1)

    def test_off_policy_does_not_change_existing_file_bytes_or_attributes(self):
        source=self.raw();before=self.files.allocation(source);raw=source.read_bytes();saved=policy.save(self.root,mode='off',revision='missing')
        storage=ScanStorage(self.root,self.out,self.cache,policy.snapshot(self.root));row=storage.compress(source,'worker')
        self.assertEqual(row['status'],'SKIPPED_POLICY_OFF');self.assertEqual(self.files.allocation(source),before);self.assertEqual(source.read_bytes(),raw)

    def test_declared_unsupported_capability_skips_without_touching_bytes(self):
        source=self.raw();before=self.files.allocation(source);raw=source.read_bytes()
        with patch('ecra.windows_storage.WindowsFiles.compression_supported',return_value=False):
            row=self.storage.compress(source,'worker')
        self.assertEqual(row['status'],'SKIPPED_UNSUPPORTED_FILESYSTEM');self.assertFalse(row['byte_verified'])
        self.assertEqual(self.files.allocation(source),before);self.assertEqual(source.read_bytes(),raw)

    def test_multiple_links_and_nonowned_paths_cannot_change_other_data(self):
        source=self.raw();other=self.root/'preserved.bin';os.link(source,other);before=self.files.allocation(other)
        self.assertEqual(self.storage.compress(source,'worker')['status'],'SKIPPED_MULTIPLE_LINKS');self.assertEqual(self.files.allocation(other),before)
        for path,kind in [(self.out/'scan.db','authority'),(self.out/'reviews.db','worker'),(other,'cache'),(self.out/'evidence/object','authority')]:
            with self.subTest(path=path),self.assertRaises(ValueError):self.storage.compress(path,kind)

    def test_actual_open_file_is_not_changed_and_failure_is_recorded(self):
        source=self.raw();before=source.read_bytes()
        with source.open('rb'):
            with self.assertRaises(OSError):self.storage.compress(source,'worker')
        self.assertEqual(source.read_bytes(),before);self.assertEqual(json.loads(self.storage.receipt.read_text().splitlines()[-1])['status'],'FAILED')

    def test_real_leaf_and_parent_symlinks_are_rejected(self):
        source=self.raw();link=self.out/'workers/TU-link.response.json';os.symlink(source,link)
        with self.assertRaises(ValueError):self.storage.compress(link,'worker')
        self.assertFalse(self.files.allocation(source)['attributes']&0x800)
        external=self.root/'preserved';external.mkdir();payload=external/'TU-1.response.json';payload.write_bytes(b'outside bytes')
        parent=self.out/'workers/alias';os.symlink(external,parent,target_is_directory=True)
        with self.assertRaises(ValueError):self.storage.compress(parent/payload.name,'worker')
        self.assertEqual(payload.read_bytes(),b'outside bytes');self.assertFalse(self.files.allocation(payload)['attributes']&0x800)

    def test_private_authority_all_typed_relations_survive_and_failures_are_unpublished(self):
        facts=dict(variables=[dict(symbol_id='v',name='v',static_classification='UNKNOWN')],
                   future=[dict(order=[2,1,2],typed=[None,False,0,0.0,-0.0,2**80,'😀','same','same']) for _ in range(300)])
        target=self.out/'scan.db';calls=[]
        def compact(path):
            calls.append(path);self.storage.compress(path,'authority')
        publish_scan(target,facts,dict(findings=[]),scan_id='s',project_id='p',compact=compact)
        provider=EvidenceProvider(target);provider.validate(deep=True);self.assertEqual(provider.load('facts'),facts)
        self.assertEqual(len(calls),1);self.assertFalse(calls[0].exists());old=target.read_bytes()
        with self.assertRaises(FileExistsError):publish_scan(target,{}, {},scan_id='s',project_id='p',compact=compact)
        self.assertEqual(target.read_bytes(),old)
        failed=self.root/'scans/failed';failed.mkdir();storage=ScanStorage(self.root,failed,self.cache,policy.snapshot(self.root))
        def fail(path):storage.compress(path,'authority');raise OSError('Actual callback failure after complete byte verification')
        with self.assertRaises(OSError):publish_scan(failed/'scan.db',facts,{},scan_id='s',project_id='p',compact=fail)
        self.assertFalse((failed/'scan.db').exists());kept=list(failed.glob('*.compaction-failed'));self.assertEqual(len(kept),1)
        EvidenceProvider(kept[0]).validate(deep=True);self.assertEqual(target.read_bytes(),old)

    def test_metadata_sampling_counts_all_paths_and_deduplicates_actual_hardlinks(self):
        source=self.raw();self.storage.compress(source,'worker');cache=self.cache/'tu-v1';cache.mkdir(parents=True)
        other=cache/('a'*64+'.facts');os.link(source,other)
        measured=measure(self.root);physical=self.files.allocation(source)['allocated_bytes']
        self.assertEqual(measured['bytes']['cache'],source.stat().st_size)
        self.assertEqual(measured['allocated_bytes']['cache'],0);self.assertGreaterEqual(measured['allocated_bytes']['scans'],physical)
        self.assertEqual(measured['allocation_status'],'MEASURED');self.assertEqual(list((self.root/'work/storage-sampling').iterdir()),[])

    def test_unreadable_allocation_is_unknown_and_never_a_false_zero(self):
        source=self.raw();real=self.files.allocation
        def inspect(instance,path):
            if Path(path).resolve()==source.resolve():raise PermissionError('Actual sampling boundary injected')
            return real(path)
        with patch('ecra.windows_storage.WindowsFiles.allocation',inspect):value=measure(self.root)
        self.assertIsNone(value['allocated_bytes']['scans']);self.assertTrue(value['sampling_partial']);self.assertEqual(value['unmeasured_files']['scans'],1)
        self.assertGreaterEqual(value['bytes']['scans'],source.stat().st_size)


if __name__=='__main__':unittest.main()
