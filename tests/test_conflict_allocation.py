import importlib.util
import json
from pathlib import Path
import random
import tracemalloc
import unittest

from ecra.analysis import conflict_pairs

reference_path=Path(__file__).parent/'fixtures/e69_conflict_pairs.py'
spec=importlib.util.spec_from_file_location('ecra._conflict_reference',reference_path)
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)


def encoded(value):
    # Preserve every field and insertion/list order, rather than sort away a
    # regression or compare only summary counts.
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def access(i,context,kind='WRITE',routes=1,**extra):
    return dict(access_id='a'+str(i),access_kind=kind,function_id='f'+str(i),file='中.c',line=i+1,
        canonical_path='obj.x',all_call_chains={context:[['entry',str(n),'f'+str(i)] for n in range(routes)]},**extra)


class ConflictAllocationTests(unittest.TestCase):
    def assert_reference(self,rows,relations,contexts):
        before=encoded(rows)
        self.assertEqual(encoded(conflict_pairs(rows,relations,contexts)),
            encoded(reference.conflict_pairs(rows,relations,contexts)))
        self.assertEqual(encoded(rows),before,'Neither implementation may mutate source access records')

    def test_frozen_reference_function_is_byte_exact_and_both_inline_and_product_boundaries_match(self):
        import ast,hashlib
        text=reference_path.read_text(encoding='utf-8');node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef))
        raw='\n'.join(text.splitlines()[node.lineno-1:node.end_lineno])+'\n'
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),'7f73bfe450235519c5d2a877581396b697bc00567c16f298cd9edc52f6bfebe5')
        contexts=dict(main=dict(physical_id='M'),irq=dict(physical_id='I'))
        relation=[dict(contexts=['main','irq'],relation='MAY_PREEMPT')]
        for n in [0,1,4,63,64,65,66]:
            rows=[access(i,'main') for i in range(n)]+[access(n+i,'irq','READ',routes=2) for i in range(n)]
            with self.subTest(n=n):self.assert_reference(rows,relation,contexts)

    def test_first_duplicate_record_wins_and_every_route_count_and_last_count_kind_survive(self):
        contexts=dict(main=dict(physical_id='M'),irq=dict(physical_id='I',reentrant=True))
        first=access(1,'main',routes=17)
        later=access(1,'main','READ',routes=31,call_path_lists_complete=False);later.update(file='different.c',line=900,canonical_path='other')
        self.assert_reference([first,later,access(2,'irq','RMW',routes=3)],[],contexts)
        pairs=conflict_pairs([first,later,access(2,'irq','RMW',routes=3)],[],contexts)
        row=next(pair[field] for pair in pairs for field in ['participant_a','participant_b'] if pair[field]['context_id']=='main')
        self.assertEqual((row['file'],row['access_kind'],row['call_path_count'],row['call_path_count_kind']),('中.c','WRITE',48,'WITNESS_COUNT'))

    def test_seeded_combinations_keep_serial_reentrant_unknown_legacy_paths_and_ignored_accesses_exact(self):
        rng=random.Random(9037)
        for case in range(45):
            contexts={cid:dict(physical_id=rng.choice(['same',cid,None]),reentrant=rng.choice([True,False])) for cid in ['a','b','c']}
            rows=[access(i,rng.choice(list(contexts)),rng.choice(['READ','WRITE','RMW','ADDRESS_TAKEN','UNKNOWN']),rng.randrange(4),call_path_lists_complete=rng.choice([True,False])) for i in range(rng.randrange(25))]
            if rows and case%2:
                rows[0]['call_chains']={c:(routes[0] if routes else []) for c,routes in rows[0].pop('all_call_chains').items()}
            relations=[] if case%3 else [dict(contexts=['a','b'],relation='SERIAL')]
            with self.subTest(case=case):self.assert_reference(rows,relations,contexts)

    def test_large_single_context_retains_all_paths_with_lower_temporary_allocation(self):
        rows=[access(i,'main',routes=4) for i in range(12000)];contexts=dict(main=dict(physical_id='M'))
        peaks=[]
        for function in [reference.conflict_pairs,conflict_pairs]:
            tracemalloc.start(1)
            try:
                self.assertEqual(function(rows,[],contexts),[])
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally:tracemalloc.stop()
        self.assertLess(peaks[1],peaks[0]*0.85,'All 48,000 routes must remain processed with fewer temporary bytes')

    def test_many_context_products_keep_every_selector_and_order_with_lower_retained_allocation(self):
        contexts={f'c{i:02d}':dict(physical_id=f'p{i}') for i in range(32)}
        rows=[access(i*400+j,cid,'WRITE' if j%2 else 'READ',routes=2)
              for i,cid in enumerate(contexts) for j in range(400)]
        self.assert_reference(rows,[],contexts)
        peaks=[]
        for function in [reference.conflict_pairs,conflict_pairs]:
            tracemalloc.start(1)
            try:
                result=function(rows,[],contexts)
                self.assertTrue(result)
                self.assertTrue(all(pair['representation']=='CONTEXT_ACCESS_PRODUCT' for pair in result))
                peaks.append(tracemalloc.get_traced_memory()[1])
                del result
            finally:tracemalloc.stop()
        self.assertLess(peaks[1],peaks[0]*0.85)

    def test_inline_pairs_near_threshold_keep_complete_records_and_lower_retained_allocation(self):
        contexts=dict(main=dict(physical_id='M'),irq=dict(physical_id='I'))
        rows=[access(i,'main','WRITE',routes=2) for i in range(63)]
        rows += [access(63+i,'irq','READ',routes=3) for i in range(63)]
        self.assert_reference(rows,[],contexts)
        peaks=[]
        for function in [reference.conflict_pairs,conflict_pairs]:
            tracemalloc.start(1)
            try:
                result=function(rows,[],contexts)
                self.assertEqual(len(result),3969)
                self.assertTrue(all('representation' not in pair and type(pair) is dict for pair in result))
                peaks.append(tracemalloc.get_traced_memory()[1])
                del result
            finally:tracemalloc.stop()
        self.assertLess(peaks[1],peaks[0]*0.85)


if __name__=='__main__':unittest.main()
