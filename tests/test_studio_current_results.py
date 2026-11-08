"""Operational queues never rewrite facts, AI answers or human signatures."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from ecra.human_reviews import ReviewStore
from ecra.scan_persistence import append_runtime,runtime
from ecra.scan_store import publish_scan,EvidenceProvider
from ecra.studio.query import QueryService


class CurrentResultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)/'data/scans/test';self.out.mkdir(parents=True)
        states={'safe-ai':'SUSPECT','safe-unknown':'UNKNOWN','risk':'SUSPECT','likely':'SUSPECT',
                'need':'SUSPECT','unknown':'UNKNOWN','failed':'SUSPECT','static-safe':'SAFE_PROVEN',
                'shared':'SHARED_NO_REVIEW','container':'CONTAINER','out':'OUT_OF_BUILD','non':'NON_STORAGE',
                'mixed-unknown':'UNKNOWN','mixed-risk':'SUSPECT','supp-safe':'UNKNOWN','supp-pending':'UNKNOWN'}
        variables=[dict(symbol_id=sid,name=sid,static_classification=state,definition_file='Src/a.c',definition_line=1,
                        **({'coverage_source':'supplemental'} if sid.startswith('supp-') else {})) for sid,state in states.items()]
        findings=[dict(symbol_id=sid,finding_id=sid,static_classification=states[sid]) for sid in states if sid not in {'shared','container','out','non','static-safe'}]
        findings.extend([dict(symbol_id='mixed-unknown',finding_id='mixed-unknown-2'),dict(symbol_id='mixed-risk',finding_id='mixed-risk-2'),dict(finding_id='gap')])
        publish_scan(self.out/'scan.db',dict(variables=variables),dict(findings=findings),scan_id='test',project_id='p')
        self.provider=EvidenceProvider(self.out/'scan.db');self.store=ReviewStore(self.out/'reviews.db',self.provider.metadata())
        answers={'safe-ai':'FALSE_POSITIVE','safe-unknown':'REVIEWED_SAFE','risk':'CONFIRMED','likely':'LIKELY',
                 'need':'NEED_MORE_CONTEXT','mixed-unknown':'REVIEWED_SAFE','mixed-risk':'REVIEWED_SAFE',
                 'mixed-risk-2':'CONFIRMED','supp-safe':'REVIEWED_SAFE','gap':'NEED_MORE_CONTEXT'}
        self.rows=[dict(finding_id=fid,state='DONE',status=status,answer=dict(status=status,reason='受控协议夹具')) for fid,status in answers.items()]
        self.rows.append(dict(finding_id='failed',state='TECH_FAILED',status='REVIEWED_SAFE',answer=dict(status='REVIEWED_SAFE')))
        append_runtime(self.out,{},self.rows);self.query=QueryService(self.out)

    def by_id(self):return {r['symbol_id']:r for r in self.query.symbols()['items']}

    def test_safe_and_nonstorage_exit_queue_unknown_and_risks_remain(self):
        rows=self.by_id()
        for sid in ['safe-ai','safe-unknown','static-safe','shared','container','out','non','supp-safe']:
            self.assertEqual(rows[sid]['confirmation_state'],'NOT_REQUIRED',sid)
            self.assertEqual(rows[sid]['needs_human_confirmation'],0,sid)
        for sid in ['risk','likely','need','unknown','failed','mixed-unknown','mixed-risk','supp-pending']:
            self.assertEqual(rows[sid]['needs_human_confirmation'],1,sid)
        # An inconclusive AI answer does not refute the existing static
        # conflict: use the established decisions.effective_decision contract.
        self.assertEqual(rows['need']['current_result'],'LIKELY')
        self.assertEqual(rows['need']['result_source'],'STATIC')
        self.assertEqual(rows['need']['ai_answer_count'],1)
        self.assertEqual(rows['failed']['current_result'],'LIKELY')

    def test_all_findings_must_be_safe_before_variable_is_safe(self):
        rows=self.by_id()
        self.assertEqual(rows['mixed-unknown']['current_result'],'UNKNOWN')
        self.assertEqual(rows['mixed-risk']['current_result'],'CONFIRMED')
        self.assertEqual(rows['mixed-unknown']['result_source'],'MIXED')

    def test_summary_and_every_drilldown_share_exact_denominator_and_pagination(self):
        summary=self.query.current_summary()
        self.assertEqual(sum(summary['result_counts'].values()),16)
        self.assertEqual(summary['pending_count'],8)
        for result,count in summary['result_counts'].items():
            page=self.query.symbols(current_result=result,limit=1)
            self.assertEqual(page['total'],count)
        pending=self.query.symbols(review_scope='pending',limit=2)
        self.assertEqual(pending['total'],summary['pending_count'])
        self.assertEqual(pending['next_offset'],2)
        self.assertEqual(self.query.symbols(current_result='SAFE',review_scope='pending')['total'],0)

    def test_revision_and_views_follow_new_snapshot_and_ignore_unpublished_events(self):
        before=self.query.result_revision()
        with closing(sqlite3.connect(self.out/'reviews.db')) as conn,conn:
            record=dict(finding_id='risk',state='DONE',status='REVIEWED_SAFE')
            conn.execute('INSERT INTO ai_events(ordinal,finding_id,state,hash,payload) VALUES (?,?,?,?,?)',(2,'risk','DONE','unpublished',json.dumps(record)))
        self.assertEqual(self.by_id()['risk']['current_result'],'CONFIRMED')
        self.assertEqual(self.query.result_revision(),before)
        changed=[dict(row,status='REVIEWED_SAFE',answer=dict(status='REVIEWED_SAFE')) if row['finding_id']=='risk' else row for row in self.rows]
        append_runtime(self.out,{},changed)
        self.assertNotEqual(self.query.result_revision(),before)
        self.assertEqual(self.by_id()['risk']['current_result'],'SAFE')
        self.assertEqual(self.query.current_summary()['pending_count'],7)

    def test_static_and_human_history_are_untouched_when_ai_becomes_safe(self):
        raw=hashlib.sha256((self.out/'scan.db').read_bytes()).hexdigest()
        event=self.store.append('risk',self.provider.fingerprint('risk'),decision='CONFIRMED_RISK',reviewer='协议夹具',comment='测试事务，不是工程签署',expected_heads=[])
        changed=[dict(row,status='FALSE_POSITIVE',answer=dict(status='FALSE_POSITIVE')) if row['finding_id']=='risk' else row for row in self.rows]
        append_runtime(self.out,{},changed)
        row=self.by_id()['risk'];self.assertEqual(row['static_classification'],'SUSPECT')
        self.assertEqual(row['current_result'],'SAFE');self.assertEqual(row['confirmation_state'],'NOT_REQUIRED')
        self.assertEqual(self.store.current('risk',self.provider.fingerprint('risk'))['decision'],'CONFIRMED_RISK')
        self.assertEqual(self.query.symbols(human_decision='CONFIRMED_RISK')['items'][0]['symbol_id'],'risk')
        self.assertEqual(hashlib.sha256((self.out/'scan.db').read_bytes()).hexdigest(),raw)

    def test_manual_submission_reduces_pending_without_changing_analysis(self):
        self.store.append('need',self.provider.fingerprint('need'),decision='CONFIRMED_SAFE',reviewer='协议夹具',comment='测试事务',expected_heads=[])
        self.assertEqual(self.query.current_summary()['pending_count'],7)
        self.assertEqual(self.by_id()['need']['current_result'],'LIKELY')
        self.assertEqual(self.query.symbols(review_scope='pending',symbol_id='need')['total'],0)

    def test_legacy_snapshot_and_v1_references_are_projected_with_same_rules(self):
        with closing(sqlite3.connect(self.out/'reviews.db')) as conn,conn:
            refs=[dict(sequence=seq,finding_id=fid,hash=hashed) for seq,fid,hashed in conn.execute('SELECT sequence,finding_id,hash FROM ai_events')]
            conn.execute('INSERT INTO ai_snapshots(hash,payload) VALUES (?,?)',('v1',json.dumps(dict(ai_events_version=1,reviews=refs))))
        self.assertEqual(self.by_id()['safe-ai']['current_result'],'SAFE')
        with closing(sqlite3.connect(self.out/'reviews.db')) as conn,conn:
            conn.execute('INSERT INTO ai_snapshots(hash,payload) VALUES (?,?)',('legacy',json.dumps(dict(reviews=self.rows))))
        self.assertEqual(self.by_id()['safe-unknown']['current_result'],'SAFE')

    def test_bounded_queries_do_not_reconstruct_facts_or_ledger(self):
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full reconstruction')):
            self.query.current_summary();self.query.symbols(limit=1);self.query.symbol_ai('risk',limit=1)
        self.assertEqual(self.query.symbol_ai('risk')['items'][0]['status'],'CONFIRMED')

    def test_filters_reject_invalid_values_and_ai_verdict_filter_uses_verdict_not_execution_state(self):
        self.assertEqual(self.query.symbols(ai_state='NEED_MORE_CONTEXT')['total'],1)
        self.assertEqual(self.query.symbols(ai_state='FALSE_POSITIVE')['total'],1)
        for args in [dict(current_result='safe'),dict(review_scope='DELETE'),dict(ai_state='UNKNOWN_FAKE')]:
            with self.assertRaises(ValueError):self.query.symbols(**args)

    def test_projection_matches_established_static_review_decision_matrix(self):
        from ecra.decisions import variable_decisions
        outcomes=['OFF','PENDING','RUNNING','TECH_FAILED','STALE','NEED_MORE_CONTEXT',
                  'CONFIRMED','LIKELY','REVIEWED_SAFE','FALSE_POSITIVE']
        out=self.out.parent/'decision-matrix';out.mkdir()
        variables=[];findings=[];reviews=[]
        for static in ('SUSPECT','UNKNOWN','SAFE_PROVEN'):
            for outcome in outcomes:
                sid=static+'-'+outcome
                variables.append(dict(symbol_id=sid,name=sid,static_classification=static))
                findings.append(dict(symbol_id=sid,finding_id=sid,static_classification=static))
                if outcome=='OFF':continue
                if outcome in {'PENDING','RUNNING','TECH_FAILED','STALE'}:
                    reviews.append(dict(finding_id=sid,state=outcome,status='REVIEWED_SAFE'))
                else:
                    reviews.append(dict(finding_id=sid,state='DONE',status=outcome,
                                        answer=dict(status=outcome)))
        facts=dict(variables=variables);report=dict(findings=findings)
        expected=variable_decisions(facts,report,{r['finding_id']:r for r in reviews})
        publish_scan(out/'scan.db',facts,report,scan_id='decision-matrix',project_id='p')
        ReviewStore(out/'reviews.db',EvidenceProvider(out/'scan.db').metadata())
        append_runtime(out,{},reviews)
        rows=QueryService(out).symbols(limit=50)['items']
        groups=dict(confirmed='CONFIRMED',likely='LIKELY',unresolved='UNKNOWN',safe='SAFE')
        self.assertEqual(len(rows),len(variables))
        for row in rows:
            with self.subTest(symbol_id=row['symbol_id']):
                self.assertEqual(row['current_result'],groups[expected[row['symbol_id']]])

    def test_mixed_findings_keep_unrefuted_static_conflicts_regardless_of_order(self):
        from ecra.decisions import variable_decisions
        import itertools
        outcomes=[('LIKELY','NEED_MORE_CONTEXT'),('CONFIRMED','NEED_MORE_CONTEXT'),
                  ('REVIEWED_SAFE','NEED_MORE_CONTEXT'),('FALSE_POSITIVE','LIKELY'),
                  ('REVIEWED_SAFE','FALSE_POSITIVE')]
        groups=dict(confirmed='CONFIRMED',likely='LIKELY',unresolved='UNKNOWN',safe='SAFE')
        for number,(left,right) in enumerate(outcomes):
            findings=[dict(symbol_id='s',finding_id='left',static_classification='SUSPECT'),
                      dict(symbol_id='s',finding_id='right',static_classification='UNKNOWN')]
            for ordering,sequence in enumerate(itertools.permutations(findings)):
                out=self.out.parent/f'mixed-{number}-{ordering}';out.mkdir()
                facts=dict(variables=[dict(symbol_id='s',name='s',static_classification='SUSPECT')])
                report=dict(findings=list(sequence))
                reviews=[dict(finding_id=fid,state='DONE',status=status,answer=dict(status=status))
                         for fid,status in [('left',left),('right',right)]]
                expected=variable_decisions(facts,report,{r['finding_id']:r for r in reviews})['s']
                publish_scan(out/'scan.db',facts,report,scan_id='mixed',project_id='p')
                ReviewStore(out/'reviews.db',EvidenceProvider(out/'scan.db').metadata())
                append_runtime(out,{},reviews)
                query=QueryService(out)
                self.assertEqual(query.symbols()['items'][0]['current_result'],groups[expected])
                self.assertEqual(query.current_summary()['result_counts'],{groups[expected]:1})


if __name__=='__main__':unittest.main()
