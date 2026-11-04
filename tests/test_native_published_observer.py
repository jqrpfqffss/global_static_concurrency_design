"""Real one-TU supervised published pipeline, not a large-project claim."""
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
        write_json(self.source/'compile_commands.json',[dict(directory=str(self.source),file='main.c',arguments=['arm-none-eabi-gcc','-mcpu=cortex-m0','-mthumb','-c','main.c'])])
        self.data=self.work/'data';self.config=self.work/'semantics.yaml'
        write_json(self.config,dict(version=1,project=dict(root=str(self.source),chip='STM32F030',core='Cortex-M0',native_word_bits=32),
            analysis=dict(compile_database='compile_commands.json',auto_system_includes=False,output=dict(location='custom',custom_dir=str(self.data))),
            contexts=[dict(id='main',kind='MAIN',functions=['main'])],review=dict(enabled=False,prepare_packets=False)))
        self.before={p.name:sha256(p) for p in self.source.iterdir()}

    def observe(self):
        command=[sys.executable,'-B',str(TOOL/'scripts/measure_native_golden.py'),'--engine',str(TOOL),'--config',str(self.config),
            '--data-root',str(self.data),'--work',str(self.work/'evidence'),'--mode','canonical-published','--limit-gib','2']
        return subprocess.run(command,cwd=TOOL,capture_output=True,text=True,encoding='utf-8',timeout=120,
            env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1'))

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
