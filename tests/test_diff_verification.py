"""T30/T43–46: local omissions never hide a reliable mismatch or an internal fault."""
import copy
import unittest

from ecra.diff_verification import completeness, publication, summary_cache_matches, verify_summaries


def summary(partial=False):
    return dict(variables={}, functions={}, build=['fixed'], comparison_scope=dict(
        inventory_known=True, build_complete=True, missing_objects=[], units=[
            dict(source_file='ok.c', tu_id='ok', parse_status='PARSED', extraction_digest='good'),
            dict(source_file='gap.c', tu_id='gap', parse_status='PARTIAL' if partial else 'PARSED', extraction_digest='gap')]))


class VerificationTests(unittest.TestCase):
    def test_complete_partial_and_not_run_are_distinct(self):
        for partial, state in [(False, 'PASSED'), (True, 'INCOMPLETE')]:
            with self.subTest(partial=partial):
                value=summary(partial)
                self.assertEqual(verify_summaries(value, copy.deepcopy(value), 2)['state'],state)
        self.assertEqual(publication({})['verification_state'],'NOT_RUN')
        self.assertEqual(publication(dict(full_verification=dict(state='INCOMPLETE')))['state'],'VALID_PARTIAL')

    def test_known_gap_on_both_runs_does_not_hide_mismatch(self):
        first=summary(True);second=copy.deepcopy(first);second['functions']['good']='changed'
        with self.assertRaisesRegex(ValueError,'不一致'):verify_summaries(first,second,2)

    def test_asymmetric_gap_requires_equal_raw_observations_and_fixed_inventory(self):
        first=summary(False);second=summary(True)
        for left,right in [(first,second),(second,first)]:
            self.assertEqual(verify_summaries(left,right,2)['state'],'INCOMPLETE')
        for mutation in ['digest','inventory','build','missing_digest']:
            value=copy.deepcopy(second)
            if mutation=='digest':value['comparison_scope']['units'][0]['extraction_digest']='bad'
            elif mutation=='inventory':value['comparison_scope']['units'].pop(0)
            elif mutation=='build':value['build']=['other']
            else:value['comparison_scope']['units'][0].pop('extraction_digest')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify_summaries(first,value,2)

    def test_unknown_status_and_missing_inventory_are_not_local_extraction_gaps(self):
        for status in ['WORKER_EXCEPTION',None]:
            value=summary(True)['comparison_scope'];value['units'][1]['parse_status']=status
            with self.assertRaises(ValueError):completeness(value)
        with self.assertRaises(ValueError):completeness({})

    def test_asymmetric_gap_cannot_hide_reliable_declaration_or_header_function_changes(self):
        first=summary(False);second=summary(True)
        for value in (first,second):
            value['comparison_scope']['units'][0]['includes']=['shared.h']
            value['variables']['g']=dict(file='ok.c',object_evidence=dict(name='g',linkage='EXTERNAL'),
                dimensions=dict(declaration='observed declaration'))
            value['functions']['inline']=dict(file='shared.h',digest='observed body')
            value['variables']['header_static']=dict(file='shared.h',
                object_evidence=dict(name='header_static',linkage='INTERNAL',translation_units=['ok.c']),
                dimensions=dict(declaration='observed header declaration'))
        self.assertEqual(verify_summaries(first,second,2)['state'],'INCOMPLETE')
        for kind in ('declaration','header_function','header_storage','definition_file'):
            changed=copy.deepcopy(second)
            if kind=='declaration':changed['variables']['g']['dimensions']['declaration']='mismatch'
            elif kind=='header_function':changed['functions']['inline']['digest']='mismatch'
            elif kind=='header_storage':del changed['variables']['header_static']
            else:changed['variables']['g']['file']='gap.c'
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify_summaries(first,changed,2)

    def test_asymmetric_gap_does_not_accept_schema_or_reliable_macro_changes(self):
        first=summary(False);second=summary(True)
        for value in (first,second):value.update(schema=11,macros={'ok.c':'fixed','gap.c':'gap'})
        for kind in ('schema','extra_field','macro','include'):
            changed=copy.deepcopy(second)
            if kind=='schema':changed['schema']=12
            elif kind=='extra_field':changed['unlocalized']='unexplained'
            elif kind=='macro':changed['macros']['ok.c']='mismatch'
            else:changed['comparison_scope']['units'][0]['includes']=['unexplained.h']
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify_summaries(first,changed,2)

    def test_cache_completeness_must_match_authoritative_counts_and_build(self):
        for partial,build_complete in [(False,True),(True,True),(False,False)]:
            scope=summary(partial)['comparison_scope'];scope['build_complete']=build_complete
            state=completeness(scope)
            manifest=dict(complete_tus=state['complete_tus'],completeness=state)
            coverage=dict(translation_units_total=2,translation_units_parsed=1 if partial else 2,
                          build_closure=dict(complete=build_complete,missing_objects=[]))
            self.assertTrue(summary_cache_matches(manifest,coverage))
            for key,value in [('state','COMPLETE' if state['state']=='VALID_PARTIAL' else 'VALID_PARTIAL'),
                              ('total_units',3),('parsed_units',0),('complete_tus',not state['complete_tus'])]:
                forged=copy.deepcopy(manifest);forged['completeness'][key]=value
                with self.subTest(partial=partial,build=build_complete,key=key):
                    self.assertFalse(summary_cache_matches(forged,coverage))
        for malformed in (None,{},dict(completeness=[]),dict(complete_tus=True,completeness=None)):
            self.assertFalse(summary_cache_matches(malformed,{}))


if __name__=='__main__':unittest.main()
