"""Physical layout, exact old formats and package rejection; no solver fixtures."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report, import_report, sha256
from ecra.scan_store import (EvidenceProvider, LEGACY_SCHEMA, SCHEMA, SCHEMA_VERSION,
                             connect_readonly, publish_scan, schema_for_version)
from ecra.studio.query import QueryService


class ScanSchemaLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ECRA 物理布局 ')
        self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.legacy=Path(__file__).with_name('fixtures').joinpath('v23_scan_schema.sql').read_text('utf-8')
        self.facts=dict(variables=[dict(symbol_id='s',name='shared',static_classification='UNKNOWN',resource_kind='scalar')],
            functions=[dict(function_id='f',name='entry')],
            accesses=[dict(access_id=str(i),symbol_id='s',function_id='f',contexts=['main','irq'],
                           mode='READ' if i%2 else 'RMW',future=dict(typed=[None,False,0,0.0,-0.0,2**80,'😀',''])) for i in range(120)],
            unknowns=[dict(reason='missing',future=i) for i in range(120)],
            future_ordered=dict(z=[2,1,2],a=['same','same']))
        self.report=dict(findings=[dict(finding_id='finding',symbol_id='s',classification='UNKNOWN',future=['second','first'])])

    def create(self,name='new'):
        out=self.base/name;publish_scan(out/'scan.db',self.facts,self.report,scan_id='s',project_id='p')
        provider=EvidenceProvider(out/'scan.db');ReviewStore(out/'reviews.db',provider.metadata())
        return out,provider

    def legacy_copy(self,source,name,version):
        out=self.base/name;out.mkdir()
        with closing(sqlite3.connect(out/'scan.db',uri=True)) as conn,conn:
            conn.execute('PRAGMA foreign_keys=ON');conn.executescript(self.legacy)
            conn.execute('ATTACH DATABASE ? AS original',((source/'scan.db').resolve().as_uri()+'?mode=ro',))
            for table in ['nodes','edges','roots','records','symbols','projects','profiles','scans']:
                conn.execute('INSERT INTO '+table+' SELECT * FROM original.'+table)
            conn.execute('PRAGMA user_version='+str(version))
        ReviewStore(out/'reviews.db',EvidenceProvider(out/'scan.db').metadata());return out

    def test_exact_old_schema_registry_and_version_types(self):
        self.assertEqual(hashlib.sha256(self.legacy.encode()).hexdigest(),
            '70454bb86688f090e98669d587ba11623a1c22419cd9eb2ab63a0f2fcc6360a9')
        self.assertEqual(LEGACY_SCHEMA,self.legacy)
        self.assertEqual(schema_for_version(1),self.legacy);self.assertEqual(schema_for_version(2),self.legacy)
        self.assertEqual(SCHEMA_VERSION,3);self.assertEqual(schema_for_version(3),SCHEMA)
        for version in [True,False,3.0,'3',None,0,4]:
            with self.subTest(version=version),self.assertRaises(ValueError):schema_for_version(version)

    def test_clustered_layout_keeps_all_typed_roots_rows_and_null_queries(self):
        new,provider=self.create();old=self.legacy_copy(new,'independent-old-layout',2)
        for folder in [new,old]:
            evidence=EvidenceProvider(folder/'scan.db');evidence.validate(deep=True)
            self.assertEqual(evidence.load('facts'),self.facts);self.assertEqual(evidence.load('report'),self.report)
            page=QueryService(folder).symbols(context='irq',limit=50)
            self.assertEqual(page['total'],1)
        self.assertEqual(provider.roots(),EvidenceProvider(old/'scan.db').roots())
        with closing(connect_readonly(new/'scan.db')) as a,closing(connect_readonly(old/'scan.db')) as b:
            for table,order in [('nodes','id'),('edges','parent,ordinal'),('records','dataset,relation,ordinal')]:
                self.assertEqual([tuple(row) for row in a.execute('SELECT * FROM '+table+' ORDER BY '+order)],
                                 [tuple(row) for row in b.execute('SELECT * FROM '+table+' ORDER BY '+order)])
            null=a.execute('SELECT count(*) FROM records WHERE symbol_id IS NULL').fetchone()[0]
            self.assertGreaterEqual(null,120)
            self.assertEqual(null,b.execute('SELECT count(*) FROM records WHERE symbol_id IS NULL').fetchone()[0])
            self.assertEqual(a.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertTrue(all(a.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0].endswith('WITHOUT ROWID') for table in ['edges','records']))
            for index in ['record_symbol','record_function','record_source','record_target']:
                self.assertIn('IS NOT NULL',a.execute('SELECT sql FROM sqlite_master WHERE name=?',(index,)).fetchone()[0])

    def test_both_old_versions_and_new_version_roundtrip_human_history_without_rewriting_source(self):
        current,_=self.create()
        for version in [1,2,3]:
            with self.subTest(version=version):
                source=current if version==3 else self.legacy_copy(current,'legacy-'+str(version),version)
                provider=EvidenceProvider(source/'scan.db');store=ReviewStore(source/'reviews.db',provider.metadata())
                event=store.append('s',provider.fingerprint('s'),reviewer='格式验收声明',decision='NEED_MORE_EVIDENCE',comment='格式往返，不是固件结论')
                original=sha256(source/'scan.db');package=self.base/('v'+str(version)+'.ecra-report');export_report(source,package)
                target=self.base/('import-'+str(version));import_report(package,target)
                restored=EvidenceProvider(target/'scans/s/scan.db')
                self.assertEqual(restored.roots(),provider.roots());self.assertEqual(sha256(source/'scan.db'),original)
                self.assertEqual(ReviewStore(target/'scans/s/reviews.db',restored.metadata()).history(),[event])
                with closing(connect_readonly(target/'scans/s/scan.db')) as conn:self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],version)

    def test_actual_bundled_v2_archive_stays_v2_and_can_be_reexported(self):
        asset=Path(__file__).resolve().parents[1]/'ecra/studio/sample_assets/stm32-demo.ecra-report'
        original=sha256(asset);root=self.base/'actual-v2';result=import_report(asset,root)
        source=root/'scans'/result['scan_id'];provider=EvidenceProvider(source/'scan.db');binding=provider.validate(deep=True)
        with closing(connect_readonly(source/'scan.db')) as conn:self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],2)
        ReviewStore(source/'reviews.db',binding)  # Existing real package, no fabricated safety event.
        package=self.base/'reexport-v2.ecra-report';export_report(source,package)
        again=import_report(package,self.base/'actual-v2-roundtrip');self.assertEqual(again['scan_id'],result['scan_id'])
        with zipfile.ZipFile(package) as zipped:self.assertEqual(json.loads(zipped.read('manifest.json'))['schema_version'],2)
        self.assertEqual(sha256(asset),original)

    def test_manifest_boolean_versions_and_relabelled_new_layout_are_rejected_without_publication(self):
        source,provider=self.create();package=self.base/'valid.ecra-report';export_report(source,package)
        destination=self.base/'existing';import_report(package,destination)
        static=sha256(destination/'scans/s/scan.db');reviews=(destination/'scans/s/reviews.db').read_bytes()
        for name,change in [('protocol-bool',dict(version=True)),('schema-bool',dict(schema_version=True)),('old-tag',dict(schema_version=2))]:
            forged=self.base/(name+'.ecra-report')
            with zipfile.ZipFile(package) as zipped,zipfile.ZipFile(forged,'w') as out:
                manifest=json.loads(zipped.read('manifest.json'));manifest.update(change)
                for item in zipped.namelist():out.writestr(item,json.dumps(manifest).encode() if item=='manifest.json' else zipped.read(item))
            with self.subTest(name=name),self.assertRaises(ValueError):import_report(forged,destination)
            self.assertEqual(sha256(destination/'scans/s/scan.db'),static)
            self.assertEqual((destination/'scans/s/reviews.db').read_bytes(),reviews)

    def test_rehashed_mixed_physical_schema_cannot_be_imported_or_exported_as_legacy(self):
        source,_=self.create();package=self.base/'v3.ecra-report';export_report(source,package)
        with closing(sqlite3.connect(source/'scan.db')) as conn:conn.execute('PRAGMA user_version=2')
        forged=self.base/'rehashed-mixed.ecra-report'
        with zipfile.ZipFile(package) as zipped,zipfile.ZipFile(forged,'w') as out:
            raw=(source/'scan.db').read_bytes();manifest=json.loads(zipped.read('manifest.json'));manifest['schema_version']=2
            manifest['files']['scan.db']=dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            for item in zipped.namelist():out.writestr(item,json.dumps(manifest).encode() if item=='manifest.json' else raw if item=='scan.db' else zipped.read(item))
        with self.assertRaisesRegex(ValueError,'结构未知'):import_report(forged,self.base/'rejected')
        with self.assertRaisesRegex(ValueError,'结构未知'):export_report(source,self.base/'rejected-export.ecra-report')
        self.assertFalse((self.base/'rejected/scans/s').exists());self.assertFalse((self.base/'rejected-export.ecra-report').exists())

    def test_unknown_sql_is_rejected_before_a_standard_package_is_written(self):
        source,_=self.create()
        with closing(sqlite3.connect(source/'scan.db')) as conn,conn:conn.execute("CREATE VIEW unknown_extra AS SELECT 'not an allowed archive schema'")
        with self.assertRaisesRegex(ValueError,'结构未知'):export_report(source,self.base/'unknown.ecra-report')
        self.assertFalse((self.base/'unknown.ecra-report').exists())


if __name__=='__main__':unittest.main()
