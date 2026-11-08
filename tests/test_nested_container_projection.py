"""Nested containers summarize concrete storage; they are never extra risks."""
from contextlib import closing
import copy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from ecra.analysis import analyze,merge
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.html_report import write_html,anchor
from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report,import_report
from ecra.scan_persistence import append_runtime
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.studio.query import QueryService
from tests import test_ecra as fixtures


class NestedContainerAnalysisTests(unittest.TestCase):
    setUp=fixtures.ProjectTest.setUp
    project=fixtures.ProjectTest.project
    extract=fixtures.ProjectTest.extract

    def test_actual_nested_storage_keeps_leaf_conflict_and_parent_members(self):
        cfg=self.project({'main.c':'''typedef struct { unsigned value; unsigned readonly; } Inner;
            typedef struct { Inner nested; unsigned nested_extra; } State;
            static State shared;
            void IRQ(void){shared.nested.value++;}
            int main(void){shared.nested.value=1;shared.nested_extra=4;return shared.nested.value;}
        '''},contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['IRQ'])])
        facts,report=self.extract(cfg);by_name={v['qualified_name']:v for v in facts['variables']}
        nested=by_name['shared.nested'];leaf=by_name['shared.nested.value']
        self.assertEqual(leaf['static_classification'],'SUSPECT')
        self.assertEqual(nested['static_classification'],'CONTAINER')
        self.assertEqual(set(nested['member_symbol_ids']),{by_name['shared.nested.value']['symbol_id'],by_name['shared.nested.readonly']['symbol_id']})
        self.assertEqual(nested['member_count'],2)
        self.assertEqual(nested['member_status_counts']['suspect'],1)
        self.assertIn('irq',nested['readers']);self.assertIn('main',nested['writers'])
        containers=[v for v in facts['variables'] if v.get('resource_kind')=='STRUCT_MEMBER_CONTAINER']
        self.assertTrue(containers)
        for container in containers:
            self.assertEqual(container['static_classification'],'CONTAINER')
            self.assertNotIn(container['symbol_id'],{f['symbol_id'] for f in report['findings']})
            self.assertNotIn(by_name['shared.nested_extra']['symbol_id'],container['member_symbol_ids'])
        leaves=[v for v in facts['variables'] if v.get('resource_kind') not in {'STRUCT_CONTAINER','STRUCT_MEMBER_CONTAINER','ARRAY_CONTAINER'}]
        self.assertEqual(report['coverage']['static_classification']['total'],len(leaves))
        self.assertTrue(any(f['symbol_id']==leaf['symbol_id'] for f in report['findings']))
        # Generate through the actual legacy renderer; child links and counts
        # come from real AST facts, not a hand-authored demo page.
        target=self.root/'legacy';target.mkdir();write_html(target,facts,report,[])
        page=(target/'index.html').read_text('utf-8')
        self.assertIn('未发现并发风险：1；疑似并发风险：1',page)
        self.assertIn('href="#'+anchor('var-',leaf['symbol_id'])+'"',page)
        # Old legacy facts lack nested labels/child summaries. Rendering can
        # derive their exact member rows without changing archived facts.
        old=copy.deepcopy(facts)
        for row in old['variables']:
            if row.get('resource_kind')=='STRUCT_MEMBER_CONTAINER':
                for key in ('static_classification','member_symbol_ids','member_count','member_status_counts'):row.pop(key,None)
        before=hashlib.sha256(repr(old).encode()).hexdigest()
        (self.root/'legacy-old').mkdir();write_html(self.root/'legacy-old',old,report,[])
        self.assertEqual(before,hashlib.sha256(repr(old).encode()).hexdigest())
        self.assertIn('未发现并发风险：1；疑似并发风险：1',(self.root/'legacy-old/index.html').read_text('utf-8'))
        for number,invalid in enumerate(([leaf['symbol_id'],leaf['symbol_id']],[[]],['unrelated-child'])):
            with self.subTest(invalid=invalid):
                damaged=copy.deepcopy(facts)
                next(row for row in damaged['variables'] if row['symbol_id']==nested['symbol_id'])['member_symbol_ids']=invalid
                destination=self.root/('invalid-'+str(number));destination.mkdir()
                with self.assertRaisesRegex(ValueError,'嵌套容器成员身份'):
                    write_html(destination,damaged,report,[])

    def test_array_member_containers_do_not_create_extra_classification_or_findings(self):
        cfg=self.project({'main.c':'''typedef struct { unsigned value; } Item;
            typedef struct { Item entries[2];char history[2][3]; } State;static State shared;
            void IRQ(void){shared.entries[0].value++;shared.history[0][0]++;}
            int main(void){shared.entries[0].value=1;shared.history[0][0]=2;return 0;}
        '''},contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['IRQ'])])
        facts,report=self.extract(cfg)
        containers=[v for v in facts['variables'] if v.get('resource_kind')=='STRUCT_MEMBER_CONTAINER']
        self.assertTrue(containers)
        finding_ids=[f['symbol_id'] for f in report['findings']]
        self.assertEqual(len(finding_ids),len(set(finding_ids)))
        for container in containers:
            self.assertEqual(container['static_classification'],'CONTAINER')
            self.assertNotIn(container['symbol_id'],finding_ids)
            self.assertEqual(container['member_count'],len(container['member_symbol_ids']))
        self.assertTrue(any(v.get('static_classification')=='SUSPECT' for v in facts['variables']))

    def test_multidimensional_boundary_keeps_conservative_root_impact(self):
        cfg=self.project({'main.c':'''typedef struct { unsigned value;unsigned readonly; } Inner;
            typedef struct { Inner nested;char history[2][3]; } State;static State shared;
            void IRQ(void){shared.history[0][0]++;}
            int main(void){shared.history[0][0]=3;return shared.nested.value;}
        '''},contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['IRQ'])])
        facts,report=self.extract(cfg)
        untouched=next(v for v in facts['variables'] if v.get('qualified_name')=='shared.nested.readonly')
        # This is a supported-scope boundary, not a claim of a real readonly
        # field race: an unmaterialized multidimensional path falls back to
        # whole-root impact. Q109 must not drop that conservative evidence.
        self.assertNotEqual(untouched['static_classification'],'SAFE_PROVEN')
        inherited=[a for a in untouched['accesses'] if a.get('inherited_from_canonical_path')=='shared']
        self.assertTrue(inherited)
        self.assertTrue(any(a.get('access_path')=='history[0][0]' for a in inherited))


class NestedContainerLegacyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ECRA old nested ');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.scan=self.base/'old';self.scan.mkdir()
        variables=[dict(symbol_id='parent',name='parent',resource_kind='STRUCT_MEMBER_CONTAINER'),
            dict(symbol_id='leaf-risk',name='leaf-risk',resource_kind='STRUCT_MEMBER',static_classification='SUSPECT'),
            dict(symbol_id='leaf-unknown',name='leaf-unknown',resource_kind='STRUCT_MEMBER',static_classification='UNKNOWN'),
            dict(symbol_id='explicit-unknown',name='explicit-unknown',resource_kind='STRUCT_MEMBER_CONTAINER',static_classification='UNKNOWN'),
            dict(symbol_id='explicit-risk',name='explicit-risk',resource_kind='STRUCT_MEMBER_CONTAINER',static_classification='SUSPECT'),
            dict(symbol_id='missing-leaf',name='missing-leaf',resource_kind='STRUCT_MEMBER')]
        findings=[dict(symbol_id=sid,finding_id=sid,static_classification=state) for sid,state in [('leaf-risk','SUSPECT'),('leaf-unknown','UNKNOWN'),('explicit-unknown','UNKNOWN'),('explicit-risk','SUSPECT')]]
        self.facts=dict(variables=variables);self.report=dict(findings=findings)
        publish_scan(self.scan/'scan.db',self.facts,self.report,scan_id='old',project_id='project')
        self.provider=EvidenceProvider(self.scan/'scan.db');self.store=ReviewStore(self.scan/'reviews.db',self.provider.metadata())
        append_runtime(self.scan,{},[dict(finding_id='explicit-risk',state='DONE',status='CONFIRMED',answer=dict(status='CONFIRMED'))])
        self.store.append('parent',self.provider.fingerprint('parent'),decision='CONFIRMED_RISK',reviewer='Protocol fixture',comment='Historical record must remain independently visible')

    def test_missing_container_label_derived_without_changing_old_authority_or_history(self):
        before=(self.scan/'scan.db').read_bytes();review_before=(self.scan/'reviews.db').read_bytes()
        self.provider.validate(deep=True)
        self.assertEqual(self.provider.load('facts'),self.facts)
        with closing(sqlite3.connect(self.scan/'scan.db')) as conn:
            self.assertEqual(conn.execute("SELECT static_classification FROM symbols WHERE symbol_id='parent'").fetchone()[0],'UNKNOWN')
        q=QueryService(self.scan);rows={r['symbol_id']:r for r in q.symbols()['items']}
        self.assertEqual(rows['parent']['static_classification'],'CONTAINER')
        self.assertEqual(rows['parent']['raw_static_classification'],'UNKNOWN')
        self.assertEqual(rows['parent']['static_classification_derived'],1)
        self.assertEqual(rows['parent']['current_result'],'CONTAINER')
        self.assertEqual(rows['parent']['human_record_decision'],'CONFIRMED_RISK')
        self.assertEqual(rows['parent']['needs_human_confirmation'],0)
        self.assertEqual(rows['explicit-risk']['static_classification'],'SUSPECT')
        self.assertEqual(rows['explicit-risk']['current_result'],'CONFIRMED')
        self.assertEqual(rows['explicit-unknown']['current_result'],'UNKNOWN')
        self.assertEqual(rows['missing-leaf']['current_result'],'UNKNOWN')
        self.assertEqual(self.provider.counts(),{'CONTAINER':1,'SUSPECT':2,'UNKNOWN':3})
        self.assertEqual(self.provider.symbols(classification='CONTAINER')['total'],1)
        self.assertEqual(q.symbols(classification='CONTAINER')['total'],1)
        self.assertEqual(q.symbols(current_result='CONTAINER')['total'],1)
        self.assertEqual(q.symbols(review_scope='pending')['total'],5)
        self.assertEqual(q.current_summary()['derived_static_classification_count'],1)
        self.assertEqual((self.scan/'scan.db').read_bytes(),before)
        self.assertEqual((self.scan/'reviews.db').read_bytes(),review_before)
        package=self.base/'legacy.ecra-report';export_report(self.scan,package)
        imported=import_report(package,self.base/'imported')
        restored=self.base/'imported/scans/old'
        EvidenceProvider(restored/'scan.db').validate(deep=True)
        with zipfile.ZipFile(package) as zipped:self.assertEqual((restored/'scan.db').read_bytes(),zipped.read('scan.db'))
        self.assertEqual(EvidenceProvider(restored/'scan.db').load('facts'),self.facts)
        self.assertEqual(EvidenceProvider(restored/'scan.db').load('report'),self.report)
        self.assertEqual((self.scan/'scan.db').read_bytes(),before)
        self.assertEqual(QueryService(restored).current_summary(),q.current_summary())
        self.assertTrue(imported)

    def test_schema_one_deep_validation_keeps_original_materialized_unknown(self):
        with sqlite3.connect(self.scan/'scan.db') as conn:conn.execute('PRAGMA user_version=1')
        before=(self.scan/'scan.db').read_bytes()
        self.provider.validate(deep=True)
        self.assertEqual(self.provider.symbols(classification='CONTAINER')['total'],1)
        self.assertEqual((self.scan/'scan.db').read_bytes(),before)

    def test_index_corruption_or_explicit_unsafe_tag_is_not_derived_away(self):
        with sqlite3.connect(self.scan/'scan.db') as conn:
            conn.execute("UPDATE symbols SET static_classification='SAFE_PROVEN' WHERE symbol_id='parent'")
        row=next(r for r in self.provider.symbols()['items'] if r['symbol_id']=='parent')
        self.assertEqual(row['static_classification'],'SAFE_PROVEN')
        self.assertEqual(row['static_classification_derived'],0)
        with self.assertRaisesRegex(ValueError,'查询投影'):self.provider.validate(deep=True)

    def test_tampered_index_kind_cannot_invent_container_identity(self):
        with sqlite3.connect(self.scan/'scan.db') as conn:
            conn.execute("UPDATE symbols SET resource_kind='STRUCT_MEMBER_CONTAINER' WHERE symbol_id='missing-leaf'")
        row=next(r for r in self.provider.symbols()['items'] if r['symbol_id']=='missing-leaf')
        self.assertEqual(row['static_classification'],'UNKNOWN')
        self.assertEqual(row['static_classification_derived'],0)
        queried=next(r for r in QueryService(self.scan).symbols()['items'] if r['symbol_id']=='missing-leaf')
        self.assertEqual(queried['current_result'],'UNKNOWN')
        self.assertEqual(queried['needs_human_confirmation'],1)
        with self.assertRaisesRegex(ValueError,'查询投影'):self.provider.validate(deep=True)
