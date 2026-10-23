"""A retained completed report must keep its quality page and its navigation."""
import contextlib
import io
import unittest

from ecra import cli


class ReportArchiveTests(unittest.TestCase):
    from tests.test_ecra import ProjectTest as _fixture
    setUp=_fixture.setUp
    project=_fixture.project

    def test_following_scan_retains_the_previous_classification_quality_page(self):
        self.project({'app.c':'int shared;void ISR(void){shared++;}void Task(void){shared++;}'})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run(self.root,no_review=True),2)
        output=self.root/'.ecra'
        quality=output/'classification_quality.html'
        original=quality.read_bytes()
        self.assertIn(b'classification_quality.html',(output/'index.html').read_bytes())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run(self.root,no_review=True),2)
        snapshots=list((output/'snapshots').iterdir())
        self.assertEqual(len(snapshots),1)
        self.assertTrue((snapshots[0]/'classification_quality.html').is_file(),
                        'Archived index links to a quality page that was not retained')
        self.assertEqual((snapshots[0]/'classification_quality.html').read_bytes(),original)
