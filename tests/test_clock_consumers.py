"""Active preprocessing, dataflow and published-report regressions."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from clang import cindex

from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.decisions import effective_decision
from ecra.extract import Extractor
from ecra.git_diff import summarize
from ecra.review import build_variable_review_packet, parse_answer
from ecra.scan_store import EvidenceProvider
from tests import test_canonical_scan, test_ecra


POSITIONS = r'''
#define DATE_ALIAS __DATE__
#define WRAP(x) ((x))
#define AGAIN(f,x) (f(x) + f(x))
#define LOG(...) emit(__VA_ARGS__)
#define PICK(c,a,b) ((c) ? (a) : (b))
#define CAT0(a,b) a ## b
#define CAT(a,b) CAT0(a,b)
#define STR(x) #x
struct State { char buffer[32]; unsigned flag; } shared;
union Text { const char *s; unsigned u; };
const char build[] = "built " DATE_ALIAS;
static union Text tag = {.s=__TIMESTAMP__};
const void *saved;
int count, guard, observed;
void *memcpy(void *, const void *, __SIZE_TYPE__);
int snprintf(char *, __SIZE_TYPE__, const char *, ...);
int strcmp(const char *, const char *);
int emit(const char *s) { static int total; total++; return s[0]; }
int consume(int);
void ISR(void) { observed++; count++; shared.flag++; }
int Task(void) {
    static const char stamp[] = __TIME__;
    const char *local = WRAP(__DATE__);
    int (*fp)(const char *) = emit;
    if (guard) emit(__DATE__); else { LOG(__TIME__); }
    if (guard) { emit(__DATE__); } else emit(__TIME__);
    while (guard--) emit(__TIMESTAMP__);
    while (guard--) { emit(__DATE__); }
    for (; guard; --guard) emit(__TIME__);
    for (; guard; --guard) { emit(__TIME__); }
    switch (guard) { case 1: emit(__DATE__); break; default: emit(__TIME__); }
retry: { emit(CAT(__DA,TE__)); }
    if (guard) goto retry;
    saved = (const void *)(local + 1);
    memcpy(shared.buffer, __DATE__, sizeof(__DATE__));
    snprintf(shared.buffer, sizeof shared.buffer, "%s", __TIMESTAMP__);
    if (strcmp(shared.buffer, stamp)) shared.flag++;
    count = fp(PICK(guard, __DATE__, __TIME__));
    observed += ({ emit(__DATE__); });
    return consume(AGAIN(emit, __DATE__)) + emit(tag.s) + build[0] + STR(__TIME__)[0];
}
'''

CPP = r'''
template<int N> struct Box { char bytes[N]; };
constexpr int digit(const char *p) { return p[7]-'0'; }
consteval int width(const char *p) { return digit(p)+1; }
using Storage = Box<width(__TIME__)>;
Storage box;
struct Sink { int call(const char *s) { return s[0]; } };
int shared;
__attribute__((aligned(1 << (digit(__TIME__) % 3)))) int aligned_word;
void Task() {
    if constexpr (__DATE__[0]=='J') shared++; else aligned_word++;
    Sink sink;
    shared += sink.call(static_cast<const char *>(__TIMESTAMP__));
}
'''


class ClockConsumers(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def scan(self, files, *args):
        cfg = self.project(files)
        database = self.root/'compile_commands.json'
        units = json.loads(database.read_text())
        for unit in units:
            if '-Xclang' in args:
                unit['arguments'][:1] = ['clang', '--target=arm-none-eabi']
            unit['arguments'][1:1] = args
        database.write_text(json.dumps(units))
        units, coverage = prepare(self.root, cfg)
        parts = []
        for unit in units:
            # Validate the fixture under its actual target/language before
            # testing the analyzer or its preprocessing observer.
            compiler = cindex.Index.create().parse(unit['source'], args=unit['arguments'])
            self.assertFalse([d for d in compiler.diagnostics if d.severity >= 3], list(compiler.diagnostics))
            part = Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run()
            self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
            parts.append(part)
        facts = merge(parts)
        facts['translation_units'] = [dict(u, parse_status=p['parse_status'], semantic_macros_digest=p['semantic_macros_digest'])
                                      for u, p in zip(units, parts)]
        report = analyze(facts, cfg, dict(translation_units_failed=0, **coverage))
        return parts, facts, report

    def test_c_positions_storage_calls_and_accesses(self):
        parts, facts, _ = self.scan({'a.c': POSITIONS, 'b.c':
            'extern int observed; int consume(int value){observed++;return value;}'}, '-std=gnu11')
        records = parts[0]['dynamic_predefined_inputs']
        self.assertEqual({b for r in records for b in r['builtins']}, {'__DATE__','__TIME__','__TIMESTAMP__'})
        self.assertTrue(any(r['macro'] == 'CAT' and r['builtins'] == ['__DATE__'] for r in records))
        self.assertTrue(any(r['kind'] == 'LITERAL_SIZE' for r in records))
        names = {c['callee_name'] for c in facts['calls']}
        self.assertTrue({'emit','consume','memcpy','snprintf','strcmp'} <= names)
        variables = {v['qualified_name']: v for v in facts['variables']}
        self.assertEqual(variables['build']['size_bytes'], 18)
        for name in ('shared.buffer','shared.flag','emit::total','Task::stamp','saved','count','observed'):
            self.assertIn(name, variables)
        modes = lambda name: {a['access_kind'] for a in variables[name]['accesses']}
        self.assertIn('RMW', modes('shared.flag'))
        self.assertIn('WRITE', modes('saved'))
        self.assertIn('RMW', modes('emit::total'))
        self.assertIn('SUSPECT', {variables[n]['static_classification'] for n in ('observed','count')})
        self.assertEqual(set(variables['observed']['contexts']), {'isr','task'})

    def test_cpp_compile_time_dispatch_and_member_call(self):
        _, facts, report = self.scan({'a.cpp': CPP}, '-std=c++20')
        records = facts['dynamic_predefined_inputs']
        self.assertTrue(any(r['scope']=='BUILD' for r in records))
        self.assertTrue(any(c['callee_name']=='call' for c in facts['calls']))
        self.assertEqual(report['analysis_status'], 'INCOMPLETE')
        from ecra.diff_impact import regional_gaps
        from ecra.diff_verification import completeness
        summary = summarize(facts, report)
        self.assertTrue(any(g['kind']=='DYNAMIC_PREDEFINED_INPUT' and g['unidentified_objects_possible']
                            for g in regional_gaps(summary, summary)))
        self.assertEqual(completeness(summary['comparison_scope'])['state'], 'VALID_PARTIAL')
        for v in facts['variables']:
            self.assertNotEqual(v['static_classification'], 'SAFE_PROVEN', v['qualified_name'])

    def test_actual_expansion_under_suppression_and_redefinition(self):
        source = r'''
#pragma clang diagnostic ignored "-Wdate-time"
#define CAT(x,y) x##y
#define STR(x) #x
#define EXPAND(x) STR(x)
#define SKIP(x) "ignored"
#define B __DATE__
const char *a = CAT(__TI,ME__);
const char *b = STR(__DATE__);
const char *c = EXPAND(__TIMESTAMP__);
const char *d = SKIP(__TIME__);
#if 0
const char *e = __DATE__;
#endif
#undef __DATE__
#define __DATE__ "x"
char replaced[sizeof(__DATE__)];
const char *alias = B;
const char *ordinary = "__DATE__"; /* __TIME__ */
'''
        parts, facts, _ = self.scan({'a.c':source}, '-w', '-std=c11')
        sites = parts[0]['dynamic_predefined_inputs']
        self.assertEqual([(r['line'],r['builtins']) for r in sites if r['builtins']],
                         [(8,['__TIME__']),(10,['__TIMESTAMP__'])])
        defined = next(r for r in sites if r.get('definitions'))
        self.assertTrue(any(r['macro'] == 'B' and r['definitions'][0]['file'] == 'a.c' for r in sites))
        self.assertEqual(defined['value_coverage'], 'BUILD_INPUT')
        self.assertEqual(defined['definitions'][0]['file'], 'a.c')
        self.assertEqual(next(v for v in facts['variables'] if v['name']=='replaced')['size_bytes'], 2)

    def test_cross_tu_storage_flow_and_unaffected_safe_object(self):
        source = {'a.c': 'const char *stamp=__DATE__;void Task(void);',
                  'b.c': """extern const char *stamp; int conditional, stable, shared;
