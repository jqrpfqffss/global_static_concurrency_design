"""Run consecutive full scans, retain metrics/DBs and compare all evidence.

The first run may already be running under large_stm32_scan.py. Its evidence
directory can be supplied with --first-evidence; it is never assumed complete
until both its execution and validation receipts exist.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--first-evidence',type=Path)
    parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--python',type=Path,default=Path(sys.executable),help='Interpreter under test; monitor retains psutil')
    parser.add_argument('--no-cprofile',action='store_true')
    args = parser.parse_args()
    args.evidence.mkdir(parents=True,exist_ok=True)
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    modules = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.engine/'ecra').glob('*.py')}
    summary = dict(engine_files=modules,config_sha256=config_hash,python=str(args.python),
                   cprofile_enabled=not args.no_cprofile,runs=[],comparisons=[],completion_comparisons=[],complete=False)
    def save():
        (args.evidence/'acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    for number in range(1,args.runs+1):
        folder = args.first_evidence if number==1 and args.first_evidence else args.evidence/f'run{number}'
        if number==1 and args.first_evidence:
            while not (folder/'validation.json').is_file():
                time.sleep(1)
        else:
            if config_hash != hashlib.sha256(args.config.read_bytes()).hexdigest():
                raise ValueError('Configuration changed between acceptance runs')
            current = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.engine/'ecra').glob('*.py')}
            if current != modules:
                raise ValueError('Engine changed between acceptance runs')
            command = [sys.executable,str(Path(__file__).with_name('large_stm32_scan.py')),
                '--engine',str(args.engine),'--project',str(args.project),'--config',str(args.config),
                '--evidence',str(folder),'--python',str(args.python),'--no-profile']
            if args.no_cprofile:
                command.append('--no-cprofile')
            subprocess.run(command,check=False)
        execution = json.loads((folder/'execution.json').read_text(encoding='utf-8'))
        validation = json.loads((folder/'validation.json').read_text(encoding='utf-8'))
        summary['runs'].append(dict(number=number,evidence=str(folder),execution=execution,validation=validation))
        save()
        if not validation.get('acceptance_passed'):
            print(json.dumps(dict(stopped=True,run=number,reason='Full scan acceptance failed; inspect saved evidence')))
            return 3
        output = Path(validation['output'])
        current_run = json.loads((output/'run.json').read_text(encoding='utf-8'))
        if current_run.get('started') != validation['state'].get('started'):
            raise ValueError('Live output belongs to a different scan; cannot archive this acceptance run')
        # Retain native diagnostics before the next run replaces the live output.
        # Complete facts remain in each copied DB and the CLI's own snapshots.
        for name in ('run.json', 'scan_state.json', 'result_validity.json',
                     'input_manifest.json', 'input_closure.json'):
            shutil.copy2(output/name, folder/f'native-{name}')
        shutil.copytree(output/'diagnostics', folder/'native-diagnostics', dirs_exist_ok=True)
        subprocess.run([sys.executable, str(Path(__file__).with_name('summarize_large_scan.py')),
            '--evidence', str(folder), '--output-dir', str(output),
            '--json', str(folder/'metrics.json'), '--markdown', str(folder/'metrics.md')], check=True)
        if number > 1:
            previous = summary['runs'][-2]['validation']['completion']
            current = validation['completion']
            fields = ('fingerprint', 'translation_units_total', 'parsed', 'partial', 'failed',
                      'fact_counts', 'variable_accountability', 'classifications', 'snapshot_status')
            differences = {key: dict(before=previous.get(key), after=current.get(key))
                           for key in fields if previous.get(key) != current.get(key)}
            summary['completion_comparisons'].append(dict(before=number-1, after=number,
                                                          identical=not differences, differences=differences))
            save()
            if differences:
                print(json.dumps(dict(stopped=True, run=number, reason='Fingerprint or coverage differs')))
                return 5
        copied = args.evidence/f'run{number}-facts.db'
        shutil.copy2(output/'facts.db',copied)
        if number>1:
            comparison = args.evidence/f'comparison-{number-1}-{number}.json'
            proc = subprocess.run([sys.executable,str(Path(__file__).with_name('compare_scan_facts.py')),
                str(args.evidence/f'run{number-1}-facts.db'),str(copied),'--output',str(comparison)])
            summary['comparisons'].append(json.loads(comparison.read_text(encoding='utf-8')))
            save()
            if proc.returncode:
                return 4
    summary['complete'] = True
    save()
    print(json.dumps(dict(complete=True,runs=args.runs,evidence=str(args.evidence))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
