"""Real Clang packets, synthetic protocol checks, and opt-in real model review.

Mocks only test transport/contract compatibility. They do not establish model
reasoning quality. The live check is separate and saves inspectable transcripts.
"""
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

import yaml

from ecra.cli import safe_review_samples
from ecra.common import read_json, write_json
from ecra.review import build_variable_review_packet, review_all, verify_receipt
from tests import test_ecra as fixtures
from tests.test_review_contract import answer_for
from ecra.review_summary import summary_value
from tests.live_review_archive import archive_sources


BASE = Path(__file__).parent / 'fixtures'
LIBRARY = Path(__file__).resolve().parents[1] / 'config' / 'concurrency_cases.md'
CASES = [
    ('stale_writeback/unsafe_direct_writeback.c', {'CONFIRMED', 'LIKELY'}),
    ('deep_review/chain.c', {'CONFIRMED', 'LIKELY'}),
    ('deep_review/coherence.c', {'CONFIRMED', 'LIKELY'}),
    ('deep_review/dma.c', {'LIKELY', 'NEED_MORE_CONTEXT'}),
    ('stale_writeback/safe_irq_protected.c', {'REVIEWED_SAFE', 'FALSE_POSITIVE'}),
    ('stale_writeback/unknown_preemption.c', {'LIKELY', 'NEED_MORE_CONTEXT'}),
]


class DeepReviewTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def prepare_case(self, filename):
        semantics = yaml.safe_load((BASE / 'stale_writeback/semantics.yaml').read_text(encoding='utf-8'))
        cfg = self.project({'app.c': (BASE / filename).read_text(encoding='utf-8'),
                            'fixture.h': (BASE / 'stale_writeback/fixture.h').read_text(encoding='utf-8')},
                           contexts=semantics['contexts'])
        cfg['project'].update(semantics['project'])
        cfg['analysis']['auto_contexts'] = False
        facts, report = self.extract(cfg)
        target = 'g_value[0]' if filename == 'deep_review/dma.c' else 'g_value'
        variable = next(v for v in facts['variables'] if v['qualified_name'] == target)
        finding = next((f for f in report['findings'] if f.get('symbol_id') == variable['symbol_id']), None)
        if finding is None:
            finding = next(f for f in safe_review_samples(facts, len(facts['variables']))
                           if f['symbol_id'] == variable['symbol_id'])
        report['findings'] = [finding]
        report.pop('review_safe_samples', None)
        cfg['review'].update(enabled=True, workers=1, retries=0, timeout_seconds=300)
        out = self.root / '.ecra' / Path(filename).stem
        write_json(out / 'facts.json', facts)
        cfg['review']['facts_path'] = str(out / 'facts.json')
        packet = build_variable_review_packet(self.root, facts, finding, facts_path=out/'facts.json',
            shared_path=out/'review/project-evidence.json', report_path=out/'review/static-report.json')
        return cfg, facts, report, packet, out

    def test_six_real_packets_reach_opencode_with_latest_case_index(self):
        for filename, expected in CASES:
            with self.subTest(filename=filename):
                cfg, facts, report, packet, out = self.prepare_case(filename)
                calls = []
                # Deliberately synthetic result: verify legal states still pass
                # the unmodified parser, not that a model reasons this way.
                status = ('REVIEWED_SAFE' if 'safe_irq_protected' in filename else
                          'NEED_MORE_CONTEXT' if 'unknown' in filename or '/dma.' in filename else 'CONFIRMED')
                value = answer_for(status, packet['finding_id'], variable=report['findings'][0]['variable_name'])
                value['evidence'] = [dict(file='app.c', line=2, claim='当前测试声明。')]
                if status == 'REVIEWED_SAFE':
                    value.update(reason='整个 READ 到 WRITEBACK 窗口都在 __disable_irq 保护内，阻止 HIGH 抢占。',
                                 interleaving='LOW 读实参和写回都在关中断范围内；HIGH 不能插入。',
                                 protection='READ 到 WRITEBACK 均完整保护，非单条原子 store 证明。')
                    value['stale_writeback_assessment'] = dict(applicable=True, blocked=True,
                        reason='PRIMASK临界区覆盖整个READ到WRITEBACK窗口，阻止HIGH插入。',
                        evidence=[dict(file='app.c', line=6)])

                def respond(argv, **kwargs):
                    calls.append((argv, kwargs))
                    return CompletedProcess(argv, 0, json.dumps(value, ensure_ascii=False), '')

                with patch('ecra.review.resolve_command', return_value=['synthetic-opencode']), patch(
                        'ecra.review.execute', side_effect=respond):
                    row = review_all(self.root, out, cfg, facts, report, 'fixture',
                        mode='review', case_library_path=LIBRARY, progress=lambda _: None)[0]
                self.assertEqual(row['state'], 'DONE')
                self.assertIn(row['status'], expected)
                self.assertEqual(len(calls), 1)
                argv, kwargs = calls[0]
                actual_packet = read_json(Path(argv[argv.index('--file') + 1]))
                self.assertEqual(actual_packet, packet)
                self.assertEqual(actual_packet['access_count'], len(packet['accesses']))
                self.assertIn('CASE-0001', kwargs.get('input') or argv[-1])
                if '/chain.' in filename:
                    names = {f['name'] for f in packet['functions']}
                    self.assertTrue({'Setter', 'FunctionA', 'FunctionB'} <= names)
                if '/coherence.' in filename:
                    self.assertIn('HIGH_IRQHandler', {f['name'] for f in packet['functions']})
                    self.assertIn('g_length', (self.root/'app.c').read_text(encoding='utf-8'))
                if '/dma.' in filename:
                    self.assertIn('board_start_rx', json.dumps(packet, ensure_ascii=False))
                    self.assertTrue(packet['unknowns'] or packet['address_escapes'])
                if 'unknown' in filename:
                    self.assertIn('UNKNOWN_PREEMPTION', json.dumps(packet))
                verify_receipt(self.root, out/'review', row)

    def test_three_cli_entries_use_actual_config_adjacent_library(self):
        import contextlib
        import io
        import tempfile
        from ecra.cli import main
        cfg = self.project({'app.c': 'int g,h;\nvoid ISR(void){g++;h++;}\nvoid Task(void){g++;h++;}\n'},
                           review=dict(enabled=True, retries=0, workers=1))
        cfg['project']['root'] = str(self.root)
        config_dir = tempfile.TemporaryDirectory(prefix='工具 配置 ')
        self.addCleanup(config_dir.cleanup)
        config = Path(config_dir.name) / 'semantics.yaml'
        config.write_text(json.dumps(cfg), encoding='utf-8')
        library = config.with_name('concurrency_cases.md')
        library.write_text('## CASE-CLI｜初始\n**分类：** R20\n**识别线索：** CLI_INITIAL\n', encoding='utf-8')
        prompts, fail = [], False

        def respond(argv, **kwargs):
            packet = read_json(Path(argv[argv.index('--file')+1]))
            prompts.append(kwargs.get('input') or argv[-1])
            if fail:
                return CompletedProcess(argv, 1, '', 'synthetic transport error')
            answer = answer_for('REVIEWED_SAFE', packet['finding_id'], variable=packet['variable'].get('canonical_path', packet['variable']['qualified_name']))
            answer['evidence'] = [dict(file='app.c', line=2, claim='模拟协议测试')]
            return CompletedProcess(argv, 0, json.dumps(answer), '')

        with contextlib.redirect_stdout(io.StringIO()), patch('ecra.review.resolve_command',
                return_value=['synthetic-opencode']), patch('ecra.review.execute', side_effect=respond):
            self.assertEqual(main(['run', '--config', str(config)]), 1)
            self.assertTrue(prompts)
            self.assertTrue(all('CLI_INITIAL' in p and str(library.resolve()) in p for p in prompts))
            before = read_json(self.root/'.ecra/facts.json')
            library.write_text(library.read_text(encoding='utf-8') +
                '\n## CASE-CLI-NEW｜追加\n**分类：** R20\n**识别线索：** CLI_NEW\n', encoding='utf-8')
            fail = True
            self.assertEqual(main(['review', '--config', str(config)]), 2)
            fail = False
            self.assertEqual(main(['review-failed', '--config', str(config)]), 1)
            self.assertTrue(all('CLI_NEW' in p for p in prompts[2:]))
            self.assertEqual(read_json(self.root/'.ecra/facts.json'), before)
            self.assertTrue((self.root/'.ecra/index.html').is_file())

    @unittest.skipUnless(os.environ.get('ECRA_DEEP_REVIEW_LIVE') == '1', 'opt-in real OpenCode review')
    def test_live_six_cases(self):
        import shutil
        import tempfile
        archive = Path(os.environ.get('ECRA_DEEP_REVIEW_ARCHIVE', str(
            Path(tempfile.gettempdir()) / 'ecra-deep-review-live'))).resolve()
        archive.mkdir(parents=True, exist_ok=True)
        observations = []
        selected = os.environ.get('ECRA_DEEP_REVIEW_CASE_FILTER', '').split(',')
        for filename, expected in CASES:
            if selected != [''] and not any(term in filename for term in selected):
                continue
            with self.subTest(filename=filename):
                cfg, facts, report, packet, out = self.prepare_case(filename)
                if os.environ.get('ECRA_DEEP_REVIEW_MODEL'):
                    cfg['review']['model'] = os.environ['ECRA_DEEP_REVIEW_MODEL']
                if os.environ.get('ECRA_REVIEW_LIVE_TIMEOUT'):
                    cfg['review']['timeout_seconds'] = float(os.environ['ECRA_REVIEW_LIVE_TIMEOUT'])
                row = review_all(self.root, out, cfg, facts, report, 'fixture',
                    mode='review', case_library_path=LIBRARY)[0]
                baseline = row.get('answer')
                if filename == CASES[0][0] and row['state'] == 'DONE':
                    # Exercise the real SUMMARY_FIX on authenticated model output,
                    # without editing the answer, status, source, or receipt.
                    limit = min(60, len(summary_value(baseline)) - 1)
                    cfg['review']['summary'].update(max_chars=limit)
                    row = review_all(self.root, out, cfg, facts, report, 'fixture',
                        mode='run', case_library_path=LIBRARY)[0]
                target = archive / Path(filename).stem
                shutil.copytree(out, target, dirs_exist_ok=True)
                # Include generated files if cited, preserving their relative paths.
                archive_sources(self.root, target, row)
                raw = '\n'.join(p.read_text(encoding='utf-8') for p in (target/'review').glob('*.ANALYZE.jsonl'))
                tool_reads = []
                for line in raw.splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    part = event.get('part') or {}
                    state = part.get('state') or {}
                    if event.get('type') == 'tool_use' and part.get('tool') == 'read' and state.get('status') == 'completed':
                        tool_reads.append(state.get('input', {}).get('filePath', ''))
                case_body_read = any('case-library' in p and not p.endswith('.index.md') for p in tool_reads)
                observation = dict(fixture=filename, state=row['state'], status=row.get('status'),
                    error=row.get('error'), answer=row.get('answer'),
                    case_body_read=case_body_read, source_read=any(p.endswith('app.c') for p in tool_reads),
                    model=(row.get('execution') or {}).get('model'),
                    prompt_chars=len((out/'review'/row['prompt_file']).read_text(encoding='utf-8')),
                    attempts=row.get('attempt_count'), summary_fix_count=row.get('summary_fix_count', 0),
                    summary_before=summary_value(baseline) if baseline else None,
                    summary_after=summary_value(row['answer']) if row.get('answer') else None)
                observations.append(observation)
                write_json(archive/'observations.json', observations)
                self.assertEqual(row['state'], 'DONE', row.get('error'))
                self.assertIn(row['status'], expected, row.get('answer'))
                self.assertTrue(case_body_read, 'real tool log must show a completed case-body read')
                verify_receipt(self.root, out/'review', row)
                if filename == CASES[0][0]:
                    self.assertTrue(row.get('analysis_cached'), 'length changes must reuse the real analysis')
                    self.assertGreaterEqual(row['summary_fix_count'], 1)
                    self.assertEqual({k:v for k,v in baseline.items() if k != 'summary'},
                                     {k:v for k,v in row['answer'].items() if k != 'summary'})


if __name__ == '__main__':
    unittest.main()
