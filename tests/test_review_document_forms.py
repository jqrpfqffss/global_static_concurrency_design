from pathlib import Path
import unittest
from ecra.studio.review_document_forms import library_forms,update_library,context_text,context_markdown,METADATA


def form(title='用户案例',description='中断发生在读值与写回之间'):
    return dict(title=title,metadata={k:'' for k in METADATA},sections={str(n):description if n==1 else '' for n in range(1,9)})


class ReviewDocumentFormsTests(unittest.TestCase):
    def test_all_26_original_cases_roundtrip_byte_for_byte_and_template_is_not_a_case(self):
        raw=(Path(__file__).parents[1]/'config/concurrency_cases.md').read_bytes();text=raw.decode('utf-8')
        cases,_=library_forms(text);self.assertEqual(len(cases),26)
        for case in cases:
            self.assertTrue(case['editable'],case['id'])
            self.assertEqual(update_library(text,case['id'],case['form'])[0].encode('utf-8'),raw)
            self.assertNotIn('```',case['form']['sections']['2'])

    def test_new_case_gets_unique_number_plain_text_fields_and_automatic_code_fence(self):
        original='# 库\n## CASE-0001｜已有\n### 1. 风险机制\n已知事实\n\n### 后续追加模板\n```markdown\n## CASE-0002｜模板\n```\n'
        value=form();value['sections']['2']='void IRQ(void) { value++; }\n// ``` inside code'
        value['metadata']['分类']='中断共享数据';value['metadata']['识别线索']='变量 value'
        updated,ident=update_library(original,None,value)
        self.assertEqual(ident,'CASE-0002');self.assertIn('````c',updated)
        cases,_=library_forms(updated);self.assertEqual(len(cases),2)
        self.assertEqual(cases[1]['form']['sections']['2'],value['sections']['2'])
        self.assertEqual(cases[1]['form']['metadata']['分类'],'中断共享数据')
        self.assertTrue(updated.endswith(original[original.index('### 后续追加模板'):]))

    def test_only_title_and_description_are_enough_for_original_case_index_without_format_warnings(self):
        from ecra.case_library import case_index
        updated,_=update_library('',None,form('偶发丢更新','已观察到值回退，具体原因仍待核实'))
        warnings=[];index=case_index(updated,warnings.append)
        self.assertEqual(warnings,[]);self.assertIn('偶发丢更新',index)
        entry=library_forms(updated)[0][0]
        self.assertEqual(entry['form']['metadata']['分类'],'用户补充（待分类）')
        self.assertEqual(entry['form']['metadata']['确认状态'],'待核实')

    def test_editing_one_field_retains_unknown_content_bom_crlf_and_other_cases(self):
        text='\ufeff# 库\r\n## CASE-0001｜旧标题\r\n**分类：** R01  \r\n**自定义字段：** 必须保留\r\n### 1. 风险机制\r\n旧说明\r\n\r\n## CASE-0002｜其他\r\n### 1. 风险机制\r\n其他说明\r\n'
        cases,_=library_forms(text);value=cases[0]['form'];value['sections']['1']='用户新说明'
        updated,_=update_library(text,'CASE-0001',value)
        self.assertEqual(updated,text.replace('旧说明','用户新说明'))
        value['metadata']['分类']='用户填写的新分类'
        updated,_=update_library(text,'CASE-0001',value)
        self.assertIn('**自定义字段：** 必须保留\r\n',updated)
        self.assertIn('**分类：** 用户填写的新分类',updated)

    def test_bom_directly_before_first_case_or_code_fence_preserves_identity(self):
        text='\ufeff## CASE-0001｜案例\r\n### 1. 风险机制\r\n原说明\r\n'
        cases,_=library_forms(text);self.assertEqual(len(cases),1)
        value=cases[0]['form'];value['title']='新名称'
        self.assertEqual(update_library(text,'CASE-0001',value)[0],text.replace('案例','新名称',1))
        fenced='\ufeff```markdown\n## CASE-9999｜模板\n```\n'+text[1:]
        self.assertEqual([c['id'] for c in library_forms(fenced)[0]],['CASE-0001'])

    def test_unknown_sections_remain_when_known_section_changes_and_unclosed_code_is_read_only(self):
        text='## CASE-0001｜案例\n### 1. 风险机制\n旧说明\n### 9. 外部补充\n必须保留\n'
        cases,_=library_forms(text);value=cases[0]['form'];value['sections']['1']='新说明'
        updated,_=update_library(text,'CASE-0001',value)
        self.assertEqual(updated,text.replace('旧说明','新说明'))
        broken=text+'```c\nunterminated\n'
        cases,_=library_forms(broken);self.assertFalse(cases[0]['editable'])

    def test_plain_text_structural_markers_cannot_create_phantom_cases_or_sections(self):
        from ecra.case_library import case_index
        value=form(description='原文\n## CASE-9999｜只是说明\n### 3. 不是章节\n分类：只是正文，不是分类字段\n识别线索：也是正文\n```\n文字\n```')
        updated,_=update_library('',None,value);cases,_=library_forms(updated)
        self.assertEqual(len(cases),1);self.assertEqual(cases[0]['form']['sections']['1'],value['sections']['1'])
        index=case_index(updated,lambda message:None)
        self.assertIn('用户补充（待分类）',index);self.assertNotIn('只是正文，不是分类字段',index)

    def test_original_bold_and_plain_metadata_styles_update_existing_field_without_duplicates(self):
        for metadata in ['**分类：** R01\n**识别线索：** old','**分类**：R01\n**识别线索**：old','分类：R01\n识别线索：old']:
            text='## CASE-0001｜案例\n'+metadata+'\n### 1. 风险机制\n说明\n'
            case=library_forms(text)[0][0];value=case['form'];value['metadata']['分类']='R02'
            self.assertEqual(update_library(text,'CASE-0001',value)[0],text.replace('R01','R02'))

    def test_duplicate_ids_and_invalid_form_are_refused_without_a_rewrite(self):
        text='## CASE-0001｜一\n### 1. 风险机制\n说明\n## CASE-0001｜二\n'
        with self.assertRaises(ValueError):update_library(text,'CASE-0001',form())
        for invalid in [dict(form(),title=''),dict(form(),title='a\nb'),dict(form(),sections={}),dict(form(),metadata={'path':'elsewhere'})]:
            with self.assertRaises(ValueError):update_library('',None,invalid)

    def test_context_empty_whitespace_and_template_all_mean_no_extra_background(self):
        for value in ['', ' \n\t', '<!--模板说明-->']:
            self.assertEqual(context_text(value),'')
        self.assertEqual(context_markdown(' \n'), '')
        value='仅在启动阶段初始化。\n实际优先级仍以源码为准。'
        self.assertEqual(context_text(context_markdown(value)),value)


if __name__=='__main__':unittest.main()
