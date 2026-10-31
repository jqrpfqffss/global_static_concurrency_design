"""Regression cases for the real-project classification repair."""
import json
from pathlib import Path
from unittest import TestCase, mock

from ecra.analysis import analyze, merge
from ecra.compilation import normalize, prepare
from ecra.cli import run
from ecra.extract import Extractor
from ecra.initialization import prove_initialization
from tests.test_ecra import ProjectTest


class RealClassificationRepairTests(TestCase):
    setUp = ProjectTest.setUp
    project = ProjectTest.project
    extract = ProjectTest.extract

    def test_gcc_build_stage_flags_are_removed_without_losing_abi_inputs(self):
        source = self.root / 'main.c'
        source.write_text('int main(void) { return 0; }', encoding='utf-8')
        raw = ['arm-none-eabi-gcc', '-mthumb-interwork', '-mapcs-frame',
               '-mlong-calls', '-mword-relocations', '-Wl,--gc-sections',
               '-Wa,-mimplicit-it=thumb', '--specs=nano.specs', '-Xlinker', '--gc-sections',
               '-Xassembler', '-mimplicit-it=thumb', '-MF', 'main.d', '-MT', 'main.o',
               '-mcpu=cortex-m7', '-mthumb', '-DSTM32H747xx', '-I', str(self.root),
               '-c', 'main.c', '-o', 'main.o']
        unit = normalize(dict(file='main.c', directory=str(self.root), arguments=raw),
                         self.root, {})
        kept = unit['arguments']
        for flag in ('-mcpu=cortex-m7', '-mthumb', '-DSTM32H747xx', '-I'):
            self.assertIn(flag, kept)
        for flag in ('-mthumb-interwork', '-mapcs-frame', '-mlong-calls',
                     '-mword-relocations', '-Wl,--gc-sections', '--specs=nano.specs',
                     '-Xlinker', '-MF', '-c'):
            self.assertNotIn(flag, kept)
        cfg = dict(analysis={}, contexts=[], entry_registrations=[])
        part = Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run()
        self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])

    def test_nonfatal_error_diagnostic_is_partial_with_ast(self):
        cfg = self.project({'a.c': '#error deliberate diagnostic\nstatic int value; int main(void) { value = 1; return value; }'},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        units, audit = prepare(self.root, cfg)
        part = Extractor(dict(root=str(self.root), unit=units[0], config=cfg)).run()
        self.assertEqual(part['parse_status'], 'PARTIAL')
        self.assertTrue(any(row['name'] == 'main' for row in part['functions']))
        facts = merge([part])
        analyze(facts, cfg, dict(translation_units_failed=0, **audit))
        value = next(row for row in facts['variables'] if row['name'] == 'value')
        self.assertNotEqual(value['static_classification'], 'UNKNOWN')

    def test_partial_parse_gap_is_local_to_referenced_variable(self):
        cfg = self.project({'a.c': '''static int affected, independent;
            static void bad(void) { affected = 1; undefined_token; }
            int main(void) { bad(); independent = 2; return independent; }'''},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        units, audit = prepare(self.root, cfg)
        part = Extractor(dict(root=str(self.root), unit=units[0], config=cfg)).run()
        self.assertEqual(part['parse_status'], 'PARTIAL')
        facts = merge([part])
        analyze(facts, cfg, dict(translation_units_failed=0, **audit))
        affected = next(row for row in facts['variables'] if row['name'] == 'affected')
        independent = next(row for row in facts['variables'] if row['name'] == 'independent')
        self.assertIn('UNKNOWN_RELEVANT_PARTIAL_TU', affected['unknown_reason_codes'])
        self.assertNotIn('UNKNOWN_RELEVANT_PARTIAL_TU', independent['unknown_reason_codes'])

    def test_cli_partial_tu_does_not_become_missing_tu(self):
        self.project({'a.c': '''static int affected, independent;
            static void bad(void) { affected = 1; undefined_token; }
            int main(void) { bad(); independent = 2; return independent; }'''},
            contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        run(self.root, no_review=True)
        output = self.root / '.ecra'
        facts = json.loads((output / 'facts.json').read_text(encoding='utf-8'))
        report = json.loads((output / 'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        self.assertEqual(report['coverage']['translation_units_partial'], 1)
        self.assertEqual(report['coverage']['translation_units_failed'], 0)
        self.assertFalse(any(row['kind'] == 'PARSE_FAILED' for row in facts['unknowns']))
        independent = next(row for row in facts['variables'] if row['name'] == 'independent')
        self.assertEqual(independent['static_classification'], 'SAFE_PROVEN')

    def test_missing_required_header_remains_failed(self):
        cfg = self.project({'a.c': '#include "absent_required_header.h"\n'
                                  'static int value; int main(void) { value++; return value; }'},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        units, _ = prepare(self.root, cfg)
        part = Extractor(dict(root=str(self.root), unit=units[0], config=cfg)).run()
        self.assertEqual(part['parse_status'], 'FAILED')

    def test_missing_printing_policy_does_not_abort_main(self):
        cfg = self.project({'a.c': '__attribute__((section(".my_data"))) static int value; '
                                  'int main(void) { value = 1; return value; }'},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        units, _ = prepare(self.root, cfg)
        from clang import cindex
        with mock.patch.object(cindex, 'PrintingPolicy', None, create=True):
            part = Extractor(dict(root=str(self.root), unit=units[0], config=cfg)).run()
        self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
        self.assertTrue(any(row['name'] == 'main' for row in part['functions']))
        self.assertEqual(part['variables'][0].get('linker_section'), '.my_data')

    def test_foreground_helper_and_cli_table_inherit_one_executor(self):
        cfg = self.project({'a.c': '''
            typedef void (*Handler)(void);
            typedef struct { const char *name; Handler handler; } Cmd;
            static int value;
            static void CmdStart(void) { value = 1; }
            static void CmdStop(void) { value = 0; }
            static const Cmd table[] = {{"start", CmdStart}, {"stop", CmdStop}};
            static void CLI_Process(unsigned index) { table[index].handler(); }
            int main(void) { for (;;) { CLI_Process(0); (void)value; } }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        value = next(row for row in facts['variables'] if row['name'] == 'value')
        self.assertEqual(value['static_classification'], 'SAFE_PROVEN')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_FOREGROUND')
        handler = next(row for row in facts['functions'] if row['name'] == 'CmdStart')
        bindings = [row for row in facts['context_bindings'] if row['function_id'] == handler['function_id']]
        self.assertTrue(bindings)
        self.assertTrue(all(next(c for c in facts['contexts'] if c['id'] == b['context_id'])['physical_id'] == 'FOREGROUND'
                            for b in bindings))

    def test_configured_async_registration_creates_an_irq_executor(self):
        cfg = self.project({'a.c': '''typedef void (*CB)(void); void RegisterCallback(CB);
            static int value; static void callback(void) { value++; }
            int main(void) { RegisterCallback(callback); return 0; }'''},
            contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        cfg['entry_registrations'] = [dict(api='RegisterCallback', callback_arg=0,
                                           kind='ISR', context_id='registered_irq')]
        facts, _ = self.extract(cfg)
        callback = next(row for row in facts['functions'] if row['name'] == 'callback')
        bindings = [row for row in facts['context_bindings'] if row['function_id'] == callback['function_id']]
        self.assertTrue(any(next(c for c in facts['contexts'] if c['id'] == b['context_id'])['physical_kind'] == 'IRQ'
                            for b in bindings))

    def test_reset_vector_allows_multilevel_init_without_explicit_disable(self):
        cfg = self.project({'a.c': '''enum { TIM4_IRQn = 30 }; void NVIC_EnableIRQ(int);
            static int config; static void C(void) { config = 4; }
            static void B(void) { C(); } static void A(void) { B(); }
            void TIM4_IRQHandler(void) { (void)config; }
            int main(void) { A(); NVIC_EnableIRQ(TIM4_IRQn); for (;;) {} }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        main = next(row for row in facts['functions'] if row['name'] == 'main')
        reset = 'assembly:verified-reset'
        facts['vector_entries'].append(dict(function_id=reset, kind='MAIN', slot=1))
        facts['calls'].append(dict(caller_function_id=reset, callee_function_id=main['function_id'],
                                   call_kind='ASSEMBLY_LITERAL_CALL'))
        variable = next(row for row in facts['variables'] if row['name'] == 'config')
        contexts = {row['id']: row for row in facts['contexts']}
        self.assertIsNotNone(prove_initialization(variable, variable['accesses'], facts, contexts, cfg))

    def test_write_after_enable_cannot_be_reclassified_as_init(self):
        cfg = self.project({'a.c': '''enum { TIM4_IRQn = 30 }; void NVIC_EnableIRQ(int);
            static int config; static void C(void) { config = 4; }
            void TIM4_IRQHandler(void) { (void)config; }
            int main(void) { C(); NVIC_EnableIRQ(TIM4_IRQn); C(); }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        main = next(row for row in facts['functions'] if row['name'] == 'main')
        reset = 'assembly:verified-reset'
        facts['vector_entries'].append(dict(function_id=reset, kind='MAIN', slot=1))
        facts['calls'].append(dict(caller_function_id=reset, callee_function_id=main['function_id'],
                                   call_kind='ASSEMBLY_LITERAL_CALL'))
        variable = next(row for row in facts['variables'] if row['name'] == 'config')
        self.assertIsNone(prove_initialization(variable, variable['accesses'], facts,
            {row['id']: row for row in facts['contexts']}, cfg))

    def test_unknown_pre_main_constructor_blocks_init_proof(self):
        cfg = self.project({'a.c': '''enum { TIM4_IRQn = 30 }; void NVIC_EnableIRQ(int);
            static int config; void TIM4_IRQHandler(void) { (void)config; }
            int main(void) { config = 4; NVIC_EnableIRQ(TIM4_IRQn); }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        cfg['project']['root'] = str(self.root)
        cfg['analysis']['cmake'] = dict(build_dir='build/manual', location='project')
        (self.root / 'startup.s').write_text('Reset_Handler:\n bl __libc_init_array\n bl main\n',
                                              encoding='utf-8')
        build = self.root / 'build/manual'
        build.mkdir(parents=True)
        (build / 'firmware.map').write_text('''.preinit_array 0x08000000 0x0
.init_array 0x08000000 0x4
 .init_array 0x08000000 0x4 custom.o
''', encoding='utf-8')
        main = next(row for row in facts['functions'] if row['name'] == 'main')
        reset = 'assembly:reset'
        facts['vector_entries'].append(dict(function_id=reset, kind='MAIN', slot=1,
                                            file='startup.s'))
        facts['calls'].append(dict(caller_function_id=reset, callee_function_id=main['function_id'],
                                   call_kind='ASSEMBLY_LITERAL_CALL'))
        variable = next(row for row in facts['variables'] if row['name'] == 'config')
        self.assertIsNone(prove_initialization(variable, variable['accesses'], facts,
            {row['id']: row for row in facts['contexts']}, cfg))

    def test_custom_async_enable_uses_configured_irq_argument(self):
        cfg = self.project({'a.c': '''enum { TIM4_IRQn = 30 };
            void NVIC_DisableIRQ(int); void StartIRQ(int, int);
            static int config; void TIM4_IRQHandler(void) { (void)config; }
            int main(void) { NVIC_DisableIRQ(TIM4_IRQn); config = 4;
                             StartIRQ(0, TIM4_IRQn); }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        cfg['async_enable'] = [dict(api='StartIRQ', irq_arg=1)]
        facts, _ = self.extract(cfg)
        variable = next(row for row in facts['variables'] if row['name'] == 'config')
        proof = prove_initialization(variable, variable['accesses'], facts,
                                     {row['id']: row for row in facts['contexts']}, cfg)
        self.assertIsNotNone(proof)
        self.assertTrue(any(event['api_name'] == 'StartIRQ'
                            for barrier in proof['irq_barriers'] for event in barrier['enables']))

    def test_hal_handle_instance_branch_prunes_unrelated_irq_instance(self):
        cfg = self.project({'a.c': '''
            typedef struct { int *Instance; } Handle;
            static int tim3, tim4; static Handle h3 = {&tim3}, h4 = {&tim4};
            static int value;
            void HAL_TIM_PeriodElapsedCallback(Handle *h) {
                if (h->Instance == &tim3) value++;
            }
            void HAL_TIM_IRQHandler(Handle *h) { HAL_TIM_PeriodElapsedCallback(h); }
            void TIM3_IRQHandler(void) { HAL_TIM_IRQHandler(&h3); }
            void TIM4_IRQHandler(void) { HAL_TIM_IRQHandler(&h4); }
            int main(void) { return 0; }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        value = next(row for row in facts['variables'] if row['name'] == 'value')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_IRQ')
        self.assertFalse(any(pair.get('may_concurrent') and pair.get('has_write_conflict')
                             for pair in value['conflict_pairs']))
        self.assertTrue(any(access.get('context_exclusions') for access in value['accesses']))

    def test_two_real_irq_instances_keep_same_source_write_conflict(self):
        cfg = self.project({'a.c': '''
            static int value;
            static void callback(void) { value++; }
            void TIM3_IRQHandler(void) { callback(); }
            void TIM4_IRQHandler(void) { callback(); }
            int main(void) { return 0; }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        value = next(row for row in facts['variables'] if row['name'] == 'value')
        self.assertEqual(value['static_classification'], 'SUSPECT')
        self.assertTrue(any(pair.get('may_concurrent') and pair.get('has_write_conflict')
                            and pair['participant_a']['access_id'] == pair['participant_b']['access_id']
                            and pair['participant_a']['context_id'] != pair['participant_b']['context_id']
                            for pair in value['conflict_pairs']))

    def test_strong_hal_callback_replaces_macro_weak_definition(self):
        cfg = self.project({
            'weak.c': '''#define __weak __attribute__((weak))
                extern int value; __weak void HAL_MspInit(void) { value++; }''',
            'app.c': '''int value; void HAL_MspInit(void) { value = 2; }
                int main(void) { HAL_MspInit(); return value; }'''
        }, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        definitions = [row for row in facts['functions'] if row['name'] == 'HAL_MspInit']
        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0]['file'], 'app.c')
        value = next(row for row in facts['variables'] if row['name'] == 'value')
        self.assertFalse(any(access['file'] == 'weak.c' for access in value['accesses']))
