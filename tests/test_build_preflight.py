import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ecra.common import read_json
from ecra.report_package import sha256
from ecra.studio.preflight import plan_page, run_preflight


class BuildPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra 编译检查 ')
        self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name).resolve()
        self.root=self.base/'firmware';self.root.mkdir()
        self.source=self.root/'main.c';self.source.write_text('int value; int main(void){return value;}\n','utf-8')
        self.build=self.base/'original-build';self.build.mkdir()
        self.database=self.build/'compile_commands.json'
        self.compiler=shutil.which('arm-none-eabi-gcc')
        self.database.write_text(json.dumps([dict(file=str(self.source),directory=str(self.root),arguments=[
            self.compiler or 'arm-none-eabi-gcc','-mcpu=cortex-m0','-mthumb','-DVARIANT=1','-UVARIANT','-DVARIANT=2',
            '-c',str(self.source),'-o',str(self.build/('object'+str(i)+'.o'))]) for i in range(2)]),'utf-8')
        self.data=self.base/'data';self.work=self.data/'work/task';self.work.mkdir(parents=True)
        self.config=self.work/'semantics.yaml'
        self.cfg=dict(version=1,project=dict(root=str(self.root)),analysis=dict(compile_database=str(self.database),
            output=dict(location='custom',custom_dir=str(self.data)),extraction_workers=2),review=dict(enabled=False))
        self.save()

    def save(self):self.config.write_text(json.dumps(self.cfg),'utf-8')
    def check(self):
        with redirect_stdout(io.StringIO()):return run_preflight(self.config,self.data,self.work/'preflight',lambda _:None)

    def test_real_all_tu_parameters_inputs_and_pagination_without_writing_firmware_or_formal_build(self):
        if not self.compiler:self.skipTest('requires actual ARM compiler')
        before={p:(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in [self.source,self.database]}
        result=self.check()
        self.assertTrue(result['passed']);self.assertEqual(result['translation_units'],2)
        self.assertEqual(result['snapshot_status'],'VERIFIED');self.assertGreater(result['input_files'],2)
        first=plan_page(self.work/'preflight',0,1);second=plan_page(self.work/'preflight',1,1)
        self.assertEqual((first['total'],first['next_offset'],second['next_offset']),(2,1,None))
        actual=first['items'][0]
        original=json.loads(self.database.read_text('utf-8'))[0]['arguments']
        self.assertEqual(actual['original_arguments'],original)
        self.assertEqual([a for a in actual['arguments'] if 'VARIANT' in a],['-DVARIANT=1','-UVARIANT','-DVARIANT=2'])
        self.assertEqual(actual['directory'],str(self.root))
        self.assertEqual(before,{p:(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in before})
        self.assertEqual(list(self.root.iterdir()),[self.source])
        self.assertEqual(list(self.build.iterdir()),[self.database])
        self.assertFalse((self.data/'scans').exists());self.assertFalse(list(self.data.rglob('latest-scan*.json')))
        self.assertTrue(all(tool['available'] for tool in result['tools']))
        self.assertEqual(read_json(self.work/'preflight/preflight.json')['state'],'PRECHECK_READY')
        for offset,limit in [(-1,20),(0,0),(0,51)]:
            with self.assertRaises(ValueError):plan_page(self.work/'preflight',offset,limit)
        with (self.work/'preflight/plan.db').open('ab') as stream:stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'摘要不一致'):plan_page(self.work/'preflight')

    def test_actual_cmake_build_uses_external_tree_real_arm_target_and_complete_toolchain_inputs(self):
        if not self.compiler or not all(shutil.which(x) for x in ('cmake','ninja')):
            self.skipTest('requires actual CMake/Ninja/ARM compiler')
        (self.root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(preflight C)\nadd_library(firmware OBJECT main.c)\ntarget_compile_definitions(firmware PRIVATE REAL_VARIANT=7)\n','utf-8')
        toolchain=self.base/'arm-toolchain.cmake'
        toolchain.write_text('set(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\nset(CMAKE_C_COMPILER "'+self.compiler.replace('\\','/')+'")\n','utf-8')
        self.cfg['analysis'].pop('compile_database');self.cfg['analysis']['cmake']=dict(generator='Ninja',target='firmware',toolchain_file=str(toolchain),build=True,location='workspace')
        self.cfg['analysis']['expected_defines']=['REAL_VARIANT=7'];self.save()
        before={p:(sha256(p),p.stat().st_mtime_ns) for p in self.root.iterdir()}
        value=self.check();self.assertTrue(value['passed'])
        build=Path(value['build_root']);self.assertTrue(build.is_relative_to(self.data))
        objects=list(build.rglob('main.c.obj'));self.assertEqual(len(objects),1)
        raw=objects[0].read_bytes();self.assertEqual(raw[:4],b'\x7fELF');self.assertEqual(int.from_bytes(raw[18:20],'little'),40)
        unit=plan_page(self.work/'preflight')['items'][0];self.assertIn('-DREAL_VARIANT=7',unit['arguments'])
        snapshot=read_json(self.work/'preflight/diagnostics/source_changes.json')
        self.assertTrue(any('arm-toolchain.cmake' in path for path in snapshot['inputs_before']))
        self.assertEqual(before,{p:(sha256(p),p.stat().st_mtime_ns) for p in self.root.iterdir()})

    def test_missing_real_compiler_fails_before_any_native_publication_and_keeps_diagnostic(self):
        rows=json.loads(self.database.read_text('utf-8'));rows[0]['arguments'][0]=str(self.base/'missing-arm-none-eabi-gcc.exe')
        self.database.write_text(json.dumps(rows),'utf-8')
        with self.assertRaisesRegex(ValueError,'编译数据库.*工具不可运行'):self.check()
        result=read_json(self.work/'preflight/preflight.json')
        self.assertFalse(result['passed']);self.assertEqual(result['state'],'PRECHECK_FAILED')
        self.assertTrue((self.work/'preflight/diagnostics/exception.log').is_file())
        self.assertEqual(plan_page(self.work/'preflight')['items'],[])
        self.assertFalse((self.data/'scans').exists())

    def test_missing_expected_macro_is_explicit_and_does_not_become_a_safety_result(self):
        self.cfg['analysis']['expected_defines']=['VARIANT=3'];self.save()
        with self.assertRaisesRegex(ValueError,'expected_defines.*VARIANT=3'):self.check()
        self.assertFalse(read_json(self.work/'preflight/preflight.json')['passed'])
        self.assertFalse(list(self.data.rglob('scan.db')))

    def test_actual_bad_cmake_and_toolchain_are_actionable_and_no_source_outputs_are_created(self):
        self.cfg['analysis'].pop('compile_database');self.cfg['analysis']['cmake']=dict(generator='Ninja',toolchain_file='missing.cmake',build=True)
        self.save()
        with patch('ecra.portable.tool_path',return_value=str(self.base/'missing-cmake.exe')):
            with self.assertRaisesRegex(ValueError,'analysis.cmake.*工具不可运行'):self.check()
        self.assertEqual(list(self.root.iterdir()),[self.source]);self.assertFalse((self.data/'scans').exists())

    def test_failure_in_required_worker_precheck_cannot_reach_native_scan(self):
        from ecra.studio.task_worker import execute
        gate=self.work/'gate';gate.write_text('owned','ascii')
        args=SimpleNamespace(gate=gate,config=self.config,data_root=self.data,stop=self.work/'stop',
                             result=self.work/'worker-result.json',mode='scan',scan_id='id',profile_id='profile')
        with patch.dict(os.environ,{},clear=False),patch('ecra.studio.preflight.run_preflight',side_effect=ValueError('bad input')),patch('ecra.scan_persistence.run_canonical') as native:
            with self.assertRaisesRegex(ValueError,'bad input'):execute(args)
            native.assert_not_called()

    def test_generated_owned_native_worker_compiles_including_classification_observation(self):
        path=Path(__file__).resolve().parents[1]/'scripts/measure_native_golden.py'
        code=next(n.value for n in ast.walk(ast.parse(path.read_text('utf-8'))) if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='code' for x in n.targets))
        compile(ast.literal_eval(code),'<owned-native-worker>','exec')

    def test_git_precheck_uses_the_same_offline_executable_as_native_git_and_missing_git_does_not_block_draft_save(self):
        from ecra.portable import tool_path
        bundle=self.base/'bundle';git=bundle/'tools/git/cmd/git.exe';git.parent.mkdir(parents=True);git.write_bytes(b'owned-path-fixture')
        with patch('ecra.portable.bundle_root',return_value=bundle),patch('ecra.portable.build_path',side_effect=lambda p:str(p)):
            self.assertEqual(Path(tool_path('git')),git)
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        app=create_app(self.data,token='test',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345',headers={'x-ecra-session':'test','origin':'http://127.0.0.1:12345'}) as client:
            with patch('ecra.portable.tool_path',side_effect=ValueError('Portable工具缺失：controlled-test')):
                value=client.post('/api/profiles',json=dict(yaml=self.config.read_text('utf-8')))
            self.assertEqual(value.status_code,200,value.text)
            self.assertFalse(list(self.data.rglob('scan.db')))


if __name__=='__main__':unittest.main()
