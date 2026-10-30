from pathlib import Path
import tempfile
import unittest

from tests import test_ecra
from ecra.analysis import merge, analyze
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.git_diff import summarize, compare
from ecra.macro_semantics import sensitive_macros


class MacroSemanticsTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def summary(self, source):
        cfg=self.project({'a.c':source})
        units, coverage=prepare(self.root,cfg)
        parts=[Extractor(dict(root=str(self.root),unit=unit,config=cfg)).run() for unit in units]
        for unit,part in zip(units,parts):unit['semantic_macros_digest']=part['semantic_macros_digest']
        facts=merge(parts);facts['translation_units']=units
        return summarize(facts,analyze(facts,cfg,dict(translation_units_failed=0,**coverage)))

    def test_line_and_nested_line_macros_preserve_effective_semantic_changes(self):
        for prefix, expression in (('', '__LINE__'), ('#define INNER __LINE__\n#define OUTER INNER\n','OUTER')):
            with self.subTest(expression=expression):
                source=prefix+'int g;\nvoid Task(void){g='+expression+';}\nvoid ISR(void){g++;}\n'
                base=self.summary(source);head=self.summary('// 注释改变实际行号值\n\n'+source)
                self.assertNotEqual(base['macros'],head['macros'])
                delta=compare(base,head,dict(files=[],head_sha='H',base_sha='B'))
                self.assertIn('c:@g',delta['selected_symbol_ids'])

    def test_presumed_line_and_file_respect_line_directive(self):
        for expression, before, after in (('__LINE__','100 "virtual.c"','200 "virtual.c"'),
                ('__FILE__[0]','100 "first.c"','100 "second.c"')):
            source='int g;\n#line '+before+'\nvoid Task(void){g='+expression+';}\nvoid ISR(void){g++;}\n'
            base=self.summary(source);head=self.summary(source.replace(before,after))
            self.assertNotEqual(base['macros'],head['macros'])
            self.assertIn('c:@g',compare(base,head,dict(files=[],head_sha='H',base_sha='B'))['selected_symbol_ids'])

    def test_unexpanded_stringification_and_counter_ignore_comment_positions(self):
        cases=['#define S(x) #x\nint g;void Task(void){const char*p=S(__LINE__);g++;}\n',
               'int g;void Task(void){g=__COUNTER__;}\n',
               '#define UNUSED __LINE__\nint g;void Task(void){g++;}\n']
        for source in cases:
            with self.subTest(source=source):
                base=self.summary(source);head=self.summary('// 普通注释\n\n'+source)
                self.assertEqual(base['macros'],head['macros'])
                self.assertEqual(compare(base,head,dict(files=[],head_sha='H',base_sha='B'))['selected_symbol_ids'],[])

    def test_counter_evaluation_count_is_semantic(self):
        source='int g;void Task(void){g=__COUNTER__;}\n'
        base=self.summary(source);head=self.summary(source.replace('g=','int dummy=__COUNTER__;g='))
        self.assertNotEqual(base['macros'],head['macros'])

    def test_file_macro_normalizes_isolated_snapshot_roots(self):
        source='int g;void Task(void){g=__FILE__[0];}\n'
        base=self.summary(source)
        original=self.root
        with tempfile.TemporaryDirectory(prefix='ecra macro 中文 ') as folder:
            try:
                self.root=Path(folder).resolve()
                (self.root/'.ecra').mkdir()
                head=self.summary(source)
            finally:
                __import__('os').chdir(original)
                self.root=original
        self.assertEqual(base['macros'],head['macros'])

    def test_dependency_cycles_and_long_chains_have_no_depth_limit(self):
        definitions=[('M0',{'__LINE__','M3999'})]
        definitions.extend((f'M{i}',{f'M{i-1}'}) for i in range(1,4000))
        sensitive=sensitive_macros(definitions)
        self.assertEqual(sensitive['M3999'],{'__LINE__'})

    def test_multiline_macro_signature_ignores_git_checkout_line_endings(self):
        source = '#define STEP(x) \\\n((x)+1)\nint g;void Task(void){g=STEP(g);}\nvoid ISR(void){g++;}\n'
        cfg = self.project({'a.c': source})

        def extract_bytes(data):
            (self.root/'a.c').write_bytes(data)
            units, _ = prepare(self.root, cfg)
            part = Extractor(dict(root=str(self.root), unit=units[0], config=cfg)).run()
            self.assertEqual(part['parse_status'], 'PARSED')
            return part['semantic_macros_digest']

        baseline = extract_bytes(source.replace('\n', '\r\n').encode())
        current = extract_bytes(source.encode())
        changed = extract_bytes(source.replace('(x)+1', '(x)+2').encode())
        self.assertEqual(baseline, current)
        self.assertNotEqual(current, changed)


if __name__=='__main__':unittest.main()
