"""Real repositories, ARM GCC/CMake builds and streamed migration fixtures."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

from ecra.cli import run
from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.git_diff import pin, assert_pin
from ecra.workspace import (WorkspaceResolver, migrate_legacy, file_hash,
                            generated_untracked, lock_path, no_links, output_settings)
from ecra.workflow import status, saved_run


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra workspace 中文 ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.tool = self.home/'tool'
        self.tool.mkdir()
        self.patcher = patch('ecra.workspace.TOOL_ROOT', self.tool)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.data_env = patch.dict(os.environ, {'ECRA_DATA_ROOT': str(self.home/'data')})
        self.data_env.start()
        self.addCleanup(self.data_env.stop)
        self.repo = self.home/'固件 空格'
        self.repo.mkdir()
        self.root = self.repo/'Board'
        self.root.mkdir()
        (self.root/'a.c').write_text('int g;void Task(void){g=1;}void ISR(void){g++;}\n')
        (self.root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
            'project(firmware C)\nconfigure_file(generated.h.in generated.h COPYONLY)\n'
            'add_library(firmware STATIC a.c)\ntarget_include_directories(firmware PRIVATE ${CMAKE_CURRENT_BINARY_DIR})\n')
        (self.root/'generated.h.in').write_text('#define VALUE 1\n')
        write_json(self.root/'compile_commands.json', [dict(directory=str(self.root), file='a.c',
            arguments=['arm-none-eabi-gcc', '-mcpu=cortex-m7', '-mthumb', '-c', 'a.c'])])
        self.git('init')
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        self.git('branch', 'base')
        self.cfg = dict(version=1, project=dict(root=str(self.root)),
            analysis=dict(compile_database='compile_commands.json', git_diff=dict(enabled=True, base_ref='base')),
            contexts=[dict(id='task', kind='TASK', functions=['Task']), dict(id='isr', kind='ISR', functions=['ISR'])],
            review=dict(enabled=False, prepare_packets=False))
        self.config = self.tool/'semantics.yaml'
        self.save()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), '-c', 'user.name=ECRA',
            '-c', 'user.email=ecra@example.invalid', '-c', 'commit.gpgSign=false', *args],
            stderr=subprocess.STDOUT).decode('utf-8').strip()

    def save(self):
        write_json(self.config, self.cfg)

    def ws(self):
        return WorkspaceResolver.resolve(self.root, self.cfg['analysis'])

    def scan(self, mode='diff'):
        self.save()
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            code = run(self.root, str(self.config), no_review=True, scan_mode=mode)
        self.assertIn(code, (0, 1, 2), capture.getvalue())
        out = Path(self.ws().results_root)
        self.assertTrue(read_json(out/'result_validity.json')['analysis_valid'])
        return out, read_json(out/'reports/global_static_concurrency.json'), capture.getvalue()

    def legacy(self):
        old = self.root/'.ecra'
        write_json(old/'scan_state.json', dict(schema=1, project_root=str(self.root), fingerprint='old'))
        write_json(old/'run.json', dict(project_root=str(self.root)))
        write_json(old/'reports/global_static_concurrency.json', dict(findings=[]))
        (old/'facts.db').write_bytes(b'legacy database bytes')
        (old/'index.html').write_text('人工确认风险/无风险/未确认; 2024-01-02; 原始备注', encoding='utf-8')
        write_json(old/'review/queue.json', [dict(state='DONE', status='CONFIRMED', note='原备注'),
            dict(state='DONE', status='FALSE_POSITIVE'), dict(state='PENDING')])
        return old

    def test_T01_T02_T03_T10_T11_identity_and_isolation(self):
        first = self.ws().initialize()
        self.assertEqual(first.project_id, self.ws().project_id)
        self.assertEqual(first.project_id, WorkspaceResolver.resolve(self.root/'../Board', self.cfg['analysis']).project_id)
        other = self.home/'other'/'固件 空格'/'Board'
        other.mkdir(parents=True)
        self.assertNotEqual(first.project_id, WorkspaceResolver.resolve(other, self.cfg['analysis']).project_id)
        self.assertFalse(Path(first.results_root).is_relative_to(self.repo))
        metadata = read_json(Path(first.project_workspace)/'project.json')
        self.assertEqual(metadata['project_id'], first.project_id)
        self.assertEqual(metadata['project_root'], str(self.root).replace('\\', '/').casefold() if os.name == 'nt' else str(self.root))

    def test_T04_T06_T09_committed_head_does_not_consume_dirty_workspace(self):
        (self.root/'.ecra').mkdir()
        (self.root/'.ecra/unknown.c').write_text('int real_user_input;')
        (self.root/'a.c').write_text('int dirty_only;')
        before = self.git('status', '--porcelain=v1', '-uall')
        index = self.git('ls-files', '--stage')
        out, report, log = self.scan()
        self.assertEqual(before, self.git('status', '--porcelain=v1', '-uall'))
        self.assertEqual(index, self.git('ls-files', '--stage'))
        pinned = report['git_diff']['pin']
        self.assertNotEqual(Path(pinned['current_source_root']), self.root)
        self.assertNotIn('dirty_only', (out/'facts.json').read_text(encoding='utf-8'))
        self.assertIn('未纳入', log)
        self.assertIn('未提交业务修改未纳入', (out/'index.html').read_text(encoding='utf-8'))
        self.assertEqual(pinned['files'], [])

    def test_T07_T08_T18_T25_effective_workspace_and_tracked_generated_inputs(self):
        self.cfg['analysis']['git_diff']['include_uncommitted'] = True
        self.save()
        (self.root/'a.c').write_text('int g;void Task(void){g=2;}void ISR(void){g++;}')
        self.git('add', 'Board/a.c')
        (self.root/'generated.h.in').write_text('#define VALUE 2')
        (self.root/'新 文件.h').write_text('#define NEW 1')
        cfg, _ = load_config(self.root, self.config)
        snapshot = pin(self.root, cfg)
        self.assertEqual({row['new_path'] for row in snapshot['files']},
            {'Board/a.c', 'Board/generated.h.in', 'Board/新 文件.h'})
        out, report, _ = self.scan()
        self.assertNotIn('current_source_root', report['git_diff']['pin'])
        (self.root/'新 文件.h').write_text('#define NEW 2')
        with self.assertRaisesRegex(ValueError, '快照已变化'):
            assert_pin(self.root, cfg, snapshot)

    def test_T05_T15_T16_T30_migration_bytes_and_interruption(self):
        old = self.legacy()
        ws = self.ws().initialize()
        hashes = {p.relative_to(old).as_posix(): file_hash(p) for p in old.rglob('*') if p.is_file()}
        original = shutil.copyfile
        count = 0
        def interrupt(source, target):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('injected disk full')
            return original(source, target)
        with patch('ecra.workspace.shutil.copyfile', side_effect=interrupt):
            with self.assertRaisesRegex(ValueError, '原数据未删除'):
                migrate_legacy(ws, lambda _: None)
        self.assertFalse((Path(ws.results_root)/'migration.json').exists())
        migrate_legacy(ws, lambda _: None)
        out = Path(ws.results_root)
        for rel, expected in hashes.items():
            self.assertEqual(expected, file_hash(old/rel))
            self.assertEqual(expected, file_hash(out/rel))
        self.assertEqual(read_json(out/'migration.json')['review_state'], 'PRESERVED_REVALIDATION_REQUIRED')
        self.assertIn('原始备注', (out/'index.html').read_text(encoding='utf-8'))
        cfg, _ = load_config(self.root, self.config)
        ws.bind(cfg['analysis'])
        safe = generated_untracked(self.root, cfg)
        self.assertIn('Board/.ecra/facts.db', safe)
        (old/'business.c').write_text('int business;')
        self.assertNotIn('Board/.ecra/business.c', generated_untracked(self.root, cfg))
        (old/'facts.db').write_bytes(b'changed user content')
        self.assertNotIn('Board/.ecra/facts.db', generated_untracked(self.root, cfg))

    def test_T13_T14_configuration_compatibility(self):
        self.assertEqual(output_settings(dict(output_dir='.ecra'))['location'], 'user')
        self.assertEqual(output_settings(dict(output_dir='my-results'))['location'], 'project')
        with self.assertRaisesRegex(ValueError, '冲突'):
            output_settings(dict(output_dir='old', output=dict(location='tool')))
        self.cfg['analysis']['output'] = dict(location='custom', custom_dir=str(self.home/'external data'))
        out, _, _ = self.scan('full')
        self.assertTrue(out.is_relative_to(self.home/'external data'))
        self.assertTrue(status(self.root, self.config)['resumable'])

    def test_T17_environment_and_compiler_bytes_invalidate_complete_cache(self):
        compiler = self.tool/'fixture-compiler'
        compiler.write_bytes(b'fixture compiler identity v1')
        write_json(self.root/'compile_commands.json', [dict(directory=str(self.root), file='a.c',
            arguments=[str(compiler), '-c', 'a.c'])])
        self.scan('full')
        self.assertTrue(status(self.root, self.config)['resumable'])
        with patch.dict(os.environ, {'CPATH': str(self.tool/'different-includes')}):
            info = status(self.root, self.config)
            self.assertFalse(info['resumable'])
            self.assertIn('环境', info['next_action'])
        compiler.write_bytes(b'fixture compiler identity v2')
        self.assertFalse(status(self.root, self.config)['resumable'])

    def test_T19_T20_lock_and_identity_conflict(self):
        ws = self.ws().initialize()
        cfg, _ = load_config(self.root, self.config)
        ws.bind(cfg['analysis'])
        lock = lock_path(self.root, cfg['analysis'])
        lock.write_text('already-running')
        with self.assertRaisesRegex(ValueError, '扫描锁'):
            run(self.root, str(self.config), no_review=True)
        self.assertEqual(lock.read_text(), 'already-running')
        lock.unlink()
        meta = Path(ws.project_workspace)/'project.json'
        data = read_json(meta)
        data['project_id'] = 'foreign'
        write_json(meta, data)
        with self.assertRaisesRegex(ValueError, '身份冲突'):
            status(self.root, self.config)

    def test_T24_readonly_workspace_diagnostic(self):
        # Deterministic permission failure even under an administrator account.
        with patch('ecra.workspace.tempfile.TemporaryFile', side_effect=PermissionError('read only')):
            with self.assertRaisesRegex(ValueError, 'custom_dir'):
                self.ws().initialize()
        self.assertFalse((self.root/'.ecra').exists())

    def test_project_mode_never_adopts_unknown_or_foreign_legacy_data(self):
        options = dict(output=dict(location='project'), output_dir='private-data')
        private = self.root/'private-data'
        private.mkdir()
        (private/'keep.txt').write_text('user data')
        with self.assertRaisesRegex(ValueError, '所有权'):
            WorkspaceResolver.resolve(self.root, options).initialize()
        self.assertEqual((private/'keep.txt').read_text(), 'user data')
        old = self.legacy()
        write_json(old/'run.json', dict(project_root=str(self.home/'different-project')))
        with self.assertRaisesRegex(ValueError, '所有权'):
            WorkspaceResolver.resolve(self.root, dict(output=dict(location='project'))).initialize()
        self.assertFalse((old/'project.json').exists())

    def test_status_exposes_verified_legacy_history_before_first_new_scan(self):
        old = self.legacy()
        before = file_hash(old/'index.html')
        info = status(self.root, self.config)
        self.assertEqual(info['state'], 'LEGACY_HISTORY_FOUND')
        self.assertEqual(info['legacy_history'], str(old))
        self.assertFalse(Path(self.ws().project_workspace).exists())
        self.assertEqual(file_hash(old/'index.html'), before)
        with self.assertRaisesRegex(ValueError, '旧版.*run'):
            saved_run(self.root, self.config, render_only=True)

    def test_interrupted_project_claim_is_explicit_and_recoverable(self):
        ws = self.ws().initialize()
        marker = Path(ws.project_workspace)/'project.json'
        pending = marker.with_name('project.json.pending')
        expected = marker.read_bytes()
        marker.rename(pending)
        with self.assertRaisesRegex(ValueError, '初始化锁.*project.json.pending'):
            ws.initialize()
        self.assertEqual(pending.read_bytes(), expected)
        pending.rename(marker)  # documented recovery after the owner exited
        ws.initialize()
        self.assertEqual(marker.read_bytes(), expected)
        self.assertFalse(pending.exists())

    def test_corrupt_project_metadata_reports_its_path_without_overwriting(self):
        ws = self.ws().initialize()
        marker = Path(ws.project_workspace)/'project.json'
        marker.write_text('{interrupted')
        with self.assertRaisesRegex(ValueError, '归属元数据.*project.json'):
            ws.initialize()
        self.assertEqual(marker.read_text(), '{interrupted')

    def test_T19_T20_real_processes_different_projects_and_same_project_lock(self):
        self.cfg['analysis']['output'] = dict(location='custom', custom_dir=str(self.tool/'workspace'))
        self.save()
        ws = self.ws().initialize()
        other = self.home/'second-project'
        other.mkdir()
        (other/'a.c').write_text('int second;void Task(void){second++;}')
        write_json(other/'compile_commands.json', [dict(directory=str(other), file='a.c',
            arguments=['arm-none-eabi-gcc', '-c', 'a.c'])])
        import copy
        second = copy.deepcopy(self.cfg)
        second['project']['root'] = str(other)
        second['analysis']['git_diff']['enabled'] = False
        second_config = self.tool/'second.yaml'
        write_json(second_config, second)
        script = Path(__file__).resolve().parents[1]/'run_ecra.py'
        def command(config):
            return [sys.executable, str(script), '--config', str(config), '--no-review','--legacy-output']
        with tempfile.TemporaryFile() as first_log, tempfile.TemporaryFile() as other_log:
            first = subprocess.Popen(command(self.config), stdout=first_log, stderr=subprocess.STDOUT)
            self.addCleanup(lambda: first.kill() if first.poll() is None else None)
            lock = Path(ws.project_workspace)/'scan.lock'
            deadline = time.monotonic()+15
            while not lock.exists() and first.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(lock.exists())
            concurrent = subprocess.Popen(command(second_config), stdout=other_log, stderr=subprocess.STDOUT)
            self.addCleanup(lambda: concurrent.kill() if concurrent.poll() is None else None)
            rejected = subprocess.run(command(self.config), capture_output=True, timeout=60)
            self.assertEqual(rejected.returncode, 3, rejected.stdout)
            self.assertIn('扫描锁', rejected.stderr.decode('utf-8', errors='replace'))
            self.assertIn(first.wait(timeout=120), (0, 1, 2))
            self.assertIn(concurrent.wait(timeout=120), (0, 1, 2))
        second_ws = WorkspaceResolver.resolve(other, second['analysis'])
        self.assertNotEqual(ws.project_id, second_ws.project_id)
        self.assertTrue((Path(second_ws.results_root)/'facts.db').is_file())
        self.assertTrue((Path(ws.results_root)/'facts.db').is_file())

    def test_T27_junction_boundary(self):
        destination = self.home/'private'
        destination.mkdir()
        alias = self.home/'data'
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(destination)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.addCleanup(lambda: alias.rmdir())
        else:
            alias.symlink_to(destination, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Junction'):
            self.ws()
        self.assertEqual(list(destination.iterdir()), [])

    @unittest.skipUnless(all(shutil.which(t) for t in ('cmake', 'ninja', 'arm-none-eabi-gcc')), 'requires ARM GCC/CMake/Ninja')
    def test_T12_T17_T21_T22_T26_T28_T29_cmake_external_builds_and_resume(self):
        self.cfg['analysis'].update(compile_database='auto', cmake=dict(build_dir='build/ecra',
            generator='Ninja', build=True, args=['-DCMAKE_SYSTEM_NAME=Generic',
            '-DCMAKE_C_COMPILER=arm-none-eabi-gcc', '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        (self.root/'a.c').write_text('#include "generated.h"\nint g;void Task(void){g=VALUE;}void ISR(void){g++;}')
        self.git('add', '.')
        self.git('commit', '-m', 'generated header')
        before = self.git('status', '--porcelain=v1', '-uall')
        out, report, _ = self.scan()
        pinned = report['git_diff']['pin']
        self.assertTrue(Path(pinned['diff_patch_path']).is_file())
        self.assertTrue(Path(pinned['base_facts_path']).is_file())
        builds = list(Path(self.ws().build_root).glob('*/CMakeCache.txt'))
        self.assertEqual(len(builds), 2)
        self.assertNotEqual(builds[0].parent, builds[1].parent)
        self.assertFalse((self.root/'build').exists())
        self.assertEqual(before, self.git('status', '--porcelain=v1', '-uall'))
        self.assertTrue(status(self.root, self.config)['resumable'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(self.root, self.config, render_only=True), (0, 1, 2))
        _, second, _ = self.scan()
        self.assertEqual(second['git_diff']['tu_cache']['hits'], 1)
        self.assertEqual(len(list(Path(self.ws().worktree_root).iterdir())), 2)
        self.assertEqual(second['git_diff']['selected_symbol_ids'], report['git_diff']['selected_symbol_ids'])
        # Consumed generated headers remain input-bound outside the firmware.
        current = Path(second['git_diff']['pin']['current_source_root'])
        from ecra.compilation import cmake_build_directory
        from ecra.git_diff import current_context
        cfg, _ = load_config(self.root, self.config)
        self.ws().bind(cfg['analysis'])
        _, cfg = current_context(self.root, cfg, second['git_diff']['pin'])
        build = cmake_build_directory(current, cfg['analysis'])
        (build/'generated.h').write_text('#define VALUE 99\n')
        self.assertFalse(status(self.root, self.config)['resumable'])

    @unittest.skipUnless(all(shutil.which(t) for t in ('cmake', 'ninja', 'arm-none-eabi-gcc')), 'requires ARM GCC/CMake/Ninja')
    def test_build_directory_relocation_is_not_a_semantic_change(self):
        self.cfg['analysis'].update(compile_database='auto', cmake=dict(generator='Ninja', build=True,
            args=['-DCMAKE_SYSTEM_NAME=Generic', '-DCMAKE_C_COMPILER=arm-none-eabi-gcc',
                  '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        (self.root/'a.c').write_text('#include "generated.h"\nint g;void Task(void){g=VALUE;}void ISR(void){g++;}')
        self.git('add', '.')
        self.git('commit', '-m', 'same generated inputs')
        self.cfg['analysis']['git_diff']['base_ref'] = 'HEAD'
        _, report, _ = self.scan()
        self.assertEqual(report['git_diff']['selected_symbol_ids'], [])

    @unittest.skipUnless(all(shutil.which(t) for t in ('cmake', 'ninja', 'arm-none-eabi-gcc')), 'requires ARM GCC/CMake/Ninja')
    def test_source_writing_cmake_is_explicitly_rejected_in_committed_mode(self):
        self.cfg['analysis'].update(compile_database='auto', cmake=dict(generator='Ninja', build=True,
            args=['-DCMAKE_SYSTEM_NAME=Generic', '-DCMAKE_C_COMPILER=arm-none-eabi-gcc',
                  '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        with (self.root/'CMakeLists.txt').open('a') as stream:
            stream.write('configure_file(generated.h.in ${CMAKE_CURRENT_SOURCE_DIR}/source-generated.h COPYONLY)\n')
        self.git('add', '.')
        self.git('commit', '-m', 'source writing generator')
        self.cfg['analysis']['git_diff']['base_ref'] = 'HEAD'
        self.save()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, str(self.config), no_review=True), 3)
        self.assertFalse((self.root/'source-generated.h').exists())
        state = read_json(Path(self.ws().results_root)/'result_validity.json')
        self.assertIn('CMAKE_BINARY_DIR', state['error'])

    @unittest.skipUnless(all(shutil.which(t) for t in ('cmake', 'ninja', 'arm-none-eabi-gcc')), 'requires ARM GCC/CMake/Ninja')
    def test_generated_source_keeps_scope_and_has_no_build_path_only_diff(self):
        self.cfg['analysis'].update(compile_database='auto', include_dirs=['.'],
            cmake=dict(generator='Ninja', build=True, args=['-DCMAKE_SYSTEM_NAME=Generic',
            '-DCMAKE_C_COMPILER=arm-none-eabi-gcc', '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        (self.root/'generated.c.in').write_text('int generated_global;void Gen(void){generated_global++;}\n')
        (self.root/'a.c').write_text('void Gen(void);void Task(void){Gen();}void ISR(void){Gen();}\n')
        with (self.root/'CMakeLists.txt').open('a') as stream:
            stream.write('configure_file(generated.c.in generated.c COPYONLY)\n'
                'target_sources(firmware PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/generated.c)\n')
        (self.root/'compile_commands.json').unlink()
        self.git('add', '-A')
        self.git('commit', '-m', 'generated source with shared state')
        self.cfg['analysis']['git_diff']['base_ref'] = 'HEAD'
        out, report, _ = self.scan()
        facts = read_json(out/'facts.json')
        self.assertIn('generated_global', {v['name'] for v in facts['variables']})
        self.assertEqual(report['git_diff']['selected_symbol_ids'], [])
        # The older auto-configure spelling must preserve the same generated
        # variable and logical exclude rules after its build also moves out.
        settings = self.cfg['analysis'].pop('cmake')
        self.cfg['analysis'].update(auto_configure_cmake=True, cmake_args=settings['args'])
        out, _, _ = self.scan('full')
        variable = next(v for v in read_json(out/'facts.json')['variables'] if v['name']=='generated_global')
        from ecra.scope import AuditScope
        excluded = dict(self.cfg['analysis'], exclude_dirs=['build/ecra'])
        self.assertIn('exclude_dirs', AuditScope(self.root, excluded).exclusion(variable['definition_file']))

    @unittest.skipUnless(all(shutil.which(t) for t in ('cmake', 'ninja', 'arm-none-eabi-gcc')), 'requires ARM GCC/CMake/Ninja')
    def test_cached_baseline_refreshes_arbitrary_cmake_environment_inputs(self):
        self.cfg['analysis'].update(compile_database='auto',
            cmake=dict(generator='Ninja', build=True, args=['-DCMAKE_SYSTEM_NAME=Generic',
            '-DCMAKE_C_COMPILER=arm-none-eabi-gcc', '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        (self.root/'a.c').write_text('#include "env.h"\nint g;void Task(void){g=ENV_VALUE;}void ISR(void){g++;}\n')
        with (self.root/'CMakeLists.txt').open('a') as stream:
            stream.write('file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/env.h "#define ENV_VALUE $ENV{ECRA_FIXTURE_MODE}\\n")\n')
        self.git('add', '.')
        self.git('commit', '-m', 'arbitrary environment driven configure')
        self.cfg['analysis']['git_diff']['base_ref'] = 'HEAD'
        with patch.dict(os.environ, {'ECRA_FIXTURE_MODE': '1'}):
            out, first, _ = self.scan()
            old_facts = file_hash(Path(first['git_diff']['pin']['base_facts_path']))
        with patch.dict(os.environ, {'ECRA_FIXTURE_MODE': '2'}):
            _, second, log = self.scan()
        self.assertIn('刷新基准 CMake', log)
        self.assertNotEqual(old_facts, file_hash(Path(second['git_diff']['pin']['base_facts_path'])))
        self.assertEqual(second['git_diff']['selected_symbol_ids'], [])

    def test_committed_scan_rejects_absolute_original_repository_dependency(self):
        shared = self.repo/'Shared'
        shared.mkdir()
        header = shared/'input.h'
        header.write_text('#define VALUE 1\n')
        (self.root/'a.c').write_text('#include "input.h"\nint g;void Task(void){g=VALUE;}void ISR(void){g++;}\n')
        write_json(self.root/'compile_commands.json', [dict(directory=str(self.root),file='a.c',
            arguments=['arm-none-eabi-gcc','-I'+str(shared),'-c','a.c'])])
        self.git('add','.')
        self.git('commit','-m','absolute sibling input')
        self.cfg['analysis']['git_diff']['base_ref']='HEAD'
        header.write_text('#define VALUE 9\n')
        self.save()
        before=self.git('status','--porcelain=v1','-uall'),self.git('ls-files','--stage')
        with contextlib.redirect_stdout(io.StringIO()):
            code=run(self.root,str(self.config),no_review=True,scan_mode='diff')
        self.assertEqual(code,3,'fixed commits must never consume the dirty original sibling header')
        self.assertEqual(before,(self.git('status','--porcelain=v1','-uall'),self.git('ls-files','--stage')))
        # Failure is explicit, rather than dropping the dependency from AST.
        diagnostics=list(Path(self.ws().results_root).glob('git_diff/artifacts/base-*/result_validity.json'))
        self.assertEqual(len(diagnostics),1)
        self.assertIn('原固件工作区输入',read_json(diagnostics[0])['error'])


if __name__ == '__main__':
    unittest.main()
