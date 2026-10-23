"""Read active/full-scan evidence without loading facts or large memory logs."""
import argparse
import json
from pathlib import Path
import re
import sys


def tail(path, size=65536):
    if not path.is_file():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-size))
        return stream.read().decode('utf-8',errors='replace')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence',type=Path,nargs='+')
    args = parser.parse_args()
    for folder in args.evidence:
        console = tail(folder/'console.log')
        units = re.findall(r'Clang (\d+)/(\d+)',console)
        discovery = re.findall(r'依赖快照 (\d+)/(\d+)',console)
        phases = re.findall(r'阶段开始：([^\r\n]+)',console)
        result = dict(run=folder.name,phase=phases[-1] if phases else '等待阶段日志',
                      clang=units[-1] if units else None,dependencies=discovery[-1] if discovery else None)
        memory_files=[path for path in (folder/'memory.jsonl',folder/'memory-recovered.jsonl') if path.is_file()]
        memory_file=max(memory_files,key=lambda path:path.stat().st_mtime) if memory_files else folder/'memory.jsonl'
        for line in reversed(tail(memory_file).splitlines()):
            try: sample=json.loads(line)
            except json.JSONDecodeError: continue
            result['seconds']=round(sample.get('seconds',0))
            if sample.get('processes'):
                mem=sample['processes'][0]['memory']
                result.update(private_mib=round(mem.get('private',mem.get('vms',0))/2**20),
                              working_set_mib=round(mem['rss']/2**20),peak_commit_mib=round(mem.get('peak_pagefile',0)/2**20))
            commit=sample.get('system_commit_bytes',{})
            if commit:result['system_commit_free_gib']=round((commit['CommitLimit']-commit['CommitTotal'])/2**30,2)
            break
        if (folder/'execution.json').is_file():
            execution=json.loads((folder/'execution.json').read_text(encoding='utf-8'))
            elapsed=execution.get('seconds')
            result.update(exit_code=execution.get('exit_code'),
                          seconds=round(elapsed) if isinstance(elapsed,(int,float)) else None)
            if execution.get('exit_status_unknown'):
                result['exit_status_unknown']=True
            if execution.get('measurement_gap'):
                result['measurement_gap']=True
        if (folder/'validation.json').is_file():
            validation=json.loads((folder/'validation.json').read_text(encoding='utf-8'))
            result.update(accepted=validation['acceptance_passed'],parse_rates=validation.get('parse_rates'))
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
