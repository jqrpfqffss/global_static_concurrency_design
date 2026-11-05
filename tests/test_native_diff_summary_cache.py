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
        first=self.scan('first');report=read_json(first/'reports/global_static_concurrency.json')
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
        with patch('ecra.git_diff.summarize',wraps=summarize) as build:third=self.scan('repaired')
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


if __name__=='__main__':unittest.main()
