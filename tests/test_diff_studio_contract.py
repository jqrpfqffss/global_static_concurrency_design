"""Diff display is an intersection, never a separate human-decision policy."""
from pathlib import Path
import unittest
from unittest.mock import patch

from ecra.common import digest
from ecra.human_reviews import ReviewStore
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.scan_persistence import append_runtime
from ecra.studio.query import QueryService
from ecra.report_package import export_report, import_report, sha256
from tests import test_studio_api as fixtures


class DiffStudioContractTests(unittest.TestCase):
    setUp = fixtures.StudioAPITests.setUp

    def project(self):
        out=self.data/'scans/three-way';out.mkdir()
        evidence=out/'evidence';evidence.mkdir()
        baseline=evidence/'base.db';base_sha='b'*40
        publish_scan(baseline,dict(variables=[dict(symbol_id='lost',name='lost',static_classification='SUSPECT')]),
                     dict(findings=[]),scan_id='base-'+base_sha,project_id='p')
        hashed=sha256(baseline);baseline.rename(evidence/hashed)
        variables=[dict(symbol_id=s,name=s,static_classification=state) for s,state in
                   [('safe','SAFE_PROVEN'),('shared','SHARED_NO_REVIEW'),('risk','SUSPECT'),('unknown','UNKNOWN'),('excluded','SUSPECT')]]
        transitions={'safe':('R01','SAFETY_RETAINED','安全结论保持'),
                     'shared':(None,'EXEMPTION_RETAINED','免复核依据保持'),
                     'risk':('R05','SUSPECT_PERSISTS','疑似风险持续'),
                     'unknown':('R09','STILL_UNKNOWN','仍待核实')}
        impacts={s:dict(impact_class='UNCERTAIN',selected=True,object_change=dict(event='MATCHED'),
                       risk_transition=dict(matrix_case=case,code=code,label=label))
                 for s,(case,code,label) in transitions.items()}
        lost=dict(symbol_id='lost',name='lost',impact_class='UNCERTAIN',impact=dict(
            impact_class='UNCERTAIN',object_change=dict(event='EXISTENCE_UNCERTAIN'),risk_transition=dict(code='PRIOR_RISK_UNCLOSED')))
        objects=[dict(symbol_id=v['symbol_id'],name=v['name'],evidence_side='current',impact_class='UNCERTAIN',impact_label='待核实',
                      object_event='MATCHED',base_classification=v['static_classification'],head_classification=v['static_classification'],
                      risk_case=transitions[v['symbol_id']][0],risk_code=transitions[v['symbol_id']][1],
                      risk_label=transitions[v['symbol_id']][2],impact_path=['impacts',v['symbol_id']])
                 for v in variables if v['symbol_id']!='excluded']
        objects.append(dict(symbol_id='lost',name='lost',evidence_side='baseline',impact_class='UNCERTAIN',impact_label='待核实',
            object_event='EXISTENCE_UNCERTAIN',base_classification='SUSPECT',head_classification=None,risk_case=None,
            risk_code='PRIOR_RISK_UNCLOSED',risk_label='原风险尚不能关闭',impact_path=['baseline_only_variables',0,'impact']))
        diff=dict(pin=dict(base_sha=base_sha,base_facts_sha256=hashed),selected_symbol_ids=list(impacts),
            conservative_symbol_ids=list(impacts),deleted_variables=[],baseline_only_variables=[lost],impacts=impacts,
            comparison_objects=objects,impact_counts=dict(DEFINITE=0,UNCERTAIN=5,EXCLUDED=1),
            full_verification=dict(state='INCOMPLETE'),publication=dict(state='VALID_PARTIAL'),regional_gaps=[dict(side='head',kind='PARSE_GAP')])
        report=dict(git_diff=diff,findings=[dict(symbol_id='risk',finding_id='risk',static_classification='SUSPECT')])
        publish_scan(out/'scan.db',dict(variables=variables),report,scan_id=out.name,project_id='p')
        provider=EvidenceProvider(out/'scan.db');store=ReviewStore(out/'reviews.db',provider.metadata())
        return out,provider,store,report

    def test_all_current_decisions_and_submission_effects_equal_ordinary_mode(self):
        out,provider,store,report=self.project();query=QueryService(out)
        static=digest(provider.load('report',['git_diff']))
        def equivalent():
            full={r['symbol_id']:r for r in query.symbols()['items']}
            selected=query.symbols(diff='selected')['items']
            for row in selected:
                self.assertEqual(row,full[row['symbol_id']])
            self.assertEqual({r['symbol_id'] for r in selected},set(report['git_diff']['selected_symbol_ids']))
            self.assertEqual(digest(provider.load('report',['git_diff'])),static)
        equivalent()
        self.assertEqual(query.symbols(diff='changes',search='safe',review_scope='pending')['total'],0)
        self.assertEqual(query.symbols(diff='changes',search='shared',review_scope='pending')['total'],0)
        for decision in ['NEED_MORE_EVIDENCE','CONFIRMED_RISK','CONFIRMED_SAFE']:
            fingerprint=provider.fingerprint('unknown')
            store.append('unknown',fingerprint,reviewer='same rules',decision=decision,
                expected_heads=[head['event_id'] for head in store.current('unknown',fingerprint)['heads']],
                comment='同侧证据人工复核依据',
                handling_status='ACCEPTED_RISK' if decision=='CONFIRMED_RISK' else 'CLOSED' if decision=='CONFIRMED_SAFE' else 'TODO')
            equivalent()
        append_runtime(out,report,[dict(finding_id='risk',state='DONE',status='REVIEWED_SAFE',answer=dict(status='REVIEWED_SAFE'))])
        equivalent()
        self.assertEqual(query.symbols(diff='selected',symbol_id='risk')['items'][0]['current_result'],'SAFE')

    def test_uncertain_baseline_is_visible_reviewable_and_survives_exchange(self):
        out,provider,store,report=self.project();api='/api/scans/'+out.name
        def get(path):
            value=self.client.get(path);self.assertEqual(value.status_code,200,value.text);return value.json()
        current=get(api+'/symbols?diff=changes')
        self.assertEqual(current['total'],5)
        self.assertNotIn('excluded',{x['symbol_id'] for x in current['items']})
        lost=get(api+'~base/symbol?symbol_id=lost')
        self.assertEqual(lost['diff_change']['object_event'],'EXISTENCE_UNCERTAIN')
        base_api=api+'~base';proof=get(base_api+'/human?symbol_id=lost')['fingerprint']
        draft=dict(symbol_id='lost',fingerprint=proof,reviewer='reviewer',decision='CONFIRMED_RISK',handling_status='ACCEPTED_RISK',expected_heads=[])
        response=self.client.post(base_api+'/human',json=draft);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(get(base_api+'/symbol?symbol_id=lost')['needs_human_confirmation'],0)
        self.assertEqual(get(api+'/summary')['diff']['publication']['state'],'VALID_PARTIAL')
        package=Path(self.tmp.name)/'diff.ecra-report';export_report(out,package)
        destination=Path(self.tmp.name)/'roundtrip';restored=import_report(package,destination)
        reopened=QueryService(destination/'scans'/restored['scan_id'])
        self.assertEqual(reopened.symbols(diff='changes'),QueryService(out).symbols(diff='changes'))
        self.assertEqual(reopened.diff_changes('objects'),QueryService(out).diff_changes('objects'))
        self.assertEqual(EvidenceProvider(destination/'scans'/restored['scan_id']/'scan.db').load('report',['git_diff']),report['git_diff'])

    def test_paginated_risk_event_and_impact_filters_do_not_load_full_roots(self):
        out,*_=self.project();query=QueryService(out)
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('whole root forbidden')):
            page=query.diff_changes('objects',impact='UNCERTAIN',limit=2)
            self.assertEqual(page['total'],5);self.assertEqual(page['next_offset'],2)
            self.assertEqual(query.diff_changes('objects',risk='R09')['items'][0]['symbol_id'],'unknown')
            self.assertEqual(query.diff_changes('objects',risk='EXEMPTION_RETAINED')['items'][0]['symbol_id'],'shared')
            self.assertEqual(query.diff_changes('objects',risk='R02')['total'],0)
            self.assertEqual(query.diff_changes('objects',event='EXISTENCE_UNCERTAIN')['items'][0]['symbol_id'],'lost')
            self.assertEqual(query.diff_changes('objects',risk='PRIOR_RISK_UNCLOSED')['items'][0]['symbol_id'],'lost')
            self.assertEqual(query.diff_changes('objects',impact='EXCLUDED')['total'],0)
            self.assertEqual(query.symbols(diff='changes',search='excluded')['total'],0)
            self.assertEqual(query.current_summary(diff='changes')['total'],5)


if __name__=='__main__':unittest.main()
