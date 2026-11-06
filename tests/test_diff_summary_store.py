import copy
import json
from pathlib import Path
import tempfile
import unittest
import weakref
from unittest.mock import patch

from ecra.common import digest, write_json
from ecra.diff_summary_store import SummaryStore, compare_spooled
from ecra.git_diff import compare, summarize
from tests import test_native_diff_reader as native_fixture


class DiffSummaryStoreTests(unittest.TestCase):
    def setUp(self):
        fixture = native_fixture.NativeDiffReaderTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.base = summarize(fixture.facts, fixture.report)
        self.folder = fixture.home/'compare'; self.folder.mkdir()
        self.path = self.folder/'base.json'; write_json(self.path, self.base, indent=None)
        self.pin = dict(files=[], project_subdir='.', head_sha='head', base_sha='base')

    def equivalent(self, head, pin=None):
        pin = pin or self.pin
        expected = compare(json.loads(self.path.read_text('utf-8')), head, pin)
        actual = compare_spooled(self.path, lambda: head, pin, self.folder)
        self.assertEqual(actual, expected)
        self.assertEqual(digest(actual), digest(expected))
        self.assertEqual(list(self.folder.glob('summary-compare-*')), [])
        return actual

    def test_identical_complete_summaries(self): self.equivalent(copy.deepcopy(self.base))

    def test_all_dimensions_and_findings_preserve_complete_impacts(self):
        for dimension in ('declaration','accesses','graph','contexts','protection','coverage','conflicts','classification'):
            with self.subTest(dimension=dimension):
                head = copy.deepcopy(self.base); value = head['variables']['state']['dimensions']
                value[dimension] = ['changed','changed'] if isinstance(value[dimension], list) else 'changed'
                if dimension == 'graph':
                    old = head['variables']['state']['graph_id']; graph = head['graphs'].pop(old)
                    graph['edges'].append(['outside','Task']); graph['functions'].append('outside')
                    new = digest(graph); head['graphs'][new] = graph
                    head['variables']['state']['graph_id'] = value['graph'] = new
                self.equivalent(head)
        head = copy.deepcopy(self.base); head['variables']['state']['findings'].append('changed')
        self.equivalent(head)

    def test_modified_functions_and_consumed_returns(self):
        head = copy.deepcopy(self.base); head['functions']['Task']['digest'] = 'different'
        head['functions']['Task']['return_type_kind'] = 'INT'
        self.equivalent(head)

    def test_added_deleted_shape_and_private_fallback(self):
        head = copy.deepcopy(self.base); del head['variables']['state']; self.equivalent(head)
        head = copy.deepcopy(self.base); head['variables']['other'] = copy.deepcopy(head['variables']['state'])
        head['variables']['other'].update(symbol_id='other', name='other', root='other'); self.equivalent(head)
        head = copy.deepcopy(self.base); head['variables']['state']['container'] = True; self.equivalent(head)
        head = copy.deepcopy(self.base); head['semantics']['contexts'].append('global-change')
        result = self.equivalent(head); self.assertIn('state', result['fallback_exemptions'])

    def test_build_and_legacy_return_edges_and_order_sensitive_evidence(self):
        head = copy.deepcopy(self.base); del head['return_edges']
        head['build'].append('new'); head['semantics']['contexts'].reverse()
        self.equivalent(head, dict(self.pin, files=[dict(new_path='CMakeLists.txt',status='M')]))

    def test_nested_scalar_types_lists_and_map_key_types(self):
        value = dict(variables={'中文': dict(values=[True,1,-0.0,None,[2,1,2]])}, unknowns=[1,True,1],
                     semantics={'ordered':[dict(steps=[2,1,2])]}, schema=7)
        path = self.folder/'types.json'; write_json(path, value, indent=None)
        with SummaryStore(self.folder/'types.db') as store:
            root = store.from_json(path)
            self.assertEqual(root['variables']['中文'], value['variables']['中文'])
            self.assertEqual(list(root['unknowns']), value['unknowns'])
            self.assertEqual(root['semantics'], value['semantics'])
            for key in [1, True, 1.0, None]:
                with self.assertRaises(KeyError): root['variables'][key]
            with self.assertRaises(TypeError): root['variables'][[]]

    def test_head_top_level_is_released_before_baseline_import(self):
        class Head(dict): pass
        references = []
        def factory():
            value = Head(copy.deepcopy(self.base)); references.append(weakref.ref(value)); return value
        original = SummaryStore.from_json
        def guarded(store, path):
            self.assertIsNone(references[0](), 'Current summary must be released before reading baseline')
            return original(store, path)
        # No caller reference survives the argument expression in the real CLI.
        with patch.object(SummaryStore, 'from_json', new=guarded):
            compare_spooled(self.path, factory, self.pin, self.folder)

    def test_malformed_and_repeated_json_do_not_publish_and_keep_diagnostics(self):
        for text in ['{"variables":{},"variables":{}}', '{"functions":', '{} trailing']:
            with self.subTest(text=text):
                self.path.write_text(text,'utf-8')
                with self.assertRaises(Exception):compare_spooled(self.path, lambda: copy.deepcopy(self.base), self.pin, self.folder)
        self.assertEqual(len(list(self.folder.glob('summary-compare-*/failure.json'))),3)

    def test_pinned_digest_change_blocks_comparison(self):
        with self.assertRaisesRegex(ValueError,'基准摘要'):
            compare_spooled(self.path, lambda: copy.deepcopy(self.base), dict(self.pin,base_summary_sha256='bad'), self.folder)
        self.assertTrue(list(self.folder.glob('summary-compare-*/failure.json')))

    def test_current_non_string_keys_are_not_coerced(self):
        head = copy.deepcopy(self.base); head['variables'][1] = head['variables'].pop('state')
        with self.assertRaisesRegex(ValueError,'字符串'):compare_spooled(self.path, lambda: head, self.pin, self.folder)

    def test_verification_preserves_full_mismatch_diagnostics(self):
        from ecra.diff_summary_store import verify_spooled
        head = copy.deepcopy(self.base)
        diagnostic = self.folder/'diagnostic.json'
        result = verify_spooled(self.path, lambda: head, self.folder, diagnostic, 1)
        self.assertEqual(result['state'], 'PASSED'); self.assertFalse(diagnostic.exists())
        head['variables']['state']['dimensions']['declaration'] = 'different'
        with self.assertRaisesRegex(ValueError, '语义事实不一致'):
            verify_spooled(self.path, lambda: head, self.folder, diagnostic, 1)
        value = json.loads(diagnostic.read_text('utf-8'))
        self.assertEqual(value['expected'], json.loads(self.path.read_text('utf-8')))
        self.assertEqual(value['actual'], json.loads(json.dumps(head)))
