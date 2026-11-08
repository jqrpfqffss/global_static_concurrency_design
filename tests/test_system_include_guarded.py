"""Real C+ASM, standard headers, guarded raw logs and JSON-safe receipts."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import unittest

from ecra.common import read_json,write_json
from ecra.compilation import _include_probe_diagnostic
from ecra.config import load_config
from ecra.extract import Extractor
from tests import test_working_cmake as fixture


@unittest.skipUnless(os.name=='nt','Actual Windows guarded CMake required')
class ActualGuardedHeaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.WorkingCMakeTests(methodName='runTest');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.case,self.root=self.fixture.case,self.fixture.root
        cmake=self.root/'CMakeLists.txt';text=cmake.read_text('utf-8').replace('project(dirty C)','project(dirty C ASM)')
        text=text.replace('STATIC main.c other.c ${CMAKE_CURRENT_BINARY_DIR}/generated.c)',
                          'STATIC main.c other.c asm_entry.s ${CMAKE_CURRENT_BINARY_DIR}/generated.c)')
        cmake.write_text(text,'utf-8')
        (self.root/'asm_entry.s').write_text('.syntax unified\n.thumb\n.global header_probe_asm\n.type header_probe_asm,%function\n.thumb_func\nheader_probe_asm:\n bx lr\n','utf-8')
        main=self.root/'main.c';main.write_text('#include <stdint.h>\n'+main.read_text('utf-8').replace('int shared;','uint32_t shared;'),'utf-8')
        cfg=read_json(self.case.config);cfg['analysis']['auto_system_includes']=True;write_json(self.case.config,cfg)
        self.case.before=self.case.source_files()

    def test_actual_c_asm_and_stdint_keep_readonly_guards_and_raw_hashes(self):
        descriptor=self.fixture.capture()
        prepared=read_json(Path(descriptor['file']).parent/'prepared.json')
        guard=prepared['compilation']['guarded_build']
        self.assertTrue(guard['source_readonly']);self.assertTrue(guard['namespace_changes_checked'])
        self.assertEqual(prepared['compilation']['assembly_sources'],['asm_entry.s'])
        self.assertEqual(self.case.source_files(),self.case.before)
        self.assertFalse((self.root/'build').exists())
        self.assertEqual(len(prepared['units']),3)
        # JSON serialisation and the complete saved preparation must stay valid.
        json.dumps(prepared,ensure_ascii=False)
        namespace=Path(guard['directory']).parent.parent;records=[]
        for directory in namespace.glob('command-*'):
            row=read_json(directory/'execution.json')
            if row.get('output_protocol',{}).get('mode')!='binary':continue
            raw=(directory/'stderr.log').read_bytes()
            self.assertEqual(row['output_protocol']['stderr']['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(row['output_protocol']['stderr']['bytes'],len(raw))
            readable=_include_probe_diagnostic(raw)
            self.assertNotIn('\ufffd',readable)
            self.assertIn('#include <...> search starts here:',readable)
            records.append(dict(command=row['command'],protocol=row['output_protocol'],readable_stderr=readable))
        self.assertTrue(records,'At least one actual guarded raw header probe is required')
        unit=next(x for x in prepared['units'] if x['source_file']=='main.c')
        cfg,_=load_config(self.root,self.case.config);old=Path.cwd()
        try:facts=Extractor(dict(root=str(self.root),unit=unit,config=cfg)).run()
        finally:os.chdir(old)
        self.assertEqual(facts['parse_status'],'PARSED',facts['diagnostics'])
        self.assertIn('shared',[v['name'] for v in facts['variables']])
        self.assertTrue(all(row['complete'] and row['exit_code']==0 for row in guard['actual_commands']))
        target=os.environ.get('ECRA_TEST_EVIDENCE_ROOT')
        if target:
            out=Path(target);out.mkdir(parents=True,exist_ok=True)
            write_json(out/'actual-guarded-header.json',dict(passed=True,GetACP=ctypes.windll.kernel32.GetACP(),
                source_readonly=True,namespace_changes_checked=True,source_unchanged=self.case.source_files()==self.case.before,
                auto_system_includes=True,assembly_sources=prepared['compilation']['assembly_sources'],
                c_translation_units=len(prepared['units']),parse_status=facts['parse_status'],raw_probes=records))


if __name__=='__main__':unittest.main()
