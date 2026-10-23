"""Native Windows environment adapter for INAV's generated settings command.

Uses the unchanged official Ruby generator, target and CFLAGS from CMake's
generated .bat file. Firmware sources are never patched. This works around
list/quote expansion of PATH in that generated cmd.exe invocation.
"""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    env = dict(os.environ, CFLAGS=config['cflags'], TARGET='MATEKF405', SETTINGS_CXX='')
    env['PATH'] = ('D:/gcc-arm-none-eabi-10.3-2021.10/bin;' +
                   str(Path(config['ruby']).parent) + ';C:/Windows/System32;C:/Windows')
    return subprocess.call([config['ruby'], config['script'], config['root'], config['settings'],
                            '-o', config['output']], env=env, cwd=config['root'])


if __name__ == '__main__':
    raise SystemExit(main())
