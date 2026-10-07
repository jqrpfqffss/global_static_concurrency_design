"""Byte views of aggregate storage must retain every possible member effect."""
import unittest

from tests import test_ecra


class ByteAliasOverlapTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def test_postincrement_byte_writer_reaches_record_members_through_wrappers(self):
        cfg = self.project({'a.c': '''
            static struct Coding { unsigned rate; unsigned char stop, parity, bits; } coding;
            static void endpoint(void *p) {
                unsigned char *dest = p;
                *dest++ = 1;
                *dest++ = 2;
            }
            static void transfer(void *p) { endpoint(p); }
            void Task(void) { transfer(&coding); }
            void ISR(void) { (void)coding.parity; }
        '''})
        facts, _ = self.extract(cfg)
        members = {v['qualified_name']: v for v in facts['variables']
                   if v.get('resource_kind') == 'STRUCT_MEMBER'}
        for name in ('coding.rate', 'coding.stop', 'coding.parity', 'coding.bits'):
            with self.subTest(name=name):
                member = members[name]
                self.assertTrue(any(a['access_kind'] == 'WRITE'
                                    and a.get('via_alias') == 'interprocedural points-to'
                                    for a in member['accesses']), name)
        self.assertNotEqual(members['coding.parity']['static_classification'], 'SAFE_PROVEN')

    def test_postincrement_from_member_covers_possible_sibling(self):
        cfg = self.project({'a.c': '''
            static struct Bytes { unsigned char first, second; } bytes;
            static void fill(unsigned char *dest) {
                *dest++ = 1;
                *dest++ = 2;
            }
            void Task(void) { fill(&bytes.first); }
            void ISR(void) { (void)bytes.second; }
        '''})
        facts, _ = self.extract(cfg)
        sibling = next(v for v in facts['variables'] if v.get('qualified_name') == 'bytes.second')
        self.assertTrue(any(a['access_kind'] == 'WRITE' and a.get('via_alias') == 'interprocedural points-to'
                            for a in sibling['accesses']), sibling['qualified_name'])
        self.assertNotEqual(sibling['static_classification'], 'SAFE_PROVEN')

    def test_postincrement_byte_reader_keeps_read_effect(self):
        cfg = self.project({'a.c': '''
            static struct Pair { unsigned char first, second; } pair;
            static unsigned char fetch(const unsigned char *src) { return *src++; }
            void Task(void) { (void)fetch((const unsigned char *)&pair); }
        '''})
        facts, _ = self.extract(cfg)
        members = {v['qualified_name']: v for v in facts['variables']
                   if v.get('resource_kind') == 'STRUCT_MEMBER'}
        for name in ('pair.first', 'pair.second'):
            self.assertTrue(any(a['access_kind'] == 'READ' and a.get('via_alias') == 'interprocedural points-to'
                                for a in members[name]['accesses']), name)

    def test_const_descriptor_table_reaches_byte_reader(self):
        cfg = self.project({'a.c': '''
            static const struct Config { unsigned short length, flags; } configuration = { 4, 7 };
            static const struct Descriptor { const void *desc; unsigned size; } descriptors[] = {
                { 0, 0 }, { &configuration, sizeof(configuration) }
            };
            static unsigned char send(const void *p) {
                const unsigned char *src = p;
                return *src++;
            }
            static unsigned char transfer(const void *p) { return send(p); }
            void Task(void) {
                const struct Descriptor *d = &descriptors[1];
                (void)transfer(d->desc);
            }
        '''})
        facts, _ = self.extract(cfg)
        members = {v['qualified_name']: v for v in facts['variables']
                   if v.get('resource_kind') == 'STRUCT_MEMBER'}
        for name in ('configuration.length', 'configuration.flags'):
            member = members[name]
            self.assertTrue(any(a['access_kind'] == 'READ'
                                and a.get('via_alias') == 'interprocedural points-to'
                                for a in member['accesses']), name)
            self.assertNotEqual(member.get('safe_reason_code'), 'SAFE_NO_RUNTIME_ACCESS', name)
            self.assertFalse(any(reason == 'UNKNOWN_RELEVANT_ALIAS'
                                 for reason in member.get('unknown_reason_codes', ())), name)

    def test_flexible_member_overlaps_backing_sibling_array(self):
        cfg = self.project({'a.c': '''
            struct Descriptor { unsigned char length; unsigned short data[]; };
            static struct Serial { struct Descriptor desc; unsigned short data[4]; unsigned tail; } serial;
            static void fill(struct Descriptor *d, unsigned count) {
                for (unsigned i = 0; i < count; i++) d->data[i] = (unsigned short)i;
            }
            void Task(void) { fill(&serial.desc, 4); }
            void ISR(void) { (void)serial.data[0]; (void)serial.tail; }
        '''})
        facts, _ = self.extract(cfg)
        backing = next(v for v in facts['variables'] if v.get('qualified_name') == 'serial.data[0]')
        tail = next(v for v in facts['variables'] if v.get('qualified_name') == 'serial.tail')
        self.assertTrue(any(a['access_kind'] == 'WRITE' for a in backing['accesses']), backing['qualified_name'])
        self.assertNotEqual(backing['static_classification'], 'SAFE_PROVEN')
        # The index is dynamic and the current interprocedural model has no
        # bound proof for ``count``.  The later field must remain a possible
        # overlap rather than receiving an unsound disjoint-storage proof.
        self.assertTrue(any(a['access_kind'] == 'WRITE' for a in tail['accesses']))
        self.assertNotEqual(tail['static_classification'], 'SAFE_PROVEN')


if __name__ == '__main__':
    unittest.main()
