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
        preflight = self.data/'work/preflight'
        with redirect_stdout(io.StringIO()):
            check = run_preflight(self.profile, self.data, preflight, lambda _: None)
        self.assertTrue(check['passed'])
        self.assertEqual(check['target'], 'app_elf')
        self.assertEqual(check['translation_units'], 3)
        run = subprocess.run([os.sys.executable, 'run_ecra.py', '--config', str(self.profile), '--no-review'],
                             capture_output=True, encoding='utf-8', timeout=180,
                             env=dict(os.environ, ECRA_DATA_ROOT=str(self.data)))
        self.assertIn(run.returncode, (0, 1, 2), run.stdout+run.stderr)
        database, = self.data.rglob('scan.db')
        provider = EvidenceProvider(database)
        provider.validate(deep=True)
        report, facts = provider.load('report'), provider.load('facts')
        coverage = report['coverage']
        self.assertEqual([coverage['translation_units_'+k] for k in ('total', 'parsed', 'partial', 'failed')], [3, 3, 0, 0])
        plan = plan_page(preflight)['items']
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


@unittest.skipUnless(all(shutil.which(tool) for tool in ('cmake', 'ninja', 'arm-none-eabi-gcc')),
                     'requires real CMake, Ninja and ARM GCC')
class AutomaticTargetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ecra auto target ')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.root = self.home/'固件 with spaces'
        self.profile = self.home/'semantics.yaml'
        self.data = self.home/'data'
        create_project(self.root)
        self.cmake = self.root/'CMakeLists.txt'
        self.version = self.root/'version.txt'
        self.version.write_text('2.22.1', 'utf-8')
        body = self.cmake.read_text('utf-8').split('add_library(other ', 1)[0]
        body = body.replace('app_elf', '${image}').replace('SUFFIX ".axf"',
            'OUTPUT_NAME "linked-${version}" SUFFIX ".payload"')
        body = body.replace('project(f4_fixture C)\n', '''project(f4_fixture C)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS version.txt)
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/version.txt" version LIMIT_COUNT 1)
set(image firmware_${version})
''')
        self.cmake.write_text(body+'''
add_custom_target(package ALL
  COMMAND ${CMAKE_COMMAND} -E touch package-entered
  COMMAND ${CMAKE_COMMAND} -E false
  DEPENDS ${image} VERBATIM)
''', 'utf-8')
        self.cfg = configuration(self.root, self.data)
        self.cfg['analysis']['cmake'].pop('target')
        self.cfg['analysis']['cmake']['generator'] = 'Ninja'
        self.cfg['analysis']['build_closure']['elf'] = 'build/manual/linked-2.22.1.payload'

    def prepare(self, **kwargs):
        return prepare(self.root, self.cfg, **kwargs)

    def extras(self, text):
        with self.cmake.open('a', encoding='utf-8') as stream:
            stream.write(text)

    def selection(self, compilation, source='automatic', target='firmware_2.22.1'):
        choice = compilation['cmake_target_selection']
        self.assertEqual((choice['source'], choice['effective_target']), (source, target), choice)
        return choice

    def test_ninja_selects_logical_target_and_reconfigures_version_without_yaml_edit(self):
        self.cfg['analysis']['cmake'].update(clean_before_configure=False, build_args=['--parallel', '2'])
        self.cfg['analysis'].pop('build_closure')
        write_json(self.profile, self.cfg)
        config_bytes = self.profile.read_bytes()
        cfg, _ = load_config(self.root, self.profile)
        for version in ('2.22.1', '2.23.0'):
            self.version.write_text(version, 'utf-8')
            units, info = prepare(self.root, cfg)
            self.selection(info, target='firmware_'+version)
            self.assertEqual(len(units), 3)
            build = Path(info['compile_database']).parent
            output = build/('linked-'+version+'.payload')
            self.assertEqual(output.read_bytes()[:4], b'\x7fELF')
            self.assertIn(str(output), info['consumed_inputs'])
            self.assertTrue((build/'generated.h').is_file())
            self.assertFalse((build/'package-entered').exists())
            self.assertTrue(any('support.dir' in row['output'] for row in read_json(info['compile_database'])))
            self.assertEqual(self.profile.read_bytes(), config_bytes)
            self.assertNotIn('target', cfg['analysis']['cmake'])
        old = build/'linked-2.22.1.payload'
        self.assertTrue(old.is_file())
        self.assertNotIn(str(old), info['consumed_inputs'])

    @unittest.skipUnless(os.name == 'nt' and shutil.which('mingw32-make'), 'requires real MinGW Makefiles')
    def test_mingw_studio_preflight_and_cli_automatic_explicit_scans_agree(self):
        from ecra.git_diff import build_arguments, summarize
        from ecra.scan_store import EvidenceProvider
        from ecra.studio.preflight import plan_page, run_preflight

        self.cfg['analysis']['cmake']['generator'] = 'MinGW Makefiles'
        def scan():
            write_json(self.profile, self.cfg)
            previous = set(self.data.rglob('scan.db'))
            proc = subprocess.run([os.sys.executable, 'run_ecra.py', '--config', str(self.profile), '--no-review'],
                                  capture_output=True, encoding='utf-8', timeout=180,
                                  env=dict(os.environ, ECRA_DATA_ROOT=str(self.data)))
            self.assertIn(proc.returncode, (0, 1, 2), proc.stdout+proc.stderr)
            database, = set(self.data.rglob('scan.db'))-previous
            provider = EvidenceProvider(database)
            provider.validate(deep=True)
            return provider.load('facts'), provider.load('report')

        write_json(self.profile, self.cfg)
        preflight = self.data/'work/preflight'
        check = run_preflight(self.profile, self.data, preflight, lambda _: None)
        self.assertIsNone(check['configured_target'])
        self.assertEqual(check['target'], 'firmware_2.22.1')
        self.assertEqual(check['target_selection']['source'], 'automatic')
        auto_facts, auto_report = scan()
        compilation = auto_report['coverage']
        self.selection(compilation)
        self.assertEqual(len(auto_facts['translation_units']), 3)
        self.assertEqual([u['original_arguments'] for u in plan_page(preflight)['items']],
                         [u['original_arguments'] for u in auto_facts['translation_units']])
        for artifact in compilation['build_closure_binding']['artifacts'].values():
            self.assertEqual(compilation['consumed_inputs'][artifact['actual']]['sha256'], artifact['sha256'])
        build = Path(compilation['compile_database']).parent
        self.assertTrue((build/'generated.c').is_file())
        self.assertFalse((build/'package-entered').exists())
        self.cfg['analysis']['cmake']['target'] = check['target']
        explicit_facts, explicit_report = scan()
        self.selection(explicit_report['coverage'], source='explicit')
        self.assertEqual([build_arguments(u, self.root) for u in auto_facts['translation_units']],
                         [build_arguments(u, self.root) for u in explicit_facts['translation_units']])
        # Compare canonical variable identities, accesses, call chains and
        # per-variable risk evidence across the actual independent builds.
        auto = summarize(auto_facts, auto_report)
        explicit = summarize(explicit_facts, explicit_report)
        self.assertEqual(auto['variables'], explicit['variables'])
        self.assertEqual(auto['edges'], explicit['edges'])
        self.assertEqual(auto['graphs'], explicit['graphs'])
        self.assertEqual(auto_report['coverage']['static_classification'],
                         explicit_report['coverage']['static_classification'])
        self.assertIn('HAL_DMA_Callback', json.dumps(auto_facts['calls']))

    def test_unique_executable_with_extra_variant_keeps_all_analysis(self):
        self.cmake.write_text(self.cmake.read_text('utf-8').split('add_custom_target(package ALL', 1)[0], 'utf-8')
        self.extras('add_library(other STATIC "object sources/dispatch.c")\n'
                    'target_compile_definitions(other PRIVATE VARIANT=2)\n')
        units, info = self.prepare()
        self.assertIn('分析范围', self.selection(info, 'default', None)['reason'])
        self.assertEqual(len(units), 4)
        self.assertEqual({arg for u in units if u['source_file'].endswith('dispatch.c')
                          for arg in u['arguments'] if arg.startswith('-DVARIANT=')},
                         {'-DVARIANT=1', '-DVARIANT=2'})
        self.assertNotIn('--target', info['cmake_steps'][-1]['command'])

    def test_linked_source_and_object_constraints_still_apply_after_selection(self):
        build = cmake_build_directory(self.root, self.cfg['analysis'])
        self.cfg['analysis']['build_closure'].update(
            linked_sources=['app/main.c', 'object sources/dispatch.c'],
            linked_objects=[str(build/'CMakeFiles/firmware_2.22.1.dir/app/main.c.obj')])
        units, info = self.prepare()
        self.selection(info)
        self.assertEqual([unit['source_file'] for unit in units], ['app/main.c'])
        self.assertEqual(info['build_closure']['source'], 'linked_inputs')
        self.assertEqual(info['build_closure']['linked_objects'], self.cfg['analysis']['build_closure']['linked_objects'])
        self.assertTrue((build/'object sources/CMakeFiles/support.dir/dispatch.c.obj').is_file())

    def test_boot_app_and_independent_custom_targets_keep_default_build(self):
        self.cmake.write_text(self.cmake.read_text('utf-8').split('add_custom_target(package ALL', 1)[0], 'utf-8')
        self.extras('add_custom_target(independent ALL COMMAND ${CMAKE_COMMAND} -E touch independent-ran)\n')
        units, info = self.prepare()
        build = Path(info['compile_database']).parent
        self.assertTrue((build/'independent-ran').is_file())
        self.assertIn('自定义目标', self.selection(info, 'default', None)['reason'])
        self.extras('add_executable(boot app/boot.c)\n'
                    'target_link_options(boot PRIVATE -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard'
                    ' -nostdlib -Wl,-e,main)\n')
        (self.root/'app/boot.c').write_text('int boot_counter;int main(void) { return ++boot_counter; }\n', 'utf-8')
        units, info = self.prepare()
        self.assertIn('多个可执行目标', self.selection(info, 'default', None)['reason'])
        self.assertEqual(len(units), 4)
        self.assertIn('app/boot.c', {unit['source_file'] for unit in units})

    @unittest.skipUnless(shutil.which('git'), 'requires Git worktrees')
    def test_git_diff_resolves_two_versions_to_separate_targets_and_artifacts(self):
        from ecra.scan_store import EvidenceProvider

        def git(*args):
            return subprocess.check_output(['git', '-c', 'user.name=ECRA test', '-c',
                                            'user.email=ecra@example.invalid', *args],
                                           cwd=self.root, text=True, encoding='utf-8').strip()
        git('init', '-q')
        git('add', '.')
        git('commit', '-qm', 'first firmware version')
        base = git('rev-parse', 'HEAD')
        self.version.write_text('2.23.0', 'utf-8')
        (self.root/'gen.c.in').write_text('#include "generated.h"\nint generated(void) { return 8; }\n', 'utf-8')
        git('commit', '-qam', 'next firmware version')
        self.cfg['analysis'].pop('build_closure')
        self.cfg['analysis']['git_diff'] = dict(enabled=True, base_ref=base, verify_against_full=True)
        write_json(self.profile, self.cfg)
        proc = subprocess.run([os.sys.executable, 'run_ecra.py', '--config', str(self.profile), '--no-review'],
                              capture_output=True, encoding='utf-8', timeout=180,
                              env=dict(os.environ, ECRA_DATA_ROOT=str(self.data)))
        self.assertIn(proc.returncode, (0, 1, 2), proc.stdout+proc.stderr)
        database, = (self.data/'scans').glob('*/scan.db')
        current = EvidenceProvider(database).load('report')
        self.assertEqual(current['git_diff']['full_verification']['state'], 'PASSED')
        baseline = EvidenceProvider(current['git_diff']['pin']['base_facts_path']).load('report')
        artifacts = []
        for report, version in ((baseline, '2.22.1'), (current, '2.23.0')):
            choice = self.selection(report['coverage'], target='firmware_'+version)
            path = Path(choice['artifact'])
            self.assertEqual(path.name, 'linked-'+version+'.payload')
            self.assertEqual(path.read_bytes()[:4], b'\x7fELF')
            self.assertIn(str(path), report['coverage']['consumed_inputs'])
            self.assertFalse((path.parent/'package-entered').exists())
            artifacts.append(path)
        self.assertNotEqual(artifacts[0].parent, artifacts[1].parent)
        self.assertEqual(git('status', '--porcelain'), '')

    def test_multicore_or_configure_only_keeps_existing_full_database(self):
        self.extras('add_executable(boot EXCLUDE_FROM_ALL app/boot.c)\n')
        (self.root/'app/boot.c').write_text('int main(void) { return 0; }\n', 'utf-8')
        for build, project in ((False, {}), (True, dict(cm4_enabled=True))):
            with self.subTest(build=build):
                self.cfg['project'].update(project)
                self.cfg['analysis']['cmake']['build'] = build
                if build:
                    with self.assertRaisesRegex(ValueError, r'(?s)CMake build 失败.*package'):
                        self.prepare()
                else:
                    units, info = self.prepare()
                    self.selection(info, 'default', None)
                    self.assertEqual(len(units), 4)
                    self.assertEqual([s['stage'] for s in info['cmake_steps']], ['clean', 'configure'])

    def test_build_args_targets_and_native_parameters_keep_their_meaning(self):
        for args in (['--target', 'firmware_2.22.1'], ['--', 'firmware_2.22.1']):
            with self.subTest(args=args):
                self.cfg['analysis']['cmake']['build_args'] = args
                units, info = self.prepare()
                self.selection(info, 'build_args', None)
                self.assertEqual(len(units), 3)
                self.assertEqual(info['cmake_steps'][-1]['command'][-len(args):], args)

    def test_selected_compile_link_and_post_build_failures_are_not_hidden(self):
        path = self.root/'app/main.c'
        main, cmake = path.read_text('utf-8'), self.cmake.read_text('utf-8')
        for src, extra, failure in [
                ('#error required_source_broken\n'+main, '', 'required_source_broken'),
                (main.replace('generated()', 'undefined_firmware_symbol()'), '', 'undefined reference'),
                (main, 'add_custom_command(TARGET ${image} POST_BUILD COMMAND ${CMAKE_COMMAND} -E false)\n',
                 ' -E false')]:
            with self.subTest(failure=failure):
                path.write_text(src, 'utf-8')
                self.cmake.write_text(cmake+extra, 'utf-8')
                with self.assertRaisesRegex(ValueError, r'(?s)CMake build 失败.*'+failure):
                    self.prepare()
                self.assertFalse((cmake_build_directory(self.root, self.cfg['analysis'])/'package-entered').exists())

    def test_reply_escape_and_build_time_cmake_input_change_block(self):
        from ecra.cmake_file_api import latest_index
        from ecra.compilation import execute

        build = cmake_build_directory(self.root, self.cfg['analysis'])
        def corrupt(argv, **kwargs):
            proc = execute(argv, **kwargs)
            if '-S' in argv:
                index = latest_index(build)
                data = read_json(index)
                data['reply']['client-ecra']['codemodel-v2']['jsonFile'] = '../outside.json'
                write_json(index, data)
            self.assertNotIn('--build', argv)
            return proc
        with patch('ecra.compilation.execute', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, '引用越界'):
                self.prepare()
        self.extras('add_custom_command(TARGET ${image} POST_BUILD COMMAND ${CMAKE_COMMAND} -E touch changed-input)\n')
        def change_input(argv, **kwargs):
            proc = execute(argv, **kwargs)
            if '--build' in argv:
                self.version.write_text('2.23.0', 'utf-8')
            return proc
        with patch('ecra.compilation.execute', side_effect=change_input):
            with self.assertRaisesRegex(ValueError, '输入证据变化.*version.txt'):
                self.prepare()
        self.assertFalse((build/'package-entered').exists())

    def test_stop_retry_requires_same_configure_evidence(self):
        from ecra.build_target_checkpoint import task_selection
        from ecra.cmake_file_api import latest_index
        from ecra.compilation import execute

        self.extras('if(DEFINED ENV{ECRA_JOB_STOP_FILE})\n'
                    '  add_custom_command(TARGET ${image} POST_BUILD COMMAND ${CMAKE_COMMAND} -E touch "$ENV{ECRA_JOB_STOP_FILE}" VERBATIM)\n'
                    'endif()\n')
        old, retry, changed = [self.data/'work/tasks'/name for name in ('original', 'retry', 'changed')]
        for folder in (old, retry, changed):
            folder.mkdir(parents=True)
            write_json(folder/'semantics.yaml', self.cfg)
        stop = self.home/'stop'
        write_json(retry/'retry-source.json', dict(source_task=old.name))

        def reformat_reply(argv, **kwargs):
            result = execute(argv, **kwargs)
            if '-S' in argv:
                index = latest_index(cmake_build_directory(self.root, self.cfg['analysis']))
                ref = read_json(index)['reply']['client-ecra']['codemodel-v2']['jsonFile']
                path = index.parent/ref
                write_json(path, read_json(path), indent=None)
            return result

        with patch.dict(os.environ, ECRA_JOB_STOP_FILE=str(stop)):
            with task_selection(old), self.assertRaises(KeyboardInterrupt):
                self.prepare()
            self.assertTrue(stop.is_file())
            stop.unlink()
            # Fresh File API serialization is allowed when the real graph and
            # compiler commands still prove the same target.
            with task_selection(retry), patch('ecra.compilation.execute', side_effect=reformat_reply), \
                    self.assertRaises(KeyboardInterrupt):
                self.prepare()
            self.assertTrue(stop.is_file())
            stop.unlink()
        self.version.write_text('2.23.0', 'utf-8')
        write_json(changed/'retry-source.json', dict(source_task=retry.name))
        with task_selection(changed), self.assertRaisesRegex(ValueError, '输入证据变化.*version.txt'):
            self.prepare()


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
