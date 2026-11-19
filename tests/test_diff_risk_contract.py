"""Stage two: real extracted evidence, then symmetric comparison contracts.

Partial extraction is exercised below the publication gate. This does not
enable partial native baselines, which remains a separate implementation stage.
"""
import copy
import json
import unittest

from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.git_diff import compare, summarize
from tests import test_ecra


SAFE = 'int shared;void main(void){shared++;}void ISR(void){}'
SUSPECT = 'int shared;void main(void){shared++;}void ISR(void){shared++;}'
UNKNOWN = 'void Opaque(int*);int shared;void main(void){shared++;Opaque(&shared);}void ISR(void){}'
SHARED = 'volatile int shared;void main(void){shared=1;}void ISR(void){int value=shared;}'
PROTECTED = ('void __disable_irq(void);void __enable_irq(void);int shared;'
             'void main(void){__disable_irq();shared++;__enable_irq();}void ISR(void){shared++;}')


class RiskContractTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def snapshot(self, sources, *, compiled=None, allow_partial=False):
        for path in self.root.glob('*.c'):
            if path.name not in sources:
                path.unlink()
        cfg = self.project(sources, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                                             dict(id='irq', kind='ISR', functions=['ISR'])])
        if compiled is not None:
            database = self.root/'compile_commands.json'
            database.write_text(json.dumps([row for row in json.loads(database.read_text('utf-8'))
                                            if row['file'] in compiled]), 'utf-8')
        units, audit = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run() for unit in units]
        if not allow_partial:
            self.assertTrue(all(part['parse_status'] == 'PARSED' for part in parts), parts)
        facts = merge(parts)
        facts['translation_units'] = [dict(unit, parse_status=part['parse_status'],
            semantic_macros_digest=part.get('semantic_macros_digest'), includes=part.get('includes', []))
            for unit, part in zip(units, parts)]
        for unit in facts['translation_units']:
            if unit['parse_status'] != 'PARSED':
                facts['unknowns'].append(dict(kind='PARSE_FAILED', file=unit['source_file']))
        coverage = dict(audit, translation_units_total=len(units),
            translation_units_parsed=sum(p['parse_status'] == 'PARSED' for p in parts),
            translation_units_failed=sum(p['parse_status'] == 'FAILED' for p in parts),
            translation_units_partial=sum(p['parse_status'] == 'PARTIAL' for p in parts))
        report = analyze(facts, cfg, coverage)
        return summarize(facts, report), facts, report

    def delta(self, base, head, files=()):
        before = json.dumps([base, head], sort_keys=True)
        result = compare(base, head, dict(files=list(files), head_sha='head', base_sha='base'))
        self.assertEqual(json.dumps([base, head], sort_keys=True), before, 'comparison must not rewrite static facts')
        return result

    def changed(self, summary):
        result = copy.deepcopy(summary)
        result['functions']['c:@F@main']['digest'] += '-body-change'
        return result

    def transition(self, base, head):
        return self.delta(base, self.changed(head))['impacts']['c:@shared']['risk_transition']

    def test_R01_R09_complete_matrix_separates_discovery_proof_and_resolution(self):
        states = {name: self.snapshot({'a.c': code})[0] for name, code in
                  [('SAFE_PROVEN', SAFE), ('SUSPECT', SUSPECT), ('UNKNOWN', UNKNOWN)]}
        expected = [
            ('SAFE_PROVEN', 'SAFE_PROVEN', 'R01', 'SAFETY_RETAINED'),
            ('SAFE_PROVEN', 'SUSPECT', 'R02', 'NEW_SUSPECT'),
            ('SAFE_PROVEN', 'UNKNOWN', 'R03', 'SAFETY_PROOF_LOST'),
            ('SUSPECT', 'SAFE_PROVEN', 'R04', 'RISK_POSSIBLY_RESOLVED'),
            ('SUSPECT', 'SUSPECT', 'R05', 'SUSPECT_PERSISTS'),
            ('SUSPECT', 'UNKNOWN', 'R06', 'PRIOR_RISK_UNCLOSED'),
            ('UNKNOWN', 'SAFE_PROVEN', 'R07', 'SAFETY_PROOF_GAINED'),
            ('UNKNOWN', 'SUSPECT', 'R08', 'SUSPECT_DISCOVERED'),
            ('UNKNOWN', 'UNKNOWN', 'R09', 'STILL_UNKNOWN')]
        for before, after, case, code in expected:
            with self.subTest(case=case):
                self.assertEqual(states[before]['variables']['c:@shared']['dimensions']['classification'], before)
                result = self.transition(states[before], states[after])
                self.assertEqual((result['matrix_case'], result['code']), (case, code), result)
                self.assertEqual(result['counts_as_new_risk'], case == 'R02')
                self.assertEqual(result['counts_as_risk_resolution'], case == 'R04')
                self.assertEqual(result['prior_risk_unclosed'], before == 'SUSPECT' and case != 'R04')
                self.assertEqual(result['current_suspect'], after == 'SUSPECT')

    def test_T18_shared_is_never_a_safety_or_new_risk_shortcut(self):
        shared = self.snapshot({'a.c': SHARED})[0]
        suspect = self.snapshot({'a.c': SUSPECT})[0]
        unknown = self.snapshot({'a.c': UNKNOWN})[0]
        safe = self.snapshot({'a.c': SAFE})[0]
        self.assertEqual(shared['variables']['c:@shared']['dimensions']['classification'], 'SHARED_NO_REVIEW')
        for before, after, code in [(suspect, shared, 'EXEMPTION_GAINED'),
                (shared, suspect, 'EXEMPTION_LOST_SUSPECT'), (shared, unknown, 'EXEMPTION_LOST_UNKNOWN'),
                (shared, safe, 'EXEMPTION_TO_SAFETY'), (safe, shared, 'EXEMPTION_GAINED'),
                (unknown, shared, 'EXEMPTION_GAINED'), (shared, shared, 'EXEMPTION_RETAINED')]:
            with self.subTest(code=code):
                result = self.transition(before, after)
                self.assertEqual(result['code'], code, result)
                self.assertFalse(result['counts_as_new_risk'])
                self.assertFalse(result['counts_as_risk_resolution'])
                self.assertIsNone(result['closure'])
        broken = copy.deepcopy(shared)
        broken['variables']['c:@shared']['risk_evidence']['shared_proof'] = None
        for before, after in ((broken, suspect), (suspect, broken)):
            result = self.transition(before, after)
            self.assertEqual(result['code'], 'EXEMPTION_UNVERIFIED')
            self.assertFalse(result['counts_as_new_risk'])
            self.assertFalse(result['counts_as_risk_resolution'])

    def test_T22_all_old_conflicts_link_to_complete_current_proof(self):
        base = self.snapshot({'a.c': SUSPECT})[0]
        head = self.snapshot({'a.c': PROTECTED})[0]
        result = self.transition(base, head)
        self.assertEqual(result['matrix_case'], 'R04', result)
        closure = result['closure']
        self.assertEqual(closure['proof_code'], 'SAFE_EFFECTIVE_PROTECTION')
        self.assertEqual([item['base_conflict'] for item in closure['correspondences']],
                         base['variables']['c:@shared']['risk_evidence']['known_conflicts'])
        self.assertEqual(set(closure['current_access_ids']),
                         {a['access_id'] for a in head['variables']['c:@shared']['risk_evidence']['accesses']})
        for mutation in ('access', 'gap', 'protection', 'current_conflict', 'old_conflicts'):
            with self.subTest(mutation=mutation):
                old, new = copy.deepcopy(base), copy.deepcopy(head)
                proof = new['variables']['c:@shared']['risk_evidence']
                if mutation == 'access': proof['safe_proof']['access_ids'].pop()
                if mutation == 'gap': proof['related_gaps'].append(dict(kind='ADDRESS_ESCAPE', relevance='external writer'))
                if mutation == 'protection': proof['protection_status'] = 'NOT_FOUND'
                if mutation == 'current_conflict': proof['known_conflicts'] = old['variables']['c:@shared']['risk_evidence']['known_conflicts']
                if mutation == 'old_conflicts': old['variables']['c:@shared']['risk_evidence']['known_conflicts'] = []
                result = self.transition(old, new)
                self.assertEqual(result['comparison_status'], 'PROOF_INCOMPLETE')
                self.assertFalse(result['counts_as_risk_resolution'])
                self.assertIsNone(result['closure'])
        partial = self.snapshot({'a.c': PROTECTED.replace('__enable_irq();}', '__enable_irq();shared++;}')})[0]
        result = self.transition(base, partial)
        self.assertEqual(result['matrix_case'], 'R05', result)
        self.assertIsNone(result['closure'])

    def test_T22_partial_conflict_inventory_cannot_count_as_new_or_resolved(self):
        suspect = self.snapshot({'a.c': SUSPECT.replace('main(void){shared++;}', 'main(void){shared++;shared++;}')})[0]
        safe = self.snapshot({'a.c': SAFE})[0]
        evidence = suspect['variables']['c:@shared']['risk_evidence']
        self.assertGreater(len(evidence['known_conflicts']), 1)
        evidence['known_conflicts'].pop()
        for before, after in ((suspect, safe), (safe, suspect)):
            with self.subTest(current=after is suspect):
                result = self.transition(before, after)
                self.assertEqual(result['comparison_status'], 'PROOF_INCOMPLETE')
                self.assertFalse(result['counts_as_new_risk'])
                self.assertFalse(result['counts_as_risk_resolution'])

    def test_T18_incomplete_exemption_terms_cannot_reuse_the_shared_label(self):
        base = self.snapshot({'a.c': SUSPECT})[0]
        shared = self.snapshot({'a.c': SHARED})[0]
        for missing in ('writer_physical_context', 'reader_physical_contexts', 'atomic_width_bytes',
                        'alignment_bytes', 'compiler_visibility', 'excluded_hazards'):
            with self.subTest(missing=missing):
                incomplete = copy.deepcopy(shared)
                incomplete['variables']['c:@shared']['risk_evidence']['shared_proof'].pop(missing)
                result = self.transition(base, incomplete)
                self.assertEqual(result['code'], 'EXEMPTION_UNVERIFIED')
                self.assertFalse(result['counts_as_risk_resolution'])
        for key, value in [('atomic_width_bytes', 8), ('alignment_bytes', 1),
                           ('compiler_visibility', 'NONE'), ('writer_physical_context', 'other'),
                           ('reader_physical_contexts', ['other']), ('excluded_hazards', ['DMA'])]:
            with self.subTest(invalid=key):
                incomplete = copy.deepcopy(shared)
                incomplete['variables']['c:@shared']['risk_evidence']['shared_proof'][key] = value
                self.assertEqual(self.transition(base, incomplete)['code'], 'EXEMPTION_UNVERIFIED')
        # Both admitted scalar access forms retain valid exemption evidence.
        for code in [SHARED.replace('shared=1', 'shared++'), SHARED.replace('volatile int', '_Atomic int')]:
            with self.subTest(valid=code):
                current = self.snapshot({'a.c': code})[0]
                self.assertEqual(self.transition(base, current)['code'], 'EXEMPTION_GAINED')

    def test_T19_known_conflict_survives_related_gap(self):
        base = self.snapshot({'a.c': SUSPECT})[0]
        head = self.snapshot({'a.c': 'void Opaque(int*);' + SUSPECT.replace('main(void){', 'main(void){Opaque(&shared);')})[0]
        result = self.transition(base, head)
        self.assertEqual(result['matrix_case'], 'R05')
        self.assertEqual(result['coverage']['head']['status'], 'PARTIAL')
        self.assertTrue(result['coverage']['head']['related_gaps'])
        self.assertTrue(result['current_suspect'])

    def test_T20_T21_failed_unit_requires_object_specific_exclusion(self):
        base = self.snapshot({'a.c': 'static ' + SUSPECT, 'failed.c': 'int other;'})[0]
        head = self.snapshot({'a.c': 'static ' + SAFE, 'failed.c': '#include "missing-header.h"\n'}, allow_partial=True)[0]
        sid = next(key for key, row in base['variables'].items() if row['name'] == 'shared')
        result = self.delta(base, head)['impacts'][sid]['risk_transition']
        self.assertEqual(result['matrix_case'], 'R04', result)
        self.assertTrue(result['closure']['excluded_gaps'])
        self.assertEqual(result['closure']['excluded_gaps'][0]['proof'], 'INTERNAL_LINKAGE_SEPARATE_TU')
        base = self.snapshot({'a.c': SUSPECT, 'failed.c': 'int other;'})[0]
        head = self.snapshot({'a.c': SAFE, 'failed.c': '#include "missing-header.h"\n'}, allow_partial=True)[0]
        result = self.transition(base, head)
        self.assertEqual(result['matrix_case'], 'R06', result)
        self.assertTrue(result['coverage']['head']['related_gaps'])
        self.assertFalse(result['counts_as_risk_resolution'])

    def test_T20_unresolved_protection_does_not_defeat_an_independent_serial_proof(self):
        base = self.snapshot({'a.c': SUSPECT})[0]
        head = self.snapshot({'a.c': 'void __set_PRIMASK(int);' +
            SAFE.replace('main(void){', 'main(void){__set_PRIMASK(shared);')})[0]
        result = self.transition(base, head)
        self.assertEqual(result['matrix_case'], 'R04', result)
        self.assertEqual(result['closure']['proof_code'], 'SAFE_SINGLE_FOREGROUND')
        self.assertTrue(any(gap.get('kind') == 'PROTECTION_UNRESOLVED'
                            for gap in result['closure']['excluded_gaps']))

    def test_T20_failed_variant_exclusion_is_complete_and_symmetric(self):
        from ecra.missing_source import preprocess_failed_units
        base = self.snapshot({'a.c': SUSPECT})[0]
        head, facts, report = self.snapshot({'a.c': SAFE, 'other.c': 'int unrelated;'})
        # Model an extraction failure after successful preprocessing. Run the
        # real preprocessor for both variants; a file-name difference alone
        # must never serve as the exclusion proof for external storage.
        unit = next(u for u in facts['translation_units'] if u['source_file'] == 'other.c')
        unit['parse_status'] = 'FAILED'
        facts['translation_units'].append(dict(unit, tu_id='other-variant'))
        records = preprocess_failed_units(facts)
        self.assertEqual([r['status'] for r in records], ['COMPLETE', 'COMPLETE'])
        head = summarize(facts, report)
        result = self.transition(base, head)
        self.assertEqual(result['matrix_case'], 'R04', result)
        self.assertEqual(result['closure']['excluded_gaps'][0]['proof'], 'ALL_FAILED_VARIANTS_EXCLUDE_IDENTIFIER')
        for mutation in ('missing_variant', 'incomplete', 'name_present'):
            with self.subTest(mutation=mutation):
                broken = copy.deepcopy(head)
                records = broken['comparison_scope']['failed_preprocessing']
                if mutation == 'missing_variant': records.pop()
                if mutation == 'incomplete': records[0]['status'] = 'UNAVAILABLE'
                if mutation == 'name_present': records[0]['identifiers'].append('shared')
                result = self.transition(base, broken)
                self.assertEqual(result['comparison_status'], 'PROOF_INCOMPLETE')
                self.assertFalse(result['counts_as_risk_resolution'])

    def test_T15_T16_added_deleted_and_out_of_build_have_independent_risk(self):
        base = self.snapshot({'main.c': 'void main(void){}void ISR(void){}'})[0]
        sources = {'main.c': SUSPECT.replace('int shared;', 'extern int shared;'), 'state.c': 'int shared;'}
        head = self.snapshot(sources)[0]
        files = [dict(status='A', old_path=None, new_path='state.c')]
        delta = self.delta(base, head, files)
        impact = delta['impacts']['c:@shared']
        self.assertEqual(impact['object_change']['event'], 'ADDED')
        self.assertTrue(impact['risk_transition']['current_suspect'])
        self.assertEqual(delta['change_counts']['counts_as_new_risk'], 0)
        removed = self.delta(head, base, [dict(status='D', old_path='state.c', new_path='state.c')])
        self.assertEqual(len(removed['deleted_variables']), 1)
        self.assertEqual(removed['change_counts']['counts_as_risk_resolution'], 0)
        out = self.snapshot({'main.c': 'void main(void){}void ISR(void){}', 'state.c': 'int shared;'}, compiled=['main.c'])[0]
        moved = self.delta(head, out)
        self.assertEqual(moved['deleted_variables'], [])
        self.assertEqual(moved['baseline_only_variables'][0]['impact']['object_change']['event'], 'OUT_OF_BUILD')

    def test_T24_missing_definition_is_symmetric_and_never_a_deletion(self):
        base = self.snapshot({'main.c': 'void main(void){}', 'state.c': SUSPECT.replace('main', 'Work')})[0]
        head = self.snapshot({'main.c': 'void main(void){}', 'state.c': '#include "missing-header.h"\n'}, allow_partial=True)[0]
        for before, after in ((base, head), (head, base)):
            with self.subTest(reverse=before is head):
                delta = self.delta(before, after)
                self.assertEqual(delta['deleted_variables'], [])
                impact = (delta['impacts'].get('c:@shared') or delta['baseline_only_variables'][0]['impact'])
                self.assertEqual(impact['object_change']['event'], 'EXISTENCE_UNCERTAIN')
                self.assertEqual(delta['change_counts']['counts_as_new_risk'], 0)
                self.assertEqual(delta['change_counts']['counts_as_risk_resolution'], 0)

    def test_T14_rename_and_active_declaration_absence_keep_baseline_evidence(self):
        base = self.snapshot({'a.c': SUSPECT})[0]
        renamed = self.snapshot({'a.c': SUSPECT.replace('shared', 'renamed')})[0]
        delta = self.delta(base, renamed)
        self.assertEqual(delta['deleted_variables'], [])
        self.assertEqual(delta['impacts']['c:@renamed']['object_change']['event'], 'MATCH_UNCERTAIN')
        self.assertEqual(delta['baseline_only_variables'][0]['impact']['object_change']['event'], 'MATCH_UNCERTAIN')
        absent = self.snapshot({'a.c': '#if 0\nint shared;\n#endif\nvoid main(void){}void ISR(void){}'})[0]
        delta = self.delta(base, absent)
        self.assertEqual(delta['deleted_variables'], [])
        self.assertEqual(delta['baseline_only_variables'][0]['impact']['object_change']['event'], 'ABSENT_IN_BUILD')
        self.assertEqual(delta['change_counts']['counts_as_risk_resolution'], 0)

    def test_legacy_summary_is_explicitly_incomparable_without_rewriting_it(self):
        base = self.snapshot({'a.c': SAFE})[0]
        head = self.snapshot({'a.c': SUSPECT})[0]
        base['schema'] = 8
        base.pop('comparison_scope')
        for row in base['variables'].values():
            row.pop('risk_evidence')
            row.pop('object_evidence')
        result = self.transition(base, head)
        self.assertEqual(result['comparison_status'], 'LEGACY_EVIDENCE')
        self.assertFalse(result['counts_as_new_risk'])
        missing = self.delta(head, dict(base, variables={}))
        self.assertEqual(missing['deleted_variables'], [])
        self.assertEqual(missing['baseline_only_variables'][0]['impact']['object_change']['event'], 'EXISTENCE_UNCERTAIN')


if __name__ == '__main__':
    unittest.main()
