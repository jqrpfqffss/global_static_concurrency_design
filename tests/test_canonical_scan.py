"""Real one-TU extraction and publication/recovery failure boundaries."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import read_json
from ecra.config import load_config
from ecra.scan_persistence import run_canonical, artifact
from ecra.scan_store import EvidenceProvider
from ecra.workflow import checked_scan, output_path, saved_run
from ecra.report_package import export_report, import_report, sha256


class CanonicalScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra canonical 中文 ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base/'firmware'; self.root.mkdir()
        (self.root/'main.c').write_text('int shared; void ISR(void){shared++;} int main(void){shared++;return shared;}',encoding='utf-8')
        self.native_build=self.base/'native-build';self.native_build.mkdir()
        database = self.native_build/'compile_commands.json'
        database.write_text(json.dumps([dict(directory=str(self.root),file='main.c',
            arguments=['arm-none-eabi-gcc','-mcpu=cortex-m7','-mthumb','-c','main.c','-o',str(self.native_build/'main.o')])]),encoding='utf-8')
        self.data = self.base/'data'
        self.config = self.base/'semantics.yaml'
        self.config.write_text(json.dumps(dict(version=1,project=dict(root=str(self.root)),
            analysis=dict(compile_database=str(database),output=dict(location='custom',custom_dir=str(self.data))),
            contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['ISR'])],
            review=dict(enabled=False,prepare_packets=False))),encoding='utf-8')

    def run_scan(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = run_canonical(self.root,self.config,no_review=True)
        self.assertIn(code,(0,1,2),stream.getvalue())
        cfg,_ = load_config(self.root,self.config)
        return output_path(self.root,cfg), cfg

    def test_native_sqlite_only_scan_resume_and_full_package_retain_evidence(self):
        before = {p.name:sha256(p) for p in self.root.iterdir()}
        out,cfg = self.run_scan()
        self.assertFalse((out/'facts.json').exists())
        self.assertFalse((out/'facts.db').exists())
        self.assertFalse((out/'index.html').exists())
        self.assertFalse((out/'reports').exists())
        self.assertFalse((out/'inventory').exists())
        self.assertEqual(artifact(out/'facts.json')[0],out/'scan.db')
        facts,report,_ = checked_scan(self.root,out,cfg,self.config)
        self.assertEqual(len(facts['variables']),1)
        self.assertEqual(read_json(out/'manifest.json')['state'],'STATIC_VALIDATED')
        original = sha256(out/'scan.db')
        with contextlib.redirect_stdout(io.StringIO()):
            saved_run(self.root,self.config,render_only=True)
        self.assertEqual(sha256(out/'scan.db'),original)
        package=self.base/'complete.ecra-report'
        export_report(out,package)
        destination=self.base/'other-computer'
        result=import_report(package,destination)
        imported=destination/'scans'/result['scan_id']
        self.assertEqual(EvidenceProvider(imported/'scan.db').load('facts'),facts)
        self.assertTrue(read_json(imported/'manifest.json')['audit_index'])
        self.assertEqual({p.name:sha256(p) for p in self.root.iterdir()},before)

    def test_failed_new_scan_preserves_previous_pointer_and_bytes(self):
        out,_ = self.run_scan(); original=sha256(out/'scan.db')
        with patch('ecra.cli.merge',side_effect=MemoryError('injected canonical merge failure')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_canonical(self.root,self.config,no_review=True),3)
        cfg,_ = load_config(self.root,self.config)
        self.assertEqual(output_path(self.root,cfg),out)
        self.assertEqual(sha256(out/'scan.db'),original)
        failures=[p for p in (self.data/'scans').iterdir() if p!=out]
        self.assertEqual(len(failures),1,dict(out=str(out),other=[str(p) for p in failures]))
        self.assertFalse((failures[0]/'manifest.json').exists())
        self.assertTrue((failures[0]/'diagnostics/exception.log').is_file())

    def test_repeated_scan_preserves_finding_baseline_and_lock_covers_publication(self):
        from ecra.workspace import lock_path
        out,cfg=self.run_scan()
        original=read_json(out/'reports/global_static_concurrency.json')
        ids={row['finding_id'] for row in original['findings']}
        self.assertTrue(ids)
        from ecra.scan_persistence import archive_audit
        def inspect_publication(path):
            self.assertTrue(lock_path(self.root,cfg['analysis']).is_file())
            return archive_audit(path)
        with patch('ecra.scan_persistence.archive_audit',side_effect=inspect_publication):
            second,_=self.run_scan()
        report=read_json(second/'reports/global_static_concurrency.json')
        self.assertEqual(set(report['baseline']['unchanged']),ids)
        self.assertEqual(report['baseline']['new'],[])
        self.assertFalse(lock_path(self.root,cfg['analysis']).exists())

    def test_disabled_model_packet_navigation_and_ledger_are_real_and_lossless(self):
        cfg=json.loads(self.config.read_text(encoding='utf-8'))
        cfg['review']['prepare_packets']=True
        self.config.write_text(json.dumps(cfg),encoding='utf-8')
        with patch('ecra.review.execute',side_effect=AssertionError('disabled model must not execute')):
            out,_=self.run_scan()
        from ecra.scan_persistence import runtime, ai_page
        import sqlite3
        rows=runtime(out)['reviews']
        self.assertTrue(rows)
        self.assertTrue(all(row['state']=='PENDING' for row in rows))
        page=ai_page(out,limit=1)
        self.assertEqual(page['total'],len(rows))
        nav=read_json(out/'review/facts-navigation.json')
        self.assertEqual(nav['database'],str(out/'scan.db'))
        self.assertFalse((out/'review/static-report.json').exists())
        from contextlib import closing
        with closing(sqlite3.connect(out/'reviews.db')) as conn:
            self.assertGreater(conn.execute('SELECT count(*) FROM ai_events').fetchone()[0],0)
            snapshot=json.loads(conn.execute('SELECT payload FROM ai_snapshots ORDER BY sequence DESC LIMIT 1').fetchone()[0])
            self.assertEqual(snapshot['ai_events_version'],2)
            self.assertEqual(snapshot['reviews'],[])
        package=self.base/'with-ai.ecra-report'
        export_report(out,package)
        imported=import_report(package,self.base/'other')
        self.assertEqual(runtime(self.base/'other/scans'/imported['scan_id'])['reviews'],rows)

    def test_real_pinned_git_diff_uses_sqlite_baseline_and_saved_recovery(self):
        import subprocess
        def git(*args):
            return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.STDOUT).decode().strip()
        database=json.loads((self.native_build/'compile_commands.json').read_text(encoding='utf-8'))
        (self.root/'compile_commands.json').write_text(json.dumps(database),encoding='utf-8')
        git('init');git('config','user.name','ECRA acceptance');git('config','user.email','ecra@example.invalid')
        git('add','.');git('commit','-m','base');git('branch','base')
        source=(self.root/'main.c').read_text(encoding='utf-8')
        (self.root/'main.c').write_text(source.replace('shared++;return','shared+=2;return'),encoding='utf-8')
        git('add','main.c');git('commit','-m','current')
        # An untracked IDE file must not make pinned-HEAD mode "dirty".
        (self.root/'ide-state.txt').write_text('not a compiler input',encoding='utf-8')
        before=git('status','--porcelain')
        cfg=json.loads(self.config.read_text(encoding='utf-8'))
        cfg['analysis']['compile_database']='compile_commands.json'
        cfg['analysis']['git_diff']=dict(enabled=True,base_ref='base',current_ref='HEAD',include_uncommitted=False)
        self.config.write_text(json.dumps(cfg),encoding='utf-8')
        out,cfg=self.run_scan()
        _,report,_=checked_scan(self.root,out,cfg,self.config)
        self.assertIn('c:@shared',report['git_diff']['selected_symbol_ids'])
        baseline=Path(report['git_diff']['pin']['base_facts_path'])
        self.assertEqual(baseline.name,'scan.db')
        EvidenceProvider(baseline).validate(deep=True)
        self.assertFalse(list(self.data.rglob('facts.json')))
        self.assertEqual(git('status','--porcelain'),before)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(self.root,self.config,render_only=True),(0,1,2))

    def test_changed_evidence_requires_new_confirmation_and_preserves_prior_history_in_package(self):
        from ecra.human_reviews import ReviewStore
        from ecra.studio.query import QueryService
        out,_=self.run_scan()
        old_provider=EvidenceProvider(out/'scan.db')
        symbol=old_provider.symbols()['items'][0]['symbol_id']
        old=ReviewStore(out/'reviews.db',old_provider.metadata())
        event=old.append(symbol,old_provider.fingerprint(symbol),reviewer='历史声明',
            decision='CONFIRMED_SAFE',comment='仅用于验证历史保留的用户声明')
        source=(self.root/'main.c').read_text(encoding='utf-8')
        (self.root/'main.c').write_text(source.replace('shared++;','shared+=2;',1),encoding='utf-8')
        newer,_=self.run_scan()
        provider=EvidenceProvider(newer/'scan.db')
        store=ReviewStore(newer/'reviews.db',provider.metadata())
        fp=provider.fingerprint(symbol)
        self.assertNotEqual(fp,old_provider.fingerprint(symbol))
        self.assertEqual(store.current(symbol,fp)['decision'],'RECHECK_REQUIRED')
        self.assertEqual(store.history(),[])
        self.assertEqual(store.prior(symbol,fp)[0]['events'],[event])
        self.assertEqual(QueryService(newer).human_counts(),{'RECHECK_REQUIRED':1})
        self.assertEqual(QueryService(newer).symbols(human_decision='RECHECK_REQUIRED')['total'],1)
        package=self.base/'changed-evidence.ecra-report';export_report(newer,package)
        result=import_report(package,self.base/'offline')
        restored=ReviewStore(self.base/'offline/scans'/result['scan_id']/'reviews.db',provider.metadata())
        self.assertEqual(restored.current(symbol,fp)['decision'],'RECHECK_REQUIRED')
        self.assertEqual(restored.prior(symbol,fp)[0]['events'],[event])
        self.assertEqual(old.history(),[event])
        store.append(symbol,fp,reviewer='重新确认',decision='CONFIRMED_RISK',comment='当前依据')
        self.assertEqual(store.current(symbol,fp)['decision'],'CONFIRMED_RISK')

    def test_actual_cmake_external_arm_object_build_does_not_create_firmware_outputs(self):
        import shutil
        import subprocess
        if not all(shutil.which(tool) for tool in ('cmake','ninja','arm-none-eabi-gcc')):
            self.skipTest('requires real CMake/Ninja/ARM GCC')
        (self.root/'toolchain.cmake').write_text('set(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\nset(CMAKE_C_COMPILER arm-none-eabi-gcc)\n',encoding='utf-8')
        (self.root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(canonical_arm C)\nadd_library(firmware OBJECT main.c)\ntarget_compile_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb)\n',encoding='utf-8')
        cfg=json.loads(self.config.read_text(encoding='utf-8'))
        cfg['analysis'].pop('compile_database')
        cfg['analysis']['cmake']=dict(generator='Ninja',target='firmware',toolchain_file='toolchain.cmake',build=True,location='workspace')
        self.config.write_text(json.dumps(cfg),encoding='utf-8')
        before={p.name:sha256(p) for p in self.root.iterdir()}
        out,cfg=self.run_scan()
        self.assertEqual({p.name:sha256(p) for p in self.root.iterdir()},before)
        from ecra.compilation import cmake_build_directory
        objects=list(cmake_build_directory(self.root,cfg['analysis']).rglob('main.c.obj'))
        self.assertEqual(len(objects),1)
        raw=objects[0].read_bytes()[:20]
        self.assertEqual(raw[:4],b'\x7fELF')
        self.assertEqual(int.from_bytes(raw[18:20],'little'),40)
        self.assertTrue((out/'scan.db').is_file())

    def test_native_benchmark_resolves_new_pointer_and_audits_sqlite_without_html(self):
        import subprocess,sys
        evidence=self.base/'benchmark'
        command=[sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'scripts/benchmark_project_scan.py'),
            '--project',str(self.root),'--config',str(self.config),'--scan-mode','full','--evidence',str(evidence)]
        result=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace',timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        receipt=read_json(evidence/'execution.json')
        self.assertTrue(receipt['complete']);self.assertTrue(receipt['artifact_audit']['passed'])
        out=Path(receipt['output'])
        self.assertTrue((out/'scan.db').is_file());self.assertFalse((out/'index.html').exists())
        measured=receipt['seconds'];receipt['complete']=False
        from ecra.common import write_json
        write_json(evidence/'execution.json',receipt)
        resumed=subprocess.run([*command,'--audit-saved'],capture_output=True,encoding='utf-8',errors='replace',timeout=120)
        self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
        self.assertEqual(read_json(evidence/'execution.json')['seconds'],measured)
