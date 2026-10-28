"""Create a fresh, real-Clang 33-variable fixture without touching user outputs."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecra.cli import run
from ecra.common import read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output/manual-browser-fixture'))
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    declarations = ''.join(f'int g{i:02d};\n' for i in range(30))
    accesses = ' '.join(f'g{i:02d}++;' for i in range(30))
    source = ('int value;\n' + declarations + 'struct State {int a; int b;} state;\n'
              f'void ISR(void) {{ value++; {accesses} state.a++; state.b++; }}\n'
              f'void Task(void) {{ value++; {accesses} state.a++; state.b++; }}\n'
              'void Unrelated(void) { int private_value = 1; (void)private_value; }\n')
    (root/'app.c').write_text(source, encoding='utf-8')
    (root/'compile_commands.json').write_text(json.dumps([dict(directory=str(root), file='app.c',
        arguments=['arm-none-eabi-gcc', '-mcpu=cortex-m7', '-mthumb', '-c', 'app.c'])]), encoding='utf-8')
    config = root/'semantics.yaml'
    config.write_text(json.dumps(dict(version=1, analysis=dict(compile_database='compile_commands.json'),
        contexts=[dict(id='isr', kind='ISR', functions=['ISR']), dict(id='task', kind='TASK', functions=['Task'])],
        review=dict(enabled=False))), encoding='utf-8')
    run(root, str(config), no_review=True)
    assert (root/'.ecra/scan_state.json').is_file(), 'scan failed'
    assert len(read_json(root/'.ecra/reports/global_static_concurrency.json')['findings']) == 33
    print(f'Fixture ready. Serve with --project "{root}" --config "{config}" --port 8876')


if __name__ == '__main__':
    main()
