import copy
import unittest

import yaml

from ecra.studio.profile_forms import form_state,merge_form


RAW='''# 工程原始注释
version: 1
project:
  name: "电机控制"
  root: "D:/工程 old"
analysis:
  output: {location: user} # 独立输出
  include_dirs: ["source, comma", 'source two']
  exclude_dirs: []
  cmake:
    generator: "Unix Makefiles" # 高级生成器保留
    build: true
    build_type: Debug
    target: firmware.elf
    configure_args: ['-DFEATURE=ON', '-DTWO=2']
  git_diff: {enabled: false, base_ref: release/old, current_ref: HEAD, include_uncommitted: false}
  future_analysis: {enabled: true, counters: [1, true, -0.0, 0.0]}
contexts:
  - {id: main, kind: MAIN, functions: [main], future_context: "保留"}
future_root:
  multiline: |
    line one
    line two
review: {enabled: false}
'''


class ProfileFormTests(unittest.TestCase):
    def test_only_requested_values_change_and_comments_quotes_unknown_values_and_all_contexts_survive(self):
        expected=yaml.safe_load(RAW);expected['project']['root']='D:/工程 new';expected['analysis']['include_dirs']=[' first directory ','with,comma']
        merged=merge_form(RAW,dict(project_root='D:/工程 new',include_dirs=[' first directory ','with,comma']))
        self.assertEqual(yaml.safe_load(merged['yaml']),expected)
        for comment in ['# 工程原始注释','# 独立输出','# 高级生成器保留']:self.assertIn(comment,merged['yaml'])
        self.assertIn('"Unix Makefiles"',merged['yaml']);self.assertIn("'-DFEATURE=ON'",merged['yaml'])
        self.assertEqual(form_state(merged['yaml'])['form']['include_dirs'],[' first directory ','with,comma'])
        values=yaml.safe_load(merged['yaml'])['analysis']['future_analysis']['counters']
        self.assertIs(type(values[0]),int);self.assertIs(type(values[1]),bool);self.assertEqual(values[2].hex(),'-0x0.0p+0')

    def test_no_form_change_preserves_original_text_byte_for_byte(self):
        for raw in [RAW,RAW.replace('\n','\r\n')]:self.assertEqual(merge_form(raw,{})['yaml'],raw)

    def test_cmake_edit_retains_generator_flags_and_unknown_analysis_fields(self):
        before=yaml.safe_load(RAW);result=merge_form(RAW,dict(variant='Release',target='control.elf',toolchain='D:/tools/arm file.cmake'))
        after=yaml.safe_load(result['yaml']);expected=copy.deepcopy(before)
        expected['analysis']['cmake'].update(build_type='Release',target='control.elf',toolchain_file='D:/tools/arm file.cmake')
        self.assertEqual(after,expected);self.assertIn('高级生成器保留',result['yaml'])

    def test_mode_switch_is_explicit_and_only_replaces_active_build_branch(self):
        result=merge_form(RAW,dict(build_mode='database',target='D:/db commands.json'))
        expected=yaml.safe_load(RAW);expected['analysis'].pop('cmake');expected['analysis']['compile_database']='D:/db commands.json'
        self.assertEqual(yaml.safe_load(result['yaml']),expected);self.assertTrue(result['build_mode_changed'])
        state=form_state(result['yaml']);self.assertEqual((state['form']['build_mode'],state['form']['target']),('database','D:/db commands.json'))
        restored=merge_form(result['yaml'],dict(build_mode='cmake',target='new.elf'))
        self.assertEqual(yaml.safe_load(restored['yaml'])['analysis']['cmake']['target'],'new.elf')

    def test_literal_boolean_like_refs_and_leading_zero_names_keep_string_types(self):
        result=merge_form(RAW,dict(project_name='012',base_ref='on',current_ref='false'))
        after=yaml.safe_load(result['yaml']);self.assertIs(type(after['project']['name']),str)
        self.assertEqual(after['analysis']['git_diff']['base_ref'],'on');self.assertEqual(after['analysis']['git_diff']['current_ref'],'false')

    def test_unrelated_anchors_merge_keys_and_alias_topology_survive(self):
        raw=RAW+'''defaults: &advanced {value: 3, flags: [1, true]}
future_alias: *advanced
future_merge: {<<: *advanced, own: 4}
'''
        result=merge_form(raw,dict(project_name='新显示名'))['yaml'];after=yaml.safe_load(result)
        self.assertIn('&advanced',result);self.assertIn('*advanced',result)
        self.assertIs(after['defaults'],after['future_alias']);self.assertIs(after['defaults']['flags'],after['future_merge']['flags'])

    def test_shared_control_mapping_and_merged_control_mapping_stay_in_advanced_editor(self):
        for raw in ['version: 1\ndefaults: &p {root: "D:/source"}\nproject: *p\nanalysis: {}\n',
            'version: 1\nproject: {root: "D:/source"}\ndefaults: &a {include_dirs: []}\nanalysis: {<<: *a}\n']:
            state=form_state(raw);self.assertFalse(state['editable']);self.assertIn('原文',state['reason'])
            with self.assertRaises(ValueError):merge_form(raw,dict(project_root='D:/next',include_dirs=['src']))

    def test_unsafe_tags_cycles_duplicate_keys_unknown_fields_and_unexpressible_directories_are_not_guessed(self):
        for raw in ['!!python/object/apply:os.system ["echo unexpected"]','a: &a {b: *a}',RAW+'version: 1\n']:
            with self.assertRaises(ValueError):merge_form(raw,dict(project_name='next'))
        with self.assertRaises(ValueError):merge_form(RAW,dict(unknown_form_field='drop nothing'))
        with self.assertRaises(ValueError):merge_form(RAW,dict(include_dirs=['a\nb']))
        with self.assertRaises(ValueError):form_state(RAW.replace('exclude_dirs: []','exclude_dirs: [1]'))


if __name__=='__main__':unittest.main()
