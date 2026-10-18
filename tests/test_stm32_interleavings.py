"""Independent execution checks for the new real-firmware benchmark fixtures."""
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.replay_stm32_interleavings import replay


class Stm32InterleavingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('gcc') or shutil.which('clang'), 'Native C compiler required')
    def test_actual_c_fixtures_exhibit_errors_and_block_safe_interleavings(self):
        compiler=shutil.which('gcc') or shutil.which('clang')
        with tempfile.TemporaryDirectory(prefix='ecra replay ') as directory:
            rows=replay(Path(directory),compiler)
        self.assertEqual(len(rows),14)
        self.assertTrue(all(r['passed'] for r in rows))


if __name__=='__main__':unittest.main()
