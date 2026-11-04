"""Explicit archived inputs must win over mutable project latest pointers."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ecra import multicore
from ecra.common import write_json
from ecra.config import load_config
from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.workspace import WorkspaceResolver
from tests import test_multicore_publication as fixtures


class PinnedMulticoreInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.MulticorePublicationTests.setUpClass.__func__(cls)

    def setUp(self):
        fixtures.MulticorePublicationTests.setUp(self)
        self.selected = {}; self.profiles = {}; self.selected_folders = []
        for variant, config in self.inputs:
            raw = json.loads(config.read_text('utf-8'))
            raw['analysis']['output'] = dict(location='custom', custom_dir=str(self.data))
            write_json(config, raw)
            cfg, _ = load_config(self.root, config)
            ws = WorkspaceResolver.resolve(self.root, cfg['analysis']).initialize()
            profile = 'profile-'+variant; ident = 'selected-'+variant
            folder = self.data/'scans'/ident; folder.mkdir(parents=True)
            facts = copy.deepcopy(self.facts)
            facts['translation_units'][0]['selection_marker'] = variant
            publish_scan(folder/'scan.db', facts, dict(findings=[]), scan_id=ident,
                         project_id=ws.project_id, profile_id=profile,
                         provenance=dict(display_identity=dict(config_sha256=sha256(config),
                                                               project_core=cfg['project']['core'])))
            provider = EvidenceProvider(folder/'scan.db'); binding = provider.validate(deep=True)
            ReviewStore(folder/'reviews.db', binding)
            write_json(folder/'manifest.json', dict(binding, format='ECRA_LOCAL_SCAN', version=1,
                       scan_sha256=sha256(folder/'scan.db')))
            self.selected[variant] = ident; self.profiles[variant] = profile
            self.selected_folders.append(folder)
        # Both configs have the same project-level pointer. Its CM4 value is
        # deliberately wrong for CM7. GUI selections remain explicit.
        self.pointer = Path(ws.project_workspace)/'latest-scan.json'
        write_json(self.pointer, dict(project_id=ws.project_id, scan_id='selected-CM4'))

    def combine(self, name='pinned', **kwargs):
        out = self.data/'scans'/name
        return out, multicore.combine(self.root, self.inputs, self.regions, out,
            scan_ids=kwargs.pop('scan_ids', self.selected),
            profile_ids=kwargs.pop('profile_ids', self.profiles), **kwargs)

    def inputs_before(self):
        return {str(p):sha256(p) for root in [self.root, *self.selected_folders]
                for p in root.rglob('*') if p.is_file()} | {
                    str(p):sha256(p) for _, p in self.inputs} | {str(self.pointer):sha256(self.pointer)}

    def test_two_selected_scans_are_not_replaced_by_the_same_wrong_latest(self):
        before = self.inputs_before()
        out, (facts, report) = self.combine()
        self.assertEqual([row['selection_marker'] for row in facts['translation_units']], ['CM7', 'CM4'])
        self.assertEqual(report['run_status'], 'INCOMPLETE')
        provider = EvidenceProvider(out/'scan.db')
        components = provider.load('provenance')['components']
        self.assertEqual([row['binding']['scan_id'] for row in components], ['selected-CM7','selected-CM4'])
        self.assertTrue(all(row['selection_mode']=='EXPLICIT_SCAN' for row in components))
        self.assertEqual(self.inputs_before(), before)
        self.assertEqual(provider.load('facts'), facts)

    def test_implicit_same_project_latest_is_rejected_without_publishing(self):
        out = self.data/'scans'/'implicit-wrong'
        with self.assertRaisesRegex(ValueError, '同一latest'):
            multicore.combine(self.root, self.inputs, self.regions, out)
        self.assertFalse(out.exists())

    def test_missing_extra_traversal_and_non_string_selection_cannot_fall_back(self):
        for value in [{}, {'CM7':'selected-CM7'}, dict(self.selected, OTHER='selected-CM4'),
                      dict(self.selected, CM7='../selected-CM7'), dict(self.selected, CM7=True), []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.combine(scan_ids=value)
        self.assertFalse((self.data/'scans'/'pinned').exists())
        with self.assertRaisesRegex(ValueError, 'profile'):
            self.combine(profile_ids={'CM7':'profile-CM7'})

    def test_wrong_profile_and_archived_configuration_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'profile'):
            self.combine(profile_ids=dict(self.profiles, CM7='profile-CM4'))
        self.inputs[0][1].write_text(self.inputs[0][1].read_text('utf-8')+'\n', 'utf-8')
        with self.assertRaisesRegex(ValueError, '配置字节不符'):
            self.combine()
        self.assertFalse((self.data/'scans'/'pinned').exists())

    def test_wrong_project_manifest_or_missing_publication_is_rejected(self):
        first = self.selected_folders[0]; manifest = first/'manifest.json'
        original = manifest.read_bytes(); value = json.loads(original)
        for changes in [dict(project_id='another-project'), dict(scan_sha256='0'*64)]:
            write_json(manifest, dict(value, **changes))
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, '清单'):
                self.combine()
        manifest.write_bytes(original); manifest.rename(first/'manifest.not-published')
        with self.assertRaisesRegex(ValueError, '已发布扫描'):
            self.combine()
        self.assertFalse((self.data/'scans'/'pinned').exists())

    def test_selected_manifest_change_after_assembly_does_not_publish(self):
        assemble = multicore._assemble
        def changed(*args, **kwargs):
            value = assemble(*args, **kwargs)
            manifest = self.selected_folders[0]/'manifest.json'
            manifest.write_bytes(manifest.read_bytes()+b'\n')
            return value
        with patch.object(multicore, '_assemble', side_effect=changed), self.assertRaisesRegex(ValueError, '输入在合并期间改变'):
            self.combine()
        self.assertFalse((self.data/'scans'/'pinned').exists())

    def test_real_cli_pins_both_scans_and_rejects_duplicate_variant_flags(self):
        command = [sys.executable, '-B', '-X', 'utf8', '-m', 'ecra.multicore',
                   '--project', str(self.root), '--data-root', str(self.data),
                   '--shared-region', '0x38000000:0x10000']
        for variant, config in self.inputs:
            command.extend(['--input', variant+'='+str(config), '--scan', variant+'='+self.selected[variant],
                            '--profile-id', variant+'='+self.profiles[variant]])
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads(result.stdout)
        self.assertTrue((Path(saved['scan_path'])/'manifest.json').is_file())
        duplicate = subprocess.run([*command, '--scan', 'CM7=selected-CM4'],
            capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn('不能为空或重复', duplicate.stderr)


if __name__ == '__main__':
    unittest.main()
