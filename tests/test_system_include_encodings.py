"""GCC header paths must survive their real byte encoding without guessing."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ecra import compilation


class IncludeProbeEncodingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA include codec ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.compiler=self.root/'arm-none-eabi-gcc.exe';self.compiler.touch()
        self.unit=dict(original_arguments=[str(self.compiler),'-c','a.c'],arguments=[],directory=str(self.root))

    def probe(self,body,*,code=0,codecs=('utf-8','cp936')):
        result=subprocess.CompletedProcess([],code,b'',body)
        with patch('ecra.compilation.execute',return_value=result) as execute,patch('ecra.compilation._include_probe_encodings',return_value=codecs):
            answer=compilation.system_includes(self.unit)
            self.assertIs(execute.call_args.kwargs['text'],False)
            self.assertIsNone(execute.call_args.kwargs['encoding']);self.assertIsNone(execute.call_args.kwargs['errors'])
            return answer

    def output(self,line):
        return b'#include <...> search starts here:\n '+line+b'\nEnd of search list.\n'

    def test_windows_acp_path_is_recovered_from_real_directory(self):
        folder=self.root/'中文 头文件';folder.mkdir()
        self.assertEqual(self.probe(self.output('中文 头文件'.encode('cp936'))),[str(folder)])

    def test_utf8_path_remains_utf8_even_with_windows_acp_available(self):
        folder=self.root/'中文 头文件';folder.mkdir()
        self.assertEqual(self.probe(self.output('中文 头文件'.encode('utf-8'))),[str(folder)])

    def test_non_windows_probe_does_not_apply_windows_acp(self):
        with patch('ecra.compilation.os',new=SimpleNamespace(name='posix')):
            self.assertEqual(compilation._include_probe_encodings(),['utf-8'])
        folder=self.root/'unicode include Ω';folder.mkdir()
        self.assertEqual(self.probe(self.output('unicode include Ω'.encode('utf-8')),codecs=('utf-8',)),[str(folder)])

    def test_two_valid_different_directories_are_an_error_not_a_preference(self):
        raw=b'\xc2\xa3'
        for codec in ('utf-8','cp936'):(self.root/raw.decode(codec)).mkdir()
        with self.assertRaisesRegex(ValueError,'编码有歧义'):
            self.probe(self.output(raw))

    def test_bad_path_cannot_be_silently_dropped_from_other_valid_paths(self):
        (self.root/'valid').mkdir()
        with self.assertRaisesRegex(ValueError,'无法无损恢复'):
            self.probe(self.output(b'valid\n \xff'))

    def test_failed_acp_output_keeps_phase_exit_code_and_readable_message(self):
        message='致命错误：头文件探测失败'
        with self.assertRaisesRegex(ValueError,'退出码：7') as caught:
            self.probe(message.encode('cp936'),code=7)
        self.assertIn(message,str(caught.exception));self.assertNotIn('\ufffd',str(caught.exception))

    def test_undecodable_failure_keeps_bytes_instead_of_replacement(self):
        with self.assertRaisesRegex(ValueError,'原始stderr字节') as caught:
            self.probe(b'bad bytes \xff',code=2)
        self.assertIn('ff',str(caught.exception));self.assertNotIn('\ufffd',str(caught.exception))

    def test_incomplete_search_output_is_not_a_success(self):
        (self.root/'valid').mkdir()
        with self.assertRaisesRegex(ValueError,'缺少完整'):
            self.probe(b'#include <...> search starts here:\n valid\n')


class GuardedOutputOptionTests(unittest.TestCase):
    def test_only_exact_binary_protocol_is_admitted_as_extra_options(self):
        from ecra.guarded_cmake import BuildExecutor
        executor=object.__new__(BuildExecutor)
        for options in [dict(text=False),dict(text=False,encoding='utf-8',errors=None),
                        dict(text=False,encoding=None,errors='replace'),dict(text=0,encoding=None,errors=None),
                        dict(text=True,encoding=None,errors=None),dict(text=False,encoding=None,errors=None,shell=True)]:
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'未证明的子进程选项'):
                executor(['unused'],**options)


@unittest.skipUnless(os.name=='nt','Actual Windows ACP GCC required')
class RealChineseGccHeaderTests(unittest.TestCase):
    def test_actual_physical_chinese_toolchain_and_stdint_parse(self):
        import ctypes
        from ecra.config import load_config
        from ecra.extract import Extractor
        from ecra.portable import tool_path
        compiler=Path(os.environ.get('ECRA_TEST_CHINESE_GCC') or tool_path('arm-none-eabi-gcc')).resolve()
        if not compiler.is_file() or str(compiler).isascii():self.skipTest('Requires actual Chinese-path ARM GCC')
        with tempfile.TemporaryDirectory(prefix='ECRA real stdint ') as folder:
            root=Path(folder).resolve();source=root/'main.c'
            source.write_text('#include <stdint.h>\nuint32_t shared;\nint main(void){return shared;}\n','utf-8')
            config=root/'semantics.yaml';config.write_text(json.dumps(dict(version=1,project=dict(root=str(root)),analysis=dict(auto_system_includes=True),review=dict(enabled=False))),'utf-8')
            cfg,_=load_config(root,config)
            unit=compilation.normalize(dict(directory=str(root),file=str(source),arguments=[str(compiler),'-mcpu=cortex-m0','-mthumb','-c',str(source),'-o',str(root/'main.o')]),root,cfg['analysis'])
            paths=compilation.system_includes(unit)
            self.assertTrue(paths);self.assertTrue(all(Path(p).is_dir() for p in paths));self.assertTrue(any((Path(p)/'stdint.h').is_file() for p in paths))
            unit['arguments'].extend(compilation.system_include_args(paths))
            old_directory=Path.cwd()
            try:facts=Extractor(dict(root=str(root),unit=unit,config=cfg)).run()
            finally:os.chdir(old_directory)
            self.assertEqual(facts['parse_status'],'PARSED',facts['diagnostics'])
            self.assertIn('shared',[v['name'] for v in facts['variables']])


if __name__=='__main__':unittest.main()
