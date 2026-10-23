"""Actual Clang input races, bounded merge equivalence and failed-run validity."""
import copy
import contextlib
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_ecra
from ecra.analysis import merge
from ecra.cli import run
from ecra.common import read_json, write_json
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.fact_parts import FactParts
from ecra.input_snapshot import InputSnapshot, file_record


class ScanStabilityTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def test_gcc_numeric_lto_jobs_preserve_ast_and_original_command(self):
        from ecra.compilation import normalize_clang_arguments
        cfg = self.project({'a.c': 'int shared; void ISR(void){shared++;} void Task(void){shared++;}'})
        original = prepare(self.root, cfg)[0][0]
        expected = Extractor(dict(root=str(self.root), unit=original, config=cfg)).run()
        database = self.root/'compile_commands.json'
        entries = read_json(database)
        entries[0]['arguments'].insert(1, '-flto=1')
        write_json(database, entries)
        mapped = prepare(self.root, cfg)[0][0]
        self.assertIn('-flto=1', mapped['original_arguments'])
        self.assertIn('-flto=1', mapped['removed_arguments'])
        self.assertIn('-flto', mapped['arguments'])
        actual = Extractor(dict(root=str(self.root), unit=mapped, config=cfg)).run()
        self.assertEqual(actual['parse_status'], 'PARSED', actual['diagnostics'])
        for table in ('variables', 'functions', 'accesses', 'calls', 'unknowns', 'pointer_constraints',
                      'indirect_accesses', 'semantic_calls', 'protection_events', 'control_flow'):
            self.assertEqual(expected[table], actual[table], table)
        # Unknown LTO modes and ABI options must still produce diagnostics.
        kept, removed = normalize_clang_arguments(['-flto=thin', '-flto=unknown', '-mabi=unknown'],
                                                   self.root, self.root/'a.c')
        self.assertEqual(kept, ['-flto=thin', '-flto=unknown', '-mabi=unknown'])
        self.assertEqual(removed, [])
        kept, removed = normalize_clang_arguments(['-flto=1'], self.root, self.root/'a.c', ['-flto=1'])
        self.assertEqual(kept, [])
        self.assertEqual(removed, ['-flto=1'])

    def fixture(self):
        return self.project({'a.c': '#include "used.h"\nint shared;void ISR(void){shared++;}void Task(void){shared++;}',
                             'used.h': 'extern int shared;\n', 'unused.h': '/* not an input */\n'})

    def test_stream_merge_retains_cross_tu_type_variant_uncertainty(self):
        cfg = self.project({'a.c': 'int shared;void ISR(void){shared++;}',
                            'b.c': 'extern long long shared;void Task(void){shared++;}'})
        units, _ = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run() for unit in units]
        facts = merge(parts)
        shared = next(v for v in facts['variables'] if v['name'] == 'shared')
        issues = [u for u in facts['unknowns'] if u['kind'] == 'TYPE_VARIANT' and u['symbol_id'] == shared['symbol_id']]
        self.assertTrue(issues, facts['unknowns'])
        self.assertEqual(set(issues[0]['types']), {'int', 'long long'})

    def test_portable_external_database_toolchain_requires_explicit_opt_in_without_cmake(self):
        cfg = self.fixture()
        cfg['analysis']['auto_system_includes'] = False
        compiler = self.root/'external-gcc.exe'
        compiler.write_bytes(b'path audit fixture; never executed')
        database = self.root/'compile_commands.json'
        entries = read_json(database)
        entries[0]['arguments'][0] = str(compiler)
        write_json(database, entries)
        bundle = self.root/'bundle'
        with patch('ecra.compilation.bundle_root', return_value=bundle), \
                patch('ecra.portable.bundle_root', return_value=bundle), \
                patch('ecra.compilation.configure_cmake') as configure:
            with self.assertRaisesRegex(ValueError, 'Portable 外部工具路径'):
                prepare(self.root, cfg)
            cfg['analysis']['allow_external_toolchain'] = True
            units, audit = prepare(self.root, cfg)
            configure.assert_not_called()
        self.assertEqual(units[0]['original_arguments'], entries[0]['arguments'])
        self.assertTrue(any(row['external'] and row['path'] == str(compiler)
                            for row in audit['compilers']))

    def injected(self, action):
        from ecra.cli import execute as original
        applied = False
        def execute(argv, **kwargs):
            nonlocal applied
            result = original(argv, **kwargs)
            if 'ecra.extract' in argv and '.dependencies.' not in str(argv[-1]) and not applied:
                applied = True
                action()
            return result
        with patch('ecra.cli.execute', side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
            return run(self.root, no_review=True)

    def test_touch_and_unrelated_source_output_are_not_input_changes(self):
        self.fixture()
        def action():
            os.utime(self.root/'used.h', None)
            (self.root/'unused.h').write_text('/* changed */')
            (self.root/'new_unbuilt.c').write_text('int outside_build;')
            (self.root/'report.json').write_text('{"changed":true}')
        self.assertEqual(self.injected(action), 2)
        data = read_json(self.root/'.ecra/diagnostics/source_changes.json')
        self.assertEqual(data['status'], 'VERIFIED')
        self.assertEqual(data['changes'], [])
        self.assertIn('used.h', data['inputs_before'])
        self.assertNotIn('unused.h', data['inputs_before'])

    def test_header_content_change_and_deletion_fail_with_paths_and_hashes(self):
        for mode in ('change', 'delete'):
            with self.subTest(mode=mode):
                self.fixture()
                before = file_record(self.root/'used.h')['sha256']
                def action():
                    if mode == 'change':
                        (self.root/'used.h').write_text('extern long shared;\n')
                    else:
                        (self.root/'used.h').unlink()
                self.assertEqual(self.injected(action), 3)
                data = read_json(self.root/'.ecra/diagnostics/source_changes.json')
                change = next(row for row in data['changes'] if row['file'] == 'used.h')
                self.assertEqual(change['before']['sha256'], before)
                self.assertFalse((self.root/'.ecra/scan_state.json').exists())
                self.assertFalse(read_json(self.root/'.ecra/result_validity.json')['analysis_valid'])

    def test_new_shadow_header_is_detected_by_clang_resolution(self):
        self.fixture()
        first, second = self.root/'first', self.root/'second'
        first.mkdir(); second.mkdir()
        (self.root/'used.h').replace(second/'used.h')
        database = self.root/'compile_commands.json'
        entries = read_json(database)
        entries[0]['arguments'][1:1] = ['-Ifirst', '-Isecond']
        write_json(database, entries)
        self.assertEqual(self.injected(lambda: (first/'used.h').write_text('extern int shared;\n')), 3)
        data = read_json(self.root/'.ecra/diagnostics/source_changes.json')
        self.assertTrue(any(row['reason'] == 'DEPENDENCY_SET_CHANGED' and row['file'] == 'first/used.h'
                            for row in data['changes']))

    def test_negative_has_include_probe_cannot_silently_change_active_branch(self):
        self.project({'a.c': '#if __has_include("feature.flag")\nint changed;\n#else\nint original;\n#endif\n'
                      'int main(void){return 0;}'})
        self.assertEqual(self.injected(lambda: (self.root/'feature.flag').write_text('present')), 3)
        data = read_json(self.root/'.ecra/diagnostics/source_changes.json')
        self.assertTrue(any(row['reason'] == 'PREPROCESSOR_STATE_CHANGED' for row in data['changes']))

    def test_saved_snapshot_detects_new_shadow_header_before_resume(self):
        from ecra.workflow import status
        self.fixture()
        first, second = self.root/'first', self.root/'second'
        first.mkdir(); second.mkdir()
        (self.root/'used.h').replace(second/'used.h')
        entries = read_json(self.root/'compile_commands.json')
        entries[0]['arguments'][1:1] = ['-Ifirst', '-Isecond']
        write_json(self.root/'compile_commands.json', entries)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        self.assertTrue(status(self.root)['resumable'])
        (first/'used.h').write_text('extern int shared; /* new effective input */\n')
        self.assertFalse(status(self.root)['resumable'])

    def test_saved_snapshot_detects_new_negative_probe_before_resume(self):
        from ecra.workflow import status
        self.project({'a.c': '#if __has_include("feature.h")\nint changed;\n#else\nint original;\n#endif\n'
                      'int main(void){return 0;}'})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        self.assertTrue(status(self.root)['resumable'])
        (self.root/'feature.h').write_text('/* newly available */\n')
        self.assertFalse(status(self.root)['resumable'])

    def test_saved_snapshot_accepts_touch_and_new_unrelated_files(self):
        from ecra.workflow import status
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        os.utime(self.root/'used.h', None)
        (self.root/'new-unused.h').write_text('/* not resolved by this target */\n')
        (self.root/'report-output.json').write_text('{"new":true}')
        self.assertTrue(status(self.root)['resumable'])
        self.assertEqual(read_json(self.root/'.ecra/diagnostics/resume_source_changes.json')['status'], 'VERIFIED')

    def test_saved_input_closure_is_bound_to_checkpoint_even_without_diagnostics(self):
        from ecra.workflow import status
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        out = self.root/'.ecra'
        self.assertTrue(read_json(out/'scan_state.json')['input_closure_sha256'])
        (out/'diagnostics/source_changes.json').unlink()
        closure = read_json(out/'input_closure.json')
        closure['units'] = []
        write_json(out/'input_closure.json', closure)
        self.assertFalse(status(self.root)['resumable'])

    def test_saved_report_change_during_render_invalidates_publication(self):
        from ecra.workflow import saved_run
        from ecra.report import generate
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        def emitted(*args, **kwargs):
            generate(*args, **kwargs)
            (self.root/'used.h').write_text('extern int shared; /* changed during saved render */\n')
        with patch('ecra.workflow.generate', side_effect=emitted), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                saved_run(self.root, render_only=True)
        out = self.root/'.ecra'
        self.assertFalse(read_json(out/'result_validity.json')['analysis_valid'])
        self.assertFalse((out/'scan_state.json').exists())
        self.assertIn('不能使用旧结论', (out/'index.html').read_text(encoding='utf-8'))
        self.assertFalse(read_json(out/'reports/global_static_concurrency.json')['analysis_valid'])

    def test_saved_report_analysis_config_change_during_render_is_rejected(self):
        from ecra.workflow import saved_run
        from ecra.report import generate
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        def emitted(*args, **kwargs):
            generate(*args, **kwargs)
            config = self.root/'.ecra/semantics.yaml'
            cfg = read_json(config)
            cfg['contexts'][0]['functions'].append('NewISR')
            write_json(config, cfg)
        with patch('ecra.workflow.generate', side_effect=emitted), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                saved_run(self.root, render_only=True)
        self.assertFalse(read_json(self.root/'.ecra/result_validity.json')['analysis_valid'])

    def test_saved_report_touch_and_unrelated_creation_during_render_are_accepted(self):
        from ecra.workflow import saved_run, status
        from ecra.report import generate
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        def emitted(*args, **kwargs):
            generate(*args, **kwargs)
            os.utime(self.root/'used.h', None)
            (self.root/'new-unused.h').write_text('/* still not a dependency */\n')
        with patch('ecra.workflow.generate', side_effect=emitted), contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(self.root, render_only=True), (0, 1, 2))
        self.assertTrue(status(self.root)['resumable'])

    def test_legacy_broad_checkpoint_can_still_render_without_input_capsule(self):
        from ecra.workflow import saved_run, file_digest
        from ecra.cli import file_hashes
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        out = self.root/'.ecra'
        config = out/'semantics.yaml'
        # Recreate the old broad manifest contract rather than relabeling a
        # precise manifest as legacy and silently dropping unrelated headers.
        write_json(out/'input_manifest.json', file_hashes(self.root, out, [config, self.root/'compile_commands.json']))
        state = read_json(out/'scan_state.json')
        state.pop('input_closure_sha256')
        state['manifest_sha256'] = file_digest(out/'input_manifest.json')
        write_json(out/'scan_state.json', state)
        (out/'input_closure.json').unlink()
        (out/'diagnostics/source_changes.json').unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(self.root, render_only=True), (0, 1, 2))

    def test_source_and_nested_response_configuration_changes_fail(self):
        for name in ('a.c', 'nested.rsp', 'compile_commands.json'):
            with self.subTest(name=name):
                self.fixture()
                (self.root/'nested.rsp').write_text('-DFEATURE=1')
                entries = read_json(self.root/'compile_commands.json')
                entries[0]['arguments'].insert(1, '@nested.rsp')
                write_json(self.root/'compile_commands.json', entries)
                def action():
                    with (self.root/name).open('a') as stream:
                        stream.write('\n' if name.endswith('.json') else '\n/*changed*/\n')
                self.assertEqual(self.injected(action), 3)
                self.assertTrue(any(row['file'] == name for row in
                    read_json(self.root/'.ecra/diagnostics/source_changes.json')['changes']))

    def test_configuration_changed_after_consumption_before_snapshot_is_rejected(self):
        for name in ('compile_commands.json', 'flags.rsp', '.ecra/semantics.yaml'):
            with self.subTest(name=name):
                self.fixture()
                response = self.root/'flags.rsp'
                response.write_text('-DFEATURE=1', encoding='utf-8')
                entries = read_json(self.root/'compile_commands.json')
                entries[0]['arguments'].insert(1, '@flags.rsp')
                write_json(self.root/'compile_commands.json', entries)
                def prepared(*args, **kwargs):
                    result = prepare(*args, **kwargs)
                    target = self.root/name
                    if name.endswith('.rsp'):
                        target.write_text('-DFEATURE=2', encoding='utf-8')
                    elif name.endswith('.yaml'):
                        cfg = read_json(target)
                        cfg['analysis']['extra_args'] = ['-DFEATURE=2']
                        write_json(target, cfg)
                    else:
                        changed = read_json(target)
                        changed[0]['arguments'].insert(1, '-DNEW_CONFIG=1')
                        write_json(target, changed)
                    return result
                with patch('ecra.cli.prepare', side_effect=prepared), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run(self.root, no_review=True), 3)
                changes = read_json(self.root/'.ecra/diagnostics/source_changes.json')['changes']
                self.assertTrue(any(row['file'] == name for row in changes))
                self.assertFalse(read_json(self.root/'.ecra/result_validity.json')['analysis_valid'])

    def test_response_changes_between_units_and_restores_before_snapshot_still_fail(self):
        from ecra.input_snapshot import read_consumed_text
        self.project({'a.c': 'int shared;void ISR(void){shared++;}',
                      'b.c': 'extern int shared;void Task(void){shared++;}'})
        response = self.root/'flags.rsp'
        response.write_text('-DFEATURE=1', encoding='utf-8')
        entries = read_json(self.root/'compile_commands.json')
        for entry in entries:
            entry['arguments'].insert(1, '@flags.rsp')
        write_json(self.root/'compile_commands.json', entries)
        reads = 0
        def consumed(path, records):
            nonlocal reads
            result = read_consumed_text(path, records)
            if Path(path) == response:
                reads += 1
                response.write_text('-DFEATURE=2' if reads == 1 else '-DFEATURE=1', encoding='utf-8')
            return result
        with patch('ecra.input_snapshot.read_consumed_text', side_effect=consumed), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        self.assertEqual(reads, 2)
        change = next(row for row in read_json(self.root/'.ecra/diagnostics/source_changes.json')['changes']
                      if row['file'] == 'flags.rsp')
        self.assertEqual(change['before']['sha256'], change['after']['sha256'])
        self.assertTrue(change['before']['unstable'])

    def test_unreadable_and_missing_inputs_fail_closed(self):
        self.fixture()
        snapshot = InputSnapshot(self.root, self.root/'.ecra/diagnostics', [self.root/'used.h'])
        with patch('ecra.input_snapshot.file_record', return_value=dict(status='UNREADABLE', sha256=None)):
            snapshot.verify_disk()
        with self.assertRaises(ValueError):
            snapshot.assert_valid()
        missing = InputSnapshot(self.root, self.root/'.ecra/diagnostics', [self.root/'absent.h'])
        with self.assertRaises(ValueError):
            missing.seal()

    def test_main_memory_failure_invalidates_old_report_and_keeps_trace(self):
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
            with patch('ecra.cli.merge', side_effect=MemoryError('controlled-main-memory-fault')):
                self.assertEqual(run(self.root, no_review=True), 3)
        out = self.root/'.ecra'
        info = read_json(out/'diagnostics/exception.json')
        self.assertEqual(info['exception_type'], 'MemoryError')
        self.assertEqual(info['origin'], 'MAIN')
        self.assertEqual(info['completed_units'], 1)
        self.assertEqual(info['fact_counts_scope'], 'translation_unit_rows_including_duplicates')
        self.assertIn('跨翻译单元事实归并', info['stage']['stage'])
        self.assertIn('controlled-main-memory-fault', (out/'diagnostics/exception.log').read_text(encoding='utf-8'))
        self.assertFalse((out/'scan_state.json').exists())
        self.assertIn('不能使用旧结论', (out/'index.html').read_text(encoding='utf-8'))
        self.assertFalse(read_json(out/'reports/global_static_concurrency.json')['analysis_valid'])
        self.assertTrue(list((out/'snapshots').glob('*/index.html')))

    def test_post_merge_memory_failure_reports_merged_counts(self):
        self.project({'a.c': 'int shared; void ISR(void){shared++;}',
                      'b.c': 'extern int shared; void Task(void){shared++;}'})
        counts = {}
        def fail(facts, *args, **kwargs):
            facts['functions'].append(dict(function_id='synthetic-added-during-analysis'))
            counts.update({key: len(value) for key, value in facts.items() if isinstance(value, list)})
            raise MemoryError('controlled-post-merge-fault')
        with patch('ecra.cli.analyze', side_effect=fail), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        info = read_json(self.root/'.ecra/diagnostics/exception.json')
        self.assertEqual(info['fact_counts_scope'], 'merged_facts')
        self.assertEqual(info['fact_counts'], counts)
        self.assertEqual(info['fact_counts']['variables'], 1)
        self.assertEqual(info['completed_units'], 2)

    def test_worker_memory_failure_is_saved_in_worker_process_and_fatal_in_parent(self):
        self.fixture()
        from ecra.cli import execute as original
        def execute(argv, **kwargs):
            if 'ecra.extract' in argv and '.dependencies.' not in str(argv[-1]):
                snippet = ('import sys;from unittest.mock import patch;from ecra.extract import main;'
                           'sys.argv=["fault",sys.argv[1],sys.argv[2]];'
                           'p=patch("ecra.extract.Extractor.run",side_effect=MemoryError("controlled-worker-memory-fault"));'
                           'p.start();main()')
                argv = [sys.executable, '-c', snippet, *argv[-2:]]
            return original(argv, **kwargs)
        with patch('ecra.cli.execute', side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        out = self.root/'.ecra'
        info = read_json(out/'diagnostics/workers/TU-00000/exception.json')
        self.assertEqual(info['origin'], 'WORKER')
        self.assertNotEqual(info['pid'], os.getpid())
        self.assertEqual(info['exception_type'], 'MemoryError')
        self.assertIn('MemoryError', read_json(out/'run.json')['error'])
        self.assertFalse((out/'scan_state.json').exists())

    def test_interrupt_invalidates_checkpoint_and_releases_scan_lock(self):
        self.fixture()
        with patch('ecra.cli.merge', side_effect=KeyboardInterrupt()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root,no_review=True),130)
        out = self.root/'.ecra'
        self.assertFalse((out/'scan.lock').exists())
        self.assertFalse((out/'scan_state.json').exists())
        self.assertEqual(read_json(out/'run.json')['state'],'INTERRUPTED')
        self.assertFalse(read_json(out/'reports/global_static_concurrency.json')['analysis_valid'])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing contract')
    def test_windows_locked_input_is_unreadable_and_recovers_after_unlock(self):
        self.fixture()
        import ctypes
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
        kernel.CreateFileW.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        path = self.root/'used.h'
        before = file_record(path)
        handle = kernel.CreateFileW(str(path),0x80000000,0,None,3,128,None)
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        try:
            self.assertEqual(file_record(path)['status'],'UNREADABLE')
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual(file_record(path)['sha256'],before['sha256'])
        handles = []
        def lock_during_scan():
            opened = kernel.CreateFileW(str(path),0x80000000,0,None,3,128,None)
            self.assertNotEqual(opened,ctypes.c_void_p(-1).value)
            handles.append(opened)
        try:
            self.assertEqual(self.injected(lock_during_scan), 3)
            self.assertFalse((self.root/'.ecra/scan.lock').exists())
            self.assertFalse((self.root/'.ecra/scan_state.json').exists())
            self.assertFalse(read_json(self.root/'.ecra/result_validity.json')['analysis_valid'])
        finally:
            for opened in handles:
                kernel.CloseHandle(opened)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)

    @unittest.skipUnless(shutil.which('cmake'), 'CMake generator required')
    def test_actual_cmake_generation_distinguishes_used_header_from_unrelated_output(self):
        self.fixture()
        script = self.root/'generate.cmake'
        script.write_text('file(WRITE "${CMAKE_CURRENT_LIST_DIR}/${OUTPUT}" "extern ${VALUE} shared;\\n")\n')
        def generate(output):
            subprocess.run([shutil.which('cmake'), '-DVALUE=long', '-DOUTPUT='+output, '-P', str(script)],
                           check=True, capture_output=True)
        self.assertEqual(self.injected(lambda: generate('unused-generated.h')), 2)
        self.assertEqual(self.injected(lambda: generate('used.h')), 3)
        changes = read_json(self.root/'.ecra/diagnostics/source_changes.json')['changes']
        self.assertTrue(any(row['file'] == 'used.h' and row['before']['sha256'] != row['after']['sha256']
                            for row in changes))

    def test_sqlite_oom_closes_handle_and_preserves_published_database(self):
        from ecra.report import write_database
        path = self.root/'facts.db'
        path.write_bytes(b'old published database sentinel')
        facts = dict(accesses=[],variables=[dict(symbol_id='x', nested={'layout':[1,2]})])
        with patch('ecra.report.json.dumps',side_effect=MemoryError('controlled-sqlite-serialization')):
            with self.assertRaises(MemoryError):
                write_database(path,facts,dict(findings=[]))
        self.assertEqual(path.read_bytes(),b'old published database sentinel')
        # Windows forbids this if a failed SQLite writer still holds its handle.
        path.with_suffix('.db.tmp').replace(self.root/'closed-failed-database.tmp')

    def test_failed_history_backup_preserves_previous_json_and_invalidates_current_run(self):
        self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root,no_review=True),2)
        out = self.root/'.ecra'
        previous = (out/'reports/global_static_concurrency.json').read_bytes()
        with patch('ecra.cli.shutil.copytree',side_effect=PermissionError('controlled-backup-denial')), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root,no_review=True),3)
        self.assertEqual((out/'reports/global_static_concurrency.json').read_bytes(),previous)
        self.assertFalse(read_json(out/'result_validity.json')['analysis_valid'])
        self.assertFalse((out/'scan.lock').exists())

    def test_replayable_merge_preserves_all_facts_and_weak_resolution(self):
        cfg = self.project({'a.c':'int g;__attribute__((weak)) void Handler(void){g++;}void Task(void){Handler();}',
                            'b.c':'extern int g;void Handler(void){g=7;}void ISR(void){Handler();}'})
        units, _ = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run() for unit in units]
        expected = merge(copy.deepcopy(parts))
        stored = FactParts()
        for index, part in enumerate(parts):
            path = self.root/f'part{index}.json'
            write_json(path, part)
            stored.append(path, part)
        self.assertEqual(expected, merge(stored))
        self.assertEqual(expected, merge(stored))

    def test_streaming_merge_retains_synthetic_failed_source_blockers(self):
        diagnostic = [dict(severity=4,message='missing required input')]
        facts = merge([dict(parse_status='FAILED',functions=[dict(function_id='f',file='broken.c')],
                            diagnostics=diagnostic,unknowns=[])])
        self.assertIn(dict(kind='PARSE_FAILED',file='broken.c',diagnostics=diagnostic),facts['unknowns'])

    def test_parallel_workers_and_review_toggle_preserve_static_evidence(self):
        self.project({'a.c':'int g;void Write(void);void ISR(void){Write();}',
                      'b.c':'extern int g;void Write(void){g++;}void Task(void){Write();}'})
        cfg_file = self.root/'.ecra/semantics.yaml'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root,no_review=True),2)
        first = read_json(self.root/'.ecra/facts.json')
        cfg = read_json(cfg_file)
        cfg['analysis']['extraction_workers'] = 2
        cfg['review'].update(enabled=True, command=[sys.executable])
        write_json(cfg_file, cfg)
        with contextlib.redirect_stdout(io.StringIO()), patch('ecra.cli.review_all',
              side_effect=lambda *a, **kw: read_json(self.root/'.ecra/review/queue.json')):
            self.assertEqual(run(self.root),2)
        second = read_json(self.root/'.ecra/facts.json')
        for table in ('variables','functions','accesses','calls','contexts','protection_events','pointer_constraints'):
            self.assertEqual(first[table],second[table], table)

    def test_used_header_change_during_final_report_invalidates_publication(self):
        from ecra.report import generate
        self.fixture()
        config = self.root/'.ecra/semantics.yaml'
        cfg = read_json(config)
        cfg['review'].update(enabled=False, prepare_packets=False)
        write_json(config, cfg)
        def emitted(*args, **kwargs):
            generate(*args, **kwargs)
            (self.root/'used.h').write_text('extern int shared; /* changed during report */\n')
        with patch('ecra.cli.generate', side_effect=emitted), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        out = self.root/'.ecra'
        self.assertFalse(read_json(out/'result_validity.json')['analysis_valid'])
        self.assertFalse((out/'scan_state.json').exists())
        self.assertTrue(any(row['file'] == 'used.h' for row in
                            read_json(out/'diagnostics/source_changes.json')['changes']))

    def test_negative_include_probe_change_during_report_is_detected(self):
        from ecra.report import generate
        self.project({'a.c': '#if __has_include("feature.flag")\nint changed;\n#else\nint original;\n#endif\n'
                      'int main(void){return 0;}'})
        config = self.root/'.ecra/semantics.yaml'
        cfg = read_json(config)
        cfg['review'].update(enabled=False, prepare_packets=False)
        write_json(config, cfg)
        def emitted(*args, **kwargs):
            generate(*args, **kwargs)
            (self.root/'feature.flag').write_text('present')
        with patch('ecra.cli.generate', side_effect=emitted), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        changes = read_json(self.root/'.ecra/diagnostics/source_changes.json')['changes']
        self.assertTrue(any(row['reason'] == 'PREPROCESSOR_STATE_CHANGED' for row in changes))

    def test_touch_and_unrelated_output_during_report_remain_valid(self):
        from ecra.report import generate
        self.fixture()
        config = self.root/'.ecra/semantics.yaml'
        cfg = read_json(config)
        cfg['review'].update(enabled=False, prepare_packets=False)
        write_json(config, cfg)
        def emitted(*args, **kwargs):
            generate(*args, **kwargs)
            os.utime(self.root/'used.h', None)
            (self.root/'unrelated-output.json').write_text('{"changed":true}')
        with patch('ecra.cli.generate', side_effect=emitted), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        snapshot = read_json(self.root/'.ecra/diagnostics/source_changes.json')
        self.assertEqual(snapshot['status'], 'VERIFIED')
        self.assertEqual(snapshot['changes'], [])

    def test_static_engine_change_during_report_invalidates_checkpoint(self):
        from ecra.report import generate
        from ecra.workflow import engine_digest
        self.fixture()
        config = self.root/'.ecra/semantics.yaml'
        cfg = read_json(config)
        cfg['review'].update(enabled=False, prepare_packets=False)
        write_json(config, cfg)
        changed = False
        def emitted(*args, **kwargs):
            nonlocal changed
            generate(*args, **kwargs)
            changed = True
        with patch('ecra.cli.generate', side_effect=emitted), patch('ecra.workflow.engine_digest',
                side_effect=lambda: 'changed-after-publication' if changed else engine_digest()), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 3)
        self.assertFalse(read_json(self.root/'.ecra/result_validity.json')['analysis_valid'])
        self.assertFalse((self.root/'.ecra/scan_state.json').exists())


if __name__ == '__main__':
    unittest.main()
