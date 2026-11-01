"""Supervise the independent golden backup with a256MiB Windows Job cap.

The copy uses one reusable buffer. A failed prior copy can only be reused after
byte verification; old observer receipts and mismatching partial bytes survive.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.studio.process_budget import ProcessBudget
from ecra.studio.resource_policy import temporary_environment
from ecra.scan_diagnostics import memory
from ecra.workspace import no_links
from ecra.report_package import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['execution','destination','work']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--resume-receipt',type=Path)
    args=parser.parse_args()
    if os.name!='nt':parser.error('Actual Windows Job required')
    execution=no_links(args.execution);original=json.loads(execution.read_text(encoding='utf-8'))
    from ecra.config import configured_project_root
    firmware=configured_project_root(original['config']);source=no_links(original['data_root'])
    work=no_links(args.work);destination=no_links(args.destination)
    for protected in [source,firmware,TOOL,destination]:
        if work==protected or work.is_relative_to(protected) or protected.is_relative_to(work):raise ValueError('Observer cannot overlap inputs/engine/backup')
    work.mkdir(parents=True,exist_ok=False);env=temporary_environment(work,dict(os.environ,PYTHONIOENCODING='utf-8'))
    (work/'observer.py').write_bytes(Path(__file__).read_bytes());(work/'backup-helper.py').write_bytes((TOOL/'scripts/freeze_native_baseline.py').read_bytes())
    code='''import sys,time,json
from pathlib import Path
tool,gate,execution,destination,work=map(Path,sys.argv[1:6])
while not gate.is_file():time.sleep(.02)
sys.path.insert(0,str(tool))
from scripts.freeze_native_baseline import freeze
result=freeze(execution,destination,work,resume_receipt=Path(sys.argv[6]) if len(sys.argv)>6 else None)
print(json.dumps(dict(passed=result['passed'],files=result['files'],reused=result['reused_verified_files'])),flush=True)
'''
    result=dict(passed=False,scope=__doc__,job_limit_bytes=256*1024**2,execution=str(execution),
        execution_sha256=sha256(execution),destination=str(destination),backup_work=str(work/'backup'),
        resume_receipt=str(args.resume_receipt) if args.resume_receipt else None,peaks={},samples=0)
    result.update(observer_script_sha256=sha256(work/'observer.py'),backup_helper_sha256=sha256(work/'backup-helper.py'))
    def save():(work/'execution.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    process=None;budget=ProcessBudget(result['job_limit_bytes']);started=time.monotonic();last=0
    save()
    try:
        with (work/'console.log').open('wb') as log,(work/'resources.jsonl').open('w',encoding='utf-8') as samples:
            argv=[sys.executable,'-B','-X','utf8','-c',code,str(TOOL),str(work/'start'),str(execution),str(destination),str(work/'backup')]
            if args.resume_receipt:argv.append(str(no_links(args.resume_receipt)))
            from ecra.studio.write_guard import OwnedProcess
            process=OwnedProcess(argv,cwd=TOOL,env=env,log=log)
            budget.assign(process);process.resume();result['pid']=process.pid;(work/'start').write_text('OWNED',encoding='ascii')
            while process.poll() is None:
                sample=dict(seconds=time.monotonic()-started,**budget.sample())
                system=memory();sample.update({k:v for k,v in system.items() if k.startswith('system_')})
                for key in ['private_bytes','working_set_bytes','peak_job_commit_bytes']:result['peaks'][key]=max(result['peaks'].get(key,0),sample.get(key,0))
                result.update(samples=result['samples']+1,seconds=sample['seconds'],last=sample)
                samples.write(json.dumps(sample,separators=(',',':'))+'\n');samples.flush()
                if sample['seconds']-last>=30:save();print(json.dumps(dict(seconds=round(sample['seconds']),peaks=result['peaks'])),flush=True);last=sample['seconds']
                if system.get('system_commit_limit_bytes',2**63)-system.get('system_commit_bytes',0)<2*1024**3:
                    result['safety_stop']='HOST_COMMIT_HEADROOM_BELOW2GiB';budget.close();break
                time.sleep(.5)
            process.wait(timeout=30)
            if budget.handle:result['peaks']['peak_job_commit_bytes']=max(result['peaks'].get('peak_job_commit_bytes',0),budget.sample()['peak_job_commit_bytes'])
        result.update(exit_code=process.returncode,seconds=time.monotonic()-started)
        receipt=work/'backup/acceptance.json'
        if receipt.is_file():result['backup']=json.loads(receipt.read_text(encoding='utf-8'))
        result['passed']=process.returncode==0 and result.get('backup',{}).get('passed') is True and 'safety_stop' not in result
        save();print(json.dumps(dict(passed=result['passed'],peaks=result['peaks'],seconds=result['seconds'])))
        return 0 if result['passed'] else 1
    except BaseException as exc:result.update(passed=False,error=str(exc),error_type=type(exc).__name__);save();raise
    finally:
        budget.close()
        if process is not None and process.poll() is None:process.wait(timeout=30)
        if process is not None:process.close()


if __name__=='__main__':raise SystemExit(main())
