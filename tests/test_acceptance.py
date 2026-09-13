import importlib.util
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('stm32_acceptance',Path(__file__).resolve().parents[1]/'validation/stm32_concurrency/verify_acceptance.py')
acceptance=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class EvidenceTests(unittest.TestCase):
    def test_warning_address_and_configured_chain_cannot_substitute_write(self):
        expected=dict(context='task',functions=['Task','store'],modes=['WRITE'])
        facts=dict(functions=[dict(function_id='a',name='Task'),dict(function_id='b',name='store')],
            calls=[dict(caller_function_id='a',callee_function_id='b',call_kind='CONFIGURED')],
            context_bindings=[dict(function_id='a',context_id='task',call_depth=0)])
        access=dict(access_kind='ADDRESS_TAKEN',contexts=['task'],function_id='b',access_id='x',file='a.c',line=2)
        var=dict(accesses=[access])
        self.assertIsNone(acceptance.chain_matches(expected,var,facts))
        access['access_kind']='WRITE'
        self.assertIsNone(acceptance.chain_matches(expected,var,facts))
        facts['calls'][0]['call_kind']='INDIRECT_RESOLVED'
        self.assertIsNotNone(acceptance.chain_matches(expected,var,facts))
        access['contexts']=[]
        self.assertIsNone(acceptance.chain_matches(expected,var,facts))

    def test_duplicate_identity_cannot_count_as_complete_inventory(self):
        expected=dict(name='count',file='a.c',kind='FILE_STATIC')
        row=dict(name='count',definition_file='a.c',kind='FILE_STATIC')
        self.assertIsNone(acceptance.identify(expected,dict(variables=[row,row])))
