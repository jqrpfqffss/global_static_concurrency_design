"""Windows/ARM regression for a failing ALL packaging target."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import read_json, write_json
from ecra.compilation import cmake_build_directory, prepare
from ecra.config import load_config
from ecra.workspace import results_path


def create_project(root):
    root.mkdir()
    (root/'app').mkdir()
    (root/'object sources').mkdir()
    (root/'CMakeLists.txt').write_text(r'''cmake_minimum_required(VERSION 3.20)
project(f4_fixture C)
add_compile_options(-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard)
add_subdirectory("object sources")
add_custom_command(OUTPUT generated.c generated.h
  COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_CURRENT_SOURCE_DIR}/gen.c.in generated.c
  COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_CURRENT_SOURCE_DIR}/gen.h.in generated.h
  DEPENDS gen.c.in gen.h.in VERBATIM)
add_custom_target(generate DEPENDS generated.c generated.h)
add_executable(app_elf app/main.c ${CMAKE_CURRENT_BINARY_DIR}/generated.c)
add_dependencies(app_elf generate)
target_link_libraries(app_elf PRIVATE support)
target_include_directories(app_elf PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
target_compile_definitions(app_elf PRIVATE STM32F407xx VARIANT=1)
set_target_properties(app_elf PROPERTIES SUFFIX ".axf")
target_link_options(app_elf PRIVATE -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
  -nostdlib -Wl,-e,main "-Wl,-Map,${CMAKE_BINARY_DIR}/app.map")
add_library(other STATIC "object sources/dispatch.c")
target_compile_definitions(other PRIVATE VARIANT=2)
add_custom_target(app_M2 ALL
  COMMAND ${CMAKE_COMMAND} -E touch package-entered -p
  COMMAND cmd /d /c "mkdir -p bin && cp app_elf.axf bin"
  DEPENDS app_elf VERBATIM)
''', 'utf-8')
    (root/'object sources/CMakeLists.txt').write_text(
        'add_library(support OBJECT dispatch.c)\ntarget_compile_definitions(support PRIVATE VARIANT=1)\n', 'utf-8')
    (root/'object sources/dispatch.c').write_text(
        '#if VARIANT == 1\nvoid HAL_DMA_Callback(void);\n'
        'void dispatch(void) { HAL_DMA_Callback(); }\n#else\nint wrong_board;\n#endif\n', 'utf-8')
    (root/'app/main.c').write_text(
        '#include "generated.h"\nvoid dispatch(void);\nvolatile int dma_buffer[2];\n'
        'static struct { int count; } state;\n'
        'void HAL_DMA_Callback(void) { static int calls; ++calls; dma_buffer[0] = calls; ++state.count; }\n'
        'void DMA1_Stream0_IRQHandler(void) { dispatch(); }\n'
        'int main(void) { dma_buffer[0] = generated(); return dma_buffer[0] + state.count; }\n', 'utf-8')
    (root/'gen.c.in').write_text('#include "generated.h"\nint generated(void) { return 7; }\n', 'utf-8')
    (root/'gen.h.in').write_text('int generated(void);\n', 'utf-8')
    (root/'toolchain.cmake').write_text('set(CMAKE_SYSTEM_NAME Generic)\n'
        'set(CMAKE_C_COMPILER arm-none-eabi-gcc)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\n', 'utf-8')


def configuration(root, data):
    return dict(version=1, project=dict(root=str(root), chip='STM32F407'), review=dict(enabled=False),
        analysis=dict(include_dirs=['app'], auto_system_includes=True,
            output=dict(location='custom', custom_dir=str(data)),
            cmake=dict(generator='MinGW Makefiles', target='app_elf', build=True, build_dir='build/manual',
                       clean_before_configure=True, toolchain_file='toolchain.cmake'),
            build_closure=dict(elf='build/manual/app_elf.axf', map='build/manual/app.map')))


@unittest.skipUnless(os.name == 'nt' and all(shutil.which(tool) for tool in
    ('cmake', 'mingw32-make', 'arm-none-eabi-gcc')), 'requires Windows, real CMake/MinGW Make/ARM GCC')
class MinGWTargetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ecra-mingw-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.root = self.home/'固件 F4'
        self.data = self.home/'data'
        self.profile = self.home/'semantics.yaml'
        create_project(self.root)
        self.cfg = configuration(self.root, self.data)

    def prepare(self):
        write_json(self.profile, self.cfg)
        cfg, _ = load_config(self.root, self.profile)
        return prepare(self.root, cfg)

    def test_real_minimum_build_and_default_all_failure(self):
        units, compilation = self.prepare()
        self.assertEqual(len(units), 3)
        build = Path(compilation['compile_database']).parent
        self.assertTrue(build.is_relative_to(self.data))
        self.assertFalse((self.root/'build').exists())
        self.assertEqual((build/'.ecra-build-owner').read_text('utf-8'), str(self.root))
        self.assertEqual((build/'app_elf.axf').read_bytes()[:4], b'\x7fELF')
        self.assertTrue((build/'generated.h').is_file())
        self.assertTrue((build/'generated.c').is_file())
        self.assertFalse((build/'package-entered').exists())
        self.assertEqual(compilation['cmake_steps'][-1]['target'], 'app_elf')
        self.assertNotIn('app_M2', Path(compilation['cmake_steps'][-1]['log']).read_text('utf-8'))
        full = read_json(build/'compile_commands.json')
        self.assertEqual(len(full), 4)
        self.assertEqual(read_json(compilation['compile_database']), [r for r in full if 'other.dir' not in r['output']])
        for unit in units:
            self.assertTrue(Path(unit['original_arguments'][0]).is_file())
            self.assertTrue({'-mcpu=cortex-m4', '-mfpu=fpv4-sp-d16', '-mfloat-abi=hard'}.issubset(unit['original_arguments']))
        dispatch = next(unit for unit in units if unit['source_file'].endswith('dispatch.c'))
        self.assertEqual(dispatch['audit_role'], 'dependency')
        self.assertIn('-DVARIANT=1', dispatch['arguments'])
        binding = compilation['build_closure_binding']
        for artifact in binding['artifacts'].values():
            self.assertEqual(artifact['sha256'], compilation['consumed_inputs'][artifact['actual']]['sha256'])

        del self.cfg['analysis']['cmake']['target']
        with self.assertRaisesRegex(ValueError, r'(?s)CMake build 失败.*app_M2'):
            self.prepare()
        build = cmake_build_directory(self.root, self.cfg['analysis'])
        self.assertTrue((build/'package-entered').is_file())
        self.assertTrue((build/'app_elf.axf').is_file())
        raw = (results_path(self.root, self.cfg['analysis'])/'cmake-build.stderr.bin').read_bytes()
        self.assertIn(b'app_M2.dir', raw)

    def test_required_compile_and_link_fail_at_build_stage(self):
        main = self.root/'app/main.c'
        original = main.read_text('utf-8')
        for text, failure in [('#error required_source_broken\n'+original, 'required_source_broken'),
            (original.replace('generated()', 'missing_link_symbol()'), 'undefined reference')]:
            with self.subTest(failure=failure):
                main.write_text(text, 'utf-8')
                with self.assertRaisesRegex(ValueError, rf'(?s)CMake build 失败.*{failure}'):
                    self.prepare()
                build = cmake_build_directory(self.root, self.cfg['analysis'])
                self.assertFalse((build/'package-entered').exists())
                self.assertFalse((build/'ecra-target-compile_commands.json').exists())

    def test_excluded_compile_command_blocks_and_changed_input_refreshes(self):
        from ecra.input_snapshot import InputSnapshot
        _, info = self.prepare()
        snapshot = InputSnapshot(self.root, self.home/'diagnostics', [], info['consumed_inputs'])
        rule = self.root/'object sources/CMakeLists.txt'
        with rule.open('a', encoding='utf-8') as stream:
            stream.write('set_property(TARGET support PROPERTY EXPORT_COMPILE_COMMANDS OFF)\n')
        snapshot.verify_disk()
        with self.assertRaises(ValueError):
            snapshot.assert_valid()
        with self.assertRaisesRegex(ValueError, '目标编译闭包无法校验'):
            self.prepare()
        self.assertFalse((cmake_build_directory(self.root, self.cfg['analysis'])/'app_elf.axf').exists())

    def test_configure_cannot_reuse_old_database_when_export_is_disabled(self):
        self.cfg['analysis']['cmake']['clean_before_configure'] = False
        self.prepare()
        rule = self.root/'CMakeLists.txt'
        rule.write_text(rule.read_text('utf-8').replace('project(', 'set(CMAKE_EXPORT_COMPILE_COMMANDS OFF)\nproject('), 'utf-8')
        with self.assertRaisesRegex(ValueError, '未刷新.*禁止使用旧编译数据库'):
            self.prepare()

    def test_stop_during_real_build_does_not_publish_target_database_then_retry_succeeds(self):
        stop = self.home/'stop'
        with (self.root/'CMakeLists.txt').open('a', encoding='utf-8') as stream:
            stream.write('if(DEFINED ENV{ECRA_JOB_STOP_FILE})\n'
                '  add_custom_command(TARGET app_elf POST_BUILD COMMAND ${CMAKE_COMMAND} -E touch "$ENV{ECRA_JOB_STOP_FILE}" VERBATIM)\n'
                'endif()\n')
        with patch.dict(os.environ, ECRA_JOB_STOP_FILE=str(stop)):
            with self.assertRaises(KeyboardInterrupt):
                self.prepare()
        build = cmake_build_directory(self.root, self.cfg['analysis'])
        self.assertTrue(stop.is_file())
        self.assertFalse((build/'ecra-target-compile_commands.json').exists())
        self.assertFalse(list(self.data.rglob('input_manifest.json')))
        units, info = self.prepare()
        self.assertEqual(len(units), 3)
        self.assertEqual(info['cmake_steps'][-1]['exit_code'], 0)

    def test_real_preflight_and_cli_scan_same_target_and_ast_evidence(self):
        from ecra.scan_store import EvidenceProvider
        from ecra.studio.preflight import plan_page, run_preflight
        write_json(self.profile, self.cfg)
        with redirect_stdout(io.StringIO()):
            check = run_preflight(self.profile, self.data, self.home/'preflight', lambda _: None)
        self.assertTrue(check['passed'])
        self.assertEqual(check['target'], 'app_elf')
        self.assertEqual(check['translation_units'], 3)
        run = subprocess.run([os.sys.executable, 'run_ecra.py', '--config', str(self.profile), '--no-review'],
                             capture_output=True, encoding='utf-8', timeout=180)
        self.assertIn(run.returncode, (0, 1, 2), run.stdout+run.stderr)
        database, = self.data.rglob('scan.db')
        provider = EvidenceProvider(database)
        provider.validate(deep=True)
        report, facts = provider.load('report'), provider.load('facts')
        coverage = report['coverage']
        self.assertEqual([coverage['translation_units_'+k] for k in ('total', 'parsed', 'partial', 'failed')], [3, 3, 0, 0])
        plan = plan_page(self.home/'preflight')['items']
        self.assertEqual([u['original_arguments'] for u in plan], [u['original_arguments'] for u in facts['translation_units']])
        self.assertEqual(coverage['cmake_steps'][-1]['target'], check['target'])
        self.assertEqual({v['name'] for v in facts['variables']}, {'dma_buffer', 'dma_buffer[0]', 'calls', 'state', 'count'})
        self.assertIn('HAL_DMA_Callback', json.dumps(facts['calls']))
        self.assertIn('DMA1_Stream0_IRQHandler', json.dumps(facts['calls']))
        self.assertFalse((Path(check['build_root'])/'package-entered').exists())

    def test_uncommitted_admission_remains_ninja_only(self):
        from ecra.working_cmake import policy
        with self.assertRaisesRegex(ValueError, 'Windows/Ninja'):
            policy(self.cfg['analysis'])
        self.cfg['analysis']['git_diff'] = dict(include_uncommitted=True)
        write_json(self.profile, self.cfg)
        with self.assertRaisesRegex(ValueError, r'analysis\.cmake\.target.*Windows/Ninja'):
            load_config(self.root, self.profile)

    def test_selected_assembly_and_distinct_commands_for_the_same_source_are_retained(self):
        rule = self.root/'CMakeLists.txt'
        rule.write_text(rule.read_text('utf-8').replace('project(f4_fixture C)', 'project(f4_fixture C ASM)')+
            '\ntarget_sources(app_elf PRIVATE entry.S)\ntarget_link_libraries(app_elf PRIVATE other)\n', 'utf-8')
        with (self.root/'toolchain.cmake').open('a', encoding='utf-8') as stream:
            stream.write('set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)\n')
        (self.root/'entry.S').write_text('.syntax unified\n.thumb\n.global entry_hook\nentry_hook: bx lr\n', 'utf-8')
        units, info = self.prepare()
        self.assertEqual(info['assembly_sources'], ['entry.S'])
        duplicate = [unit for unit in units if unit['source_file'].endswith('dispatch.c')]
        self.assertEqual(len({unit['tu_id'] for unit in duplicate}), 2)
        self.assertEqual({arg for unit in duplicate for arg in unit['arguments'] if arg.startswith('-DVARIANT=')},
                         {'-DVARIANT=1', '-DVARIANT=2'})


class BuildLogTests(unittest.TestCase):
    def test_raw_bytes_and_mixed_utf8_gbk_and_unknown_diagnostics(self):
        from ecra.build_execution import save_logs
        from ecra.common import execute
        text = '命令语法不正确。'
        raw = text.encode('gbk')+b'\r\n'+'UTF-8 诊断\n'.encode('utf-8')+b'\xff'
        cmd = [os.sys.executable, '-c', f'import sys; sys.stderr.buffer.write({raw!r}); sys.exit(1)']
        result = execute(cmd, text=False, encoding=None, errors=None)
        with tempfile.TemporaryDirectory() as folder, patch('ecra.build_execution._windows_code_pages', return_value=('cp936',)):
            log, evidence, display = save_logs(Path(folder), 'build', result.stdout, result.stderr)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(Path(evidence['stderr']['path']).read_bytes(), raw)
            self.assertIn(text, display)
            self.assertIn('UTF-8 诊断', log.read_text('utf-8'))
            self.assertIn('编码不确定', display)
            self.assertIn(r'\xff', display)
