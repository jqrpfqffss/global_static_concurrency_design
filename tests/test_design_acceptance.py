"""D01-D20: real Clang, facts, CFG, SQLite, both HTMLs and offline queue."""
import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from tests import test_ecra as fixtures
ROOT = fixtures.ROOT
from ecra.report import generate
from ecra.review import review_all
from ecra.html_report import anchor


EXPECTED = {
    'D01': ('unused','SAFE_PROVEN','NOT_FOUND'), 'D02': ('value','SAFE_PROVEN','NOT_FOUND'),
    'D03': ('value','SAFE_PROVEN','NOT_FOUND'), 'D04': ('value','SHARED_NO_REVIEW','NOT_FOUND'),
    'D05': ('value','SUSPECT','NOT_FOUND'), 'D06': ('value','SUSPECT','NOT_FOUND'),
    'D07': ('value','SUSPECT','NOT_FOUND'), 'D08': ('value','SAFE_PROVEN','EFFECTIVE'),
    'D09': ('value','SUSPECT','PARTIAL'),     'D10': ('value','SAFE_PROVEN','EFFECTIVE'),
    # D11/D12: 已知 MAIN↔ISR 写冲突 + BASEPRI/间接调用未解析 => SUSPECT（T15：
    # 优先级/保护缺口不能把已知冲突降级为 UNKNOWN）。
    'D11': ('value','SUSPECT','UNRESOLVED'), 'D12': ('value','SUSPECT','NOT_FOUND'),
    'D13': ('value','SAFE_PROVEN','NOT_FOUND'), 'D14': ('value','UNKNOWN','NOT_FOUND'),
    'D15': ('value','SUSPECT','NOT_FOUND'), 'D16': ('value','SAFE_PROVEN','EFFECTIVE'),
    'D17': ('value','SUSPECT','NOT_FOUND'), 'D18': ('value','SUSPECT','INEFFECTIVE'),
    'D19': ('value','SHARED_NO_REVIEW','NOT_FOUND'), 'D20': ('value','SUSPECT','NOT_FOUND'),
}


class DesignCases(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def verify_case(self, case):
        destination = os.environ.get('ECRA_ACCEPTANCE_OUT')
        if destination:
            # Use durable project roots so packet/source references remain
            # valid after unittest removes its otherwise isolated temp dirs.
            self.root = Path(destination)/case
            (self.root/'.ecra').mkdir(parents=True, exist_ok=True)
        name, classification, protection = EXPECTED[case]
        source = (ROOT/'examples/stm32_demo/cases'/case/'main.c').read_text(encoding='utf-8')
        cfg = self.project({'main.c':source}, contexts=[dict(id='main',kind='MAIN',functions=['main'])],
                           review=dict(enabled=False,prepare_packets=True))
        cfg['project']['nvic_priority_bits'] = 4
        if case == 'D16':
            cfg['critical_sections'] = [dict(enter='Enter',exit='Leave',type='irq_mask')]
        facts, report = self.extract(cfg)
        target = next(v for v in facts['variables'] if v['name']==name)
        self.assertEqual(target['static_classification'],classification,target)
        self.assertEqual(target['protection_status'],protection,target)
        self.assertEqual(target['analysis_coverage'], 'PARTIAL' if target.get('coverage_reasons') else 'COMPLETE')
        if classification == 'SAFE_PROVEN':
            self.assertTrue(target['safe_reason'])
            self.assertTrue(target['safe_evidence'])
        if classification == 'UNKNOWN':
            self.assertTrue(target['unknown_reason'])
            self.assertTrue(target['blocking_evidence'])
            self.assertTrue(target['required_context'])
        counts = report['coverage']['static_classification']
        self.assertEqual(counts['total'],sum(counts[k] for k in ('proven','no_review','suspect','unknown')))
        access_ids = {a['access_id'] for a in facts['accesses']}
        self.assertEqual(access_ids,{a['access_id'] for v in facts['variables'] for a in v['accesses']})
        if case not in {'D01'}:
            self.assertTrue(target['accesses'])
            self.assertTrue(target['contexts'])
        if case in {'D07','D20'}:
            self.assertTrue(facts['calls'])
            self.assertTrue(any(len(p)>1 for a in target['accesses'] for paths in a['all_call_chains'].values() for p in paths))
        if case == 'D20':
            self.assertEqual(len(target['accesses']),32)
            self.assertTrue(all(len(a['all_call_chains']['main'])==2 for a in target['accesses']))
        if case == 'D15':
            self.assertTrue(any(c['kind']=='DMA' for c in facts['contexts']))
        if case == 'D19':
            self.assertEqual(len(target['writers']),1)
            self.assertGreaterEqual(len(target['contexts']),2)
        facts.setdefault('translation_units', [])
        report['coverage'].update(translation_units_total=1,translation_units_parsed=1,parse_coverage_percent=100)
        out = self.root/'.ecra'
        generate(out,facts,report,[])
        reviews = review_all(self.root,out,cfg,facts,report,'design-fixture',progress=lambda _:None)
        generate(out,facts,report,reviews)
        queued = {f['symbol_id'] for f in report['findings'] if f.get('symbol_id')}
        self.assertEqual(queued,{v['symbol_id'] for v in facts['variables']
                                 if v['static_classification'] not in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}})
        html = (out/'index.html').read_text(encoding='utf-8')
        review_html = (out/'opencode_review.html').read_text(encoding='utf-8')
        self.assertIn(anchor('var-',target['symbol_id']),html)
        for access in target['accesses']:
            self.assertIn(access['access_id'],html)
            self.assertTrue(access['all_call_chains'])
        for f in report['findings']:
            self.assertIn(anchor('review-',f['finding_id']),review_html)
            packet = json.loads((out/'review'/f"{f['finding_id']}.input.json").read_text(encoding='utf-8'))
            self.assertEqual(packet['finding']['accesses'],f['accesses'])
        with closing(sqlite3.connect(out/'facts.db')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM variables').fetchone()[0],counts['total'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accesses').fetchone()[0],len(access_ids))


