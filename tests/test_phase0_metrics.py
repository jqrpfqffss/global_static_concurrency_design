"""阶段 0（OPT-01/02/03）单元测试。

覆盖规划 §22.2 阶段 0 的三个度量/证据项：
- OPT-01：RR_build / RR_all 两个口径并列且分子分母一致，补充盘点不隐藏；
- OPT-02：SUSPECT 携带结构化破坏性模式码（D-xx）与最小见证；单写者门槛
  带逐项 NR 检查结果；根因统计（diagnostics）可复现；
- OPT-03：访问 evidence id 内容稳定，继承行的 inherited_from_access_id
  可长期追溯到来源访问。
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests import test_ecra
from ecra.analysis import analyze


class Phase0Tests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    MAIN = [dict(id='main', kind='MAIN', functions=['main'])]

    def extract(self, cfg, allow_fail=()):
        from ecra.analysis import merge
        from ecra.compilation import prepare
        from ecra.extract import Extractor
        units, audit = prepare(self.root, cfg)
        parts = []
        for u in units:
            part = Extractor(dict(root=str(self.root), unit=u, config=cfg)).run()
            if part['parse_status'] != 'PARSED' and u['source_file'] not in allow_fail:
                self.fail('unexpected parse failure: ' + str(part['diagnostics']))
            parts.append(part)
        facts = merge(parts)
        for part, unit in zip(parts, units):
            if part['parse_status'] != 'PARSED':
                facts['unknowns'].append(dict(kind='PARSE_FAILED', file=unit['source_file'],
                                              diagnostics=part['diagnostics']))
        audit['translation_units_failed'] = sum(p['parse_status'] != 'PARSED' for p in parts)
        coverage = dict(audit)
        return facts, audit, coverage

    def analyze(self, sources, contexts=None, configure=None):
        cfg = self.project(sources, contexts=contexts or self.MAIN)
        if configure:
            configure(cfg)
        facts, audit, coverage = self.extract(cfg)
        return facts, analyze(facts, cfg, coverage, root=self.root)

    def variable(self, facts, name, path=None):
        if path:
            return next(v for v in facts['variables'] if v.get('canonical_path') == path
                        or v.get('qualified_name') == path)
        return next(v for v in facts['variables'] if v['name'] == name
                    and v.get('resource_kind') != 'STRUCT_CONTAINER')

    # ---- OPT-01：指标口径 ------------------------------------------------

    def test_OPT01_rr_build_and_rr_all_reported_separately(self):
        cfg = self.project({'a.c': '''
            int shared = 0;
            void TIM2_IRQHandler(void){ shared = 1; }
            int main(void){ while(1){ shared = 2; } return 0; }
        '''}, contexts=self.MAIN)
        facts, audit, coverage = self.extract(cfg)
        # 注入一条补充盘点声明（未编译源码中的声明），验证口径拆分。
        facts['variables'].append(dict(
            symbol_id='X-supplemental-inventory', name='suppl_only', qualified_name='suppl_only',
            kind='GLOBAL', linkage='EXTERNAL', type='int', coverage_source='supplemental',
            definition_file='missing_variant.c', definition_line=3, parse_status='PARSED'))
        report = analyze(facts, cfg, coverage, root=self.root)
        cov = report['coverage']
        build = cov['static_classification_build']
        static = cov['static_classification']
        quality = cov['classification_quality']
        # 两个口径的分母关系：TOTAL_BUILD + VARIANT_INVENTORY = 全盘点 TOTAL
        self.assertEqual(build['variant_inventory'], 1)
        self.assertEqual(build['total'] + build['variant_inventory'], static['total'])
        self.assertEqual(build['dependency_declarations'], 0)
        # 分子分母同口径
        expect_rr_build = round(100 * (build['suspect'] + build['unknown']) / max(1, build['total']), 2)
        self.assertEqual(build['rr_build'], expect_rr_build)
        expect_rr_all = round(100 * (build['suspect'] + build['unknown'] + 1)
                              / (build['total'] + 1), 2)
        self.assertEqual(build['rr_all'], expect_rr_all)
        # quality 中的历史键 review_rate 与 rr_all 同口径，不再混入盘点分子
        self.assertEqual(quality['rr_build'], build['rr_build'])
        self.assertEqual(quality['rr_all'], build['rr_all'])
        self.assertEqual(quality['review_rate'], build['rr_all'])
        self.assertEqual(quality['total_build'], build['total'])

    # ---- OPT-02：结构化原因码与最小见证 ----------------------------------

    def test_OPT02_double_write_carries_destructive_code_and_witness(self):
        facts, report = self.analyze({'a.c': '''
            int flag = 0;
            void TIM2_IRQHandler(void){ flag = 1; }
            void TIM3_IRQHandler(void){ flag = 2; }
            int main(void){ while(1){ flag = 0; } return 0; }
            '''})
        v = self.variable(facts, 'flag')
        self.assertEqual(v['static_classification'], 'SUSPECT')
        self.assertIn('D-01', v['destructive_codes'])
        witness = next(w for w in v['witnesses'] if w['pattern'] == 'D-01')
        self.assertEqual(len(witness['domains']), 2)
        self.assertTrue(all(witness['access_ids']))
        all_ids = {a['access_id'] for a in facts['accesses']}
        for aid in witness['access_ids']:
            self.assertIn(aid, all_ids)
        from ecra.diagnostics import root_cause_stats
        stats = root_cause_stats(facts, report)
        self.assertGreaterEqual(stats['suspect']['multi_cause'].get('D-01', 0), 1)
        self.assertIn('D-01', stats['suspect']['labels'])

    def test_OPT02_single_writer_no_review_records_gate_results(self):
        facts, _ = self.analyze({'a.c': '''
            unsigned int counter = 0;
            void TIM2_IRQHandler(void){ counter++; }
            int main(void){ while(1){ int x = counter; (void)x; } return 0; }
            '''})
        v = self.variable(facts, 'counter')
        self.assertEqual(v['static_classification'], 'SHARED_NO_REVIEW')
        checks = {c['gate']: c for c in v['shared_no_review_evidence']['nr_checks']}
        self.assertEqual(checks['NR-01']['result'], 'PASS')
        self.assertEqual(checks['NR-03']['result'], 'PASS')
        self.assertEqual(checks['NR-03']['width'], 4)

    def test_OPT02_gate_failure_is_structured_D08(self):
        facts, _ = self.analyze({'a.c': '''
            unsigned long long stamp = 0;
            void TIM2_IRQHandler(void){ stamp++; }
            int main(void){ while(1){ unsigned long long y = stamp; (void)y; } return 0; }
            '''})
        v = self.variable(facts, 'stamp')
        self.assertEqual(v['static_classification'], 'SUSPECT')
        self.assertEqual(v['destructive_codes'], ['D-08'])
        failed = [g for g in v['gate_results'] if g.get('result') == 'FAIL']
        self.assertEqual(failed[0]['code'], 'NR-03_WIDTH_EXCEEDS_WORD')
        witness = v['witnesses'][0]
        self.assertEqual(witness['pattern'], 'D-08')
        self.assertIn('NR-03_WIDTH_EXCEEDS_WORD', witness['failed_gates'])

    def test_OPT02_root_cause_v2_json_is_written(self):
        facts, report = self.analyze({'a.c': '''
            int flag = 0;
            void TIM2_IRQHandler(void){ flag = 1; }
            void TIM3_IRQHandler(void){ flag = 2; }
            int main(void){ while(1){ flag = 0; } return 0; }
            '''})
        from ecra.diagnostics import write_root_cause_v2
        with tempfile.TemporaryDirectory() as tmp:
            write_root_cause_v2(Path(tmp), facts, report)
            data = json.loads((Path(tmp) / 'reports' / 'root_cause_v2.json')
                              .read_text(encoding='utf-8'))
        self.assertIn('D-01', data['suspect']['multi_cause'])
        self.assertIn('build', data['totals'])
        self.assertIn('rr_build', data['totals']['build'])

    # ---- OPT-03：证据 ID 稳定化 -------------------------------------------

    def test_OPT03_inherited_access_ids_stay_resolvable(self):
        # RC-3 路径修复（OPT-20）后，常规成员访问不再回退；用字节级类型
        # 双关（无法匹配成员路径）构造整对象回退与继承行，验证证据链。
        facts, _ = self.analyze({'a.c': '''
            struct Ring { int head; int tail; int buf[4]; };
            struct Ring r;
            void TIM2_IRQHandler(void){
                unsigned char *cp = (unsigned char *)&r;
                cp[0] = 1;
            }
            int main(void){ r.tail = 3; while(1){ int x = r.tail; (void)x; } return 0; }
            '''})
        inherited = [a for a in facts['accesses']
                     if a.get('access_scope') == 'INHERITED_WHOLE_OBJECT_ACCESS']
        self.assertTrue(inherited, '路径回退应产生继承行（RC-3 现状），否则该测试失去对象')
        all_ids = {a['access_id'] for a in facts['accesses']}
        rows_by_id = {a['access_id']: a for a in facts['accesses']}
        for row in inherited:
            self.assertIn(row['inherited_from_access_id'], all_ids)
            source = rows_by_id[row['inherited_from_access_id']]
            self.assertNotEqual(source.get('access_scope'), 'INHERITED_WHOLE_OBJECT_ACCESS')
        # access_id 无重复（内容稳定 ID 在合并去重后保持唯一）
        self.assertEqual(len(all_ids), len(facts['accesses']))


if __name__ == '__main__':
    unittest.main()
