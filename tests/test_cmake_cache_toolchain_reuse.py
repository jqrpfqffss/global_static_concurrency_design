"""Stable CMake metadata without weakening exact configure-input identity."""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.compilation import configure_cmake, cmake_toolchain_input
from ecra.portable import _BUILD_ALIASES, read_cache


class CMakeCachedToolchainTests(unittest.TestCase):
    def test_only_the_same_existing_toolchain_surviving_configure_avoids_repeated_override(self):
        with tempfile.TemporaryDirectory(prefix='ecra-cached-toolchain-') as name:
            home=Path(name).resolve()
            cases=[
                ('new',None,'arm.cmake',False,True),
                ('absolute','absolute','arm.cmake',False,False),
                ('source-relative','cmake/arm.cmake','cmake/arm.cmake',False,False),
                ('build-relative','arm.cmake','build/ecra/arm.cmake',False,False),
                ('build-shadows-source','arm.cmake','arm.cmake',False,True),
                ('changed','other.cmake','arm.cmake',False,True),
                ('clean','absolute','arm.cmake',True,True),
            ]
            for mode,cached,requested,clean,explicit in cases:
                with self.subTest(mode=mode):
                    root=home/mode;build=root/'build/ecra';build.mkdir(parents=True)
                    selected=root/requested;selected.parent.mkdir(parents=True,exist_ok=True)
                    selected.write_text('# requested real input\n','utf-8')
                    if cached=='absolute':cached=str(selected)
                    elif cached is not None:
                        old=build/cached
                        if mode=='source-relative':old=root/cached
                        old.parent.mkdir(parents=True,exist_ok=True)
                        if old!=selected:old.write_text('# different existing input\n','utf-8')
                    if cached is not None:
                        (build/'CMakeCache.txt').write_text('CMAKE_TOOLCHAIN_FILE:FILEPATH='+cached+'\n','utf-8')
                    if clean:(build/'.ecra-build-owner').write_text(str(root),'utf-8')
                    settings=dict(output=dict(location='custom',custom_dir=str(home/(mode+'-data'))),
                        cmake=dict(location='project',build_dir='build/ecra',generator='Ninja',
                                   toolchain_file=requested,clean_before_configure=clean,build=True))
                    original=copy.deepcopy(settings);before=selected.read_bytes()
                    def execute(command,**kwargs):
                        if '-B' in command:
                            folder=Path(command[command.index('-B')+1]);folder.mkdir(parents=True,exist_ok=True)
                            (folder/'compile_commands.json').write_text('[]','utf-8')
                        return subprocess.CompletedProcess(command,0,'boundary fixture','')
                    with patch('ecra.compilation.bundle_root',return_value=None),patch('ecra.portable.bundle_root',return_value=None),patch('ecra.compilation.execute',side_effect=execute):
                        _,steps=configure_cmake(root,settings,lambda _:None,True)
                    command=next(row['command'] for row in steps if row['stage']=='configure')
                    flags=[arg for arg in command if arg.startswith('-DCMAKE_TOOLCHAIN_FILE=')]
                    self.assertEqual(bool(flags),explicit)
                    if explicit:self.assertEqual(flags,['-DCMAKE_TOOLCHAIN_FILE='+str(selected.resolve())])
                    self.assertEqual(settings,original)
                    self.assertEqual(selected.read_bytes(),before)

    @unittest.skipUnless(os.name=='nt','Actual Windows Portable CMake/ARM toolchain required')
    def test_actual_first_reconfigure_is_byte_stable_and_changed_inputs_are_still_consumed(self):
        with tempfile.TemporaryDirectory(prefix='ecra-real-cached-toolchain-') as name:
            home=Path(name).resolve();source=home/'source';source.mkdir();aliases=home/'aliases'
            (source/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(cache_identity C ASM)\nadd_library(firmware STATIC main.c)\n','utf-8')
            (source/'main.c').write_text('int actual_compiled_value;\n','utf-8')
            toolchain=source/'arm.cmake'
            toolchain.write_text('set(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_SYSTEM_PROCESSOR arm)\nset(CMAKE_C_COMPILER arm-none-eabi-gcc)\nset(CMAKE_ASM_COMPILER arm-none-eabi-gcc)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\n','utf-8')
            settings=dict(output=dict(location='custom',custom_dir=str(home/'data')),
                cmake=dict(location='workspace',build_dir='build/ecra',generator='Ninja',toolchain_file='arm.cmake',build=True))
            from ecra.workspace import WorkspaceResolver
            WorkspaceResolver.resolve(source,settings).initialize().bind(settings)
            with patch.dict(os.environ,ECRA_PATH_ALIAS_ROOT=str(aliases)),patch.dict(_BUILD_ALIASES,{},clear=True):
                try:
                    def configure(build=False):
                        database,steps=configure_cmake(source,settings,lambda _:None,build)
                        return {key:(database.parent/key).read_bytes() for key in ('CMakeCache.txt','compile_commands.json')},steps,database
                    before,first,database=configure()
                    self.assertTrue(any(arg.startswith('-DCMAKE_TOOLCHAIN_FILE=') for arg in first[0]['command']))
                    for _ in range(2):
                        after,steps,_=configure()
                        self.assertEqual(before,after)
                        self.assertFalse(any(arg.startswith('-DCMAKE_TOOLCHAIN_FILE=') for arg in steps[0]['command']))
                    toolchain.write_text(toolchain.read_text('utf-8')+'add_compile_definitions(ECRA_TOOLCHAIN_SEMANTIC=5)\n','utf-8')
                    changed,steps,_=configure()
                    self.assertNotEqual(changed['compile_commands.json'],before['compile_commands.json'])
                    self.assertIn('ECRA_TOOLCHAIN_SEMANTIC=5',changed['compile_commands.json'].decode('utf-8'))
                    other=source/'other.cmake';other.write_text(toolchain.read_text('utf-8').replace('SEMANTIC=5','SEMANTIC=9'),'utf-8')
                    settings['cmake']['toolchain_file']='other.cmake'
                    changed,steps,new_database=configure()
                    self.assertTrue(any(arg.startswith('-DCMAKE_TOOLCHAIN_FILE=') for arg in steps[0]['command']))
                    # The formal external workspace binds distinct toolchain
                    # settings to distinct real build directories. Reusing an
                    # in-source CMake cache for another toolchain is not the
                    # currently supported delivery contract.
                    self.assertNotEqual(new_database.parent,database.parent)
                    self.assertEqual(cmake_toolchain_input(source,new_database.parent,read_cache(new_database.parent)['CMAKE_TOOLCHAIN_FILE']),other)
                    self.assertIn('ECRA_TOOLCHAIN_SEMANTIC=9',changed['compile_commands.json'].decode('utf-8'))
                    settings['cmake']['clean_before_configure']=True
                    configure(True)
                    _,steps,_=configure(True)
                    configured=next(row for row in steps if row['stage']=='configure')
                    self.assertTrue(any(arg.startswith('-DCMAKE_TOOLCHAIN_FILE=') for arg in configured['command']))
                    self.assertEqual([row['stage'] for row in steps],['clean','configure','build'])
                finally:
                    if aliases.exists():
                        for alias in aliases.iterdir():
                            self.assertEqual(alias.parent.resolve(),aliases.resolve())
                            self.assertTrue(alias.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                            alias.rmdir()


if __name__=='__main__':unittest.main()
