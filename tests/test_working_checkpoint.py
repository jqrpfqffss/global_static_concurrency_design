"""Recovery admission: no live fallback for damaged complete CMake inputs."""
import tempfile
from pathlib import Path
import unittest

from ecra.common import read_json,write_json
from ecra.report_package import sha256
from ecra.working_checkpoint import retry_inputs


class WorkingCheckpointTests(unittest.TestCase):
    def setUp(self):
        home=tempfile.TemporaryDirectory();self.addCleanup(home.cleanup);self.home=Path(home.name).resolve()
        self.data=self.home/'data';self.root=self.home/'firmware';self.root.mkdir()
        self.old=self.data/'work/tasks'/('a'*32);self.new=self.data/'work/tasks'/('b'*32)
        self.old.mkdir(parents=True);self.new.mkdir()
        cfg=dict(version=1,project=dict(root=str(self.root)),analysis=dict(compile_database='auto',
            cmake=dict(generator='Ninja'),git_diff=dict(enabled=True,include_uncommitted=True,base_ref='HEAD')),
            review=dict(enabled=False))
        write_json(self.old/'semantics.yaml',cfg);(self.new/'semantics.yaml').write_bytes((self.old/'semantics.yaml').read_bytes())
        self.task=dict(id='a'*32,state='INTERRUPTED',mode='scan',project_root=str(self.root),profile_revision=sha256(self.old/'semantics.yaml'))
        write_json(self.old/'task.json',self.task);write_json(self.new/'retry-source.json',dict(source_task='a'*32))

    def reuse(self):return retry_inputs(self.data,self.new,self.new/'semantics.yaml','scan',lambda _:None)

    def test_incomplete_capture_can_be_started_again(self):
        self.assertIsNone(self.reuse());self.assertFalse((self.new/'reused-working-inputs.json').exists())

    def test_complete_but_different_engine_is_rejected_instead_of_recaptured(self):
        plan=self.old/'fixed-inputs/capture-plan.json';plan.parent.mkdir()
        write_json(plan,dict(engine_digest='different',effective_analysis_digest='different'))
        with self.assertRaisesRegex(ValueError,'实现或有效配置'):self.reuse()
        self.assertFalse((self.new/'reused-working-inputs.json').exists())

    def test_task_state_identity_mode_and_config_bytes_are_bound(self):
        for changed in [dict(state='COMPLETE'),dict(id='c'*32),dict(mode='precheck'),dict(profile_revision='changed')]:
            with self.subTest(changed=changed):
                write_json(self.old/'task.json',dict(self.task,**changed))
                with self.assertRaisesRegex(ValueError,'恢复任务状态'):self.reuse()
        write_json(self.old/'task.json',self.task)
        with (self.new/'semantics.yaml').open('ab') as stream:stream.write(b'\n')
        with self.assertRaisesRegex(ValueError,'原配置字节'):self.reuse()

    def test_traversal_and_foreign_task_paths_are_rejected(self):
        write_json(self.new/'retry-source.json',dict(source_task='../foreign'))
        with self.assertRaisesRegex(ValueError,'受控任务'):self.reuse()

    def test_existing_database_retry_has_no_new_cmake_checkpoint_requirement(self):
        cfg=read_json(self.new/'semantics.yaml');del cfg['analysis']['cmake'];cfg['analysis']['compile_database']='compile_commands.json'
        write_json(self.new/'semantics.yaml',cfg)
        self.assertIsNone(self.reuse())
