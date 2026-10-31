import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.workspace import WorkspaceResolver, formal_workspace, user_data_root


class StudioWorkspaceTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','NTFS tool aliases')
    def test_tool_environment_aliases_whole_bundle_so_gcc_sibling_layout_survives(self):
        from ecra.portable import tool_environment,tool_path
        with tempfile.TemporaryDirectory(prefix='ECRA 工具 中文 ') as folder:
            root=Path(folder).resolve();binary=root/'tools/arm-gcc/bin/arm-none-eabi-gcc.exe'
            binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture')
            helper=root/'tools/arm-gcc/libexec/cc1.exe';helper.parent.mkdir();helper.write_bytes(b'fixture helper')
            with patch('ecra.portable.bundle_root',return_value=root),patch.dict('ecra.portable._BUILD_ALIASES',{},clear=True):
                tool_environment();alias=Path(tool_path('arm-none-eabi-gcc'))
                self.assertEqual((alias.parent/'../libexec/cc1.exe').resolve(),helper)
                self.assertTrue((alias.parent/'../libexec/cc1.exe').is_file())
                self.assertEqual(alias.resolve(),binary)
    def test_studio_boot_rejects_source_data_root_before_creating_settings(self):
        from ecra.studio.server import create_app
        with tempfile.TemporaryDirectory() as folder:
            firmware=Path(folder)/'firmware';firmware.mkdir()
            (firmware/'CMakeLists.txt').write_text('project(real_firmware C)')
            with self.assertRaisesRegex(ValueError,'工程内'):
                create_app(firmware/'data')
            self.assertFalse((firmware/'data').exists())
    @unittest.skipUnless(os.name=='nt','NTFS build alias')
    def test_ascii_build_alias_reserves_space_for_cmake_trycompile_suffixes(self):
        from ecra.portable import build_path
        with tempfile.TemporaryDirectory(prefix='ecra-short-build-') as folder:
            root=Path(folder).resolve()
            with patch.dict('ecra.portable._BUILD_ALIASES',{},clear=True):
                alias=Path(build_path(root,prefer_junction=True))
                self.assertNotEqual(str(alias),str(root))
                self.assertEqual(alias.resolve(),root)
                self.assertEqual(Path(build_path(root/'child',prefer_junction=True)).resolve(),root/'child')
                # Remove only the newly created junction after verifying its
                # target, never recursively delete the target data.
                if alias.resolve()==root:alias.rmdir()

    def test_existing_tool_identity_migrates_with_all_bytes_and_source_preserved(self):
        from ecra.common import write_json,read_json
        from ecra.workspace import migrate_legacy,file_hash
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);fw=base/'firmware';fw.mkdir();tool=base/'old-install';tool.mkdir()
            with patch('ecra.workspace.TOOL_ROOT',tool), patch.dict(os.environ,{'ECRA_DATA_ROOT':str(base/'user-data')}):
                old=WorkspaceResolver.resolve(fw,dict(output=dict(location='tool'))).initialize()
                source=Path(old.results_root)
                write_json(source/'run.json',dict(project_root=str(fw)))
                write_json(source/'scan_state.json',dict(schema=1,project_root=str(fw),fingerprint='old'))
                write_json(source/'reports/global_static_concurrency.json',dict(findings=[]))
                (source/'facts.db').write_bytes(b'preserve legacy bytes exactly')
                write_json(source/'review/queue.json',[dict(note='人工历史原文')])
                hashes={p.relative_to(source):file_hash(p) for p in source.rglob('*') if p.is_file()}
                new=WorkspaceResolver.resolve(fw,{}).initialize()
                migrate_legacy(new,lambda _:None)
                target=Path(new.results_root)
                self.assertEqual(read_json(target/'migration.json')['source_kind'],'TOOL_WORKSPACE')
                for relative,hashed in hashes.items():
                    self.assertEqual(file_hash(target/relative),hashed)
                    self.assertEqual(file_hash(source/relative),hashed)
                self.assertEqual(list(fw.iterdir()),[])

    def test_user_data_is_stable_and_not_inside_firmware_or_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            fw = base/'固件'; fw.mkdir()
            with patch.dict(os.environ, {'ECRA_DATA_ROOT': str(base/'用户 数据')}):
                ws = formal_workspace(fw, {})
                self.assertEqual(Path(ws.workspace_root), (base/'用户 数据').resolve())
                self.assertFalse((base/'用户 数据').exists(), 'precheck must not write')
                ws.initialize()
                self.assertEqual(list(fw.iterdir()), [])
                self.assertEqual(WorkspaceResolver.resolve(fw, {}).project_id, ws.project_id)

    def test_formal_modes_reject_legacy_writes_and_unsafe_dirty_path(self):
        with tempfile.TemporaryDirectory() as folder:
            fw = Path(folder)
            for cfg in [dict(output=dict(location='project')), dict(output=dict(location='tool')),
                        dict(cmake=dict(location='project')), dict(git_diff=dict(include_uncommitted=True))]:
                with self.assertRaises(ValueError):
                    formal_workspace(fw, cfg)
                self.assertEqual(list(fw.iterdir()), [])

    def test_relative_and_overlapping_data_roots_rejected_before_any_write(self):
        with patch.dict(os.environ, {'ECRA_DATA_ROOT': 'relative'}):
            with self.assertRaises(ValueError):
                user_data_root()
        with tempfile.TemporaryDirectory() as folder:
            fw = Path(folder)
            with patch.dict(os.environ, {'ECRA_DATA_ROOT': str(fw/'data')}):
                with self.assertRaises(ValueError):
                    formal_workspace(fw, {})
                self.assertEqual(list(fw.iterdir()), [])
