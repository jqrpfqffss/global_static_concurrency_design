"""Real two-TU fixed-branch scans: symmetric gaps, validation failure, reopen/cache/package."""
import contextlib
import copy
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from ecra.common import read_json, write_json, digest
from ecra.report_package import export_report, import_report, sha256
from ecra.scan_store import EvidenceProvider
from ecra.studio.query import QueryService
from ecra.workflow import output_path
from ecra.config import load_config
from tests import test_native_diff_summary_cache as fixtures


class PartialScanTests(unittest.TestCase):
    setUp=fixtures.NativeDiffSummaryCacheTests.setUp
    git=fixtures.NativeDiffSummaryCacheTests.git
    source_files=fixtures.NativeDiffSummaryCacheTests.source_files
    scan=fixtures.NativeDiffSummaryCacheTests.scan

    def versions(self):
        self.git('branch','healthy')
        # Invalid conditional hides the declaration from Clang, while the
        # fixed source still contains it. Missing observations are not deletion.
        (self.root/'main.c').write_text('#if (\nint shared;void Task(void){shared++;}\n#endif\n','utf-8')
        self.git('commit','-am','localized parse gap');self.git('branch','broken')
        self.before=self.source_files()
        cfg=read_json(self.config)
        cfg['analysis']['git_diff'].update(base_ref='healthy',current_ref='broken',verify_against_full=True)
        write_json(self.config,cfg)
        return cfg

    def test_symmetric_missing_object_and_partial_cache_exchange(self):
        cfg=self.versions()
        first=self.scan('gap-head');report=read_json(first/'reports/global_static_concurrency.json');diff=report['git_diff']
        self.assertEqual(diff['publication']['state'],'VALID_PARTIAL')
        self.assertEqual(diff['full_verification']['state'],'INCOMPLETE')
        self.assertFalse(diff['deleted_variables'])
        lost=next(v for v in diff['baseline_only_variables'] if v['symbol_id']=='c:@shared')
        self.assertEqual(lost['impact']['object_change']['event'],'EXISTENCE_UNCERTAIN')
        self.assertFalse(lost['impact']['risk_transition']['counts_as_risk_resolution'])
        cfg['analysis']['git_diff'].update(base_ref='broken',current_ref='healthy');write_json(self.config,cfg)
        second=self.scan('gap-base');reverse=read_json(second/'reports/global_static_concurrency.json')['git_diff']
        self.assertEqual(reverse['publication']['state'],'VALID_PARTIAL')
        self.assertEqual(reverse['full_verification']['state'],'PASSED')  # Current side fully verifies; base remains partial.
        self.assertEqual(reverse['impacts']['c:@shared']['object_change']['event'],'EXISTENCE_UNCERTAIN')
        self.assertFalse(reverse['impacts']['c:@shared']['risk_transition']['counts_as_new_risk'])
        archived=Path(reverse['pin']['base_summary_path']);manifest=read_json(archived.with_suffix('.manifest.json'))
        self.assertFalse(manifest['complete_tus'])
        hot=self.scan('gap-base-hot');hotdiff=read_json(hot/'reports/global_static_concurrency.json')['git_diff']
        self.assertTrue(hotdiff['baseline_summary_cache']['hit'])
        cache_manifest=(self.diff_root/'summary-cache'/archived.name).with_suffix('.manifest.json')
        forged=read_json(cache_manifest)
        forged['completeness']['state']='COMPLETE'
        write_json(cache_manifest,forged)
        recovered=self.scan('gap-cache-metadata-recovered')
        recovered_diff=read_json(recovered/'reports/global_static_concurrency.json')['git_diff']
        self.assertEqual(recovered_diff['baseline_summary_cache'],dict(hit=False,corrupt=True))
        self.assertEqual(recovered_diff['publication']['state'],'VALID_PARTIAL')
        self.assertEqual(read_json(cache_manifest)['completeness']['state'],'VALID_PARTIAL')
        for key in ('impacts','impact_counts','object_accounting','comparison_objects','change_counts'):
            def portable(value):
                if isinstance(value,dict):
                    return {k:portable(v) for k,v in value.items() if k not in {'base_summary_path','base_facts_path','diff_patch_path'}}
                if isinstance(value,list):return [portable(v) for v in value]
                return value
            self.assertEqual(portable(reverse[key]),portable(hotdiff[key]),key)
        package=self.home/'partial.ecra-report';export_report(second,package)
        destination=self.home/'imported';result=import_report(package,destination)
        restored=destination/'scans'/result['scan_id']
        self.assertEqual(EvidenceProvider(restored/'scan.db').load('report',['git_diff']),reverse)
        self.assertEqual(QueryService(restored).diff_summary()['publication']['state'],'VALID_PARTIAL')

    def test_partial_reference_mismatch_and_internal_failure_keep_previous_publication(self):
        self.versions();valid=self.scan('valid-partial');before=sha256(valid/'scan.db')
        from ecra.git_diff import full_reference_summary
        def inconsistent(*args,**kwargs):
            value=full_reference_summary(*args,**kwargs)
            variable=next(iter(value['variables'].values()))
            variable['dimensions']['declaration']='confirmed-disagreement'
            return value
        with patch('ecra.git_diff.full_reference_summary',side_effect=inconsistent):
            failed=self.scan('mismatch',success=False)
        self.assertTrue((failed/'diagnostics/git-diff-verification-failed.json').is_file())
        self.assertFalse((failed/'manifest.json').exists())
        with patch('ecra.git_diff.full_reference_summary',side_effect=RuntimeError('unlocalized internal fault')):
            failed=self.scan('internal',success=False)
        self.assertFalse((failed/'manifest.json').exists())
        cfg,_=load_config(self.root,self.config)
        self.assertEqual(output_path(self.root,cfg),valid)
        self.assertEqual(sha256(valid/'scan.db'),before)

    def test_unknown_current_worker_status_without_independent_reference_is_failure(self):
        cfg=self.versions();cfg['analysis']['git_diff']['verify_against_full']=False;write_json(self.config,cfg)
        valid=self.scan('valid-before-invalid-status');before=sha256(valid/'scan.db')
        from ecra.cli import extraction_responses
        def invalid(*args,**kwargs):
            for unit,response,metadata in extraction_responses(*args,**kwargs):
                if unit['source_file']=='other.c':
                    value=read_json(metadata);value['parse_status']='UNRECOGNIZED_INTERNAL_STATE';write_json(metadata,value)
                yield unit,response,metadata
        with patch('ecra.cli.extraction_responses',side_effect=invalid):
            failed=self.scan('invalid-current-status',success=False)
        self.assertFalse((failed/'manifest.json').exists())
        cfg,_=load_config(self.root,self.config)
        self.assertEqual(output_path(self.root,cfg),valid)
        self.assertEqual(sha256(valid/'scan.db'),before)


if __name__=='__main__':unittest.main()
