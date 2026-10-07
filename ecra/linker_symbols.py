"""Verify linker-script boundary symbols against the final ELF and link map.

A declaration and an ELF symbol alone do not prove that a C object was
defined: an assembly object can also supply a symbol.  Only an assignment in
the link map that agrees with a zero-sized, global ELF NOTYPE symbol is treated
as a linker-created address anchor.
"""

from collections import defaultdict
from pathlib import Path
import re
import struct


_ASSIGNMENT = re.compile(
    r'^\s*(0x[0-9a-fA-F]+)\s+'
    r'(?:(?:PROVIDE|PROVIDE_HIDDEN)\s*\(\s*)?'
    r'([A-Za-z_$][\w.$]*)\s*=\s*')


def _symbols_in_elf(path):
    data = path.read_bytes()
    if len(data) < 64 or data[:4] != b'\x7fELF':
        raise ValueError('not an ELF file')
    elf_class, encoding = data[4:6]
    if elf_class not in (1, 2) or encoding not in (1, 2):
        raise ValueError('unsupported ELF format')
    endian = '<' if encoding == 1 else '>'
    if elf_class == 1:
        header = struct.unpack_from(endian + 'HHIIIIIHHHHHH', data, 16)
        section_format = endian + 'IIIIIIIIII'
        symbol_format = endian + 'IIIBBH'
        symbol_fields = lambda row: (row[0], row[1], row[2], row[3], row[5])
    else:
        header = struct.unpack_from(endian + 'HHIQQQIHHHHHH', data, 16)
        section_format = endian + 'IIQQQQIIQQ'
        symbol_format = endian + 'IBBHQQ'
        symbol_fields = lambda row: (row[0], row[4], row[5], row[1], row[3])
    section_offset, section_entry_size, section_count = header[5], header[10], header[11]
    section_size = struct.calcsize(section_format)
    if (not section_count or section_entry_size < section_size
            or section_offset + section_entry_size * section_count > len(data)):
        raise ValueError('invalid ELF section table')
    sections = [struct.unpack_from(section_format, data, section_offset + i * section_entry_size)
                for i in range(section_count)]
    names = defaultdict(list)
    symbol_size = struct.calcsize(symbol_format)
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB, not a dynamic-library import table.
            continue
        offset, size, string_index, entry_size = section[4], section[5], section[6], section[9]
        if (string_index >= len(sections) or entry_size < symbol_size
                or offset + size > len(data)):
            raise ValueError('invalid ELF symbol table')
        string_section = sections[string_index]
        strings_offset, strings_size = string_section[4], string_section[5]
        if strings_offset + strings_size > len(data):
            raise ValueError('invalid ELF string table')
        strings = data[strings_offset:strings_offset + strings_size]
        for at in range(offset, offset + size, entry_size):
            name_offset, value, byte_size, info, section_index = symbol_fields(
                struct.unpack_from(symbol_format, data, at))
            if name_offset >= len(strings):
                continue
            end = strings.find(b'\0', name_offset)
            if end < 0:
                continue
            name = strings[name_offset:end].decode('utf-8', errors='replace')
            if name:
                names[name].append(dict(address=value, size=byte_size, type=info & 15,
                                        binding=info >> 4, section_index=section_index))
    return names


def _assignments_in_map(path):
    assignments = defaultdict(list)
    with path.open(encoding='utf-8', errors='replace') as stream:
        for line_number, line in enumerate(stream, 1):
            match = _ASSIGNMENT.match(line)
            if match:
                assignments[match.group(2)].append(dict(address=int(match.group(1), 16),
                                                        line=line_number))
    return assignments


def linker_definitions(build_closure, project_root=None):
    """Return address anchors proved by both artifacts of this exact link.

    A missing, stale, malformed, or stripped artifact yields no proof.  Callers
    then keep ordinary missing-definition coverage blockers.
    """
    elf_name, map_name = build_closure.get('elf'), build_closure.get('map')
    if not elf_name or not map_name:
        return {}
    root = Path(project_root or '.')
    elf = (root / elf_name).resolve()
    link_map = (root / map_name).resolve()
    try:
        symbols = _symbols_in_elf(elf)
        assignments = _assignments_in_map(link_map)
    except (OSError, ValueError, struct.error):
        return {}
    verified = {}
    for name, map_rows in assignments.items():
        defined = [row for row in symbols.get(name, ()) if row['section_index'] != 0]
        if (len(map_rows) != 1 or len(defined) != 1):
            continue
        symbol, assignment = defined[0], map_rows[0]
        if (symbol['address'] != assignment['address'] or symbol['size'] != 0
                or symbol['type'] != 0 or symbol['binding'] != 1
                or symbol['section_index'] == 0xfff2):  # SHN_COMMON is storage.
            continue
        verified[name] = dict(origin='LINKER_SCRIPT', symbol=name,
                              address=symbol['address'], elf=str(elf), map=str(link_map),
                              map_line=assignment['line'], elf_type='NOTYPE', size_bytes=0)
    return verified


def linked_symbol_names(build_closure, project_root=None):
    """Return defined names only when both final link artifacts are readable.

    This is used to disambiguate older extracted function records whose Clang
    attributes were saved without their spellings.  A missing artifact gives
    no negative symbol evidence.
    """
    elf_name, map_name = build_closure.get('elf'), build_closure.get('map')
    if not elf_name or not map_name:
        return None
    root = Path(project_root or '.')
    try:
        symbols = _symbols_in_elf((root / elf_name).resolve())
        _assignments_in_map((root / map_name).resolve())
    except (OSError, ValueError, struct.error):
        return None
    if not symbols:
        # A stripped ELF supplies no negative symbol evidence.
        return None
    return {name for name, rows in symbols.items()
            if any(row['section_index'] not in (0, 0xfff2) for row in rows)}
