import time
import unittest

from tests import test_ecra
from ecra.cli import run
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.shared_json import logical_digest


class DynamicPredefinedTests(unittest.TestCase):
    setUp=test_ecra.ProjectTest.setUp
    project=test_ecra.ProjectTest.project

    def parse(self,cfg):
        units,_=prepare(self.root,cfg)
        extractor=Extractor(dict(root=str(self.root),unit=units[0],config=cfg))
        part=extractor.run()
        literals=[node.spelling for node in extractor.translation_unit.cursor.walk_preorder()
                  if node.kind.name=='STRING_LITERAL']
        return part,literals

    def test_immutable_metadata_raw_facts_are_independent_of_actual_clock(self):
        cfg=self.project({'a.c':'const char * const buildTime=__TIME__;const char * const buildDate=__DATE__;const char * const stamp=__TIMESTAMP__;'})
        before,literals_before=self.parse(cfg);time.sleep(1.1);after,literals_after=self.parse(cfg)
        self.assertNotEqual(literals_before,literals_after)
        self.assertEqual(logical_digest(before),logical_digest(after))
        self.assertEqual({p['macro'] for p in before['dynamic_predefined_inputs']},{'__TIME__','__DATE__','__TIMESTAMP__'})
        self.assertTrue(all(p['value_coverage']=='STRING_CONTENT_UNKNOWN' for p in before['dynamic_predefined_inputs']))

    def test_clock_dependent_nvic_priority_fails_without_publishing_safety(self):
        cfg=self.project({'a.c':"void HAL_NVIC_SetPriority(int,int,int);int g;void Task(void){HAL_NVIC_SetPriority(1,__TIME__[7]-'0',0);g++;}void ISR(void){g++;}"})
        with self.assertRaisesRegex(ValueError,'动态预定义宏用于运行逻辑或存储布局'):
            self.parse(cfg)
        self.assertEqual(run(self.root,None,no_review=True),3)
        import json
        self.assertFalse(json.loads((self.root/'.ecra/result_validity.json').read_text(encoding='utf-8'))['analysis_valid'])

    def test_layout_and_same_tu_constant_folding_are_rejected(self):
        for name,source in [('a.c','int arr[sizeof(__TIME__)];'),
                       ('a.c','const char * const stamp=__TIME__;int g;void Task(void){g=stamp[0];}'),
                       ('a.cpp',"template<int N>struct Box{char bytes[N];};constexpr const char* stamp=__TIME__;Box<stamp[7]-'0'+1> box;")]:
            with self.subTest(source=source):
                cfg=self.project({name:source})
                with self.assertRaisesRegex(ValueError,'动态预定义'):
                    self.parse(cfg)

    def test_wrapped_metadata_and_unused_or_stringified_clock_tokens(self):
        for source,expected in [('#define STAMP __TIME__\nconst char * const stamp=STAMP;',1),
                                ('#define UNUSED __TIME__\nint g;',0),
                                ('#define STR(x) #x\nconst char * const stamp=STR(__TIME__);',0)]:
            with self.subTest(source=source):
                cfg=self.project({'a.c':source});part,_=self.parse(cfg)
                self.assertEqual(len(part['dynamic_predefined_inputs']),expected)
