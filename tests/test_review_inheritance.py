"""Unchanged-evidence inheritance, revocation, lineage and portable round trips."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ecra.human_reviews import ReviewStore, ReviewConflict
from ecra.report_package import export_report, import_report, export_delta, import_delta
from ecra.review_inheritance import validate_prior
from ecra.scan_store import publish_scan, EvidenceProvider
from ecra.studio.query import QueryService


class ReviewInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra 继承 ')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.facts=dict(variables=[dict(symbol_id='s',name='shared',static_classification='UNKNOWN')],
            accesses=[dict(symbol_id='s', contexts=['irq'], future_field=['exact', 1])])
        self.old,self.op=self.scan('old')
        self.first=self.old.append('s',self.op.fingerprint('s'),reviewer='原工程师声明',
            decision='CONFIRMED_SAFE',comment='测试依据，非真实固件结论',handling_status='CLOSED')

    def scan(self, name, *, previous=None, facts=None, input_fp=None):
        folder=self.base/name;folder.mkdir()
        publish_scan(folder/'scan.db',facts or self.facts,
            dict(fingerprint=input_fp or 'a'*64,generated_at=name,findings=[]),scan_id=name,project_id='p')
        provider=EvidenceProvider(folder/'scan.db')
        store=ReviewStore(folder/'reviews.db',provider.metadata())
        if previous:
            store.inherit_from(previous[0],previous[1],provider)
        return store,provider

    def state(self, store, provider):
        return store.current('s',provider.fingerprint('s'))

    def test_unchanged_complete_inputs_and_facts_inherit_without_forging_current_events(self):
        new,np=self.scan('new',previous=(self.old,self.op))
        self.assertNotEqual(self.op.fingerprint('s'),np.fingerprint('s'))
        state=self.state(new,np)
        self.assertTrue(state['inherited'])
        self.assertEqual(state['decision'],'CONFIRMED_SAFE')
        self.assertEqual(state['handling_status'],'CLOSED')
        self.assertEqual(state['heads'],[])
        self.assertEqual(state['inherited_sources'],[self.first])
        self.assertEqual(new.history(),[])
        self.assertEqual(self.old.history(),[self.first])
        self.assertEqual(QueryService(new.path.parent).human_counts(),{'CONFIRMED_SAFE':1})
        self.assertEqual(QueryService(new.path.parent).symbols(human_decision='CONFIRMED_SAFE',handling_status='CLOSED')['total'],1)

    def test_any_input_or_full_fact_change_requires_recheck_even_when_variable_is_identical(self):
        changed=copy.deepcopy(self.facts);changed['accesses'][0]['contexts']=['main']
        for name,kwargs in [('inputs',dict(input_fp='b'*64)),('facts',dict(facts=changed))]:
            with self.subTest(name=name):
                new,np=self.scan(name,previous=(self.old,self.op),**kwargs)
                self.assertEqual(self.state(new,np)['decision'],'RECHECK_REQUIRED')
                self.assertFalse(self.state(new,np)['inherited'])
                self.assertNotIn('inheritance',new.prior('s',np.fingerprint('s'))[0])

    def test_undo_stays_revoked_across_rescan_and_explicit_reconfirmation_can_inherit(self):
        new,np=self.scan('new',previous=(self.old,self.op))
        undo=new.undo('s',np.fingerprint('s'),reviewer='复核声明',comment='撤回依据',expected_heads=[])
        self.assertEqual(undo['evidence_parents'][0]['event_id'],self.first['event_id'])
        third,tp=self.scan('third',previous=(new,np))
        self.assertEqual(self.state(third,tp)['decision'],'RECHECK_REQUIRED')
        confirmed=third.append('s',tp.fingerprint('s'),reviewer='新声明',decision='CONFIRMED_RISK',comment='重新核查')
        fourth,fp=self.scan('fourth',previous=(third,tp))
        self.assertEqual(self.state(fourth,fp)['decision'],'CONFIRMED_RISK')
        self.assertEqual(self.state(fourth,fp)['inherited_sources'],[confirmed])
        self.assertEqual(self.old.history(),[self.first])

    def test_full_package_and_delta_keep_proof_and_cross_scan_undo_idempotently(self):
        new,np=self.scan('new',previous=(self.old,self.op))
        package=self.base/'before.ecra-report';export_report(new.path.parent,package)
        imported=import_report(package,self.base/'offline')
        folder=self.base/'offline/scans'/imported['scan_id']
        restored=ReviewStore(folder/'reviews.db',np.metadata())
        self.assertTrue(self.state(restored,np)['inherited'])
        new.undo('s',np.fingerprint('s'),reviewer='声明',comment='撤销',expected_heads=[])
        delta=self.base/'undo.ecra-review-delta';export_delta(new.path.parent,delta)
        self.assertEqual(import_delta(delta,folder)['imported_events'],1)
        self.assertEqual(import_delta(delta,folder)['imported_events'],0)
        self.assertEqual(self.state(restored,np)['decision'],'RECHECK_REQUIRED')
        final=self.base/'after.ecra-report';export_report(folder,final)
        again=import_report(final,self.base/'offline2')
        reopened=ReviewStore(self.base/'offline2/scans'/again['scan_id']/'reviews.db',np.metadata())
        self.assertEqual(reopened.history(),new.history())

    def test_unseen_parallel_old_head_survives_later_confirmation_as_conflict(self):
        new,np=self.scan('new',previous=(self.old,self.op))
        new.append('s',np.fingerprint('s'),reviewer='B',decision='CONFIRMED_RISK',comment='B依据')
        branch=self.old.append('s',self.op.fingerprint('s'),reviewer='A',decision='NEED_MORE_EVIDENCE',
            expected_heads=[self.first['event_id']])
        # Merge a newer snapshot of source A into an independent current scan.
        third,tp=self.scan('third',previous=(new,np))
        # Source A already exists: conflicting payloads must never overwrite.
        with self.assertRaisesRegex(ValueError,'不同内容'):
            third.inherit_from(self.old,self.op,tp)
        self.assertEqual(self.old.history()[-1],branch)

    def test_parallel_cross_scan_decisions_require_explicit_resolution(self):
        a,ap=self.scan('a',previous=(self.old,self.op))
        b,bp=self.scan('b',previous=(self.old,self.op))
        a.append('s',ap.fingerprint('s'),decision='CONFIRMED_RISK',reviewer='A')
        b.append('s',bp.fingerprint('s'),decision='CONFIRMED_SAFE',reviewer='B',comment='B依据')
        merged,mp=self.scan('merged',previous=(a,ap))
        merged.inherit_from(b,bp,mp)
        self.assertTrue(self.state(merged,mp)['conflict'])
        self.assertEqual(QueryService(merged.path.parent).human_counts(),{'CONFLICT':1})
        with self.assertRaises(ReviewConflict):
            merged.append('s',mp.fingerprint('s'),reviewer='C',decision='CONFIRMED_RISK')
        resolved=merged.append('s',mp.fingerprint('s'),reviewer='C',decision='CONFIRMED_RISK',
            resolve=True,comment='核对全部来源')
        next_scan,nfp=self.scan('resolved',previous=(merged,mp))
        self.assertEqual(self.state(next_scan,nfp)['inherited_sources'],[resolved])

    def test_forged_proof_missing_lineage_and_tampered_repeat_roll_back(self):
        new,np=self.scan('new',previous=(self.old,self.op))
        with sqlite3.connect(new.path) as conn:
            row=conn.execute('SELECT * FROM prior_decisions').fetchone()
        value=json.loads(row[-1]);value['inheritance']['input_fingerprint']='b'*64
        raw=json.dumps(value)
        with self.assertRaisesRegex(ValueError,'指纹'):
            validate_prior((*row[:4],hashlib.sha256(raw.encode()).hexdigest(),raw),np)
        new.undo('s',np.fingerprint('s'),reviewer='声明',comment='撤销',expected_heads=[])
        delta=self.base/'good.delta';export_delta(new.path.parent,delta)
        payload=json.loads(delta.read_text('utf-8'))
        payload['events'][0]['evidence_parents'][0]['event_id']='missing'
        bad=self.base/'bad.delta';bad.write_text(json.dumps(payload),'utf-8')
        target,_=self.scan('target')
        # The target has to carry the same immutable scan identity.
        clone=self.base/'clone';clone.mkdir()
        import shutil
        shutil.copyfile(new.path.parent/'scan.db',clone/'scan.db')
        clean=ReviewStore(clone/'reviews.db',np.metadata())
        with self.assertRaisesRegex(ValueError,'前驱'):
            import_delta(bad,clone)
        self.assertEqual(clean.history(),[])
        self.assertEqual(clean.prior('s',np.fingerprint('s')),[])

    def test_inherited_only_delta_carries_original_history_without_new_events(self):
        new,np=self.scan('new',previous=(self.old,self.op))
        import shutil
        clone=self.base/'delta-only';clone.mkdir()
        shutil.copyfile(np.path,clone/'scan.db')
        target=ReviewStore(clone/'reviews.db',np.metadata())
        delta=self.base/'inherited.delta';export_delta(new.path.parent,delta)
        self.assertEqual(import_delta(delta,clone)['imported_events'],0)
        self.assertTrue(self.state(target,np)['inherited'])
        self.assertEqual(target.history(),[])
        self.assertEqual(self.state(target,np)['inherited_sources'],[self.first])

    def test_cross_scan_causal_cycle_is_rejected(self):
        from ecra.review_inheritance import validate_lineage
        a=copy.deepcopy(self.first)
        b=dict(a,event_id='later-event',scan_id='later')
        a['evidence_parents']=[dict(scan_id=b['scan_id'],event_id=b['event_id'],fingerprint=b['fingerprint'])]
        b['evidence_parents']=[dict(scan_id=a['scan_id'],event_id=a['event_id'],fingerprint=a['fingerprint'])]
        with self.assertRaisesRegex(ValueError,'循环'):
            validate_lineage([dict(binding=dict(scan_id=a['scan_id']),events=[a]),
                dict(binding=dict(scan_id=b['scan_id']),events=[b])],[])
