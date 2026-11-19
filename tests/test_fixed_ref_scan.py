"""Stage one: real refs, fixed build inputs, editing and publication barriers."""
import contextlib
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.git_diff import assert_pin, pin, prepare_current, write_comparison_patch
from ecra.report_package import sha256
from ecra.scan_persistence import run_canonical
from ecra.scan_store import EvidenceProvider
from ecra.workflow import checked_scan, output_path
from tests import test_canonical_scan as fixtures


class FixedRefScanTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.CanonicalScanTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.config, self.data, self.home = fixture.root, fixture.config, fixture.data, fixture.base
        self.git, _ = fixture.pinned_diff_project()
        self.git('branch', 'current')
        self.git('tag', 'v-base', 'base')
        self.git('tag', '-a', 'v-current', '-m', 'annotated current', 'current')
        self.base_sha, self.current_sha = self.git('rev-parse', 'base'), self.git('rev-parse', 'current')
        raw = read_json(self.config)
        raw['analysis']['git_diff']['current_ref'] = 'current'
        write_json(self.config, raw)
        self.cfg, _ = load_config(self.root, self.config)
        from ecra.workspace import WorkspaceResolver
        self.ws = WorkspaceResolver.resolve(self.root, self.cfg['analysis']).initialize()
        self.ws.bind(self.cfg['analysis'])

    def scan(self, ident, expected=(0, 1, 2)):
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            code = run_canonical(self.root, self.config, no_review=True, scan_id=ident, profile_id='fixed-ref')
        self.assertIn(code, expected, log.getvalue())
        return self.data/'scans'/ident

    def report(self, out):
        return EvidenceProvider(out/'scan.db').load('report')

    def original_files(self):
        return {p.relative_to(self.root).as_posix(): (sha256(p), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_T31_branch_tag_matrix_uses_one_commit_and_git_view_for_source_and_patch(self):
        before = self.original_files()
        for old, new in [('base', 'current'), ('v-base', 'v-current'), ('base', 'v-current'), ('v-base', 'current')]:
            with self.subTest(base=old, current=new):
                self.cfg['analysis']['git_diff'].update(base_ref=old, current_ref=new)
                fixed = pin(self.root, self.cfg)
                self.assertEqual((fixed['base_sha'], fixed['head_sha']), (self.base_sha, self.current_sha))
                self.assertEqual((fixed['base_ref'], fixed['current_ref']), (old, new))
                source, cfg = prepare_current(self.root, Path(self.ws.results_root), self.cfg, fixed, lambda _: None)
                self.assertEqual((source/'main.c').read_bytes(), (self.root/'main.c').read_bytes())
                self.assertNotEqual(Path(cfg['analysis']['compile_database']), self.root/'compile_commands.json')
                patch_file = self.home/'comparison.patch'
                write_comparison_patch(fixed, patch_file)
                expected = subprocess.check_output(['git', '-C', str(self.root), 'diff', '--binary', '--no-color',
                    '--src-prefix=a/', '--dst-prefix=b/', self.base_sha, self.current_sha, '--'])
                self.assertEqual(patch_file.read_bytes(), expected)
                assert_pin(self.root, self.cfg, fixed)
        self.assertEqual(self.original_files(), before)

    def test_T01_T32_tip_comparison_excludes_staged_unstaged_and_untracked_bytes(self):
        clean = pin(self.root, self.cfg)
        (self.root/'main.c').write_text('int staged_only;\n', 'utf-8')
        self.git('add', 'main.c')
        (self.root/'main.c').write_text('int live_only;\n', 'utf-8')
        (self.root/'new.h').write_text('#define UNTRACKED 1\n', 'utf-8')
        before = self.original_files()
        self.assertEqual(pin(self.root, self.cfg), clean)
        assert_pin(self.root, self.cfg, clean)
        self.assertEqual(self.original_files(), before)
        # Divergent history with the same tree must compare tips, not merge-base.
        same_tree = self.git('commit-tree', self.git('rev-parse', 'current^{tree}'), '-p', 'base', '-m', 'diverged')
        self.git('update-ref', 'refs/heads/diverged', same_tree)
        self.cfg['analysis']['git_diff']['base_ref'] = 'diverged'
        self.assertEqual(pin(self.root, self.cfg)['files'], [])

    def test_T33_T34_edits_during_baseline_extraction_and_publication_keep_archived_inputs(self):
        from ecra import cli, git_diff
        clean = self.scan('clean')
        expected = self.report(clean)
        baseline, extraction, dependencies = git_diff.prepare_base, cli.extraction_responses, cli.dependency_results
        events = []
        dependency_calls = 0

        def during_baseline(*args, **kwargs):
            (self.root/'main.c').write_text('int staged_during_baseline;\n', 'utf-8')
            self.git('add', 'main.c')
            events.append('baseline')
            return baseline(*args, **kwargs)

        def during_extraction(root, units, cfg, *args, **kwargs):
            if cfg['analysis']['git_diff']['enabled']:
                self.git('checkout', '-b', 'continue-editing', 'current')
                (self.root/'main.c').write_text('int edited_during_extraction;\n', 'utf-8')
                (self.root/'new.h').write_text('#define NEW_WORK 1\n', 'utf-8')
                events.append('extraction')
            yield from extraction(root, units, cfg, *args, **kwargs)

        def before_publication(root, units, cfg, *args, **kwargs):
            nonlocal dependency_calls
            if cfg['analysis']['git_diff']['enabled']:
                dependency_calls += 1
                if dependency_calls == 2:
                    self.git('update-ref', 'refs/heads/current', 'base')
                    self.git('tag', '-f', 'v-current', 'base')
                    live = read_json(self.config)
                    live['analysis']['extra_args'] = ['-DPROFILE_EDITED_LATER=1']
                    write_json(self.config, live)
                    events.append('publication')
            yield from dependencies(root, units, cfg, *args, **kwargs)

        with patch.object(git_diff, 'prepare_base', side_effect=during_baseline), \
                patch.object(cli, 'extraction_responses', side_effect=during_extraction), \
                patch.object(cli, 'dependency_results', side_effect=before_publication):
            edited = self.scan('edited')
        actual = self.report(edited)
        self.assertEqual(events, ['baseline', 'extraction', 'publication'])
        self.assertEqual(actual['git_diff']['pin']['head_sha'], self.current_sha)
        self.assertEqual(actual['git_diff']['selected_symbol_ids'], expected['git_diff']['selected_symbol_ids'])
        self.assertEqual(Path(actual['git_diff']['pin']['diff_patch_path']).read_bytes(),
                         Path(expected['git_diff']['pin']['diff_patch_path']).read_bytes())
        old_facts = EvidenceProvider(clean/'scan.db').load('facts')
        new_facts = EvidenceProvider(edited/'scan.db').load('facts')
        for variable in old_facts['variables']:
            if 'impact' in variable:
                for key in ('base_facts_path', 'base_summary_path', 'diff_patch_path'):
                    old_path = Path(variable['impact'][key])
                    new_path = Path(actual['git_diff']['pin'][key])
                    self.assertEqual(sha256(old_path), sha256(new_path))
                    variable['impact'][key] = str(new_path)
        self.assertEqual(new_facts, old_facts)
        live_cfg, _ = load_config(self.root, self.config)
        for out in (clean, edited):
            checked_scan(self.root, out, live_cfg, self.config, with_facts=False)
        self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD'), 'continue-editing')
        self.assertEqual((self.root/'main.c').read_text('utf-8'), 'int edited_during_extraction;\n')
        self.assertIn('staged_during_baseline', self.git('show', ':main.c'))
        self.assertEqual(pin(self.root, live_cfg)['head_sha'], self.base_sha, 'A new scan resolves new refs')

    def test_T25_T35_private_metadata_source_configuration_and_archives_are_still_verified(self):
        good = self.scan('good')
        report = self.report(good)
        fixed = report['git_diff']['pin']
        original_authority = sha256(good/'scan.db')
        for path in [Path(fixed['current_source_root'])/'main.c', Path(fixed['config_path']),
                     Path(fixed['diff_patch_path']), Path(fixed['base_summary_path'])]:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                try:
                    path.write_bytes(b'changed private input')
                    with self.assertRaises(ValueError):
                        checked_scan(self.root, good, self.cfg, self.config, with_facts=False)
                finally:
                    path.write_bytes(original)
        private = Path(fixed['frozen_git']['repository'])
        subprocess.check_call(['git', '-C', str(private), 'tag', 'private-tampering'], stdout=subprocess.DEVNULL)
        with self.assertRaisesRegex(ValueError, '固定 Git'):
            checked_scan(self.root, good, self.cfg, self.config, with_facts=False)
        failed = self.scan('bad-private', expected=(3,))
        self.assertFalse((failed/'manifest.json').exists())
        self.assertEqual(output_path(self.root, self.cfg), good)
        self.assertEqual(sha256(good/'scan.db'), original_authority)

    def test_T32_dirty_diff_rejected_before_capture_and_full_mode_preserved(self):
        from ecra.git_diff import settings, validate_mode
        from ecra import cli
        from ecra.frozen_scan import execution_workspace
        full = dict(enabled=False, current_ref='HEAD', include_uncommitted=True)
        self.assertTrue(settings(full)['include_uncommitted'])
        with self.assertRaisesRegex(ValueError, 'Diff 只支持'):
            validate_mode(settings(dict(full, enabled=True)))
        raw = read_json(self.config)
        raw['analysis']['git_diff'].update(full)
        write_json(self.config, raw)
        with patch('ecra.dirty_inputs.capture_inputs', side_effect=AssertionError('must reject before capture')):
            for runner in (cli.run, run_canonical):
                with self.subTest(runner=runner.__name__), self.assertRaisesRegex(ValueError, 'Diff 只支持'):
                    runner(self.root, self.config, scan_mode='diff')
        with self.assertRaisesRegex(ValueError, 'Diff 只支持'):
            execution_workspace(self.root, dict(self.cfg['analysis'], git_diff=dict(full, enabled=True)), object())

    def test_T35_real_cmake_git_describe_keeps_original_tags_until_next_scan(self):
        import shutil
        if not all(shutil.which(name) for name in ('cmake', 'ninja', 'arm-none-eabi-gcc')):
            self.skipTest('Requires CMake, Ninja and ARM GCC')
        (self.root/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(fixed_git_inputs C)
find_package(Git REQUIRED)
execute_process(COMMAND "${GIT_EXECUTABLE}" describe --tags --always
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}" OUTPUT_VARIABLE VERSION OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY)
file(WRITE "${CMAKE_BINARY_DIR}/git-version.txt" "${VERSION}")
add_library(firmware STATIC main.c)
target_compile_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb)
target_compile_definitions(firmware PRIVATE VERSION_TEXT="${VERSION}")
''', 'utf-8')
        self.git('add', 'CMakeLists.txt')
        self.git('commit', '-m', 'CMake reads Git metadata')
        self.git('branch', 'build-base')
        self.git('branch', 'build-current')
        self.git('tag', 'build-frozen')
        raw = read_json(self.config)
        raw['analysis'].update(compile_database='auto', cmake=dict(generator='Ninja', build=True,
            args=['-DCMAKE_SYSTEM_NAME=Generic', '-DCMAKE_C_COMPILER=arm-none-eabi-gcc',
                  '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']))
        raw['analysis']['git_diff'].update(base_ref='build-base', current_ref='build-current')
        write_json(self.config, raw)
        from ecra import git_diff
        original = git_diff.prepare_base

        def move_tag_after_baseline(*args, **kwargs):
            result = original(*args, **kwargs)
            self.git('tag', '-d', 'build-frozen')
            self.git('tag', 'build-later')
            return result

        with patch.object(git_diff, 'prepare_base', side_effect=move_tag_after_baseline):
            out = self.scan('metadata-build')
        fixed = self.report(out)['git_diff']['pin']
        for side in ('base', 'current'):
            self.assertEqual((Path(fixed[side+'_build_path'])/'git-version.txt').read_text(), 'build-frozen')
        cfg, _ = load_config(self.root, self.config)
        checked_scan(self.root, out, cfg, self.config, with_facts=False)
        newer = self.scan('metadata-next')
        new_fixed = self.report(newer)['git_diff']['pin']
        self.assertNotEqual(new_fixed['frozen_git']['id'], fixed['frozen_git']['id'])
        self.assertEqual((Path(new_fixed['current_build_path'])/'git-version.txt').read_text(), 'build-later')
        self.assertEqual((Path(fixed['current_build_path'])/'git-version.txt').read_text(), 'build-frozen')

    def test_T25_baseline_only_external_build_input_change_blocks_publication(self):
        sdk = self.home/'external-sdk.h'
        sdk.write_text('#define BASE_VALUE 1\n', 'utf-8')
        source = (self.root/'main.c').read_text('utf-8')
        (self.root/'main.c').write_text('#include "' + sdk.as_posix() + '"\n' + source, 'utf-8')
        self.git('add', 'main.c'); self.git('commit', '-m', 'baseline external input')
        self.git('branch', '-f', 'base', 'HEAD')
        (self.root/'main.c').write_text(source, 'utf-8')
        self.git('commit', '-am', 'current no longer uses baseline SDK')
        self.git('branch', '-f', 'current', 'HEAD')
        from ecra import git_diff
        original = git_diff.prepare_base

        def change_sdk(*args, **kwargs):
            result = original(*args, **kwargs)
            sdk.write_text('#define BASE_VALUE 2\n', 'utf-8')
            return result

        with patch.object(git_diff, 'prepare_base', side_effect=change_sdk):
            failed = self.scan('sdk-changed', expected=(3,))
        self.assertFalse((failed/'manifest.json').exists())
        self.assertIn('external-sdk.h', read_json(failed/'result_validity.json')['error'])

    def test_T34_studio_preflight_handoff_keeps_same_versions_and_effective_configuration(self):
        from ecra.studio.preflight import run_preflight
        with contextlib.redirect_stdout(io.StringIO()):
            preflight = run_preflight(self.config, self.data, self.data/'work/preflight')
        fixed = preflight['git']
        self.git('update-ref', 'refs/heads/current', 'base')
        raw = read_json(self.config)
        raw['analysis']['extra_args'] = ['-DCHANGED_AFTER_PREFLIGHT=1']
        write_json(self.config, raw)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            code = run_canonical(self.root, self.config, no_review=True, scan_id='handoff', _git_pin=fixed)
        self.assertIn(code, (0, 1, 2), log.getvalue())
        out = self.data/'scans/handoff'
        result = self.report(out)['git_diff']['pin']
        self.assertEqual(result['head_sha'], self.current_sha)
        self.assertEqual(result['config_sha256'], fixed['config_sha256'])
        self.assertEqual(result['frozen_git'], fixed['frozen_git'])
        from ecra.scan_identity import query
        self.assertEqual(query(EvidenceProvider(out/'scan.db'))['config_sha256'], fixed['config_sha256'])
        cfg, _ = load_config(self.root, self.config)
        checked_scan(self.root, out, cfg, self.config, with_facts=False)


if __name__ == '__main__':
    unittest.main()
