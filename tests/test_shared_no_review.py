"""Strict gates for the non-safety ``SHARED_NO_REVIEW`` classification.

The exemption is intentionally narrow: one physical writer may publish a
naturally aligned volatile scalar to read-only observers.  Every destructive
or unresolved pattern must remain in the OpenCode review queue.
"""
import unittest

from tests import test_ecra as fixtures


class SharedNoReviewTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, source, *, contexts=None):
        cfg = self.project({'main.c': source}, contexts=contexts or [
            dict(id='main', kind='MAIN', functions=['main'])])
        self.facts, self.report = self.extract(cfg)
        return self.facts, self.report

    def variable(self, name):
        matches = [variable for variable in self.facts['variables']
                   if variable.get('qualified_name') == name
                   or variable.get('canonical_path') == name]
        if not matches:
            matches = [variable for variable in self.facts['variables']
                       if variable.get('name') == name]
        self.assertEqual(len(matches), 1,
                         (name, [v.get('canonical_path') for v in self.facts['variables']]))
        return matches[0]

    def assert_classification(self, name, expected):
        variable = self.variable(name)
        self.assertEqual(variable['static_classification'], expected, variable)
        queued = [finding for finding in self.report['findings']
                  if finding.get('symbol_id') == variable['symbol_id']]
        self.assertEqual(len(queued), 1 if expected in {'SUSPECT', 'UNKNOWN'} else 0,
                         (expected, queued, variable))
        return variable

    def test_native_aligned_volatile_single_writer_and_readers_need_no_review(self):
        self.scan('''
            static volatile unsigned value;
            void TIM2_IRQHandler(void) { value = 1u; }
            void USART1_IRQHandler(void) { (void)value; }
            int main(void) { return (int)value; }
        ''')
        value = self.assert_classification('value', 'SHARED_NO_REVIEW')
        self.assertEqual(value['shared_reason_code'], 'SHARED_SINGLE_WRITER_READERS')
        self.assertEqual(value['size_bytes'], 4)
        self.assertGreaterEqual(value['alignment_bytes'], value['size_bytes'])
        self.assertFalse(value.get('safe_evidence'), value)
        proof = value['shared_evidence']
        self.assertEqual(proof['atomic_width_bytes'], 4)
        self.assertEqual(proof['writer_physical_context'], 'IRQ:TIM2_IRQHandler')
        self.assertEqual(set(proof['reader_physical_contexts']),
                         {'FOREGROUND', 'IRQ:USART1_IRQHandler'})
        self.assertTrue(any(pair.get('relation', {}).get('relation') == 'UNKNOWN_PREEMPTION'
                            for pair in value['conflict_pairs']), value['conflict_pairs'])

    def test_multiple_physical_writers_remain_suspect(self):
        self.scan('''
            static volatile unsigned value;
            void TIM2_IRQHandler(void) { value = 1u; }
            void USART1_IRQHandler(void) { value = 2u; }
            int main(void) { return (int)value; }
        ''')
        value = self.assert_classification('value', 'SUSPECT')
        self.assertIn('SHARED_NOT_SINGLE_WRITER', value['shared_no_review_rejections'])

    def test_writer_side_read_is_recorded_with_multiple_writers(self):
        self.scan('''
            static volatile unsigned value;
            void TIM2_IRQHandler(void) { value = 1u; }
            void USART1_IRQHandler(void) { value = value + 1u; }
            int main(void) { return (int)value; }
        ''')
        value = self.assert_classification('value', 'SUSPECT')
        self.assertIn('SHARED_NOT_SINGLE_WRITER', value['shared_no_review_rejections'])
        self.assertIn('SHARED_WRITER_ALSO_READS', value['shared_no_review_rejections'])

    def test_single_writer_rmw_with_atomic_readers_needs_no_review(self):
        self.scan('''
            static volatile unsigned value;
            void TIM2_IRQHandler(void) { value++; }
            int main(void) { return (int)value; }
        ''')
        value = self.assert_classification('value', 'SHARED_NO_REVIEW')
        self.assertEqual(len(value['shared_evidence']['writer_rmw_access_ids']), 1)

    def test_relevant_address_escape_is_unknown_instead_of_shared(self):
        self.scan('''
            static volatile unsigned value;
            void External_Process(volatile unsigned *);
            void TIM2_IRQHandler(void) { value = 1u; }
            int main(void) { External_Process(&value); return (int)value; }
        ''')
        value = self.assert_classification('value', 'UNKNOWN')
        self.assertIn('UNKNOWN_ADDRESS_ESCAPE', value['unknown_reason_codes'])
        self.assertIn('SHARED_RELEVANT_UNKNOWN', value['shared_no_review_rejections'])
        self.assertIsNone(value.get('shared_evidence'))

    def test_dma_lifetime_gap_cannot_enter_shared_no_review(self):
        self.scan('''
            static volatile unsigned char buffer[16];
            int HAL_UART_Receive_DMA(void *, volatile unsigned char *, unsigned);
            int main(void) { return HAL_UART_Receive_DMA(0, buffer, 16); }
        ''')
        buffer = self.assert_classification('buffer', 'UNKNOWN')
        self.assertIn('UNKNOWN_DMA_LIFETIME', buffer['unknown_reason_codes'])
        self.assertIsNone(buffer.get('shared_evidence'))

    def test_whole_object_member_overlap_remains_suspect(self):
        self.scan('''
            struct State { unsigned value; };
            static volatile struct State state;
            static const struct State defaults = { 1u };
            void TIM2_IRQHandler(void) { state = defaults; }
            int main(void) { return (int)state.value; }
        ''')
        value = self.assert_classification('state.value', 'SUSPECT')
        self.assertIn('SHARED_OVERLAPPING_STORAGE', value['shared_no_review_rejections'])

    def test_dynamic_array_overlap_cannot_enter_shared_no_review(self):
        self.scan('''
            static volatile unsigned slots[2];
            static unsigned index_value;
            void TIM2_IRQHandler(void) { slots[0] = 1u; }
            int main(void) { return (int)slots[index_value]; }
        ''')
        value = self.assert_classification('slots[0]', 'SUSPECT')
        self.assertIn('SHARED_OVERLAPPING_STORAGE', value['shared_no_review_rejections'])

    def test_nonvolatile_scalar_remains_suspect(self):
        self.scan('''
            static unsigned value;
            void TIM2_IRQHandler(void) { value = 1u; }
            int main(void) { return (int)value; }
        ''')
        value = self.assert_classification('value', 'SUSPECT')
        self.assertIn('SHARED_COMPILER_VISIBILITY', value['shared_no_review_rejections'])

    def test_atomic_looking_typedef_is_not_atomic_evidence(self):
        self.scan('''
            typedef unsigned atomic_counter_t;
            static atomic_counter_t value;
            void TIM2_IRQHandler(void) { value = 1u; }
            int main(void) { return (int)value; }
        ''')
        value = self.assert_classification('value', 'SUSPECT')
        self.assertFalse(value.get('is_atomic'), value)
        self.assertIn('SHARED_COMPILER_VISIBILITY', value['shared_no_review_rejections'])

    def test_packed_member_uses_root_guaranteed_alignment(self):
        self.scan('''
            struct __attribute__((packed)) Packet {
                volatile unsigned value;
                unsigned char padding;
            };
            static struct Packet packet;
            void TIM2_IRQHandler(void) { packet.value = 1u; }
            int main(void) { return (int)packet.value; }
        ''')
        value = self.assert_classification('packet.value', 'SUSPECT')
        self.assertEqual(value['declared_alignment_bytes'], 4)
        self.assertEqual(value['root_alignment_bytes'], 1)
        self.assertEqual(value['alignment_bytes'], 1)
        self.assertIn('SHARED_NONATOMIC_WIDTH_OR_ALIGNMENT', value['shared_no_review_rejections'])

    def test_volatile_aggregate_qualifies_direct_member_access(self):
        self.scan('''
            struct State { unsigned value; };
            static volatile struct State state;
            void TIM2_IRQHandler(void) { state.value = 1u; }
            int main(void) { return (int)state.value; }
        ''')
        value = self.assert_classification('state.value', 'SHARED_NO_REVIEW')
        self.assertTrue(value['is_volatile'], value)
        self.assertEqual(value['shared_evidence']['compiler_visibility'], 'VOLATILE')

    def test_real_c11_atomic_type_is_exact_metadata(self):
        self.scan('''
            static _Atomic unsigned value;
            void TIM2_IRQHandler(void) { value = 1u; }
            int main(void) { return (int)value; }
        ''')
        value = self.assert_classification('value', 'SHARED_NO_REVIEW')
        self.assertTrue(value['is_atomic'], value)
        self.assertEqual(value['shared_evidence']['compiler_visibility'], 'ATOMIC')

    def test_two_logical_entries_of_one_irq_are_one_serial_executor(self):
        self.scan('''
            static unsigned value;
            void RouteA(void) { value = 1u; }
            void RouteB(void) { (void)value; }
            int main(void) { return 0; }
        ''', contexts=[
            dict(id='tim2_route_a', kind='ISR', vector='TIM2_IRQHandler', functions=['RouteA']),
            dict(id='tim2_route_b', kind='ISR', vector='TIM2_IRQHandler', functions=['RouteB']),
        ])
        value = self.assert_classification('value', 'SAFE_PROVEN')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_IRQ')
        physical = next(item for item in self.facts['physical_contexts']
                        if item['physical_id'] == 'IRQ:TIM2_IRQHandler')
        self.assertEqual(set(physical['logical_context_ids']), {'tim2_route_a', 'tim2_route_b'})
        self.assertFalse(any(pair['may_concurrent'] for pair in value['conflict_pairs']),
                         value['conflict_pairs'])

    def test_destructive_conflict_wins_over_relevant_gap(self):
        self.scan('''
            static volatile unsigned value;
            void External_Process(volatile unsigned *);
            void TIM2_IRQHandler(void) { value = 1u; }
            void USART1_IRQHandler(void) { value = 2u; }
            int main(void) { External_Process(&value); return (int)value; }
        ''')
        value = self.assert_classification('value', 'SUSPECT')
        self.assertEqual(value['analysis_coverage'], 'PARTIAL')
        self.assertTrue(value['blocking_evidence'])
        self.assertIn('SHARED_NOT_SINGLE_WRITER', value['shared_no_review_rejections'])
        self.assertIn('SHARED_RELEVANT_UNKNOWN', value['shared_no_review_rejections'])


if __name__ == '__main__':
    unittest.main()
