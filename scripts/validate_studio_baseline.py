"""Validate a frozen legacy scan and prove complete Studio storage roundtrip.

Does not run a new native scan, mutate firmware, or claim large-project G1.
The independent frozen engine must approve its own input/engine checkpoint.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256, export_report
from ecra.workflow import read_saved_json


def strict_difference(first, second, path='$'):
    if type(first) is not type(second):
        return path + ': type'
    if isinstance(first, dict):
        if list(first) != list(second):
            return path + ': ordered keys'
        for key in first:
            result = strict_difference(first[key], second[key], path + '.' + key)
            if result:
                return result
    elif isinstance(first, list):
        if len(first) != len(second):
            return path + ': length'
        for index, (a, b) in enumerate(zip(first, second)):
            result = strict_difference(a, b, path + '[' + str(index) + ']')
            if result:
                return result
    elif (first.hex() != second.hex() if isinstance(first, float) else first != second):
        return path + ': value'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    baseline = args.baseline.resolve()
    config = baseline/'semantics.yaml'
    # Invoke original checked_scan, not a weakened validator in the candidate.
    checker = """from pathlib import Path
from ecra.config import load_config,configured_project_root
from ecra.workflow import checked_scan,output_path
import sys,json
config=Path(sys.argv[1]); root=configured_project_root(config)
cfg,_=load_config(root,config); out=output_path(root,cfg)
_,_,state=checked_scan(root,out,cfg,config,with_facts=False)
print(json.dumps(dict(output=str(out),fingerprint=state['fingerprint'])))
"""
    check = subprocess.run([sys.executable, '-B', '-c', checker, str(config)], cwd=baseline/'engine',
                           capture_output=True, text=True, encoding='utf-8', check=True)
    original = Path(json.loads(check.stdout.splitlines()[-1])['output'])
    original_hashes = {str(path.relative_to(original)): sha256(path) for path in
        [original/'facts.json', original/'reports/global_static_concurrency.json', original/'facts.db', original/'scan_state.json',
         original/'input_manifest.json', original/'input_closure.json']}
    facts = read_saved_json(original/'facts.json', canonical_accesses=True)
    report = read_saved_json(original/'reports/global_static_concurrency.json')
    root = baseline/'firmware'
    manifest = json.loads((original/'input_manifest.json').read_text(encoding='utf-8'))
    sources = []
    for name, expected in manifest.items():
        path = Path(name) if Path(name).is_absolute() else root/name
        if path.suffix.lower() in {'.c', '.cpp', '.h', '.hpp', '.s', '.ld', '.cmake'}:
            if sha256(path) != expected:
                raise ValueError('归档源码与冻结输入不同: '+name)
            raw = path.read_bytes()
            import base64
            sources.append(dict(file=name, sha256=expected, bytes_base64=base64.b64encode(raw).decode('ascii'),
                                text=raw.decode('utf-8-sig', errors='replace'), text_is_lossless=raw.decode('utf-8-sig', errors='replace').encode('utf-8')==raw))
    provenance = dict(original_engine=json.loads((baseline/'metadata.json').read_text(encoding='utf-8')),
        scan_state=json.loads((original/'scan_state.json').read_text(encoding='utf-8')),
        input_manifest=manifest, input_closure=read_saved_json(original/'input_closure.json'), archived_sources=sources,
        scope='Storage roundtrip of a real frozen 4-TU ARM scan, not a new native scan or large G1 acceptance')
    scan = args.data_root.resolve()/'scans/golden-f030'
    started = time.perf_counter()
    roots = publish_scan(scan/'scan.db', facts, report, scan_id='golden-f030', project_id='stm32f030-public',
                         provenance=provenance, validation_state='STATIC_VALIDATED')
    provider = EvidenceProvider(scan/'scan.db')
    binding = provider.validate(deep=True)
    differences = {name: strict_difference(original_value, provider.load(name)) for name, original_value in
                   [('facts', facts), ('report', report), ('provenance', provenance)]}
    ReviewStore(scan/'reviews.db', binding)
    package = args.data_root.resolve()/'exports/golden-f030.ecra-report'
    export_report(scan, package)
    preserved = all(sha256(original/path) == value for path, value in original_hashes.items())
    result = dict(passed=preserved and not any(differences.values()), scope=provenance['scope'],
        original=str(original), original_hashes=original_hashes, original_preserved=preserved,
        differences=differences, classification_differences=0 if differences['facts'] is None else 'NOT_COMPARED_SEPARATELY',
        roots={name:hashed for name,(_,hashed) in roots.items()}, sqlite_bytes=(scan/'scan.db').stat().st_size,
        standard_package_bytes=package.stat().st_size, legacy_final_bytes=sum(p.stat().st_size for p in original.rglob('*') if p.is_file()),
        seconds=time.perf_counter()-started, data_root=str(args.data_root.resolve()), package=str(package),
        real_large_project_native_comparison='NOT_VERIFIED', diff_golden='NOT_VERIFIED', performance_gate='NOT_VERIFIED')
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
