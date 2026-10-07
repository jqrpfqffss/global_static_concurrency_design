"""A classifier change must invalidate a saved scan before review resumes."""

import unittest
from unittest.mock import patch

from ecra.workflow import engine_digest


class EngineDigestCoverageTests(unittest.TestCase):
    def test_digest_includes_classification_and_phase_modules(self):
        seen = []

        def record(path):
            seen.append(path.name)
            return path.name

        with patch('ecra.workflow.file_digest', side_effect=record):
            engine_digest()
        self.assertTrue({'evidence.py', 'initialization.py', 'diagnostics.py',
                         'extract.py', 'points_to.py'} <= set(seen))


if __name__ == '__main__':
    unittest.main()
