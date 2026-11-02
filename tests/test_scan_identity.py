import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.scan_identity import capture, query
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report, import_report, sha256


class ScanIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra archived identity ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def provider(self, *, provenance=None, report=None):
        folder=self.base/'scans/frozen-scan';folder.mkdir(parents=True)
        publish_scan(folder/'scan.db',dict(variables=[]),report or dict(findings=[]),
                     scan_id='frozen-scan',project_id='project',profile_id='m7',provenance=provenance or {})
        result=EvidenceProvider(folder/'scan.db');ReviewStore(folder/'reviews.db',result.metadata())
        return result

    def test_captured_crlf_config_hash_and_actual_cache_variant_survive_full_package(self):
        raw='# 原注释\r\nproject: {name: "真实控制器"}\r\nanalysis: {cmake: {target: flight, build_type: Debug}}\r\n'.encode()
        identity=capture(raw,'../config/semantics.yaml',dict(cmake_cache={'CMAKE_BUILD_TYPE':'Release'}))
        self.assertEqual(identity['config_sha256'],hashlib.sha256(raw).hexdigest())
        provider=self.provider(provenance=dict(display_identity=identity),report=dict(findings=[],workspace=dict(project_root='I:/固件/H747')))
        before=sha256(provider.path)
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('No full evidence reconstruction')):
            actual=query(provider)
        self.assertEqual(actual['project_name'],'真实控制器');self.assertEqual(actual['configured_target'],'flight')
        self.assertEqual(actual['build_variant'],'Release')
        package=self.base/'result.ecra-report';export_report(provider.path.parent,package)
        destination=self.base/'other-device';result=import_report(package,destination)
        self.assertEqual(query(EvidenceProvider(destination/'scans'/result['scan_id']/'scan.db')),actual)
        self.assertEqual(sha256(provider.path),before)

    def test_old_windows_root_is_named_without_inventing_target_variant_or_core(self):
        provider=self.provider(provenance=dict(project_root='X:\\Firmware\\控制器 M7'),report=dict(findings=[],git_commit='unknown'))
        actual=query(provider)
        self.assertEqual(actual['project_name'],'控制器 M7')
        self.assertIn('目录名',actual['project_name_source'])
        self.assertIsNone(actual['configured_target']);self.assertIsNone(actual['build_variant'])
        self.assertIsNone(actual['config_file']);self.assertIsNone(actual['diff'])

    def test_old_archive_uses_observed_cache_and_keeps_pinned_diff_direction(self):
        pin=dict(base_ref='release',current_ref='feature',base_sha='a'*40,head_sha='b'*40,include_uncommitted=False)
        report=dict(findings=[],workspace=dict(project_root='/firmware/真实根'),
                    coverage=dict(cmake_cache={'CMAKE_BUILD_TYPE':'Debug'}),git_diff=dict(pin=pin),analysis_status='INCOMPLETE')
        actual=query(self.provider(report=report))
        self.assertEqual(actual['project_name'],'真实根');self.assertEqual(actual['diff'],pin)
        self.assertEqual(actual['build_variant'],'Debug');self.assertEqual(actual['analysis_status'],'INCOMPLETE')

    def test_missing_provenance_stays_unknown_not_a_safety_or_hardware_claim(self):
        actual=query(self.provider())
        self.assertIsNone(actual['project_name']);self.assertIsNone(actual['analysis_status'])
        self.assertIn('不表示',actual['note'])

    def test_large_scalars_are_segmented_not_loaded_or_silently_truncated(self):
        provider=self.provider(provenance=dict(display_identity=dict(project_name='长名称'*10000)))
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('unbounded load')),patch.object(EvidenceProvider,'text',side_effect=AssertionError('full text read')):
            actual=query(provider)
        self.assertIsNone(actual['project_name'])
        self.assertIn('provenance/display_identity/project_name',actual['oversized_fields'])

    def test_large_config_does_not_enter_yaml_loader_and_records_explicit_limit(self):
        raw=b'#'+b'x'*(256*1024)
        with patch('yaml.safe_load',side_effect=AssertionError('large config parsed')):
            actual=capture(raw,'../semantics.yaml',{})
        self.assertIn('上限',actual['note']);self.assertNotIn('project_name',actual)
        self.assertEqual(actual['config_sha256'],hashlib.sha256(raw).hexdigest())

    def test_display_text_and_path_are_returned_without_reading_live_files(self):
        sentinel=self.base/'original-firmware';sentinel.mkdir();(sentinel/'secret.txt').write_text('do not read')
        actual=query(self.provider(provenance=dict(display_identity=dict(project_name='<script>window.injected=true</script>'),project_root=str(sentinel))))
        self.assertEqual(actual['project_name'],'<script>window.injected=true</script>')
        self.assertIsNone(actual['compile_database'])

    def test_malformed_optional_config_shapes_do_not_create_synthetic_identity(self):
        actual=capture(b'project: []\nanalysis: {cmake: false}\n','config.yaml',dict(cmake_cache=False))
        self.assertIsNone(actual['project_name']);self.assertIsNone(actual['configured_target']);self.assertIsNone(actual['build_variant'])
