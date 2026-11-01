"""PowerShell verifies actual frozen source bytes before labelling a bundle."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name=='nt','Windows PowerShell packaging helper')
class FrozenSourcePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA source snapshot 中文 ');self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.source=self.home/'source';self.source.mkdir()
        (self.source/'源文件.bin').write_bytes(b'\x00\xff CRLF\r\n')
        self.manifest=Path(str(self.source)+'.sha256.json');content=(self.source/'源文件.bin').read_bytes()
        self.value=dict(passed=True,head='a'*40,files=[dict(file='源文件.bin',size=len(content),sha256=hashlib.sha256(content).hexdigest())])
        self.helper=self.home/'check.ps1';self.helper.write_text("param([string]$Functions,[string]$Root)\n$ErrorActionPreference='Stop'\n[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n. $Functions\nGet-FrozenSourceRevision $Root | ConvertTo-Json\n",encoding='utf-8-sig')

    def check(self):
        self.manifest.write_text(json.dumps(self.value,ensure_ascii=False),encoding='utf-8')
        # Python inherits PS7's module path unchanged; Windows PS5 cannot load
        # the PS7 Utility module that precedes its own. Use its built-in module
        # tree for this explicitly PS5 compatibility check, without altering
        # the user's shell or machine environment.
        probe_environment={key:value for key,value in os.environ.items() if key.casefold()!='psmodulepath'}
        probe_environment['PSModulePath']=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/Modules')
        return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.helper),
            '-Functions',str(Path(__file__).resolve().parents[1]/'scripts/portable_common.ps1'),'-Root',str(self.source)],capture_output=True,env=probe_environment)

    def test_verified_revision_is_bound_to_complete_actual_working_bytes_without_git(self):
        before=(self.source/'源文件.bin').read_bytes();result=self.check()
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        value=json.loads(result.stdout.decode('utf-8-sig'));self.assertEqual(value['head'],'a'*40)
        self.assertEqual(value['files'],1);self.assertEqual(value['sha256'].lower(),hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual((self.source/'源文件.bin').read_bytes(),before)

    def test_missing_changed_and_escaping_manifest_entries_fail_closed(self):
        for change in ['missing','changed','escape']:
            with self.subTest(change=change):
                original=dict(self.value['files'][0])
                if change=='missing':self.value['files'][0]['file']='absent.py'
                if change=='changed':self.value['files'][0]['sha256']='0'*64
                if change=='escape':self.value['files'][0]['file']='../outside.py'
                self.assertNotEqual(self.check().returncode,0)
                self.value['files'][0]=original
        self.assertEqual(list(self.source.iterdir()),[self.source/'源文件.bin'])


if __name__=='__main__':unittest.main()
