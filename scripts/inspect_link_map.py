"""Distinguish compile-command closure from actual GNU ld object selection.

Read-only. All database rows remain available to ECRA; archive members that
were not selected are reported, never removed from the scanning database.
Section garbage collection is separate from object selection.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecra.compilation import split_command


def normalized(text):
    return text.replace('\\', '/').lower()


def inspect(database, build, map_file, ninja):
    entries = json.loads(database.read_text(encoding='utf-8-sig'))
    objects = {}
    for entry in entries:
        if Path(entry['file']).suffix.lower() not in {'.c', '.cc', '.cpp', '.cxx', '.s'}:
            continue
        args = entry.get('arguments') or split_command(entry['command'])
        output = entry.get('output') or (args[args.index('-o')+1] if '-o' in args else None)
        if not output:
            raise ValueError(f'No object output for {entry["file"]}')
        absolute = (Path(entry['directory'])/output).resolve()
        target = absolute.relative_to(build.resolve()).as_posix()
        objects[target] = dict(source=entry['file'], object=target, immediate_outputs=[])
    targets = list(objects)
    for offset in range(0, len(targets), 24):
        process = subprocess.run([str(ninja), '-C', str(build), '-t', 'query', *targets[offset:offset+24]],
                                 capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        if process.returncode:
            raise ValueError(process.stderr)
        current, outputs = None, False
        for line in process.stdout.splitlines():
            if line and not line[0].isspace() and line.endswith(':'):
                current, outputs = line[:-1], False
            elif line == '  outputs:':
                outputs = True
            elif outputs and line.startswith('    ') and current in objects:
                objects[current]['immediate_outputs'].append(line.strip())
    members, direct, in_header = set(), set(), True
    with map_file.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            if line.startswith(('Discarded input sections', 'Memory Configuration', 'Linker script and memory map')):
                in_header = False
            if in_header:
                match = re.match(r'([^\s]+\.a)\(([^)]+)\)', line)
                if match:
                    members.add(tuple(normalized(item) for item in match.groups()))
            if line.startswith('LOAD '):
                direct.add(normalized(line[5:].strip()))
    for target, row in objects.items():
        libraries = [out for out in row['immediate_outputs'] if out.endswith('.a')]
        row['archive_targets'] = libraries
        row['selected_archive_targets'] = [lib for lib in libraries if (normalized(lib), normalized(Path(target).name)) in members]
        if normalized(target) in direct:
            row['link_selection'] = 'DIRECT_LOAD'
        elif row['selected_archive_targets']:
            row['link_selection'] = 'ARCHIVE_MEMBER_SELECTED'
        elif libraries:
            row['link_selection'] = 'ARCHIVE_MEMBER_NOT_SELECTED'
        else:
            row['link_selection'] = 'NOT_RESOLVED_FROM_MAP'
    result = dict(database=str(database), database_sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
                  link_map=str(map_file), map_sha256=hashlib.sha256(map_file.read_bytes()).hexdigest(),
                  database_entries=len(entries), compiled_objects=len(objects),
                  counts=dict(Counter(row['link_selection'] for row in objects.values())),
                  archive_members_in_map=len(members), direct_load_entries=len(direct), rows=list(objects.values()),
                  boundary='Object selection only; selected objects can still have sections removed by --gc-sections. '
                           'Prebuilt compiler runtime archive members are outside the source compilation database. '
                           'No scan inputs or database rows were removed.')
    result['resolved'] = not result['counts'].get('NOT_RESOLVED_FROM_MAP')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--map', dest='map_file', type=Path, required=True)
    parser.add_argument('--ninja', default='ninja')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.database, args.build, args.map_file, args.ninja)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(resolved=result['resolved'], counts=result['counts'], output=str(args.output))))
    return 0 if result['resolved'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
