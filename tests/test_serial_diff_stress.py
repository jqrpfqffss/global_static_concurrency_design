"""Independent expected outcomes for the real serial branch injection corpus."""
import json
import unittest

from ecra.git_diff import summarize, compare
from scripts.prepare_serial_diff import FIXTURE, delta_text
from scripts.validate_serial_diff import audit_cases
from tests import test_ecra


class SerialDiffStressTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def test_real_fixture_baseline_and_delta(self):
        sources = {p.name: p.read_text(encoding='utf-8') for p in FIXTURE.iterdir() if p.suffix in ('.c', '.h')}
        # Keep the actual probe bodies; replace only the board/libc boundary.
        sources['ecra_diff_probe.h'] = sources['ecra_diff_probe.h'].replace(
            '#include <string.h>', 'typedef __SIZE_TYPE__ size_t; void *memcpy(void *, const void *, size_t);')
        sources['main.h'] = 'void __disable_irq(void); void __enable_irq(void);'
        sources['entry.c'] = '#include "ecra_diff_probe.h"\nvoid main(void){Probe_Init();Probe_Foreground();}\nvoid USART2_IRQHandler(void){Probe_Irq();}'
        contexts = [dict(id='main', kind='MAIN', functions=['main'])]
        cfg = self.project(sources, contexts=contexts)
        bf, br = self.extract(cfg)
        base = summarize(bf, br)
        cfg = self.project({name: delta_text(name, source) for name, source in sources.items()}, contexts=contexts)
        hf, hr = self.extract(cfg)
        diff = compare(base, summarize(hf, hr), dict(files=[], head_sha='h', base_sha='b'))
        expectations = json.loads((FIXTURE/'expectations.json').read_text(encoding='utf-8'))['cases']
        hr['git_diff'] = diff
        audit = audit_cases(hf, hr, bf, expectations)
        failures = [(row['id'], row['errors']) for row in audit['cases'] if not row['passed']]
        self.assertEqual(failures, [])
        self.assertEqual(audit['passed_cases'], 21)


if __name__ == '__main__':
    unittest.main()
