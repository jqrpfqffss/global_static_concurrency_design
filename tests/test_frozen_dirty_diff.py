"""Real baseline/current/full comparison through the private frozen path."""
import copy
import io
import contextlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ecra.common import read_json,write_json
from ecra.config import load_config
from ecra.scan_persistence import run_canonical
from ecra.scan_store import EvidenceProvider
from ecra.workflow import output_path
from scripts.validate_studio_baseline import strict_difference
from tests import test_frozen_scan_pipeline as fixtures


class FrozenDirtyDiffTests(unittest.TestCase):
    def setUp(self):
        case=fixtures.FrozenScanPipelineTests(methodName='runTest');case.setUp()
        self.addCleanup(case.doCleanups);self.case=case
        self.root,self.base,self.config,self.data=case.root,case.base,case.config,case.data
        current=(self.root/'main.c').read_bytes()
        (self.root/'main.c').write_text('int shared; void ISR(void){shared++;} int main(void){shared++;return shared;}\n','utf-8')
        database=self.root/'compile_commands.json';write_json(database,read_json(case.database))
        case.git('add','.');case.git('commit','-qm','Complete baseline with real versioned database')
        case.git('branch','comparison-base')
        (self.root/'main.c').write_text('int staged_only;\n','utf-8');case.git('add','main.c')
        (self.root/'main.c').write_bytes(current)
        raw=read_json(self.config);raw['analysis']['compile_database']='compile_commands.json'
        raw['analysis']['git_diff']=dict(enabled=True,base_ref='comparison-base',current_ref='HEAD',
                                       include_uncommitted=True,cache_enabled=True,verify_against_full=True)
        write_json(self.config,raw);case.database=database;case.cfg,_=load_config(self.root,self.config)
        self.cfg=case.cfg

    def scan(self,ident,descriptor,mode='diff',expected=(0,1,2)):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=run_canonical(self.root,self.config,no_review=True,scan_id=ident,profile_id=ident,
                               scan_mode=mode,_compiler_view=descriptor)
        self.assertIn(code,expected,output.getvalue())
        return self.data/'scans'/ident

    def test_real_dirty_diff_full_verification_and_independent_full_facts_are_identical(self):
        from ecra.report_package import sha256
        from ecra.git_diff import compare
        before={str(p):sha256(p) for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError,'未提交字节'):
            run_canonical(self.root,self.config,no_review=True)
        descriptor=self.case.capture()
        diff=self.scan('dirty-diff',descriptor)
        provider=EvidenceProvider(diff/'scan.db');facts=provider.load('facts');report=provider.load('report')
        result=report['git_diff'];self.assertEqual(result['full_verification']['state'],'PASSED')
        self.assertIn('c:@shared',result['selected_symbol_ids'])
        self.assertTrue(result['pin']['include_uncommitted'])
        # All ordinary compare fields come from the unchanged algorithm over
        # the independently analyzed baseline and current complete summary.
        from ecra.git_diff import summarize
        baseline=read_json(Path(result['pin']['base_summary_path']))
        calculated=compare(baseline,summarize(facts,report),result['pin'])
        actual={k:v for k,v in result.items() if k not in {'baseline_summary_cache','tu_cache','full_verification'}}
        self.assertIsNone(strict_difference(calculated,actual))
        full=self.scan('independent-full',descriptor,mode='full')
        independent=EvidenceProvider(full/'scan.db').load('facts')
        for variable in independent['variables']:
            sid=variable['symbol_id']
            if sid in result['impacts']:variable['impact']=copy.deepcopy(result['impacts'][sid])
        self.assertIsNone(strict_difference(facts,independent))
        # verify_against_full must actually reextract through the same view.
        requests=list((diff/'workers/full-verification').glob('*.request.json'))
        self.assertEqual(len(requests),2)
        self.assertTrue(all(read_json(p)['compiler_view']==descriptor for p in requests))
        # The independent baseline must not inherit the current view or dirty
        # mode; it uses only the fixed base commit's actual compiler inputs.
        baseline_root=Path(result['pin']['base_source_root'])
        self.assertNotEqual(baseline_root,self.root)
        self.assertEqual({str(p):sha256(p) for p in self.root.rglob('*') if p.is_file()},before)
        with self.assertRaisesRegex(ValueError,'未提交字节'):
            run_canonical(self.root,self.config,no_review=True)

    def test_capture_is_reverified_after_real_baseline_before_current_is_consumed(self):
        from ecra import git_diff
        descriptor=self.case.capture();prepare=git_diff.prepare_base
        def change_index(*args,**kwargs):
            result=prepare(*args,**kwargs)
            self.case.git('add','main.c')
            return result
        with patch('ecra.git_diff.prepare_base',side_effect=change_index):
            failed=self.scan('changed-while-baseline',descriptor,expected=(3,))
        self.assertFalse((failed/'manifest.json').exists())
        self.assertIn('原索引或HEAD已变化',read_json(failed/'result_validity.json')['error'])
        self.assertFalse((failed/'workers').exists())

    def test_diff_patch_uses_frozen_git_bytes_even_when_live_bytes_change_then_restore(self):
        from ecra import git_diff
        descriptor=self.case.capture();write_patch=git_diff.write_comparison_patch
        source=self.root/'main.c';raw=source.read_bytes();stat=source.stat()
        def changed_only_during_read(pinned,destination):
            source.write_bytes(b'int adversarial_live_patch_bytes;\n')
            try:return write_patch(pinned,destination)
            finally:
                source.write_bytes(raw);os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with patch('ecra.git_diff.write_comparison_patch',side_effect=changed_only_during_read):
            out=self.scan('patch-byte-proof',descriptor)
        report=EvidenceProvider(out/'scan.db').load('report');pinned=report['git_diff']['pin']
        frozen=read_json(Path(descriptor['file']))['capture']['repository_root']
        expected=self.base/'captured-expected.patch'
        write_patch(dict(pinned,repository_root=frozen),expected)
        self.assertEqual(Path(pinned['diff_patch_path']).read_bytes(),expected.read_bytes())
        self.assertNotIn(b'adversarial_live_patch_bytes',expected.read_bytes())

    def test_dirty_diff_warm_and_corrupted_cache_retain_all_facts_and_uncached_verification(self):
        from ecra.workspace import context
        from ecra.report_package import sha256
        descriptor=self.case.capture()
        cold=self.scan('diff-cold',descriptor)
        expected=EvidenceProvider(cold/'scan.db').load('facts')
        def assert_same_facts(out):
            actual=EvidenceProvider(out/'scan.db').load('facts')
            projected=copy.deepcopy(expected)
            actual_variables={row['symbol_id']:row for row in actual['variables']}
            pin=EvidenceProvider(out/'scan.db').load('report')['git_diff']['pin']
            for variable in projected['variables']:
                if 'impact' not in variable:continue
                # Each scan has its own immutable evidence reference. Prove
                # the complete referenced bytes identical before rebinding
                # those locations; do not alter the graph comparator.
                for location,proof in [('base_facts_path','base_facts_sha256'),
                                       ('base_summary_path','base_summary_sha256'),
                                       ('diff_patch_path','diff_patch_sha256')]:
                    old=Path(variable['impact'][location])
                    new=Path(actual_variables[variable['symbol_id']]['impact'][location])
                    self.assertEqual(str(new),pin[location])
                    self.assertEqual(sha256(old),sha256(new))
                    self.assertEqual(sha256(new),pin[proof])
                    variable['impact'][location]=str(new)
            self.assertIsNone(strict_difference(projected,actual))
        warm=self.scan('diff-warm',descriptor)
        self.assertEqual(read_json(warm/'diagnostics/tu_cache.json'),dict(hits=2,extracted=0,corrupt=0,total=2))
        assert_same_facts(warm)
        cache=Path(context(self.root,self.cfg['analysis']).cache_root)/'formal/tu-v1'
        cached=list(cache.glob('*.facts'));self.assertGreaterEqual(len(cached),2)
        for entry in cached:entry.write_bytes(b'actual damaged raw cache payload')
        repaired=self.scan('diff-corrupt',descriptor)
        self.assertEqual(read_json(repaired/'diagnostics/tu_cache.json'),dict(hits=0,extracted=2,corrupt=2,total=2))
        assert_same_facts(repaired)
        for out in [cold,warm,repaired]:
            report=EvidenceProvider(out/'scan.db').load('report')
            self.assertEqual(report['git_diff']['full_verification']['state'],'PASSED')
            requests=list((out/'workers/full-verification').glob('*.request.json'))
            self.assertEqual(len(requests),2)
            self.assertTrue(all(read_json(path)['compiler_view']==descriptor for path in requests))


if __name__=='__main__':unittest.main()
