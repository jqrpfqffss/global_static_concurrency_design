"""Cross-project onboarding and negative safety cases, using real Clang extraction."""
import contextlib
import io
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_ecra
from ecra.cli import main
from ecra.config import load_config
from ecra.html_report import variable_decisions
from ecra.compilation import normalize, system_include_args


class EntryAndSafetyTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def test_addressed_callback_through_cross_tu_wrappers_and_dispatch(self):
        cfg = self.project({
            'app.c': '''typedef void (*CB)(void); void Register(CB); void Dispatch(void);
                static int count; static void Consume(void){count++;}
                static void Complete(void){Consume();}
                void main(void){Register(&Complete); Consume();}
                void USART1_IRQHandler(void){Dispatch();}''',
            'bsp.c': '''typedef void (*CB)(void); static CB slot;
                static void Set(CB cb){slot=cb;}
                static void Forward(CB cb){Set(cb);}
                void Register(CB cb){Forward(cb);}
                void Dispatch(void){(*slot)();}'''
        }, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, report = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name'] == 'count')
        self.assertEqual(len(count['writers']), 2)
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Complete' for c in facts['calls']))
        self.assertTrue(any('GS-MULTI-WRITER' in f['rules'] for f in report['findings'] if f.get('symbol_id') == count['symbol_id']))

    def test_out_of_order_designated_callback_table(self):
        cfg = self.project({'a.c': '''
            static int count; static void Complete(void){count++;}
            struct Ops {int tag; void (*callback)(void);};
            static struct Ops ops={.callback=&Complete,.tag=7};
            void main(void){Complete();}
            void TIM2_IRQHandler(void){ops.callback();}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(len(count['writers']), 2)

    def test_nvic_setvector_through_wrapped_integer_cast(self):
        cfg = self.project({'a.c': '''
            void NVIC_SetVector(int, unsigned);
            static int count; static void ActualVector(void){count++;}
            void install(void (*cb)(void)){NVIC_SetVector(5,(unsigned)cb);}
            void main(void){install(&ActualVector); count++;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(len(count['writers']), 2)
        self.assertTrue(any(c['kind']=='ISR' for c in facts['contexts']))

    def test_known_main_path_does_not_hide_escaped_callback(self):
        cfg = self.project({'a.c': '''
            void vendor_register(void (*)(void));
            static int count; static void Update(void){count++;}
            static void Callback(void){Update();}
            void main(void){Update();vendor_register(Callback);}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(count['writers'], ['main'])
        self.assertEqual(count['audit_status'], 'REVIEW_REQUIRED')
        self.assertIn('FUNCTION_ADDRESS', count['screening_blockers'])

    def test_one_write_site_shared_by_two_irqs_still_conflicts(self):
        cfg = self.project({'a.c': '''
            static int written; static void Write(void){written=1;}
            void TIM2_IRQHandler(void){Write();}
            void TIM3_IRQHandler(void){Write();}
            int main(void){return 0;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, report = self.extract(cfg)
        written = next(v for v in facts['variables'] if v['name']=='written')
        self.assertNotEqual(written['audit_status'], 'SCREENED_NO_CONCURRENCY_RISK')
        self.assertTrue(any('GS-MULTI-WRITER' in f['rules'] for f in report['findings']))

    def test_grouped_registration_keeps_reentrancy_and_multiple_matching_contexts(self):
        cfg = self.project({'a.c': '''
            void InstallA(void (*)(void)); void InstallB(void (*)(void));
            static int count; void A(void){count++;} void B(void){count++;}
            void main(void){InstallA(A);InstallB(B);}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        cfg['entry_registrations'] = [dict(api='InstallA',callback_arg=0,kind='CALLBACK',context_id='callbacks',may_repeat=False),
                                      dict(api='InstallB',callback_arg=0,kind='CALLBACK',context_id='callbacks',may_repeat=True)]
        facts, report = self.extract(cfg)
        self.assertTrue(next(c for c in facts['contexts'] if c['id']=='callbacks')['reentrant'])
        self.assertTrue(any('GS-MULTI-WRITER' in f['rules'] for f in report['findings']))

    def test_unrelated_bad_registration_is_visible_without_tainting_private_variable(self):
        cfg = self.project({'a.c': '''
            void Install(void (*)(void)); static int count;
            void main(void){Install((void (*)(void))0x1000); count++;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        cfg['entry_registrations'] = [dict(api='Install',callback_arg=0,kind='ISR'),
                                      dict(api='TypoInstall',callback_arg=1,kind='ISR')]
        facts, _ = self.extract(cfg)
        self.assertTrue({'UNRESOLVED_REGISTERED_ENTRY','UNMATCHED_ENTRY_REGISTRATION'} <= {u['kind'] for u in facts['unknowns']})
        count = next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(count['static_classification'], 'SAFE')
        self.assertEqual(count['safe_reason_code'], 'SAFE_SINGLE_FOREGROUND')
        self.assertEqual(count['screening_blockers'], [])

    def test_overlapping_registration_cannot_erase_reentrancy(self):
        cfg = self.project({'a.c': 'void Install(void (*)(void)); static int count; void A(void){count++;} void main(void){Install(A);}'},
                           contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        cfg['entry_registrations'] = [dict(api=api,callback_arg=0,kind='CALLBACK',context_id='callbacks',may_repeat=repeat)
                                      for api,repeat in [('Install',False),('Install*',True)]]
        facts, _ = self.extract(cfg)
        self.assertTrue(next(c for c in facts['contexts'] if c['id']=='callbacks')['reentrant'])
        self.assertIn('AMBIGUOUS_ENTRY_REGISTRATION', {u['kind'] for u in facts['unknowns']})

    def test_unselected_translation_unit_does_not_add_a_runtime_writer(self):
        cfg = self.project({'a.c': 'int shared; int main(void){return shared;}'},
                           contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        (self.root/'missing.c').write_text('extern int shared; void TIM2_IRQHandler(void){shared=1;}',encoding='utf-8')
        facts, _ = self.extract(cfg)
        shared = next(v for v in facts['variables'] if v['name']=='shared')
        self.assertNotIn('SOURCE_NOT_IN_DATABASE', shared['screening_blockers'])
        self.assertEqual(shared['static_classification'], 'SAFE')
        self.assertEqual(shared['safe_reason_code'], 'SAFE_READ_ONLY')
        self.assertEqual(shared['writers'], [])

    def test_explicit_serial_context_with_multiple_roots_is_not_reentrant(self):
        cfg = self.project({'a.c':'static int count; void A(void){count++;} void B(void){count++;}'},
                           contexts=[dict(id='serial_irq',kind='ISR',functions=['A','B'])])
        facts, _ = self.extract(cfg)
        self.assertFalse(facts['contexts'][0]['reentrant'])
        self.assertEqual(facts['variables'][0]['audit_status'], 'SCREENED_NO_CONCURRENCY_RISK')


class ProjectPortabilityTests(unittest.TestCase):
    def test_gcc_private_headers_are_fallback_not_runtime_overrides(self):
        private = self.base/'compiler/include'
        runtime = self.base/'runtime/include'
        private.mkdir(parents=True)
        runtime.mkdir(parents=True)
        for name in ('stddef.h','stdarg.h'):
            (private/name).write_text('/* compiler intrinsic */',encoding='utf-8')
        self.assertEqual(system_include_args([str(private),str(runtime)]),
                         ['-idirafter',str(private),'-isystem',str(runtime)])

    def test_expected_macro_values_follow_definition_and_undefinition_order(self):
        root = Path.cwd()
        def missing(arguments, expected):
            return normalize(dict(directory=str(root),file='app.c',arguments=['clang',*arguments,'-c','app.c']),
                             root, dict(expected_defines=expected))['missing_defines']
        self.assertEqual(missing(['-DAPP_RTOS=0','-D','CORE_CM7'], ['APP_RTOS=0','CORE_CM7=1']), [])
        self.assertEqual(missing(['-DAPP_RTOS=1'], ['APP_RTOS=0']), ['APP_RTOS=0'])
        self.assertEqual(missing(['-DCORE_CM7','-U','CORE_CM7'], ['CORE_CM7']), ['CORE_CM7'])
        self.assertEqual(missing(['-DAPP_RTOS=1','-UAPP_RTOS','-DAPP_RTOS=0'], ['APP_RTOS=0']), [])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra portability ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        original = Path.cwd()
        self.addCleanup(lambda: os.chdir(original))
        semantics = self.base/'tool/config/semantics.yaml'
        for target in ('ecra.config.SEMANTICS_FILE', 'ecra.cli.SEMANTICS_FILE'):
            mocked = patch(target, semantics)
            mocked.start()
            self.addCleanup(mocked.stop)

    def invoke(self, *args):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            code = main(list(args))
        return code

    def board(self, name, cpu='cortex-m3'):
        root = self.base/name
        (root/'User/DriversCustom').mkdir(parents=True)
        (root/'Debug').mkdir()
        source = root/'User/DriversCustom/app.c'
        source.write_text('static int read_only; static int count; int main(void){count++;return read_only;} void TIM2_IRQHandler(void){count++;}',encoding='utf-8')
        (root/'Debug/compile_commands.json').write_text(json.dumps([dict(directory=str(root),file=str(source),
            arguments=['arm-none-eabi-gcc','-mcpu='+cpu,'-mthumb','-c',str(source)])]),encoding='utf-8')
        return root

    def select(self, root):
        from ecra.config import SEMANTICS_FILE
        SEMANTICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEMANTICS_FILE.write_text(json.dumps(dict(
            version=1, project=dict(root=str(root)),
            analysis=dict(compile_database='Debug/compile_commands.json', include_dirs=['.'],
                          exclude_dirs=['build', '.ecra']),
            contexts=[dict(id='main', kind='MAIN', functions=['main'])],
            review=dict(enabled=False))), encoding='utf-8')

    def test_four_cortex_projects_are_selected_one_at_a_time_by_one_config(self):
        for cpu in ('cortex-m0','cortex-m3','cortex-m4','cortex-m7'):
            with self.subTest(cpu=cpu):
                root = self.board(cpu, cpu)
                self.select(root)
                cfg,path=load_config()
                self.assertFalse(cfg['review']['enabled'])
                self.assertEqual(cfg['analysis']['include_dirs'],['.'])
                self.assertFalse((root/'.ecra/semantics.yaml').exists())
                self.assertEqual(self.invoke('--no-review'),2,self.stderr.getvalue())
                out=root/'.ecra'
                facts=json.loads((out/'facts.json').read_text(encoding='utf-8'))
                variables={v['name']:v for v in facts['variables']}
                self.assertEqual(variables['read_only']['audit_status'],'SCREENED_NO_CONCURRENCY_RISK')
                self.assertEqual(len(variables['count']['writers']),2)
                html=(out/'index.html').read_text(encoding='utf-8')
                self.assertIn('href="#inventory" data-decision-filter="screened_safe"',html)
                self.assertEqual(self.invoke('status','--json'),0)
                self.assertTrue(json.loads(self.stdout.getvalue())['resumable'])
                self.assertEqual(self.invoke('report'),2,self.stderr.getvalue())

    def test_switching_project_reuses_the_same_semantics_file(self):
        roots=[self.board('customer-a/Board'),self.board('customer-b/Board')]
        self.select(roots[0])
        first = load_config()[1]
        self.select(roots[1])
        self.assertEqual(load_config()[1], first)
        self.assertEqual(load_config()[0]['project']['root'], str(roots[1]))

    def test_duplicate_yaml_keys_and_broken_yaml_are_actionable(self):
        root=self.board('board')
        cfg=root/'bad.yaml'
        for content in ('version: 1\nanalysis: {}\nanalysis: {}', 'version: 1\nanalysis: ['):
            cfg.write_text(content,encoding='utf-8')
            self.assertEqual(self.invoke('doctor','--project',str(root),'--config',str(cfg)),3)
            self.assertIn('YAML',self.stderr.getvalue())
            self.assertNotIn('Traceback',self.stderr.getvalue())

    def test_init_creates_one_config_without_modifying_legacy_semantics(self):
        root=self.board('legacy')
        (root/'.ecra').mkdir()
        legacy=root/'.ecra/semantics.yaml'
        legacy.write_text('version: 1\nanalysis:\n  compile_database: Debug/compile_commands.json\n  extra_args: [-DFEATURE=42]\nreview:\n  enabled: false\n',encoding='utf-8')
        original=legacy.read_bytes()
        self.assertEqual(self.invoke('init','--project',str(root)),0,self.stderr.getvalue())
        cfg,path=load_config()
        self.assertNotEqual(path,legacy)
        self.assertEqual(cfg['project']['root'],str(root))
        self.assertEqual(legacy.read_bytes(),original)

    def test_multiple_debug_release_databases_require_selection(self):
        root=self.board('ambiguous')
        (root/'Release').mkdir()
        (root/'Release/compile_commands.json').write_bytes((root/'Debug/compile_commands.json').read_bytes())
        self.assertEqual(self.invoke('init','--project',str(root)),0)
        self.assertEqual(self.invoke('doctor'),3)
        self.assertIn('多个编译数据库',self.stdout.getvalue())

    def test_existing_findings_override_screened_label(self):
        facts=dict(variables=[dict(symbol_id='x',audit_status='SCREENED_NO_CONCURRENCY_RISK')])
        report=dict(findings=[dict(symbol_id='x',finding_id='GS-x',rules=['GS-MULTI-WRITER'])])
        self.assertEqual(variable_decisions(facts,report,{}),{'x':'likely'})

    @unittest.skipUnless(shutil.which('cmake') and shutil.which('ninja') and shutil.which('arm-none-eabi-gcc'),
                         'requires CMake, Ninja and Arm GCC')
    def test_fresh_cmake_project_auto_toolchain_builds_real_arm_object(self):
        root=self.board('cmake-board','cortex-m4')
        (root/'User/DriversCustom/app.c').write_text('''#include <stdint.h>
#include <stdatomic.h>
static atomic_uint count;
int main(void){atomic_fetch_add_explicit(&count, 1, memory_order_relaxed);return 0;}
void TIM2_IRQHandler(void){atomic_store_explicit(&count, 2, memory_order_release);}
''',encoding='utf-8')
        (root/'cmake').mkdir()
        (root/'cmake/gcc-arm-none-eabi.cmake').write_text('''set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
''',encoding='utf-8')
        (root/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(portable_board C)
add_library(firmware OBJECT User/DriversCustom/app.c)
target_compile_options(firmware PRIVATE -mcpu=cortex-m4 -mthumb)
''',encoding='utf-8')
        self.assertEqual(self.invoke('init','--project',str(root)),0,self.stderr.getvalue())
        cfg,_=load_config()
        self.assertEqual(cfg['analysis']['cmake']['toolchain_file'],'cmake/gcc-arm-none-eabi.cmake')
        self.assertEqual(self.invoke(),2,self.stdout.getvalue()+self.stderr.getvalue())
        report=json.loads((root/'.ecra/reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        self.assertEqual(report['coverage']['translation_units_failed'],0)
        objects=[p for p in (root/'build/ecra').rglob('app.c.*') if p.suffix in {'.o','.obj'}]
        self.assertEqual(len(objects),1)
        header=objects[0].read_bytes()[:20]
        self.assertEqual(header[:4],b'\x7fELF')
        self.assertEqual(int.from_bytes(header[18:20],'little'),40)  # EM_ARM, not host x86
        self.assertEqual(self.invoke('report'),2,self.stderr.getvalue())

    def test_invalid_registration_context_kind_is_rejected_before_scan(self):
        root=self.board('bad-registration')
        config=root/'bad.yaml'
        config.write_text('''version: 1
contexts: [{id: irq, kind: ISR}]
entry_registrations: [{api: Install, callback_arg: 0, kind: TASK, context_id: irq}]
''',encoding='utf-8')
        self.assertEqual(self.invoke('doctor','--project',str(root),'--config',str(config)),3)
        self.assertIn('类型冲突',self.stderr.getvalue())
