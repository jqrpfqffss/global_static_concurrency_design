import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

from ecra.analysis import analyze, merge, preemption_relations
from ecra.cli import run, safe_review_samples
from ecra.compilation import normalize, prepare
from ecra.config import load_config
from ecra.extract import Extractor
from ecra.review import parse_answer, review_all
from tests.review_fixtures import structured_fields


ROOT = Path(__file__).resolve().parents[1]


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ecra test ")
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = Path.cwd()
        self.addCleanup(lambda: __import__("os").chdir(self.original_cwd))
        (self.root / ".ecra").mkdir()

    def project(self, sources, contexts=None, review=None):
        entries = []
        for name, text in sources.items():
            (self.root / name).write_text(text, encoding="utf-8")
            if name.endswith((".c", ".cpp")):
                entries.append(dict(directory=str(self.root), file=name,
                                    arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-c", name, "-o", name + ".o"]))
        (self.root / "compile_commands.json").write_text(json.dumps(entries), encoding="utf-8")
        cfg = dict(version=1, analysis=dict(compile_database="compile_commands.json"),
                   contexts=contexts or [dict(id="isr", kind="ISR", functions=["ISR"]), dict(id="task", kind="TASK", functions=["Task"])],
                   review=review or dict(enabled=False))
        (self.root / ".ecra/semantics.yaml").write_text(json.dumps(cfg), encoding="utf-8")
        return load_config(self.root)[0]

    def extract(self, cfg):
        units, audit = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=u, config=cfg)).run() for u in units]
        for part in parts:
            self.assertEqual(part["parse_status"], "PARSED", part["diagnostics"])
        facts = merge(parts)
        coverage = dict(translation_units_failed=0, **audit)
        report = analyze(facts, cfg, coverage)
        return facts, report

    def test_identity_headers_extern_shadow_and_calls(self):
        cfg = self.project({
            "h.h": "extern int g; static int hs; static inline void H(void){hs++;}",
            "a.c": '#include "h.h"\nint g; static int state; const int table[2]={1,2};\nstatic void F(void){static int s; s++; {static int s; s++;}}\nvoid ISR(void){g++; state++; F(); H();}',
            "b.c": '#include "h.h"\nstatic int state; void Task(void){g+=1; state++; H();}'})
        facts, report = self.extract(cfg)
        variables = facts["variables"]
        self.assertEqual(len([v for v in variables if v["name"] == "g"]), 1)
        self.assertEqual(len([v for v in variables if v["name"] == "state"]), 2)
        self.assertEqual(len([v for v in variables if v["name"] == "hs"]), 2)
        self.assertEqual(len([v for v in variables if v["name"] == "s"]), 2)
        g = next(v for v in variables if v["name"] == "g")
        self.assertEqual(g["size_bytes"], 4)
        self.assertEqual(set(g["writers"]), {"isr", "task"})
        self.assertTrue(next(v for v in variables if v["name"] == "table")["is_const"])
        self.assertIn("GS-MULTI-WRITER", next(f for f in report["findings"] if f["symbol_id"] == g["symbol_id"])["rules"])

    def test_access_classification_and_aliases(self):
        cfg = self.project({"a.c": """int g, idx, arr[8]; int *gp;
struct S {int field;} s;
void ISR(void) {g++;}
void Task(void){
 g = g + 1;
 arr[idx] = g;
 s.field = 3;
 int *p = &g;
 *p = 7;
 *gp = 9;
 int n = sizeof(g);
}
"""})
        facts, report = self.extract(cfg)
        vs = {v["name"]: v for v in facts["variables"]}
        self.assertEqual([a["access_kind"] for a in vs["idx"]["accesses"]], ["READ"])
        self.assertIn("WRITE", [a["access_kind"] for a in vs["arr"]["accesses"]])
        self.assertIn("WRITE", [a["access_kind"] for a in vs["s"]["accesses"]])
        self.assertEqual([a["access_kind"] for a in vs["gp"]["accesses"]], ["READ"])
        self.assertTrue(any(a.get("via_alias") == "p" and a["access_kind"] == "WRITE" for a in vs["g"]["accesses"]))
        self.assertFalse(any(a["line"] == 10 for a in vs["g"]["accesses"]))
        self.assertIn("INCOMPLETE", report["analysis_status"])

    def test_snapshot_and_local_static_reentrancy(self):
        cfg = self.project({"a.c": """int g;
static void F(void){static int s; s++;}
void ISR(void){g=5; F();}
void Task(void){int old=g; F(); g=old;}
"""})
        facts, report = self.extract(cfg)
        by_name = {f["variable_name"]: f for f in report["findings"]}
        self.assertIn("GS-STALE-SNAPSHOT", by_name["g"]["rules"])
        self.assertIn("GS-LOCAL-STATIC-REENTRANT", by_name["F::s"]["rules"])
        s = next(v for v in facts["variables"] if v["name"] == "s")
        self.assertEqual(set(s["contexts"]), {"isr", "task"})
        self.assertTrue(all(len(p) == 2 for a in s["accesses"] for p in a["call_chains"].values()))

    def test_access_preserves_all_resolved_call_paths(self):
        """A diamond must not collapse two valid routes into one shortest path."""
        cfg = self.project({"a.c": """int g;
void Use(void){ g++; }
void Left(void){ Use(); }
void Right(void){ Use(); }
void main(void){ Left(); Right(); }
"""}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        g = next(v for v in facts['variables'] if v['name'] == 'g')
        access = next(a for a in g['accesses'] if a['function_id'].endswith('Use'))
        self.assertEqual(len(access['all_call_chains']['main']), 2)
        self.assertEqual({tuple(path) for path in access['all_call_chains']['main']}, {
            (next(f['function_id'] for f in facts['functions'] if f['name'] == 'main'),
             next(f['function_id'] for f in facts['functions'] if f['name'] == 'Left'),
             next(f['function_id'] for f in facts['functions'] if f['name'] == 'Use')),
            (next(f['function_id'] for f in facts['functions'] if f['name'] == 'main'),
             next(f['function_id'] for f in facts['functions'] if f['name'] == 'Right'),
             next(f['function_id'] for f in facts['functions'] if f['name'] == 'Use')),
        })

    def test_isr_preemption_requires_grouping_and_literal_priorities(self):
        facts = dict(functions=[
            dict(function_id='main', name='main'),
            dict(function_id='tim', name='TIM4_IRQHandler'),
            dict(function_id='uart', name='USART1_IRQHandler')],
            accesses=[], calls=[],
            context_bindings=[dict(context_id='main', function_id='main', call_depth=0),
                              dict(context_id='tim', function_id='tim', call_depth=0),
                              dict(context_id='uart', function_id='uart', call_depth=0)],
            irq_priority_events=[
                dict(function_id='main', api_name='HAL_NVIC_SetPriorityGrouping', arguments=['3']),
                dict(function_id='main', api_name='HAL_NVIC_SetPriority', arguments=['TIM4_IRQn', '1', '0']),
                dict(function_id='main', api_name='HAL_NVIC_SetPriority', arguments=['USART1_IRQn', '3', '0'])])
        contexts = dict(tim=dict(id='tim', kind='ISR'), uart=dict(id='uart', kind='ISR'))
        relation = preemption_relations(facts, contexts, dict(project=dict(nvic_priority_bits=4)))[0]
        self.assertEqual(relation['relation'], 'CAN_PREEMPT')
        self.assertEqual(relation['higher'], 'tim')
        facts['irq_priority_events'] = facts['irq_priority_events'][1:]
        self.assertEqual(preemption_relations(facts, contexts)[0]['relation'], 'UNKNOWN_PREEMPTION')

    def test_safe_review_sample_is_separate_from_risk_findings(self):
        facts = dict(variables=[dict(symbol_id='b', qualified_name='safe_b', static_classification='SAFE',
                                     accesses=[], definition_file='b.c', definition_line=2),
                                dict(symbol_id='a', qualified_name='safe_a', static_classification='SAFE',
                                     accesses=[], definition_file='a.c', definition_line=1),
                                dict(symbol_id='c', qualified_name='unknown', static_classification='UNKNOWN')])
        samples = safe_review_samples(facts, 1)
        self.assertEqual([s['variable_name'] for s in samples], ['safe_a'])
        self.assertTrue(samples[0]['review_safe_sample'])
        self.assertEqual(samples[0]['rules'], ['SAFE_SAMPLE'])

    def test_task_registration_is_not_direct_call(self):
        cfg = self.project({"a.c": """int g; int xTaskCreate(void (*f)(void*), const char*, int, void*, int, void*);
void Job(void *p){g++;}
void TIM4_IRQHandler(void){g++;}
int main(void){xTaskCreate(Job,"job",10,0,1,0);return 0;}
"""}, contexts=[dict(id="main", kind="MAIN", functions=["main"])])
        facts, _ = self.extract(cfg)
        g = facts["variables"][0]
        self.assertNotIn("main", g["contexts"])
        self.assertTrue(any(c.startswith("auto:task:") for c in g["contexts"]))
        self.assertTrue(any(c.startswith("auto:TIM4_IRQHandler:") for c in g["contexts"]))

    def test_recursion_and_unreachable_access(self):
        cfg = self.project({"a.c": "int g; void Rec(void){g++; Rec();} void ISR(void){Rec();} void Task(void){} void Lost(void){g++;}"})
        facts, report = self.extract(cfg)
        self.assertTrue(facts["recursive_edges"])
        self.assertEqual(report["coverage"]["unknown_accesses"], 0)
        self.assertEqual(report['coverage']['unreachable_accesses'], 1)

    def test_protection_does_not_suppress(self):
        cfg = self.project({"a.c": "int g; void enter(void); void leave(void); void ISR(void){g++;} void Task(void){enter();g++;leave();}"})
        cfg["api_patterns"] = dict(lock_enter=["enter"], lock_exit=["leave"])
        _, report = self.extract(cfg)
        finding = next(f for f in report["findings"] if f["variable_name"] == "g")
        self.assertEqual(finding["protection_status"], "PARTIAL")
        self.assertIn("GS-MULTI-WRITER", finding["rules"])

    def test_critical_section_macro_evidence(self):
        cfg = self.project({"a.c": """int g;void vPortEnterCritical(void);void vPortExitCritical(void);
#define taskENTER_CRITICAL() vPortEnterCritical()
#define taskEXIT_CRITICAL() vPortExitCritical()
void ISR(void){g++;}
void Task(void){taskENTER_CRITICAL();g++;taskEXIT_CRITICAL();}
"""})
        cfg["api_patterns"] = dict(lock_enter=["taskENTER_CRITICAL"], lock_exit=["taskEXIT_CRITICAL"])
        facts, report = self.extract(cfg)
        self.assertEqual(len([e for e in facts["protection_events"] if e.get("macro")]), 2)
        self.assertEqual(next(f for f in report["findings"] if f["variable_name"] == "g")["protection_status"], "PARTIAL")

    def test_primask_complete_window_is_static_safe(self):
        cfg = self.project({"a.c": """int g; void __disable_irq(void); void __enable_irq(void);
void ISR(void){ g++; }
void main(void){ __disable_irq(); g++; __enable_irq(); }
"""}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                  dict(id='isr', kind='ISR', functions=['ISR'])])
        facts, report = self.extract(cfg)
        g = next(v for v in facts["variables"] if v['name'] == 'g')
        self.assertEqual(g['protection_status'], 'EFFECTIVE')
        self.assertEqual(g['static_classification'], 'SAFE')
        self.assertEqual(g['analysis_coverage'], 'COMPLETE')
        self.assertEqual(report['coverage']['static_classification'], dict(total=1, safe=1, suspect=0, unknown=0))

    def test_primask_save_restore_keeps_complete_window_effective(self):
        cfg = self.project({"a.c": """int g; typedef unsigned int uint32_t;
uint32_t __get_PRIMASK(void); void __set_PRIMASK(uint32_t); void __disable_irq(void);
void ISR(void){ g++; }
void main(void){ uint32_t key=__get_PRIMASK(); __disable_irq(); g++; __set_PRIMASK(key); }
"""}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                  dict(id='isr', kind='ISR', functions=['ISR'])])
        facts, _ = self.extract(cfg)
        g = next(v for v in facts['variables'] if v['name'] == 'g')
        self.assertEqual(g['protection_status'], 'EFFECTIVE')

    def test_partial_primask_and_basepri_are_not_safe(self):
        cfg = self.project({"a.c": """int g; void __disable_irq(void); void __enable_irq(void); void __set_BASEPRI(unsigned);
void ISR(void){ g++; }
void main(void){ int old; __disable_irq(); old=g; __enable_irq(); g=old+1; }
"""}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                  dict(id='isr', kind='ISR', functions=['ISR'])])
        facts, report = self.extract(cfg)
        g = next(v for v in facts['variables'] if v['name'] == 'g')
        self.assertEqual(g['protection_status'], 'PARTIAL')
        self.assertEqual(g['static_classification'], 'SUSPECT')
        # BASEPRI is a separate unknown in an otherwise equivalent source.
        cfg = self.project({"b.c": """int b; void __set_BASEPRI(unsigned);
void ISR(void){ b++; } void main(void){ __set_BASEPRI(0x50); b++; }
"""}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                  dict(id='isr', kind='ISR', functions=['ISR'])])
        facts, _ = self.extract(cfg)
        b = next(v for v in facts['variables'] if v['name'] == 'b')
        self.assertEqual(b['protection_status'], 'UNRESOLVED')
        self.assertEqual(b['static_classification'], 'UNKNOWN')

    def test_basepri_literal_threshold_is_effective_only_with_complete_nvic_facts(self):
        cfg = self.project({'a.c': '''enum { TIM4_IRQn = 30 };
int g; void __set_BASEPRI(unsigned); void HAL_NVIC_SetPriorityGrouping(unsigned);
void HAL_NVIC_SetPriority(unsigned, unsigned, unsigned);
void TIM4_IRQHandler(void){ g++; }
void main(void){ HAL_NVIC_SetPriorityGrouping(3); HAL_NVIC_SetPriority(TIM4_IRQn, 5, 0); __set_BASEPRI(0x50); g++; __set_BASEPRI(0); }
'''}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                  dict(id='tim', kind='ISR', functions=['TIM4_IRQHandler'])])
        cfg['project']['nvic_priority_bits'] = 4
        facts, _ = self.extract(cfg)
        g = next(v for v in facts['variables'] if v['name'] == 'g')
        self.assertEqual(g['protection_status'], 'EFFECTIVE')
        self.assertEqual(g['static_classification'], 'SAFE')

    def test_conditional_irq_mask_never_becomes_effective(self):
        cfg = self.project({"a.c": """int g; void __disable_irq(void); void __enable_irq(void);
void ISR(void){ g++; }
void main(int ready){ if (ready) __disable_irq(); g++; __enable_irq(); }
"""}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                  dict(id='isr', kind='ISR', functions=['ISR'])])
        facts, _ = self.extract(cfg)
        g = next(v for v in facts['variables'] if v['name'] == 'g')
        self.assertNotEqual(g['protection_status'], 'EFFECTIVE')
        self.assertEqual(g['static_classification'], 'SUSPECT')

    def test_pipeline_partial_parse_and_sqlite(self):
        self.project({"a.c": "int g; void ISR(void){g++;} void Task(void){g++;}", "bad.c": '#include "missing.h"\nint hidden;'})
        code = run(self.root, no_review=True)
        self.assertEqual(code, 2)
        out = self.root / ".ecra"
        report = json.loads((out / "reports/global_static_concurrency.json").read_text(encoding="utf-8"))
        self.assertEqual(report["coverage"]["translation_units_failed"], 1)
        self.assertEqual(report["run_status"], "INCOMPLETE")
        with sqlite3.connect(out / "facts.db") as db:
            self.assertGreater(db.execute("SELECT count(*) FROM variables").fetchone()[0], 0)
        db.close()
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue((out / "opencode_review.html").is_file())
        self.assertTrue((out / "review/queue.json").is_file())

        # A later fatal run must invalidate BOTH user-facing reports.
        from unittest.mock import patch
        with patch('ecra.cli.prepare', side_effect=ValueError('broken build database')):
            self.assertEqual(run(self.root, no_review=True), 3)
        for name in ('index.html', 'opencode_review.html'):
            self.assertIn('本次扫描失败', (out/name).read_text(encoding='utf-8'))

    def test_missing_sources_and_expected_define(self):
        cfg = self.project({"a.c": "int g;"})
        (self.root / "forgotten.c").write_text("int forgotten;", encoding="utf-8")
        cfg["analysis"]["expected_defines"] = ["STM32H747xx"]
        units, audit = prepare(self.root, cfg)
        self.assertEqual(audit["unlisted_sources"], ["forgotten.c"])
        self.assertEqual(units[0]["missing_defines"], ["STM32H747xx"])

    def test_response_file_and_paths_with_spaces(self):
        (self.root / "flags.rsp").write_text('-I"include dir" -DSTM32H747xx -mcpu=cortex-m7', encoding="utf-8")
        unit = normalize(dict(directory=str(self.root), file="a.c", arguments=["arm-none-eabi-gcc", "@flags.rsp", "-c", "a.c", "-o", "out.o"]), self.root, {})
        self.assertIn("-Iinclude dir", unit["arguments"])
        self.assertIn("--target=arm-none-eabi", unit["arguments"])
        self.assertNotIn("out.o", unit["arguments"])

    def test_review_validation(self):
        (self.root / "a.c").write_text("int x;", encoding="utf-8")
        answer = dict(finding_id="GS-1", status="REVIEWED_SAFE", evidence=[dict(file="a.c", line=1)],
                      **{k: "evidence" for k in ("reason", "interleaving", "protection", "impact", "fix", "verification")})
        raw = json.dumps(dict(type="text", part=dict(text=json.dumps(answer))))
        self.assertEqual(parse_answer(raw, "GS-1", self.root)["status"], "REVIEWED_SAFE")
        with self.assertRaises(ValueError):
            parse_answer(raw, "GS-2", self.root)
        answer["evidence"][0]["line"] = 99
        with self.assertRaises(ValueError):
            parse_answer(json.dumps(dict(type="text", part=dict(text=json.dumps(answer)))), "GS-1", self.root)

    def test_macro_array_escape_and_initializer(self):
        cfg = self.project({"a.c": """int g, arr[8]; int *saved=&g;
#define INC(x) ((x)++)
void ISR(void){INC(g);}
void Task(void){int *p=arr; p[0]=1;}
"""})
        facts, _ = self.extract(cfg)
        vs = {v["name"]: v for v in facts["variables"]}
        self.assertTrue(any(a["access_kind"] == "RMW" for a in vs["g"]["accesses"]))
        self.assertTrue(any(a["access_kind"] == "ADDRESS_TAKEN" for a in vs["arr"]["accesses"]))
        self.assertTrue(any(u["kind"] == "STATIC_INITIALIZER_REFERENCE" for u in facts["unknowns"]))

    def test_cpp_namespaces_and_static_members(self):
        cfg = self.project({"a.cpp": """namespace A {int state;} namespace B {int state;}
struct S {static int counter; int ordinary;}; int S::counter;
void ISR(){A::state++;S::counter++;} void Task(){B::state++;S::counter++;}
"""})
        facts, _ = self.extract(cfg)
        self.assertEqual(len([v for v in facts["variables"] if v["name"] == "state"]), 2)
        counter = [v for v in facts["variables"] if v["name"] == "counter"]
        self.assertEqual(len(counter), 1)
        self.assertIn(counter[0]["kind"], {"GLOBAL", "FILE_STATIC", "LOCAL_STATIC"})
        # A non-static data member is not an independent shared object.
        self.assertFalse(any(v["name"] == "ordinary" for v in facts["variables"]))

    def test_opencode_process_queue_cache_and_failures(self):
        cfg = self.project({"a.c": "int g;void ISR(void){g++;}void Task(void){g++;}"})
        facts, report = self.extract(cfg)
        out = self.root / ".ecra"
        fake = out / "fake_opencode.py"
        fake.write_text('''import sys,json,os
from pathlib import Path
args=sys.argv[1:]
p=Path(args[args.index('--file')+1])
packet=json.loads(p.read_text(encoding='utf-8'))
cfg=json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])
assert cfg['agent']['ecra-review']['permission']['*']=='deny'
answer=dict(finding_id=packet['finding']['finding_id'],status='CONFIRMED',evidence=[dict(file='a.c',line=1,quote=Path('a.c').read_text().splitlines()[0])])
answer.update({k:'evidence checked' for k in ('reason','interleaving','protection','impact','fix','verification')})
answer.update(__V2__)
answer['review_type']='VARIABLE' if packet['finding'].get('symbol_id') else 'EVIDENCE_GAP'
answer['evidence'][0]['claim']='Protocol fixture claim'
answer['investigation']=[dict(id=r['id'],assessment='Protocol fixture only',evidence_refs=[1]) for r in packet['investigation_requirements']]
print(json.dumps(dict(type='text',part=dict(text=json.dumps(answer)))))
'''.replace('__V2__',repr(structured_fields())), encoding="utf-8")
        cfg["review"] = dict(enabled=True, command=[sys.executable, str(fake)], retries=0)
        first = review_all(self.root, out, cfg, facts, report, "source1", lambda _: None)
        self.assertTrue(all(r["state"] == "DONE" for r in first), first)
        second = review_all(self.root, out, cfg, facts, report, "source1", lambda _: None)
        self.assertTrue(all(r.get("cached") for r in second))
        damaged = out/'review'/(first[0]['finding_id']+'.result.json')
        content = json.loads(damaged.read_text(encoding='utf-8'))
        content['answer']['evidence'] = []
        damaged.write_text(json.dumps(content), encoding='utf-8')
        repaired = review_all(self.root, out, cfg, facts, report, 'source1', lambda _: None)
        self.assertFalse(repaired[0].get('cached'))
        self.assertTrue(repaired[0]['answer']['evidence'])
        third = review_all(self.root, out, cfg, facts, report, "source2", lambda _: None)
        self.assertFalse(any(r.get("cached") for r in third))
        fake.write_text('print("not JSON events")', encoding="utf-8")
        failed = review_all(self.root, out, cfg, facts, report, "source3", lambda _: None)
        self.assertTrue(all(r["state"] == "FAILED" for r in failed))

    def test_opencode_timeout_and_queue_limit(self):
        cfg = self.project({"a.c": "int g, h;void ISR(void){g++;h++;}void Task(void){g++;h++;}"})
        facts, report = self.extract(cfg)
        fake = self.root / ".ecra/fake_opencode.py"
        fake.write_text("import time; print('partial-review-evidence',flush=True); time.sleep(5)", encoding="utf-8")
        cfg["review"] = dict(enabled=True, command=[sys.executable, str(fake)], retries=0,
                             timeout_seconds=0.5, max_items=1)
        def checkpoint(results):
            queue = json.loads((self.root/'.ecra/review/queue.json').read_text(encoding='utf-8'))
            self.assertEqual(len(queue), len(report['findings']))
        results = review_all(self.root, self.root / ".ecra", cfg, facts, report, "fingerprint", lambda _: None, checkpoint)
        self.assertEqual(results[0]["state"], "FAILED")
        self.assertTrue(all(r["state"] == "PENDING" for r in results[1:]))
        log = self.root/'.ecra/review'/(results[0]['finding_id']+'.attempt0.jsonl')
        self.assertIn('partial-review-evidence', log.read_text(encoding='utf-8'))

    def test_review_cache_survives_different_process_hash_seeds(self):
        import os
        from ecra.common import execute
        self.project({'a.c': 'int g; void H(void){g++;} void ISR(void){H();} void Task(void){H();}'})
        fake = self.root/'.ecra/fake_opencode.py'
        fake.write_text('''import sys,json
from pathlib import Path
p=Path(sys.argv[sys.argv.index('--file')+1])
packet=json.loads(p.read_text(encoding='utf-8'))
finding=packet['finding']
answer=dict(finding_id=finding['finding_id'],status='CONFIRMED',evidence=[dict(file='a.c',line=1,quote=Path('a.c').read_text().splitlines()[0])])
answer.update({k:'Checked source' for k in ('reason','interleaving','protection','impact','fix','verification')})
answer.update(__V2__)
answer['review_type']='VARIABLE' if finding.get('symbol_id') else 'EVIDENCE_GAP'
answer['evidence'][0]['claim']='Protocol fixture claim'
answer['investigation']=[dict(id=r['id'],assessment='Protocol fixture only',evidence_refs=[1]) for r in packet['investigation_requirements']]
print(json.dumps(dict(type='text',part=dict(text=json.dumps(answer)))))
'''.replace('__V2__',repr(structured_fields())), encoding='utf-8')
        cfg, path = load_config(self.root)
        cfg['review'] = dict(enabled=True, command=[sys.executable, str(fake)], retries=0)
        path.write_text(json.dumps(cfg), encoding='utf-8')
        self.assertEqual(run(self.root, no_review=True), 2)
        for index, seed in enumerate(('1', '2', '3')):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            command = 'run' if index == 1 else 'review'
            proc = execute([sys.executable, str(ROOT/'run_ecra.py'), command, '--project', str(self.root)],
                           env=env, timeout=30)
            self.assertEqual(proc.returncode, 1, proc.stdout+proc.stderr)
            queue = json.loads((self.root/'.ecra/review/queue.json').read_text(encoding='utf-8'))
            self.assertTrue(queue)
            self.assertTrue(all(r['state']=='DONE' for r in queue))
            if index:
                self.assertTrue(all(r.get('cached') for r in queue), queue)

    def test_need_more_context_is_retried_on_next_run(self):
        from subprocess import CompletedProcess
        from unittest.mock import patch
        cfg = self.project({'a.c': 'int g;void ISR(void){g++;}void Task(void){g++;}'})
        facts, report = self.extract(cfg)
        cfg['review'] = dict(enabled=True, command=[sys.executable], retries=0)
        fid = report['findings'][0]['finding_id']
        answer = dict(finding_id=fid, status='NEED_MORE_CONTEXT', evidence=[],
                      **{k:'Need scheduling evidence' for k in ('reason','interleaving','protection','impact','fix','verification')})
        answer.update(structured_fields('NEED_MORE_CONTEXT'))
        result = CompletedProcess([], 0, json.dumps(dict(type='text', part=dict(text=json.dumps(answer)))), '')
        with patch('ecra.review.execute', return_value=result) as execute:
            review_all(self.root, self.root/'.ecra', cfg, facts, report, 'same-input', lambda _:None)
            second = review_all(self.root, self.root/'.ecra', cfg, facts, report, 'same-input', lambda _:None)
        self.assertEqual(execute.call_count, 2)
        self.assertFalse(second[0].get('cached'))

    def test_stable_ids_when_lines_are_inserted(self):
        source = "int g;static void F(void){static int s;s++;}void ISR(void){g++;F();}void Task(void){g++;F();}"
        cfg = self.project({"a.c": source})
        facts1, report1 = self.extract(cfg)
        (self.root / "a.c").write_text("\n\n/* New comment */\n" + source, encoding="utf-8")
        facts2, report2 = self.extract(cfg)
        self.assertEqual([v["symbol_id"] for v in facts1["variables"]], [v["symbol_id"] for v in facts2["variables"]])
        self.assertEqual([f["finding_id"] for f in report1["findings"]], [f["finding_id"] for f in report2["findings"]])

    def test_clean_run_and_unincluded_header_gate(self):
        self.project({"a.c": "const int table=3; int main(void){return table;}"},
                     contexts=[dict(id="main", kind="MAIN", functions=["main"])])
        self.assertEqual(run(self.root, no_review=True), 0)
        (self.root / "orphan.h").write_text("static int hidden;", encoding="utf-8")
        self.assertEqual(run(self.root, no_review=True), 2)
        report = json.loads((self.root / ".ecra/reports/global_static_concurrency.json").read_text(encoding="utf-8"))
        self.assertEqual(report["coverage"]["unlisted_headers"], ["orphan.h"])
        self.assertTrue(list((self.root / ".ecra/snapshots").iterdir()))

    def test_corrupt_review_cache_is_reprocessed(self):
        cfg = self.project({"a.c": "int g;void ISR(void){g++;}void Task(void){g++;}"})
        facts, report = self.extract(cfg)
        folder = self.root / ".ecra/review"
        folder.mkdir()
        (folder / (report["findings"][0]["finding_id"] + ".result.json")).write_text("{broken", encoding="utf-8")
        cfg["review"] = dict(enabled=True, command=["ecra-nonexistent-cli-test"])
        results = review_all(self.root, self.root / ".ecra", cfg, facts, report, "x", lambda _: None)
        self.assertTrue(all(r["state"] == "FAILED" for r in results))

    def test_review_resume_does_not_parse_again_and_keeps_completed_items(self):
        from subprocess import CompletedProcess
        from unittest.mock import patch
        from ecra.workflow import saved_run, status, checked_scan
        self.project({'a.c': 'int g,h;void ISR(void){g++;h++;}void Task(void){g++;h++;}'},
                     review=dict(enabled=True,command=[sys.executable],max_items=1,retries=0))
        self.assertEqual(run(self.root,no_review=True),2)
        out=self.root/'.ecra'
        calls=[]
        def respond(argv, **kwargs):
            packet=json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
            fid=packet['finding']['finding_id']; calls.append(fid)
            answer=dict(finding_id=fid,status='CONFIRMED',evidence=[dict(file='a.c',line=1,quote=(self.root/'a.c').read_text().splitlines()[0])],
                **{k:'Checked source evidence' for k in ('reason','interleaving','protection','impact','fix','verification')})
            answer.update(structured_fields(review_type='VARIABLE' if packet['finding'].get('symbol_id') else 'EVIDENCE_GAP'))
            answer['evidence'][0]['claim']='Protocol fixture claim'
            answer['investigation']=[dict(id=r['id'],assessment='Protocol fixture only',evidence_refs=[1]) for r in packet['investigation_requirements']]
            return CompletedProcess(argv,0,json.dumps(dict(type='text',part=dict(text=json.dumps(answer)))), '')
        with patch('ecra.cli.execute',side_effect=AssertionError('Resume must not reparse Clang')), patch('ecra.review.execute',side_effect=respond):
            self.assertEqual(saved_run(self.root),2)
            self.assertEqual(len(calls),1)
            self.assertEqual(status(self.root)['unresolved'],1)
            with patch('ecra.workflow.review_all',side_effect=KeyboardInterrupt):
                self.assertEqual(saved_run(self.root),130)
            self.assertFalse((out/'scan.lock').exists())
            cfg,path=load_config(self.root)
            cfg['review']['max_items']=0
            cfg['review']['timeout_seconds']=600
            path.write_text(json.dumps(cfg),encoding='utf-8')
            self.assertEqual(saved_run(self.root),1)
            self.assertEqual(len(calls),2)
            self.assertEqual(saved_run(self.root,render_only=True),1)
            self.assertEqual(len(calls),2)
            self.assertEqual(status(self.root)['unresolved'],0)
        self.assertEqual(len(set(calls)),2)
        cfg,path=load_config(self.root)
        cfg['review']['timeout_seconds']=600
        path.write_text(json.dumps(cfg),encoding='utf-8')
        checked_scan(self.root,out,cfg,path)  # review-only settings do not force Clang
        (self.root/'a.c').write_text('int changed;',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'变化'):
            saved_run(self.root)
        self.assertFalse((out/'scan.lock').exists())

    def test_resume_rejects_changed_nested_response_file_and_new_sources(self):
        from ecra.workflow import saved_run
        self.project({'a.c': 'int g;void ISR(void){g++;}void Task(void){g++;}'})
        (self.root/'outer.rsp').write_text('@inner.rsp',encoding='utf-8')
        (self.root/'inner.rsp').write_text('-DFEATURE=1',encoding='utf-8')
        db=self.root/'compile_commands.json'
        entries=json.loads(db.read_text()); entries[0]['arguments'].insert(1,'@outer.rsp')
        db.write_text(json.dumps(entries))
        self.assertEqual(run(self.root,no_review=True),2)
        manifest=json.loads((self.root/'.ecra/input_manifest.json').read_text(encoding='utf-8'))
        self.assertIn('inner.rsp',manifest)
        (self.root/'inner.rsp').write_text('-DFEATURE=2',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'inner.rsp'):
            saved_run(self.root,render_only=True)
        (self.root/'inner.rsp').write_text('-DFEATURE=1',encoding='utf-8')
        (self.root/'new.c').write_text('int missed;',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'new.c'):
            saved_run(self.root,render_only=True)

    def test_doctor_preserves_previous_run_and_reports_even_on_failure(self):
        from unittest.mock import patch
        self.project({'a.c':'int g;void ISR(void){g++;}void Task(void){g++;}'})
        run(self.root,no_review=True)
        out=self.root/'.ecra'
        before={name:(out/name).read_bytes() for name in ('run.json','run.log','index.html','opencode_review.html','scan_state.json')}
        self.assertEqual(run(self.root,doctor_only=True),0)
        with patch('ecra.cli.prepare',side_effect=ValueError('missing database')):
            self.assertEqual(run(self.root,doctor_only=True),3)
        cfg,path=load_config(self.root)
        cfg['review']=dict(enabled=True,command=['ecra-missing-opencode-for-test'])
        path.write_text(json.dumps(cfg),encoding='utf-8')
        self.assertEqual(run(self.root,doctor_only=True),2)
        self.assertEqual(before,{name:(out/name).read_bytes() for name in before})

    def test_saved_report_rejects_damaged_facts(self):
        from ecra.workflow import saved_run
        self.project({'a.c':'int g;void ISR(void){g++;}void Task(void){g++;}'})
        run(self.root,no_review=True)
        facts=self.root/'.ecra/facts.json'
        data=json.loads(facts.read_text(encoding='utf-8')); data['accesses']=[]
        facts.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'事实'):
            saved_run(self.root,render_only=True)

    def test_saved_report_does_not_trust_an_unmatched_safe_receipt(self):
        from ecra.workflow import saved_run
        self.project({'a.c':'int g;void ISR(void){g++;}void Task(void){g++;}'})
        run(self.root,no_review=True)
        out=self.root/'.ecra'
        queue=out/'review/queue.json'
        rows=json.loads(queue.read_text(encoding='utf-8'))
        rows[0].update(state='DONE',status='REVIEWED_SAFE',answer={'reason':'old receipt from another scan'})
        queue.write_text(json.dumps(rows),encoding='utf-8')
        self.assertEqual(saved_run(self.root,render_only=True),2)
        rows=json.loads(queue.read_text(encoding='utf-8'))
        self.assertEqual(rows[0]['state'],'STALE')
        self.assertNotIn('answer',rows[0])
        report=json.loads((out/'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        self.assertEqual(report['review_summary']['reviewed_safe_or_false_positive'],0)


if __name__ == "__main__":
    unittest.main()