def _test(case):
    def method(self):
        self.verify_case(case)
    return method


for _case in EXPECTED:
    setattr(DesignCases,'test_'+_case,_test(_case))


class ControlFlowAdversarial(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def check(self, body, safe, helpers='', declarations=''):
        cfg = self.project({'a.c':'''int value; void __disable_irq(void);void __enable_irq(void);
unsigned __get_PRIMASK(void);void __set_PRIMASK(unsigned);
void TIM4_IRQHandler(void){value++;}
''' + declarations + helpers + '\nint main(int flag){'+body+'return 0;}\n'},
            contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts,_ = self.extract(cfg)
        value = next(v for v in facts['variables'] if v['name']=='value')
        self.assertEqual(value['static_classification']=='SAFE_PROVEN',safe,value)
        return value

    def test_nested_disable_is_not_a_nesting_lock(self):
        self.check('__disable_irq();__disable_irq();__enable_irq();value++;',False)

    def test_both_endpoints_masked_but_window_open(self):
        self.check('__disable_irq();int old=value;__enable_irq();__disable_irq();value=old+1;__enable_irq();',False)

    def test_branch_merge_both_arms_disable(self):
        self.check('if(flag){__disable_irq();}else{__disable_irq();}value++;__enable_irq();',True)

    def test_early_return_does_not_create_a_false_unmasked_path(self):
        self.check('__disable_irq();if(flag){__enable_irq();return 1;}value++;__enable_irq();',True)

    def test_conditional_unmask_blocks_safety(self):
        self.check('__disable_irq();if(flag)__enable_irq();value++;',False)

    def test_nested_save_restore_tracks_actual_saved_bit(self):
        self.check('unsigned a=__get_PRIMASK();__disable_irq();unsigned b=__get_PRIMASK();__disable_irq();__set_PRIMASK(b);value++;__set_PRIMASK(a);',True)

    def test_overwritten_save_key_cannot_protect(self):
        self.check('__disable_irq();unsigned k=__get_PRIMASK();k=0;__set_PRIMASK(k);value++;',False)

    def test_incremented_save_key_cannot_protect(self):
        self.check('__disable_irq();unsigned k=__get_PRIMASK();k--;__set_PRIMASK(k);value++;',False)

    def test_compound_assignment_save_key_cannot_protect(self):
        self.check('__disable_irq();unsigned k=__get_PRIMASK();k-=1;__set_PRIMASK(k);value++;',False)

    def test_local_pointer_can_overwrite_saved_key(self):
        self.check('__disable_irq();unsigned k=__get_PRIMASK();unsigned *p=&k;*p=0;__set_PRIMASK(k);value++;',False)

    def test_memset_can_overwrite_saved_key(self):
        self.check('__disable_irq();unsigned k=__get_PRIMASK();memset(&k,0,sizeof k);__set_PRIMASK(k);value++;',False,
                   declarations='void *memset(void *,int,unsigned);')

    def test_helper_access_inherits_mask(self):
        self.check('__disable_irq();Use();__enable_irq();',True,'void Use(void){value++;}')

    def test_helper_unmasks_before_access(self):
        self.check('__disable_irq();Open();value++;',False,'void Open(void){__enable_irq();}')

    def test_helper_opens_and_restores_snapshot_window(self):
        self.check('__disable_irq();int old=value;Gap();value=old;__enable_irq();',False,
                   'void Gap(void){__enable_irq();__disable_irq();}')

    def test_separate_helpers_do_not_hide_open_window(self):
        self.check('__disable_irq();Read();__enable_irq();__disable_irq();Write();__enable_irq();',False,
                   'int snapshot; void Read(void){snapshot=value;} void Write(void){value=snapshot;}')

    def test_unordered_mask_and_access_cannot_prove_safety(self):
        self.check('value += Enable();',False,'int Enable(void){__disable_irq();return 1;}')

    def test_loop_exit_join_and_break(self):
        self.check('__disable_irq();while(flag){value++;if(flag>1)break;}value++;__enable_irq();',True)

    def test_each_loop_rmw_is_independently_masked(self):
        self.check('while(flag){__disable_irq();value++;__enable_irq();}',True)

    def test_independent_helper_rmws_may_unmask_between_transactions(self):
        self.check('Use();Use();',True,'void Use(void){__disable_irq();value++;__enable_irq();}')

    def test_unsupported_goto_preserves_uncertainty(self):
        self.check('__disable_irq();if(flag)goto out;value++;out:__enable_irq();',False)


class PriorityAdversarial(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def variant(self, substitution, expected, protection):
        source = (ROOT/'examples/stm32_demo/cases/D10/main.c').read_text(encoding='utf-8')
        source = substitution(source)
        cfg = self.project({'main.c': source}, contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        cfg['project']['nvic_priority_bits'] = 4
        facts, _ = self.extract(cfg)
        value = next(v for v in facts['variables'] if v['name']=='value')
        self.assertEqual(value['static_classification'],expected,value)
        self.assertEqual(value['protection_status'],protection,value)

    def test_more_urgent_irq_is_not_masked(self):
        self.variant(lambda s:s.replace('(2+3)', '(2+0)'), 'SUSPECT','INEFFECTIVE')

    def test_uncalled_priority_setup_is_not_evidence(self):
        self.variant(lambda s:s.replace('int main(void)', 'int Configure(void)').replace('__set_BASEPRI(0x50);',
            'return 0;} int main(void){__set_BASEPRI(0x50);'), 'SUSPECT','UNRESOLVED')

    def test_conditional_priority_setup_is_not_evidence(self):
        self.variant(lambda s:s.replace('HAL_NVIC_SetPriority(TIM4_IRQn,PRIORITY,0);',
            'if(value)HAL_NVIC_SetPriority(TIM4_IRQn,PRIORITY,0);'), 'SUSPECT','UNRESOLVED')


class SafeSampleIntegration(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def test_safe_sample_queue_packet_database_and_html(self):
        from ecra.cli import safe_review_samples
        cfg = self.project({'a.c':'static int value; int main(void){value++;return 0;}'},
            contexts=[dict(id='main',kind='MAIN',functions=['main'])],
            review=dict(enabled=False,prepare_packets=True))
        facts, report = self.extract(cfg)
        facts.setdefault('translation_units', [])
        report['review_safe_samples'] = safe_review_samples(facts,1)
        report['coverage'].update(translation_units_total=1,translation_units_parsed=1,parse_coverage_percent=100)
        out = self.root/'.ecra'
        generate(out,facts,report,[])
        receipts = review_all(self.root,out,cfg,facts,report,'sample',progress=lambda _:None)
        generate(out,facts,report,receipts)
        self.assertEqual(report['findings'],[])
        self.assertEqual(report['review_summary']['total'],0)
        self.assertEqual(report['safe_sample_summary'],dict(total=1,completed=0,unresolved=1))
        sample = report['review_safe_samples'][0]
        self.assertIn(anchor('review-',sample['finding_id']),(out/'opencode_review.html').read_text(encoding='utf-8'))
        self.assertTrue((out/'review'/f"{sample['finding_id']}.input.json").is_file())
        with closing(sqlite3.connect(out/'facts.db')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_safe_samples').fetchone()[0],1)
