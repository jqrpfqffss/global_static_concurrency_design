"""The real CMake ASM query is allowed only within its exact private boundary."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

from ecra.common import read_json,write_json
from ecra.working_cmake import audit_trace
from tests import test_working_cmake as fixture


class WorkingCMakeAsmQueryTests(unittest.TestCase):
    def test_exact_builtin_assembler_version_query_and_all_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='ECRA ASM admission ') as folder:
            root=Path(folder).resolve();source=root/'source';source.mkdir()
            builtin=root/'cmake';builtin.mkdir()
            namespace=root/'private';build=namespace/'builds/current';build.mkdir(parents=True)
            working=build/'CMakeFiles/3.29.6/CompilerIdASM';working.mkdir(parents=True)
            trace=root/'trace.jsonl';executor=SimpleNamespace(namespace=namespace,traces=[trace])
            compiler=str(Path(sys.executable).resolve())
            cache=dict(CMAKE_ROOT=str(builtin),CMAKE_C_COMPILER=compiler,CMAKE_ASM_COMPILER=compiler,
                       CMAKE_CACHEFILE_DIR=str(build),CMAKE_CACHE_MAJOR_VERSION='3',
                       CMAKE_CACHE_MINOR_VERSION='29',CMAKE_CACHE_PATCH_VERSION='6')
            origin=builtin/'Modules/CMakeDetermineCompilerId.cmake'
            args=['COMMAND',compiler,'','','--version','WORKING_DIRECTORY',str(working),
                  'OUTPUT_VARIABLE','output','ERROR_VARIABLE','output','RESULT_VARIABLE','result','TIMEOUT','10']
            def run(current,args,overrides=None):
                write_json(trace,dict(cmd='execute_process',file=str(current),args=args),indent=None)
                return audit_trace(executor,dict(cmake_cache=dict(cache,**(overrides or {}))),source)
            self.assertEqual(run(origin,args),dict(files=[],directories=[]))
            other=root/'other.exe';other.write_bytes(b'not executed by the audit fixture')
            for label,current,query,overrides in [
                ('project-origin',source/'CMakeLists.txt',args,None),
                ('unrelated-builtin',builtin/'Modules/FindOther.cmake',args,None),
                ('other-tool',origin,[*args[:1],str(other),*args[2:]],None),
                ('not-configured-assembler',origin,args,dict(CMAKE_ASM_COMPILER=str(other))),
                ('extra-command',origin,[*args,'COMMAND',compiler],None),
                ('extra-argument',origin,[*args,'-c','untrusted.py'],None),
                ('source-working-directory',origin,[str(source) if item==str(working) else item for item in args],None),
                ('other-private-build',origin,args,dict(CMAKE_CACHEFILE_DIR=str(namespace/'builds/other'))),
                ('wrong-version',origin,args,dict(CMAKE_CACHE_PATCH_VERSION='7')),
                ('redirect',origin,['OUTPUT_FILE' if item=='OUTPUT_VARIABLE' else item for item in args],None),
                ('unbounded-timeout',origin,['999' if item=='10' else item for item in args],None),
            ]:
                with self.subTest(label=label),self.assertRaisesRegex(ValueError,'自定义进程'):
                    run(current,query,overrides)


@unittest.skipUnless(os.name=='nt','Windows guarded build required')
class ActualWorkingCMakeAsmTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.WorkingCMakeTests(methodName='runTest');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.case,self.root=self.fixture.case,self.fixture.root
        cmake=self.root/'CMakeLists.txt'
        text=cmake.read_text('utf-8').replace('project(dirty C)','project(dirty C ASM)')
        text=text.replace('STATIC main.c other.c ${CMAKE_CURRENT_BINARY_DIR}/generated.c)',
                          'STATIC main.c other.c asm_entry.s ${CMAKE_CURRENT_BINARY_DIR}/generated.c)')
        cmake.write_text(text,'utf-8')
        (self.root/'asm_entry.s').write_text('.syntax unified\n.thumb\n.global acceptance_asm_stub\n'
            '.type acceptance_asm_stub,%function\n.thumb_func\nacceptance_asm_stub:\n  bx lr\n','utf-8')
        cfg=read_json(self.case.config)
        # This admission fixture uses int and generated macros only. Standard
        # header discovery is a separate contract, exercised by the real CDC
        # run; no header search is required to parse these three C inputs.
        cfg['analysis']['auto_system_includes']=False
        write_json(self.case.config,cfg)
        self.case.before=self.case.source_files()

    def test_actual_c_and_asm_capture_preserves_source_and_keeps_exact_trace(self):
        descriptor=self.fixture.capture()
        prepared=read_json(Path(descriptor['file']).parent/'prepared.json')
        compilation=prepared['compilation'];guard=compilation['guarded_build']
        self.assertTrue(guard['source_readonly']);self.assertTrue(guard['namespace_changes_checked'])
        self.assertEqual(self.case.source_files(),self.case.before)
        self.assertFalse((self.root/'build').exists())
        self.assertEqual(len(prepared['units']),3)
        self.assertEqual(compilation['assembly_sources'],['asm_entry.s'])
        rows=[]
        for trace in guard['trace_files']:
            rows.extend(json.loads(line) for line in Path(trace['file']).read_text('utf-8').splitlines() if line.startswith('{'))
        queries=[row for row in rows if row.get('cmd')=='execute_process'
                 and Path(row['file']).name=='CMakeDetermineCompilerId.cmake'
                 and '--version' in row['args'] and 'WORKING_DIRECTORY' in row['args']]
        self.assertTrue(queries,'Actual ASM compiler ID query must have been recorded')
        self.assertTrue(all(row['complete'] and row['exit_code']==0 for row in guard['actual_commands']))

    def test_actual_project_command_cannot_borrow_the_asm_builtin_query(self):
        from ecra.dirty_inputs import capture_inputs
        cmake=self.root/'CMakeLists.txt'
        cmake.write_text(cmake.read_text('utf-8')+'''\nexecute_process(COMMAND "${CMAKE_ASM_COMPILER}" --version
          WORKING_DIRECTORY "${CMAKE_BINARY_DIR}/CMakeFiles/${CMAKE_VERSION}/CompilerIdASM"
          OUTPUT_VARIABLE output ERROR_VARIABLE output RESULT_VARIABLE result TIMEOUT 10)\n''','utf-8')
        before=self.case.source_files()
        with self.assertRaisesRegex(ValueError,'自定义进程'):
            capture_inputs(self.root,self.case.config,self.case.data/'work/custom-asm-command')
        self.assertEqual(self.case.source_files(),before)


if __name__=='__main__':unittest.main()
