"""A read transaction through accessors is still a multi-field read."""

import unittest

from tests import test_ecra as fixtures


class AccessorCoherenceTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def test_accessor_pair_cannot_enter_shared_no_review(self):
        source = '''
            struct State { volatile unsigned value; volatile unsigned valid; };
            static struct State state;
            static unsigned read_value(void) { return state.value; }
            static unsigned read_valid(void) { return state.valid; }
            void TIM2_IRQHandler(void) { state.value = 1u; state.valid = 1u; }
            int main(void) { unsigned v = read_value(); unsigned ok = read_valid();
                             return (int)(v + ok); }
        '''
        cfg = self.project({'main.c': source}, contexts=[
            dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        for name in ('state.value', 'state.valid'):
            member = next(v for v in facts['variables'] if v.get('canonical_path') == name)
            self.assertEqual(member['static_classification'], 'SUSPECT', member)
            self.assertIn('SHARED_MULTI_FIELD_COHERENCE',
                          member['shared_no_review_rejections'])
            self.assertTrue(member['multi_field_coherence'])
            for summary in member['multi_field_coherence']:
                full = next(row for row in facts['multi_field_coherence']
                            if row['coherence_id'] == summary['coherence_id'])
                self.assertEqual(summary['writer_access_count'], len(full['writer_access_ids']))
                self.assertEqual(summary['reader_access_count'], len(full['reader_access_ids']))
        ids = [row['coherence_id'] for row in facts['multi_field_coherence']]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == '__main__':
    unittest.main()
