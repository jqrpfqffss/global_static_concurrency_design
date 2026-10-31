"""Independent native candidate extraction on a frozen real baseline input.

Only the listed execution-envelope fields differ by contract. No fact field,
array, relation or static classification is sorted or removed.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from scripts.validate_studio_baseline import strict_difference
from ecra.workflow import read_saved_json, clean_report
from ecra.report_package import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--name',default='native-candidate-comparison')
    args=parser.parse_args()
    baseline=args.baseline.resolve()
    original=next((baseline/'legacy-data/projects').glob('*/results'))
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.name):raise ValueError('Invalid comparison directory name')
    new=original.parent/args.name
    if new.exists():raise FileExistsError('Comparison output already exists; preserve it')
    original_hashes={str(p.relative_to(original)):sha256(p) for p in [original/'facts.json',original/'facts.db',original/'reports/global_static_concurrency.json']}
    run_code="""from pathlib import Path
import json,sys,time
from ecra.config import load_config,configured_project_root
from ecra.workspace import WorkspaceResolver
from ecra.cli import run
config=Path(sys.argv[1]);root=configured_project_root(config);cfg,_=load_config(root,config)
ws=WorkspaceResolver.resolve(root,cfg['analysis']).for_results(Path(sys.argv[2])).initialize()
started=time.perf_counter();code=run(root,config,no_review=True,scan_mode='full',_workspace=ws)
print(json.dumps(dict(exit_code=code,seconds=time.perf_counter()-started)))
raise SystemExit(code if code not in (0,1,2) else 0)
"""
    log=new.parent/(args.name+'.log')
    with log.open('w',encoding='utf-8') as stream:
        result=subprocess.run([sys.executable,'-B','-c',run_code,str(baseline/'semantics.yaml'),str(new)],
            cwd=args.candidate,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError('Native candidate failed; see '+str(log))
    facts_before=read_saved_json(original/'facts.json',canonical_accesses=True)
    facts_after=read_saved_json(new/'facts.json',canonical_accesses=True)
    report_before=clean_report(read_saved_json(original/'reports/global_static_concurrency.json'))
    report_after=clean_report(read_saved_json(new/'reports/global_static_concurrency.json'))
    envelopes={}
    for name,report in [('before',report_before),('after',report_after)]:
        envelope={key:report.pop(key,None) for key in ('generated_at','fingerprint')}
        workspace=report.get('workspace')
        if workspace:
            report['workspace']=dict(workspace)
            envelope['workspace.results_root']=report['workspace'].pop('results_root',None)
        # These are tool-side buffer-read audit timestamps, never source
        # initialization/protection ordering. Keep every raw value in the
        # envelope and retain status/hash/size in the semantic comparison.
        envelope['input_read_timings']={}
        for path,record in report.get('coverage',{}).get('consumed_inputs',{}).items():
            if isinstance(record,dict):
                envelope['input_read_timings'][path]={key:record.pop(key) for key in
                    ('read_started_ns','read_completed_ns') if key in record}
        envelopes[name]=envelope
    differences=dict(facts=strict_difference(facts_before,facts_after),static_report=strict_difference(report_before,report_after))
    preserved=all(sha256(original/name)==hashed for name,hashed in original_hashes.items())
    receipt=dict(passed=preserved and not any(differences.values()),differences=differences,
        execution_envelope=envelopes,source_original_preserved=preserved,original_hashes=original_hashes,
        native_candidate=str(new),log=str(log),log_sha256=sha256(log),
        scope='Two independently extracted scans of the identical real 4-TU STM32F030 ARM input; not large G1/G2/G3/G4',
        validation=json.loads((new/'result_validity.json').read_text(encoding='utf-8')),
        original_run=json.loads((original/'run.json').read_text(encoding='utf-8')),
        candidate_run=json.loads((new/'run.json').read_text(encoding='utf-8')))
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=receipt['passed'],differences=differences)))
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
