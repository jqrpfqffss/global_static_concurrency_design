"""Stable exact-directory aliases preserve real CMake cache/database bytes."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.portable import _BUILD_ALIASES,build_path,tool_environment,tool_path


@unittest.skipUnless(os.name=='nt','Actual Windows junctions required')
class CompactAliasOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra-alias-order-')
        self.home=Path(self.temp.name).resolve();self.aliases=self.home/'aliases'
        self.parent=self.home/'actual/builds';self.child=self.parent/'firmware';self.child.mkdir(parents=True)
        self.environment=patch.dict(os.environ,ECRA_PATH_ALIAS_ROOT=str(self.aliases))
        self.environment.start();self.registry=patch.dict(_BUILD_ALIASES,{},clear=True);self.registry.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.aliases.exists():
            for alias in self.aliases.iterdir():
                # Only aliases made in this test-owned exact parent are removed;
                # never recursively remove an alias target or a tool directory.
                self.assertEqual(alias.parent.resolve(),self.aliases.resolve())
                self.assertTrue(alias.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                alias.rmdir()
        self.registry.stop();self.environment.stop();self.temp.cleanup()

    def test_existing_compact_directory_alias_is_independent_of_ancestor_registration_order(self):
        parent_alias=Path(build_path(self.parent,prefer_junction=True))
        ancestor_first=Path(build_path(self.child,prefer_junction=True))
        _BUILD_ALIASES.clear()
        child_first=Path(build_path(self.child,prefer_junction=True))
        later_parent=Path(build_path(self.parent,prefer_junction=True))
        self.assertEqual(ancestor_first,child_first)
        self.assertEqual(parent_alias,later_parent)
        self.assertEqual(child_first.resolve(),self.child)
        self.assertEqual(parent_alias.resolve(),self.parent)
        self.assertEqual(Path(build_path(self.child,prefer_junction=True)),child_first)

    def test_missing_compact_directory_has_the_same_alias_after_creation_and_reopening(self):
        target=self.parent/'not-created-yet'/'firmware'
        build_path(self.parent,prefer_junction=True)
        before=Path(build_path(target,prefer_junction=True))
        self.assertFalse(target.exists(),'Requesting an alias must not create the target')
        target.mkdir(parents=True)
        _BUILD_ALIASES.clear()
        after=Path(build_path(target,prefer_junction=True))
        self.assertEqual(before,after)
        self.assertEqual(before.resolve(),target)
        file=self.parent/'not-a-directory';file.write_bytes(b'preserved')
        with self.assertRaisesRegex(ValueError,'要求目录'):
            build_path(file,prefer_junction=True)
        self.assertEqual(file.read_bytes(),b'preserved')

    def test_noncompact_tool_paths_keep_the_whole_bundle_sibling_layout(self):
        bundle=self.home/'tool 中文'
        compiler=bundle/'tools/arm-gcc/bin/compiler.exe';compiler.parent.mkdir(parents=True);compiler.write_bytes(b'fixture')
        sibling=bundle/'tools/arm-gcc/libexec/cc1.exe';sibling.parent.mkdir();sibling.write_bytes(b'sibling')
        alias=Path(build_path(bundle,prefer_junction=True))
        binary=Path(build_path(compiler))
        self.assertEqual(binary,alias/'tools/arm-gcc/bin/compiler.exe')
        self.assertEqual((binary.parent/'../libexec/cc1.exe').resolve(),sibling)
        self.assertEqual(binary.resolve(),compiler)

    def test_real_cmake_cache_and_compile_database_survive_registry_order_change(self):
        source=self.home/'source';source.mkdir()
        self.child.rmdir()  # Actual first managed configure receives a missing build directory.
        (source/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(alias_order C)\n'
            'add_library(firmware STATIC main.c)\n','utf-8')
        (source/'main.c').write_text('int real_compiled_value;\n','utf-8')
        def configure(alias):
            argv=[tool_path('cmake'),'-S',str(source),'-B',str(alias),'-G','Ninja',
                  '-DCMAKE_C_COMPILER='+tool_path('arm-none-eabi-gcc'),
                  '-DCMAKE_MAKE_PROGRAM='+tool_path('ninja'),'-DCMAKE_SYSTEM_NAME=Generic',
                  '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON']
            result=subprocess.run(argv,env=tool_environment(),cwd=self.home,capture_output=True,
                                  text=True,encoding='utf-8',errors='replace',timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            return {name:(self.child/name).read_bytes() for name in ('CMakeCache.txt','compile_commands.json')}
        build_path(self.parent,prefer_junction=True)
        first_alias=Path(build_path(self.child,prefer_junction=True))
        # configure_cmake asks for the spelling before it creates and marks the
        # owned build directory, then invokes CMake after that creation.
        self.assertFalse(self.child.exists())
        self.child.mkdir()
        self.assertEqual(first_alias.resolve(),self.child)
        # CMake's first reconfigure replaces compiler-cache help initialized by
        # compiler detection. Settle that ordinary first-run metadata before
        # comparing the effect of alias-registry order alone.
        configure(first_alias);before=configure(first_alias)
        self.assertEqual(before,configure(first_alias))
        _BUILD_ALIASES.clear()
        second_alias=Path(build_path(self.child,prefer_junction=True));after=configure(second_alias)
        self.assertEqual(first_alias,second_alias)
        self.assertEqual(before,after)
        import json
        entries=json.loads(after['compile_commands.json'])
        self.assertEqual(len(entries),1)
        self.assertEqual(Path(entries[0]['file']).resolve(),source/'main.c')


if __name__=='__main__':unittest.main()
