import copy
import unittest

import yaml

from ecra.studio.profile_forms import form_state,merge_form


RAW='''# 原始入口与高级规则
version: 1
project: {name: 工程, root: "D:/firmware"}
analysis: {compile_database: auto, include_dirs: [], exclude_dirs: []}
contexts:
  # 入口列表注释
  - id: main # ID注释
    kind: MAIN
    functions: [main, main] # 函数注释
    regex: ['^start_.*']
    enabled: true
    future: &advanced {value: "on", numbers: [1, true, -0.0]}
  - id: timer # 定时器注释
    kind: ISR
    functions:
      - TIM_IRQHandler # 函数项注释
    priority: 3
    reentrant: false
future_alias: *advanced
concurrency: [{contexts: [main, timer]}]
'''


class ContextFormTests(unittest.TestCase):
    def test_read_uses_actual_contexts_without_defaults_or_text_rewrite(self):
        state=form_state(RAW)
        self.assertTrue(state['contexts_editable'])
        self.assertEqual(state['form']['contexts'],[
            dict(origin_id='main',id='main',kind='MAIN',functions=['main','main']),
            dict(origin_id='timer',id='timer',kind='ISR',functions=['TIM_IRQHandler'])])
        for raw in [RAW,RAW.replace('\n','\r\n')]:self.assertEqual(merge_form(raw,{})['yaml'],raw)
        self.assertEqual(form_state('project: {}\nanalysis: {}\n')['form']['contexts'],[])

    def test_changed_fields_preserve_advanced_values_aliases_comments_and_order(self):
        for raw in [RAW,RAW.replace('\n','\r\n')]:
            rows=form_state(raw)['form']['contexts'];rows[1].update(id='irq_timer',kind='IRQ',functions=['ISR New','IRQ,2','IRQ,2'])
            rows.append(dict(origin_id=None,id='control_task',kind='TASK',functions=['ControlTask']))
            expected=yaml.safe_load(raw);expected['contexts'][1].update(id='irq_timer',kind='IRQ',functions=['ISR New','IRQ,2','IRQ,2'])
            expected['contexts'].append(dict(id='control_task',kind='TASK',functions=['ControlTask']))
            result=merge_form(raw,dict(contexts=rows));after=yaml.safe_load(result['yaml'])
            self.assertEqual(after,expected)
            self.assertIs(after['future_alias'],after['contexts'][0]['future'])
            for marker in ['# 原始入口与高级规则','# 入口列表注释','# ID注释','# 函数注释','# 定时器注释','# 函数项注释',"'^start_.*'",'"on"']:
                self.assertIn(marker,result['yaml'])
            self.assertEqual(list(after['contexts'][1]),list(expected['contexts'][1]))
            self.assertEqual(after['contexts'][0]['future']['numbers'][2].hex(),'-0x0.0p+0')
            self.assertEqual(result['changed_paths'],['contexts'])
            if '\r\n' in raw:self.assertNotIn('\n',result['yaml'].replace('\r\n',''))
            # Advanced references are NOT guessed/renamed behind the user's back.
            self.assertEqual(after['concurrency'][0]['contexts'],['main','timer'])

    def test_explicit_removal_removes_whole_selected_row_and_keeps_other_row(self):
        rows=form_state(RAW)['form']['contexts'];result=merge_form(RAW,dict(contexts=rows[:1]))['yaml']
        expected=yaml.safe_load(RAW);expected['contexts'].pop()
        self.assertEqual(yaml.safe_load(result),expected)
        for marker in ['# 入口列表注释','# ID注释','# 函数注释']:self.assertIn(marker,result)

    def test_shared_context_containers_and_merge_keys_disable_only_context_editing(self):
        examples=[
            'contexts: &rows [{id: main, kind: MAIN, functions: [main]}]\nother: *rows\n',
            'contexts: [&row {id: main, kind: MAIN, functions: [main]}]\nother: *row\n',
            'contexts: [{id: main, kind: MAIN, functions: &funcs [main]}]\nother: *funcs\n',
            'default: &row {id: main, kind: MAIN, functions: [main]}\ncontexts: [{<<: *row}]\n',
            'contexts: [{id: main, kind: MAIN, functions: [main]}, {id: main, kind: ISR}]\n',
            'contexts: [{id: main, kind: [MAIN]}]\n',
            'contexts: [{id: main, kind: MAIN, functions: [""]}]\n',
            'contexts: [{id: "line\\nnext", kind: MAIN}]\n',
        ]
        for fragment in examples:
            with self.subTest(fragment=fragment):
                raw='project: {name: old}\nanalysis: {}\n'+fragment
                state=form_state(raw);self.assertTrue(state['editable']);self.assertFalse(state['contexts_editable'])
                self.assertTrue(state['contexts_reason']);expected=yaml.safe_load(raw);expected['project']['name']='new'
                self.assertEqual(yaml.safe_load(merge_form(raw,dict(project_name='new'))['yaml']),expected)
                with self.assertRaises(ValueError):merge_form(raw,dict(contexts=[]))

    def test_forged_origins_duplicates_invalid_types_and_reorder_are_rejected(self):
        original=form_state(RAW)['form']['contexts']
        bad=[]
        for field,value in [('origin_id','unknown'),('origin_id',[]),('id',''),('id','line\nnext'),('kind','invented'),('kind',[]),('functions',['']),('functions',['a\nb']),('functions',[1])]:
            rows=copy.deepcopy(original);rows[0][field]=value;bad.append(rows)
        rows=copy.deepcopy(original);rows[1]['id']='main';bad.append(rows)
        rows=copy.deepcopy(original);rows[1]['origin_id']='main';bad.append(rows)
        rows=copy.deepcopy(original);rows[0]['unknown']='value';bad.append(rows)
        bad.extend([original[::-1],[dict(origin_id=None,id='new',kind='TASK',functions=[])]+original,{},None])
        for rows in bad:
            with self.subTest(rows=rows),self.assertRaises(ValueError):merge_form(RAW,dict(contexts=rows))

    def test_unchanged_context_projection_does_not_add_missing_functions_or_defaults(self):
        raw='project: {}\nanalysis: {}\ncontexts: [{id: main, kind: MAIN, regex: ["^Main"]}]\n'
        rows=form_state(raw)['form']['contexts'];result=merge_form(raw,dict(contexts=rows))['yaml']
        self.assertEqual(yaml.safe_load(result),yaml.safe_load(raw));self.assertNotIn('functions:',result)
        self.assertNotIn('auto_system_includes:',result)

    def test_system_header_control_preserves_engine_defaults_and_boolean_types(self):
        self.assertEqual(form_state(RAW)['form']['system_headers'],'default')
        self.assertNotIn('auto_system_includes',yaml.safe_load(merge_form(RAW,dict(project_name='new'))['yaml'])['analysis'])
        raw=RAW
        for choice,wanted in [('on',True),('off',False),('default',None)]:
            result=merge_form(raw,dict(system_headers=choice))['yaml'];expected=yaml.safe_load(raw)
            if wanted is None:expected['analysis'].pop('auto_system_includes')
            else:expected['analysis']['auto_system_includes']=wanted
            self.assertEqual(yaml.safe_load(result),expected)
            self.assertEqual(form_state(result)['form']['system_headers'],choice);raw=result
        with self.assertRaises(ValueError):merge_form(RAW,dict(system_headers='guess'))
        with self.assertRaises(ValueError):form_state(RAW.replace('analysis: {','analysis: {auto_system_includes: "true", '))

    def test_unexpressible_empty_directory_and_multiline_text_do_not_silently_disappear(self):
        for raw in [RAW.replace('include_dirs: []','include_dirs: [""]'),RAW.replace('name: 工程','name: "first\\nsecond"')]:
            with self.assertRaises(ValueError):form_state(raw)
        with self.assertRaises(ValueError):merge_form(RAW,dict(include_dirs=['']))


if __name__=='__main__':unittest.main()
