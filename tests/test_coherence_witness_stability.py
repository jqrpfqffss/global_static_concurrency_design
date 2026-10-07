"""Coherence witness selection must not depend on solver insertion order."""
import unittest

from ecra.analysis import multi_field_coherence


class CoherenceWitnessStabilityTests(unittest.TestCase):
    def test_equivalent_function_pairs_choose_stable_witness(self):
        variables = [dict(symbol_id='root::member::a', root_symbol_id='root'),
                     dict(symbol_id='root::member::b', root_symbol_id='root')]
        contexts = {'fg': dict(physical_id='FOREGROUND'),
                    'irq': dict(physical_id='IRQ:TIM2')}
        accesses = {v['symbol_id']: [] for v in variables}
        for variable in variables:
            sid = variable['symbol_id']
            for function in ('WriterB', 'WriterA'):
                accesses[sid].append(dict(access_id=f'{sid}:{function}',
                    access_kind='WRITE', function_id=function, contexts=['fg']))
            for function in ('ReaderB', 'ReaderA'):
                accesses[sid].append(dict(access_id=f'{sid}:{function}',
                    access_kind='READ', function_id=function, contexts=['irq']))
        first = multi_field_coherence(variables, accesses, contexts)['root::member::a'][0]
        reversed_accesses = {sid: list(reversed(rows)) for sid, rows in accesses.items()}
        second = multi_field_coherence(variables, reversed_accesses, contexts)['root::member::a'][0]
        self.assertEqual(first, second)
        self.assertEqual(first['function_pair_count'], 4)
        self.assertEqual(first['witness'], dict(writer_function_id='WriterA',
                                                reader_function_id='ReaderA'))


if __name__ == '__main__':
    unittest.main()
