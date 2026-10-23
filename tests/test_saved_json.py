import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_ecra
from ecra.cli import run
from ecra.common import digest
from ecra.workflow import clean_report, read_saved_json, saved_report_digest, status


class SavedJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'saved.json'

    def test_empty_arrays_and_all_nested_json_types_are_preserved(self):
        value = dict(empty=[], empty_object={}, arrays=[[], [True, 1, False, 0, 1.0, None]],
                     text='中文 <&> 😀', variables=[dict(paths=[[True], [1], [1.0], ['field']])],
                     number=-0.0, exponent=1.25e100)
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        actual = read_saved_json(self.path)
        self.assertEqual(json.dumps(actual), json.dumps(value))

    def test_unicode_bom_and_array_duplicates_remain_complete(self):
        value = dict(variables=[dict(symbol_id='中文')]*3, findings=[])
        self.path.write_bytes(b'\xef\xbb\xbf'+json.dumps(value, ensure_ascii=False).encode('utf-8'))
        self.assertEqual(read_saved_json(self.path), value)

    def test_loader_never_requests_an_all_file_read(self):
        value = dict(variables=[dict(symbol_id='shared-'+str(i), evidence='read'*100) for i in range(1000)])
        class Bounded(io.StringIO):
            def read(self, size=-1):
                if size < 0:
                    raise AssertionError('unbounded file read')
                return super().read(size)
        with patch.object(Path, 'open', return_value=Bounded(json.dumps(value))):
            self.assertEqual(read_saved_json(self.path), value)

    def test_only_equal_strings_are_shared(self):
        text = 'repeated symbol identity '+str(123456789)
        self.path.write_text(json.dumps(dict(variables=[dict(name=text), dict(name=text)])))
        actual = read_saved_json(self.path)
        self.assertIs(actual['variables'][0]['name'], actual['variables'][1]['name'])
        self.assertIsNot(actual['variables'][0], actual['variables'][1])

    def test_invalid_truncated_duplicate_or_non_object_input_fails(self):
        for text in ('[]', '{"a":1,"a":2}', '{"a":[1,]}', '{"a":[1', '{}true'):
            with self.subTest(text=text):
                self.path.write_text(text)
                with self.assertRaises(ValueError):
                    read_saved_json(self.path)

    def test_canonical_accesses_restore_shared_entities_without_losing_entries(self):
        access = dict(access_id='A', symbol_id='g', function_id='f', access_kind='READ', file='a.c', offset=1)
        value = dict(variables=[dict(symbol_id='g', accesses=[access, access])], accesses=[access])
        self.path.write_text(json.dumps(value))
        actual = read_saved_json(self.path, canonical_accesses=True)
        self.assertEqual(json.dumps(actual), json.dumps(value))
        self.assertEqual(len(actual['variables'][0]['accesses']), 2)
        self.assertIs(actual['variables'][0]['accesses'][0], actual['accesses'][0])

    def test_access_canonicalization_never_merges_types_values_key_order_or_variants(self):
        base = dict(access_id='A', symbol_id='g', function_id='f', access_kind='READ', file='a.c', offset=1)
        rows = [dict(base, extra=True), dict(base, extra=1), dict(base, extra=-0.0), dict(base, extra=0.0),
                dict(base, access_kind='WRITE'), dict(base, symbol_id='other'),
                dict(reversed(list(base.items())))]
        self.path.write_text(json.dumps(dict(accesses=rows)))
        actual = read_saved_json(self.path, canonical_accesses=True)
        self.assertEqual(json.dumps(actual), json.dumps(dict(accesses=rows)))
        self.assertEqual(len({id(row) for row in actual['accesses']}), len(rows))

    def test_streaming_digest_is_identical_to_existing_checkpoint_digest(self):
        for value in ({}, dict(中文='证据😀', values=[True, 1, -0.0, None, 1e100]),
                      dict(findings=[dict(id=str(i), evidence=['a', 'b']) for i in range(1000)])):
            with self.subTest(value_type=type(value).__name__):
                self.assertEqual(saved_report_digest(value), digest(value))

    def test_report_cleaning_preserves_values_and_does_not_mutate_original(self):
        original = dict(coverage=dict(total=1), run_status='DONE', risk_summary=dict(variables=[]),
            findings=[dict(finding_id='x', status='SAFE', review=dict(status='SAFE'),
                           review_state='DONE', effective_decision='SAFE', accesses=[dict(id='A')])])
        before = copy.deepcopy(original)
        expected = copy.deepcopy(original)
        expected.pop('run_status'); expected.pop('risk_summary')
        for key in ('review', 'review_state', 'effective_decision'):
            expected['findings'][0].pop(key)
        expected['findings'][0]['status'] = 'NEED_OPENCODE_REVIEW'
        actual = clean_report(original)
        self.assertEqual(actual, expected)
        self.assertEqual(original, before)
        self.assertIsNot(actual['findings'][0], original['findings'][0])
        self.assertIs(actual['findings'][0]['accesses'], original['findings'][0]['accesses'])


class SavedStatusTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def test_disabled_review_without_packets_publishes_once_and_keeps_the_actual_queue(self):
        from ecra.common import read_json, write_json
        from ecra.report import generate
        from ecra.workflow import save_scan
        self.project({'a.c': 'int shared;void ISR(void){shared++;}void Task(void){shared++;}'})
        config = self.root/'.ecra/semantics.yaml'
        cfg = read_json(config)
        cfg['review'].update(enabled=False, prepare_packets=False)
        write_json(config, cfg)
        with patch('ecra.cli.generate', wraps=generate) as rendered, \
                patch('ecra.workflow.save_scan', wraps=save_scan) as saved, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        self.assertEqual(rendered.call_count, 1)
        self.assertEqual(saved.call_count, 1)
        self.assertFalse(saved.call_args.kwargs['initialize_queue'])
        queue = read_json(self.root/'.ecra/review/queue.json')
        self.assertTrue(queue)
        self.assertTrue(all('已关闭' in row['error'] for row in queue))
        self.assertTrue(status(self.root)['resumable'])

    def test_packet_preparation_retains_early_publication_and_all_static_facts(self):
        from ecra.common import read_json, write_json
        from ecra.report import generate
        self.project({'a.c': 'int shared;void ISR(void){shared++;}void Task(void){shared++;}'})
        config = self.root/'.ecra/semantics.yaml'
        cfg = read_json(config)
        cfg['review'].update(enabled=False, prepare_packets=False)
        write_json(config, cfg)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        first = read_json(self.root/'.ecra/facts.json')
        cfg['review']['prepare_packets'] = True
        write_json(config, cfg)
        with patch('ecra.cli.generate', wraps=generate) as rendered, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        self.assertEqual(rendered.call_count, 2)
        second = read_json(self.root/'.ecra/facts.json')
        self.assertEqual(first, second)
        self.assertTrue(status(self.root)['resumable'])

    def test_status_validates_saved_fact_hash_without_deserializing_all_facts(self):
        self.project({'a.c': 'int shared;void ISR(void){shared++;}void Task(void){shared++;}'})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        loaded = []
        def observe(path):
            loaded.append(Path(path).name)
            if Path(path).name == 'facts.json':
                raise AssertionError('status must not deserialize facts')
            return read_saved_json(path)
        with patch('ecra.workflow.read_saved_json', side_effect=observe):
            result = status(self.root)
        self.assertTrue(result['resumable'])
        self.assertIn('global_static_concurrency.json', loaded)
        facts = self.root/'.ecra/facts.json'
        facts.write_text('{}')
        result = status(self.root)
        self.assertFalse(result['resumable'])


if __name__ == '__main__':
    unittest.main()
