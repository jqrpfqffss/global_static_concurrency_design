import unittest
from unittest.mock import patch

from ecra.missing_source import (_preprocess_command, complete_identifiers,
                                 may_reference, preprocess_failed_units)
from ecra.evidence import EvidenceIndex


class FailedTUPreprocessingTests(unittest.TestCase):
    def test_command_keeps_build_macros_but_removes_output_side_effects(self):
        command = _preprocess_command([
            'arm-none-eabi-gcc', '-DDEVICE=1', '-MD', '-MF', 'firmware.d',
            '-o', 'firmware.o', '-c', 'firmware.c'])
        self.assertEqual(['arm-none-eabi-gcc', '-E', '-o', '-',
                          '-DDEVICE=1', 'firmware.c'], command)

    def test_all_failed_variants_must_preprocess_before_absence_is_proven(self):
        units = [dict(source_file='sync.c', tu_id='one', parse_status='FAILED',
                      directory='.', original_arguments=['cc', '-c', 'sync.c']),
                 dict(source_file='sync.c', tu_id='two', parse_status='FAILED',
                      directory='.', original_arguments=['cc', '-c', 'sync.c'])]
        facts = {'translation_units': units}
        results = [type('Result', (), dict(returncode=0, stdout=b'extern int live;'))(),
                   type('Result', (), dict(returncode=0, stdout=b'extern int other;'))()]
        with patch('ecra.missing_source.subprocess.run', side_effect=results) as run:
            rows = preprocess_failed_units(facts)
        self.assertEqual(2, run.call_count)
        self.assertEqual(['COMPLETE', 'COMPLETE'], [row['status'] for row in rows])
        self.assertTrue(may_reference(facts, 'sync.c', 'live'))
        self.assertFalse(may_reference(facts, 'sync.c', 'absent'))
        self.assertEqual({'extern', 'int', 'live', 'other'},
                         complete_identifiers(facts, 'sync.c'))
        facts['failed_tu_preprocessing'][1]['status'] = 'UNAVAILABLE'
        self.assertTrue(may_reference(facts, 'sync.c', 'absent'))
        self.assertIsNone(complete_identifiers(facts, 'sync.c'))

    def test_failed_tu_gap_remains_for_named_object_and_is_local_to_it(self):
        facts = dict(functions=[], calls=[], variables=[], translation_units=[],
                     unknowns=[dict(kind='PARSE_FAILED', file='failed.c')],
                     failed_tu_preprocessing=[dict(source_file='failed.c',
                                                   status='COMPLETE', identifiers=['used'])])
        index = EvidenceIndex(facts, {}, {'project': {}}, set())
        def gaps(name):
            variable = dict(symbol_id=name, name=name, qualified_name=name,
                            definition_file='good.c', linkage='EXTERNAL')
            return index.build(variable, [], {}, 'NOT_FOUND').critical_gaps
        self.assertEqual(['UNKNOWN_RELEVANT_MISSING_TU'],
                         [gap['reason_code'] for gap in gaps('used')])
        self.assertEqual([], gaps('unrelated'))

    def test_unparsed_inline_assembly_prevents_absence_proof(self):
        facts = {'translation_units': [dict(source_file='sync.c', tu_id='one',
                    parse_status='FAILED', directory='.',
                    original_arguments=['cc', '-c', 'sync.c'])]}
        result = type('Result', (), dict(returncode=0,
            stdout=b'void f(void) { __asm__ volatile ("str r0, [r1]"); }'))()
        with patch('ecra.missing_source.subprocess.run', return_value=result):
            rows = preprocess_failed_units(facts)
        self.assertEqual('OPAQUE_ASM', rows[0]['status'])
        self.assertTrue(may_reference(facts, 'sync.c', 'unmentioned_global'))


if __name__ == '__main__':
    unittest.main()
