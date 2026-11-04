"""Automatic discovery feeds the proven frozen path, never a permissive VFS."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from ecra.dirty_inputs import capture_inputs,supported
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider
from tests import test_frozen_scan_pipeline as fixtures
from scripts.compare_native_graphs import compare


class DirtyInputPlanningTests(unittest.TestCase):
    def setUp(self):
        case=fixtures.FrozenScanPipelineTests(methodName='runTest');case.setUp()
        self.addCleanup(case.doCleanups);self.case=case

    def test_automatic_sdk_and_metadata_inventory_retains_full_native_semantics(self):
        case=self.case
        before={str(p):sha256(p) for p in case.root.rglob('*') if p.is_file()}
        descriptor=capture_inputs(case.root,case.config,case.data/'work/automatic-capture')
        frozen=case.scan('automatic-frozen',descriptor)
        original=case.scan('ordinary-full')
        result=compare(original/'scan.db',frozen/'scan.db')
        self.assertTrue(result['passed'],result['differences'])
        self.assertEqual({str(p):sha256(p) for p in case.root.rglob('*') if p.is_file()},before)
        from ecra.common import read_json
        plan=read_json(case.data/'work/automatic-capture/capture-plan.json')
        self.assertIn(str(case.sdk),plan['external_directories'])
        self.assertEqual(plan['compiler_view'],descriptor)
        self.assertEqual(plan['admission'],'REQUIRES_CONFIG_AND_FULL_PIPELINE_VALIDATION')

    def test_database_change_between_consumption_and_freeze_is_rejected(self):
        from ecra import working_compiler_view
        case=self.case;real=working_compiler_view.create
        def changed(*args,**kwargs):
            raw=case.database.read_bytes();case.database.write_bytes(raw+b'\n')
            return real(*args,**kwargs)
        with patch('ecra.working_compiler_view.create',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'数据库.*变化'):
                capture_inputs(case.root,case.config,case.data/'work/changed-db')

    def test_unverified_cmake_auto_and_supplement_modes_remain_blocked(self):
        for analysis in [dict(compile_database='auto'),dict(compile_database='db',cmake={}),
                dict(compile_database='db',auto_configure_cmake=True),dict(compile_database='db',build_closure_only=False)]:
            with self.subTest(analysis=analysis),self.assertRaisesRegex(ValueError,'显式编译数据库'):
                supported(analysis)

    def test_real_stop_watcher_interrupts_capture_without_publishing_a_plan_or_touching_prior_scan(self):
        import os,time
        from ecra.common import read_json
        case=self.case;out=case.scan('valid-before-capture-stop');before=sha256(out/'scan.db')
        originals={str(p):sha256(p) for p in case.root.rglob('*') if p.is_file()}
        folder=case.data/'work/capture-stopped';stop=case.data/'stop-capture'
        def progress(text):
            if '盘点真实编译参数' in text:
                stop.write_text('requested',encoding='ascii');time.sleep(2)
        with patch.dict(os.environ,ECRA_JOB_STOP_FILE=str(stop)):
            with self.assertRaises(KeyboardInterrupt):capture_inputs(case.root,case.config,folder,progress)
        self.assertFalse((folder/'capture-plan.json').exists())
        self.assertEqual(read_json(folder/'diagnostics/exception.json')['exception_type'],'KeyboardInterrupt')
        self.assertEqual(sha256(out/'scan.db'),before)
        self.assertEqual({str(p):sha256(p) for p in case.root.rglob('*') if p.is_file()},originals)

    def test_real_preflight_reuses_same_capture_and_preserves_source_and_index(self):
        from ecra.studio.preflight import run_preflight
        from ecra.common import read_json
        case=self.case
        from ecra.common import write_json
        raw=read_json(case.config)
        raw['analysis']['git_diff']=dict(enabled=True,base_ref='HEAD',current_ref='HEAD',include_uncommitted=True)
        write_json(case.config,raw)
        before={str(p):sha256(p) for p in case.root.rglob('*') if p.is_file()}
        descriptor=capture_inputs(case.root,case.config,case.data/'work/preflight-capture')
        result=run_preflight(case.config,case.data,case.data/'work/real-preflight',progress=lambda text:None,
            _compiler_view=descriptor)
        self.assertTrue(result['passed'])
        self.assertEqual(result['frozen_working_inputs'],descriptor)
        self.assertEqual(result['translation_units'],2)
        for path in (case.data/'work/real-preflight/workers').glob('*.dependencies.request.json'):
            self.assertEqual(read_json(path)['compiler_view'],descriptor)
        self.assertEqual({str(p):sha256(p) for p in case.root.rglob('*') if p.is_file()},before)

    def test_real_frozen_checkpoint_replays_both_views_and_rejects_later_source_change(self):
        from ecra.common import read_json
        from ecra.config import load_config
        from ecra.workflow import checked_scan
        case=self.case
        descriptor=capture_inputs(case.root,case.config,case.data/'work/replay-capture')
        out=case.scan('frozen-replay',descriptor)
        cfg,config=load_config(case.root,case.config)
        _,_,state=checked_scan(case.root,out,cfg,config,with_facts=False,_report_projection=True)
        self.assertEqual(state['fingerprint'],read_json(out/'scan_state.json')['fingerprint'])
        self.assertEqual(read_json(out/'diagnostics/resume_source_changes.json')['status'],'VERIFIED')
        before=sha256(out/'scan.db')
        original_index=(case.root/'.git/index').read_bytes()
        case.git('add','main.c')
        with self.assertRaisesRegex(ValueError,'原索引或HEAD已变化'):
            checked_scan(case.root,out,cfg,config,with_facts=False,_report_projection=True)
        (case.root/'.git/index').write_bytes(original_index)  # this test's private repository only
        (case.root/'main.c').write_text('int changed_after_snapshot;\n','utf-8')
        with self.assertRaisesRegex(ValueError,'变化'):
            checked_scan(case.root,out,cfg,config,with_facts=False,_report_projection=True)
        self.assertEqual(sha256(out/'scan.db'),before)

    def test_saved_render_reads_fixed_source_during_live_byte_aba(self):
        import os
        from ecra import workflow
        from ecra.input_snapshot import read_analysis_bytes
        case=self.case
        descriptor=capture_inputs(case.root,case.config,case.data/'work/saved-reader')
        out=case.scan('frozen-saved-reader',descriptor)
        source=case.root/'main.c';raw=source.read_bytes();stat=source.stat();observed=[]
        real=workflow.generate
        def render(*args,**kwargs):
            source.write_bytes(b'int live_adversarial_packet_source;\n')
            try:observed.append(read_analysis_bytes(source))
            finally:
                source.write_bytes(raw);os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            return real(*args,**kwargs)
        with patch('ecra.workflow.generate',side_effect=render),contextlib.redirect_stdout(io.StringIO()):
            code=workflow.saved_run(case.root,case.config,render_only=True,_out=out)
        self.assertIn(code,(0,1,2))
        self.assertTrue(observed);self.assertTrue(all(value==raw for value in observed))
        self.assertEqual(source.read_bytes(),raw)

    def test_resume_allows_review_only_config_edits_but_rejects_analysis_changes(self):
        from ecra.common import read_json,write_json
        from ecra.config import load_config
        from ecra.workflow import checked_scan
        from ecra.working_compiler_view import validate
        case=self.case
        descriptor=capture_inputs(case.root,case.config,case.data/'work/review-options')
        out=case.scan('frozen-review-options',descriptor)
        document=read_json(case.config);document['review']['model']='different-model-without-network-call'
        write_json(case.config,document);cfg,config=load_config(case.root,case.config)
        with self.assertRaisesRegex(ValueError,'原编译输入已变化'):
            validate(descriptor,case.root,cfg)
        checked_scan(case.root,out,cfg,config,with_facts=False,_report_projection=True)
        # A supervised review gets a fresh task-owned config path. The saved
        # original config proof stays pinned; runtime options may differ.
        relocated=case.base/'new-review-task/semantics.yaml';write_json(relocated,document)
        review_cfg,review_path=load_config(case.root,relocated)
        checked_scan(case.root,out,review_cfg,review_path,with_facts=False,_report_projection=True)
        from ecra.workflow import saved_run
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(saved_run(case.root,review_path,render_only=True,_out=out),(0,1,2))
        document['analysis']['extra_args']=['-DBUSINESS_CHANGED=1'];write_json(case.config,document)
        cfg,_=load_config(case.root,case.config)
        with self.assertRaisesRegex(ValueError,'分析配置已变化'):
            checked_scan(case.root,out,cfg,config,with_facts=False,_report_projection=True)
