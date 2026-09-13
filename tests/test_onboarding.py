"""First-use contracts: custom config, safe YAML values and CMake bootstrap."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.cli import main
from ecra.compilation import prepare
from ecra.config import load_config


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra onboarding ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        registry = patch('ecra.config.PROJECT_INDEX', self.root/'tool-config/projects.yaml')
        registry.start()
        self.addCleanup(registry.stop)

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main([*args, '--project', str(self.root)])

    def test_init_custom_config_preserves_values_and_never_overwrites(self):
        database = 'build folder/#debug/compile_commands.json'
        self.assertEqual(self.invoke('init', '--config', '.ecra/custom.yaml',
                                    '--compile-database', database, '--model', 'existing/model'), 0)
        cfg, path = load_config(self.root, '.ecra/custom.yaml')
        self.assertEqual(cfg['analysis']['compile_database'], database)
        self.assertEqual(cfg['review']['model'], 'existing/model')
        self.assertTrue(cfg['review']['enabled'])
        self.assertEqual(cfg['review']['max_items'], 0)
        self.assertFalse((self.root/'.ecra/semantics.yaml').exists())
        original = path.read_bytes()
        self.assertEqual(self.invoke('init', '--config', str(path)), 3)
        self.assertEqual(path.read_bytes(), original)

    def test_init_windows_path_and_invalid_or_misplaced_options(self):
        database = r'C:\firmware build\compile_commands.json'
        self.assertEqual(self.invoke('init', '--compile-database', database), 0)
        self.assertEqual(load_config(self.root)[0]['analysis']['compile_database'], database)
        self.assertEqual(self.invoke('run', '--model', 'existing/model'), 3)
        self.assertEqual(self.invoke('init', '--config', 'invalid.yaml', '--model', 'invalid'), 3)
        self.assertFalse((self.root/'invalid.yaml').exists())

    def test_default_init_keeps_semantics_in_tool_project_registry(self):
        tool = self.root / 'concurrency-tool'
        with patch('ecra.config.TOOL_ROOT', tool), patch('ecra.config.PROJECT_INDEX', tool/'config/projects.yaml'), \
             patch('ecra.cli.TOOL_ROOT', tool):
            self.assertEqual(self.invoke('init'), 0)
            cfg, path = load_config(self.root)
        self.assertTrue(path.is_relative_to(tool/'config/projects'))
        self.assertEqual(cfg['version'], 1)
        self.assertFalse((self.root/'.ecra/semantics.yaml').exists())
        index = (tool/'config/projects.yaml').read_text(encoding='utf-8')
        self.assertIn('semantics.yaml', index)

    def config(self):
        return {'analysis': {'compile_database': 'build/compile_commands.json',
                             'auto_configure_cmake': True, 'cmake_build_dir': 'build',
                             'cmake_generator': 'Ninja', 'exclude': ['build/*']}}

    def test_explicit_missing_database_bootstraps_then_reuses(self):
        (self.root/'a.c').write_text('int main(void){return 0;}')
        def configure(argv, **kwargs):
            build = self.root/'build'
            build.mkdir()
            (build/'compile_commands.json').write_text(json.dumps([
                {'directory': str(self.root), 'file': 'a.c', 'arguments': ['cc', '-c', 'a.c']}]))
            self.assertIn('-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', argv)
            return subprocess.CompletedProcess(argv, 0, 'configured', '')
        with patch('ecra.compilation.execute', side_effect=configure) as execute:
            units, audit = prepare(self.root, self.config())
            self.assertEqual(len(units), 1)
            self.assertEqual(audit['selection_reason'], 'explicit')
            prepare(self.root, self.config())
            self.assertEqual(execute.call_count, 1)

    def test_mismatched_cmake_path_fails_before_configuration(self):
        cfg = self.config()
        cfg['analysis']['compile_database'] = 'other/compile_commands.json'
        with patch('ecra.compilation.execute') as execute:
            with self.assertRaisesRegex(ValueError, '不匹配'):
                prepare(self.root, cfg)
            execute.assert_not_called()

    def test_successful_cmake_without_database_explains_generator(self):
        with patch('ecra.compilation.execute', return_value=subprocess.CompletedProcess([], 0, '', '')):
            with self.assertRaisesRegex(ValueError, 'Ninja'):
                prepare(self.root, self.config())


if __name__ == '__main__':
    unittest.main()
