import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tests import test_ecra
from ecra.common import read_json, write_json
from ecra.git_diff import compare, summarize, settings, pin, assert_pin, presentation_view
from ecra.cli import run
from ecra.review import build_variable_review_packet
from ecra.review_integrity import review_targets, review_integrity


class SemanticDiffTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def delta(self, old, new, files=None):
        cfg = self.project(old)
        bf, br = self.extract(cfg)
        base = summarize(bf, br)
        for name in old.keys()-new.keys():
            (self.root/name).unlink()
        cfg = self.project(new)
        hf, hr = self.extract(cfg)
        head = summarize(hf, hr)
        pinned = dict(files=files or [], head_sha='head', base_sha='base', base_source_root=str(self.root))
        result = compare(base, head, pinned)
        return result, hf, hr

    def names(self, result, facts):
        return {v['qualified_name'] for v in facts['variables'] if v['symbol_id'] in result['selected_symbol_ids']}

    def test_T01_T08_write_to_rmw(self):
        diff, facts, _ = self.delta({'a.c': 'int g; void Task(void){g=1;} void ISR(void){g=2;}'},
                                  {'a.c': 'int g; void Task(void){g++;} void ISR(void){g=2;}'})
        self.assertIn('g', self.names(diff, facts))
        self.assertIn('ACCESS_CHANGED', next(iter(diff['impacts'].values()))['reasons'])

    def test_long_initializer_after_extern_uses_complete_definition(self):
        values = ','.join('1' for _ in range(400))
        before = {'a.c': 'extern int g[400]; int g[400]={' + values + '};void Task(void){int x=g[399];}'}
        after = {'a.c': before['a.c'].replace(values, values[:-1] + '2')}
        diff, facts, _ = self.delta(before, after)
        self.assertTrue(diff['selected_symbol_ids'])
        self.assertTrue(any('DIRECT_CHANGED' in i['reasons'] for i in diff['impacts'].values()))

    def test_source_local_macro_change_is_build_semantic_impact(self):
        before = {'a.c': '#define VALUE 1\nint g;void Task(void){g=VALUE;}void ISR(void){g++;}'}
        after = {'a.c': before['a.c'].replace('VALUE 1', 'VALUE 2')}
        # ProjectTest.extract intentionally omits CLI metadata; use a real
        # extractor's digest explicitly to exercise this scalar TU contract.
        cfg = self.project(before)
        from ecra.compilation import prepare
        from ecra.extract import Extractor
        from ecra.analysis import merge, analyze
        def summary():
            units, coverage = prepare(self.root, cfg)
            parts = [Extractor(dict(root=str(self.root), unit=u, config=cfg)).run() for u in units]
            facts = merge(parts)
            for u, part in zip(units, parts):
                u['semantic_macros_digest'] = part['semantic_macros_digest']
            facts['translation_units'] = units
            return summarize(facts, analyze(facts, cfg, dict(translation_units_failed=0, **coverage)))
        base = summary()
        (self.root/'a.c').write_text(after['a.c'])
        head = summary()
        diff = compare(base, head, dict(files=[], head_sha='h', base_sha='b'))
        self.assertIn('BUILD_SEMANTICS_CHANGED', diff['impacts']['c:@g']['reasons'])

    def test_T02_T03_T23_distinct_static_storage(self):
        before = {'a.c': 'static int s; void Task(void){static int s;s++;} void ISR(void){s++;}',
                  'b.c': 'static int s; void Other(void){s++;}'}
        after = dict(before, **{'a.c': before['a.c'].replace('static int s;s++;', 'static int s;s+=2;')})
        diff, facts, _ = self.delta(before, after)
        self.assertIn('Task::s', self.names(diff, facts))
        self.assertEqual(len({v['symbol_id'] for v in facts['variables']}), 3)

    def test_T04_deep_downstream(self):
        src = 'int g,h; void C(void){g++;h++;} void B(void){C();} void Task(void){B();} void ISR(void){g++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('Task(void){B();}', 'Task(void){B();B();}')})
        self.assertTrue({'g', 'h'} <= self.names(diff, facts))

    def test_T05_T11_T12_return_control_upstream(self):
        src = 'int mode,g; int Get(void){return mode;} void Task(void){if(Get())g=1;} void ISR(void){g++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('return mode;', 'return !mode;')})
        self.assertIn('g', self.names(diff, facts))

    def test_T06_function_pointer_target(self):
        src = 'int g,h; void A(void){g++;} void B(void){h++;} void Task(void){void(*p)(void)=A;p();} void ISR(void){g++;h++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('=A;', '=B;')})
        self.assertTrue({'g', 'h'} <= self.names(diff, facts))

    def test_T07_callback_registration(self):
        src = 'int g,h;void reg(void(*p)(void));void A(void){g++;}void B(void){h++;}void Task(void){reg(A);}void ISR(void){g++;h++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('reg(A)', 'reg(B)')})
        self.assertTrue({'g', 'h'} <= self.names(diff, facts))

    def test_T09_remove_protection(self):
        src = 'void __disable_irq(void);void __enable_irq(void);int g;void Task(void){__disable_irq();g++;__enable_irq();}void ISR(void){g++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('__disable_irq();g++;__enable_irq();', 'g++;')})
        self.assertIn('g', self.names(diff, facts))

    def test_T10_T26_nvic_priority(self):
        src = 'void HAL_NVIC_SetPriority(int,int,int);int g;void Task(void){HAL_NVIC_SetPriority(30,1,0);}void ISR(void){g++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('(30,1,0)', '(30,0,0)')})
        self.assertIn('g', self.names(diff, facts))

    def test_T13_shared_data_fixed_point(self):
        src = 'int raw,filtered,out;void Task(void){raw=1;}void F(void){filtered=raw;}void O(void){out=filtered;}void ISR(void){out++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('raw=1', 'raw=2')})
        self.assertTrue({'raw', 'filtered', 'out'} <= self.names(diff, facts))

    def test_T14_pointer_parameter(self):
        src = 'int g;void Set(int*p){*p=1;}void Task(void){Set(&g);}void ISR(void){g++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('*p=1', '*p=2')})
        self.assertIn('g', self.names(diff, facts))

    def test_T15_dynamic_array(self):
        src = 'int a[8],i;void Task(void){a[i]=1;}void ISR(void){a[2]++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('a[i]=1', 'a[i]=2')})
        self.assertTrue(any(n.startswith('a') for n in self.names(diff, facts)))

    def test_T16_union_overlap(self):
        src = 'union U{int x;char bytes[4];}u;void Task(void){u.x=1;}void ISR(void){u.bytes[0]++;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('u.x=1', 'u.x=2')})
        self.assertTrue(any(n.startswith('u') for n in self.names(diff, facts)))

    def test_T17_deleted_call_keeps_old_edges(self):
        src = 'int g;void Use(void){g++;}void Task(void){Use();}void ISR(void){Use();}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('Task(void){Use();}', 'Task(void){}')})
        self.assertTrue(any(i['removed_edges'] for i in diff['impacts'].values()))

    def test_T18_rename_is_explicitly_uncertain(self):
        diff, facts, _ = self.delta({'a.c': 'int g;void Task(void){g++;}'}, {'a.c': 'int h;void Task(void){h++;}'})
        self.assertIn('h', self.names(diff, facts))
        self.assertTrue(diff['deleted_variables'])
        self.assertIn('MATCH_UNCERTAIN', next(iter(diff['impacts'].values()))['reasons'])

    def test_T19_file_move_static_matching(self):
        src = 'static int g;void Task(void){g++;}'
        cfg = self.project({'old.c': src})
        bf, br = self.extract(cfg)
        (self.root/'old.c').unlink()
        cfg = self.project({'new.c': src})
        hf, hr = self.extract(cfg)
        diff = compare(summarize(bf, br, {'old.c': 'new.c'}), summarize(hf, hr), dict(files=[],head_sha='h',base_sha='b'))
        self.assertFalse(diff['deleted_variables'])

    def test_T20_T21_build_change_expands(self):
        src = {'a.c': 'int g;void Task(void){g++;}'}
        diff, facts, _ = self.delta(src, src, [dict(new_path='CMakeLists.txt')])
        self.assertIn('g', self.names(diff, facts))
        self.assertEqual(diff['fallback_level'], 'L1')

    def test_T22_recursive_closure(self):
        src = 'int g;void B(void);void Task(void){B();}void B(void){g++;Task();}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('g++', 'g+=2')})
        self.assertIn('g', self.names(diff, facts))

    def test_T24_comment_blank_lines_are_not_semantic_changes(self):
        src = 'int g;\nvoid Task(void){g++;}\nvoid ISR(void){g++;}\n'
        diff, _, _ = self.delta({'a.c': src}, {'a.c': '// 注释\n\n' + src})
        self.assertEqual(diff['selected_symbol_ids'], [])

    def test_T24_comments_do_not_replace_automatic_pointer_slots(self):
        src = 'int g;\nvoid Task(void){int*p=&g;*p=1;}\nvoid ISR(void){g++;}\n'
        diff, _, _ = self.delta({'a.c': src}, {'a.c': '// 注释\n\n' + src})
        self.assertEqual(diff['selected_symbol_ids'], [])

    def test_T24_escaped_storage_and_anonymous_type_positions_are_not_impacts(self):
        cases = [
            'int g;void external(int*);\nvoid Task(void){external(&g);}\nvoid ISR(void){g++;}\n',
            'int g[4];void external(int*);\nvoid Task(void){external(g);}\nvoid ISR(void){g[0]++;}\n',
            'struct {int a,b;}g;\nvoid Task(void){g.a++;}\nvoid ISR(void){g.a++;}\n',
        ]
        for source in cases:
            with self.subTest(source=source):
                diff, facts, report = self.delta({'a.c': source}, {'a.c': '// 注释\n\n'+source})
                self.assertEqual(diff['selected_symbol_ids'], [])
                self.assertTrue(facts['variables'])
                if 'external' in source:
                    self.assertTrue(facts['unknowns'])
                    self.assertTrue(any(v.get('blocking_evidence') for v in facts['variables']))

    def test_anonymous_layout_change_remains_a_semantic_impact(self):
        source = 'struct {int a,b;}g;void Task(void){g.a++;}void ISR(void){g.a++;}'
        diff, facts, _ = self.delta({'a.c':source},{'a.c':source.replace('int a,b;', 'int a;short b;')})
        self.assertIn('c:@g', diff['selected_symbol_ids'])
        self.assertIn('DIRECT_CHANGED', diff['impacts']['c:@g']['reasons'])

    def test_disjoint_struct_fields_do_not_spread_through_ui_container(self):
        # Calls may legitimately share a function; isolate readers so only the
        # modified field's independent accessor component should be selected.
        src = 'struct S{int x,y;}s;void Task(void){s.x=1;}void ISR(void){s.x++;}void Other(void){s.y=2;}'
        diff, facts, _ = self.delta({'a.c': src}, {'a.c': src.replace('s.x=1', 's.x=2')})
        self.assertIn('s.x', self.names(diff, facts))
        if not diff['fallback_reasons']:
            self.assertNotIn('s.y', self.names(diff, facts))

    def test_T25_T27_ecat_change_keeps_tim4_packet(self):
        src = 'struct S{int msgSp;}g_mfcInterface;void INF_SetPointFP(void){g_mfcInterface.msgSp++;}void Old(void){INF_SetPointFP();}void ECAT_IRQHandler(void){Old();}void TIM4_IRQHandler(void){INF_SetPointFP();}'
        after = src.replace('ECAT_IRQHandler(void){Old();}', 'ECAT_IRQHandler(void){INF_SetPointFP();}')
        diff, facts, report = self.delta({'a.c': src}, {'a.c': after})
        sid = next(v['symbol_id'] for v in facts['variables'] if v.get('qualified_name') == 'g_mfcInterface.msgSp')
        self.assertIn(sid, diff['selected_symbol_ids'])
        finding = next(f for f in report['findings'] if f.get('symbol_id') == sid)
        packet = build_variable_review_packet(self.root, facts, finding, facts_path='facts.json', shared_path='shared.json', report_path='report.json')
        self.assertTrue(any(f['name'] == 'TIM4_IRQHandler' for f in packet['functions']))
        self.assertTrue(any('TIM4' in json.dumps(a) for a in packet['call_path_sets']))


class GitIntegrationTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def command(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT).decode().strip()

    def repository(self):
        self.project({'a.c': 'int g;void Task(void){g=1;}void ISR(void){g++;}', 'b.c': 'int unrelated;void Other(void){unrelated=2;}'})
        (self.root/'.gitignore').write_text('.ecra/\n')
        self.command('init')
        self.command('config', 'user.email', 'ecra@example.invalid')
        self.command('config', 'user.name', 'ECRA regression')
        self.command('add', '.')
        self.command('commit', '-m', 'base')
        self.command('branch', 'base')
        cfg = read_json(self.root/'.ecra/semantics.yaml')
        cfg['analysis']['git_diff'] = dict(enabled=True, target_ref='base', compare_mode='direct')
        write_json(self.root/'.ecra/semantics.yaml', cfg)
        return cfg

    def scan(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = run(self.root, no_review=True)
        if code == 3:
            self.fail((self.root/'.ecra/run.log').read_text(encoding='utf-8'))
        return read_json(self.root/'.ecra/reports/global_static_concurrency.json')

    def test_T28_T33_T36_empty_diff_saved_scope_and_html(self):
        self.repository()
        report = self.scan()
        self.assertEqual(report['git_diff']['selected_symbol_ids'], [])
        self.assertTrue((self.root/'.ecra/index.html').is_file())
        self.assertFalse((self.root/'.ecra/diff_index.html').exists())
        html = (self.root/'.ecra/index.html').read_text(encoding='utf-8')
        self.assertIn('本次比较未识别到需要核对的差异变量', html)
        from ecra.workflow import checked_scan
        from ecra.config import load_config
        cfg, path = load_config(self.root)
        _, restored, _ = checked_scan(self.root, self.root/'.ecra', cfg, path, with_facts=False)
        self.assertEqual(restored['git_diff']['selected_symbol_ids'], [])
        self.assertTrue(review_integrity(restored, read_json(self.root/'.ecra/review/queue.json'))['complete'])

    def test_T29_bad_ref_and_missing_git(self):
        self.repository()
        cfg, _ = __import__('ecra.config', fromlist=['load_config']).load_config(self.root)
        cfg['analysis']['git_diff']['target_ref'] = 'not-existing'
        with self.assertRaises(ValueError):
            pin(self.root, cfg)
        with patch('ecra.git_diff.subprocess.run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, 'Git 无法运行'):
                pin(self.root, cfg)

    def test_T30_cache_hits_corruption_and_full_equivalence(self):
        cfg = self.repository()
        (self.root/'a.c').write_text('int g;void Task(void){g+=2;}void ISR(void){g++;}')
        self.command('add', 'a.c')
        self.command('commit', '-m', 'change')
        first = self.scan()
        self.assertIn('c:@g', first['git_diff']['selected_symbol_ids'])
        second = self.scan()
        self.assertEqual(second['git_diff']['tu_cache']['hits'], 2)
        for path in (self.root/'.ecra/cache/tu-v1').glob('*.facts'):
            path.write_text('corrupt')
        repaired = self.scan()
        self.assertEqual(repaired['git_diff']['tu_cache']['corrupt'], 2)
        self.assertEqual(repaired['git_diff']['tu_cache']['hits'], 0)
        cfg['analysis']['git_diff']['verify_against_full'] = True
        write_json(self.root/'.ecra/semantics.yaml', cfg)
        third = self.scan()
        self.assertEqual(third['git_diff']['full_verification']['state'], 'PASSED')

    def test_baseline_summary_reuse_and_corruption_rebuild(self):
        self.repository()
        first = self.scan()
        with patch('ecra.git_diff.summarize', wraps=summarize) as build:
            second = self.scan()
        self.assertEqual(first['git_diff']['selected_symbol_ids'], second['git_diff']['selected_symbol_ids'])
        self.assertEqual(build.call_count, 1, 'Only HEAD needs normalization after complete baseline validation')
        summaries = list((self.root/'.ecra/git_diff/summary-cache').glob('*.summary.json'))
        self.assertEqual(len(summaries), 1)
        summaries[0].write_text('corrupt')
        with patch('ecra.git_diff.summarize', wraps=summarize) as build:
            repaired = self.scan()
        self.assertEqual(build.call_count, 2)
        self.assertEqual(repaired['git_diff']['selected_symbol_ids'], first['git_diff']['selected_symbol_ids'])
        manifest = summaries[0].with_suffix('.manifest.json')
        manifest.write_text('[]')
        with patch('ecra.git_diff.summarize', wraps=summarize) as build:
            repaired = self.scan()
        self.assertEqual(build.call_count, 2)
        self.assertEqual(repaired['git_diff']['selected_symbol_ids'], first['git_diff']['selected_symbol_ids'])

    def test_summary_mutation_after_validation_blocks_publication(self):
        self.repository()
        from ecra.analysis import analyze
        def tamper(facts, cfg, *args, **kwargs):
            report = analyze(facts, cfg, *args, **kwargs)
            if cfg['analysis']['git_diff']['enabled']:
                path = next((self.root/'.ecra/git_diff/summary-cache').glob('*.summary.json'))
                summary = read_json(path)
                summary['variables']['c:@g']['dimensions']['declaration'] = 'tampered'
                write_json(path, summary)
            return report
        with patch('ecra.cli.analyze', side_effect=tamper), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        self.assertFalse(read_json(self.root/'.ecra/result_validity.json')['analysis_valid'])

    def test_summary_cache_does_not_bypass_baseline_input_validation(self):
        self.repository()
        self.scan()
        report = read_json(self.root/'.ecra/reports/global_static_concurrency.json')
        base = __import__('pathlib').Path(report['git_diff']['pin']['base_source_root'])
        (base/'a.c').write_text('int corrupted;')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        self.assertFalse(read_json(self.root/'.ecra/result_validity.json')['analysis_valid'])

    def test_T31_git_snapshot_changes_block_resume(self):
        self.repository()
        cfg, _ = __import__('ecra.config', fromlist=['load_config']).load_config(self.root)
        before = pin(self.root, cfg)
        (self.root/'a.c').write_text('int changed;')
        with self.assertRaises(ValueError):
            assert_pin(self.root, cfg, before)

    def test_settings_strict_types(self):
        for bad in (dict(enabled=1), dict(compare_mode='x'), dict(target_ref='-x'), dict(cache_enabled='false'), dict(unknown=True)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settings(bad)

    def test_T35_chinese_paths(self):
        self.root = self.root/'中文 固件'
        (self.root/'.ecra').mkdir(parents=True)
        self.repository()
        self.assertEqual(self.scan()['git_diff']['selected_symbol_ids'], [])

    def test_merge_base_and_direct_are_pinned_separately(self):
        self.repository()
        (self.root/'a.c').write_text('int changed;')
        self.command('add', 'a.c')
        self.command('commit', '-m', 'head')
        tree = self.command('rev-parse', 'HEAD^{tree}')
        target = self.command('commit-tree', tree, '-p', 'base', '-m', 'target-only')
        self.command('update-ref', 'refs/heads/target', target)
        from ecra.config import load_config
        cfg, _ = load_config(self.root)
        cfg['analysis']['git_diff'].update(target_ref='target', compare_mode='direct')
        direct = pin(self.root, cfg)
        cfg['analysis']['git_diff']['compare_mode'] = 'merge_base'
        ancestor = pin(self.root, cfg)
        self.assertEqual(direct['base_sha'], target)
        self.assertEqual(ancestor['base_sha'], self.command('rev-parse', 'base'))
        self.assertNotEqual(direct['base_sha'], ancestor['base_sha'])

    def test_staged_unstaged_untracked_workspace_snapshot(self):
        self.repository()
        from ecra.config import load_config
        cfg, _ = load_config(self.root)
        cfg['analysis']['git_diff']['include_uncommitted'] = True
        (self.root/'a.c').write_text('int staged;')
        self.command('add', 'a.c')
        (self.root/'b.c').write_text('int unstaged;')
        (self.root/'新 文件.h').write_text('#define FLAG 1')
        snapshot = pin(self.root, cfg)
        self.assertTrue(any(f['status'] == '?' and f['new_path'] == '新 文件.h' for f in snapshot['files']))
        (self.root/'新 文件.h').write_text('#define FLAG 2')
        with self.assertRaises(ValueError):
            assert_pin(self.root, cfg, snapshot)

    def test_project_subdirectory_binds_real_repo_paths(self):
        self.repository()
        sub = self.root/'固件 子目录'
        sub.mkdir()
        (sub/'input.h').write_text('#define FLAG 1')
        self.command('add', '.')
        self.command('commit', '-m', 'subdir')
        from ecra.config import load_config
        cfg, _ = load_config(self.root)
        cfg['analysis']['git_diff']['include_uncommitted'] = True
        before = pin(sub, cfg)
        (sub/'input.h').write_text('#define FLAG 2')
        self.assertNotEqual(before['workspace_digest'], pin(sub, cfg)['workspace_digest'])
        with self.assertRaises(ValueError):
            assert_pin(sub, cfg, before)

    def test_header_comments_preserve_macro_whitespace_semantics(self):
        from ecra.git_diff import comment_insensitive
        self.assertEqual(comment_insensitive(b'#define VALUE 1\nint x;\n'),
                         comment_insensitive(b'// comment\n#define VALUE 1\n\nint x; /* comment */\n'))
        self.assertNotEqual(comment_insensitive(b'#define F(x) x\n'), comment_insensitive(b'#define F (x) x\n'))
        self.assertIsNone(comment_insensitive(b'#define F \\\n1\n'))
        self.assertIsNone(comment_insensitive(b'\xff'))

    def test_portable_missing_offline_git_is_explicit(self):
        from ecra.git_diff import git
        with patch('ecra.portable.bundle_root', return_value=self.root/'portable'):
            with self.assertRaisesRegex(ValueError, '离线 Git'):
                git(self.root, '--version')

    def test_saved_review_failed_uses_persisted_diff_range(self):
        self.repository()
        report = self.scan()
        from ecra.workflow import saved_run
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(self.root, failed_only=True), (0, 1, 2))
        saved = read_json(self.root/'.ecra/reports/global_static_concurrency.json')
        self.assertEqual(report['git_diff']['selected_symbol_ids'], saved['git_diff']['selected_symbol_ids'])
        self.assertEqual(read_json(self.root/'.ecra/review/queue.json'), [])

    def test_saved_status_and_render_do_not_requeue_unselected_risk(self):
        self.repository()
        src = ('int g,h;void G1_IRQHandler(void){g=1;}void G2_IRQHandler(void){g++;}'
               'void H1_IRQHandler(void){h++;}void H2_IRQHandler(void){h++;}')
        (self.root/'a.c').write_text(src)
        (self.root/'b.c').write_text('')
        self.command('add', '.')
        self.command('commit', '-m', 'independent IRQ groups')
        self.command('branch', 'independent-base')
        cfg = read_json(self.root/'.ecra/semantics.yaml')
        cfg['contexts'] = []
        cfg['analysis']['git_diff']['target_ref'] = 'independent-base'
        write_json(self.root/'.ecra/semantics.yaml', cfg)
        (self.root/'a.c').write_text(src.replace('g=1', 'g=2'))
        self.command('add', 'a.c')
        self.command('commit', '-m', 'change only g')
        report = self.scan()
        self.assertEqual(report['git_diff']['selected_symbol_ids'], ['c:@g'])
        self.assertEqual(len(report['findings']), 2)
        from ecra.workflow import status, saved_run
        self.assertEqual(status(self.root)['findings'], 1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(self.root, render_only=True), (1, 2))
        report = read_json(self.root/'.ecra/reports/global_static_concurrency.json')
        self.assertEqual(report['review_summary']['total'], 1)
        self.assertEqual(len(read_json(self.root/'.ecra/review/queue.json')), 1)

    def test_diff_review_grants_read_access_to_patch_and_base_facts(self):
        self.repository()
        (self.root/'a.c').write_text('int g;void Task(void){g=2;}void ISR(void){g++;}')
        self.command('add', 'a.c')
        self.command('commit', '-m', 'change')
        report = self.scan()
        facts = read_json(self.root/'.ecra/facts.json')
        from ecra.config import load_config
        from ecra.review import review_all
        cfg, _ = load_config(self.root)
        cfg['review'].update(enabled=True, retries=0)
        seen = []
        def check_permissions(argv, **kwargs):
            permissions = json.loads(kwargs['env']['OPENCODE_PERMISSION'])['read']
            pin = report['git_diff']['pin']
            for key in ('base_facts_path', 'base_summary_path', 'diff_patch_path'):
                self.assertEqual(permissions[str(Path(pin[key]))], 'allow')
            baseline = read_json(pin['base_summary_path'])
            for impact in report['git_diff']['impacts'].values():
                self.assertEqual(impact['base_summary_path'], pin['base_summary_path'])
                self.assertEqual(impact['base_summary_sha256'], pin['base_summary_sha256'])
                self.assertIn(impact['base']['graph_id'], baseline['graphs'])
            seen.append(True)
            # Deliberate protocol-only failure; no model is executed.
            return subprocess.CompletedProcess(argv, 1, '', '仅校验读取权限')
        with contextlib.redirect_stdout(io.StringIO()), patch('ecra.review.resolve_command', return_value=['fake-review']), patch('ecra.review.execute', side_effect=check_permissions):
            review_all(self.root, self.root/'.ecra', cfg, facts, report, report['fingerprint'])
        self.assertTrue(seen)


if __name__ == '__main__':
    unittest.main()
