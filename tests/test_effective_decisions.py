"""Static risk must survive inconclusive or unfinished semantic reviews."""
import copy
import contextlib
import io
import itertools
import json
import unittest
from collections import Counter
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ecra.common import read_json
from ecra.cli import run
from ecra.decisions import effective_decision, variable_decisions
from ecra.html_report import (REVIEW_PAGE, anchor, reviewed_variable_summary,
                              review_records, risk_summary)
from ecra.report import generate
from ecra.review import review_all
from ecra.review_integrity import review_integrity, normalize_review_record
from ecra.workflow import clean_report, analysis_config
from tests import test_ecra as fixtures
from tests.test_review_contract import answer_for


def record(outcome, fid='F'):
    if outcome == 'OFF':
        return dict(finding_id=fid, state='PENDING', status=None, error='OpenCode 自动复核已关闭')
    if outcome in {'PENDING', 'RUNNING', 'TECH_FAILED', 'FAILED', 'STALE'}:
        # Old semantic answers must never make unfinished/stale reviews safe.
        return dict(finding_id=fid, state=outcome, status='REVIEWED_SAFE', error='synthetic failure',
                    answer=answer_for('REVIEWED_SAFE', fid))
    return dict(finding_id=fid, state='DONE', status=outcome, answer=answer_for(outcome, fid))


INCONCLUSIVE = ('OFF', 'PENDING', 'RUNNING', 'TECH_FAILED', 'FAILED', 'STALE', 'NEED_MORE_CONTEXT')


class DecisionTests(unittest.TestCase):
    def test_complete_static_review_matrix_without_mutation(self):
        for static, outcome in itertools.product(('SUSPECT', 'UNKNOWN'), INCONCLUSIVE + (
                'CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE')):
            with self.subTest(static=static, outcome=outcome):
                finding = dict(finding_id='F', static_classification=static, rules=['GS-MULTI-WRITER'])
                review = record(outcome)
                before = copy.deepcopy((finding, review))
                expected = {'CONFIRMED': 'confirmed', 'LIKELY': 'likely',
                            'REVIEWED_SAFE': 'safe', 'FALSE_POSITIVE': 'safe'}.get(
                                outcome, 'likely' if static == 'SUSPECT' else 'unresolved')
                self.assertEqual(effective_decision(finding, review), expected)
                self.assertEqual((finding, review), before)
                self.assertEqual(effective_decision(finding, normalize_review_record(review)), expected)

    def test_missing_record_uses_static_not_concurrent_rules_or_cached_static(self):
        for static, expected in [('SUSPECT', 'likely'), ('UNKNOWN', 'unresolved')]:
            finding = dict(static_classification=static, rules=['GS-MULTI-WRITER'])
            self.assertEqual(effective_decision(finding, {}), expected)
            self.assertEqual(effective_decision(finding, dict(
                state='PENDING', static_classification='UNKNOWN' if static == 'SUSPECT' else 'SUSPECT')), expected)
            self.assertEqual(effective_decision({}, {}, variable=finding), expected)

    def test_variable_aggregation_is_order_independent_and_keeps_strongest_risk(self):
        facts = dict(variables=[dict(symbol_id='shared', static_classification='SUSPECT')])
        for first, second, expected in [
                ('LIKELY', 'NEED_MORE_CONTEXT', 'likely'),
                ('CONFIRMED', 'NEED_MORE_CONTEXT', 'confirmed'),
                ('REVIEWED_SAFE', 'NEED_MORE_CONTEXT', 'unresolved'),
                ('FALSE_POSITIVE', 'LIKELY', 'likely'),
                ('REVIEWED_SAFE', 'FALSE_POSITIVE', 'safe')]:
            findings = [dict(finding_id='A', symbol_id='shared', static_classification='SUSPECT'),
                        dict(finding_id='B', symbol_id='shared', static_classification='UNKNOWN')]
            for order in itertools.permutations(findings):
                with self.subTest(first=first, second=second, order=[f['finding_id'] for f in order]):
                    records = dict(A=record(first, 'A'), B=record(second, 'B'))
                    report = dict(findings=list(order))
                    self.assertEqual(variable_decisions(facts, report, records)['shared'], expected)
                    headline = reviewed_variable_summary(list(order), records, facts['variables'][0])[0]
                    self.assertEqual(headline, {'confirmed': '已确认并发风险', 'likely': '疑似并发风险',
                                               'unresolved': '无法判断', 'safe': '已复核安全'}[expected])

    def test_no_finding_does_not_erase_static_suspect_or_unknown(self):
        facts = dict(variables=[dict(symbol_id=s, static_classification=s) for s in ('SUSPECT', 'UNKNOWN')])
        self.assertEqual(variable_decisions(facts, dict(findings=[]), {}),
                         dict(SUSPECT='likely', UNKNOWN='unresolved'))

    def test_parse_failure_does_not_erase_a_confirmed_semantic_review(self):
        facts = dict(variables=[dict(symbol_id='shared', static_classification='UNKNOWN', parse_status='FAILED')])
        report = dict(findings=[dict(finding_id='F', symbol_id='shared', static_classification='UNKNOWN')])
        for outcome, expected in [('CONFIRMED', 'confirmed'), ('REVIEWED_SAFE', 'safe'),
                                  ('NEED_MORE_CONTEXT', 'unresolved')]:
            self.assertEqual(variable_decisions(facts, report, {'F': record(outcome)})['shared'], expected)

    def test_integrity_rejects_a_review_copy_that_changed_static_classification(self):
        report = dict(findings=[dict(finding_id='F', static_classification='SUSPECT')])
        review = dict(record('NEED_MORE_CONTEXT'), static_classification='UNKNOWN')
        self.assertTrue(any('静态分类不一致' in e for e in review_integrity(report, [review])['errors']))
        self.assertEqual(effective_decision(report['findings'][0], review), 'likely')


class ExportTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self):
        cfg = self.project({'app.c': 'int counter; extern int external_value;\n'
            'void ISR(void){counter++;}\nvoid Task(void){counter++;(void)external_value;}\n'})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        facts = read_json(self.root / '.ecra/facts.json')
        report = clean_report(read_json(self.root / '.ecra/reports/global_static_concurrency.json'))
        self.assertEqual(Counter(v.get('static_classification') for v in facts['variables']),
                         {'SUSPECT': 1, 'UNKNOWN': 1})
        return cfg, facts, report

    def test_exports_and_headlines_share_matrix_and_preserve_raw_status(self):
        _, facts, original = self.scan()
        before_facts = copy.deepcopy(facts)
        static = {f['finding_id']: f['static_classification'] for f in original['findings']}
        for outcome in INCONCLUSIVE + ('CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE'):
            with self.subTest(outcome=outcome):
                report = copy.deepcopy(original)
                reviews = [record(outcome, f['finding_id']) for f in report['findings']]
                before_reviews = copy.deepcopy(reviews)
                out = self.root / '.ecra' / outcome
                out.mkdir()
                generate(out, facts, report, reviews)
                exported = read_json(out / 'reports/global_static_concurrency.json')
                records = {r['finding_id']: r for r in review_records(report, reviews)}
                summary = risk_summary(facts, report, records)
                self.assertEqual(exported['risk_summary'], summary)
                expected = ({'likely': 1, 'unresolved': 1} if outcome in INCONCLUSIVE
                            else {'confirmed': 2} if outcome == 'CONFIRMED'
                            else {'likely': 2} if outcome == 'LIKELY' else {'safe': 2})
                self.assertEqual({k: n for k, n in summary['counts'].items() if n}, expected)
                html = (out / 'index.html').read_text(encoding='utf-8')
                review_html = (out / REVIEW_PAGE).read_text(encoding='utf-8')
                markdown = (out / 'reports/global_static_concurrency.md').read_text(encoding='utf-8')
                review_md = (out / 'reports/opencode_global_static_review.md').read_text(encoding='utf-8')
                for variable in summary['variables']:
                    group = variable['decision']
                    self.assertIn(f'data-decision-filter="{group}"><strong>{summary["counts"][group]}</strong>', html)
                    for text in (html, markdown, review_md):
                        self.assertIn(variable['label'], text)
                for finding in exported['findings']:
                    fid = finding['finding_id']
                    self.assertEqual(finding['static_classification'], static[fid])
                    self.assertEqual(finding['effective_decision'], effective_decision(finding, records[fid]))
                    self.assertEqual(finding['review_status'], outcome if outcome not in INCONCLUSIVE[:-1] else None)
                    section = review_html.split('id="' + anchor('review-', fid) + '"', 1)[1].split('</tr>', 1)[0]
                    self.assertIn('data-group', review_html)
                    self.assertIn('decision ' + finding['effective_decision'], section)
                    self.assertIn('OpenCode：', section)
                    if outcome == 'TECH_FAILED':
                        self.assertIn('OpenCode复核失败', section)
                    if outcome == 'NEED_MORE_CONTEXT':
                        self.assertEqual(finding['review_result']['answer']['status'], outcome)
                self.assertEqual(clean_report(report), clean_report(original))
                self.assertEqual(facts, before_facts)
                self.assertEqual(reviews, before_reviews)

    def test_review_enabled_switch_keeps_static_counts_through_queue_and_receipts(self):
        cfg, facts, report = self.scan()
        before = copy.deepcopy((facts, report))
        baseline = None
        for mode in ('OFF', 'PENDING', 'NEED_MORE_CONTEXT', 'TECH_FAILED'):
            with self.subTest(mode=mode):
                config = copy.deepcopy(cfg)
                config['review'].update(enabled=mode != 'OFF', retries=0, workers=1)
                self.assertEqual(analysis_config(config), analysis_config(cfg))
                out = self.root / '.ecra' / ('queue-' + mode)
                if mode == 'PENDING':
                    reviews = [dict(finding_id=f['finding_id'], state='PENDING') for f in report['findings']]
                else:
                    def respond(argv, **kwargs):
                        packet = read_json(Path(argv[argv.index('--file') + 1]))
                        self.assertEqual(packet['variable']['static_classification'],
                                         next(f['static_classification'] for f in report['findings']
                                              if f['finding_id'] == packet['finding_id']))
                        answer = answer_for('NEED_MORE_CONTEXT', packet['finding_id'])
                        return CompletedProcess([], 1, '', 'synthetic transport failure') if mode == 'TECH_FAILED' else (
                            CompletedProcess([], 0, json.dumps(answer), ''))
                    with patch('ecra.review.resolve_command', return_value=['synthetic-cli']), patch(
                            'ecra.review.execute', side_effect=respond) as execute:
                        reviews = review_all(self.root, out, config, facts, report, 'scan', lambda _: None)
                        if mode == 'OFF':
                            execute.assert_not_called()
                    self.assertEqual(read_json(out / 'review/queue.json'), reviews)
                    for review in reviews:
                        finding = next(f for f in report['findings'] if f['finding_id'] == review['finding_id'])
                        self.assertEqual(review['static_classification'], finding['static_classification'])
                        if mode != 'OFF':
                            self.assertEqual(read_json(out / 'review' / (review['finding_id'] + '.result.json')), review)
                            self.assertEqual(review['state'], 'DONE' if mode == 'NEED_MORE_CONTEXT' else 'TECH_FAILED')
                summary = risk_summary(facts, report, {r['finding_id']: r for r in reviews})
                if baseline is None:
                    baseline = summary
                self.assertEqual(summary, baseline)
                self.assertEqual(summary['counts']['likely'], 1)
                self.assertEqual(summary['counts']['unresolved'], 1)
                self.assertEqual((facts, report), before)

    def test_mixed_findings_show_the_variable_decision_on_every_review_card(self):
        _, facts, original = self.scan()
        source = next(f for f in original['findings'] if f['static_classification'] == 'SUSPECT')
        sid = source['symbol_id']
        for outcome, expected in [('LIKELY', 'likely'), ('CONFIRMED', 'confirmed')]:
            report = copy.deepcopy(original)
            other = dict(copy.deepcopy(source), finding_id=source['finding_id'] + '-gap',
                         static_classification='UNKNOWN')
            report['findings'].append(other)
            reviews = [record(outcome if f['finding_id'] == source['finding_id'] else 'NEED_MORE_CONTEXT',
                              f['finding_id']) for f in report['findings']]
            out = self.root / '.ecra' / ('mixed-' + outcome)
            out.mkdir()
            generate(out, facts, report, reviews)
            variable = next(v for v in report['risk_summary']['variables'] if v['symbol_id'] == sid)
            self.assertEqual(variable['decision'], expected)
            review_html = (out / REVIEW_PAGE).read_text(encoding='utf-8')
            for finding in (source, other):
                section = review_html.split('id="' + anchor('review-', finding['finding_id']) + '"', 1)[1].split('</tr>', 1)[0]
                self.assertIn('变量最终分类', section)
                self.assertIn('decision ' + expected, section)
            for name in ('global_static_concurrency.md', 'opencode_global_static_review.md'):
                text = (out / 'reports' / name).read_text(encoding='utf-8')
                self.assertEqual(text.count('变量最终分类：' + variable['label']), 2)
            # Review details still describe the raw uncertainty, not an invented LIKELY answer.
            self.assertEqual(next(r for r in reviews if r['finding_id'] == other['finding_id'])['status'],
                             'NEED_MORE_CONTEXT')

    def test_packets_never_include_derived_decisions_from_a_published_report(self):
        from ecra.review import build_variable_review_packet
        _, facts, report = self.scan()
        finding = copy.deepcopy(report['findings'][0])
        kwargs = dict(facts_path=self.root / '.ecra/facts.json',
                      shared_path=self.root / '.ecra/review/project-evidence.json',
                      report_path=self.root / '.ecra/review/static-report.json')
        before = build_variable_review_packet(self.root, facts, finding, **kwargs)
        finding.update(effective_decision='safe', decision_label='OLD_DERIVED_LABEL')
        after = build_variable_review_packet(self.root, facts, finding, **kwargs)
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
