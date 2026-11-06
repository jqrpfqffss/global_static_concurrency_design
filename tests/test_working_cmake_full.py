"""Real full working-CMake scan without selecting any comparison baseline."""
import contextlib
import io
import os
import unittest
from unittest.mock import patch

from ecra.common import read_json,write_json
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider
from tests import test_working_cmake as fixture


@unittest.skipUnless(os.name=='nt','Windows guarded builds required')
class WorkingCMakeFullTests(unittest.TestCase):
    def test_generated_working_inputs_full_scan_and_saved_refresh_without_baseline(self):
        case=fixture.WorkingCMakeTests();case.setUp();self.addCleanup(case.doCleanups)
        config=read_json(case.case.config)
        config['analysis']['git_diff']=dict(enabled=False,include_uncommitted=True)
        write_json(case.case.config,config)
        descriptor=case.capture()
        from ecra.scan_persistence import run_canonical
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('ecra.compilation.configure_cmake',
                side_effect=AssertionError('Full scan must consume the prepared current build')):
            code=run_canonical(case.root,case.case.config,no_review=True,scan_id='working-full',
                scan_mode='full',_compiler_view=descriptor)
        self.assertIn(code,(0,1,2),output.getvalue())
        out=case.case.data/'scans/working-full';provider=EvidenceProvider(out/'scan.db')
        provider.validate(deep=True);facts=provider.load('facts');report=provider.load('report')
        self.assertNotIn('git_diff',report)
        self.assertEqual(len(facts['translation_units']),3)
        self.assertEqual(next(v['size_bytes'] for v in facts['variables'] if v['name']=='marker'),12)
        self.assertEqual(read_json(out/'input_closure.json')['frozen_view']['proof_scope'],
            'COMPLETE_GUARDED_CMAKE_INPUTS_V1')
        self.assertFalse((case.root/'build').exists());self.assertFalse((out/'facts.json').exists())
        self.assertFalse(list(out.glob('git_diff/base*')))
        from ecra.workflow import saved_run
        original=sha256(out/'scan.db')
        with contextlib.redirect_stdout(io.StringIO()):
            refreshed=saved_run(case.root,case.case.config,render_only=True,_out=out)
        self.assertIn(refreshed,(0,1,2));self.assertEqual(sha256(out/'scan.db'),original)
        self.assertEqual(case.case.source_files(),case.case.before)
