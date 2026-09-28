"""Storage-overlap and address-escape regressions (real AST extraction)."""
import unittest
from tests import test_ecra as fixtures


class StorageEvidenceTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, source):
        cfg = self.project({'main.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, report = self.extract(cfg)
        self.assertEqual(len({f['symbol_id'] for f in report['findings']}), len(report['findings']))
        return {v['qualified_name']: v for v in facts['variables']}

    def test_nested_array_constant_elements_do_not_overlap(self):
        rows = self.scan('''static struct { unsigned slots[2]; unsigned other; } state;
            void TIM4_IRQHandler(void){state.slots[1]++;}
            int main(void){state.slots[0]++;state.other++;return 0;}''')
        for name in ('state.slots[0]', 'state.slots[1]', 'state.other'):
            self.assertEqual(rows[name]['static_classification'], 'SAFE', rows[name])
            self.assertIn('SAFE_DISJOINT_STORAGE', rows[name].get('safe_reason_codes', []), rows[name])
            proof = rows[name]['safe_evidence']['disjoint_storage']
            start, end = proof['range_bits']
            self.assertTrue(all(end <= item['range_bits'][0] or item['range_bits'][1] <= start
                                for item in proof['nonoverlapping_resources']))

    def test_nested_array_dynamic_index_only_overlaps_that_field(self):
        rows = self.scan('''static struct { unsigned slots[2]; unsigned other; } state;
            void TIM4_IRQHandler(void){(void)state.slots[0];}
            int main(int i){state.slots[i]++;state.other++;return 0;}''')
        for name in ('state.slots[0]', 'state.slots[*]'):
            self.assertEqual(rows[name]['static_classification'], 'SUSPECT', rows[name])
            self.assertNotIn('SAFE_DISJOINT_STORAGE', rows[name].get('safe_reason_codes', []))
        self.assertEqual(rows['state.other']['static_classification'], 'SAFE')

    def test_escaped_union_member_affects_overlapping_member(self):
        rows = self.scan('''static union { unsigned a, b; } state;
            void Opaque(unsigned*);void TIM4_IRQHandler(void){(void)state.b;}
            int main(void){Opaque(&state.a);return 0;}''')
        for name in ('state.a', 'state.b'):
            self.assertEqual(rows[name]['static_classification'], 'UNKNOWN', rows[name])
            self.assertIn('UNKNOWN_ADDRESS_ESCAPE', rows[name]['unknown_reason_codes'])

    def test_escaped_array_member_does_not_escape_other_element_or_field(self):
        rows = self.scan('''static struct { unsigned a, b; } state[2];
            void Opaque(unsigned*);void TIM4_IRQHandler(void){(void)state[1].a;}
            int main(void){Opaque(&state[0].a);state[0].b++;return 0;}''')
        self.assertEqual(rows['state[0].a']['static_classification'], 'UNKNOWN', rows['state[0].a'])
        self.assertEqual(rows['state[0].b']['static_classification'], 'SAFE', rows['state[0].b'])
        self.assertEqual(rows['state[1].a']['static_classification'], 'SAFE', rows['state[1].a'])

    def test_dynamic_nested_array_escape_is_relevant_to_constant_index(self):
        rows = self.scan('''static struct { unsigned a[2], b; } state;
            void Opaque(unsigned*);void TIM4_IRQHandler(void){(void)state.a[0];}
            int main(int i){Opaque(&state.a[i]);state.b++;return 0;}''')
        self.assertEqual(rows['state.a[0]']['static_classification'], 'UNKNOWN', rows['state.a[0]'])
        self.assertEqual(rows['state.b']['static_classification'], 'SAFE', rows['state.b'])

    def test_bitfields_do_not_get_independent_word_rmw_proof(self):
        rows = self.scan('''static struct { unsigned a:1, b:1; } state;
            void TIM4_IRQHandler(void){state.b=1;}
            int main(void){state.a=1;return 0;}''')
        self.assertEqual(rows['state.a']['static_classification'], 'SUSPECT')
        self.assertEqual(rows['state.b']['static_classification'], 'SUSPECT')

    def test_struct_members_have_explicit_disjoint_layout_evidence(self):
        rows = self.scan('''static struct { unsigned foreground, irq; } state;
            void TIM4_IRQHandler(void){state.irq++;}
            int main(void){state.foreground++;return 0;}''')
        for name in ('state.foreground', 'state.irq'):
            self.assertEqual(rows[name]['static_classification'], 'SAFE')
            self.assertIn('SAFE_DISJOINT_STORAGE', rows[name]['safe_reason_codes'])

    def test_union_members_cannot_gain_disjoint_proof(self):
        rows = self.scan('''static union { unsigned a, b; } state;
            void TIM4_IRQHandler(void){state.b++;}
            int main(void){state.a++;return 0;}''')
        for name in ('state.a', 'state.b'):
            self.assertEqual(rows[name]['static_classification'], 'SUSPECT')
            self.assertNotIn('SAFE_DISJOINT_STORAGE', rows[name].get('safe_reason_codes', []))


if __name__ == '__main__':
    unittest.main()