void Task(void){ if(stamp[0]=='J') conditional++; shared++; }
void ISR(void){shared++;} void Other(void){stable++;}"""}
        _, facts, report = self.scan(source, '-std=c11')
        vs = {v['name']:v for v in facts['variables']}
        self.assertEqual(vs['conditional']['static_classification'], 'UNKNOWN')
        self.assertEqual(vs['stable']['static_classification'], 'SAFE_PROVEN')
        self.assertEqual(vs['shared']['static_classification'], 'SUSPECT')
        finding = next(f for f in report['findings'] if f['variable_name']=='conditional')
        packet = build_variable_review_packet(self.root, facts, finding, facts_path='facts.json',
            shared_path='shared.json', report_path='report.json')
        self.assertTrue(any(u.get('macro')=='__DATE__' and u.get('clock',{}).get('source')
                            for u in packet['unknowns']))
        safe = dict(finding_id=finding['finding_id'], status='REVIEWED_SAFE', reason='safe',
                    evidence=[dict(file='b.c',line=2,claim='safe')])
        self.assertEqual(effective_decision(finding,dict(state='DONE',**safe)), 'unresolved')
        with self.assertRaisesRegex(ValueError, '构建时间输入'):
            parse_answer(json.dumps(safe), finding['finding_id'], self.root, packet=packet)

    def test_bound_priority_and_paths_versus_analysis_epoch(self):
        source = {'a.c': """int a,b;
