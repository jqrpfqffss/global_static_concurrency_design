"""Non-Clang reads must prove the exact bytes consumed, even after restore."""
import contextlib
import hashlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from ecra import cli
from ecra.common import read_json, write_json
from ecra.input_snapshot import InputSnapshot, SOURCE_READS, select_analysis_files, read_analysis_text


class ParentSourceReadTests(unittest.TestCase):
    from tests.test_ecra import ProjectTest as _fixture
    setUp = _fixture.setUp
    project = _fixture.project

    def test_assembly_content_changed_and_restored_at_parent_read_fails_closed(self):
        self.project({'a.c': 'int shared;void ISR(void){shared++;}void Task(void){shared++;}',
                      'startup.S': '.section .isr_vector,"a"\ng_pfnVectors:\n.word _estack\n.word Task\n.word ISR\n'})
        entries = read_json(self.root/'compile_commands.json')
        entries.append(dict(directory=str(self.root),file='startup.S',
                            arguments=['arm-none-eabi-gcc','-mcpu=cortex-m7','-mthumb','-c','startup.S']))
        write_json(self.root/'compile_commands.json',entries)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run(self.root,no_review=True),2)
        assembly = self.root/'startup.S'
        original = assembly.read_bytes()
        consumed = original + b'/* actually consumed then restored */\n'
        changed = []
        analyze = cli.analyze

        def reading(method):
            def read(path,*args,**kwargs):
                if path.resolve()==assembly and not changed:
                    changed.append(True)
                    assembly.write_bytes(consumed)
                    try:
                        return method(path,*args,**kwargs)
                    finally:
                        assembly.write_bytes(original)
                return method(path,*args,**kwargs)
            return read

        def analyzed(*args,**kwargs):
            with patch.object(Path,'read_text',reading(Path.read_text)), \
                    patch.object(Path,'read_bytes',reading(Path.read_bytes)):
                return analyze(*args,**kwargs)

        with patch.object(cli,'analyze',side_effect=analyzed), contextlib.redirect_stdout(io.StringIO()):
            code = cli.run(self.root,no_review=True)
        self.assertTrue(changed)
        self.assertEqual(assembly.read_bytes(),original)
        self.assertEqual(code,3,'A different parent-consumed assembly version was accepted')
        out = self.root/'.ecra'
        detail = next(row for row in read_json(out/'diagnostics/source_changes.json')['changes']
                      if row['file']=='startup.S' and row.get('phase')=='PARENT_READ')
        self.assertEqual(detail['before']['sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(detail['after']['sha256'],hashlib.sha256(consumed).hexdigest())
        self.assertEqual(read_json(out/'diagnostics/exception.json')['snapshot_status'],'INVALID')
        self.assertFalse(read_json(out/'result_validity.json')['analysis_valid'])
        self.assertFalse((out/'scan_state.json').exists())

    def test_verified_reader_preserves_text_semantics_and_records_only_hashes(self):
        source = self.root/'a.c'
        source.write_bytes('/* 中文 */\r\nint shared;\r'.encode('utf-8'))
        expected = source.read_text(encoding='utf-8')
        snapshot = InputSnapshot(self.root,self.root/'.ecra/diagnostics',[source])
        snapshot.seal()
        self.assertEqual(snapshot.read_text(source,encoding='utf-8'),expected)
        self.assertEqual(snapshot.parent_reads['a.c']['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertNotIn('text',snapshot.parent_reads['a.c'])
        self.assertNotIn('content',snapshot.parent_reads['a.c'])

    def test_unreadable_or_undeclared_parent_input_is_rejected(self):
        source = self.root/'a.c'
        source.write_text('int shared;',encoding='utf-8')
        snapshot = InputSnapshot(self.root,self.root/'.ecra/diagnostics',[source])
        snapshot.seal()
        with patch.object(Path,'read_bytes',side_effect=PermissionError('controlled parent lock')):
            with self.assertRaises(ValueError):
                snapshot.read_text(source,encoding='utf-8')
        fresh = InputSnapshot(self.root,self.root/'.ecra/other-diagnostics',[source])
        fresh.seal()
        other = self.root/'unregistered.c'
        other.write_text('int another;',encoding='utf-8')
        with self.assertRaises(ValueError):
            fresh.read_text(other,encoding='utf-8')

    def test_streamed_map_bytes_changed_then_restored_are_rejected(self):
        from ecra.linker_symbols import _assignments_in_map
        folder = self.root/'build/ecra'
        folder.mkdir(parents=True)
        path = folder/'firmware.map'
        original = b'0x00000010 anchor = 0x10\r\n'
        path.write_bytes(original)
        snapshot = InputSnapshot(self.root,self.root/'.ecra/diagnostics',[])
        snapshot.register_selection(folder,'*.map')
        snapshot.seal()
        token = SOURCE_READS.set(snapshot)
        read_bytes = Path.read_bytes
        changed = []
        def consumed(file):
            if file.resolve()==path and not changed:
                changed.append(True)
                path.write_bytes(b'0x00000020 anchor = 0x20\n')
                try:
                    return read_bytes(file)
                finally:
                    path.write_bytes(original)
            return read_bytes(file)
        try:
            self.assertEqual(select_analysis_files(folder,'*.map'),[path])
            with patch.object(Path,'read_bytes',consumed), self.assertRaises(ValueError):
                _assignments_in_map(path)
        finally:
            SOURCE_READS.reset(token)
        self.assertTrue(changed)
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(snapshot.status,'INVALID')

    def test_unused_map_outputs_are_ignored_but_used_file_selection_is_verified(self):
        folder = self.root/'build/ecra'
        folder.mkdir(parents=True)
        (folder/'one.map').write_text('one',encoding='utf-8')
        unused = InputSnapshot(self.root,self.root/'.ecra/unused',[])
        unused.register_selection(folder,'*.map')
        unused.seal()
        (folder/'two.map').write_text('two',encoding='utf-8')
        unused.verify_disk()
        unused.assert_valid()
        used = InputSnapshot(self.root,self.root/'.ecra/used',[])
        used.register_selection(folder,'*.map')
        used.seal()
        self.assertEqual(len(used.select_files(folder,'*.map')),2)
        (folder/'three.map').write_text('three',encoding='utf-8')
        used.verify_disk()
        with self.assertRaises(ValueError):
            used.assert_valid()

    def test_cache_and_generated_compiler_metadata_changed_after_consumption_fail(self):
        for target in ('cache','compiler'):
            with self.subTest(target=target):
                self.project({'a.c':'int shared;void ISR(void){shared++;}'})
                cache = self.root/'CMakeCache.txt'
                cache.write_text('CMAKE_CACHE_MAJOR_VERSION:INTERNAL=3\nCMAKE_CACHE_MINOR_VERSION:INTERNAL=29\n'
                                 'CMAKE_CACHE_PATCH_VERSION:INTERNAL=6\n',encoding='utf-8')
                compiler = self.root/'CMakeFiles/3.29.6/CMakeCCompiler.cmake'
                compiler.parent.mkdir(parents=True,exist_ok=True)
                compiler.write_text('set(CMAKE_C_COMPILER_VERSION "10.3.1")\n',encoding='utf-8')
                changed = cache if target=='cache' else compiler
                prepare = cli.prepare
                def prepared(*args,**kwargs):
                    result = prepare(*args,**kwargs)
                    with changed.open('a',encoding='utf-8') as stream:
                        stream.write('# changed after read\n')
                    return result
                with patch.object(cli,'prepare',side_effect=prepared),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.run(self.root,no_review=True),3)
                changes = read_json(self.root/'.ecra/diagnostics/source_changes.json')['changes']
                self.assertTrue(any(row['file']==changed.relative_to(self.root).as_posix()
                                    and row['reason']=='CONFIGURATION_CHANGED_AFTER_READ' for row in changes))

    def test_saved_checkpoint_rejects_changed_consumed_map_selection(self):
        from ecra.workflow import status
        self.project({'a.c':'int shared;void ISR(void){shared++;}void Task(void){shared++;}'})
        folder = self.root/'build/ecra'
        folder.mkdir(parents=True)
        (folder/'one.map').write_text('map bytes consumed by analysis',encoding='utf-8')
        analyze = cli.analyze
        def analyzed(*args,**kwargs):
            candidates = select_analysis_files(folder,'*.map')
            self.assertEqual(len(candidates),1)
            read_analysis_text(candidates[0],encoding='utf-8')
            return analyze(*args,**kwargs)
        with patch.object(cli,'analyze',side_effect=analyzed),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run(self.root,no_review=True),2)
        self.assertIsNone(SOURCE_READS.get())
        capsule = read_json(self.root/'.ecra/input_closure.json')
        self.assertEqual(capsule['parent_selections'][0]['files'],['build/ecra/one.map'])
        self.assertTrue(status(self.root)['resumable'])
        (folder/'two.map').write_text('additional candidate',encoding='utf-8')
        self.assertFalse(status(self.root)['resumable'])
        changes = read_json(self.root/'.ecra/diagnostics/resume_source_changes.json')['changes']
        self.assertTrue(any(row['reason']=='PARENT_INPUT_SET_CHANGED' for row in changes))
