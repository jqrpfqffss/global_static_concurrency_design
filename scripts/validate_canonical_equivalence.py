"""Independent native canonical scan against the exact frozen original input."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.report_package import sha256
from ecra.workflow import read_saved_json, clean_report
from scripts.validate_studio_baseline import strict_difference


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args()
    base=args.baseline.resolve(); work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    original=next((base/'legacy-data/projects').glob('*/results'))
    names=['facts.json','facts.db','reports/global_static_concurrency.json','scan_state.json','input_manifest.json','input_closure.json']
    hashes={name:sha256(original/name) for name in names}
    # Keep the original config bytes and path, compiler, roots, sources and
    # compile DB identical. Only the explicit workspace object redirects output.
    code='''from dataclasses import replace
from pathlib import Path
import json,sys,time
from ecra.config import load_config,configured_project_root
from ecra.workspace import WorkspaceResolver
from ecra.cli import run
from ecra.common import write_json
from ecra.scan_store import EvidenceProvider
config=Path(sys.argv[1]);dest=Path(sys.argv[2]);root=configured_project_root(config)
cfg,_=load_config(root,config)
analysis=dict(cfg['analysis'],output=dict(location='custom',custom_dir=str(dest)))
ws=WorkspaceResolver.resolve(root,analysis).initialize()
out=dest/'scans/native-canonical';out.mkdir(parents=True)
ws=replace(ws,results_root=str(out))
write_json(out/'storage.json',dict(version=1,scan_id='native-canonical',project_id=ws.project_id,profile_id='default'))
started=time.perf_counter();code=run(root,config,no_review=True,_workspace=ws)
EvidenceProvider(out/'scan.db').validate(deep=True)
print(json.dumps(dict(exit_code=code,seconds=time.perf_counter()-started)))
raise SystemExit(0 if code in (0,1,2) else code)
'''
    started=time.perf_counter()
    with (work/'scan.log').open('w',encoding='utf-8') as output:
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(base/'semantics.yaml'),str(work/'data')],
                              cwd=TOOL,stdout=output,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Native scan failed: '+str(work/'scan.log'))
    current=work/'data/scans/native-canonical'
    before=read_saved_json(original/'facts.json',canonical_accesses=True)
    after=read_saved_json(current/'facts.json',canonical_accesses=True)
    reports=[clean_report(read_saved_json(path/'reports/global_static_concurrency.json')) for path in (original,current)]
    envelopes=[]
    for report in reports:
        env={key:report.pop(key,None) for key in ('generated_at','fingerprint')}
        report['workspace']=dict(report['workspace'])
        env['workspace.results_root']=report['workspace'].pop('results_root',None)
        env['input_read_timings']={}
        for path,record in report.get('coverage',{}).get('consumed_inputs',{}).items():
            if isinstance(record,dict):
                env['input_read_timings'][path]={key:record.pop(key) for key in ('read_started_ns','read_completed_ns') if key in record}
        envelopes.append(env)
    differences=dict(facts=strict_difference(before,after),static_report=strict_difference(*reports))
    preserved=all(sha256(original/name)==hashed for name,hashed in hashes.items())
    absent={name:not (current/name).exists() for name in ['facts.json','facts.db','index.html','reports','inventory']}
    receipt=dict(passed=preserved and all(absent.values()) and not any(differences.values()),
        differences=differences,original_preserved=preserved,original_hashes=hashes,legacy_outputs_absent=absent,
        execution_envelopes=envelopes,seconds=time.perf_counter()-started,
        canonical_database_bytes=(current/'scan.db').stat().st_size,output=str(current),
        scope='Real independently extracted identical frozen 4-TU ARM input; no large G1/G2/G3/G4 claim')
    (work/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ['passed','differences','original_preserved','legacy_outputs_absent','canonical_database_bytes']}))
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