void HAL_NVIC_SetPriority(int,int,int);
void Task(void){ if(__DATE__[0]=='J') a++;else b++;
HAL_NVIC_SetPriority(1,__TIME__[7]-'0',0); }"""}
        for epoch, selected, priority in [('946684800','a',0),('1700000001','b',1)]:
            parts, facts, _ = self.scan(source,'-Xclang','-source-date-epoch','-Xclang',epoch)
            self.assertTrue(all(r['clock']['bound'] for r in parts[0]['dynamic_predefined_inputs']))
            self.assertEqual(parts[0]['irq_priority_events'][0]['argument_values'],[1,priority,0])
            self.assertEqual({v['name'] for v in facts['variables'] if v['accesses']},{selected})
        parts, facts, _ = self.scan(source)
        self.assertEqual(parts[0]['irq_priority_events'][0]['argument_values'],[1,None,0])
        self.assertEqual({v['name'] for v in facts['variables'] if v['accesses']},{'a','b'})
        self.assertTrue(all(v['static_classification']=='UNKNOWN' for v in facts['variables']))

    def test_display_only_epochs_have_equal_diff_dimensions(self):
        files = {'a.c':'void out(const char *);int g;void Task(void){out(__TIME__);g++;}',
                 'b.c':'int count;void out(const char *text){count++;}void ISR(void){count++;}'}
        data = []
        for epoch in ['946684800','1700000001']:
            with patch.dict(os.environ,SOURCE_DATE_EPOCH=epoch):
                _, facts, report = self.scan(files)
            data.append((facts, summarize(facts, report)))
        self.assertNotEqual(data[0][0]['dynamic_predefined_inputs'], data[1][0]['dynamic_predefined_inputs'])
        self.assertEqual(data[0][1], data[1][1])
        self.assertFalse(any(u['kind']=='DYNAMIC_PREDEFINED_INPUT' for u in data[0][0]['unknowns']))

    def test_pinned_time_flags_only_select_real_consumers(self):
        from ecra.git_diff import clock_only_database, compare
        pinned = dict(base_sha='a'*40, head_sha='b'*40, project_subdir='.', files=[dict(
            old_path='compile_commands.json',new_path='compile_commands.json',status='M',clock_flags_only=True)])
        for flags in [(['-Xclang','-source-date-epoch','-Xclang','946684800'],
                       ['-Xclang','-source-date-epoch','-Xclang','1700000001']),
                      (['-D__TIME__="00:00:00"'], ['-D__TIME__="12:34:51"'])]:
            def database(args):
                return json.dumps([dict(file='a.c',directory='project',arguments=['clang',*args,'-c','a.c'])])
            self.assertTrue(clock_only_database(database(flags[0]), database(flags[1])))
            import subprocess
            def command(args):
                return json.dumps([dict(file='a.c',command=subprocess.list2cmdline(['clang',*args,'-c','a.c']))])
            self.assertTrue(clock_only_database(command(flags[0]), command(flags[1])))
            self.assertFalse(clock_only_database(database([]), database([])+' '))
            self.assertFalse(clock_only_database(database(flags[0]), database([*flags[1],'-DFEATURE=1'])))
            for use in ('out(__TIME__);g++;', "if(__TIME__[7]=='0')g++;"):
                summaries = []
                for args in flags:
                    _, facts, report = self.scan({'a.c':'void out(const char *); int g; void Task(){'+use+'}',
                        'b.c':'int count;void out(const char*s){count++;}void ISR(){count++;}'}, *args)
                    summaries.append(summarize(facts, report))
                selected = compare(*summaries, pinned)['selected_symbol_ids']
                if use.startswith('out'):
                    self.assertEqual(selected, [])
                else:
                    self.assertIn('c:@g', selected)

    def test_delayed_function_macro_stringification_and_command_line_override(self):
        source = """#define ID(x) x
