"""Library contracts must generate pointee accesses before avoiding escapes."""

import unittest

from tests import test_ecra as fixtures


class StandardLibrarySemanticsTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def test_strcpy_through_global_pointer_writes_buffer_in_irq(self):
        source = '''
            char *strcpy(char *, const char *);
            static char buf[8];
            static char *gp;
            void TIM2_IRQHandler(void) { strcpy(gp, "x"); }
            int main(void) { gp = buf; return buf[0]; }
        '''
        cfg = self.project({'main.c': source}, contexts=[
            dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        buffer = [row for row in facts['variables'] if row['name'].startswith('buf')
                  and row.get('static_classification') in {'SUSPECT', 'UNKNOWN'}]
        self.assertTrue(buffer, [(row['name'], row.get('static_classification'))
                                 for row in facts['variables']])
        self.assertTrue(any(access.get('via_api') == 'strcpy'
                            and access['access_kind'] == 'WRITE'
                            and access.get('contexts')
                            for row in buffer for access in row['accesses']))


if __name__ == '__main__':
    unittest.main()
