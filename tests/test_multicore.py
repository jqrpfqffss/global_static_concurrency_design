import struct
import tempfile
import unittest
from pathlib import Path
from ecra.multicore import elf_objects


class ElfEvidenceTests(unittest.TestCase):
    def test_arm_elf_object_addresses_and_private_binding(self):
        # ELF32 independent fixture with two object symbols at different RAMs.
        names=b'\0mailbox\0private\0'
        header=bytearray(52)
        header[:7]=b'\x7fELF\x01\x01\x01'
        struct.pack_into('<H',header,18,40)
        struct.pack_into('<I',header,32,52)
        struct.pack_into('<HH',header,46,40,3)
        string_offset=52+120
        symbol_offset=string_offset+len(names)
        sections=bytes(40)+struct.pack('<10I',0,3,0,0,string_offset,len(names),0,0,1,0)+struct.pack('<10I',0,2,0,0,symbol_offset,32,1,0,4,16)
        symbols=struct.pack('<IIIBBH',1,0x38000000,16,0x11,0,1)+struct.pack('<IIIBBH',9,0x24000000,4,0x01,0,1)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'firmware.elf'; p.write_bytes(header+sections+names+symbols)
            result=elf_objects(p)
            self.assertEqual([(s['address'],s['size'],s['binding']) for s in result],[(0x38000000,16,1),(0x24000000,4,0)])
            header[18]=62
            p.write_bytes(header+sections+names+symbols)
            with self.assertRaises(ValueError): elf_objects(p)
