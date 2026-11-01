import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class NativeObserverIdentityTests(unittest.TestCase):
    def test_invalid_output_identity_cannot_create_an_escaped_directory(self):
        tool=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ecra-id-guard-') as folder:
            root=Path(folder)
            for option in ['--scan-id','--profile-id']:
                command=[sys.executable,'-B',str(tool/'scripts/measure_native_golden.py'),'--engine',str(tool),'--config',str(root/'missing.yaml'),
                         '--data-root',str(root/'data'),'--work',str(root/'work'),'--mode','canonical','--limit-gib','2',option,'../escape']
                result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=dict(os.environ,PYTHONIOENCODING='utf-8'))
                self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                self.assertIn('identity is invalid',result.stderr)
                self.assertEqual(list(root.iterdir()),[])


if __name__=='__main__':unittest.main()
