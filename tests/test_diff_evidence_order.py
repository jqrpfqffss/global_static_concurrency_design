import copy
import unittest

from ecra import git_diff as fixed


class EvidenceOrderTests(unittest.TestCase):
    def model(self):
        variable=dict(symbol_id='g',qualified_name='g',static_classification='UNKNOWN',analysis_coverage='PARTIAL',
            blocking_evidence=[dict(reason_code='UNRESOLVED_POINTEE',symbol_id='dma[12]'),
                               dict(reason_code='UNRESOLVED_POINTEE',symbol_id='dma[6]')],
            screening_blockers=['COVERAGE','ALIAS'],protection_details=[dict(context='MAIN',sequence=['mask','write']),
                dict(context='IRQ',sequence=['write','restore'])],initializer=['1','2'])
        finding=dict(finding_id='F',symbol_id='g',rules=['SHARED_RW','UNKNOWN_ALIAS'],static_classification='UNKNOWN',
            conflict_pairs=[dict(left='MAIN',right='IRQ'),dict(left='IRQ',right='DMA')],
            uncertainties=[dict(kind='CALL'),dict(kind='ALIAS')])
        return dict(variables=[variable],functions=[],calls=[]),dict(findings=[finding],analysis_status='INCOMPLETE',coverage={})

    def compare(self, facts, report, changed, changed_report=None):
        saved=copy.deepcopy((facts,report,changed,changed_report))
        delta=fixed.compare(fixed.summarize(facts,report),fixed.summarize(changed,changed_report or report),
            dict(files=[],head_sha='h',base_sha='b'))
        self.assertEqual((facts,report,changed,changed_report),saved,'比较不能修改原始事实或静态分类')
        return delta

    def test_blocking_and_screening_collections_ignore_only_order(self):
        facts,report=self.model();changed=copy.deepcopy(facts)
        changed['variables'][0]['blocking_evidence'].reverse()
        changed['variables'][0]['screening_blockers'].reverse()
        self.assertEqual(self.compare(facts,report,changed)['selected_symbol_ids'],[])

    def test_protection_record_order_does_not_change_execution_steps(self):
        facts,report=self.model();changed=copy.deepcopy(facts)
        changed['variables'][0]['protection_details'].reverse()
        self.assertEqual(self.compare(facts,report,changed)['selected_symbol_ids'],[])
        changed['variables'][0]['protection_details'][0]['sequence'].reverse()
        self.assertIn('PROTECTION_CHANGED',self.compare(facts,report,changed)['impacts']['g']['reasons'])

    def test_finding_evidence_collections_preserve_all_records_and_types(self):
        facts,report=self.model();changed_report=copy.deepcopy(report)
        for key in ('rules','conflict_pairs','uncertainties'):changed_report['findings'][0][key].reverse()
        self.assertEqual(self.compare(facts,report,copy.deepcopy(facts),changed_report)['selected_symbol_ids'],[])
        changed_report['findings'][0]['uncertainties'].append(dict(kind='NEW_GAP'))
        self.assertIn('CONFLICT_CHANGED',self.compare(facts,report,copy.deepcopy(facts),changed_report)['impacts']['g']['reasons'])

    def test_duplicates_content_scalar_types_arrays_and_proof_order_still_matter(self):
        for edit in ('duplicate','content','type','array','proof'):
            with self.subTest(edit=edit):
                facts,report=self.model();changed=copy.deepcopy(facts);v=changed['variables'][0]
                if edit=='duplicate':v['blocking_evidence'].append(copy.deepcopy(v['blocking_evidence'][0]))
                elif edit=='content':v['blocking_evidence'][0]['symbol_id']='dma[0]'
                elif edit=='type':
                    facts['variables'][0]['blocking_evidence'][0]['possible']=True;v['blocking_evidence'][0]['possible']=1
                elif edit=='array':v['initializer'].reverse()
                else:
                    facts['variables'][0]['safe_evidence']=dict(initialization=dict(sequence=['reset','write']))
                    v['safe_evidence']=dict(initialization=dict(sequence=['write','reset']))
                self.assertIn('g',self.compare(facts,report,changed)['selected_symbol_ids'])


if __name__=='__main__':unittest.main()
