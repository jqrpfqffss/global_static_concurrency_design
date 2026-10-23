"""Completed solutions must not survive through bound-cache ownership cycles."""
import gc
import unittest
from unittest.mock import patch
import weakref

from ecra.points_to import Solver


class SolverLifetimeTests(unittest.TestCase):
    def test_caches_and_debug_callback_do_not_retain_solver_without_gc(self):
        for tracing in ('', '1'):
            with self.subTest(tracing=bool(tracing)), patch.dict('os.environ', ECRA_SOLVER_TRACE_HOT=tracing):
                enabled = gc.isenabled()
                gc.disable()
                try:
                    solver = Solver(dict(variables=[], functions=[], pointer_storage=[]))
                    reference = weakref.ref(solver)
                    pool = solver.target_pool
                    cache = solver.symbol
                    self.assertIsNone(cache('unknown:unresolved'))
                    self.assertEqual(cache.cache_info().misses, 1)
                    self.assertIsNone(cache('unknown:unresolved'))
                    self.assertEqual(cache.cache_info().hits, 1)
                    del solver
                    self.assertIsNone(reference(), 'A completed Solver still depends on cyclic GC')
                    with self.assertRaises(ReferenceError):
                        cache('different:uncached')
                    # A retained exact target set can still intern targets.
                    pool.bit('unknown:later')
                finally:
                    if enabled:
                        gc.enable()


if __name__ == '__main__':
    unittest.main()
