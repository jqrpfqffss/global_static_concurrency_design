"""Human decisions never replace static/model evidence; exercise real SQLite."""
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ecra.common import digest
from ecra.manual_review import Ledger, Conflict, progress, targets, source_evidence


def item(sid='global::g', evidence='e1'):
    return dict(variable_id=digest(['storage-v1', sid]), symbol_id=sid, variable_name=sid,
                source_file='app.c', source_location=1, analysis_scope_id='scope',
                evidence_digest=evidence, static_classification='SUSPECT', reviews=[])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.ledger = Ledger(self.out, 'project')
        self.item = item()
        self.items = {self.item['variable_id']: self.item}

    def request(self, decision='CONFIRMED_RISK', revision=0, reason='实测中断抢占'):
        return dict(self.item, decision=decision, revision=revision, reason=reason, reviewer='工程师')

    def test_restart_progress_and_duplicate_findings(self):
        self.assertEqual(self.ledger.sync(self.items)[0]['decision'], 'UNCONFIRMED')
        self.ledger.submit(self.items, self.request())
        restored = Ledger(self.out, 'project').sync(self.items)
        self.assertEqual(restored[0]['decision'], 'CONFIRMED_RISK')
        self.assertEqual(progress(restored)['percent'], 100)
        self.assertEqual(progress([])['percent'], 0)

    def test_required_safe_reason_edit_undo_and_full_history(self):
        with self.assertRaises(ValueError):
            self.ledger.submit(self.items, self.request('CONFIRMED_SAFE', reason=' \n'))
        self.ledger.submit(self.items, self.request())
        self.ledger.submit(self.items, self.request('CONFIRMED_SAFE', 1, '实测硬件串行访问'))
        self.ledger.submit(self.items, self.request('UNCONFIRMED', 2, '撤销，继续核实'))
        events = self.ledger.history(self.item['variable_id'])
        self.assertEqual([e['new_decision'] for e in events], ['CONFIRMED_RISK', 'CONFIRMED_SAFE', 'UNCONFIRMED'])
        self.assertEqual(events[1]['previous']['reason'], '实测中断抢占')
        self.assertEqual(self.ledger.sync(self.items)[0]['revision'], 3)

    def test_conflicts_bad_id_stale_scope_and_stale_evidence(self):
        request = self.request()
        self.ledger.submit(self.items, request)
        with self.assertRaises(Conflict):
            Ledger(self.out, 'project').submit(self.items, request)
        for field, value in [('variable_id', 'wrong'), ('analysis_scope_id', 'old'), ('evidence_digest', 'old')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.ledger.submit(self.items, dict(request, **{field: value}))
        self.assertEqual(len(self.ledger.history()), 1)

    def test_invalidation_is_audited_and_never_silently_restored(self):
        self.ledger.submit(self.items, self.request('CONFIRMED_SAFE'))
        changed = {self.item['variable_id']: dict(self.item, evidence_digest='e2')}
        result = self.ledger.sync(changed)
        self.assertEqual(result[0]['decision'], 'NEEDS_RECHECK')
        self.assertEqual(result[0]['previous_decision'], 'CONFIRMED_SAFE')
        self.assertEqual(progress(result)['percent'], 0)
        self.assertEqual(self.ledger.sync(self.items)[0]['decision'], 'NEEDS_RECHECK')
        self.assertEqual(len(self.ledger.history()), 2)
        self.assertEqual(self.ledger.history()[1]['old_evidence_digest'], 'e1')

    def test_invalid_source_and_out_of_scope_history(self):
        self.ledger.submit(self.items, self.request('CONFIRMED_SAFE'))
        rows = self.ledger.sync(self.items, valid=False, error='源码校验失败')
        self.assertEqual(rows[0]['decision'], 'NEEDS_RECHECK')
        self.assertEqual(self.ledger.sync({}), [])
        self.assertEqual(len(self.ledger.export()['records']), 1)
        self.assertEqual(len(self.ledger.history()), 2)

    def test_paused_reader_never_reconciles_a_stale_catalog(self):
        self.ledger.submit(self.items, self.request('CONFIRMED_SAFE'))
        updated = dict(self.item, evidence_digest='new-scan')
        self.ledger.submit({updated['variable_id']: updated}, dict(updated, decision='CONFIRMED_SAFE',
            revision=1, reason='另一个服务在新证据上确认', reviewer='工程师'))
        rows = self.ledger.paused(self.items)
        self.assertFalse(rows[0]['valid'])
        self.assertEqual(rows[0]['decision'], 'NEEDS_RECHECK')
        self.assertEqual(len(self.ledger.history()), 2)
        self.assertEqual(self.ledger.sync({updated['variable_id']: updated})[0]['decision'], 'CONFIRMED_SAFE')

    def test_transaction_rolls_back_history_if_current_write_fails(self):
        with closing(self.ledger.connect()) as db, db:
            db.execute("CREATE TRIGGER fail_write BEFORE INSERT ON current_review BEGIN SELECT RAISE(ABORT,'disk fault'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.ledger.submit(self.items, self.request())
        self.assertEqual(self.ledger.history(), [])
        self.assertEqual(self.ledger.sync(self.items)[0]['revision'], 0)

    def test_wal_backup_contains_committed_data(self):
        self.ledger.submit(self.items, self.request())
        backup = self.out / 'backup.sqlite3'
        self.ledger.backup(backup)
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM history').fetchone()[0], 1)
            self.assertIn('CONFIRMED_RISK', db.execute('SELECT payload FROM current_review').fetchone()[0])

    def test_project_isolation(self):
        self.ledger.submit(self.items, self.request())
        other = Ledger(self.out, 'another-project')
        self.assertEqual(other.sync(self.items)[0]['decision'], 'UNCONFIRMED')
        self.assertEqual(other.history(), [])

    def test_export_import_roundtrip_history_and_mismatching_evidence(self):
        self.ledger.submit(self.items, self.request('CONFIRMED_SAFE'))
        data = self.ledger.export()
        imported = Ledger(self.out / 'recovered', 'project')
        imported.import_data(self.items, data, {})
        row = imported.sync(self.items)[0]
        self.assertEqual(row['decision'], 'CONFIRMED_SAFE')
        self.assertEqual(row['confirmed_at'], data['records'][0]['confirmed_at'])
        self.assertEqual(imported.history()[0]['current']['imported_history'], data['history'])
        changed = {self.item['variable_id']: dict(self.item, evidence_digest='e2')}
        other = Ledger(self.out / 'changed', 'project')
        other.import_data(changed, data, {})
        self.assertEqual(other.sync(changed)[0]['decision'], 'NEEDS_RECHECK')
        with self.assertRaises(Conflict):
            imported.import_data(self.items, data, {})

    def test_invalid_import_is_atomic(self):
        self.ledger.submit(self.items, self.request())
        original = self.ledger.export()
        for change in ('project', 'reason', 'duplicate', 'identity', 'history'):
            document = copy.deepcopy(original)
            if change == 'project': document['project_id'] = 'foreign'
            if change == 'reason': document['records'][0].update(decision='CONFIRMED_SAFE', reason=' ')
            if change == 'duplicate': document['records'] *= 2
            if change == 'identity': document['records'][0]['symbol_id'] = 'wrong'
            if change == 'history': document['history'] = ['wrong']
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.ledger.import_data(self.items, document, {self.item['variable_id']: 1})
        self.assertEqual(self.ledger.export(), original)

    def test_progress_120_variable_acceptance_example(self):
        rows = ([dict(decision='CONFIRMED_RISK')] * 20 + [dict(decision='CONFIRMED_SAFE')] * 15
                + [dict(decision='UNCONFIRMED')] * 85)
        self.assertEqual(progress(rows)['percent'], 29.17)
        self.assertEqual(progress(rows)['total'], 120)

    def test_targets_members_containers_gaps_safe_and_duplicate_findings(self):
        variables = [dict(symbol_id=s, static_classification=c, resource_kind=r)
                     for s,c,r in [('root','SUSPECT','STRUCT_CONTAINER'), ('root.a','SUSPECT','STRUCT_MEMBER'),
                                   ('root.b','UNKNOWN','STRUCT_MEMBER'), ('safe','SAFE_PROVEN','GLOBAL'),
                                   ('shared','SHARED_NO_REVIEW','GLOBAL')]]
        report = dict(findings=[dict(symbol_id=s) for s in ['root', 'root.a', 'root.a', 'root.b', None]])
        self.assertEqual([v['symbol_id'] for v in targets(dict(variables=variables), report)], ['root.a', 'root.b'])


if __name__ == '__main__':
    unittest.main()
