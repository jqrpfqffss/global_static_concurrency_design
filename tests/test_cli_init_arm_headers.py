"""The first compile-database config must parse standard ARM runtime headers."""
import json
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from ecra.cli import main
from ecra.compilation import prepare
from ecra.config import load_config
from ecra.portable import bundle_root, tool_path


class InitArmHeadersTests(unittest.TestCase):
    def test_init_real_arm_database_and_extract_stdint_global(self):
        tool = Path(__file__).resolve().parents[1]
        bundled = tool/'.tools-cache/arm-gcc-10.3-2021.10/bin/arm-none-eabi-gcc.exe'
        compiler = tool_path('arm-none-eabi-gcc') if bundle_root() else (str(bundled) if bundled.is_file() else shutil.which('arm-none-eabi-gcc'))
        if not compiler:
            self.skipTest('Actual ARM GCC unavailable')
        with tempfile.TemporaryDirectory(prefix='ecra init headers ') as folder:
            base = Path(folder).resolve(); root = base/'firmware'; root.mkdir()
            source = root/'main.c'; source.write_text('#include <stdint.h>\nuint32_t shared;\nint main(void){shared++;return 0;}\n')
            output = base/'main.o'
            arguments = [compiler,'-mcpu=cortex-m0','-mthumb','-c',str(source),'-o',str(output)]
            built = subprocess.run(arguments,cwd=base,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            database = base/'compile_commands.json'
            database.write_text(json.dumps([dict(directory=str(base),file=str(source),arguments=arguments)]))
            config = base/"config with ' quote/semantics.yaml"
            captured = io.StringIO()
            with redirect_stdout(captured):
                self.assertEqual(main(['init','--project',str(root),'--config',str(config),'--compile-database',str(database)]),0)
            next_steps = [line for line in captured.getvalue().splitlines() if line.startswith(('环境检查：','一键排查：'))]
            self.assertEqual(len(next_steps),2)
            for line in next_steps:
                self.assertIn('--config',line)
                self.assertIn(str(config).replace("'", "''") if os.name=='nt' else 'semantics.yaml',line)
            cfg,_ = load_config(root,config)
            self.assertTrue(cfg['analysis']['auto_system_includes'])
            cfg['analysis']['output'] = dict(location='custom',custom_dir=str(base/'data'))
            units,_ = prepare(root,cfg)
            self.assertEqual(len(units),1)
            request = base/'extract.request.json'; result = base/'extract.result.json'
            request.write_text(json.dumps(dict(root=str(root),unit=units[0],config=cfg,verify_inputs=True)))
            proc = subprocess.run([sys.executable,'-B','-m','ecra.extract',str(request),str(result)],cwd=tool,
                env=dict(os.environ,PYTHONIOENCODING='utf-8'),capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            facts = json.loads(result.read_text('utf-8'))
            self.assertEqual(facts['parse_status'],'PARSED',facts['diagnostics'])
            self.assertIn('shared',[v['name'] for v in facts['variables']])


if __name__ == '__main__':
    unittest.main()
