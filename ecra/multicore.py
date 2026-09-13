"""Combine separate core scans only where linked ELF addresses overlap shared RAM."""
import argparse
import copy
import hashlib
import json
import struct
from pathlib import Path

from .analysis import analyze, TABLES
from .common import read_json, write_json
from .config import load_config
from .report import generate


def elf_objects(path):
    raw = Path(path).read_bytes()
    if raw[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H', raw, 18)[0] != 40:
        raise ValueError('Expected little-endian ELF32 ARM firmware: ' + str(path))
    section_offset = struct.unpack_from('<I', raw, 32)[0]
    entry_size, count = struct.unpack_from('<HH', raw, 46)
    sections = [struct.unpack_from('<10I', raw, section_offset + i*entry_size) for i in range(count)]
    symbols = []
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = raw[strings[4]:strings[4]+strings[5]]
        owner = ''
        for offset in range(section[4], section[4]+section[5], section[9] or 16):
            name, address, size, info, _, shndx = struct.unpack_from('<IIIBBH', raw, offset)
            spelling = names[name:].split(b'\0', 1)[0].decode('utf-8', 'replace')
            if info & 15 == 4:
                owner = spelling
            if info & 15 == 1 and shndx and size:
                symbols.append(dict(name=spelling, address=address, size=size, binding=info >> 4, file=owner))
    return symbols


def combine(root, inputs, regions, out, elf_paths=None):
    combined = {k: [] for k in TABLES}
    combined.update(pointer_model_applied=True, linked_objects=[])
    cfg = load_config(root, inputs[0][1])[0]
    cfg['contexts'], cfg['call_edges'] = [], []
    cfg['analysis']['auto_contexts'] = False
    objects = {}
    cross = {}
    units = []
    for variant, config_path in inputs:
        source_cfg, _ = load_config(root, config_path)
        folder = root / source_cfg['analysis']['output_dir']
        facts = read_json(folder / 'facts.json')
        elf = root / (elf_paths or {}).get(variant, source_cfg['project'].get('firmware_elf', ''))
        linked = elf_objects(elf)
        idmap = {}
        for var in facts['variables']:
            symbol = var['symbol_id']
            matches = [s for s in linked if s['name'] == var['name'] and
                       (s['binding'] != 0 or Path(s['file']).name == Path(var['definition_file'] or '').name)]
            location = matches[0] if len(matches) == 1 else None
            shared = location and any(start <= location['address'] and location['address']+location['size'] <= start+size for start, size in regions)
            sid = ('shared:' + hex(location['address']) + ':' + str(location['size'])) if shared else variant + '::' + symbol
            idmap[symbol] = sid
            obj = copy.deepcopy(var)
            obj.update(symbol_id=sid, accesses=[], core_instances=[dict(variant=variant, symbol_id=symbol)])
            if shared:
                obj['linked_address'] = location['address']
                combined['linked_objects'].append(dict(variant=variant, symbol_id=symbol, combined_symbol_id=sid,
                    elf=str(elf), elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(), **location))
                cross.setdefault(sid, set()).add(source_cfg['project']['core'])
            if sid in objects:
                objects[sid]['core_instances'].extend(obj['core_instances'])
            else:
                objects[sid] = obj
        fmap = {f['function_id']: variant + '::' + f['function_id'] for f in facts['functions']}
        for f in facts['functions']:
            combined['functions'].append(dict(f, function_id=fmap[f['function_id']]))
        for a in facts['accesses']:
            row = copy.deepcopy(a)
            row.update(symbol_id=idmap[a['symbol_id']], function_id=fmap.get(a['function_id'], ''),
                       access_id=variant + ':' + a['access_id'], core=source_cfg['project']['core'], variant=variant)
            combined['accesses'].append(row)
        for c in facts['calls']:
            combined['calls'].append(dict(c, caller_function_id=fmap.get(c['caller_function_id'], variant + '::' + c['caller_function_id']),
                callee_function_id=fmap.get(c['callee_function_id'], variant + '::' + (c['callee_function_id'] or ''))))
        for key in ('unknowns', 'protection_events', 'snapshots'):
            for item in facts[key]:
                row = copy.deepcopy(item)
                if row.get('symbol_id'):
                    row['symbol_id'] = idmap[row['symbol_id']]
                if row.get('function_id'):
                    row['function_id'] = fmap.get(row['function_id'], variant + '::' + row['function_id'])
                combined[key].append(row)
        for c in facts['contexts']:
            roots = [fmap[b['function_id']] for b in facts['context_bindings'] if b['context_id'] == c['id'] and b['call_depth'] == 0]
            cfg['contexts'].append(dict(c, id=variant + ':' + c['id'], functions=roots, core=source_cfg['project']['core']))
        units.extend(dict(u, variant=variant) for u in facts['translation_units'])
    combined['variables'] = list(objects.values())
    combined['translation_units'] = units
    coverage = dict(translation_units_failed=sum(u['parse_status'] != 'PARSED' for u in units),
                    translation_units_total=len(units), unlisted_sources=[])
    coverage['translation_units_parsed'] = len(units) - coverage['translation_units_failed']
    coverage['parse_coverage_percent'] = round(100*coverage['translation_units_parsed']/max(1,len(units)),2)
    report = analyze(combined, cfg, coverage)
    for finding in report['findings']:
        if len(cross.get(finding.get('symbol_id'), set())) > 1:
            finding['rules'] = sorted(set(finding['rules']) | {'GS-CROSS-CORE'})
            finding['linked_memory_evidence'] = [x for x in combined['linked_objects'] if x['combined_symbol_id'] == finding['symbol_id']]
    report.update(run_status='INCOMPLETE', review_summary=dict(total=len(report['findings']), unresolved=len(report['findings'])),
                  fingerprint=hashlib.sha256(json.dumps(combined['linked_objects'], sort_keys=True).encode()).hexdigest())
    out.mkdir(parents=True, exist_ok=True)
    generate(out, combined, report, [])
    return combined, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--input', action='append', required=True, help='variant=config/path.yaml')
    p.add_argument('--shared-region', action='append', required=True, help='start:size, integers including 0x prefix')
    p.add_argument('--elf', action='append', default=[], help='variant=firmware.elf')
    p.add_argument('--output', default='results/multicore')
    a = p.parse_args()
    root = a.project.resolve()
    out = (root / a.output).resolve()
    if out == root or not out.is_relative_to(root):
        raise ValueError('Output must be a project subdirectory')
    facts, report = combine(root, [x.split('=', 1) for x in a.input], [tuple(int(v, 0) for v in x.split(':')) for x in a.shared_region], out,
                            dict(x.split('=', 1) for x in a.elf))
    print(json.dumps(dict(variables=len(facts['variables']), cross_core_findings=sum('GS-CROSS-CORE' in f['rules'] for f in report['findings']))))


if __name__ == '__main__':
    main()
