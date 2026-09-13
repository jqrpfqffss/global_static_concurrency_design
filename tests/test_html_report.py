import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from ecra.html_report import REVIEW_PAGE, anchor, write_html, review_label, rule_summary, decision, variable_decisions, risk_overview, snapshot_scenario


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.links, self.groups, self.scripts = [], [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a':
            self.links.append(attrs.get('href', ''))
        if tag == 'tr' and 'data-group' in attrs:
            self.groups.append(attrs['data-group'])
        if tag == 'script':
            self.scripts.append(attrs)


class ReportTests(unittest.TestCase):
    def test_snapshot_scenario_requires_matching_source_and_context_evidence(self):
        contexts = {'main': {'kind':'MAIN'}, 'irq': {'kind':'ISR'}}
        def access(kind, function, line, context, path=''):
            return dict(access_kind=kind, function_id=function, file='app.c', line=line,
                        access_path=path, contexts=[context], call_chains={context:[function]},
                        source_text=f'code_at_{line};')
        read = access('READ','poll',10,'main')
        irq = access('RMW','interrupt',20,'irq')
        write = access('WRITE','poll',30,'main')
        finding = dict(rules=['GS-STALE-SNAPSHOT'], snapshots=[{'function_id':'poll'}], accesses=[read,irq,write])
        self.assertEqual(snapshot_scenario(finding, contexts), [('main',read),('irq',irq),('main',write)])
        write['access_path'] = '.other'
        self.assertIsNone(snapshot_scenario(finding, contexts))
        write['access_path'] = ''
        write['line'] = 5
        self.assertIsNone(snapshot_scenario(finding, contexts))
        write['line'] = 30
        irq['call_chains'] = {}
        self.assertIsNone(snapshot_scenario(finding, contexts))
        irq['call_chains'] = {'irq':['interrupt']}
        read['access_kind'] = 'ADDRESS_TAKEN'
        self.assertIsNone(snapshot_scenario(finding, contexts))

    def test_risk_decisions_do_not_confuse_gaps_or_unfinished_reviews_with_safety(self):
        shared = dict(finding_id='A', symbol_id='a', rules=['GS-MULTI-WRITER'])
        gap = dict(finding_id='B', symbol_id='b', rules=['GS-NO-ACCESS-EVIDENCE'])
        self.assertEqual(decision(shared, {}), 'likely')
        self.assertEqual(decision(gap, {}), 'unresolved')
        self.assertEqual(decision(shared, dict(state='DONE', status='CONFIRMED')), 'confirmed')
        self.assertEqual(decision(shared, dict(state='DONE', status='REVIEWED_SAFE')), 'safe')
        self.assertEqual(decision(shared, dict(state='STALE', status='REVIEWED_SAFE')), 'likely')
        self.assertEqual(decision(gap, dict(state='FAILED', status='CONFIRMED')), 'unresolved')
        facts = dict(variables=[dict(symbol_id=s) for s in ['a', 'b', 'c']])
        report = dict(findings=[shared, gap, dict(finding_id='D', symbol_id=None, rules=['INDIRECT_CALL'])], coverage={})
        records = {'D': dict(state='DONE', status='CONFIRMED')}
        result = variable_decisions(facts, report, records)
        self.assertEqual(result, dict(a='likely', b='unresolved', c='inventory'))
        html = risk_overview(facts, report, records, result)
        self.assertIn('发现疑似并发风险', html)
        self.assertNotIn('已确认存在并发风险', html)  # A confirmed gap is not a confirmed variable.
        self.assertIn('data-decision-filter="confirmed"><strong>0</strong>', html)
        self.assertIn('data-decision-filter="likely"><strong>1</strong>', html)
        self.assertIn('data-decision-filter="unresolved"><strong>1</strong>', html)

    def test_two_reports_preserve_identities_paths_and_unfinished_results(self):
        # Same name, different storage identities; a diamond graph has two paths
        # although context propagation retains a single shortest witness.
        functions = [dict(function_id=f, name=f, file='app.c', line=i+1)
                     for i, f in enumerate(['Task', 'ISR', 'Left', 'Right', 'Use'])]
        calls = [dict(caller_function_id=a, callee_function_id=b, callee_name=b,
                      file='app.c', line=i+1, call_kind=kind)
                 for i, (a, b, kind) in enumerate([
                     ('Task', 'Left', 'DIRECT'), ('Task', 'Right', 'DIRECT'),
                     ('Left', 'Use', 'DIRECT'), ('Right', 'Use', 'INDIRECT_RESOLVED'),
                     ('ISR', 'Use', 'CONFIGURED'), ('Use', 'Use', 'DIRECT')])]
        access = dict(symbol_id='a::state', function_id='Use', access_kind='RMW', file='app.c', line=5,
                      source_text='state++; /* </script><script>BAD()</script> */', contexts=['task', 'irq'],
                      call_chains={'task': ['Task', 'Left', 'Use'], 'irq': ['ISR', 'Use']},
                      protection_evidence=[dict(event_kind='lock_exit', line=4)])
        variables = [dict(symbol_id=sid, name='state', qualified_name='state', kind='FILE_STATIC',
                          definition_file=file, definition_line=1, type='unsigned', size_bytes=4,
                          alignment_bytes=4, is_const=False, is_volatile=True, translation_units=[file],
                          readers=['task', 'irq'] if i == 0 else [], writers=['task', 'irq'] if i == 0 else [],
                          audit_status='REVIEW_REQUIRED' if i == 0 else 'NO_CANDIDATE_IN_MODELED_PATHS',
                          accesses=[access] if i == 0 else [])
                     for i, (sid, file) in enumerate([('a::state', 'a.c'), ('b::state', 'b.c')])]
        facts = dict(variables=variables, functions=functions, calls=calls, contexts=[
            dict(id='task', kind='TASK', priority=4), dict(id='irq', kind='ISR', priority=2)],
            unknowns=[dict(kind='EXTERNAL_CALLEE', file='app.c', line=8)], translation_units=[])
        findings = [dict(finding_id='F'+str(i), symbol_id='a::state' if i == 0 else None,
                         variable_name='state' if i == 0 else 'coverage_gap', risk_level='HIGH', confidence='MEDIUM',
                         rules=['GS-MULTI-WRITER'], definition=dict(file='a.c', line=1),
                         protection_status='PARTIAL', accesses=[access], context_pairs=[['task', 'irq']],
                         concurrency_reason='任务读改写期间被中断覆盖', uncertainties=[])
                    for i in range(7)]
        report = dict(findings=findings, coverage=dict(unknown_accesses=1, unlisted_sources=['lost.c']),
                      analysis_status='INCOMPLETE', run_status='INCOMPLETE', limitations=['真实保护范围仍须核对'])
        reviews = [dict(finding_id='F'+str(i), state=state, status=status,
                        answer=dict(reason='理由', interleaving='交错过程', protection='锁外清理',
                                    impact='事件丢失', fix='移动清理', verification='检查抢占',
                                    evidence=[dict(file='a.c', line=1)]))
                   for i, (state, status) in enumerate([
                       ('DONE', 'CONFIRMED'), ('DONE', 'LIKELY'), ('DONE', 'REVIEWED_SAFE'),
                       ('DONE', 'FALSE_POSITIVE'), ('FAILED', 'CONFIRMED'), ('STALE', 'REVIEWED_SAFE')])]
        reviews[4]['answer']['reason'] = 'FAILED_OLD_REASON_MUST_NOT_BE_CURRENT'
        reviews[5]['answer']['reason'] = 'STALE_SAFE_REASON_MUST_NOT_BE_CURRENT'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_html(out, facts, report, reviews)
            first = (out/'index.html').read_text(encoding='utf-8')
            second = (out/REVIEW_PAGE).read_text(encoding='utf-8')
        inventory, review = Document(first), Document(second)
        self.assertIn(anchor('var-', 'a::state'), inventory.ids)
        self.assertIn(anchor('var-', 'b::state'), inventory.ids)
        self.assertEqual(len(inventory.ids), len(set(inventory.ids)))
        self.assertEqual(review.groups, ['confirmed', 'likely', 'safe', 'safe', 'unresolved', 'unresolved', 'unresolved'])
        self.assertIn('lost.c', first)
        self.assertIn('priority', first)
        self.assertIn('lock_exit', first)
        self.assertNotIn('<script>BAD()', first + second)
        self.assertEqual(len(inventory.scripts), 2)  # inert graph data + local UI
        self.assertTrue(all('src' not in s for s in inventory.scripts + review.scripts))
        graph = json.loads(first.split('<script type="application/json" id="call-graph">')[1].split('</script>')[0])
        self.assertEqual(graph['calls'], calls)
        # Stale/failed answers remain auditable in the collapsed raw receipt,
        # but never populate a current explanation or cited-source table.
        for index, sentinel in [(4, 'FAILED_OLD_REASON_MUST_NOT_BE_CURRENT'), (5, 'STALE_SAFE_REASON_MUST_NOT_BE_CURRENT')]:
            section = second.split('id="' + anchor('review-', 'F'+str(index)) + '"')[1].split('id="' + anchor('review-', 'F'+str(index+1)) + '"')[0]
            self.assertEqual(section.count(sentinel), 1)
            self.assertNotIn('<p>' + sentinel, section)
            self.assertIn('有效复核引用的源码（0 处）', section)
            self.assertIn('旧回答已失效', section)
        self.assertLess(first.index('<section id="risks"'), first.index('<section id="inventory"'))
        self.assertIn('读改写', first)
        self.assertIn('任务 task', first)
        self.assertIn('中断 irq', first)
        for link in inventory.links:
            if link.startswith(REVIEW_PAGE+'#'):
                self.assertIn(link.split('#')[1], review.ids)
        for link in review.links:
            if link.startswith('index.html#'):
                self.assertIn(link.split('#')[1], inventory.ids)

    def test_local_mode_unknown_rules_and_empty_scope_are_readable(self):
        facts = dict(variables=[], functions=[], calls=[], contexts=[], unknowns=[], translation_units=[])
        finding = dict(finding_id='unknown', symbol_id=None, variable_name='coverage_gap',
                       definition={'file': 'Drivers/vendor.c', 'line': 9}, rules=['FUTURE_RULE'],
                       risk_level='MEDIUM', accesses=[], scope_role='dependency_evidence')
        report = dict(findings=[finding], coverage=dict(audit_scope=dict(include_dirs=['Core'],
                      exclude_dirs=['Drivers', 'Vendor'], variables_selected=0, variables_omitted=18),
                      translation_units_parsed=2, translation_units_total=2),
                      analysis_status='INCOMPLETE', limitations=[])
        record = dict(finding_id='unknown', state='PENDING', status='NEED_MORE_CONTEXT',
                      error='OpenCode 自动复核已关闭；证据包已生成')
        self.assertEqual(rule_summary(finding)[0][1], 'FUTURE_RULE')
        self.assertIn('未启用模型', review_label(record))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_html(out, facts, report, [record])
            for name in ['index.html', REVIEW_PAGE]:
                text = (out / name).read_text(encoding='utf-8')
                self.assertIn('模型复核未启用', text)
                self.assertIn('范围外 18 个变量不排查', text)
                self.assertNotIn('检查 OpenCode 配置或错误信息', text)
                self.assertIn('data-file="Drivers/vendor.c"', text)
            self.assertIn('data-scope="dependency"', (out / 'index.html').read_text(encoding='utf-8'))
            # No findings is a valid inventory-only view, not a JS initialization error.
            report['findings'] = []
            write_html(out, facts, report, [])
            text = (out / 'index.html').read_text(encoding='utf-8')
            self.assertIn('没有匹配记录', text)
            self.assertIn('id="file-filter"', text)
            self.assertIn('id="risks" class="panel"', text)


if __name__ == '__main__':
    unittest.main()
