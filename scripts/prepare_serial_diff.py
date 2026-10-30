"""Create two committed test branches in the real serial firmware; never flash.

The original branch is preserved. Requires a clean worktree and refuses to
reuse branch names or overwrite existing probe files. Baseline contains dormant
deep IRQ code; delta activates it without editing its storage/accessor bodies.
"""
import argparse
import json
from pathlib import Path
import subprocess

TOOL = Path(__file__).resolve().parents[1]
FIXTURE = TOOL / 'tests/fixtures/serial_diff'

DIFF_EDITS = {
    'ecra_diff_storage.c': [('unsigned probe_deleted;', 'volatile unsigned probe_added;')],
    'ecra_diff_foreground.c': [
        ('static unsigned probe_same_name;', 'extern volatile unsigned probe_added;\nstatic unsigned probe_same_name;'),
        ('    probe_rmw = 3;', '    probe_rmw++;\n    probe_added++;'),
        ('    __disable_irq();\n    probe_lock_removed++;\n    __enable_irq();', '    probe_lock_removed++;'),
    ],
    'ecra_diff_irq.c': [
        ('static unsigned probe_same_name;', 'extern volatile unsigned probe_added;\nstatic unsigned probe_same_name;'),
        ('    probe_race_removed++;', '    probe_added++;'),
        ('    /* DELTA_ACTIVATE_DEEP_IRQ */', '    Probe_IrqBody();'),
    ],
}


def delta_text(name, text):
    for old, new in DIFF_EDITS.get(name, []):
        if text.count(old) != 1:
            raise ValueError('Unexpected delta anchor: ' + name + ' ' + old)
        text = text.replace(old, new)
    return text


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                   encoding='utf-8').strip()


def prepare(root, baseline, current):
    root = root.resolve()
    if git(root, 'status', '--porcelain'):
        raise ValueError('Firmware worktree must be clean')
    existing = set(git(root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads').splitlines())
    if baseline in existing or current in existing or baseline == current:
        raise ValueError('Use new and distinct baseline/current branch names')
    for branch in (baseline, current):
        git(root, 'check-ref-format', '--branch', branch)
    original = git(root, 'rev-parse', 'HEAD')
    original_branch = git(root, 'branch', '--show-current')
    files = {}
    for source in FIXTURE.iterdir():
        if source.suffix not in ('.c', '.h'):
            continue
        target = root / 'Core' / ('Inc' if source.suffix == '.h' else 'Src') / source.name
        if target.exists():
            raise ValueError('Refusing to overwrite ' + str(target))
        files[target] = source.read_text(encoding='utf-8')
    replacements = {
        'CMakeLists.txt': ('  Core/Src/main.c', '  Core/Src/main.c\n' + ''.join(
            '  Core/Src/' + name + '\n' for name in sorted(p.name for p in files if p.suffix == '.c')).rstrip()),
        'Core/Src/main.c': ('#include "app_cli_commands.h"', '#include "app_cli_commands.h"\n#include "ecra_diff_probe.h"'),
        'Core/Src/stm32f1xx_it.c': ('#include "stm32f1xx_it.h"', '#include "stm32f1xx_it.h"\n#include "ecra_diff_probe.h"'),
    }
    for name, (old, new) in replacements.items():
        path = root / name
        text = path.read_text(encoding='utf-8')
        if text.count(old) != 1:
            raise ValueError('Unexpected integration anchor: ' + name)
        files[path] = text.replace(old, new)
    main = root / 'Core/Src/main.c'
    files[main] = files[main].replace('    Cli_Process(&cli);', '    Cli_Process(&cli);\n    Probe_Foreground();')
    files[main] = files[main].replace('  /* USER CODE BEGIN 2 */', '  /* USER CODE BEGIN 2 */\n  Probe_Init();')
    irq = root / 'Core/Src/stm32f1xx_it.c'
    files[irq] = files[irq].replace('  HAL_UART_IRQHandler(&huart2);', '  HAL_UART_IRQHandler(&huart2);\n  Probe_Irq();')
    ignore = root / '.gitignore'
    files[ignore] = ignore.read_text(encoding='utf-8').rstrip() + '\n\n# Local concurrency scan artifacts\n.ecra/\n'
    git(root, 'switch', '-c', baseline)
    for path, text in files.items():
        path.write_text(text, encoding='utf-8', newline='\n')
    names = [p.relative_to(root).as_posix() for p in files]
    git(root, 'add', '--', *names)
    git(root, 'commit', '-m', 'test: add dormant deep concurrency probes to serial firmware')
    base_sha = git(root, 'rev-parse', 'HEAD')
    git(root, 'switch', '-c', current)
    for name in DIFF_EDITS:
        path = root / 'Core/Src' / name
        path.write_text(delta_text(name, path.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
    git(root, 'add', '--', *['Core/Src/' + name for name in DIFF_EDITS])
    git(root, 'commit', '-m', 'test: activate hidden IRQ races and conventional diff cases')
    return dict(project=str(root), original_branch=original_branch, original_sha=original,
                baseline_branch=baseline, baseline_sha=base_sha,
                current_branch=current, current_sha=git(root, 'rev-parse', 'HEAD'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--baseline', default='ecra/diff-baseline-20261030')
    parser.add_argument('--current', default='ecra/diff-stress-20261030')
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.project, args.baseline, args.current)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
