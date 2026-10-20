"""Portable failures must be observable before a stale database can be scanned."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ecra.compilation import configure_cmake
from ecra.portable import audit_executable, check_cache, read_cache, tool_environment, tool_path, build_path


class PortableCMakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra portable tests ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.build = self.root/'build/ecra'
        self.build.mkdir(parents=True)
        self.settings = dict(cmake=dict(build_dir='build/ecra',generator='MinGW Makefiles',build=True))

    def cache(self, **kwargs):
        (self.build/'CMakeCache.txt').write_text('\n'.join(k+':STRING='+str(v) for k,v in kwargs.items()),encoding='utf-8')

    def test_generator_mismatch_does_not_invoke_cmake_or_delete(self):
        self.cache(CMAKE_GENERATOR='Ninja')
        with patch('ecra.compilation.execute') as execute:
            with self.assertRaisesRegex(ValueError,'Generator 冲突'):
                configure_cmake(self.root,self.settings,lambda _:None,True)
            execute.assert_not_called()
        self.assertTrue((self.build/'CMakeCache.txt').is_file())

    def test_make_cache_from_another_machine_rejected(self):
        self.cache(CMAKE_GENERATOR='MinGW Makefiles',CMAKE_MAKE_PROGRAM='X:/old/mingw32-make.exe')
        with self.assertRaisesRegex(ValueError,'旧电脑路径'):
            check_cache(self.build,self.root,'MinGW Makefiles',self.root/'tools/mingw32-make.exe')

    def test_non_cached_toolchain_compiler_metadata_is_checked_before_build(self):
        self.cache(CMAKE_CACHE_MAJOR_VERSION='3',CMAKE_CACHE_MINOR_VERSION='29',CMAKE_CACHE_PATCH_VERSION='6')
        meta = self.build/'CMakeFiles/3.29.6'
        meta.mkdir(parents=True)
        (meta/'CMakeCCompiler.cmake').write_text('set(CMAKE_C_COMPILER "X:/old/arm-none-eabi-gcc.exe")\n')
        with patch('ecra.portable.bundle_root',return_value=self.root/'bundle'):
            with self.assertRaisesRegex(ValueError,'Portable 外部工具路径'):
                check_cache(self.build,self.root,'MinGW Makefiles')

    def test_formal_build_cannot_be_cleaned_even_inside_project(self):
        sentinel = self.build/'formal-IDE-build.txt'
        sentinel.write_text('user data')
        self.settings['cmake']['clean_before_configure'] = True
        with self.assertRaisesRegex(ValueError,'非 ECRA 专用'):
            configure_cmake(self.root,self.settings,lambda _:None,True)
        self.assertEqual(sentinel.read_text(),'user data')

    def test_wrong_owner_does_not_authorize_deletion(self):
        (self.build/'.ecra-build-owner').write_text('another project')
        self.settings['cmake']['clean_before_configure'] = True
        with self.assertRaisesRegex(ValueError,'非 ECRA 专用'):
            configure_cmake(self.root,self.settings,lambda _:None,True)

    def test_explicit_external_compiler_is_diagnosed_and_never_replaced(self):
        outside = self.root/'external/gcc.exe'
        outside.parent.mkdir()
        outside.touch()
        with patch('ecra.portable.bundle_root',return_value=self.root/'bundle'):
            with self.assertRaisesRegex(ValueError,'Portable 外部工具路径'):
                audit_executable(str(outside),self.root)
            result = audit_executable(str(outside),self.root,allow_external=True)
            self.assertTrue(result['external'])
            self.assertEqual(result['path'],str(outside))

    def test_isolated_build_path_retains_windows_and_excludes_host(self):
        with patch('ecra.portable.bundle_root',return_value=self.root), patch.dict(os.environ,PATH='X:/foreign/gcc'):
            env = tool_environment()
            self.assertNotIn('foreign',env['PATH'])
            self.assertIn('System32',env['PATH'])
            self.assertIn(str(self.root/'tools/mingw/bin'),env['PATH'])
            self.assertEqual(os.environ['PATH'],'X:/foreign/gcc') # OpenCode keeps it

    def test_unix_make_lookup_uses_isolated_search_path(self):
        with patch('ecra.portable.bundle_root',return_value=self.root), \
             patch('ecra.portable.shutil.which',return_value=None) as which:
            self.assertEqual(tool_path('make'),'make')
            self.assertIn(str(self.root/'tools/mingw/bin'),which.call_args.kwargs['path'])

    @unittest.skipUnless(os.name == 'nt','Windows filesystem alias required')
    def test_unicode_make_alias_reaches_the_same_files(self):
        import stat
        source = self.root/'firmware 中文'
        source.mkdir()
        (source/'payload.txt').write_text('same file')
        with patch('ecra.portable._short_path',side_effect=str):
            alias = Path(build_path(source))
        self.assertTrue(str(alias).isascii())
        self.assertEqual(alias.resolve(),source.resolve())
        self.assertTrue(os.path.samefile(alias/'payload.txt',source/'payload.txt'))
        self.assertEqual((alias/'payload.txt').read_text(),'same file')
        if getattr(alias.lstat(),'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            self.addCleanup(alias.rmdir) # unlink only this junction; never its target

    @unittest.skipUnless(os.name == 'nt','Windows filesystem alias required')
    def test_unicode_alias_conflict_preserves_existing_data(self):
        import hashlib
        source = self.root/'conflicting 中文'
        source.mkdir()
        parent = Path(tempfile.gettempdir())/'ECRA-paths'
        parent.mkdir(exist_ok=True)
        alias = parent/hashlib.sha256(str(source.resolve()).casefold().encode('utf-8')).hexdigest()[:32]
        alias.mkdir()
        marker = alias/'keep.txt'
        marker.write_text('user data')
        self.addCleanup(alias.rmdir)
        self.addCleanup(marker.unlink)
        with patch('ecra.portable._short_path',side_effect=str):
            with self.assertRaisesRegex(ValueError,'别名冲突'):
                build_path(source)
        self.assertEqual(marker.read_text(),'user data')

    def test_build_false_exports_without_build(self):
        self.settings['cmake']['build'] = False
        def invoke(command, **kwargs):
            (self.build/'compile_commands.json').write_text('[]')
            return subprocess.CompletedProcess(command,0,'configured','')
        with patch('ecra.compilation.execute',side_effect=invoke) as execute:
            _, records = configure_cmake(self.root,self.settings,lambda _:None,True)
        self.assertEqual(execute.call_count,1)
        self.assertEqual([r['stage'] for r in records],['configure'])
        self.assertEqual(records[0]['command'][records[0]['command'].index('-G')+1],'MinGW Makefiles')

    def test_portable_make_is_forced_and_postconfigure_external_compiler_rejected(self):
        make = self.root/'tools/mingw/bin/mingw32-make.exe'
        cmake = self.root/'tools/cmake/bin/cmake.exe'
        (self.root/'portable-lock.json').write_text(json.dumps(dict(version_patterns={})))
        def invoke(command, **kwargs):
            self.assertIn('-DCMAKE_MAKE_PROGRAM:FILEPATH='+str(make),command)
            self.cache(CMAKE_GENERATOR='MinGW Makefiles',CMAKE_MAKE_PROGRAM=make,
                       CMAKE_C_COMPILER='X:/old/arm-none-eabi-gcc.exe')
            (self.build/'compile_commands.json').write_text('[]')
            return subprocess.CompletedProcess(command,0,'configured','')
        with patch('ecra.compilation.bundle_root',return_value=self.root), \
             patch('ecra.portable.bundle_root',return_value=self.root), \
             patch('ecra.compilation.tool_path',side_effect=lambda name: str(cmake if name=='cmake' else make)), \
             patch('ecra.compilation.probe_tool',return_value=dict(running=True,matching=True)), \
             patch('ecra.compilation.execute',side_effect=invoke) as execute:
            with self.assertRaisesRegex(ValueError,'Portable 外部工具路径'):
                configure_cmake(self.root,self.settings,lambda _:None,True)
            self.assertEqual(execute.call_count,1)

    @unittest.skipUnless(os.name == 'nt','Windows PE fixture required')
    def test_pe_dependency_check_detects_missing_python_dll(self):
        spec = importlib.util.spec_from_file_location('portable_validator',Path(__file__).parents[1]/'scripts/validate_portable.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        shutil.copy2(sys.executable,self.root/'python.exe')
        machine, imports = module.pe_imports(self.root/'python.exe')
        self.assertIn(machine,(0x8664,0x14c))
        self.assertTrue(any(name.startswith('python') for name in imports))
        with self.assertRaisesRegex(ValueError,'Missing runtime DLL python'):
            module.verify_pe_dependencies(self.root)

    @unittest.skipUnless(os.name == 'nt','Windows PE manifest update required')
    def test_utf8_manifest_preserves_non_resource_code_and_attests_source(self):
        import hashlib
        import contextlib
        import io
        spec = importlib.util.spec_from_file_location('make_utf8_recipe',Path(__file__).parents[1]/'scripts/enable_make_utf8.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = self.root/'manifest-fixture.exe'
        shutil.copy2(sys.executable,target)
        original = target.read_bytes()
        report = self.root/'adaptation.json'
        with self.assertRaisesRegex(ValueError,'Unexpected upstream Make SHA256'):
            module.enable(target,report,'0'*64)
        self.assertEqual(target.read_bytes(),original)
        with contextlib.redirect_stdout(io.StringIO()):
            module.enable(target,report,hashlib.sha256(original).hexdigest())
        metadata = json.loads(report.read_text())
        self.assertTrue(metadata['non_resource_sections_unchanged'])
        self.assertEqual(module.sections(target.read_bytes()),module.sections(original))
        self.assertNotEqual(metadata['artifact_sha256'],metadata['source_sha256'])


@unittest.skipUnless(shutil.which('powershell') or shutil.which('pwsh'),'PowerShell required')
class PortableCacheScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra cache tests ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.shell = shutil.which('powershell') or shutil.which('pwsh')
        self.repo = Path(__file__).resolve().parents[1]
        # Python inherits PowerShell Core's module search path from this test
        # host; Windows PS 5.1 needs to initialise its own standard module path.
        self.env = {k:v for k,v in os.environ.items() if k.upper() != 'PSMODULEPATH'}

    @staticmethod
    def quoted(path):
        return "'" + str(path).replace("'", "''") + "'"

    def invoke(self, code):
        import base64
        script = "$ErrorActionPreference='Stop'\n. " + self.quoted(self.repo/'scripts/portable_common.ps1') + '\n' + code
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        result = subprocess.run([self.shell,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                                capture_output=True,timeout=30,env=self.env)
        self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))

    def test_cached_file_mutation_is_rejected(self):
        asset = self.root/'asset'
        asset.mkdir()
        (asset/'tool.txt').write_text('original')
        self.invoke('$asset=' + self.quoted(asset) + r'''
$receipt=@{files=(Get-TreeHashes $asset)}
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $asset '.portable-receipt.json') -Encoding UTF8
Assert-TreeReceipt $asset
Set-Content -LiteralPath (Join-Path $asset 'tool.txt') -Value 'changed'
$rejected=$false
try { Assert-TreeReceipt $asset } catch { $rejected=$_.Exception.Message -like 'Cache file changed*' }
if (-not $rejected) { throw 'A changed cached file was accepted' }
''')

    def test_cleanup_cannot_escape_named_parent(self):
        parent = self.root/'output'
        parent.mkdir()
        outside = self.root/'user-data.txt'
        outside.write_text('preserve')
        self.invoke('$parent='+self.quoted(parent)+'\n$outside='+self.quoted(outside)+r'''
$rejected=$false
try { Remove-OutputChild $parent $outside } catch { $rejected=$_.Exception.Message -like 'Refusing path outside*' }
if (-not $rejected) { throw 'Unsafe cleanup was accepted' }
''')
        self.assertEqual(outside.read_text(),'preserve')

    def test_existing_bundle_configuration_is_not_overwritten(self):
        config = self.root/'ECRA-Portable/config/semantics.yaml'
        config.parent.mkdir(parents=True)
        config.write_text('project: {root: USER_CUSTOM_PATH}\n')
        original = config.read_bytes()
        result = subprocess.run([self.shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
            '-File',str(self.repo/'build_portable.ps1'),'-OutputDir',str(self.root)],capture_output=True,timeout=30,env=self.env)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Output already exists',result.stdout+result.stderr)
        self.assertEqual(config.read_bytes(),original)


if __name__ == '__main__':
    unittest.main()
