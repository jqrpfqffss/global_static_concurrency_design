"""Verify a pinned, already-built single Ninja target and its real database.

Read-only: never configure/build or edit the firmware/database. This complements
prepare_large_stm32.py and the scan acceptance runner.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecra.compilation import split_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--ninja', default='ninja')
    parser.add_argument('--arm-version', default='10.3.1')
    parser.add_argument('--min-units', type=int, default=226)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    def command(argv, cwd=args.project):
        proc = subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=120)
        if proc.returncode:
            raise RuntimeError(f'{argv}: {proc.returncode}\n{proc.stderr[-3000:]}')
        return proc.stdout.strip()
    revision = command(['git', 'rev-parse', 'HEAD'])
    status = command(['git', 'status', '--porcelain', '--untracked-files=no'])
    entries = json.loads(args.database.read_text(encoding='utf-8-sig'))
    units = [entry for entry in entries if Path(entry['file']).suffix.lower() in {'.c', '.cc', '.cpp', '.cxx'}]
    commands = command([args.ninja, '-C', args.build, '-t', 'commands', args.target]).splitlines()
    def normalize(value):
        return ' '.join(value.replace('\\', '/').split())
    closure = {normalize(value) for value in commands}
    missing, outside, compilers = [], [], {}
    for unit in units:
        directory = Path(unit.get('directory', args.project))
        source = (directory/unit['file']).resolve()
        if not source.is_file():
            missing.append(str(source))
        raw = unit.get('arguments') or split_command(unit['command'])
        # Native Ninja databases retain the exact command. Do not silently
        # accept a different variant or discard an unmatched compilation.
        rendered = unit.get('command') or subprocess.list2cmdline(raw)
        if normalize(rendered) not in closure:
            outside.append(dict(file=str(source), command=rendered))
        index = 1 if Path(raw[0]).stem.lower() in {'ccache', 'sccache'} else 0
        compiler = raw[index]
        if compiler not in compilers:
            if Path(compiler).stem.lower() not in {'arm-none-eabi-gcc', 'arm-none-eabi-g++'}:
                raise ValueError(f'Not the expected real ARM GCC target: {compiler}')
            version = command([compiler, '-dumpfullversion', '-dumpversion'], directory)
            compilers[compiler] = dict(version=version, banner=command([compiler, '--version'], directory))
    result = dict(commit=revision, expected_commit=args.commit, tracked_modifications=status,
                  database=str(args.database.resolve()), database_sha256=hashlib.sha256(args.database.read_bytes()).hexdigest(),
                  database_entries=len(entries), translation_units=len(units),
                  source_extensions=dict(Counter(Path(e['file']).suffix.lower() for e in entries)),
                  target=args.target, ninja_version=command([args.ninja, '--version']),
                  compilers=compilers, missing_sources=missing, unmatched_target_commands=outside)
    result['verified'] = (revision == args.commit and not status and len(units) >= args.min_units
                          and not missing and not outside and bool(compilers)
                          and all(c['version'] == args.arm_version for c in compilers.values()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(verified=result['verified'], units=len(units), unmatched=len(outside), output=str(args.output))))
    return 0 if result['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
