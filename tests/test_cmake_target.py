"""Use the real build graph, not a name heuristic, to isolate hardware variants."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.compilation import configure_cmake, prepare
from ecra.config import load_config
from ecra.input_snapshot import InputSnapshot


class CMakeTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra 目标 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.settings = dict(compile_database='auto', build_closure_only=True,
            cmake=dict(build_dir='build/ecra', generator='Ninja', target='firmware', build=True))

    def fixture(self):
        compiler = shutil.which('arm-none-eabi-gcc')
        if not compiler or not shutil.which('cmake') or not shutil.which('ninja'):
            self.skipTest('需要实际 CMake、Ninja 和 ARM GCC')
        if 'compdb-targets' not in subprocess.check_output(['ninja', '-t', 'list'], text=True):
            self.skipTest('需要支持 compdb-targets 的 Ninja')
        cmake = ('cmake_minimum_required(VERSION 3.18)\n'
                 'set(CMAKE_SYSTEM_NAME Generic)\n'
                 'set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\n'
                 f'set(CMAKE_C_COMPILER "{Path(compiler).as_posix()}")\n'
                 'project(real_closure C)\n'
                 'add_library(shared OBJECT shared.c)\n'
                 'target_compile_definitions(shared PRIVATE VARIANT=1)\n'
                 'add_library(firmware STATIC main.c $<TARGET_OBJECTS:shared>)\n'
                 'add_library(other STATIC shared.c other.c)\n'
                 'target_compile_definitions(other PRIVATE VARIANT=2)\n')
        (self.root/'CMakeLists.txt').write_text(cmake, encoding='utf-8')
        for name, text in dict(shared='int shared=VARIANT;', main='int main_value;', other='int unrelated;').items():
            (self.root/(name+'.c')).write_text(text, encoding='utf-8')

    def test_real_target_contains_object_library_and_excludes_other_variant(self):
        self.fixture()
        database, steps = configure_cmake(self.root, self.settings, lambda _: None, True)
        rows = json.loads(database.read_text(encoding='utf-8'))
        self.assertEqual({Path(r['file']).name for r in rows}, {'main.c', 'shared.c'})
        self.assertTrue(any('-DVARIANT=1' in r['command'] for r in rows))
        self.assertFalse(any('-DVARIANT=2' in r['command'] for r in rows))
        self.assertEqual([s['stage'] for s in steps], ['configure', 'target-closure', 'build'])
        self.assertTrue(any('--target' in s['command'] for s in steps if s['stage'] == 'build'))
        units, coverage = prepare(self.root, dict(analysis=self.settings), lambda _: None, build_firmware=False)
        self.assertEqual(len(units), 2)
        self.assertTrue(coverage['compile_database'].endswith('ecra-target-compile_commands.json'))
        # Configuration inputs participate in the existing snapshot mechanism.
        snapshot = InputSnapshot(self.root, self.root/'diagnostics', [], coverage['consumed_inputs'])
        # A real CMake source change must refresh the closure on the next run.
        with (self.root/'CMakeLists.txt').open('a') as stream:
            stream.write('target_sources(shared PRIVATE added.c)\n')
        snapshot.verify_disk()
        with self.assertRaises(ValueError):
            snapshot.assert_valid()
        (self.root/'added.c').write_text('int added;', encoding='utf-8')
        database, _ = configure_cmake(self.root, self.settings, lambda _: None, True)
        self.assertEqual(len(json.loads(database.read_text(encoding='utf-8'))), 3)

    def test_unselected_mode_keeps_original_multi_target_database(self):
        self.fixture()
        del self.settings['cmake']['target']
        database, steps = configure_cmake(self.root, self.settings, lambda _: None, True)
        self.assertEqual(database.name, 'compile_commands.json')
        self.assertEqual(len(json.loads(database.read_text(encoding='utf-8'))), 4)
        self.assertEqual([s['stage'] for s in steps], ['configure', 'build'])

    def test_forced_response_files_remain_usable_after_ninja_removes_them(self):
        self.fixture()
        self.settings['cmake']['args'] = ['-DCMAKE_NINJA_FORCE_RESPONSE_FILE=ON']
        configure_cmake(self.root, self.settings, lambda _: None, True)
        units, _ = prepare(self.root, dict(analysis=self.settings), lambda _: None, build_firmware=False)
        self.assertEqual(len(units), 2)
        shared = next(u for u in units if u['source_file'] == 'shared.c')
        self.assertIn('-DVARIANT=1', shared['original_arguments'])

    def test_missing_target_fails_and_does_not_use_stale_database(self):
        self.fixture()
        configure_cmake(self.root, self.settings, lambda _: None, True)
        self.settings['cmake']['target'] = 'missing-target'
        with self.assertRaisesRegex(ValueError, '闭包读取失败'):
            configure_cmake(self.root, self.settings, lambda _: None, False)

    def test_unsupported_ninja_and_empty_or_malformed_closure_fail(self):
        self.fixture()
        configure_cmake(self.root, self.settings, lambda _: None, True)
        from ecra.compilation import execute as original
        for output, code in [('[]', 0), ('{}', 0), ('not-json', 0), ('', 1)]:
            def execute(argv, **kwargs):
                if 'compdb-targets' in argv:
                    return subprocess.CompletedProcess(argv, code, output, 'unsupported')
                return original(argv, **kwargs)
            with self.subTest(output=output, code=code), patch('ecra.compilation.execute', side_effect=execute):
                with self.assertRaisesRegex(ValueError, '闭包'):
                    configure_cmake(self.root, self.settings, lambda _: None, False)

    def test_target_config_is_strict(self):
        cfg = dict(version=1, project=dict(root=str(self.root)), analysis=self.settings)
        path = self.root/'semantics.yaml'
        for target, generator, args in [(False, 'Ninja', []), ('', 'Ninja', []),
                ('--help', 'Ninja', []), ('bad\nname', 'Ninja', []),
                ('firmware', 'MinGW Makefiles', []), ('firmware', 'Ninja', ['--target', 'other']),
                ('firmware', 'Ninja', ['--', 'other'])]:
            self.settings['cmake'].update(target=target, generator=generator, build_args=args)
            path.write_text(json.dumps(cfg), encoding='utf-8')
            with self.subTest(target=target, generator=generator, args=args), self.assertRaisesRegex(ValueError, 'cmake'):
                load_config(self.root, path)


if __name__ == '__main__':
    unittest.main()