#define JOIN(a,b) a##b
#define STR(x) #x
#define B __DATE__
char *a=ID(JOIN)(__TI,ME__), *b=B, *c=STR(__DATE__);
#ifdef __DATE__
int enabled;
#endif
"""
        parts, _, _ = self.scan({'a.c':source}, '-D__DATE__="short"')
        rows = parts[0]['dynamic_predefined_inputs']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['builtins'], ['__TIME__'])
        self.assertEqual(rows[1]['definitions'], [dict(name='__DATE__', file='<command-line>',
                                                      spelling='__DATE__="short"')])
        self.assertEqual(rows[1]['literal_types'], ['char[6]'])

    def test_used_statement_expression_return_propagates_across_tus(self):
        _, facts, _ = self.scan({'a.c':'int f(const char *);int g;void Task(){g=({f(__DATE__);});}',
             'b.c':'int f(const char *s){return s[0];}'}, '-std=gnu11')
        self.assertTrue(facts['calls'][0]['result_used'])
        self.assertIn('UNKNOWN_DYNAMIC_BUILD_INPUT', facts['variables'][0]['unknown_reason_codes'])

    def test_preprocessed_file_is_the_compiler_input(self):
        cfg = self.project({'a.c':'int ignored;'})
        (self.root/'image.i').write_text('int a,b; void Task(void){if("Jun 12 2001"[0]==74) a++;else b++;}')
        database = self.root/'compile_commands.json'
        unit, = json.loads(database.read_text())
        unit.update(file='image.i', arguments=['clang','--target=arm-none-eabi','-c','image.i'])
        database.write_text(json.dumps([unit]))
        units, _ = prepare(self.root, cfg)
        part = Extractor(dict(root=str(self.root), unit=units[0], config=cfg)).run()
        self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
        self.assertFalse(part['dynamic_predefined_inputs'])
        self.assertEqual({a['symbol_id'] for a in merge([part])['accesses']}, {'c:@a'})

    def test_observer_failure_preserves_both_paths_and_real_memory_error(self):
        source = {'a.c': "int a,b; void Task(){if(__DATE__[0]=='J')a++;else b++;}"}
        original = cindex.Index.parse
        def inject(error):
            def parse(index, *args, **kwargs):
                if '-fmacro-backtrace-limit=0' in kwargs.get('args', ()):
                    raise error
                return original(index, *args, **kwargs)
            return patch.object(cindex.Index, 'parse', parse)
        with inject(cindex.TranslationUnitLoadError('injected trace load failure')):
            parts, facts, report = self.scan(source)
        self.assertEqual(parts[0]['dynamic_predefined_inputs'][0]['scope'], 'BUILD')
        self.assertEqual(report['analysis_status'], 'INCOMPLETE')
        self.assertEqual({v['name'] for v in facts['variables'] if v['accesses']}, {'a','b'})
        self.assertTrue(all(v['static_classification']=='UNKNOWN' for v in facts['variables']))
        with inject(MemoryError('test quota')), self.assertRaises(MemoryError):
            self.scan(source)

    def test_direct_and_transitive_template_arguments_block_absence_proofs(self):
        _, facts, _ = self.scan({'a.cpp': """
