"""Derived-publication boundaries, using actual Clang facts and ELF32 bytes."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from ecra import multicore
from ecra.common import write_json
from ecra.config import load_config
from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report,import_report,sha256
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.workspace import WorkspaceResolver
from tests import test_ecra
from tests.async_jobs import cleanup_temporary


def linked_elf():
    names=b'\0mailbox\0private_value\0';header=bytearray(52)
    header[:7]=b'\x7fELF\x01\x01\x01';struct.pack_into('<H',header,18,40)
    struct.pack_into('<I',header,32,52);struct.pack_into('<HH',header,46,40,3)
    offset=52+120;symbols=offset+len(names)
    sections=bytes(40)+struct.pack('<10I',0,3,0,0,offset,len(names),0,0,1,0)+struct.pack('<10I',0,2,0,0,symbols,32,1,0,4,16)
    return bytes(header)+sections+names+struct.pack('<IIIBBH',1,0x38000000,4,0x11,0,1)+struct.pack('<IIIBBH',9,0x24000000,4,0x11,0,1)


class MulticorePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=test_ecra.ProjectTest('runTest');fixture.setUp();cls.addClassCleanup(fixture.doCleanups)
        cfg=fixture.project({'a.c':'int mailbox,private_value; void main(void){mailbox++;private_value=1;}'},
                            contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        cls.facts,_=fixture.extract(cfg)
        # extract() asserts the actual single TU is PARSED; the CLI normally
        # attaches its unit inventory after merge. Include that same inventory.
        cls.facts['translation_units']=[dict(file='a.c',source_file='a.c',parse_status='PARSED')]

    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='ecra multicore publication ');self.addCleanup(cleanup_temporary,self,tmp)
        self.base=Path(tmp.name).resolve();self.root=self.base/'firmware';self.root.mkdir();self.data=self.base/'data'
        (self.root/'a.c').write_text('int mailbox,private_value; void main(void){mailbox++;private_value=1;}','utf-8')
        self.inputs=[];self.folders=[]
        for index,(variant,core) in enumerate([('CM7','Cortex-M7'),('CM4','Cortex-M4')]):
            elf=self.root/(variant+'.elf');elf.write_bytes(linked_elf())
            config=self.base/(variant+'.yaml')
            write_json(config,dict(version=1,project=dict(core=core,firmware_elf=elf.name),
                analysis=dict(output=dict(location='custom',custom_dir=str(self.base/('input-'+variant)))),
                review=dict(enabled=False)))
            cfg,_=load_config(self.root,config);ws=WorkspaceResolver.resolve(self.root,cfg['analysis']);ws.initialize()
            folder=Path(ws.results_root);self.folders.append(folder)
            if index==0:
                publish_scan(folder/'scan.db',copy.deepcopy(self.facts),dict(findings=[]),scan_id='input-CM7',project_id=ws.project_id)
            else:write_json(folder/'facts.json',copy.deepcopy(self.facts))
            self.inputs.append((variant,config))
        self.regions=[(0x38000000,0x10000)]

    def snapshot_inputs(self):
        return {str(p):sha256(p) for root in [self.root,*self.folders] for p in root.rglob('*') if p.is_file()}

    def run_combine(self,name='combined'):
        out=self.data/'scans'/name
        return out,multicore.combine(self.root,self.inputs,self.regions,out)

    def test_mixed_canonical_legacy_complete_result_and_review_package_roundtrip(self):
        before=self.snapshot_inputs();out,(facts,report)=self.run_combine()
        self.assertEqual(self.snapshot_inputs(),before)
        self.assertFalse(any((out/name).exists() for name in ['facts.json','facts.db','index.html','reports','inventory','summary.md']))
        provider=EvidenceProvider(out/'scan.db');binding=provider.validate(deep=True)
        self.assertEqual(provider.load('facts'),facts)
        self.assertEqual(report['run_status'],'INCOMPLETE')
        shared=next(v for v in facts['variables'] if v['name']=='mailbox')
        self.assertEqual(shared['symbol_id'],'shared:0x38000000:4')
        self.assertEqual(len(shared['core_instances']),2)
        self.assertEqual(len([v for v in facts['variables'] if v['name']=='private_value']),2)
        self.assertTrue(any('GS-CROSS-CORE' in f['rules'] for f in report['findings']))
        manifest=json.loads((out/'manifest.json').read_text('utf-8'))
        self.assertFalse(manifest['source_reverification']);self.assertFalse((out/'scan_state.json').exists())
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        with TestClient(create_app(self.data,token='multicore-test',authority='testserver'),
                        headers={'X-ECRA-Session':'multicore-test'}) as client:
            summary=client.get('/api/scans/combined/summary').json()
            self.assertIn('链接地址派生合并',summary['evidence_notice'])
            self.assertIsNone(summary['legacy_warning']);self.assertTrue(summary['can_confirm']);self.assertFalse(summary['can_review'])
        store=ReviewStore(out/'reviews.db',binding)
        event=store.append(shared['symbol_id'],provider.fingerprint(shared['symbol_id']),decision='NEED_MORE_EVIDENCE',reviewer='多核发布测试',comment='测试暂无法确认')
        archive=self.base/'combined.ecra-report';export_report(out,archive)
        second=self.base/'second';result=import_report(archive,second)
        restored=second/'scans'/result['scan_id'];self.assertEqual(EvidenceProvider(restored/'scan.db').metadata(),binding)
        with closing(sqlite3.connect(restored/'reviews.db')) as conn:
            self.assertEqual(conn.execute('SELECT event_id FROM events').fetchall(),[(event['event_id'],)])
        self.assertEqual(self.snapshot_inputs(),before)

    def test_default_new_id_uses_same_resolver_data_root_without_core_latest_pointer(self):
        receipt={};multicore.combine(self.root,self.inputs,self.regions,data_root=self.data,publication=receipt)
        out=Path(receipt['scan_path']);self.assertEqual(out.parent,self.data/'scans')
        self.assertTrue((out/'manifest.json').is_file());self.assertEqual(receipt['scan_id'],out.name)
        for folder in self.folders:self.assertFalse((folder.parent/'latest-scan.json').exists())

    def test_firmware_relative_existing_and_incompatible_output_rejected(self):
        before=self.snapshot_inputs()
        for out in [Path('results/multicore'),self.root/'scans'/'bad',self.base/'bad-structure']:
            with self.subTest(out=out),self.assertRaises(ValueError):multicore.combine(self.root,self.inputs,self.regions,out)
        out,_=self.run_combine();old=sha256(out/'scan.db')
        with self.assertRaises(FileExistsError):multicore.combine(self.root,self.inputs,self.regions,out)
        self.assertEqual(sha256(out/'scan.db'),old);self.assertEqual(self.snapshot_inputs(),before)

    def test_input_change_after_assembly_keeps_previous_valid_scan_and_rejects_new_result(self):
        out,_=self.run_combine();old=sha256(out/'scan.db');assemble=multicore._assemble
        def changed(*args,**kwargs):
            value=assemble(*args,**kwargs);(self.root/'CM4.elf').write_bytes(linked_elf()+b'changed');return value
        bad=self.data/'scans'/'changed'
        with patch.object(multicore,'_assemble',side_effect=changed),self.assertRaisesRegex(ValueError,'输入在合并期间改变'):
            multicore.combine(self.root,self.inputs,self.regions,bad)
        self.assertFalse(bad.exists());self.assertEqual(sha256(out/'scan.db'),old)

    def test_failed_publication_is_not_visible_and_does_not_overwrite_previous(self):
        out,_=self.run_combine();old={p.name:sha256(p) for p in out.iterdir() if p.is_file()};bad=self.data/'scans'/'failed'
        with patch('ecra.scan_store.publish_scan',side_effect=OSError('injected disk failure')),self.assertRaises(OSError):
            multicore.combine(self.root,self.inputs,self.regions,bad)
        self.assertTrue((bad/'storage.json').exists());self.assertFalse((bad/'manifest.json').exists())
        self.assertFalse(json.loads((bad/'result_validity.json').read_text('utf-8'))['analysis_valid'])
        self.assertEqual({p.name:sha256(p) for p in out.iterdir() if p.is_file()},old)

    def test_duplicate_variants_invalid_region_and_mismatched_data_root_never_publish(self):
        for inputs,regions in [(self.inputs*2,self.regions),(self.inputs,[(0,0)]),(self.inputs,[(-1,4)])]:
            with self.subTest(inputs=inputs,regions=regions),self.assertRaises(ValueError):
                multicore.combine(self.root,inputs,regions,data_root=self.data)
        with self.assertRaisesRegex(ValueError,'同一个独立数据根'):
            multicore.combine(self.root,self.inputs,self.regions,self.data/'scans'/'wrong',data_root=self.base/'other')
        self.assertFalse(self.data.exists())

    def test_input_change_during_publication_keeps_failed_authority_hidden(self):
        from ecra.scan_store import publish_scan as actual_publish
        def changed(*args,**kwargs):
            value=actual_publish(*args,**kwargs)
            (self.root/'CM4.elf').write_bytes(linked_elf()+b'changed-after-graph')
            return value
        bad=self.data/'scans'/'changed-after-graph'
        with patch('ecra.scan_store.publish_scan',side_effect=changed),self.assertRaisesRegex(ValueError,'输入在发布期间改变'):
            multicore.combine(self.root,self.inputs,self.regions,bad)
        self.assertTrue((bad/'scan.db').exists());self.assertFalse((bad/'manifest.json').exists())
        from ecra.studio.history import history
        self.assertEqual(history(self.data)['items'],[])

    def test_corrupted_canonical_component_cannot_be_merged_into_valid_result(self):
        provider=EvidenceProvider(self.folders[0]/'scan.db');node=provider.resolve('facts',['variables',0,'name'])
        with closing(sqlite3.connect(provider.path)) as conn,conn:
            conn.execute("UPDATE nodes SET value=x'74616d7065726564' WHERE id=?",(node,))
        bad=self.data/'scans'/'bad-component'
        with self.assertRaises(ValueError):multicore.combine(self.root,self.inputs,self.regions,bad)
        self.assertFalse(bad.exists())

    def test_partial_failed_unit_coverage_is_retained_in_derived_publication(self):
        # Explicit unit metadata fault fixture, not another native scan.
        facts=copy.deepcopy(self.facts)
        facts['translation_units']=[dict(file=name,source_file=name,parse_status=status) for name,status in
                                    [('a.c','PARSED'),('partial.c','PARTIAL'),('missing.c','FAILED')]]
        write_json(self.folders[1]/'facts.json',facts)
        _,report=multicore.combine(self.root,self.inputs[1:],self.regions,self.data/'scans'/'coverage')
        coverage=report['coverage']
        self.assertEqual([coverage['translation_units_'+key] for key in ['total','parsed','partial','failed']],[3,1,1,1])
        self.assertEqual(report['run_status'],'INCOMPLETE')
