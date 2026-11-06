"""Actual guarded CMake/ARM/Git working-byte flow; not a G2 substitute."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import read_json,write_json
from ecra.scan_store import EvidenceProvider
from ecra.report_package import sha256
from tests import test_native_diff_summary_cache as native_fixture


@unittest.skipUnless(os.name=='nt','Windows guarded builds required')
class WorkingCMakeTests(unittest.TestCase):
    def setUp(self):
        if not all(shutil.which(p) for p in ('cmake','ninja','arm-none-eabi-gcc')):self.skipTest('actual toolchain required')
        self.case=native_fixture.NativeDiffSummaryCacheTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.root=self.case.root
        (self.root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(dirty C)\n'
            'set(WIDTH 1)\nconfigure_file(generated.h.in generated.h @ONLY)\n'
            'configure_file(generated.c.in generated.c @ONLY)\n'
            'add_library(firmware STATIC main.c other.c ${CMAKE_CURRENT_BINARY_DIR}/generated.c)\n'
            'target_include_directories(firmware PRIVATE ${CMAKE_CURRENT_BINARY_DIR})\n','utf-8')
        (self.root/'generated.h.in').write_text('#define BUILD_WIDTH @WIDTH@\n','utf-8')
        (self.root/'generated.c.in').write_text('int generated_value=@WIDTH@;\n','utf-8')
        (self.root/'main.c').write_text('#include "generated.h"\nint marker[BUILD_WIDTH];int shared;'
            'void Task(void){shared=BUILD_WIDTH;}void ISR(void){shared++;}\n','utf-8')
        self.case.git('add','.');self.case.git('commit','-m','CMake baseline');base=self.case.git('rev-parse','HEAD')
        text=(self.root/'CMakeLists.txt').read_text('utf-8')
        (self.root/'CMakeLists.txt').write_text(text.replace('WIDTH 1','WIDTH 2'),'utf-8');self.case.git('add','CMakeLists.txt')
        (self.root/'CMakeLists.txt').write_text(text.replace('WIDTH 1','WIDTH 3'),'utf-8')
        cfg=read_json(self.case.config);cfg['analysis'].update(compile_database='auto',
            cmake=dict(build_dir='build/ecra',generator='Ninja',target='firmware',build=True,clean_before_configure=True,
                args=['-DCMAKE_SYSTEM_NAME=Generic','-DCMAKE_C_COMPILER=arm-none-eabi-gcc',
                      '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        cfg['analysis']['git_diff'].update(include_uncommitted=True,base_ref=base,verify_against_full=True)
        write_json(self.case.config,cfg);self.case.before=self.case.source_files()

    def capture(self):
        from ecra.dirty_inputs import capture_inputs
        with contextlib.redirect_stdout(io.StringIO()):
            return capture_inputs(self.root,self.case.config,self.case.data/'work/fixed')

    def test_actual_generated_inputs_staging_and_complete_native_diff(self):
        from ecra.scan_persistence import run_canonical
        from ecra import cli
        old=self.case.data/'work/tasks'/('a'*32);old.mkdir(parents=True)
        self.case.config=old/'semantics.yaml'
        shutil.copyfile(self.case.home/'semantics.yaml',self.case.config)
        descriptor=self.capture()
        # Commit two actual current TU objects, then interrupt before the third
        # is handed to the consumer. No complete result may be published.
        extraction=cli.extraction_responses
        def interrupt(*args,**kwargs):
            if Path(args[0]).resolve()!=self.root.resolve():
                yield from extraction(*args,**kwargs);return
            for index,row in enumerate(extraction(*args,**kwargs)):
                if index==2:raise KeyboardInterrupt('real current TU checkpoint')
                yield row
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('ecra.cli.extraction_responses',new=interrupt):
            code=run_canonical(self.root,self.case.config,no_review=True,scan_id='stopped-cmake',scan_mode='diff',_compiler_view=descriptor)
        self.assertEqual(code,130,output.getvalue());self.assertFalse((self.case.data/'scans/stopped-cmake/manifest.json').exists())
        # Use the same plan location and immutable task config as the actual
        # broker. This is the real replay service, not a second prepare path.
        (old/'fixed-inputs').mkdir();shutil.copyfile(self.case.data/'work/fixed/capture-plan.json',old/'fixed-inputs/capture-plan.json')
        write_json(old/'task.json',dict(id='a'*32,state='INTERRUPTED',mode='scan',project_root=str(self.root),profile_revision=sha256(self.case.config)))
        fresh=self.case.data/'work/tasks'/('b'*32);fresh.mkdir();shutil.copyfile(self.case.config,fresh/'semantics.yaml')
        write_json(fresh/'retry-source.json',dict(source_task='a'*32))
        from ecra.working_checkpoint import retry_inputs
        reused=retry_inputs(self.case.data,fresh,fresh/'semantics.yaml','scan',lambda _:None)
        self.assertEqual(reused,(self.case.config,descriptor));self.assertTrue((fresh/'reused-working-inputs.json').is_file())
        from ecra.compilation import configure_cmake
        original=configure_cmake
        def guarded(root,*args,**kwargs):
            if Path(root).resolve()==self.root.resolve():raise AssertionError('Sealed current side must never reconfigure')
            return original(root,*args,**kwargs)
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('ecra.compilation.configure_cmake',side_effect=guarded):
            code=run_canonical(self.root,self.case.config,no_review=True,scan_id='dirty-cmake',scan_mode='diff',_compiler_view=descriptor)
        self.assertIn(code,(0,1,2),output.getvalue())
        out=self.case.data/'scans/dirty-cmake';provider=EvidenceProvider(out/'scan.db')
        facts=provider.load('facts');report=provider.load('report')
        self.assertEqual(next(v['size_bytes'] for v in facts['variables'] if v['name']=='marker'),12)
        baseline=EvidenceProvider(report['git_diff']['pin']['base_facts_path']).load('facts')
        self.assertEqual(next(v['size_bytes'] for v in baseline['variables'] if v['name']=='marker'),4)
        self.assertEqual(report['git_diff']['full_verification']['state'],'PASSED')
        self.assertEqual(self.case.source_files(),self.case.before)
        self.assertFalse((self.root/'build').exists());self.assertFalse((out/'facts.json').exists())
        self.assertEqual(len(facts['translation_units']),3)
        self.assertEqual(read_json(out/'diagnostics/tu_cache.json'),dict(hits=2,extracted=1,corrupt=0,total=3))
        from ecra.workflow import saved_run
        static_sha=sha256(out/'scan.db')
        with contextlib.redirect_stdout(io.StringIO()):
            refreshed=saved_run(self.root,self.case.config,render_only=True,_out=out)
        self.assertIn(refreshed,(0,1,2));self.assertEqual(sha256(out/'scan.db'),static_sha)
        self.assertEqual(read_json(descriptor['file'])['format'],'ECRA_FROZEN_COMPILER_VIEW_V3')
        prepared=Path(descriptor['file']).parent/'prepared.json';original=prepared.read_bytes()
        prepared.write_bytes(original+b'\n')
        from ecra.working_compiler_view import ParentFiles
        from ecra.config import load_config
        cfg,_=load_config(self.root,self.case.config)
        try:
            with self.assertRaisesRegex(ValueError,'准备结果'):ParentFiles(descriptor,self.root,cfg)
        finally:prepared.write_bytes(original)
        source=self.root/'main.c';raw=source.read_bytes();stamp=source.stat()
        source.write_bytes(raw+b'\nint changed_after_stop;\n')
        try:
            with self.assertRaisesRegex(ValueError,'原工作输入已变化'):
                retry_inputs(self.case.data,fresh,fresh/'semantics.yaml','scan',lambda _:None)
        finally:source.write_bytes(raw);os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual(self.case.source_files(),self.case.before)

    def test_kernel_watch_detects_byte_aba_and_root_rename_is_blocked(self):
        from ecra.guarded_cmake import InputWatch
        source=self.root/'main.c';raw=source.read_bytes();stamp=source.stat()
        with InputWatch() as watch:
            watch.directory(self.root)
            source.write_text('changed','utf-8');source.write_bytes(raw)
            os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            with self.assertRaisesRegex(ValueError,'即使已恢复'):watch.check()
            with self.assertRaises(OSError):self.root.rename(self.root.with_name('moved'))

    def test_source_write_from_real_cmake_is_denied_without_source_changes(self):
        path=self.root/'CMakeLists.txt';path.write_text(path.read_text('utf-8')+'\nfile(WRITE "${CMAKE_SOURCE_DIR}/forbidden" "bad")\n','utf-8')
        before=self.case.source_files()
        with self.assertRaises(ValueError):self.capture()
        self.assertEqual(self.case.source_files(),before);self.assertFalse((self.root/'forbidden').exists())


class WorkingCMakeAuditTests(unittest.TestCase):
    def test_stop_during_copy_hash_and_kernel_check_is_cooperative(self):
        from ecra.working_compiler_view import _copy
        from ecra.working_snapshot import _hash
        from ecra.guarded_cmake import InputWatch
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();source=root/'source';source.write_bytes(b'actual'*250000)
            stop=root/'stop';stop.touch()
            with patch.dict(os.environ,{'ECRA_JOB_STOP_FILE':str(stop)}):
                with self.assertRaises(KeyboardInterrupt):_copy(source,root/'copy')
                with self.assertRaises(KeyboardInterrupt):_hash(source)
                if os.name=='nt':
                    with InputWatch() as watch:
                        with self.assertRaises(KeyboardInterrupt):watch.check()
            self.assertEqual(source.read_bytes(),b'actual'*250000)

    @unittest.skipUnless(os.name=='nt' and shutil.which('cmake'),'actual Windows CMake required')
    def test_low_child_cannot_erase_parent_pipe_trace(self):
        from ecra.guarded_cmake import InputWatch,BuildExecutor,require_protected_source
        with tempfile.TemporaryDirectory(prefix='ECRA trace guard ') as name:
            home=Path(name).resolve();source=home/'source';source.mkdir()
            (source/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(trace NONE)\n','utf-8')
            with InputWatch() as watch:
                watch.directory(source);executor=BuildExecutor(home/'owned',source,watch)
                built=executor(['cmake','-S',str(source),'-B',str(executor.namespace/'builds/config'),'-G','Ninja'],cwd=source)
                self.assertEqual(built.returncode,0,built.stderr)
                trace=executor.traces[0];raw=trace.read_bytes();require_protected_source(executor.audit)
                script=executor.namespace/'erase.cmake';script.write_text('file(WRITE "${TRACE}" "erased")\n','utf-8')
                denied=executor(['cmake','-DTRACE='+str(trace),'-P',str(script)],cwd=source)
                self.assertNotEqual(denied.returncode,0);self.assertEqual(trace.read_bytes(),raw)
                self.assertIn(b'"cmd"',raw)

    def test_external_configuration_reads_are_bound_and_source_globs_keep_namespace(self):
        from ecra.working_cmake import audit_trace
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();source=root/'project';source.mkdir();builtin=root/'cmake';builtin.mkdir()
            external=root/'external';external.mkdir();path=external/'actual.txt';path.write_text('actual','utf-8')
            trace=root/'trace.jsonl';executor=SimpleNamespace(traces=[trace])
            compilation=dict(cmake_cache=dict(CMAKE_ROOT=str(builtin)))
            def run(args):
                write_json(trace,dict(cmd='file',file=str(source/'CMakeLists.txt'),args=args),indent=None)
                return audit_trace(executor,compilation,source)
            result=run(['READ',str(path),'contents'])
            self.assertEqual(result['files'],[path]);self.assertEqual(result['directories'],[external])
            self.assertEqual(run(['GLOB_RECURSE','units',str(source/'Core/Src/*.c')]),dict(files=[],directories=[]))
            with self.assertRaisesRegex(ValueError,'外部GLOB'):run(['GLOB','units',str(external/'*.c')])
            with self.assertRaisesRegex(ValueError,'相对配置'):run(['READ','../external/actual.txt','contents'])

    def test_unsupported_builds_are_rejected_without_fallback(self):
        from ecra.working_cmake import policy
        for override in [dict(cmake=dict(generator='MinGW Makefiles')),dict(cmake=dict(location='project')),
                dict(auto_configure_cmake=True),dict(build_closure_only=False),dict(build_closure=dict(elf='original.elf'))]:
            value=dict(cmake=dict(generator='Ninja'));value.update(override)
            with self.subTest(override=override),self.assertRaises(ValueError):policy(value)

    def test_builtin_module_is_not_a_blanket_custom_process_exemption(self):
        from ecra.working_cmake import audit_trace
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();builtin=root/'cmake';builtin.mkdir()
            trace=root/'trace.jsonl';executor=SimpleNamespace(traces=[trace])
            compilation=dict(cmake_cache=dict(CMAKE_ROOT=str(builtin),CMAKE_C_COMPILER=str(Path(sys.executable).resolve())))
            def run(origin,args):
                write_json(trace,dict(cmd='execute_process',file=str(builtin/origin),args=args),indent=None)
                audit_trace(executor,compilation,root)
            run('Modules/CMakeDetermineCompilerId.cmake',['COMMAND',sys.executable,'-c','CMakeCCompilerId.c'])
            run('Modules/CMakeDetermineCompiler.cmake',['COMMAND',sys.executable,'-print-sysroot','OUTPUT_VARIABLE','output'])
            for origin,args in [
                ('Modules/FindOther.cmake',['COMMAND',sys.executable,'-c','arbitrary']),
                ('Modules/CMakeDetermineCompiler.cmake',['COMMAND',sys.executable,'--version','-c','arbitrary']),
                ('Modules/CMakeDetermineCompiler.cmake',['COMMAND',sys.executable,'--version','COMMAND',sys.executable]),
            ]:
                with self.subTest(origin=origin,args=args),self.assertRaisesRegex(ValueError,'自定义进程'):run(origin,args)
            ninja=root/'ninja.exe';ninja.write_bytes(b'not executed by this audit unit test')
            compilation['cmake_cache'].update(CMAKE_MAKE_PROGRAM=str(ninja),CMAKE_GENERATOR='Ninja')
            query=['COMMAND',str(ninja),'--version','OUTPUT_VARIABLE','_ninja_version','ERROR_VARIABLE','_ninja_version']
            run('Modules/Compiler/GNU.cmake',query)
            for origin,args in [('Modules/FindOther.cmake',query),
                    ('Modules/Compiler/GNU.cmake',[*query,'COMMAND',str(ninja)]),
                    ('Modules/Compiler/GNU.cmake',['COMMAND',str(ninja),'--version','-f','arbitrary.ninja'])]:
                with self.subTest(origin=origin,args=args),self.assertRaisesRegex(ValueError,'自定义进程'):run(origin,args)

    @unittest.skipUnless(os.name=='nt','Windows aliases required')
    def test_registered_junction_parent_spelling_is_accepted_but_other_junction_is_rejected(self):
        from ecra.portable import build_path,_BUILD_ALIASES,_junction
        from ecra.working_cmake import input_path
        with tempfile.TemporaryDirectory(prefix='ECRA CMake alias ') as name,patch.dict(_BUILD_ALIASES,{},clear=True):
            root=Path(name).resolve();target=root/'actual';target.mkdir();(target/'input.h').write_text('actual','utf-8')
            alias=Path(build_path(target,prefer_junction=True))
            expanded=alias.parent.resolve()/alias.name
            self.assertEqual(input_path(expanded/'input.h'),target/'input.h')
            other=root/'unregistered';_junction(other,target)
            try:
                with self.assertRaisesRegex(ValueError,'Junction'):input_path(other/'input.h')
            finally:other.rmdir()

    @unittest.skipUnless(os.name=='nt','Windows aliases required')
    def test_stale_unrelated_alias_does_not_block_new_input_but_used_alias_fails_closed(self):
        from ecra.portable import build_path,_BUILD_ALIASES,_junction
        from ecra.working_cmake import input_path,registered_aliases
        with tempfile.TemporaryDirectory(prefix='ECRA stale alias ') as name,patch.dict(_BUILD_ALIASES,{},clear=True):
            root=Path(name).resolve();stale=root/'old';stale.mkdir();other=root/'other';other.mkdir()
            live=root/'live';live.mkdir();(live/'input.h').write_text('actual','utf-8')
            old_alias=Path(build_path(stale,prefer_junction=True));old_alias.rmdir();_junction(old_alias,other)
            try:
                current=Path(build_path(live,prefer_junction=True))
                self.assertEqual(input_path(current/'input.h'),live/'input.h')
                self.assertNotIn(stale,{target for target,_ in registered_aliases()})
                with self.assertRaisesRegex(ValueError,'别名已变化'):input_path(old_alias/'input.h')
                with self.assertRaisesRegex(ValueError,'未指向原目录'):build_path(stale,prefer_junction=True)
            finally:old_alias.rmdir()
