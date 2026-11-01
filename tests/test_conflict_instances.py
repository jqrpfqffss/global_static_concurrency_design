import ast
import gc
import hashlib
import importlib.util
from pathlib import Path
import tracemalloc
import unittest

from ecra.analysis import conflict_pairs
from tests.test_conflict_allocation import access,encoded,reference

path=Path(__file__).parent/'fixtures/selectors_conflict_pairs.py'
spec=importlib.util.spec_from_file_location('ecra._selectors_reference',path)
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)


class ConflictInstanceTests(unittest.TestCase):
    def test_previous_selector_reference_is_frozen_byte_exact(self):
        text=path.read_text('utf-8');node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef))
        raw='\n'.join(text.splitlines()[node.lineno-1:node.end_lineno])+'\n'
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),'ab821d23392938a71fdd64c60af57954e2f3d309b6fab384535b8a51da2e6a7a')

    def test_overlapping_contexts_duplicate_ids_last_witness_first_role_and_insertion_order_match_both(self):
        for count in [3,64,90]:
            contexts={cid:dict(physical_id='shared' if cid in ['b','d'] else cid,reentrant=cid=='c') for cid in ['d','b','c','a']}
            rows=[]
            for i in range(count):
                row=access(i,'a','READ' if i%3==0 else 'RMW',routes=2)
                row['all_call_chains']={cid:[[cid,str(i),str(n)] for n in range(1+i%3)] for cid in ['d','b','c','a']}
                rows.append(row)
            for i in reversed(range(0,count,3)):
                row=access(i,'a','WRITE',routes=2,call_path_lists_complete=False)
                row.update(function_id='later_different_function',file='later.c',canonical_path='other.member')
                row['all_call_chains']={cid:[[cid,'later',str(i)]] for cid in ['a','c']}
                rows.append(row)
            rows.extend([access(count+1,'a',routes=0),access(count+2,'a','ADDRESS_TAKEN')])
            before=encoded(rows);actual=encoded(conflict_pairs(rows,[],contexts))
            with self.subTest(count=count):
                self.assertEqual(actual,encoded(reference.conflict_pairs(rows,[],contexts)))
                self.assertEqual(actual,encoded(previous.conflict_pairs(rows,[],contexts)))
                self.assertEqual(encoded(rows),before)

    def test_output_reuses_one_plain_participant_per_instance(self):
        rows=[access(1,'a'),access(2,'b'),access(3,'c')]
        result=conflict_pairs(rows,[],{cid:dict(physical_id=cid) for cid in ['a','b','c']})
        seen={}
        for pair in result:
            for side in ['participant_a','participant_b']:
                row=pair[side];self.assertIs(type(row),dict)
                if row['instance_id'] in seen:self.assertIs(row,seen[row['instance_id']])
                seen[row['instance_id']]=row

    def test_unused_malformed_participants_still_fail_instead_of_becoming_empty_safe_output(self):
        row=access(1,'main');del row['function_id']
        for function in [reference.conflict_pairs,previous.conflict_pairs,conflict_pairs]:
            with self.assertRaises(KeyError):function([row],[],dict(main={}))
            row=access(1,'main');row['access_id']=b'not-json'
            with self.assertRaises(TypeError):function([row],[],dict(main={}))
            row=access(1,'main');del row['function_id']

    def test_many_contexts_avoid_unreferenced_full_instances_without_losing_any_ordered_output(self):
        contexts={f'c{i:02d}':dict(physical_id=f'p{i}') for i in range(16)}
        rows=[]
        for i in range(2000):
            row=access(i,'c00','READ' if i%2 else 'WRITE')
            row['all_call_chains']={cid:[[cid,'f'+str(i)]] for cid in contexts};rows.append(row)
        peaks=[];outputs=[]
        for function in [previous.conflict_pairs,conflict_pairs]:
            gc.collect();tracemalloc.start(1)
            try:
                result=function(rows,[],contexts);peaks.append(tracemalloc.get_traced_memory()[1])
            finally:tracemalloc.stop()
            outputs.append(encoded(result));del result
        self.assertEqual(outputs[0],outputs[1]);self.assertLess(peaks[1],peaks[0]*.7)


if __name__=='__main__':unittest.main()