int a,b; template<int N> void set(){a++;} template<> void set<0>(){b++;}
void Task(){const int first=__TIME__[7]-'0'; const int second=first; set<second>();}
void Other(){set<__TIME__[7]-'0'>();}
"""}, '-std=c++20')
        self.assertEqual([r['scope'] for r in facts['dynamic_predefined_inputs']], ['BUILD','BUILD'])
        self.assertEqual({v['name']:v['static_classification'] for v in facts['variables']},
                         {'a':'UNKNOWN','b':'UNKNOWN'})

    def test_analysis_only_redefinition_cannot_prove_firmware_layout(self):
        cfg = self.project({'a.c':'int storage[sizeof(__DATE__)];'})
        cfg['analysis']['extra_args'] = ['-D__DATE__="x"']
        unit = prepare(self.root,cfg)[0][0]
        part = Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run()
        row, = part['dynamic_predefined_inputs']
        self.assertEqual(part['parse_status'], 'PARSED')
        self.assertEqual(row['clock'], dict(source='ANALYSIS_MACRO_DEFINITION', bound=False))
        self.assertEqual(row['scope'], 'BUILD')
        facts = merge([part])
        analyze(facts, cfg, dict(translation_units_failed=0))
        self.assertEqual(facts['variables'][0]['static_classification'], 'UNKNOWN')

    def test_cpp_folded_irq_number_has_only_observed_mapping(self):
        parts, _, _ = self.scan({'a.cpp': "enum { First=__TIME__[7]-'0', Device_IRQn }; int value=Device_IRQn;"},
                                '-std=c++20')
        irq, = parts[0]['nvic_irq_definitions']
        self.assertIsNone(irq['value'])
        self.assertIsInstance(irq['observed_value'], int)

    def test_compiler_date_diagnostic_promoted_to_error_is_kept(self):
        cfg = self.project({'a.c':'const char *s=__DATE__;'})
        unit = prepare(self.root,cfg)[0][0]
        unit['arguments'].append('-Werror=date-time')
        part = Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run()
        self.assertEqual(part['parse_status'], 'PARTIAL')
        self.assertTrue(any(d['severity']>=3 and 'date' in d['message'].lower() for d in part['diagnostics']))

    def test_user_errors_remain_diagnostics(self):
        for error, message in [('#include "absent.h"', 'file not found'), ('int x = ;', 'expected expression')]:
            cfg = self.project({'a.c':'char *s=__DATE__;\n'+error})
            unit = prepare(self.root,cfg)[0][0]
            part = Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run()
            self.assertIn(part['parse_status'], ('PARTIAL','FAILED'))
            self.assertTrue(any(d['severity']>=3 and message in d['message'] for d in part['diagnostics']))


class ClockDiffPublication(unittest.TestCase):
    def test_published_clock_only_database_diff_matches_native_baseline(self):
        fixture = test_canonical_scan.CanonicalScanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        git, _ = fixture.pinned_diff_project()
        (fixture.root/'main.c').write_text(
            'int shared;void out(const char *p){shared++;}void ISR(){shared++;}int main(){out(__TIME__);return shared;}')
        database = fixture.root/'compile_commands.json'
        units = json.loads(database.read_text(encoding='utf8'))
        units[0]['arguments'].insert(1, '-D__TIME__="01:02:03"')
        database.write_text(json.dumps(units),encoding='utf8')
        git('add','main.c','compile_commands.json')
        git('commit','-m','first build clock')
        git('branch','clock-base')
        units[0]['arguments'][1] = '-D__TIME__="03:04:05"'
        database.write_text(json.dumps(units),encoding='utf8')
        git('add','compile_commands.json')
        git('commit','-m','second build clock')
        cfg = json.loads(fixture.config.read_text(encoding='utf8'))
        cfg['analysis']['git_diff'].update(base_ref='clock-base',verify_against_full=True)
        fixture.config.write_text(json.dumps(cfg),encoding='utf8')
        out, _ = fixture.run_scan()
        provider = EvidenceProvider(out/'scan.db')
        diff = provider.load('report')['git_diff']
        self.assertTrue(diff['pin']['files'][0]['clock_flags_only'])
        self.assertEqual(diff['selected_symbol_ids'], [])
        variable, = provider.load('facts')['variables']
        self.assertEqual(variable['static_classification'], 'SUSPECT')

    def test_published_diff_matches_independent_full_scan(self):
        fixture = test_canonical_scan.CanonicalScanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        git, _ = fixture.pinned_diff_project()
        src = fixture.root/'main.c'
        src.write_text(src.read_text().replace('shared+=2;', "if(__DATE__[0]=='J') shared+=2;"))
        git('add','main.c')
        git('commit','-m','clock dependent guard')
        cfg = json.loads(fixture.config.read_text())
        cfg['analysis']['git_diff']['verify_against_full'] = True
        fixture.config.write_text(json.dumps(cfg))
        out, _ = fixture.run_scan()
        provider = EvidenceProvider(out/'scan.db')
        facts, report = provider.load('facts'), provider.load('report')
        self.assertEqual(facts['translation_units'][0]['parse_status'], 'PARSED')
        var = next(v for v in facts['variables'] if v['name']=='shared')
        self.assertEqual(var['static_classification'], 'SUSPECT')
        self.assertIn('UNKNOWN_DYNAMIC_BUILD_INPUT', var['unknown_reason_codes'])
        self.assertIn(var['symbol_id'], report['git_diff']['selected_symbol_ids'])
        self.assertEqual(report['analysis_status'], 'INCOMPLETE')
        self.assertEqual(json.loads((out/'result_validity.json').read_text())['analysis_valid'], True)
