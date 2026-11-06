import contextlib
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from ecra.common import read_json,write_json
from ecra.managed_build_closure import resolve
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider


class ManagedBuildClosureTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.folder=Path(folder.name).resolve();self.root=self.folder/'firmware';self.root.mkdir()
        self.build=self.folder/'data/builds/owned';self.build.mkdir(parents=True)
        (self.build/'.ecra-build-owner').write_text(str(self.root),'utf-8')
        for name in ('firmware.elf','firmware.map'):(self.build/name).write_bytes(name.encode())
        self.closure=dict(elf='build/ecra/firmware.elf',map='build/ecra/firmware.map')
        self.analysis=dict(cmake=dict(build_dir='build/ecra'),build_closure=self.closure)
        self.steps=[dict(stage='build',exit_code=0)];self.consumed={}

    def bind(self):return resolve(self.root,self.analysis,self.build,self.steps,self.consumed)

    def test_exact_missing_logical_pair_binds_to_owned_outputs_with_full_hashes(self):
        bound,proof=self.bind()
        self.assertEqual(self.analysis['build_closure'],self.closure)
        for key in ('elf','map'):
            actual=self.build/Path(self.closure[key]).name
            self.assertEqual(bound[key],str(actual));self.assertEqual(proof['artifacts'][key]['sha256'],sha256(actual))
            self.assertEqual(self.consumed[str(actual)]['sha256'],sha256(actual))
        self.assertFalse((self.root/'build').exists())

    def test_existing_or_external_explicit_inputs_keep_their_original_meaning(self):
        for key in ('elf','map'):
            path=self.root/self.closure[key];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original explicit artifact')
        self.assertEqual(self.bind(),(self.closure,None));self.assertEqual(self.consumed,{})
        self.analysis['build_closure']=dict(elf=str(self.build/'firmware.elf'),map=str(self.build/'firmware.map'))
        self.assertEqual(self.bind(),(self.analysis['build_closure'],None))

    def test_missing_owner_or_one_artifact_fails_without_retargeting_or_dropping(self):
        (self.build/'.ecra-build-owner').write_text(str(self.folder/'another-source'),'utf-8')
        with self.assertRaisesRegex(ValueError,'构建归属'):self.bind()
        (self.build/'.ecra-build-owner').write_text(str(self.root),'utf-8');(self.build/'firmware.map').unlink()
        with self.assertRaisesRegex(ValueError,'ELF/MAP'):self.bind()
        self.assertEqual(self.consumed,{})

    def test_unbuilt_project_mode_and_escaping_names_do_not_gain_a_binding(self):
        self.steps=[];self.assertEqual(self.bind(),(self.closure,None))
        self.steps=[dict(stage='build',exit_code=0)];self.analysis['cmake']['location']='project'
        self.assertEqual(self.bind(),(self.closure,None));self.analysis['cmake']['location']='workspace'
        self.analysis['build_closure']=dict(elf='elsewhere/firmware.elf',map='elsewhere/firmware.map')
        self.assertEqual(self.bind(),(self.analysis['build_closure'],None))
        self.analysis['build_closure']=dict(elf='build/ecra/../../outside.elf',map=self.closure['map'])
        with self.assertRaisesRegex(ValueError,'ELF/MAP'):self.bind()


@unittest.skipUnless(os.name=='nt' and all(shutil.which(p) for p in ('cmake','ninja','arm-none-eabi-gcc')),'actual ARM CMake required')
class ManagedBuildClosureNativeTests(unittest.TestCase):
    def test_real_arm_linked_artifacts_bind_both_git_sides_and_uncached_full_verification(self):
        from tests import test_native_diff_summary_cache as fixture
        case=fixture.NativeDiffSummaryCacheTests();case.setUp();self.addCleanup(case.doCleanups)
        root=case.root
        (root/'main.c').write_text('int shared;void Task(void){shared=1;}void ISR(void){shared++;}\n','utf-8')
        (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(linked C)\n'
            'add_executable(firmware main.c)\nset_target_properties(firmware PROPERTIES SUFFIX ".elf")\n'
            'target_compile_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb -ffreestanding)\n'
            'target_link_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb -nostdlib -Wl,-e,Task "-Wl,-Map,${CMAKE_BINARY_DIR}/firmware.map")\n','utf-8')
        case.git('add','.');case.git('commit','-m','actual linked CMake baseline');base=case.git('rev-parse','HEAD')
        (root/'main.c').write_text('int shared;void Task(void){shared=2;}void ISR(void){shared++;}\n','utf-8')
        case.git('commit','-am','actual current write');before=case.source_files()
        cfg=read_json(case.config);cfg['analysis'].update(compile_database='auto',
            cmake=dict(build_dir='build/ecra',generator='Ninja',target='firmware',build=True,
                args=['-DCMAKE_SYSTEM_NAME=Generic','-DCMAKE_C_COMPILER=arm-none-eabi-gcc','-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']),
            build_closure=dict(elf='build/ecra/firmware.elf',map='build/ecra/firmware.map'))
        cfg['analysis']['git_diff'].update(base_ref=base,verify_against_full=True);write_json(case.config,cfg)
        from ecra.scan_persistence import run_canonical
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=run_canonical(root,case.config,no_review=True,scan_id='linked',scan_mode='diff')
        self.assertIn(code,(0,1,2),output.getvalue());out=case.data/'scans/linked';provider=EvidenceProvider(out/'scan.db')
        provider.validate(deep=True);report=provider.load('report')
        self.assertEqual(report['git_diff']['full_verification']['state'],'PASSED')
        base_report=EvidenceProvider(report['git_diff']['pin']['base_facts_path']).load('report')
        artifacts=[]
        for value in (report,base_report):
            binding=value['coverage']['build_closure_binding'];closure=value['coverage']['build_closure']
            for key in ('elf','map'):
                path=Path(closure[key]);self.assertTrue(path.is_file());self.assertFalse(path.is_relative_to(root))
                self.assertEqual(binding['artifacts'][key]['sha256'],sha256(path))
                self.assertIn(str(path),value['coverage']['consumed_inputs'])
            self.assertTrue(Path(closure['elf']).read_bytes().startswith(b'\x7fELF'));artifacts.append(closure['elf'])
        self.assertNotEqual(*artifacts);self.assertEqual(case.source_files(),before)
        self.assertFalse((root/'build').exists());self.assertFalse((out/'facts.json').exists())
        from ecra.studio.preflight import run_preflight
        with contextlib.redirect_stdout(io.StringIO()):
            check=run_preflight(case.config,case.data,case.home/'preflight',lambda _:None)
        self.assertTrue(check['passed']);self.assertEqual(case.source_files(),before)
