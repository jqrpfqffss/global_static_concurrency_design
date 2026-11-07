import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ecra.studio.review_materials import describe,save,stage,stage_for_task,material_lock,MAX_EDIT
from ecra.studio.review_document_forms import library_forms
from ecra.review_context import review_context_section
from ecra.human_reviews import ReviewConflict
from tests.test_review_document_forms import form

CASE='## CASE-0001｜边界测试\n**分类：** R01\n**识别线索：** 旧值写回\n### 1. 风险机制\nBODY_SENTINEL完整正文\n'
CONTEXT='<!-- 模板不进入提示 -->\nCONTEXT_SENTINEL：任务与中断只按源码核实。\n'

class ReviewMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.config=self.base/'tool/config';self.config.mkdir(parents=True)
        self.data=self.base/'data';self.data.mkdir();self.profile=self.data/'projects/project/profiles/profile.yaml';self.profile.parent.mkdir(parents=True);self.profile.write_text('version: 1\n','utf-8')
        (self.config/'concurrency_cases.md').write_text(CASE,'utf-8');(self.config/'review_context.md').write_text(CONTEXT,'utf-8')
        self.override=patch('ecra.config.CONFIG_HOME',self.config);self.override.start();self.addCleanup(self.override.stop)
    def folder(self,name):
        p=self.base/name;p.mkdir();return p
    def payload(self,text='',name='review_context.md'):
        return dict(name=name,action='context',revision=describe()['documents'][name]['revision'],text=text)

    def test_no_profile_is_needed_and_empty_context_reaches_original_loader(self):
        self.profile.unlink();self.assertEqual(describe()['source'],'config')
        saved=save(self.data,self.payload(''));self.assertTrue(saved['saved'])
        self.assertEqual((self.config/'review_context.md').read_bytes(),b'')
        self.assertEqual(saved['documents']['review_context.md']['effective_chars'],0)
        task=self.folder('blank');stage(self.profile,task)
        self.assertEqual(review_context_section(task/'review_context.md'),'')

    def test_latest_config_only_ignores_but_preserves_all_old_profile_overrides(self):
        custom=self.base/'external.md';custom.write_text('DO_NOT_READ_EXTERNAL','utf-8')
        binding=self.profile.with_suffix('.review-materials.json');binding.write_text(json.dumps(dict(version=1,documents={name:dict(mode='file',path=str(custom)) for name in ['concurrency_cases.md','review_context.md']})),'utf-8')
        self.profile.with_name('review_context.md').write_text('DO_NOT_READ_ADJACENT','utf-8')
        before=binding.read_bytes();task=self.folder('fixed');stage(self.profile,task)
        self.assertEqual((task/'review_context.md').read_text('utf-8'),CONTEXT)
        self.assertEqual((task/'concurrency_cases.md').read_text('utf-8'),CASE)
        self.assertEqual(binding.read_bytes(),before)
        for key in ['path','source','mode','documents']:
            with self.assertRaises(ValueError):save(self.data,dict(self.payload('unsafe'),**{key:'external'}))
        with self.assertRaises(ValueError):save(self.data,dict(self.payload(),name='../elsewhere.md'))

    def test_case_form_updates_only_config_and_backs_up_exact_original(self):
        state=describe()['documents']['concurrency_cases.md'];new=form('新案例','用户填写的丢失更新过程')
        original=(self.config/'concurrency_cases.md').read_bytes()
        result=save(self.data,dict(name='concurrency_cases.md',action='case',revision=state['revision'],case_id=None,form=new))
        self.assertEqual(result['selected_case_id'],'CASE-0002');self.assertEqual(Path(result['backup']).read_bytes(),original)
        self.assertEqual(Path(result['saved_copy']).read_bytes(),(self.config/'concurrency_cases.md').read_bytes())
        self.assertEqual(len(library_forms((self.config/'concurrency_cases.md').read_text('utf-8'))[0]),2)
        self.assertEqual(self.profile.read_text('utf-8'),'version: 1\n')
        self.assertEqual(list(self.profile.parent.glob('*.review-materials.json')),[])

    def test_get_and_save_bom_first_case_preserves_bom_and_crlf(self):
        raw=b'\xef\xbb\xbf'+CASE.replace('\n','\r\n').encode()
        path=self.config/'concurrency_cases.md';path.write_bytes(raw)
        info=describe()['documents']['concurrency_cases.md'];value=info['entries'][0]['form'];value['title']='新名称'
        save(self.data,dict(name='concurrency_cases.md',action='case',revision=info['revision'],case_id='CASE-0001',form=value))
        self.assertEqual(path.read_bytes(),raw.replace('边界测试'.encode(),'新名称'.encode()))

    def test_file_revision_conflict_keeps_concurrent_content_and_refuses_overwrite(self):
        spec=self.payload('my draft');(self.config/'review_context.md').write_text('external edit','utf-8')
        with self.assertRaises(ReviewConflict):save(self.data,spec)
        self.assertEqual((self.config/'review_context.md').read_text('utf-8'),'external edit')

    def test_task_freezes_originals_even_if_config_is_edited_mid_review_and_retry_reuses_snapshot(self):
        with self.assertRaisesRegex(ValueError,'缺少复核资料快照'):stage(self.profile,self.folder('no-snapshot'),retry=True)
        task=self.folder('task');original=stage(self.profile,task);config=task/'semantics.yaml';config.write_text('version: 1\n','utf-8')
        save(self.data,self.payload('工程背景已更新'))
        retry=self.folder('retry');stage(config,retry,retry=True)
        self.assertEqual((retry/'review_context.md').read_text('utf-8'),CONTEXT)
        fresh=self.folder('fresh');stage(self.profile,fresh)
        self.assertIn('工程背景已更新',(fresh/'review_context.md').read_text('utf-8'))
        self.assertEqual(hashlib.sha256((task/'review_context.md').read_bytes()).hexdigest(),original['documents']['review_context.md']['sha256'])
        (task/'review_context.md').write_text('tampered','utf-8')
        with self.assertRaisesRegex(ValueError,'原任务资料快照已变化'):stage(config,self.folder('bad'),retry=True)

    def test_all_review_modes_and_prepare_packets_freeze_only_when_needed(self):
        for mode in ['scan','review','review-failed']:
            self.assertEqual(stage_for_task(self.profile,self.folder(mode),mode,{'review':{'enabled':mode=='scan'}})['status'],'FROZEN')
        self.assertEqual(stage_for_task(self.profile,self.folder('packets'),'scan',{'review':{'prepare_packets':True}})['status'],'FROZEN')
        (self.config/'concurrency_cases.md').unlink()
        for mode in ['scan','precheck']:
            self.assertEqual(stage_for_task(self.profile,self.folder('static-'+mode),mode,{'review':{'enabled':False}})['status'],'NOT_REQUIRED')
        with self.assertRaises(ValueError):stage(self.profile,self.folder('missing-library'))

    def test_absent_optional_context_matches_empty_original_behavior_and_can_be_created_empty(self):
        (self.config/'review_context.md').unlink();task=self.folder('absent');stage(self.profile,task)
        self.assertEqual((task/'review_context.md').read_bytes(),b'')
        self.assertEqual(describe()['documents']['review_context.md']['revision'],'missing')
        save(self.data,self.payload(''))
        self.assertEqual((self.config/'review_context.md').read_bytes(),b'')

    def test_large_non_utf8_and_links_are_not_silently_overwritten(self):
        path=self.config/'review_context.md';path.write_bytes(b'x'*(MAX_EDIT+1));state=describe()['documents']['review_context.md'];self.assertFalse(state['editable'])
        with self.assertRaises(ValueError):save(self.data,self.payload('small'))
        path.write_bytes(b'bad\xff')
        with self.assertRaises(ValueError):save(self.data,self.payload('small'))
        self.assertEqual(path.read_bytes(),b'bad\xff')
        path.unlink();external=self.base/'outside';external.write_text('keep','utf-8')
        try:path.symlink_to(external)
        except OSError:return
        with self.assertRaises(ValueError):save(self.data,dict(name='review_context.md',action='context',revision='missing',text='overwrite'))
        self.assertEqual(external.read_text('utf-8'),'keep')

    def test_unwritable_config_keeps_original_and_backup_without_claiming_saved(self):
        from ecra.studio import review_materials as module
        original=module._atomic
        def fail_target(path,raw):
            if Path(path).parent.resolve()==self.config.resolve():raise PermissionError('synthetic write denial')
            return original(path,raw)
        with patch.object(module,'_atomic',side_effect=fail_target):
            with self.assertRaisesRegex(ValueError,'config 原文件不可写'):save(self.data,self.payload('new'))
        self.assertEqual((self.config/'review_context.md').read_text('utf-8'),CONTEXT)
        self.assertTrue(list((self.data/'settings/review-materials-history').rglob('*.md')))

    def test_editor_and_freezing_share_cross_process_config_lock(self):
        from ecra.storage_activity import DataBusy
        spec=self.payload('new')
        with material_lock():
            with self.assertRaises(DataBusy):save(self.data,spec)

    def test_frozen_config_documents_reach_original_review_prompt_boundary(self):
        from tests.test_case_library import CaseLibraryTests
        fixture=CaseLibraryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        task=self.folder('prompt');stage(self.profile,task)
        fixture.library=task/'concurrency_cases.md'
        rows=fixture.run_review(review_context_path=task/'review_context.md')
        prompt=fixture.prompt();self.assertIn('CONTEXT_SENTINEL',prompt);self.assertNotIn('模板不进入提示',prompt)
        self.assertIn('CASE-0001',prompt);self.assertIn('read 至少读取一条',prompt)
        self.assertEqual(rows[0]['state'],'DONE')

if __name__=='__main__':unittest.main()
