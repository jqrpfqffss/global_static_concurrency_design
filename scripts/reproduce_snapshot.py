"""Deterministic snapshot faults in a disposable fixture, never real firmware."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.engine.resolve()))
    from ecra import cli
    original = cli.execute
    args.evidence.mkdir(parents=True, exist_ok=True)
    results = []
    for mode in ('unchanged', 'source', 'header', 'timestamp', 'unrelated_header', 'report', 'config', 'delete_header'):
        root = (args.evidence / mode).resolve()
        root.mkdir(exist_ok=True)
        (root / 'used.h').write_text('extern int shared;\n', encoding='utf-8')
        (root / 'app.c').write_text('#include "used.h"\nint shared; void IRQ(void){shared++;} int main(void){shared++;return 0;}\n', encoding='utf-8')
        (root / 'unused.h').write_text('/* independent output */', encoding='utf-8')
        (root / 'compile_commands.json').write_text(json.dumps([dict(directory=str(root), file='app.c',
            arguments=['arm-none-eabi-gcc', '-mcpu=cortex-m4', '-mthumb', '-I.', '-c', 'app.c'])]))
        cfg = root/'semantics.yaml'
        cfg.write_text(json.dumps(dict(version=1, analysis=dict(compile_database='compile_commands.json'),
             contexts=[dict(id='main', kind='MAIN', functions=['main']), dict(id='irq',kind='ISR',functions=['IRQ'])],
             review=dict(enabled=False, prepare_packets=False))), encoding='utf-8')
        changed = False
        def execute(argv, **kw):
            nonlocal changed
            result = original(argv, **kw)
            if 'ecra.extract' in argv and '.dependencies.' not in str(argv[-1]) and not changed:
                changed = True
                if mode == 'timestamp':
                    os.utime(root/'used.h', None)
                elif mode == 'unrelated_header':
                    (root/'unused.h').write_text('/* updated unrelated output */', encoding='utf-8')
                elif mode == 'report':
                    (root/'report.json').write_text('{"updated":true}', encoding='utf-8')
                elif mode == 'delete_header':
                    (root/'used.h').unlink()
                elif mode in ('source', 'header', 'config'):
                    path = root / {'source':'app.c', 'header':'used.h', 'config':'compile_commands.json'}[mode]
                    with path.open('a', encoding='utf-8') as stream:
                        stream.write('\n' if mode == 'config' else '\n/* content changed during extraction */\n')
            return result
        cli.execute = execute
        with (root/'console.log').open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log):
            code = cli.run(root, str(cfg), no_review=True)
        state = json.loads((root/'.ecra/run.json').read_text(encoding='utf-8'))
        results.append(dict(mode=mode, exit_code=code, state=state.get('state'), error=state.get('error')))
    cli.execute = original
    (args.evidence/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))


if __name__ == '__main__':
    main()
