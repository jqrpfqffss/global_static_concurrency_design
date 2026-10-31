"""Collect exact installed frontend and pinned wheel notices for distribution."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    # Vite copies public/ on every clean build; notices must survive rebuilding
    # the hashed application assets, not depend on a previous build directory.
    out=root/'studio/public/licenses';out.mkdir(parents=True,exist_ok=True)
    inventory=[]
    wheels=json.loads((args.cache/'studio-wheels.json').read_text(encoding='utf-8'))['wheels']
    for entry in wheels:
        path=args.cache/'wheels'/entry['filename']
        if hashlib.sha256(path.read_bytes()).hexdigest().lower()!=entry['sha256'].lower():
            raise ValueError('wheel changed after publisher verification')
        notices=[]
        with zipfile.ZipFile(path) as zipped:
            for name in zipped.namelist():
                basename=Path(name).name.lower()
                if 'license' in basename or basename.startswith(('copying','notice','authors')):
                    if zipped.getinfo(name).file_size>4*1024*1024:
                        raise ValueError('Unexpected large license notice')
                    notices.append(dict(source=name,text=zipped.read(name).decode('utf-8',errors='replace')))
        output=entry['package'].replace('/','_')+'-'+entry['version']+'.json'
        (out/output).write_text(json.dumps(dict(package=entry,notices=notices),ensure_ascii=False,indent=2),encoding='utf-8')
        inventory.append(dict(package=entry['package'],version=entry['version'],file=output,notice_files=len(notices)))
    vue=root/'studio/node_modules/vue'
    meta=json.loads((vue/'package.json').read_text(encoding='utf-8'))
    (out/'vue-LICENSE.txt').write_text((vue/'LICENSE').read_text(encoding='utf-8'),encoding='utf-8')
    inventory.append(dict(package='vue',version=meta['version'],license=meta['license'],file='vue-LICENSE.txt'))
    (out/'inventory.json').write_text(json.dumps(dict(packages=inventory,note='License inventory; source wheel notices and upstream distribution licenses retained.'),ensure_ascii=False,indent=2),encoding='utf-8')
    import shutil
    shutil.copytree(out,root/'ecra/studio/web/licenses',dirs_exist_ok=True)
    print(json.dumps(dict(packages=len(inventory),output=str(out))))


if __name__=='__main__':main()
