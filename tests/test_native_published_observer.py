"""Real two-TU supervised published pipeline, not a large-project claim."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

from ecra.common import read_json,write_json
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider
from ecra.storage_activity import DataActivity

TOOL=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt','actual Windows Job observer')
class NativePublishedObserverTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='ecra observer ');self.addCleanup(folder.cleanup)
        self.work=Path(folder.name);self.source=self.work/'firmware';self.source.mkdir()
        (self.source/'main.c').write_text('int shared;int main(void){shared++;return shared;}\n','utf-8')
        (self.source/'helper.c').write_text('int helper(int value){return value+1;}\n','utf-8')
        write_json(self.source/'compile_commands.json',[dict(directory=str(self.source),file=name,arguments=['arm-none-eabi-gcc','-mcpu=cortex-m0','-mthumb','-c',name]) for name in ['main.c','helper.c']])
        self.data=self.work/'data';self.config=self.work/'semantics.yaml'
        write_json(self.config,dict(version=1,project=dict(root=str(self.source),chip='STM32F030',core='Cortex-M0',native_word_bits=32),
            analysis=dict(compile_database='compile_commands.json',auto_system_includes=False,output=dict(location='custom',custom_dir=str(self.data))),
            contexts=[dict(id='main',kind='MAIN',functions=['main'])],review=dict(enabled=False,prepare_packets=False)))
        self.before={p.name:sha256(p) for p in self.source.iterdir()}

    def observe(self,*,evidence='evidence',scan_id='native-golden',resume=None,inject=False):
        command=[sys.executable,'-B',str(TOOL/'scripts/measure_native_golden.py'),'--engine',str(TOOL),'--config',str(self.config),
            '--data-root',str(self.data),'--work',str(self.work/evidence),'--mode','canonical-published','--limit-gib','2','--scan-id',scan_id]
        if resume:command+=['--resume-published-from',str(self.work/resume)]
        if inject:command.append('--inject-stop-before-merge')
        return subprocess.run(command,cwd=TOOL,capture_output=True,text=True,encoding='utf-8',timeout=120,
            env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='0',SOURCE_DATE_EPOCH='1793577600'))

    def test_actual_full_publication_manifest_native_authority_and_budget_release(self):
        process=self.observe();self.assertEqual(process.returncode,0,process.stderr+process.stdout)
        receipt=read_json(self.work/'evidence/execution.json');self.assertTrue(receipt['complete'])
        self.assertEqual(receipt['canonical_scope'],'Public run_canonical including final publication')
        self.assertEqual(receipt['publication']['state'],'STATIC_VALIDATED')
        scan=self.data/'scans/native-golden';self.assertEqual(receipt['publication']['manifest_sha256'],sha256(scan/'manifest.json'))
        EvidenceProvider(scan/'scan.db').validate(deep=True)
        self.assertFalse((scan/'facts.json').exists());self.assertFalse((scan/'index.html').exists())
        self.assertEqual(receipt['safety_job_commit_limit_bytes'],2*1024**3)
        self.assertGreater(receipt['peaks']['peak_job_commit_bytes'],0)
        with DataActivity(self.data,exclusive=True,purpose='scan-budget'):pass
        self.assertEqual(self.before,{p.name:sha256(p) for p in self.source.iterdir()})

    def test_mismatched_declared_output_never_creates_fake_scan_or_touches_other_root(self):
        cfg=read_json(self.config);elsewhere=self.work/'different data';cfg['analysis']['output']['custom_dir']=str(elsewhere);write_json(self.config,cfg)
        process=self.observe();self.assertNotEqual(process.returncode,0)
        receipt=read_json(self.work/'evidence/execution.json');self.assertFalse(receipt['complete'])
        self.assertIsNone(receipt['publication']['manifest_sha256'])
        self.assertFalse((self.data/'scans/native-golden').exists());self.assertFalse(elsewhere.exists())
        self.assertEqual(self.before,{p.name:sha256(p) for p in self.source.iterdir()})

    def test_real_interrupted_extraction_resumes_verified_cache_into_new_public_scan(self):
        failed=self.observe(inject=True);self.assertNotEqual(failed.returncode,0)
        old=self.data/'scans/native-golden';self.assertFalse((old/'manifest.json').exists())
        original={p.relative_to(old).as_posix():sha256(p) for p in old.rglob('*') if p.is_file()}
        resumed=self.observe(evidence='recovery',scan_id='recovered',resume='evidence')
        self.assertEqual(resumed.returncode,0,resumed.stderr+resumed.stdout)
        value=read_json(self.work/'recovery/execution.json');self.assertTrue(value['complete']);self.assertFalse(value['cold_extraction'])
        self.assertEqual(value['tu_cache'],dict(hits=2,extracted=0,corrupt=0,total=2))
        self.assertEqual(Path(value['recovery']['previous_output']),old.resolve())
        EvidenceProvider(self.data/'scans/recovered/scan.db').validate(deep=True)
        self.assertEqual(original,{p.relative_to(old).as_posix():sha256(p) for p in old.rglob('*') if p.is_file()})
        self.assertEqual(self.before,{p.name:sha256(p) for p in self.source.iterdir()})
        # A completed observer is never an interrupted recovery source.
        refused=self.observe(evidence='refused',scan_id='another',resume='recovery')
        self.assertNotEqual(refused.returncode,0);self.assertIn('incomplete previous attempt',refused.stderr)
        self.assertFalse((self.data/'scans/another').exists())
        # A lost observer completion receipt cannot turn a published scan into
        # an interrupted one either.
        value['complete']=False;write_json(self.work/'recovery/execution.json',value)
        refused=self.observe(evidence='published-refused',scan_id='published-again',resume='recovery')
        self.assertNotEqual(refused.returncode,0);self.assertIn('already published',refused.stderr)
        self.assertFalse((self.data/'scans/published-again').exists())

    def test_recovery_reextracts_changed_source_instead_of_reusing_its_old_facts(self):
        self.assertNotEqual(self.observe(inject=True).returncode,0)
        (self.source/'main.c').write_text('int shared=7;int main(void){shared++;return shared;}\n','utf-8')
        resumed=self.observe(evidence='changed-recovery',scan_id='changed',resume='evidence')
        self.assertEqual(resumed.returncode,0,resumed.stderr+resumed.stdout)
        value=read_json(self.work/'changed-recovery/execution.json')
        self.assertEqual(value['tu_cache'],dict(hits=1,extracted=1,corrupt=0,total=2))
        facts=EvidenceProvider(self.data/'scans/changed/scan.db').load('facts')
        self.assertEqual(next(v for v in facts['variables'] if v['name']=='shared')['initializer'],'int shared = 7')

    def test_wrong_engine_config_live_owner_and_same_scan_id_are_refused_without_taking_over(self):
        self.assertNotEqual(self.observe(inject=True).returncode,0)
        path=self.work/'evidence/execution.json';raw=path.read_bytes();saved=read_json(path)
        for field,value in [('engine',str(self.work/'other-engine')),('config_sha256','different'),('pid',os.getpid())]:
            with self.subTest(field=field):
                changed=dict(saved);changed[field]=value;write_json(path,changed)
                refused=self.observe(evidence='refused-'+field,scan_id='refused-'+field,resume='evidence')
                self.assertNotEqual(refused.returncode,0);self.assertFalse((self.data/'scans'/('refused-'+field)).exists())
                path.write_bytes(raw)
        refused=self.observe(evidence='same-id',resume='evidence');self.assertNotEqual(refused.returncode,0)
        self.assertIn('new scan ID',refused.stderr)
        self.assertEqual(self.before,{p.name:sha256(p) for p in self.source.iterdir()})
