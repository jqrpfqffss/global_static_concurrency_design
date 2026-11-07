import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.studio.review_materials import describe,save,stage,stage_for_task,inspect_document,MAX_EDIT
from ecra.review_context import review_context_section
from ecra.case_library import case_library_section
from ecra.human_reviews import ReviewConflict

CASE='## CASE-0001｜边界测试\n**分类：** R01\n**识别线索：** 旧值写回\nBODY_SENTINEL完整正文\n'
CONTEXT='<!-- 模板不进入提示 -->\nCONTEXT_SENTINEL：任务与中断只按源码核实。\n'


class ReviewMaterialsTests(unittest.TestCase):
    def test_absent_optional_default_context_matches_original_empty_context_behavior(self):
        (self.config/'review_context.md').unlink()
        info=describe(self.profile)['documents']['review_context.md'];self.assertTrue(info['available']);self.assertEqual(info['effective_chars'],0)
        task=self.folder('optional');stage(self.profile,task)
        self.assertEqual(review_context_section(task/'review_context.md'),'')
        with self.assertRaises(ValueError):save(self.data,self.profile,self.payload(**{'review_context.md':{'mode':'file','path':str(self.base/'missing.md')}}))

    def test_staged_documents_reach_actual_original_review_prompt_boundary(self):
        from tests.test_case_library import CaseLibraryTests
        fixture=CaseLibraryTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        task=self.folder('engine-boundary');stage(self.profile,task)
        fixture.library=task/'concurrency_cases.md'
        fixture.run_review(review_context_path=task/'review_context.md')
        self.assertTrue(fixture.calls)
        prompt=fixture.prompt();self.assertIn('CONTEXT_SENTINEL',prompt);self.assertIn('CASE-0001',prompt)
        self.assertIn('第七步',prompt);self.assertIn('第八步',prompt)
        self.assertIn(hashlib.sha256(CASE.encode()).hexdigest(),prompt)
        self.assertTrue(any('BODY_SENTINEL' in path.read_text('utf-8') for path in (fixture.out/'review/case-library').glob('*.md')))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.data=self.base/'data';self.config=self.base/'config';self.config.mkdir()
        self.profile=self.data/'projects'/'project'/'profiles'/'profile.yaml';self.profile.parent.mkdir(parents=True);self.profile.write_text('version: 1\n','utf-8')
        (self.config/'concurrency_cases.md').write_bytes(CASE.encode('utf-8'));(self.config/'review_context.md').write_bytes(CONTEXT.encode('utf-8'))
        self.patch=patch('ecra.config.CONFIG_HOME',self.config);self.patch.start();self.addCleanup(self.patch.stop)

    def folder(self,name):
        folder=self.base/name;folder.mkdir();return folder

    def payload(self,**changes):
        value={'revision':describe(self.profile)['revision'],'documents':{'concurrency_cases.md':{'mode':'automatic'},'review_context.md':{'mode':'automatic'}}}
        value['documents'].update(changes);return value

    def test_default_documents_reach_unchanged_engine_index_body_and_context_loader(self):
        status=describe(self.profile);self.assertEqual(status['documents']['concurrency_cases.md']['cases'],1)
        folder=self.folder('task');result=stage(self.profile,folder)
        self.assertEqual((folder/'concurrency_cases.md').read_bytes(),(self.config/'concurrency_cases.md').read_bytes())
        self.assertEqual(result['documents']['review_context.md']['sha256'],hashlib.sha256(CONTEXT.encode()).hexdigest())
        context=review_context_section(folder/'review_context.md');self.assertIn('CONTEXT_SENTINEL',context);self.assertNotIn('模板不进入提示',context)
        messages=[];prompt,paths=case_library_section(folder/'concurrency_cases.md',folder/'review',messages.append)
        self.assertFalse(messages);self.assertIn('CASE-0001',prompt);self.assertIn('BODY_SENTINEL',paths[0].read_text('utf-8'))
        self.assertIn('read 至少读取一条',prompt)

    def test_profile_managed_copy_is_isolated_versioned_and_frozen_before_later_edits(self):
        original=(self.config/'review_context.md').read_bytes()
        result=save(self.data,self.profile,self.payload(**{'review_context.md':{'mode':'managed','content':'工程A背景'}}))
        self.assertTrue(result['saved']);old=self.folder('old-task');stage(self.profile,old)
        save(self.data,self.profile,self.payload(**{'review_context.md':{'mode':'managed','content':'工程A新背景'}}))
        self.assertEqual((old/'review_context.md').read_text('utf-8'),'工程A背景')
        new=self.folder('new-task');stage(self.profile,new);self.assertEqual((new/'review_context.md').read_text('utf-8'),'工程A新背景')
        other=self.profile.with_name('other.yaml');other.write_text('version: 1\n','utf-8');self.assertEqual(describe(other)['documents']['review_context.md']['text'],CONTEXT)
        self.assertEqual((self.config/'review_context.md').read_bytes(),original)
        self.assertTrue(list((self.profile.parent/'review-materials-history').glob('*.json')))

    def test_explicit_file_refresh_legacy_precedence_and_builtin_override(self):
        adjacent=self.profile.with_name('concurrency_cases.md');adjacent.write_text(CASE.replace('0001','0002'),'utf-8')
        self.assertIn('0002',describe(self.profile)['documents']['concurrency_cases.md']['text'])
        save(self.data,self.profile,self.payload(**{'concurrency_cases.md':{'mode':'builtin'}}))
        self.assertIn('0001',describe(self.profile)['documents']['concurrency_cases.md']['text'])
        custom=self.base/'自选 案例.md';custom.write_text(CASE,'utf-8')
        save(self.data,self.profile,self.payload(**{'concurrency_cases.md':{'mode':'file','path':str(custom)}}))
        custom.write_text(CASE.replace('0001','0003'),'utf-8');task=self.folder('latest');stage(self.profile,task)
        self.assertIn('0003',(task/'concurrency_cases.md').read_text('utf-8'))

    def test_missing_explicit_source_and_stale_revision_fail_without_overwriting_binding(self):
        saved=save(self.data,self.profile,self.payload());path=self.profile.with_suffix('.review-materials.json');before=path.read_bytes()
        bad=self.payload(**{'concurrency_cases.md':{'mode':'file','path':str(self.base/'missing.md')}})
        with self.assertRaises(ValueError):save(self.data,self.profile,bad)
        self.assertEqual(path.read_bytes(),before)
        with self.assertRaises(ReviewConflict):save(self.data,self.profile,dict(self.payload(),revision='stale'))
        (self.config/'concurrency_cases.md').unlink()
        with self.assertRaisesRegex(ValueError,'无法冻结复核资料'):stage(self.profile,self.folder('missing-task'))

    def test_every_review_entry_stages_docs_but_precheck_and_static_scan_do_not_require_them(self):
        for mode in ['scan','review','review-failed']:
            result=stage_for_task(self.profile,self.folder(mode),mode,{'review':{'enabled':mode=='scan'}})
            self.assertEqual(result['status'],'FROZEN')
        self.assertEqual(stage_for_task(self.profile,self.folder('packets'),'scan',{'review':{'enabled':False,'prepare_packets':True}})['status'],'FROZEN')
        (self.config/'concurrency_cases.md').unlink()
        self.assertEqual(stage_for_task(self.profile,self.folder('precheck'),'precheck',{'review':{'enabled':True}})['status'],'NOT_REQUIRED')
        self.assertEqual(stage_for_task(self.profile,self.folder('static'),'scan',{'review':{'enabled':False}})['status'],'NOT_REQUIRED')

    def test_retry_reuses_original_snapshot_and_detects_tampering(self):
        old=self.folder('old');stage(self.profile,old);config=old/'semantics.yaml';config.write_text('version: 1\n','utf-8')
        (self.config/'review_context.md').write_text('changed global','utf-8')
        new=self.folder('retry');stage(config,new,retry=True);self.assertEqual((new/'review_context.md').read_text('utf-8'),CONTEXT)
        (old/'review_context.md').write_text('tampered','utf-8')
        with self.assertRaisesRegex(ValueError,'原任务资料快照已变化'):stage(config,self.folder('bad-retry'),retry=True)

    def test_managed_hash_template_empty_large_preview_and_link_boundaries(self):
        (self.config/'review_context.md').write_text('<!-- 只是模板 -->','utf-8')
        self.assertEqual(describe(self.profile)['documents']['review_context.md']['effective_chars'],0)
        saved=save(self.data,self.profile,self.payload(**{'review_context.md':{'mode':'managed','content':'owned'}}))
        path=Path(saved['documents']['review_context.md']['path']);path.write_text('changed','utf-8')
        self.assertFalse(describe(self.profile)['documents']['review_context.md']['available'])
        with self.assertRaises(ValueError):stage(self.profile,self.folder('tampered'))
        large=self.base/'large.md';large.write_bytes(b'x'*(MAX_EDIT+1));info=inspect_document(large,'concurrency_cases.md')
        self.assertTrue(info['available']);self.assertTrue(info['preview_only']);self.assertFalse(info['editable']);self.assertEqual(info['bytes'],MAX_EDIT+1)
        link=self.base/'link.md'
        try:link.symlink_to(large)
        except OSError:return
        self.assertFalse(inspect_document(link,'concurrency_cases.md')['available'])


if __name__=='__main__':unittest.main()
