from pathlib import Path
import sqlite3
import tempfile
import unittest

from ecra.human_reviews import ReviewConflict, ReviewStore


class HumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ecra 人工确认 ')
        self.addCleanup(self.tmp.cleanup)
        self.binding = dict(scan_id='s', project_id='p', facts_hash='facts', report_hash='report')
        self.a = ReviewStore(Path(self.tmp.name)/'a.db', self.binding, device='A')
        self.b = ReviewStore(Path(self.tmp.name)/'b.db', self.binding, device='B')

    def append(self, store=None, **kwargs):
        return (store or self.a).append('canonical::state', 'full-evidence', reviewer='工程师声明',
            decision=kwargs.pop('decision', 'CONFIRMED_RISK'), **kwargs)

    def test_safe_requires_basis_and_accepting_risk_is_separate(self):
        with self.assertRaisesRegex(ValueError, '依据'):
            self.append(decision='CONFIRMED_SAFE')
        self.append(handling_status='ACCEPTED_RISK')
        state = self.a.current('canonical::state', 'full-evidence')
        self.assertEqual(state['decision'], 'CONFIRMED_RISK')
        self.assertEqual(state['handling_status'], 'ACCEPTED_RISK')

    def test_reopen_preserves_decision_and_continue_position(self):
        self.append(comment='真实依据')
        self.a.position('variables', dict(search='state', offset=50, symbol='canonical::state'))
        reopened = ReviewStore(self.a.path, self.binding)
        self.assertEqual(reopened.current('canonical::state', 'full-evidence')['decision'], 'CONFIRMED_RISK')
        self.assertEqual(reopened.position('variables')['offset'], 50)
        self.assertEqual(reopened.current('canonical::state', 'changed-evidence')['decision'], 'PENDING')

    def test_undo_adds_event_and_preserves_original_and_reason(self):
        first = self.append(comment='原依据')
        self.a.undo('canonical::state', 'full-evidence', reviewer='声明', comment='误操作', expected_heads=[first['event_id']])
        self.assertEqual(self.a.current('canonical::state', 'full-evidence')['decision'], 'PENDING')
        self.assertEqual(len(self.a.history()), 2)
        self.assertEqual(self.a.history()[0]['comment'], '原依据')
        with sqlite3.connect(self.a.path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute('DELETE FROM events')

    def test_two_devices_idempotence_conflict_and_explicit_resolution(self):
        first = self.append()
        self.b.merge(self.a.history(), fingerprint_for=lambda _: 'full-evidence')
        a_second = self.append(decision='CONFIRMED_SAFE', comment='电脑A依据', expected_heads=[first['event_id']])
        b_second = self.append(self.b, decision='NEED_MORE_EVIDENCE', comment='电脑B缺口', expected_heads=[first['event_id']])
        self.assertEqual(self.a.merge(self.b.history(), fingerprint_for=lambda _: 'full-evidence'), 1)
        self.assertEqual(self.a.merge(self.b.history(), fingerprint_for=lambda _: 'full-evidence'), 0)
        current = self.a.current('canonical::state', 'full-evidence')
        self.assertTrue(current['conflict'])
        heads = [e['event_id'] for e in current['heads']]
        with self.assertRaises(ReviewConflict):
            self.append(expected_heads=heads)
        self.append(expected_heads=heads, resolve=True, comment='核对双方完整证据')
        self.assertFalse(self.a.current('canonical::state', 'full-evidence')['conflict'])
        self.assertEqual(len(self.a.history()), 4)

    def test_stale_save_tampered_repeat_missing_parent_and_wrong_binding_rejected(self):
        first = self.append()
        with self.assertRaises(ReviewConflict):
            self.append()
        bad = dict(first, comment='篡改同ID')
        with self.assertRaises(ValueError):
            self.a.merge([bad], fingerprint_for=lambda _: 'full-evidence')
        with self.assertRaises(ValueError):
            self.b.merge([dict(first, fingerprint='changed')], fingerprint_for=lambda _: 'full-evidence')
        with self.assertRaises(ValueError):
            ReviewStore(self.a.path, dict(self.binding, facts_hash='other'))
        self.assertEqual(len(self.a.history()), 1)

    def test_thousand_partial_decisions_are_transactional_and_persist(self):
        for i in range(1000):
            self.a.append(str(i), str(i), reviewer='未认证声明', decision='CONFIRMED_RISK' if i<107 else 'PENDING')
        reopened = ReviewStore(self.a.path, self.binding)
        self.assertEqual(len(reopened.history()), 1000)
        self.assertEqual(sum(e['decision'] == 'CONFIRMED_RISK' for e in reopened.history()), 107)
