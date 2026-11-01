import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from scripts.native_metrics import directory_size,FileAllocation,PagingRates


@unittest.skipUnless(os.name=='nt','Real Windows filesystem and PDH required')
class NativeMetricsTests(unittest.TestCase):
    def test_actual_file_allocation_and_hard_links_are_not_counted_twice(self):
        with tempfile.TemporaryDirectory(prefix='ECRA 分配采样 ') as folder:
            root=Path(folder);file=root/'payload';file.write_bytes(b'x'*65537);os.link(file,root/'alias')
            result=directory_size(root)
            self.assertEqual((result['files'],result['unique_files'],result['logical_bytes']),(2,1,2*65537))
            self.assertEqual(result['allocated_bytes'],FileAllocation()(file))
            self.assertGreaterEqual(result['allocated_bytes'],65537);self.assertFalse(result['sampling_partial'])

    def test_actual_sparse_file_allocation_is_smaller_than_logical_length_and_disappearing_root_is_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'sparse';file.touch()
            command=subprocess.run(['fsutil','sparse','setflag',str(file)],capture_output=True)
            self.assertEqual(command.returncode,0,command.stderr.decode(errors='replace'))
            with file.open('r+b') as stream:stream.truncate(256*1024**2);stream.seek(128*1024**2);stream.write(b'payload')
            result=directory_size(folder)
            self.assertEqual(result['logical_bytes'],256*1024**2);self.assertLess(result['allocated_bytes'],result['logical_bytes']//16)
            missing=directory_size(Path(folder)/'missing');self.assertTrue(missing['sampling_partial'])

    def test_actual_language_neutral_pdh_paging_counters_warm_up_and_close(self):
        rates=PagingRates()
        try:
            time.sleep(1.1);result=rates.sample()
            self.assertTrue(result['available'],result)
            self.assertEqual(set(result['values']),set(rates.paths))
            self.assertTrue(all(math.isfinite(value) and value>=0 for value in result['values'].values()))
        finally:rates.close();rates.close()


if __name__=='__main__':unittest.main()
