"""A buffer address written to a peripheral register cannot be called read-only."""

import unittest

from tests import test_ecra as fixtures


class RegisterAddressPublishTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def test_direct_mmio_address_publication_retains_hardware_gap(self):
        source = '''
            typedef struct { volatile unsigned M0AR; } DMA_Stream;
            #define DMA2_Stream2 ((DMA_Stream *)0x40026428UL)
            static volatile unsigned char rxbuf[16];
            static unsigned by_value;
            int main(void) {
                DMA2_Stream2->M0AR = (unsigned long)rxbuf;
                DMA2_Stream2->M0AR = by_value;
                return rxbuf[0];
            }
        '''
        cfg = self.project({'main.c': source}, contexts=[
            dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        buffer = next((row for row in facts['variables'] if row['name'].startswith('rxbuf')
                       and row.get('static_classification') in {'UNKNOWN', 'SUSPECT'}), None)
        self.assertIsNotNone(buffer, [(row['name'], row.get('static_classification'))
                                      for row in facts['variables']])
        self.assertEqual(buffer['static_classification'], 'UNKNOWN', buffer)
        self.assertIn('UNKNOWN_DMA_LIFETIME', buffer['unknown_reason_codes'])
        self.assertTrue(any(issue['kind'] == 'UNRESOLVED_DMA_BUFFER'
                            and issue.get('mmio_address') == 0x40026428
                            for issue in facts['unknowns']))
        scalar = next(row for row in facts['variables'] if row['name'] == 'by_value')
        self.assertNotIn('UNKNOWN_DMA_LIFETIME', scalar.get('unknown_reason_codes', []))


if __name__ == '__main__':
    unittest.main()
