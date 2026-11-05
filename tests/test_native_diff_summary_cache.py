"""Real native scans across distinct IDs; no simulated baseline evidence."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import digest, read_json, write_json
from ecra.git_diff import SUMMARY_SCHEMA, summarize
from ecra.report_package import sha256
from ecra.scan_persistence import run_canonical
from ecra.scan_store import EvidenceProvider
from ecra.workflow import clean_report, engine_digest, saved_report_digest


class NativeDiffSummaryCacheTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='ECRA Diff cache 中文 ');self.addCleanup(folder.cleanup)
        self.home=Path(folder.name).resolve();self.root=self.home/'firmware';self.root.mkdir()
        self.env=patch.dict(os.environ,dict(GIT_CONFIG_GLOBAL='NUL' if os.name=='nt' else '/dev/null',GIT_CONFIG_NOSYSTEM='1'))
        self.env.start();self.addCleanup(self.env.stop)
        (self.root/'main.c').write_text('int shared;void Task(void){shared=1;}void ISR(void){shared++;}\n','utf-8')
        (self.root/'other.c').write_text('static int other;void Other(void){other++;}\n','utf-8')
        write_json(self.root/'compile_commands.json',[dict(directory=str(self.root),file=name,
            arguments=['arm-none-eabi-gcc','-mcpu=cortex-m7','-mthumb','-c',name]) for name in ['main.c','other.c']])
        self.git('init');self.git('config','user.name','Native cache test');self.git('config','user.email','test@example.invalid')
        self.git('add','.');self.git('commit','-m','base');self.base=self.git('rev-parse','HEAD')
        (self.root/'main.c').write_text('int shared;void Task(void){shared=2;}void ISR(void){shared++;}\n','utf-8')
        self.git('commit','-am','current')
        self.data=self.home/'data';self.config=self.home/'semantics.yaml'
        write_json(self.config,dict(version=1,project=dict(root=str(self.root)),
            analysis=dict(compile_database='compile_commands.json',output=dict(location='custom',custom_dir=str(self.data)),
                          git_diff=dict(enabled=True,base_ref=self.base)),
            contexts=[dict(id='task',kind='TASK',functions=['Task']),dict(id='irq',kind='ISR',functions=['ISR'])],
            review=dict(enabled=False,prepare_packets=False)))
        self.before=self.source_files()

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.root),'-c','commit.gpgSign=false',*args],stderr=subprocess.DEVNULL).decode().strip()

    def source_files(self):
        return {p.relative_to(self.root).as_posix():(sha256(p),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}

    def scan(self,scan_id,*,success=True):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=run_canonical(self.root,self.config,no_review=True,scan_id=scan_id,scan_mode='diff')
        if success:self.assertIn(code,(0,1,2),stream.getvalue())
        else:self.assertEqual(code,3,stream.getvalue())
        out=self.data/'scans'/scan_id
        self.assertFalse((out/'facts.json').exists());self.assertFalse((out/'reports').exists())
        self.assertEqual(self.source_files(),self.before)
        return out

    def test_cross_scan_hit_matches_original_full_key_and_summary_without_full_baseline_load(self):
        load=EvidenceProvider.load
        def cold_guard(provider,name,*args,**kwargs):
            if provider.path.parent.name.startswith('base-'+self.base):
                raise AssertionError('A native cold summary must not restore the complete baseline '+name)
            return load(provider,name,*args,**kwargs)
        with patch.object(EvidenceProvider,'load',new=cold_guard):first=self.scan('first')
        report=read_json(first/'reports/global_static_concurrency.json')
        pin=report['git_diff']['pin'];archived=Path(pin['base_summary_path']);original=archived.read_bytes()
        base_out=Path(pin['base_facts_path'])  # Immutable archive of exactly the baseline database.
        facts=EvidenceProvider(base_out).load('facts');full_report=EvidenceProvider(base_out).load('report')
        expected=summarize(facts,full_report,{})
        self.assertEqual(read_json(archived),expected)
        key=digest(dict(schema=SUMMARY_SCHEMA,engine=engine_digest(),facts=pin['base_facts_sha256'],
            report=saved_report_digest(clean_report(full_report),encoding='ECRA_MERKLE_V1'),renames={}))
        self.assertEqual(archived.name,key+'.summary.json')
        cache=next((self.data/'projects').glob('*/results/git_diff/summary-cache/'+archived.name))
        self.assertFalse(os.path.samefile(cache,archived))
        baseline=cache.parent.parent/'artifacts'/('base-'+self.base)/'scan.db'
        load=EvidenceProvider.load
        def guarded(provider,name,*args,**kwargs):
            if provider.path.resolve()==baseline.resolve():
                raise AssertionError('A validated native cache hit must not restore complete baseline '+name)
            return load(provider,name,*args,**kwargs)
        with patch.object(EvidenceProvider,'load',new=guarded),patch('ecra.git_diff.summarize',wraps=summarize) as build:
            second=self.scan('second')
        self.assertEqual(build.call_count,1,'Only the current side is summarized on a hit')
        second_report=read_json(second/'reports/global_static_concurrency.json')
        self.assertEqual(second_report['git_diff']['baseline_summary_cache'],dict(hit=True,corrupt=False))
        second_archive=Path(second_report['git_diff']['pin']['base_summary_path'])
        self.assertNotEqual(second_archive,archived);self.assertEqual(second_archive.read_bytes(),original)
        self.assertFalse(os.path.samefile(cache,second_archive))
        # Rebuilding a corrupt shared cache cannot alter either archived pin.
        cache.write_bytes(b'corrupt cache')
        with patch.object(EvidenceProvider,'load',new=cold_guard),patch('ecra.git_diff.summarize',wraps=summarize) as build:
            third=self.scan('repaired')
        self.assertEqual(build.call_count,2)
        repaired=read_json(third/'reports/global_static_concurrency.json')
        self.assertEqual(repaired['git_diff']['baseline_summary_cache'],dict(hit=False,corrupt=True))
        self.assertEqual(read_json(cache),expected)
        self.assertEqual(archived.read_bytes(),original);self.assertEqual(second_archive.read_bytes(),original)
        self.assertEqual(report['git_diff']['selected_symbol_ids'],repaired['git_diff']['selected_symbol_ids'])

    def test_valid_summary_cannot_bypass_isolated_source_pollution(self):
        first=self.scan('first');report=read_json(first/'reports/global_static_concurrency.json')
        original=sha256(first/'scan.db');base=Path(report['git_diff']['pin']['base_source_root'])
        (base/'main.c').write_text('int polluted;\n','utf-8')
        failed=self.scan('polluted',success=False)
        self.assertFalse((failed/'manifest.json').exists());self.assertEqual(sha256(first/'scan.db'),original)

    def test_partial_baseline_never_publishes_complete_summary(self):
        # Both versions really contain an unresolvable compiler input.
        (self.root/'main.c').write_text('#include "absent.h"\nint shared;\n','utf-8')
        self.git('commit','-am','partial baseline');partial=self.git('rev-parse','HEAD')
        cfg=read_json(self.config);cfg['analysis']['git_diff']['base_ref']=partial;write_json(self.config,cfg)
        self.before=self.source_files();failed=self.scan('partial',success=False)
        self.assertFalse((failed/'manifest.json').exists())
        self.assertEqual(list(self.data.glob('projects/*/results/git_diff/summary-cache/*.manifest.json')),[])

    def test_mutation_between_validation_and_archive_copy_blocks_new_publication(self):
        first=self.scan('first');report=read_json(first/'reports/global_static_concurrency.json')
        old_archive=Path(report['git_diff']['pin']['base_summary_path']);before=old_archive.read_bytes()
        import shutil
        copy=shutil.copyfile;mutated=[]
        def tamper(source,target,*args,**kwargs):
            if Path(source).name.endswith('.summary.json'):
                Path(source).write_bytes(b'changed after manifest validation');mutated.append(str(source))
            return copy(source,target,*args,**kwargs)
        with patch('shutil.copyfile',side_effect=tamper):failed=self.scan('tampered',success=False)
        self.assertEqual(len(mutated),1);self.assertFalse((failed/'manifest.json').exists())
        self.assertEqual(old_archive.read_bytes(),before)

    def test_real_cmake_changed_build_creates_new_authority_and_preserves_prior_version(self):
        import shutil
        if not all(shutil.which(tool) for tool in ['cmake','ninja','arm-none-eabi-gcc']):
            self.skipTest('requires actual CMake/Ninja/ARM GCC')
        (self.root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
            'project(native_diff_cache C)\nset(BUILD_WIDTH 1 CACHE STRING "real input")\n'
            'add_library(firmware STATIC main.c other.c)\n'
            'target_compile_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb)\n'
            'target_compile_definitions(firmware PRIVATE BUILD_WIDTH=${BUILD_WIDTH})\n','utf-8')
        (self.root/'main.c').write_text('int build_marker[BUILD_WIDTH];int shared;void Task(void){shared=2;}void ISR(void){shared++;}\n','utf-8')
        self.git('add','.');self.git('commit','-m','real CMake baseline');self.base=self.git('rev-parse','HEAD')
        (self.root/'main.c').write_text('int build_marker[BUILD_WIDTH];int shared;void Task(void){shared=3;}void ISR(void){shared++;}\n','utf-8')
        self.git('commit','-am','CMake current')
        cfg=read_json(self.config)
        cfg['analysis'].update(compile_database='auto',cmake=dict(build_dir='build/ecra',generator='Ninja',
            build_type='Debug',build=True,clean_before_configure=False,args=['-DCMAKE_SYSTEM_NAME=Generic','-DCMAKE_C_COMPILER=arm-none-eabi-gcc',
                                             '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        cfg['analysis']['git_diff'].update(base_ref=self.base,verify_against_full=True)
        write_json(self.config,cfg);self.before=self.source_files()
        first=self.scan('cmake-first');first_report=read_json(first/'reports/global_static_concurrency.json')
        original_baselines={p:sha256(p) for p in self.data.glob('projects/*/results/git_diff/artifacts/base-*/scan.db')}
        self.assertEqual(len(original_baselines),1)
        def marker_size(report):
            facts=EvidenceProvider(report['git_diff']['pin']['base_facts_path']).load('facts')
            return next(v['size_bytes'] for v in facts['variables'] if v['name']=='build_marker')
        self.assertEqual(marker_size(first_report),4)
        cfg['analysis']['cmake']['args'].append('-DBUILD_WIDTH=2');write_json(self.config,cfg)
        second=self.scan('cmake-changed-build')
        report=read_json(second/'reports/global_static_concurrency.json')
        self.assertFalse(report['git_diff']['baseline_summary_cache']['hit'])
        self.assertEqual(marker_size(report),8,'A regenerated baseline must contain the changed real compiler input')
        self.assertEqual(report['git_diff']['full_verification']['state'],'PASSED')
        self.assertFalse((self.root/'build').exists())
        libraries=list((self.data/'projects').glob('*/builds/**/libfirmware.a'))
        self.assertGreaterEqual(len(libraries),2,'Both pinned versions must actually build outside firmware')
        for library in libraries:
            with library.open('rb') as stream:self.assertEqual(stream.read(8),b'!<arch>\n')
        for path,original in original_baselines.items():self.assertEqual(sha256(path),original)
        self.assertEqual(len(list(self.data.glob('projects/*/results/git_diff/artifacts/base-*/scan.db'))),2)
        self.assertNotEqual(first_report['git_diff']['pin']['base_facts_sha256'],report['git_diff']['pin']['base_facts_sha256'])
        self.assertIn('c:@shared',report['git_diff']['selected_symbol_ids'])

    def test_unknown_or_escaping_baseline_index_is_rejected_without_changing_prior_authority(self):
        first=self.scan('first');original=sha256(first/'scan.db')
        index=next(self.data.glob('projects/*/results/git_diff/artifacts/base-*.latest.json'));saved=read_json(index)
        invalid=[dict(saved,version=True),dict(saved,version=2),dict(saved,base_sha='other'),
                 dict(saved,directory='../../outside'),dict(saved,directory='base-'+self.base+'-unknown'),dict(saved,extra='unknown')]
        for ordinal,value in enumerate(invalid):
            with self.subTest(value=value):
                write_json(index,value);failed=self.scan('invalid-index-'+str(ordinal),success=False)
                self.assertFalse((failed/'manifest.json').exists());self.assertEqual(sha256(first/'scan.db'),original)
        write_json(index,saved)

    def test_interrupted_baseline_reuses_verified_tu_cache_in_new_authority(self):
        with patch('ecra.cli.merge',side_effect=RuntimeError('EXPLICIT_BASELINE_STOP_BEFORE_MERGE')):
            self.scan('interrupted-baseline',success=False)
        old=next(self.data.glob('projects/*/results/git_diff/artifacts/base-'+self.base))
        original={p.relative_to(old).as_posix():sha256(p) for p in old.rglob('*') if p.is_file()}
        self.assertFalse((old/'scan.db').exists())
        cache=next(self.data.glob('projects/*/results/cache/**/git-baselines/*/tu-v1'))
        self.assertEqual(len(list(cache.glob('*.facts'))),2)
        recovered=self.scan('recovered-baseline');report=read_json(recovered/'reports/global_static_concurrency.json')
        index=read_json(old.with_name(old.name+'.latest.json'));new=old.with_name(index['directory'])
        self.assertNotEqual(old,new);EvidenceProvider(new/'scan.db').validate(deep=True)
        self.assertEqual(read_json(new/'diagnostics/tu_cache.json'),dict(hits=2,extracted=0,corrupt=0,total=2))
        self.assertEqual(original,{p.relative_to(old).as_posix():sha256(p) for p in old.rglob('*') if p.is_file()})
        self.assertEqual(report['git_diff']['pin']['base_facts_sha256'],sha256(new/'scan.db'))

    def test_failed_regeneration_never_replaces_locator_or_old_baseline(self):
        first=self.scan('first');index=next(self.data.glob('projects/*/results/git_diff/artifacts/base-*.latest.json'))
        original_index=index.read_bytes();baseline=index.parent/read_json(index)['directory'];original=sha256(baseline/'scan.db')
        cfg=read_json(self.config);cfg['analysis']['git_diff']['cache_enabled']=False;write_json(self.config,cfg)
        with patch('ecra.git_diff.write_comparison_patch',side_effect=OSError('EXPLICIT_FAILURE_BEFORE_BASELINE_INDEX_PUBLICATION')):
            failed=self.scan('failed-regeneration',success=False)
        self.assertFalse((failed/'manifest.json').exists());self.assertEqual(index.read_bytes(),original_index)
        self.assertEqual(sha256(baseline/'scan.db'),original)
        self.assertEqual(read_json(first/'manifest.json')['state'],'STATIC_VALIDATED')


if __name__=='__main__':unittest.main()
