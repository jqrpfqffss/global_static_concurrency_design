import json
import os
import sqlite3
import time
import unittest
from contextlib import closing
from unittest.mock import patch

from tests import test_ecra
from ecra.analysis import analyze, merge
from ecra.cli import execute, run
from ecra.common import read_json
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

    def test_compile_time_print_keeps_the_call(self):
        cfg = self.project({'a.c': r'''
void ADPT_Print(const char *, ...);
void Task(void) {
    ADPT_Print("\r\n Compile Time: %s %s", __DATE__, __TIME__);
}
'''})
        part, _ = self.parse(cfg)
        self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
        self.assertEqual([c['callee_name'] for c in part['calls']], ['ADPT_Print'])
        records = part['dynamic_predefined_inputs']
        self.assertEqual([(r['macro'], r['argument_index']) for r in records],
                         [('__DATE__', 1), ('__TIME__', 2)])
        self.assertTrue(all(r['value_coverage'] == 'STRING_CONTENT_UNKNOWN' for r in records))

    def test_forwarded_strings_preserve_shared_evidence_across_build_times(self):
        source = r'''
#define DATE_TEXT __DATE__
#define BUILD_TEXT ("built " DATE_TEXT " at " __TIME__)
#define ADPT_Print(...) do { TraceWrite("boot", __VA_ARGS__); } while (0)
int shared_read, shared_rmw;
static char shared_buffer[16];
static void TraceWrite(const char *channel, const char *text, ...) {
    static unsigned writes;
    writes++;
    shared_buffer[0] = text[0];
}
void ISR(void) {
    shared_read++;
    shared_rmw++;
    TraceWrite("irq", "isr");
}
void Task(void) {
    ADPT_Print("\r\n Compile Time: %s %s",
               (BUILD_TEXT), "timestamp: " __TIMESTAMP__,
               shared_read, shared_rmw++);
}
'''
        cfg = self.project({'a.c': source})
        _, coverage = prepare(self.root, cfg)

        def scan(epoch):
            with patch.dict(os.environ, SOURCE_DATE_EPOCH=epoch):
                part, literals = self.parse(cfg)
            self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
            raw_digest = logical_digest(part)
            facts = merge([part])
            report = analyze(facts, cfg, dict(translation_units_failed=0, **coverage))
            return raw_digest, literals, facts, report, part['dynamic_predefined_inputs']

        first, first_literals, facts, report, records = scan('1700000000')
        second, second_literals, later, later_report, _ = scan('1800000000')
        self.assertEqual(first, second)
        self.assertNotEqual(first_literals, second_literals)
        self.assertEqual([(r['macro'], r['argument_index']) for r in records],
                         [('BUILD_TEXT', 2), ('__TIMESTAMP__', 3)])
        self.assertEqual(records[0]['builtins'], ['__DATE__', '__TIME__'])
        self.assertTrue(all(r['callee_name'] == 'TraceWrite' for r in records))
        line = next(i for i, text in enumerate(source.splitlines(), 1) if '(BUILD_TEXT)' in text)
        self.assertEqual({(r['file'], r['line']) for r in records}, {('a.c', line)})

        def classifications(data):
            return {v['symbol_id']: v['static_classification'] for v in data['variables']}

        self.assertEqual(classifications(facts), classifications(later))
        self.assertEqual(report['findings'], later_report['findings'])
        trace = next(f['function_id'] for f in facts['functions'] if f['name'] == 'TraceWrite')
        task = next(f['function_id'] for f in facts['functions'] if f['name'] == 'Task')
        self.assertTrue(any(c['caller_function_id'] == task and c['callee_function_id'] == trace
                            for c in facts['calls']))
        variables = {v['name']: v for v in facts['variables']}
        for name, function, mode in [('shared_read', task, 'READ'), ('shared_rmw', task, 'RMW'),
                                     ('shared_buffer', trace, 'WRITE'), ('writes', trace, 'RMW')]:
            with self.subTest(variable=name):
                variable = variables[name]
                self.assertIn((function, mode), {(a['function_id'], a['access_kind'])
                                                 for a in variable['accesses']})
                self.assertEqual(set(variable['contexts']), {'isr', 'task'})

        (self.root/'a.c').write_text(source.replace('shared_rmw++);', 'shared_rmw);'), encoding='utf-8')
        changed, _, changed_facts, _, _ = scan('1800000000')
        self.assertNotEqual(second, changed)
        rmw = next(v for v in changed_facts['variables'] if v['name'] == 'shared_rmw')
        self.assertEqual({a['access_kind'] for a in rmw['accesses'] if a['function_id'] == task}, {'READ'})

    def test_runtime_arguments_do_not_allow_consumed_values(self):
        prefix = 'int Print(const char *s, ...); int g, values[256];'
        for code in (
            "if (__DATE__[0] == 'A') g++;",
            'if (Print(__DATE__)) g++;',
            'g = values[(unsigned char)__TIMESTAMP__[0]];',
            'Print("%d", __TIME__[7]);',
            'Print(__DATE__ + 1);',
            'g = Print(__DATE__) + 1;',
            'g = ({ Print(__DATE__); });',
            '__builtin_constant_p(__TIME__);',
        ):
            with self.subTest(code=code):
                cfg = self.project({'a.c': prefix + 'void Task(void) {' + code + '}'})
                with self.assertRaisesRegex(ValueError, '动态预定义宏用于运行逻辑或存储布局'):
                    self.parse(cfg)

    def test_macro_parameter_printed_and_reused_elsewhere_is_rejected(self):
        for extra in ('g = (s)[0];', '_Static_assert(sizeof(s) > 1, "timestamp size");'):
            with self.subTest(extra=extra):
                cfg = self.project({'a.c': f'''
#define USE(s) do {{ Print(s); {extra} }} while (0)
#define FORWARD(s) USE(s)
void Print(const char *s);
int g;
void Task(void) {{ FORWARD(__DATE__); }}
'''})
                with self.assertRaisesRegex(ValueError, r'__DATE__.*无法唯一确认包装宏 FORWARD'):
                    self.parse(cfg)

    def test_cast_to_void_is_a_discarded_runtime_call(self):
        cfg = self.project({'a.c': '''
int Emit(const char *s);
void Task(void) { (void)(Emit((__DATE__))); }
'''})
        part, _ = self.parse(cfg)
        self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
        self.assertEqual([c['callee_name'] for c in part['calls']], ['Emit'])
        self.assertEqual(part['dynamic_predefined_inputs'][0]['argument_index'], 0)

    def test_macro_pasting_does_not_hide_compile_time_evaluation(self):
        prefix = '#define PASTE(a,b) a##b\n#define JOIN(a,b) PASTE(a,b)\n'
        for source in (
            'JOIN(const,expr) int Print(const char *s) { return s[0]; }\n'
            'void Task() { Print(__DATE__); }',
            'JOIN(const,eval) int Print(const char *s) { return s[0]; }\n'
            'void Task() { Print(__DATE__); }',
            'int Print(const char *s);\n'
            'int Print(const char *s) __attribute__((JOIN(enable_,if)(s[0]==0, "empty")));\n'
            'void Task() { Print(__DATE__); }',
            'void Print(const char *s);\n'
            'JOIN(const,expr) void Task(bool runtime) { if (runtime) { Print(__DATE__); } }',
        ):
            with self.subTest(source=source):
                cfg = self.project({'a.cpp': prefix + source})
                database = self.root/'compile_commands.json'
                commands = read_json(database)
                commands[0]['arguments'].insert(1, '-std=c++20')
                database.write_text(json.dumps(commands), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, '可能参与编译期求值'):
                    self.parse(cfg)

    def test_worker_saves_scan_reuses_cache_and_rejects_changed_time_logic(self):
        source = r'''
static int counter;
static void ADPT_Print(const char *fmt, ...) { counter += fmt[0]; }
int main(void) {
    ADPT_Print("\r\n Compile Time: %s %s", __DATE__, __TIME__);
    return counter;
}
'''
        self.project({'a.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        out = self.root/'.ecra'
        extractions = []

        def observe(argv, **kwargs):
            if 'ecra.extract' in argv:
                request = read_json(argv[-2])
                if not request.get('dependencies_only'):
                    extractions.append(request['unit']['source_file'])
            return execute(argv, **kwargs)

        with patch.dict(os.environ, PYTHONHASHSEED='0'), patch('ecra.cli.execute', side_effect=observe):
            self.assertIn(run(self.root, no_review=True, _cache_enabled=True), (0, 1, 2))
            self.assertEqual(extractions, ['a.c'])
            valid = read_json(out/'result_validity.json')
            self.assertTrue(valid['analysis_valid'])
            self.assertEqual(valid['state'], 'STATIC_SCAN_SAVED')
            facts = read_json(out/'facts.json')
            self.assertEqual(facts['translation_units'][0]['parse_status'], 'PARSED')
            self.assertIn('ADPT_Print', [c['callee_name'] for c in facts['calls']])
            with closing(sqlite3.connect(out/'facts.db')) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM variables WHERE name='counter'").fetchone()[0], 1)
            self.assertTrue((out/'index.html').is_file())
            self.assertTrue((out/'reports/global_static_concurrency.json').is_file())

            self.assertIn(run(self.root, no_review=True, _cache_enabled=True), (0, 1, 2))
            self.assertEqual(extractions, ['a.c'], 'The second scan should restore the verified TU')
            self.assertTrue(read_json(out/'result_validity.json')['analysis_valid'])
            self.assertEqual(read_json(out/'facts.json')['calls'], facts['calls'])

            (self.root/'a.c').write_text(source.replace('return counter;', 'return counter + __TIME__[7];'),
                                        encoding='utf-8')
            self.assertEqual(run(self.root, no_review=True, _cache_enabled=True), 3)
            self.assertEqual(extractions, ['a.c', 'a.c'], 'An edited TU must be extracted again')
            failed = read_json(out/'result_validity.json')
            self.assertFalse(failed['analysis_valid'])
            self.assertIn('Worker', failed['error'])
            self.assertIn('__TIME__', failed['error'])
            self.assertFalse((out/'scan_state.json').exists())

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
