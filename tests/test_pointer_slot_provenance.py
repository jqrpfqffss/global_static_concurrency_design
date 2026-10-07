"""Pointer containers, loaded pointees and exact subobjects must stay distinct."""
import unittest

from tests import test_ecra as fixtures


class PointerSlotProvenanceTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, source):
        cfg = self.project({'main.c': source}, contexts=[
            dict(id='main', kind='MAIN', functions=['main'])])
        self.facts, _ = self.extract(cfg)
        return self.facts

    def variables(self, prefix):
        return [variable for variable in self.facts['variables']
                if (variable.get('canonical_path') or variable.get('qualified_name', '')).startswith(prefix)]

    def test_pointer_table_slot_read_does_not_write_table(self):
        self.scan('''
            typedef struct HW { volatile unsigned reg; } HW;
            static HW h0, h1;
            static HW *const table[] = { &h0, &h1 };
            static void Store(unsigned i) { HW *p = table[i]; p->reg = 1u; }
            int main(void) { Store(0); Store(1); return 0; }
        ''')
        table = self.variables('table')
        self.assertTrue(table)
        self.assertTrue(any(a['access_kind'] == 'READ' for v in table for a in v.get('accesses', [])), table)
        self.assertFalse(any(a['access_kind'] in {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE'}
                             for v in table for a in v.get('accesses', [])), table)
        for name in ('h0.reg', 'h1.reg'):
            member = next(v for v in self.facts['variables'] if v.get('canonical_path') == name)
            self.assertTrue(any(a['access_kind'] == 'WRITE' and
                                a.get('via_alias') == 'interprocedural points-to'
                                for a in member['accesses']), member)

    def test_pointer_member_load_does_not_write_container(self):
        self.scan('''
            typedef struct HW { volatile unsigned reg; } HW;
            typedef struct Bus { HW *device; } Bus;
            static HW h0, h1;
            static Bus buses[] = { {&h0}, {&h1} };
            static void Store(unsigned i) { Bus *slot=&buses[i]; HW *p=slot->device; p->reg=1u; }
            int main(void) { Store(0); return 0; }
        ''')
        buses = self.variables('buses')
        self.assertTrue(buses)
        self.assertFalse(any(a['access_kind'] in {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE'}
                             for v in buses for a in v.get('accesses', [])), buses)
        self.assertTrue(any(a['access_kind'] == 'WRITE'
                            for name in ('h0.reg', 'h1.reg')
                            for v in self.facts['variables'] if v.get('canonical_path') == name
                            for a in v.get('accesses', [])))

    def test_address_of_member_keeps_exact_subobject(self):
        self.scan('''
            static struct State { unsigned a, b; } state;
            int main(void) { unsigned *p=&state.a; *p=1u; return (int)state.b; }
        ''')
        a = next(v for v in self.facts['variables'] if v.get('canonical_path') == 'state.a')
        b = next(v for v in self.facts['variables'] if v.get('canonical_path') == 'state.b')
        self.assertTrue(any(x['access_kind'] == 'WRITE' for x in a['accesses']), a)
        self.assertFalse(any(x['access_kind'] in {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE'}
                             for x in b['accesses']), b)
        self.assertFalse(any(x.get('access_scope') == 'INHERITED_WHOLE_OBJECT_ACCESS'
                             for x in a['accesses'] + b['accesses']))

    def test_function_static_multi_declarator_all_defined(self):
        self.scan('''
            static unsigned Use(void) { static unsigned count, sum, sumsq;
                count++; sum += count; sumsq += sum; return sumsq; }
            int main(void) { return (int)Use(); }
        ''')
        for name in ('count', 'sum', 'sumsq'):
            variable = next(v for v in self.facts['variables'] if v['name'] == name)
            self.assertEqual(len(variable['definitions']), 1, variable)
            self.assertEqual(variable['definition_file'], 'main.c', variable)


if __name__ == '__main__':
    unittest.main()
