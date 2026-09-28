"""Generic call/alias recovery, independent of project and classifier policy."""
import unittest

from tests import test_ecra as fixtures
from ecra.analysis import merge, context_graph
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.points_to import enrich


class ResolutionTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project

    def facts(self, sources):
        cfg = self.project(sources, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        units, _ = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run() for unit in units]
        for part in parts:
            self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
        facts = merge(parts)
        enrich(facts, cfg)
        return facts, cfg

    def test_const_struct_table_dynamic_dispatch_inherits_foreground(self):
        facts, cfg = self.facts({'a.c': '''
            static int value;
            static void A(void) { value++; }
            static void B(void) { value = 2; }
            typedef struct { unsigned tag; void (*run)(void); } Task;
            static const Task tasks[] = {{.run = A, .tag = 1}, {.tag = 2, .run = B}};
            static void Dispatch(unsigned i) { tasks[i].run(); }
            int main(void) { Dispatch(0); Dispatch(1); return value; }
        '''})
        targets = {call['callee_name'] for call in facts['calls'] if call['call_kind'] == 'INDIRECT_RESOLVED'}
        self.assertEqual(targets, {'A', 'B'})
        self.assertFalse(any(issue['kind'] in {'INDIRECT_CALL', 'FUNCTION_ADDRESS'} for issue in facts['unknowns']))
        _, paths, _ = context_graph(facts, cfg)
        for function in facts['functions']:
            if function['name'] in {'A', 'B'}:
                self.assertEqual(len(paths[function['function_id']]), 1)

    def test_constant_function_array_selects_only_its_element(self):
        facts, _ = self.facts({'a.c': '''
            static void A(void) {} static void B(void) {}
            static void (*const routes[])(void) = {A, B};
            int main(void) { routes[0](); return 0; }
        '''})
        self.assertEqual([c['callee_name'] for c in facts['calls'] if c['call_kind'] == 'INDIRECT_RESOLVED'], ['A'])

    def test_callback_registration_wrappers_preserve_irq_caller(self):
        facts, cfg = self.facts({'a.c': '''
            typedef void (*CB)(void); void Install(CB); void Dispatch(void);
            static int value; static void Callback(void) { value++; }
            int main(void) { Install(Callback); return 0; }
            void USART1_IRQHandler(void) { Dispatch(); }
        ''', 'b.c': '''
            typedef void (*CB)(void); static CB callback;
            static void Set(CB cb) { callback = cb; }
            void Install(CB cb) { Set(cb); }
            void Dispatch(void) { callback(); }
        '''})
        _, paths, _ = context_graph(facts, cfg)
        callback = next(f for f in facts['functions'] if f['name'] == 'Callback')
        self.assertEqual(len(paths[callback['function_id']]), 1)
        self.assertTrue(all('USART1' in cid or cid.startswith('IRQ:') for cid in paths[callback['function_id']]))
        self.assertEqual(facts['address_escapes'], [])

    def test_strong_override_removes_weak_body_independent_of_tu_order(self):
        for ordering in (False, True):
            with self.subTest(ordering=ordering):
                weak = ('weak.c', '''
                    int obsolete; __attribute__((weak)) void Hook(void) { obsolete++; }
                    void IRQDispatch(void) { Hook(); }
                ''')
                strong = ('strong.c', '''
                    int actual; void Hook(void) { actual++; }
                    void IRQDispatch(void); void USART1_IRQHandler(void) { IRQDispatch(); }
                    int main(void) { return 0; }
                ''')
                facts, _ = self.facts(dict([weak, strong] if ordering else [strong, weak]))
                hook = next(f for f in facts['functions'] if f['name'] == 'Hook')
                self.assertEqual(hook['file'], 'strong.c')
                self.assertFalse(hook['is_weak'])
                obsolete = next(v for v in facts['variables'] if v['name'] == 'obsolete')
                self.assertFalse(any(a['symbol_id'] == obsolete['symbol_id'] for a in facts['accesses']))

    def test_local_address_is_not_an_escape_but_opaque_argument_is(self):
        facts, _ = self.facts({'a.c': '''
            static int local_target, escaped_target; void External(int *);
            int main(void) { int *p = &local_target; *p = 1; External(&escaped_target); return *p; }
        '''})
        by_id = {v['symbol_id']: v['name'] for v in facts['variables']}
        self.assertEqual({by_id[e['symbol_id']] for e in facts['address_escapes'] if e.get('symbol_id')}, {'escaped_target'})

    def test_partial_function_pointer_resolution_keeps_indirect_gap(self):
        facts, _ = self.facts({'a.c': '''
            typedef void (*CB)(void); CB Opaque(void);
            static int value; static void Known(void) { value++; }
            int main(void) { CB cb = Known; cb = Opaque(); cb(); return 0; }
        '''})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Known' for c in facts['calls']))
        self.assertTrue(any(u['kind'] == 'INDIRECT_CALL' for u in facts['unknowns']))
        call = next(c for c in facts['semantic_calls'] if not c['target'])
        self.assertEqual(call['target_coverage'], 'PARTIAL')

    def test_mixed_known_and_opaque_pointee_retains_variable_local_gap(self):
        facts, _ = self.facts({'a.c': '''
            static int value, unrelated; int *Opaque(void);
            int main(void) { int *p = &value; p = Opaque(); *p = 1; unrelated++; return 0; }
        '''})
        value = next(v for v in facts['variables'] if v['name'] == 'value')
        unrelated = next(v for v in facts['variables'] if v['name'] == 'unrelated')
        gaps = [u for u in facts['unknowns'] if u['kind'] == 'UNRESOLVED_POINTEE']
        self.assertTrue(any(u.get('symbol_id') == value['symbol_id'] for u in gaps))
        self.assertFalse(any(u.get('symbol_id') == unrelated['symbol_id'] for u in gaps))

    def test_generic_linker_section_registration_is_recovered(self):
        facts, _ = self.facts({'a.c': '''
            typedef struct { void (*run)(void); } Entry;
            static int value; static void Work(void) { value++; }
            #define REGISTER(fn) static const Entry item __attribute__((section("hooks"), used)) = {.run=fn}
            REGISTER(Work);
            extern const Entry __start_hooks[], __stop_hooks[];
            int main(void) { for (const Entry *p=__start_hooks; p<__stop_hooks; ++p) p->run(); return 0; }
        '''})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Work' for c in facts['calls']))

    def test_pointer_offset_targets_correct_array_element(self):
        facts, _ = self.facts({'a.c': '''
            static int values[3];
            int main(void) { int *p = &values[0]; *(p + 1) = 9; return 0; }
        '''})
        accesses = [a for a in facts['accesses'] if a.get('via_alias') == 'interprocedural points-to'
                    and a['access_kind'] == 'WRITE']
        self.assertTrue(any(a['access_path'] == '/[1]' for a in accesses), accesses)

    def test_pointer_iteration_widens_without_losing_unknown_index(self):
        facts, _ = self.facts({'a.c': '''
            static int values[3];
            int main(void) { for (int *p = values; p < values + 3; ++p) *p = 9; return 0; }
        '''})
        self.assertFalse(any(u['kind'] == 'POINTS_TO_LIMIT' for u in facts['unknowns']))
        self.assertTrue(any(a['access_path'] == '/[*]' and a['access_kind'] == 'WRITE'
                            for a in facts['accesses']))

    def test_distinct_dma_calls_do_not_share_one_hardware_executor(self):
        facts, _ = self.facts({'a.c': '''
            int HAL_UART_Receive_DMA(void *, unsigned char *, unsigned);
            static unsigned char a[4], b[4];
            int main(void) { HAL_UART_Receive_DMA((void *)1,a,4); HAL_UART_Receive_DMA((void *)2,b,4); return 0; }
        '''})
        self.assertEqual(len({c['id'] for c in facts['hardware_contexts']}), 2)

    def test_inline_assembly_gaps_bind_to_named_storage_and_pointer_operands(self):
        facts, _ = self.facts({'a.c': '''
            static int named, pointee, unrelated;
            int main(void) { int *p=&pointee; __asm__ volatile("ldr r0, =named" : : "r"(p)); unrelated++; return 0; }
        '''})
        names = {v['symbol_id']: v['name'] for v in facts['variables']}
        touched = {names[u['symbol_id']] for u in facts['unknowns']
                   if u['kind'] == 'INLINE_ASSEMBLY' and u.get('symbol_id')}
        self.assertEqual(touched, {'named', 'pointee'})

    def test_aggregate_copy_parameter_and_return_keep_callback_fields(self):
        facts, _ = self.facts({'a.c': '''
            typedef struct { void (*callback)(void); } Ops;
            static int value; static void Work(void) { value++; }
            static Ops original = {Work}, copied;
            static Ops Forward(Ops arg) { return arg; }
            int main(void) { copied=Forward(original); copied.callback(); return 0; }
        '''})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Work' for c in facts['calls']))

    def test_opaque_aggregate_return_does_not_complete_partial_callback(self):
        facts, _ = self.facts({'a.c': '''
            typedef struct { void (*callback)(void); } Ops; Ops Opaque(void);
            static void Work(void) {} static Ops ops={Work};
            int main(void) { ops=Opaque(); ops.callback(); return 0; }
        '''})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Work' for c in facts['calls']))
        self.assertTrue(any(u['kind'] == 'INDIRECT_CALL' for u in facts['unknowns']))

    def test_memcpy_of_callback_record_preserves_possible_callee(self):
        facts, _ = self.facts({'a.c': '''
            void *memcpy(void *, const void *, unsigned);
            typedef struct { void (*callback)(void); } Ops;
            static void Work(void) {} static Ops original={Work}, copy;
            int main(void) { memcpy(&copy,&original,sizeof(copy)); copy.callback(); return 0; }
        '''})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Work' for c in facts['calls']))

    def test_recursive_record_layout_stops_at_pointer_field(self):
        facts, _ = self.facts({'a.c': '''
            struct Link { struct Link *next; void (*callback)(void); };
            static struct Link one, two;
            int main(void) { two=one; return 0; }
        '''})
        copies = [c for c in facts['pointer_constraints'] if c.get('aggregate')]
        self.assertTrue(copies)
        self.assertTrue(all(c['aggregate_paths'] == ['/callback', '/next'] for c in copies))

    def test_compound_literal_return_keeps_callback_target(self):
        facts, _ = self.facts({'a.c': '''
            typedef struct { void (*callback)(void); } Ops;
            static void Work(void) {} static Ops ops;
            static Ops Factory(void) { return (Ops){.callback=Work}; }
            int main(void) { ops=Factory(); ops.callback(); return 0; }
        '''})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Work' for c in facts['calls']))

    def test_byte_copy_arguments_recover_layout_before_void_cast(self):
        facts, _ = self.facts({'a.c': '''
            void *memcpy(void *, const void *, unsigned);
            struct Item { unsigned tag; int *value; }; static struct Item src[2], dst[2];
            int main(void) { memcpy((void *)dst,(const void *)src,sizeof(dst)); return 0; }
        '''})
        call = next(c for c in facts['semantic_calls'] if c['name'] == 'memcpy')
        self.assertEqual(call['argument_pointee_paths'][:2], [['/[*]/tag', '/[*]/value']] * 2)
        self.assertEqual(call['argument_pointee_sizes'][:2], [16, 16])
        self.assertEqual(call['argument_values'][2], 16)

    def test_cmsis_priority_width_keeps_translation_unit_provenance(self):
        facts, _ = self.facts({'a.c': '#define __NVIC_PRIO_BITS (4U)\nint main(void){return 0;}',
                              'b.c': '#define __NVIC_PRIO_BITS 3\nvoid Helper(void){}'})
        widths = [e for e in facts['irq_priority_events'] if e['api_name'] == 'CMSIS_NVIC_PRIO_BITS']
        self.assertEqual({(e['translation_unit'], e['argument_values'][0]) for e in widths}, {('a.c', 4), ('b.c', 3)})

    def test_aggregate_copy_on_shared_allocator_stays_within_typed_layout(self):
        facts, _ = self.facts({'a.c': '''
            typedef struct { void (*callback)(void); } Pin;
            typedef struct { Pin pin; unsigned tag; } Device;
            static unsigned pool[16]; static void Work(void) {}
            static void *Allocate(void) { return pool; }
            int main(void) {
                Pin *source=Allocate(); Device *device=Allocate();
                source->callback=Work;
                device->pin=*source;
                device->pin.callback();
                return 0;
            }
        '''})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'Work' for c in facts['calls']))
        # Both typed views share one may-allocation. A copy may only select the
        # Pin layout, never recursively copy Device.pin back into itself.
        self.assertFalse(any('/pin/pin' in row['location'] for row in facts['pointer_targets']))
        self.assertLess(len(facts['pointer_targets']), 30)

    @staticmethod
    def priority_source():
        return '''
            #define __NVIC_PRIO_BITS (4U)
            enum { TIM2_IRQn=28, TIM3_IRQn=29 };
            void NVIC_SetPriorityGrouping(unsigned); void NVIC_SetPriority(int,unsigned);
            static int value;
            void TIM2_IRQHandler(void) { value++; }
            void TIM3_IRQHandler(void) { value++; }
            int main(void) {
                NVIC_SetPriorityGrouping(3);
                NVIC_SetPriority(TIM2_IRQn,5); NVIC_SetPriority(TIM3_IRQn,5);
                return 0;
            }
        '''

    def test_cmsis_priority_width_automatically_proves_non_interleaving(self):
        cfg = self.project({'a.c': self.priority_source()},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = fixtures.ProjectTest.extract(self, cfg)
        value = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(value['static_classification'], 'SAFE')
        self.assertEqual(value['safe_reason_code'], 'SAFE_NON_INTERLEAVING')

    def test_conflicting_device_priority_widths_cannot_prove_safe(self):
        cfg = self.project({'a.c': self.priority_source(),
                            'b.c': '#define __NVIC_PRIO_BITS 3\nvoid Helper(void){}'},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = fixtures.ProjectTest.extract(self, cfg)
        value = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(value['static_classification'], 'SUSPECT')
        self.assertTrue(value['conflict_pairs'])

    def test_priority_width_configuration_cannot_override_conflicting_header(self):
        cfg = self.project({'a.c': self.priority_source()},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        cfg['project']['nvic_priority_bits'] = 3
        facts, _ = fixtures.ProjectTest.extract(self, cfg)
        value = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(value['static_classification'], 'SUSPECT')
        self.assertTrue(value['conflict_pairs'])


if __name__ == '__main__':
    unittest.main()
