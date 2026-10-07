"""Missing declarations and linker anchors need target-specific proof."""

import json
import struct
import unittest

from tests import test_ecra

from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.evidence import EvidenceIndex
from ecra.extract import Extractor
from ecra.linker_symbols import linker_definitions


def write_elf64(path, entries):
    """Write a minimal ELF symbol table without depending on a host linker."""
    strings = b'\0' + b''.join(name.encode() + b'\0' for name, *_ in entries)
    offsets = {}
    at = 1
    for name, *_ in entries:
        offsets[name] = at
        at += len(name.encode()) + 1
    strings_at = 64 + 3 * 64
    symbols_at = (strings_at + len(strings) + 7) & ~7
    symbols = bytearray(24)
    for name, address, symbol_type, byte_size in entries:
        symbols += struct.pack('<IBBHQQ', offsets[name], 0x10 | symbol_type,
                               0, 0xfff1, address, byte_size)
    data = bytearray(symbols_at + len(symbols))
    data[:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<HHIQQQIHHHHHH', data, 16,
                     2, 62, 1, 0, 0, 64, 0, 64, 0, 0, 64, 3, 0)
    struct.pack_into('<IIQQQQIIQQ', data, 64 + 64,
                     0, 3, 0, 0, strings_at, len(strings), 0, 0, 1, 0)
    struct.pack_into('<IIQQQQIIQQ', data, 64 + 128,
                     0, 2, 0, 0, symbols_at, len(symbols), 1, 0, 8, 24)
    data[strings_at:strings_at + len(strings)] = strings
    data[symbols_at:] = symbols
    path.write_bytes(data)


class MissingDefinitionEvidenceTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def test_macro_attribute_extent_is_bounded_and_unlinked_header_helper_is_not_entry(self):
        cfg = self.project({
            'h.h': '''#define FORCE_INLINE __attribute__((always_inline))
                #define POSSIBLY_USED __attribute__((used))
                extern int absent;
                static FORCE_INLINE inline int helper(void) { return absent; }''',
            'a.c': '#include "h.h"\nint main(void) { return 0; }',
        }, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        elf, link_map = self.root/'firmware.elf', self.root/'firmware.map'
        write_elf64(elf, [('main', 0x1000, 2, 1)])
        link_map.write_text(' 0x00001000 main = .\n', encoding='utf-8')
        cfg['analysis']['build_closure'] = dict(elf=str(elf), map=str(link_map))
        facts, _ = self.extract(cfg)
        helper = next(row for row in facts['functions'] if row['name'] == 'helper')
        self.assertEqual('PROVEN_UNREACHABLE', helper['reachability'])
        self.assertTrue(all(len(spelling) < 100 for spelling in helper['attribute_spellings']))
        absent = next(row for row in facts['variables'] if row['name'] == 'absent')
        self.assertEqual('NON_STORAGE', absent['static_classification'])
        self.assertEqual('UNLINKED_DECLARATION', absent['resource_kind'])

    def test_unused_header_extern_and_derived_members_do_not_block(self):
        cfg = self.project({
            'h.h': '''typedef struct { int *dest; unsigned wlen; } Table;
                extern const Table copy_start, copy_end;
                extern volatile int unused_scalar;
                static __attribute__((always_inline,noreturn)) inline void unused_start(void) {
                    for (const Table *p=&copy_start; p<&copy_end; ++p)
                        p->dest[0] = p->wlen;
                    for (;;) {}
                }''',
            'a.c': '#include "h.h"\nint main(void){return 0;}',
        }, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        names = {v['qualified_name']: v for v in facts['variables']}
        for name in ('unused_scalar', 'copy_start.dest', 'copy_start.wlen',
                     'copy_end.dest', 'copy_end.wlen'):
            self.assertEqual(names[name]['static_classification'], 'SAFE_PROVEN', name)
            self.assertEqual(names[name]['safe_reason_code'], 'SAFE_NO_RUNTIME_ACCESS', name)
            self.assertNotIn('UNKNOWN_RELEVANT_MISSING_TU',
                             names[name]['unknown_reason_codes'], name)
        inline = [f for f in facts['functions'] if f['name'] == 'unused_start']
        self.assertEqual(len(inline), 1)
        self.assertEqual(inline[0]['reachability'], 'PROVEN_UNREACHABLE')
        self.assertTrue(any('always_inline' in spelling
                            for spelling in inline[0]['attribute_spellings']))

    def test_saved_extraction_without_attribute_spelling_uses_link_evidence(self):
        cfg = self.project({
            'h.h': '''extern volatile int unused_buffer;
                static __attribute__((always_inline,noreturn)) inline void helper(void) {
                    unused_buffer = 1;
                    for (;;) {}
                }''',
            'a.c': '#include "h.h"\nstatic int state;\n'
                   'static void __attribute__((constructor)) Startup(void){state++;}\n'
                   'int main(void){return 0;}',
        }, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        elf, link_map = self.root/'firmware.elf', self.root/'firmware.map'
        write_elf64(elf, [('main', 0x1000, 2, 1), ('Startup', 0x1100, 2, 1)])
        link_map.write_text(' 0x00001000 main = .\n', encoding='utf-8')
        cfg['analysis']['build_closure'] = dict(elf=str(elf), map=str(link_map))
        units, audit = prepare(self.root, cfg)
        facts = merge([Extractor(dict(root=str(self.root), unit=u, config=cfg)).run()
                       for u in units])
        for function in facts['functions']:
            function.pop('attribute_spellings', None)  # Older persisted raw facts.
        analyze(facts, cfg, dict(translation_units_failed=0, **audit))
        buffer = next(v for v in facts['variables'] if v['name'] == 'unused_buffer')
        self.assertEqual(buffer['static_classification'], 'NON_STORAGE')
        self.assertEqual(buffer['resource_kind'], 'UNLINKED_DECLARATION')
        functions = {f['name']: f for f in facts['functions']}
        self.assertEqual(functions['helper']['reachability'], 'PROVEN_UNREACHABLE')
        self.assertEqual(functions['Startup']['reachability'], 'UNKNOWN_ENTRY')

    def test_reachable_undefined_extern_remains_unknown(self):
        cfg = self.project({'h.h': 'extern int live;',
                            'a.c': '#include "h.h"\nint main(void){return live;}'},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        live = next(v for v in facts['variables'] if v['name'] == 'live')
        self.assertEqual(live['static_classification'], 'UNKNOWN')
        self.assertIn('UNKNOWN_RELEVANT_MISSING_TU', live['unknown_reason_codes'])

    def test_elf_and_map_must_agree_on_zero_sized_notype_assignment(self):
        elf, link_map = self.root/'firmware.elf', self.root/'firmware.map'
        write_elf64(elf, [('boundary', 0x20001000, 0, 0),
                          ('ordinary', 0x20002000, 1, 4),
                          ('wrong_address', 0x20003000, 0, 0)])
        link_map.write_text(' 0x20001000 boundary = .\n'
                            ' 0x20002000 ordinary = .\n'
                            ' 0x20004000 wrong_address = .\n', encoding='utf-8')
        closure = dict(elf=str(elf), map=str(link_map))
        proofs = linker_definitions(closure, self.root)
        self.assertEqual(set(proofs), {'boundary'})
        self.assertEqual(proofs['boundary']['address'], 0x20001000)
        self.assertEqual(linker_definitions(dict(elf=str(elf), map='missing.map'), self.root), {})

        def evidence(name, other_issue=False):
            variable = dict(symbol_id='c:@' + name, name=name, qualified_name=name,
                            linkage='EXTERNAL', definition_file=None, definition_line=None,
                            declarations=[dict(file='a.c')], translation_units=['a.c'])
            issues = ([dict(kind='INLINE_ASSEMBLY', symbol_id=variable['symbol_id'],
                            file='a.c', line=2)] if other_issue else [])
            facts = dict(variables=[variable], functions=[], calls=[], unknowns=issues,
                         translation_units=[])
            index = EvidenceIndex(facts, dict(project_root=str(self.root), build_closure=closure),
                                  dict(project={}), set())
            address = dict(access_kind='ADDRESS_TAKEN', access_id='A1', function_id='main',
                           file='a.c', line=1, contexts=[])
            return index.build(variable, [address], {}, [])

        boundary = evidence('boundary', other_issue=True)
        self.assertEqual(boundary.definition['origin'], 'LINKER_SCRIPT')
        self.assertEqual({g['kind'] for g in boundary.critical_gaps}, {'INLINE_ASSEMBLY'})
        for name in ('ordinary', 'wrong_address'):
            self.assertIn('DEFINITION_MISSING',
                          {g['kind'] for g in evidence(name).critical_gaps})

    def test_linker_address_anchor_is_excluded_from_storage_denominator(self):
        cfg = self.project({'a.c': '''extern unsigned char boundary;
            int main(void) { return (int)(unsigned long)&boundary; }'''} ,
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        elf, link_map = self.root/'firmware.elf', self.root/'firmware.map'
        write_elf64(elf, [('boundary', 0x20001000, 0, 0)])
        link_map.write_text(' 0x20001000 boundary = .\n', encoding='utf-8')
        cfg['analysis']['build_closure'] = dict(elf=str(elf), map=str(link_map))
        facts, report = self.extract(cfg)
        boundary = next(row for row in facts['variables'] if row['name'] == 'boundary')
        self.assertEqual('LINKER_ADDRESS_ANCHOR', boundary['resource_kind'])
        self.assertEqual('NON_STORAGE', boundary['static_classification'])
        self.assertEqual('LINKER_SCRIPT', boundary['linker_anchor_evidence']['origin'])
        self.assertFalse(any(row.get('symbol_id') == boundary['symbol_id']
                             for row in report['findings']))


if __name__ == '__main__':
    unittest.main()
