import tempfile
from pathlib import Path
import tracemalloc
import unittest

from ecra.report import AtomicLines


class StreamingReportTests(unittest.TestCase):
    def test_streamed_output_matches_previous_join_bytes(self):
        for lines in ([], [''], ['first'], ['first',''], ['', '中文😀', 'a\nb', '', 'last']):
            with self.subTest(lines=lines), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);expected=root/'expected.md';actual=root/'actual.md'
                expected.write_text('\n'.join(lines), encoding='utf-8')
                with AtomicLines(actual) as output:
                    for line in lines:output.append(line)
                self.assertEqual(actual.read_bytes(),expected.read_bytes())

    def test_memory_does_not_grow_with_complete_report_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.md'
            tracemalloc.start()
            try:
                with AtomicLines(path) as output:
                    for index in range(2000):output.append(str(index)+'完整证据 '*1024)
                _,peak=tracemalloc.get_traced_memory()
            finally:tracemalloc.stop()
            self.assertGreater(path.stat().st_size,20*1024*1024)
            self.assertLess(peak,1024*1024)

    def test_failure_preserves_previous_complete_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.md';path.write_text('历史完整证据',encoding='utf-8')
            with self.assertRaises(MemoryError):
                with AtomicLines(path) as output:
                    output+=['部分新内容','尚未完成']
                    self.assertEqual(path.read_text(encoding='utf-8'),'历史完整证据')
                    raise MemoryError('controlled failure')
            self.assertEqual(path.read_text(encoding='utf-8'),'历史完整证据')
            self.assertFalse(path.with_suffix('.md.tmp').exists())

    def test_explicit_finish_and_context_exit_publish_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.md'
            with AtomicLines(path,['头部','']) as output:
                output+=['完整正文','尾部'];output.finish()
                self.assertEqual(path.read_text(encoding='utf-8'),'头部\n\n完整正文\n尾部')
                with self.assertRaises(ValueError):output.append('禁止修改已发布文件')


if __name__=='__main__':unittest.main()
