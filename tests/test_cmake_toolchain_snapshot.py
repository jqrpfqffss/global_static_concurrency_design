"""A cached relative CMake toolchain must bind the file CMake actually used."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ecra.compilation import cmake_toolchain_input
from ecra.input_snapshot import InputSnapshot
from ecra.portable import read_cache, bundle_root, tool_path


class CMakeToolchainSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra toolchain 中文 ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base/'source'; self.root.mkdir()
        self.build = self.base/'build'; self.build.mkdir()

    def test_source_relative_toolchain_is_independent_of_caller_directory_and_still_verified(self):
        source = self.root/'cmake/arm.cmake'; source.parent.mkdir()
        source.write_text('set(CMAKE_SYSTEM_NAME Generic)\n', encoding='utf-8')
        selected = cmake_toolchain_input(self.root, self.build, 'cmake/arm.cmake')
        self.assertEqual(selected, source)
        snapshot = InputSnapshot(self.root, self.base/'diagnostics', [selected])
        snapshot.verify_disk(); snapshot.assert_valid()
        source.write_text('set(CMAKE_SYSTEM_NAME Changed)\n', encoding='utf-8')
        snapshot.verify_disk()
        with self.assertRaisesRegex(ValueError, '扫描期间发生变化'):
            snapshot.assert_valid()

    def test_relative_build_file_takes_precedence_over_source_file(self):
        for folder in (self.root, self.build):
            (folder/'arm.cmake').write_text('# actual toolchain\n', encoding='utf-8')
        self.assertEqual(cmake_toolchain_input(self.root, self.build, 'arm.cmake'), self.build/'arm.cmake')

    def test_absolute_external_toolchain_keeps_its_exact_identity(self):
        source = self.base/'external toolchain.cmake'; source.write_text('# external\n')
        self.assertEqual(cmake_toolchain_input(self.root, self.build, str(source)), source)

    def test_real_cmake_configure_uses_same_build_first_and_source_fallback(self):
        bundled = Path(__file__).resolve().parents[1]/'.tools-cache/cmake-3.29.6/bin/cmake.exe'
        cmake = tool_path('cmake') if bundle_root() else (str(bundled) if bundled.is_file() else shutil.which('cmake'))
        if not cmake:
            self.skipTest('Actual CMake unavailable')
        (self.root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(Snapshot NONE)\n')
        for mode in ('source', 'build'):
            with self.subTest(mode=mode):
                build = self.build/mode; build.mkdir()
                source = self.root/'arm.cmake'
                source.write_text('set(ECRA_SELECTED source CACHE STRING "")\n')
                if mode == 'build':
                    (build/'arm.cmake').write_text('set(ECRA_SELECTED build CACHE STRING "")\n')
                command = [cmake, '-S', str(self.root), '-B', str(build), '-DCMAKE_TOOLCHAIN_FILE=arm.cmake']
                proc = subprocess.run(command, cwd=self.base, capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
                cache = read_cache(build)
                self.assertEqual(cache['ECRA_SELECTED'], mode)
                selected = cmake_toolchain_input(self.root, build, cache['CMAKE_TOOLCHAIN_FILE'])
                self.assertEqual(selected, (self.root if mode == 'source' else build)/'arm.cmake')


if __name__ == '__main__':
    unittest.main()
