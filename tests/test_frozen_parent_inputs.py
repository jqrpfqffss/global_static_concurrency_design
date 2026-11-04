"""Actual parent source reads and glob selection over an independent capsule."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import unittest

from ecra import working_snapshot as working
from ecra import working_compiler_view as view
from ecra.input_snapshot import InputSnapshot,SOURCE_READS,read_analysis_bytes,read_analysis_text,select_analysis_files
from tests import test_working_snapshot as fixture


class FrozenParentInputTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.WorkingSnapshotTests(methodName='runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.repo;self.base=self.fixture.base;self.cfg=dict(analysis=self.fixture.analysis)
        (self.root/'empty.map').mkdir();(self.root/'firmware.map').write_bytes(b'original\r\nmap bytes\r\n')
        self.build=self.base/'external build';self.build.mkdir();(self.build/'empty.map').mkdir()
        (self.build/'linked.map').write_bytes(b'linker evidence\r\n')
        self.config=self.base/'data/profiles/fixed.json';self.config.parent.mkdir(parents=True)
        self.config.write_bytes(b'{"original":true}\r\n')
        self.database=self.base/'metadata/compile_commands.json';self.database.parent.mkdir()
        self.database.write_bytes(b'[]\r\n')
        self.response=self.base/'flags.rsp';self.response.write_bytes(b'-mcpu=cortex-m0\r\n')

    def capture(self):
        result=working.capture(self.root,self.cfg)
        descriptor=view.create(result,self.root,self.cfg,external_directories=[self.build],
                               external_files=[self.config,self.database,self.response])
        return result,descriptor

    def test_actual_parent_readers_and_glob_keep_full_captured_bytes_after_original_files_change(self):
        result,descriptor=self.capture()
        explicit=[self.root/'main.c',self.root/'firmware.map',self.config,self.database,self.response]
        expected={path:path.read_bytes() for path in explicit}
        with view.ParentFiles(descriptor,self.root,self.cfg) as files:
            snapshot=InputSnapshot(self.root,self.base/'diagnostics',explicit,file_view=files)
            snapshot.register_selection(self.root,'*.map');snapshot.register_selection(self.build,'*.map')
            (self.root/'main.c').write_text('int changed_original;\n','utf-8')
            self.config.write_bytes(b'changed original config');self.response.write_bytes(b'changed original flags')
            (self.root/'new.map').write_bytes(b'new original map')
            token=SOURCE_READS.set(snapshot)
            try:
                for path,raw in expected.items():self.assertEqual(read_analysis_bytes(path),raw)
                self.assertEqual(read_analysis_text(self.root/'firmware.map'),'original\nmap bytes\n')
                self.assertEqual({path.name for path in select_analysis_files(self.root,'*.map')},{'empty.map','firmware.map'})
                self.assertEqual({path.name for path in select_analysis_files(self.build,'*.map')},{'empty.map','linked.map'})
            finally:SOURCE_READS.reset(token)
            snapshot.seal();snapshot.finalize_parent_inputs()
            closure=json.loads((self.base/'input_closure.json').read_text('utf-8'))
            self.assertEqual(closure['frozen_view']['sha256'],descriptor['sha256'])
            self.assertTrue(closure['frozen_view']['original_final_reverification_required'])
            self.assertTrue(snapshot.parent_reads)
            self.assertTrue(view.validate(descriptor,self.root,self.cfg,reverify_original=False)['valid'])
            with self.assertRaises(ValueError):view.validate(descriptor,self.root,self.cfg)

    def test_empty_directory_identity_is_preserved_and_changes_never_become_unique_map_selection(self):
        result,descriptor=self.capture();tree=Path(result['source_root'])
        self.assertTrue((tree/'empty.map').is_dir())
        self.assertTrue(working.validate(result,self.root,self.cfg)['directory_proof'])
        with view.ParentFiles(descriptor,self.root,self.cfg) as files:
            self.assertEqual(len(files.select_files(self.root,'*.map')),2)
            (tree/'empty.map').rmdir()
            with self.assertRaisesRegex(ValueError,'目录'):files.select_files(self.root,'*.map')

    def test_source_and_external_empty_directory_additions_are_verified_separately_from_files(self):
        result,descriptor=self.capture()
        (self.root/'new empty').mkdir()
        with self.assertRaisesRegex(ValueError,'未记录的目录'):working.validate(result,self.root,self.cfg)
        self.assertTrue(working.validate(result,self.root,self.cfg,reverify_original=False)['valid'])
        (self.root/'new empty').rmdir();(self.build/'late empty').mkdir()
        with self.assertRaisesRegex(ValueError,'未记录的目录'):view.validate(descriptor,self.root,self.cfg)
        self.assertTrue(view.validate(descriptor,self.root,self.cfg,reverify_original=False)['valid'])

    def test_changed_copy_and_capture_manifest_unknown_inputs_and_closed_view_are_rejected(self):
        result,descriptor=self.capture();tree=Path(result['source_root'])
        with view.ParentFiles(descriptor,self.root,self.cfg) as files:
            unknown=self.base/'not fixed.txt';unknown.write_bytes(b'live bytes')
            with self.assertRaisesRegex(ValueError,'不回退'):files.read_bytes(unknown)
            (tree/'main.c').write_bytes(b'corrupted copied bytes')
            with self.assertRaisesRegex(ValueError,'实际读取字节已变化'):files.read_bytes(self.root/'main.c')
            with self.assertRaisesRegex(ValueError,'副本已变化'):files.file_record(self.root/'main.c')
        with self.assertRaisesRegex(ValueError,'已经关闭'):files.read_bytes(self.root/'main.c')
        # A separate fresh capsule, because the previous copy is intentionally damaged.
        fresh=working.capture(self.root,self.cfg)
        second=view.create(fresh,self.root,self.cfg,external_directories=[self.build])
        with closing(sqlite3.connect(fresh['manifest'])) as conn:
            conn.execute("DELETE FROM directories WHERE relative='empty.map'");conn.commit()
        with self.assertRaisesRegex(ValueError,'目录清单已变化'):view.ParentFiles(second,self.root,self.cfg)

    def test_legacy_file_only_capture_remains_valid_but_cannot_claim_directory_complete_parent_reads(self):
        result=working.capture(self.root,self.cfg)
        with closing(sqlite3.connect(result['manifest'])) as conn:
            conn.execute('DROP TABLE directories');conn.execute("DELETE FROM meta WHERE key='capture_schema'");conn.commit()
        result.pop('capture_schema')
        self.assertFalse(working.validate(result,self.root,self.cfg)['directory_proof'])
        descriptor=view.create(result,self.root,self.cfg,external_directories=[self.build])
        with self.assertRaisesRegex(ValueError,'旧捕获缺少目录集合证据'):view.ParentFiles(descriptor,self.root,self.cfg)

    def test_formal_resume_does_not_ignore_new_frozen_parent_identity(self):
        from ecra.workflow import verify_saved_input_closure,file_digest
        out=self.base/'saved';out.mkdir();capsule=out/'input_closure.json'
        capsule.write_text(json.dumps(dict(frozen_view=dict(file='fixed-view',sha256='0'*64))),'utf-8')
        state=dict(input_closure_sha256=file_digest(capsule))
        with self.assertRaisesRegex(ValueError,'正式恢复链路尚未完成验收'):
            verify_saved_input_closure(self.root,out,self.cfg,state,{},self.config)

    def test_unused_single_directory_candidate_does_not_invalidate_other_source_inputs(self):
        (self.root/'only.map').mkdir();result,descriptor=self.capture()
        ordinary=InputSnapshot(self.root,self.base/'ordinary-diagnostics',[self.root/'main.c'])
        ordinary.register_selection(self.root,'only.map');ordinary.seal()
        with view.ParentFiles(descriptor,self.root,self.cfg) as files:
            snapshot=InputSnapshot(self.root,self.base/'single-directory-diagnostics',[self.root/'main.c'],file_view=files)
            snapshot.register_selection(self.root,'only.map');snapshot.seal()
            self.assertFalse(snapshot.changes)
            self.assertEqual(snapshot.select_files(self.root,'only.map'),ordinary.select_files(self.root,'only.map'))
            token=SOURCE_READS.set(snapshot)
            try:
                with self.assertRaisesRegex(ValueError,'无法验证真实输入'):read_analysis_bytes(self.root/'only.map')
            finally:SOURCE_READS.reset(token)
            self.assertEqual(snapshot.parent_reads['only.map']['status'],'UNREADABLE')

    def test_real_constructor_assembly_and_map_proof_uses_captured_parent_bytes(self):
        from ecra.initialization import _startup_constructor_proof
        source=self.root/'startup.S';source.write_text('Reset_Handler:\n bl __libc_init_array\n bl main\n','utf-8')
        maps=self.root/'build/ecra';maps.mkdir(parents=True)
        link=maps/'firmware.map';link.write_text('.preinit_array 0x08001000 0x0\n.init_array 0x08001000 0x4\n .init_array 0x08001000 0x4 C:/arm/lib/crtbegin.o\n','utf-8')
        cfg=dict(self.cfg,project=dict(root=str(self.root)))
        facts=dict(vector_entries=[dict(function_id='reset',slot=1,file='startup.S')],
                   functions=[dict(function_id='reset',name='Reset_Handler'),dict(function_id='main',name='main')])
        original=_startup_constructor_proof(facts,cfg,'reset','main');self.assertIsNotNone(original)
        result,descriptor=self.capture()
        with view.ParentFiles(descriptor,self.root,cfg) as files:
            snapshot=InputSnapshot(self.root,self.base/'proof-diagnostics',[source,link],file_view=files)
            snapshot.register_selection(maps,'*.map')
            source.write_text('Reset_Handler:\n bl unknown_new_initialization\n bl main\n','utf-8')
            link.write_text('changed live linker map','utf-8')
            self.assertIsNone(_startup_constructor_proof(facts,cfg,'reset','main'))
            token=SOURCE_READS.set(snapshot)
            try:self.assertEqual(_startup_constructor_proof(facts,cfg,'reset','main'),original)
            finally:SOURCE_READS.reset(token)
            self.assertIn('startup.S',snapshot.parent_reads)
            self.assertIn('build/ecra/firmware.map',snapshot.parent_reads)
            snapshot.verify_disk();snapshot.assert_valid()

    @unittest.skipUnless(os.name=='nt','Windows case-insensitive path identity')
    def test_windows_path_spelling_keeps_parent_input_and_real_worker_bytes(self):
        result,descriptor=self.capture();source=self.root/'main.c'
        with view.ParentFiles(descriptor,self.root,self.cfg) as files:
            self.assertEqual(files.read_bytes(Path(str(source).upper())),source.read_bytes())
        from tests import test_working_compiler_view as worker_fixture
        case=worker_fixture.WorkingCompilerViewTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        _,worker_descriptor=case.capture();case.unit['source']=case.unit['source'].upper()
        original=case.worker();frozen=case.worker(worker_descriptor)
        self.assertEqual(original['parse_status'],'PARSED',original.get('diagnostics'))
        self.assertEqual(frozen,original)
