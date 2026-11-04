"""Real canonical scans: pinned workers, parent reads, cache and publication."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ecra import working_compiler_view as view, working_snapshot
from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.scan_persistence import run_canonical
from ecra.scan_store import EvidenceProvider
from ecra.workflow import analysis_config, output_path
from scripts.compare_native_graphs import compare
from tests import test_canonical_scan as canonical_fixture


class FrozenScanPipelineTests(unittest.TestCase):
    def setUp(self):
        fixture = canonical_fixture.CanonicalScanTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.base, self.root, self.config, self.data = fixture.base, fixture.root, fixture.config, fixture.data
        import subprocess
        self.git = lambda *args: subprocess.check_output(['git','-C',str(self.root),*args], stderr=subprocess.STDOUT)
        self.git('init','-q'); self.git('config','user.name','pipeline fixture')
        self.git('config','user.email','pipeline@example.invalid'); self.git('config','core.autocrlf','false')
        (self.root/'.gitignore').write_text('generated/\n','utf-8')
        self.git('add','.'); self.git('commit','-qm','base')
        (self.root/'main.c').write_text('int staged_value;\n','utf-8'); self.git('add','main.c')
        (self.root/'generated').mkdir()
        (self.root/'generated/input.h').write_text('#define INPUT 3\n','utf-8')
        self.sdk=self.base/'SDK 中文'; self.sdk.mkdir()
        (self.sdk/'external.h').write_text('#define SDK_VALUE 7\n','utf-8')
        (self.sdk/'positive-probe.h').write_text('/* existence affects preprocessing */\n','utf-8')
        (self.root/'main.c').write_text('''#include "generated/input.h"
#include <external.h>
#if __has_include(<positive-probe.h>) && !__has_include("generated/late.h")
#define PROBE 11
#else
#define PROBE 99
#endif
int shared;
char file_layout[sizeof(__FILE__)];
const char *file_name=__FILE__;
void ISR(void){shared+=INPUT+SDK_VALUE+PROBE;}
int main(void){shared++;return shared;}
''','utf-8')
        (self.root/'callback.c').write_text('extern int shared; void callback(void){shared++;}\n','utf-8')
        self.database=fixture.native_build/'compile_commands.json'
        entries=read_json(self.database)
        entries[0]['arguments'][1:1]=['-I',str(self.sdk)]
        entries.append(dict(directory=str(self.root),file='callback.c',arguments=[
            'arm-none-eabi-gcc','-mcpu=cortex-m7','-mthumb','-c','callback.c']))
        write_json(self.database,entries)
        cfg=read_json(self.config); cfg['analysis']['extraction_workers']=2
        write_json(self.config,cfg)
        self.cfg,_=load_config(self.root,self.config)
        from ecra.workspace import WorkspaceResolver
        WorkspaceResolver.resolve(self.root,self.cfg['analysis']).initialize()

    def capture(self):
        from clang import cindex
        from ecra.portable import resolved_executable
        cindex.Index.create()
        executables=[Path(cindex.conf.lib._name).resolve(),resolved_executable('arm-none-eabi-gcc',self.root)]
        capture=working_snapshot.capture(self.root,self.cfg)
        self.captured=capture
        return view.create(capture,self.root,self.cfg,external_directories=[self.sdk],
                           external_files=[self.config,self.database,*[p for p in executables if p.is_file()]])

    def scan(self,ident,descriptor=None,expected=(0,1,2)):
        log=io.StringIO()
        with contextlib.redirect_stdout(log):
            # Independent profiles keep the ordinary new/unchanged finding
            # baseline identical. Cache keys retain the same effective config.
            code=run_canonical(self.root,self.config,no_review=True,scan_id=ident,profile_id=ident,_compiler_view=descriptor)
        self.assertIn(code,expected,log.getvalue())
        return self.data/'scans'/ident

    def test_full_native_scan_cold_warm_corrupt_cache_and_complete_archived_inputs_match(self):
        from ecra.report_package import sha256,export_report,import_report
        before={str(p.relative_to(self.root)):sha256(p) for p in self.root.rglob('*') if p.is_file()}
        descriptor=self.capture()
        frozen=self.scan('frozen-cold',descriptor)
        original=self.scan('original')
        comparison=compare(original/'scan.db',frozen/'scan.db')
        self.assertTrue(comparison['passed'],comparison['differences'])
        warm=self.scan('frozen-warm',descriptor)
        self.assertTrue(compare(original/'scan.db',warm/'scan.db')['passed'])
        stats=read_json(warm/'diagnostics/tu_cache.json')
        self.assertEqual(stats,dict(hits=2,extracted=0,corrupt=0,total=2))
        from ecra.workspace import context
        cache=Path(context(self.root,self.cfg['analysis']).cache_root)/'formal/tu-v1'
        damaged=next(cache.glob('*.facts')); damaged.write_bytes(b'actual corrupted cache bytes')
        repaired=self.scan('frozen-repaired',descriptor)
        self.assertEqual(read_json(repaired/'diagnostics/tu_cache.json')['corrupt'],1)
        result=compare(original/'scan.db',repaired/'scan.db')
        self.assertTrue(result['passed'],result['differences'])
        closure=read_json(repaired/'input_closure.json')
        self.assertEqual(closure['frozen_view']['sha256'],descriptor['sha256'])
        provider=EvidenceProvider(repaired/'scan.db'); provider.validate(deep=True)
        for request in (repaired/'workers').glob('*.request.json'):
            record=read_json(request)
            if '.original.' not in request.name:self.assertEqual(record['compiler_view'],descriptor)
        sources=read_json(repaired/'diagnostics/source_changes.json')
        self.assertTrue(sources['parent_reads'])
        self.assertIn(str(self.config.relative_to(self.base)), '\n'.join(sources['parent_reads']))
        package=self.base/'actual-frozen.ecra-report'; export_report(repaired,package)
        restored=import_report(package,self.base/'independent-import')
        self.assertTrue(compare(repaired/'scan.db',self.base/'independent-import/scans'/restored['scan_id']/'scan.db')['passed'])
        self.assertEqual({str(p.relative_to(self.root)):sha256(p) for p in self.root.rglob('*') if p.is_file()},before)
        self.assertEqual(analysis_config(load_config(self.root,self.config)[0]),analysis_config(self.cfg))

    def test_real_live_negative_probe_change_fails_and_preserves_previous_valid_snapshot(self):
        from ecra import cli
        good=self.scan('previous'); descriptor=self.capture()
        original=cli.extraction_responses
        def change(*args,**kwargs):
            (self.root/'generated/late.h').write_text('/* changes the active branch */\n','utf-8')
            yield from original(*args,**kwargs)
        with patch('ecra.cli.extraction_responses',side_effect=change):
            failed=self.scan('changed-negative-probe',descriptor,expected=(3,))
        self.assertFalse((failed/'manifest.json').exists())
        self.assertFalse(read_json(failed/'result_validity.json')['analysis_valid'])
        self.assertEqual(output_path(self.root,self.cfg),good)
        self.assertIn('原始与冻结编译输入',read_json(failed/'result_validity.json')['error'])

    def test_real_index_change_at_parent_analysis_barrier_prevents_publication(self):
        from ecra import cli
        descriptor=self.capture(); analyze=cli.analyze
        def stage(*args,**kwargs):
            self.git('add','main.c')
            return analyze(*args,**kwargs)
        with patch('ecra.cli.analyze',side_effect=stage):
            failed=self.scan('changed-index',descriptor,expected=(3,))
        self.assertFalse((failed/'manifest.json').exists())
        self.assertIn('原索引或HEAD已变化',read_json(failed/'result_validity.json')['error'])

    def test_tampered_capture_never_replaces_previous_and_unsupported_modes_remain_blocked(self):
        good=self.scan('previous'); descriptor=self.capture()
        (Path(self.captured['source_root'])/'main.c').write_bytes(b'int corrupt_copy;')
        bad=self.scan('changed-copy',descriptor,expected=(3,))
        self.assertFalse((bad/'manifest.json').exists()); self.assertEqual(output_path(self.root,self.cfg),good)
        from ecra.frozen_scan import check_mode
        from types import SimpleNamespace
        workspace=SimpleNamespace(results_root=str(good))
        for update in [dict(git_diff=dict(enabled=True)),dict(cmake={}),dict(compile_database='auto'),
                       dict(auto_configure_cmake=True),dict(build_closure_only=False)]:
            with self.subTest(update=update):
                cfg=copy.deepcopy(self.cfg); cfg['analysis'].update(update)
                with self.assertRaisesRegex(ValueError,'尚未验收'):check_mode(cfg,workspace,False)
        with self.assertRaisesRegex(ValueError,'显式独立'):check_mode(self.cfg,None,False)
        with self.assertRaisesRegex(ValueError,'新的原生'):check_mode(self.cfg,workspace,False)

    def test_original_change_during_complete_archive_audit_cannot_publish_a_new_pointer(self):
        from ecra import scan_persistence
        good=self.scan('previous'); descriptor=self.capture()
        audit=scan_persistence.archive_audit
        def change(out):
            result=audit(out)
            (self.root/'main.c').write_bytes(b'int changed_during_long_audit;')
            return result
        with patch('ecra.scan_persistence.archive_audit',side_effect=change):
            with self.assertRaisesRegex(ValueError,'原工作输入已变化'):
                self.scan('changed-during-audit',descriptor)
        failed=self.data/'scans/changed-during-audit'
        self.assertFalse((failed/'manifest.json').exists())
        self.assertFalse(read_json(failed/'result_validity.json')['analysis_valid'])
        self.assertEqual(output_path(self.root,self.cfg),good)


if __name__=='__main__':unittest.main()
