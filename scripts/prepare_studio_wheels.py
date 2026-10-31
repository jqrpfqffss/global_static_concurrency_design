"""Download pinned cp310/Windows wheels and verify PyPI publisher hashes.

Writes new receipts in an explicit cache, never installs into a user's Python.
Offline verification checks every selected wheel against its saved receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    requirements = Path(__file__).resolve().parents[1]/'requirements-studio.txt'
    wheels = args.cache.resolve()/'wheels'; wheels.mkdir(parents=True, exist_ok=True)
    if not args.offline:
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--no-deps',
            '--platform=win_amd64', '--python-version=310', '--implementation=cp', '--abi=cp310',
            '--dest', str(wheels), '-r', str(requirements)], check=True)
    selected = []
    for line in requirements.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, version = line.split('==')
        normalized = name.lower().replace('-', '_')
        def compatible(path):
            python, abi, platform = path.stem.split('-')[-3:]
            return (python in {'cp310', 'py3', 'py2.py3'} and abi in {'cp310', 'none', 'abi3'}
                    and platform in {'win_amd64', 'any'})
        candidates = [p for p in wheels.glob('*.whl') if p.name.lower().startswith(normalized+'-'+version+'-') and compatible(p)]
        if len(candidates) != 1:
            raise ValueError('离线 wheel 缺失或版本/平台不唯一: '+line)
        file = candidates[0]; hashed = hashlib.sha256(file.read_bytes()).hexdigest()
        receipt = Path(str(file)+'.receipt.json')
        if args.offline:
            saved = json.loads(receipt.read_text(encoding='utf-8-sig'))
            if saved['sha256'].lower() != hashed:
                raise ValueError('离线 wheel 哈希不一致: '+file.name)
        else:
            with urllib.request.urlopen('https://pypi.org/pypi/'+name+'/'+version+'/json', timeout=60) as response:
                metadata = json.load(response)
            matches = [record for record in metadata['urls'] if record['filename'] == file.name]
            if len(matches) != 1 or matches[0]['digests']['sha256'] != hashed:
                raise ValueError('PyPI 发布哈希不一致: '+file.name)
            saved = dict(sha256=hashed, source=matches[0]['url'], package=name, version=version,
                         filename=file.name, requires_python=metadata['info'].get('requires_python'),
                         license=metadata['info'].get('license'), license_expression=metadata['info'].get('license_expression'))
            receipt.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
        selected.append(saved)
    (args.cache/'studio-wheels.json').write_text(json.dumps(dict(passed=True,offline=args.offline,wheels=selected),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,wheels=len(selected),offline=args.offline)))


if __name__ == '__main__':
    main()
