"""Compare an independently generated native golden with real parsed TUs.

Uses exactly the original config file, compiler database and source paths. The
candidate's execution directory alone is redirected through WorkspaceResolver.
The original result and original engine are never opened for writing.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider
from ecra.workflow import clean_report, read_saved_json
from scripts.validate_studio_baseline import strict_difference


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    original=args.original.resolve();config=args.config.resolve()
    before={str(p.relative_to(original)):sha256(p) for p in original.rglob('*') if p.is_file()}
    state=json.loads((original/'scan_state.json').read_text(encoding='utf-8'));root=Path(state['project_root'])
    source_before={str(p.relative_to(root)):sha256(p) for p in root.rglob('*') if p.is_file()}
    config_before=sha256(config)
    code='''from pathlib import Path
from dataclasses import replace
import json,sys
from ecra.config import load_config,configured_project_root
from ecra.workspace import WorkspaceResolver
from ecra.cli import run
from ecra.common import write_json
config=Path(sys.argv[1]);data=Path(sys.argv[2]);root=configured_project_root(config);cfg,_=load_config(root,config)
analysis=dict(cfg['analysis'],output=dict(location='custom',custom_dir=str(data)))
ws=WorkspaceResolver.resolve(root,analysis).initialize()
ws=replace(ws,results_root=str(data/'scans/native-parsed-f030'),snapshots_root=str(data/'scans/native-parsed-f030/snapshots'))
out=Path(ws.results_root);out.mkdir(parents=True)
write_json(out/'storage.json',dict(version=1,scan_id='native-parsed-f030',project_id=ws.project_id,profile_id='same-original-input'))
result=run(root,config,no_review=True,scan_mode='full',_workspace=ws)
print(json.dumps(dict(exit_code=result,output=str(out))))
raise SystemExit(result if result not in (0,1,2) else 0)
'''
    started=time.monotonic()
    with (work/'candidate.log').open('w',encoding='utf-8') as log:
        child=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(config),str(work/'data')],
            cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT)
    if child.returncode:raise RuntimeError('candidate run failed; see candidate.log')
    out=work/'data/scans/native-parsed-f030';provider=EvidenceProvider(out/'scan.db');provider.validate(deep=True)
    validity=json.loads((out/'result_validity.json').read_text(encoding='utf-8'));assert validity['analysis_valid']
    old_facts=read_saved_json(original/'facts.json',canonical_accesses=True);new_facts=provider.load('facts')
    old_report=clean_report(read_saved_json(original/'reports/global_static_concurrency.json'))
    new_report=provider.load('report');envelopes={}
    for label,report in [('before',old_report),('after',new_report)]:
        envelope={key:report.pop(key,None) for key in ('generated_at','fingerprint')}
        if 'workspace' in report:
            report['workspace']=dict(report['workspace']);envelope['workspace.results_root']=report['workspace'].pop('results_root',None)
        envelope['read_timings']={}
        for name,row in report.get('coverage',{}).get('consumed_inputs',{}).items():
            if isinstance(row,dict):
                envelope['read_timings'][name]={key:row.pop(key) for key in list(row) if key.startswith('read_') and key.endswith('_ns')}
        envelopes[label]=envelope
    differences=dict(facts=strict_difference(old_facts,new_facts),report=strict_difference(old_report,new_report))
    preserved=before=={str(p.relative_to(original)):sha256(p) for p in original.rglob('*') if p.is_file()}
    source_preserved=source_before=={str(p.relative_to(root)):sha256(p) for p in root.rglob('*') if p.is_file()}
    absent={name:not (out/name).exists() for name in ['facts.json','facts.db','index.html','reports','inventory']}
    result=dict(passed=not any(differences.values()) and preserved and source_preserved and sha256(config)==config_before and all(absent.values()),
        differences=differences,original_preserved=preserved,original_source_and_git_preserved=source_preserved,
        original_hashes=before,config_sha256=config_before,legacy_outputs_absent=absent,
        tus=[dict(source_file=row['source_file'],parse_status=row['parse_status']) for row in old_facts['translation_units']],
        facts_counts={key:len(old_facts[key]) for key in ['variables','functions','accesses','calls','unknowns']},
        execution_envelopes=envelopes,seconds=time.monotonic()-started,engine=str(args.engine.resolve()),
        original=str(original),candidate=str(out),coverage_gate='PARTIAL_INDEPENDENT_SMALL_NATIVE_GOLDEN',
        large_G1_G2='NOT_VERIFIED',physical_32GB='NOT_VERIFIED')
    args.receipt.parent.mkdir(parents=True,exist_ok=True);args.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],differences=differences,tus=result['tus'],seconds=result['seconds']),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
