"""Complete package codec equivalence and unchanged import/resource boundaries."""
import errno
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report,import_report,sha256,MAX_PACKAGE_RATIO
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.studio.server import create_app


class ArchiveCompressionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='ecra complete codec ');self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name).resolve();self.data=self.base/'data';self.scan=self.data/'scans'/'codec'
        self.scan.mkdir(parents=True)
        publish_scan(self.scan/'scan.db',dict(variables=[dict(symbol_id='s',name='value',static_classification='UNKNOWN')],
            future=[1,True,-0.0,2**90,['duplicate','duplicate']]),dict(findings=[]),scan_id='codec',project_id='p')
        self.provider=EvidenceProvider(self.scan/'scan.db');self.binding=self.provider.metadata()
        self.store=ReviewStore(self.scan/'reviews.db',self.binding)
        self.event=self.store.append('s',self.provider.fingerprint('s'),decision='NEED_MORE_EVIDENCE',reviewer='压缩验收声明',comment='完整事件保持')

    def test_default_compact_and_fast_have_identical_complete_payloads_and_events(self):
        evidence=self.scan/'evidence';evidence.mkdir();raw=b'archived source bytes\n'
        (evidence/hashlib.sha256(raw).hexdigest()).write_bytes(raw)
        before={name:sha256(self.scan/name) for name in ['scan.db','reviews.db']};payloads=[]
        for codec,expected in [('compact',zipfile.ZIP_BZIP2),('deflate',zipfile.ZIP_DEFLATED)]:
            package=self.base/(codec+'.ecra-report')
            export_report(self.scan,package,**({} if codec=='compact' else dict(compression=codec)))
            with zipfile.ZipFile(package) as zipped:
                self.assertEqual(zipped.getinfo('scan.db').compress_type,expected)
                self.assertTrue(all(i.compress_type==zipfile.ZIP_DEFLATED for i in zipped.infolist() if i.filename!='scan.db'))
                payloads.append({i.filename:zipped.read(i) for i in zipped.infolist()})
            target=self.base/('import-'+codec);import_report(package,target)
            restored=target/'scans'/'codec';self.assertEqual(EvidenceProvider(restored/'scan.db').metadata(),self.binding)
            self.assertEqual(ReviewStore(restored/'reviews.db',self.binding).history(),[self.event])
        self.assertEqual(payloads[0],payloads[1])
        self.assertEqual({name:sha256(self.scan/name) for name in before},before)

    def test_extremely_compressible_database_falls_back_without_raising_import_limit(self):
        # Explicit scalar-capacity fixture, not a native firmware project.
        source=self.base/'high-ratio';source.mkdir()
        publish_scan(source/'scan.db',dict(variables=[],long_text='x'*(64*1024**2)),dict(findings=[]),scan_id='ratio',project_id='p')
        provider=EvidenceProvider(source/'scan.db');ReviewStore(source/'reviews.db',provider.metadata())
        probe=self.base/'ratio-probe.zip'
        with zipfile.ZipFile(probe,'w',compression=zipfile.ZIP_BZIP2,compresslevel=9) as zipped:zipped.write(source/'scan.db','scan.db')
        with zipfile.ZipFile(probe) as zipped:
            info=zipped.getinfo('scan.db');self.assertGreater(info.file_size,max(1,info.compress_size)*MAX_PACKAGE_RATIO)
        package=self.base/'ratio.ecra-report';export_report(source,package,compression='compact')
        with zipfile.ZipFile(package) as zipped:self.assertEqual(zipped.getinfo('scan.db').compress_type,zipfile.ZIP_DEFLATED)
        self.assertEqual(MAX_PACKAGE_RATIO,2000)
        target=self.base/'ratio-import';import_report(package,target)
        self.assertEqual(EvidenceProvider(target/'scans/ratio/scan.db').metadata(),provider.metadata())

    def test_importing_other_codec_of_same_complete_package_is_idempotent(self):
        target=self.base/'same-target'
        for index,codec in enumerate(['compact','deflate']):
            package=self.base/('same-'+codec+'.ecra-report');export_report(self.scan,package,compression=codec)
            result=import_report(package,target)
            self.assertEqual(bool(result.get('repeated')),bool(index))
            restored=target/'scans/codec'
            self.assertEqual(EvidenceProvider(restored/'scan.db').metadata(),self.binding)
            self.assertEqual(ReviewStore(restored/'reviews.db',self.binding).history(),[self.event])

    def test_unknown_codec_is_rejected_without_creating_export_destination(self):
        for codec in ['lzma',None,True,[],{}]:
            with self.subTest(codec=codec),self.assertRaises(ValueError):
                export_report(self.scan,self.base/'invalid-parent/out.ecra-report',compression=codec)
        self.assertFalse((self.base/'invalid-parent').exists())

    def test_encoder_disk_failure_keeps_source_and_previous_complete_archive(self):
        old=self.base/'old.ecra-report';export_report(self.scan,old);old_sha=sha256(old)
        source={name:sha256(self.scan/name) for name in ['scan.db','reviews.db']};actual_write=zipfile.ZipFile.write
        def failed(zipped,filename,arcname=None,*args,**kwargs):
            if arcname=='scan.db':raise OSError(errno.ENOSPC,'injected encoder disk full')
            return actual_write(zipped,filename,arcname,*args,**kwargs)
        new=self.base/'failed.ecra-report'
        with patch.object(zipfile.ZipFile,'write',failed),self.assertRaises(OSError):export_report(self.scan,new)
        self.assertFalse(new.exists());self.assertEqual(sha256(old),old_sha)
        self.assertEqual(source,{name:sha256(self.scan/name) for name in source})

    def test_api_selects_real_member_codec_and_delta_stays_independent(self):
        client=TestClient(create_app(self.data,token='codec',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345',
                          headers={'X-ECRA-Session':'codec','Origin':'http://127.0.0.1:12345'})
        with client:
            for codec,expected in [('compact',zipfile.ZIP_BZIP2),('deflate',zipfile.ZIP_DEFLATED)]:
                response=client.post('/api/scans/codec/export',json=dict(kind='full',compression=codec));self.assertEqual(response.status_code,200,response.text)
                value=response.json();self.assertEqual(value['compression'],codec);self.assertFalse(value['compression_fallback'])
                downloaded=client.get(value['download']);self.assertEqual(downloaded.status_code,200)
                with zipfile.ZipFile(io.BytesIO(downloaded.content)) as zipped:self.assertEqual(zipped.getinfo('scan.db').compress_type,expected)
            delta=client.post('/api/scans/codec/export',json=dict(kind='delta',compression='unused'))
            self.assertEqual(delta.status_code,200,delta.text);self.assertNotIn('compression',delta.json())
            self.assertTrue(delta.json()['filename'].endswith('.ecra-review-delta'))

    def test_api_invalid_mode_or_kind_preserves_archive_and_events(self):
        client=TestClient(create_app(self.data,token='codec',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345',
                          headers={'X-ECRA-Session':'codec','Origin':'http://127.0.0.1:12345'})
        before={name:sha256(self.scan/name) for name in ['scan.db','reviews.db']}
        with client:
            for payload in [dict(kind='other'),dict(kind=[]),dict(kind=None),dict(kind='full',compression='lzma'),dict(kind='full',compression=[])]:
                response=client.post('/api/scans/codec/export',json=payload);self.assertEqual(response.status_code,400,response.text)
        self.assertFalse((self.data/'exports').exists());self.assertEqual(before,{name:sha256(self.scan/name) for name in before})
