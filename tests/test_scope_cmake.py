"""Directory ownership must not erase HAL callback/alias evidence."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.analysis import analyze, merge
from ecra.cli import main, run
from ecra.compilation import prepare, system_includes
from ecra.config import load_config
from ecra.extract import Extractor
from ecra.scope import AuditScope, validate_selection
from ecra.workflow import status


class ScopeCMakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra scoped project ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        registry = patch('ecra.config.PROJECT_INDEX', self.root/'tool-config/projects.yaml')
        registry.start()
        self.addCleanup(registry.stop)
        original = Path.cwd()
        self.addCleanup(lambda: os.chdir(original))

    def fixture(self, sources, **analysis):
        entries = []
        for name, source in sources.items():
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
            if path.suffix == '.c':
                entries.append(dict(directory=str(self.root), file=name,
                    arguments=['arm-none-eabi-gcc', '-mcpu=cortex-m3', '-mthumb', '-I.', '-c', name]))
        (self.root/'compile_commands.json').write_text(json.dumps(entries))
        (self.root/'.ecra').mkdir(exist_ok=True)
        cfg = dict(version=1, analysis=dict(compile_database='compile_commands.json', **analysis),
                   contexts=[dict(id='main', kind='MAIN', functions=['main'])], review=dict(enabled=False))
        self.save(cfg)
        return load_config(self.root)[0]

    def save(self, cfg):
        (self.root/'.ecra/semantics.yaml').write_text(json.dumps(cfg), encoding='utf-8')

    def extract(self, cfg):
        units, audit = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=u, config=cfg)).run() for u in units]
        for part in parts:
            self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
        facts = merge(parts)
        report = analyze(facts, cfg, dict(translation_units_failed=0, **audit))
        return facts, report

    def test_dependency_callback_and_pointer_write_survive_scope(self):
        cfg = self.fixture({
            'App/main.c': 'int count; void Dispatch(void); void Write(int*); void Callback(void){count++;} '
                          'void USART2_IRQHandler(void){Dispatch();} int main(void){Write(&count);return 0;}',
            'Vendor/hal.c': 'int hal_private; void Callback(void); void Dispatch(void){hal_private++;Callback();} '
                            'void Write(int *p){*p+=1;} void VendorUnused(void){void (*f)(void)=0;f();}',
        }, include_dirs=['App'], exclude_dirs=['Vendor'])
        facts, report = self.extract(cfg)
        self.assertEqual([v['name'] for v in facts['variables']], ['count'])
        count = facts['variables'][0]
        self.assertIn('main', count['writers'])
        self.assertTrue(any(x.startswith('auto:USART2_IRQHandler:') for x in count['writers']))
        self.assertTrue(any(a['file']=='Vendor/hal.c' and a['access_kind']=='RMW' for a in count['accesses']))
        self.assertTrue(any(len(chain)==3 for a in count['accesses'] for chain in a['call_chains'].values()))
        self.assertFalse(any(x['variable_name']=='hal_private' for x in report['findings']))
        self.assertFalse(any(x.get('file')=='Vendor/hal.c' and x['kind']=='INDIRECT_CALL' for x in facts['unknowns']))
        self.assertEqual(report['coverage']['audit_scope']['variables_omitted'], 1)

    def test_header_static_extern_ownership_multiple_roots_and_exclusion_precedence(self):
        cfg = self.fixture({
            'App/main.c': '#include "Include/shared.h"\nvoid Other(void);int main(void){own++;header_count++;Other();return vendor;}',
            'Include/shared.h': 'extern int vendor; extern int own; static int header_count;',
            'More/own.c': '#include "Include/shared.h"\nint own;void Other(void){header_count++;}',
            'Vendor/impl.c': 'int vendor;',
            'App/third_party/lib.c': 'int excluded;',
            'Application/unrelated.c': 'int prefix_collision;',
        }, include_dirs=['App', 'Include', str(self.root/'More')], exclude_dirs=['App/third_party'])
        facts, report = self.extract(cfg)
        names = [v['name'] for v in facts['variables']]
        self.assertEqual(sorted(names), ['header_count', 'header_count', 'own'])
        self.assertFalse(report['coverage']['unlisted_sources'])
        self.assertEqual(len({v['symbol_id'] for v in facts['variables']}), 3)

    def test_dependency_uncertainties_on_target_path_remain(self):
        cfg = self.fixture({'App/main.c': 'int count;void Dispatch(void);void Callback(void){count++;} int main(void){Dispatch();return 0;}',
                            'Vendor/hal.c': 'void Callback(void);void Unknown(void);void Dispatch(void){Unknown();Callback();}'},
                           include_dirs=['App'])
        units, audit = prepare(self.root, cfg)
        facts = merge([Extractor(dict(root=str(self.root),unit=u,config=cfg)).run() for u in units])
        dispatch = next(f['function_id'] for f in facts['functions'] if f['name']=='Dispatch')
        facts['unknowns'].extend([dict(kind='EXTERNAL_CALLEE',file='Vendor/hal.c',line=1,function_id=dispatch),
                                 dict(kind='PARSE_FAILED',file='Vendor/broken.c')])
        report = analyze(facts,cfg,dict(translation_units_failed=1, **audit))
        self.assertTrue(any(f['variable_name']=='EXTERNAL_CALLEE' for f in report['findings']))
        self.assertTrue(any(f['variable_name']=='PARSE_FAILED' for f in report['findings']))
        self.assertEqual(report['analysis_status'],'INCOMPLETE')

    def test_unlisted_user_code_retained_vendor_code_not_missing(self):
        cfg=self.fixture({'App/main.c':'int count;int main(void){return count;}'},include_dirs=['App'],exclude_dirs=['Vendor'])
        (self.root/'App/forgotten.c').write_text('int forgotten;')
        (self.root/'Vendor').mkdir()
        (self.root/'Vendor/not_built.c').write_text('int library;')
        _,audit=prepare(self.root,cfg)
        self.assertEqual(audit['unlisted_sources'],['App/forgotten.c'])

    def test_scope_validation_and_empty_selection_never_reports_complete(self):
        cfg=self.fixture({'App/main.c':'int count;int main(void){return count;}'},include_dirs=['Missing'])
        with self.assertRaisesRegex(ValueError,'排查目录不存在'):
            prepare(self.root,cfg)
        cfg['analysis'].update(include_dirs=['App'],exclude_dirs=['App'])
        facts,report=self.extract(cfg)
        self.assertEqual(facts['variables'],[])
        self.assertEqual(report['analysis_status'],'INCOMPLETE')
        self.assertTrue(any(f['variable_name']=='EMPTY_AUDIT_SCOPE' for f in report['findings']))
        for bad in ('App', ['App/*'], ['']):
            cfg['analysis']['include_dirs']=bad
            self.save(cfg)
            with self.assertRaises(ValueError):load_config(self.root)

    def test_windows_separators_and_sibling_prefix(self):
        (self.root/'App/sub').mkdir(parents=True)
        scope=AuditScope(self.root,dict(include_dirs=['App\\sub'],exclude_dirs=['App/sub/vendor']))
        self.assertTrue(scope.contains('App/sub/a.c'))
        self.assertFalse(scope.contains('App/sub/vendor/a.h'))
        self.assertTrue(scope.contains('App/sub/vendor_extra/a.h'))
        self.assertFalse(scope.contains('App/submarine/a.c'))

    def test_vendor_support_files_mixed_into_user_tree_and_legacy_headers(self):
        cfg = self.fixture({
            'Core/main.c': '#include "Core/legacy.h"\nextern int SystemCoreClock;int own;void Set(int*);'
                           'int main(void){Set(&own);return SystemCoreClock+legacy;}void USART2_IRQHandler(void){own++;}',
            'Core/system.c': 'int SystemCoreClock;void Set(int*p){*p+=1;}',
            'Core/legacy.h': 'static int legacy;',
            'Core/vendor/nested/lib.c': 'int vendor;',
            'Core/vendor_extra/own.c': 'int extra;',
        }, include_dirs=['Core', 'Core/vendor'], exclude_dirs=['Core\\vendor'],
           exclude_files=['Core/system.c'], exclude=['Core/legacy.h'])
        facts, report = self.extract(cfg)
        self.assertEqual(sorted(v['name'] for v in facts['variables']), ['extra', 'own'])
        own = next(v for v in facts['variables'] if v['name'] == 'own')
        self.assertTrue(any(a['file'] == 'Core/system.c' and a['access_kind'] == 'RMW' for a in own['accesses']))
        scope = report['coverage']['audit_scope']
        self.assertEqual(scope['variables_omitted'], 3)
        self.assertEqual(scope['excluded_variable_leaks'], 0)
        self.assertEqual({f['file'] for f in scope['excluded_files']}, {'Core/system.c', 'Core/legacy.h', 'Core/vendor/nested/lib.c'})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        report = json.loads((self.root/'.ecra/reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        self.assertFalse(any(f.get('symbol_id') and f['variable_name'] in {'legacy', 'SystemCoreClock', 'vendor'} for f in report['findings']))

    def test_all_definitions_and_missing_definition_exclusions_win(self):
        (self.root/'App').mkdir()
        scope = AuditScope(self.root, dict(include_dirs=['App'], exclude_dirs=['App/vendor']))
        self.assertFalse(scope.variable(dict(definition_file='App/fallback.c',
            definitions=[dict(file='App/vendor/real.c')], declarations=[dict(file='App/own.h')])) )
        self.assertFalse(scope.variable(dict(declarations=[dict(file='App/own.h'), dict(file='App/vendor/extern.h')])))
        self.assertTrue(scope.variable(dict(definition_file='App/own.c', declarations=[dict(file='App/vendor/extern.h')])))
        scope = AuditScope(self.root, dict(exclude=['App/vendor/*']))
        self.assertFalse(scope.contains('App/vendor/nested/private.h'))
        self.assertTrue(scope.contains('App/vendor_extra/own.h'))

    def test_export_blocks_reintroduced_excluded_variables_and_candidates(self):
        (self.root/'Core').mkdir()
        own = dict(symbol_id='own', definition_file='Core/own.c')
        vendor = dict(symbol_id='vendor', definition_file='Core/system.c')
        report = dict(coverage=dict(project_root=str(self.root), audit_scope=dict(
            include_dirs=['Core'], exclude_files=['Core/system.c'])), findings=[])
        validate_selection(dict(variables=[own]), report)
        with self.assertRaisesRegex(ValueError, '过滤完整性校验失败'):
            validate_selection(dict(variables=[own, vendor]), report)
        report['findings'] = [dict(finding_id='leak', symbol_id='vendor', definition={'file':'Core/system.c'})]
        with self.assertRaisesRegex(ValueError, '过滤完整性校验失败'):
            validate_selection(dict(variables=[own]), report)

    def test_risk_summary_matches_exports_and_stale_answers_do_not_create_patch_plans(self):
        from ecra.report import generate
        cfg = self.fixture({'App/main.c':'int count;void USART2_IRQHandler(void){count++;}int main(void){count++;return 0;}'}, include_dirs=['App'])
        with contextlib.redirect_stdout(io.StringIO()):
            run(self.root, no_review=True)
        out = self.root/'.ecra'
        facts = json.loads((out/'facts.json').read_text(encoding='utf-8'))
        report = json.loads((out/'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        finding = next(f for f in report['findings'] if f.get('symbol_id'))
        self.assertEqual(report['risk_summary']['counts']['likely'], 1)
        self.assertEqual(report['risk_summary']['counts']['confirmed'], 0)
        # Presentation metadata must not invalidate a freshly saved scan.
        self.assertTrue(status(self.root)['resumable'])
        self.assertFalse(status(self.root)['review_enabled'])
        record = dict(finding_id=finding['finding_id'], state='STALE', status='CONFIRMED',
                      answer=dict(reason='OLD_REASON', fix='OLD_FIX', verification='OLD_VERIFY'))
        finding.update(review=record['answer'], status='CONFIRMED')
        generate(out, facts, report, [record])
        self.assertNotIn('review', finding)
        self.assertEqual(finding['status'], 'NEED_OPENCODE_REVIEW')
        self.assertNotIn('OLD_FIX', (out/'reports/opencode_patch_plan.md').read_text(encoding='utf-8'))
        self.assertNotIn('OLD_REASON', (out/'reports/opencode_global_static_review.md').read_text(encoding='utf-8'))
        self.assertIn('与 HTML 一致', (out/'reports/global_static_concurrency.md').read_text(encoding='utf-8'))
        self.assertEqual(report['risk_summary']['counts']['likely'], 1)
        record.update(state='DONE', status='CONFIRMED')
        generate(out, facts, report, [record])
        self.assertEqual(report['risk_summary']['counts']['confirmed'], 1)
        self.assertIn('OLD_FIX', (out/'reports/opencode_patch_plan.md').read_text(encoding='utf-8'))

    def test_external_include_directory_is_audited_and_fingerprinted(self):
        from ecra.cli import file_hashes
        workspace = self.root
        self.root = workspace/'firmware'
        self.root.mkdir()
        external = workspace/'shared code';external.mkdir()
        forgotten = external/'forgotten.c';forgotten.write_text('int shared;')
        cfg=self.fixture({'App/main.c':'int main(void){return 0;}'},include_dirs=['App',str(external)])
        _,audit=prepare(self.root,cfg)
        self.assertIn(forgotten.as_posix(),audit['unlisted_sources'])
        hashes=file_hashes(self.root,self.root/'.ecra',audit_roots=AuditScope(self.root,cfg['analysis']).includes)
        self.assertIn(forgotten.as_posix(),hashes)

    def test_real_pipeline_excludes_vendor_headers_and_invalidates_changed_scope(self):
        cfg=self.fixture({'App/main.c':'int count;void USART2_IRQHandler(void){count++;}int main(void){count++;return 0;}',
                          'Vendor/library.c':'static int private_count;',
                          'Vendor/unused.h':'static int not_in_build;'},include_dirs=['App'],exclude_dirs=['Vendor'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root,no_review=True),2)
        out=self.root/'.ecra'
        facts=json.loads((out/'facts.json').read_text(encoding='utf-8'))
        report=json.loads((out/'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        self.assertEqual([v['name'] for v in facts['variables']],['count'])
        self.assertNotIn('Vendor/unused.h',report['coverage']['unlisted_headers'])
        self.assertNotIn('private_count',(out/'index.html').read_text(encoding='utf-8'))
        self.assertTrue(status(self.root)['resumable'])
        cfg['analysis']['exclude_dirs'].append('App')
        self.save(cfg)
        self.assertFalse(status(self.root)['resumable'])

    def managed(self):
        return dict(analysis=dict(cmake=dict(build_dir='build',generator='Ninja',build_type='Debug',args=['-DBOARD=demo']),
                                 auto_system_includes=False,exclude_dirs=['build']))

    def test_managed_cmake_refreshes_existing_database_and_builds_each_run(self):
        (self.root/'App').mkdir()
        (self.root/'App/main.c').write_text('int main(void){return 0;}')
        build=self.root/'build';build.mkdir()
        database=build/'compile_commands.json'
        database.write_text('[]')  # deliberately stale
        def invoke(argv,**kwargs):
            if '-S' in argv:
                self.assertIn('-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',argv)
                self.assertIn('-DBOARD=demo',argv)
                database.write_text(json.dumps([dict(directory=str(self.root),file='App/main.c',arguments=['cc','-c','App/main.c'])]))
            return subprocess.CompletedProcess(argv,0,'ok','')
        with patch('ecra.compilation.execute',side_effect=invoke) as execute:
            for _ in range(2):
                units,audit=prepare(self.root,self.managed())
                self.assertEqual(len(units),1)
                self.assertEqual([s['stage'] for s in audit['cmake_steps']],['configure','build'])
            self.assertEqual(execute.call_count,4)
        self.assertTrue((self.root/'.ecra/cmake-build.log').is_file())

    def test_managed_failure_stops_before_old_database_is_scanned(self):
        with patch('ecra.compilation.execute',return_value=subprocess.CompletedProcess([],1,'compile error','')) as execute:
            with self.assertRaisesRegex(ValueError,'停止扫描'):
                prepare(self.root,self.managed())
            self.assertEqual(execute.call_count,1)
        cfg=self.managed();cfg['analysis']['compile_database']='wrong/compile_commands.json'
        with patch('ecra.compilation.execute') as execute:
            with self.assertRaisesRegex(ValueError,'不匹配'):prepare(self.root,cfg)
            execute.assert_not_called()

    def test_system_include_probe_preserves_space_paths(self):
        compiler=self.root/'tool chain/arm-none-eabi-gcc.exe'
        compiler.parent.mkdir();compiler.touch()
        include=self.root/'tool chain/include';include.mkdir()
        unit=dict(original_arguments=[str(compiler),'-c','a.c'],arguments=[],directory=str(self.root))
        with patch('ecra.compilation.execute',return_value=subprocess.CompletedProcess([],0,'',
                   '#include <...> search starts here:\n '+str(include)+'\nEnd of search list.\n')) as execute:
            self.assertEqual(system_includes(unit),[str(include)])
            self.assertEqual(execute.call_args.args[0][0],str(compiler))

    def test_cmake_init_generates_baremetal_one_command_config(self):
        (self.root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)')
        (self.root/'Core/Src').mkdir(parents=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['init','--project',str(self.root)]),0)
        cfg,_=load_config(self.root)
        self.assertIn('cmake',cfg['analysis'])
        self.assertEqual(cfg['analysis']['include_dirs'],['.'])
        self.assertTrue(cfg['analysis']['auto_system_includes'])
        self.assertEqual(cfg['contexts'],[dict(id='main',kind='MAIN',functions=['main'])])


if __name__=='__main__':unittest.main()
