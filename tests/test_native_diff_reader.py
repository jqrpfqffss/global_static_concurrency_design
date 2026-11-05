"""Full original-summary oracles for native cold baseline reading."""
import copy
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra.block_bitmap import BLOCK_BITS
from ecra.common import digest
from ecra.git_diff import summarize
from ecra.native_diff_summary import summarize_native, _Inputs
from ecra.scan_store import EvidenceProvider, publish_scan


class NativeDiffReaderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='ECRA cold Diff 中文 ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        access = dict(function_id='Task', access_kind='RMW', parse_confidence='exact',
                      call_chains=[['main', 'Task']], extra=dict(ordered=[2, 1, 2], boolean=True, integer=1))
        variable = dict(symbol_id='state', name='state', kind='FILE_STATIC', storage_class='STATIC',
                        static_classification='SAFE_PROVEN', analysis_coverage='COMPLETE', type='int',
                        accesses=[access, copy.deepcopy(access)], contexts=['task'], blocking_evidence=[],
                        safe_evidence=[dict(proof=[3, 2, 3])], screening_blockers=[],
                        conflict_pairs=[dict(participants=['a', 'b'], custom=-0.0)],
                        protection_details=[dict(states=[dict(irq_state='ENABLED', faultmask=0, basepri=0)])],
                        concurrency_relations=[dict(relation='same', trace=['second', 'first'])],
                        member_definitions=[dict(type='int', order=[1, 0])], initializer=[2, 1],
                        definition_file='main.c', definition_line=7, size_bytes=4)
        self.facts = dict(variables=[variable], functions=[dict(function_id=n, name=n,
            semantic_digest=n, consumed_macros_digest='macros', return_type_kind='VOID',
            file='main.c', line=3, translation_unit='main.c', unused_large_body=[dict(ast='unread')])
            for n in ['main', 'Task']], calls=[dict(caller_function_id='main', callee_function_id='Task',
                result_used=True, unused_arguments=[1, 2])],
            contexts=[dict(id='task', kind='TASK')],
            context_bindings=[dict(function_id='Task', context_id='task', ordered=[2, 1])]*2,
            context_call_graph=dict(roots=dict(task=['main']), edges=dict(task=[['main', 'Task']]*2)),
            nvic_priorities=[dict(context_ids=['task'], irq_number=1, enabled=True, logical_priority=2)],
            translation_units=[dict(source_file='main.c', parse_status='PARSED', semantic_macros_digest='m',
                includes=[str(self.home/'header.h')], original_arguments=['cc', '-I'+str(self.home), '-DM=2'])],
            unknowns=[dict(kind='unknown', sequence=[2, 1], value=10**80)]*2,
            pointer_targets=[dict(source_id='slot', targets=['obj:b', 'obj:a', 'obj:a'], trace=[2, 1])])
        for key in ('irq_priority_events', 'nvic_resolved_events', 'protection_events', 'registrations',
                    'hardware_contexts', 'preemption_relations', 'address_escapes'):
            self.facts[key] = [dict(kind=key, ordered=[True, 1, -0.0, None, '中文'])]*2
        self.report = dict(analysis_status='COMPLETE', coverage=dict(project_root=str(self.home)),
            findings=[dict(finding_id='f1', symbol_id='state', static_classification='SAFE_PROVEN',
                rules=[dict(rule='r', trace=[2, 1])]*2, conflict_pairs=variable['conflict_pairs'],
                uncertainties=[dict(kind='u', ordered=[False, 0])], unused_large_slice=dict(body=[1, 2]))])
        self.number = 0

    def publish(self):
        self.number += 1
        path = self.home/(str(self.number)+'.db')
        publish_scan(path, self.facts, self.report, scan_id=str(self.number), project_id='p')
        return path

    def equivalent(self, renames=None):
        path = self.publish()
        provider = EvidenceProvider(path)
        expected = summarize(provider.load('facts'), provider.load('report'), renames)
        with patch.object(EvidenceProvider, 'load', side_effect=AssertionError('whole-root load forbidden')):
            actual = summarize_native(path, renames)
        self.assertEqual(actual, expected)
        # Re-serialization after the connection closes must contain no proxies.
        self.assertEqual(digest(actual), digest(expected))
        return actual

    def test_complete_fields_duplicates_and_nested_order(self):
        first = self.equivalent()
        self.assertTrue(first['variables']['state']['private_storage_isolation'])
        self.assertEqual(len(first['semantics']['registrations']), 2)
        self.facts['variables'][0]['accesses'][0]['extra']['ordered'] = [1, 2, 2]
        second = self.equivalent()
        self.assertNotEqual(first['variables']['state']['dimensions']['accesses'],
                            second['variables']['state']['dimensions']['accesses'])

    def test_inherited_access_blocks_private_isolation_despite_positional_normalization(self):
        self.facts['variables'][0]['accesses'][0]['inherited_from_access_id'] = 'prior-access'
        result = self.equivalent()
        self.assertFalse(result['variables']['state']['private_storage_isolation'])

    def test_pool_encodings_match_inline_with_repeated_references(self):
        self.facts['pointer_targets'] *= 2
        expected = self.equivalent()
        for encoding in ['3', [[0, '3']]]:
            with self.subTest(encoding=encoding):
                self.facts['pointer_target_atoms'] = ['obj:b', 'obj:a']
                self.facts['pointer_target_sets'] = {'pool': encoding}
                self.facts['pointer_target_block_bits'] = BLOCK_BITS
                self.facts['pointer_targets'] = [dict(source_id='slot', target_set_id='pool',
                    target_count=2, trace=[2, 1])]*2
                self.assertEqual(self.equivalent(), expected)

    def test_build_root_cfg_and_rename_use_original_canonicalization(self):
        build = self.home/'build'; source = (build/'gen.c').as_posix()
        function_id = 'tu::'+source+'::c:gen.c@F@Task'
        self.facts['functions'][1].update(function_id=function_id, translation_unit=source, file=source)
        self.facts['calls'][0]['callee_function_id'] = function_id
        self.facts['variables'][0]['accesses'] = [dict(function_id=function_id, access_kind='WRITE',
            cfg_node_id='CFG-'+digest([source, function_id])[:20], type='(anonymous struct at x.c:12:3)')]
        self.facts['translation_units'][0].update(source_file=source, ecra_build_root=str(build),
            original_arguments=['cc', '-I'+str(build), '-DM=2'])
        self.equivalent({'main.c': 'renamed.c'})

    def test_empty_optional_relations_and_missing_required_function_identity(self):
        self.facts = dict(variables=[], functions=[], calls=[],
            translation_units=[dict(source_file='main.c', parse_status='PARSED')])
        self.report = dict(findings=[], analysis_status='COMPLETE')
        self.equivalent()
        self.facts['functions'] = [dict(name='broken')]
        path = self.publish()
        for callback in (lambda: summarize(self.facts, self.report), lambda: summarize_native(path)):
            with self.assertRaises(KeyError): callback()

    def test_partial_empty_and_malformed_authorities_do_not_complete(self):
        for units in ([], [dict(source_file='main.c', parse_status='PARTIAL')]):
            with self.subTest(units=units):
                self.facts['translation_units'] = units
                with self.assertRaisesRegex(ValueError, '部分解析'): summarize_native(self.publish())
        self.facts['translation_units'] = [dict(source_file='main.c', parse_status='PARSED')]
        self.facts['functions'] = [None]
        with self.assertRaisesRegex(ValueError, '非对象'): summarize_native(self.publish())

    def test_invalid_pool_references_fail_in_both_readers(self):
        self.facts.update(pointer_target_atoms=['obj:a'], pointer_target_sets={'p': [[0, '2']]},
                          pointer_target_block_bits=BLOCK_BITS)
        self.facts['pointer_targets'] = [dict(source_id='slot', target_set_id='p')]
        path = self.publish()
        for callback in (lambda: summarize(self.facts, self.report), lambda: summarize_native(path)):
            with self.assertRaisesRegex(ValueError, 'missing atom'): callback()

    def test_pool_keys_preserve_python_types_instead_of_sqlite_text_affinity(self):
        self.facts.update(pointer_target_atoms=['obj:a'], pointer_target_sets={'1': '1'})
        for reference in (1, True, 1.0, None, [], {}):
            with self.subTest(reference=reference):
                self.facts['pointer_targets'] = [dict(source_id='slot', target_set_id=reference)]
                path = self.publish()
                expected_error = TypeError if isinstance(reference, (list, dict)) else KeyError
                for callback in (lambda: summarize(self.facts, self.report), lambda: summarize_native(path)):
                    with self.assertRaises(expected_error): callback()

    def test_unread_bodies_and_report_slices_are_never_decoded(self):
        path = self.publish(); provider = EvidenceProvider(path)
        forbidden = {provider.resolve('facts', ['functions', 0, 'unused_large_body']),
                     provider.resolve('report', ['findings', 0, 'unused_large_slice'])}
        original = _Inputs.value
        def guarded(reader, node):
            self.assertNotIn(node, forbidden)
            return original(reader, node)
        with patch.object(_Inputs, 'value', new=guarded):
            self.assertEqual(summarize_native(path), summarize(self.facts, self.report))
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
