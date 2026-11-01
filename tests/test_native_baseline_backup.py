import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.report_package import sha256
from scripts.freeze_native_baseline import freeze


class NativeBaselineBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA baseline backup ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        (self.source/'子目录').mkdir();(self.source/'子目录/原始.bin').write_bytes(bytes(range(256))*400)
        (self.source/'empty').write_bytes(b'');os.link(self.source/'子目录/原始.bin',self.source/'alias')
        self.firmware=self.root/'firmware';self.firmware.mkdir();config=self.root/'config.json'
        config.write_text(json.dumps(dict(project=dict(root=str(self.firmware)))),encoding='utf-8')
        self.run=dict(complete=True,data_root=str(self.source),validity=dict(analysis_valid=True),config=str(config),config_sha256=sha256(config))
        self.execution=self.root/'execution.json';self.execution.write_text(json.dumps(self.run),encoding='utf-8')
        self.backup=self.root/'backup';self.work=self.root/'observer'

    def test_every_binary_and_unicode_file_is_independently_copied_verified_and_manifested(self):
        before={p.relative_to(self.source).as_posix():sha256(p) for p in self.source.rglob('*') if p.is_file()}
        result=freeze(self.execution,self.backup,self.work)
        self.assertTrue(result['passed']);self.assertEqual(result['files'],3)
        self.assertEqual(before,{p.relative_to(self.backup).as_posix():sha256(p) for p in self.backup.rglob('*') if p.is_file()})
        self.assertEqual(before,{p.relative_to(self.source).as_posix():sha256(p) for p in self.source.rglob('*') if p.is_file()})
        self.assertFalse(os.path.samefile(self.source/'alias',self.backup/'alias'))
        self.assertFalse(os.path.samefile(self.backup/'alias',self.backup/'子目录/原始.bin'))
        self.assertEqual(result['manifest_sha256'],sha256(self.work/'files.db'))

    def test_invalid_result_existing_destination_and_firmware_overlap_are_rejected_without_writes(self):
        self.run['validity']['analysis_valid']=False;self.execution.write_text(json.dumps(self.run),encoding='utf-8')
        with self.assertRaises(ValueError):freeze(self.execution,self.backup,self.work)
        self.assertFalse(self.backup.exists());self.assertFalse(self.work.exists())
        self.run['validity']['analysis_valid']=True;self.execution.write_text(json.dumps(self.run),encoding='utf-8')
        with self.assertRaises(ValueError):freeze(self.execution,self.firmware/'forbidden',self.work)
        self.assertFalse((self.firmware/'forbidden').exists());self.assertFalse(self.work.exists())
        self.backup.mkdir();(self.backup/'keep').write_bytes(b'keep')
        with self.assertRaises(FileExistsError):freeze(self.execution,self.backup,self.work)
        self.assertEqual((self.backup/'keep').read_bytes(),b'keep')

    def test_copy_failure_keeps_original_and_partial_evidence_and_never_reports_complete(self):
        before=sha256(self.source/'alias')
        with patch('scripts.freeze_native_baseline.shutil.copystat',side_effect=OSError('injected metadata write failure')):
            with self.assertRaises(OSError):freeze(self.execution,self.backup,self.work)
        result=json.loads((self.work/'acceptance.json').read_text(encoding='utf-8'))
        self.assertFalse(result['passed']);self.assertEqual(result['state'],'FAILED')
        self.assertTrue(any(p.is_file() for p in self.backup.rglob('*')))
        self.assertEqual(sha256(self.source/'alias'),before)
        with self.assertRaises(FileExistsError):freeze(self.execution,self.backup,self.work)

    def test_explicit_failed_resume_rehashes_partial_and_never_overwrites_mismatch(self):
        with patch('scripts.freeze_native_baseline.shutil.copystat',side_effect=OSError('injected after bytes')):
            with self.assertRaises(OSError):freeze(self.execution,self.backup,self.work)
        original={str(p.relative_to(self.backup)):p.read_bytes() for p in self.backup.rglob('*') if p.is_file()}
        result=freeze(self.execution,self.backup,self.root/'resumed',resume_receipt=self.work/'acceptance.json')
        self.assertTrue(result['passed']);self.assertGreater(result['reused_verified_files'],0)
        for name,content in original.items():self.assertEqual((self.backup/name).read_bytes(),content)
        other=self.root/'corrupt-backup';other.mkdir();(other/'empty').write_bytes(b'damaged')
        previous=json.loads((self.work/'acceptance.json').read_text());previous['destination']=str(other)
        receipt=self.root/'matching-failed.json';receipt.write_text(json.dumps(previous))
        with self.assertRaisesRegex(ValueError,'retained without overwrite'):
            freeze(self.execution,other,self.root/'refused',resume_receipt=receipt)
        self.assertEqual((other/'empty').read_bytes(),b'damaged')

    def test_hashing_uses_reusable_readinto_and_matches_binary_digest(self):
        from scripts.freeze_native_baseline import hash_file
        from io import BytesIO
        import hashlib
        class NoRead(BytesIO):
            def read(self,*args):raise AssertionError('oversized per-file bytes allocation')
        raw=bytes(range(256))*4097;buffer=bytearray(4096)
        for _ in range(3):
            with patch.object(Path,'open',return_value=NoRead(raw)):
                self.assertEqual(hash_file(Path('unused'),buffer),hashlib.sha256(raw).hexdigest())


if __name__=='__main__':unittest.main()
