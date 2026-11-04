"""Receipt-only fields equal old full JSON parsing; discarded JSON is checked."""
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from ecra.review_contract import stale_writeback_hints,validate_nvic_missing_facts,NVICFactConflictError
from ecra.review_language import technical_identifiers
from ecra.review_packet import ReceiptReader,validation_packet


class ReceiptPacketProjectionTests(unittest.TestCase):
    def test_boundary_chunks_preserve_every_field_used_by_contract_and_language_checks(self):
        original=dict(variable=dict(name='shared',qualified_name='device.shared',canonical_path='device.shared'),
            functions=[dict(name='Worker',body='中😀"\\\n'*1200),dict(name='Worker',body='other')],
            concurrency_hints=[dict(kind='READ_THEN_WRITEBACK',nested=[False,2**100,-0.0])],
            nvic_priorities=[dict(source_configurations=[{'proof':'retained'}],configured_preemption=3,irqn=['IRQ1'],vectors=['IRQ1_Handler'])],
            other=[dict(payload='ignored\\\"汉',number=1e120),None,True])
        text=json.dumps(original,ensure_ascii=True,indent=1)
        for chunk in (1,2,3,7,64,65536):
            with self.subTest(chunk=chunk):
                reader=ReceiptReader(io.StringIO(text),chunk_size=chunk);actual=reader.packet(True)
                self.assertEqual(actual['concurrency_hints'],original['concurrency_hints'])
                self.assertEqual(actual['nvic_priorities'],original['nvic_priorities'])
                self.assertEqual(stale_writeback_hints(actual),stale_writeback_hints(original))
                self.assertEqual(technical_identifiers(actual),technical_identifiers(original))
                for packet in (original,actual):
                    with self.assertRaises(NVICFactConflictError):validate_nvic_missing_facts(dict(missing_context=['IRQ1优先级未知']),packet)

    def test_discarded_large_strings_never_enter_value_decoder_or_large_buffer(self):
        text='{"large":"'+'汉'*200000+'\\uD800\\nend","functions":[{"name":"A","body":'+json.dumps('x'*100000)+'}],"nvic_priorities":[]}'
        reader=ReceiptReader(io.StringIO(text),chunk_size=1024);original=reader.value;peaks=[]
        def guarded():
            peaks.append(len(reader.buffer));self.assertLessEqual(len(reader.buffer),2048)
            return original()
        reader.value=guarded;actual=reader.packet(True)
        self.assertEqual(actual['functions'],[dict(name='A')]);self.assertTrue(peaks)

    def test_invalid_unused_json_is_not_hidden_by_projection(self):
        invalid=['{"unused":[1,]}','{"unused":{"x":}}','{"unused":"bad\\q"}',
            '{"unused":"raw\ncontrol"}','{"unused":01}','{"unused":1.}','{"unused":1e+}',
            '{"unused":truefalse}','{"unused":"bad\\u0xx0"}','{"unused":[]} trailing','{"unused":- true}']
        for raw in invalid:
            for chunk in (1,7,65536):
                with self.subTest(raw=raw,chunk=chunk),self.assertRaises((ValueError,TypeError)):
                    ReceiptReader(io.StringIO(raw),chunk_size=chunk).packet(False)

    def test_literals_empty_containers_duplicates_unicode_and_old_shared_codec(self):
        rng=random.Random(431);values=[None,True,False,0,-0.0,-15,2**160,1e-20,'中😀"\\\t',[],{},float('nan'),float('inf'),float('-inf')]
        for unused in range(50):
            value=[rng.choice(values) for i in range(8)];text=json.dumps(dict(ignored=value,concurrency_hints=[]),ensure_ascii=False)
            self.assertEqual(ReceiptReader(io.StringIO(text),chunk_size=3).packet(False),dict(concurrency_hints=[]))
        raw='{"functions":[{"name":"old"}],"functions":[{"name":"new"}],"concurrency_hints":[1],"concurrency_hints":[]}'
        actual=ReceiptReader(io.StringIO(raw),chunk_size=2).packet(True)
        self.assertEqual(actual,dict(functions=[dict(name='new')],concurrency_hints=[]))
        with tempfile.TemporaryDirectory() as folder:
            from ecra.shared_json import write
            path=Path(folder)/'old.input.json';record=dict(name='Legacy',body='x'*1000)
            write(path,dict(concurrency_hints=[],functions=[record]*8),threshold=1)
            from ecra.shared_json import encoded_stream
            with path.open(encoding='utf-8') as stream:self.assertTrue(encoded_stream(stream))
            self.assertEqual(technical_identifiers(validation_packet(path,identifiers=True)),{'Legacy'})
