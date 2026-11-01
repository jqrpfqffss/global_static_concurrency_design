"""Encode a completed native baseline's raw JSON for bounded graph comparison.

Never re-extracts firmware or restores complete facts. This is an encoding
diagnostic, not another native G2 scan or a standard offline result package.
The original native JSON and its observer receipt remain authoritative.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.report_package import sha256
from ecra.workspace import no_links
from ecra.studio.process_budget import ProcessBudget
from ecra.studio.resource_policy import temporary_environment
from scripts.native_metrics import directory_size


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['execution','engine','work']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--limit-gib',type=int,default=2)
    args=parser.parse_args()
    if os.name!='nt' or not 1<=args.limit_gib<=8:parser.error('Actual Windows Job with1–8GiB budget required')
    execution=no_links(args.execution);original=json.loads(execution.read_text(encoding='utf-8'))
    if not original.get('complete') or original.get('validity',{}).get('analysis_valid') is not True:raise ValueError('Original native run has not completed input validation')
    source=no_links(original['output']);engine=no_links(args.engine);work=no_links(args.work)
    from ecra.config import configured_project_root
    firmware=configured_project_root(original['config'])
    if work.exists():raise FileExistsError('Preserve all previous comparison attempts')
    if any(work==root or work.is_relative_to(root) or root.is_relative_to(work) for root in [source,engine]):raise ValueError('Diagnostic output must not overlap source baseline or engine')
    if work==firmware or work.is_relative_to(firmware):raise ValueError('Comparison work cannot enter firmware')
    facts=source/'facts.json';report=source/'reports/global_static_concurrency.json'
    if not facts.is_file() or not report.is_file():raise ValueError('Complete original JSON inputs are missing')
    work.mkdir(parents=True)
    (work/'observer.py').write_bytes(Path(__file__).read_bytes())
    if shutil.disk_usage(work).free<20*1024**3:raise ValueError('Keep20GiB free before large graph conversion')
    child_work=work/'worker';child_work.mkdir();env=temporary_environment(child_work,dict(os.environ,PYTHONIOENCODING='utf-8'))
    code=r'''import json,sys,time
from pathlib import Path
engine,gate,execution,work=map(Path,sys.argv[1:5])
while not gate.is_file():time.sleep(.02)
sys.path.insert(0,str(engine))
from ecra.report_package import sha256
from ecra.scan_store import publish_json_scan,EvidenceProvider
original=json.loads(execution.read_text(encoding='utf-8'));source=Path(original['output'])
inputs=[source/'facts.json',source/'reports/global_static_concurrency.json'];before={}
for path in inputs:
 print('校验只读原始输入：'+path.name,flush=True);before[str(path)]=sha256(path)
def progress(message):print(message,flush=True)
target=work/'original-graph.db'
publish_json_scan(target,*inputs,scan_id='original-native-comparison-only',project_id='frozen-native-original',
 provenance=dict(original_execution=str(execution),execution_sha256=sha256(execution)),progress=progress)
print('逐节点/关系/投影完整校验；剩余量未知',flush=True)
provider=EvidenceProvider(target);provider.validate(deep=True)
unchanged=all(sha256(Path(path))==digest for path,digest in before.items())
result=dict(passed=unchanged,source_json_unchanged=unchanged,source_sha256=before,
 database=str(target),metadata=provider.metadata(),complete_fact_graph_restore=False,
 scope='Streaming representation of existing independently native original; not new extraction, not standard full archive')
(work/'conversion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(0 if unchanged else 1)
'''
    result=dict(complete=False,scope=__doc__,execution=str(execution),execution_sha256=sha256(execution),
        engine=str(engine),work=str(work),job_limit_bytes=args.limit_gib*1024**3,peaks={},samples=0,
        original_native_validity=original['validity'],source=str(source),temporary_root=env['TEMP'])
    result['observer_script_sha256']=sha256(work/'observer.py')
    def save():(work/'execution.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    budget=ProcessBudget(result['job_limit_bytes']);process=None;start=time.monotonic();last_disk=last_report=0;disk={}
    save()
    try:
        with (work/'console.log').open('wb') as log,(work/'resources.jsonl').open('w',encoding='utf-8') as samples:
            from ecra.studio.write_guard import OwnedProcess
            process=OwnedProcess([sys.executable,'-B','-X','utf8','-c',code,str(engine),str(work/'start'),str(execution),str(work)],cwd=engine,env=env,log=log)
            budget.assign(process);process.resume();result['pid']=process.pid;(work/'start').write_text('OWNED',encoding='ascii')
            while process.poll() is None:
                elapsed=time.monotonic()-start;sample=dict(seconds=elapsed,**budget.sample())
                from ecra.scan_diagnostics import memory
                system=memory();sample.update({k:v for k,v in system.items() if k.startswith('system_')})
                if system.get('system_commit_limit_bytes',2**63)-system.get('system_commit_bytes',0)<2*1024**3:
                    result['safety_stop']='Host commit headroom below2GiB';budget.close();break
                if not disk or elapsed-last_disk>=30:disk=directory_size(work);last_disk=elapsed
                sample['disk']=disk;sample['drive_free_bytes']=shutil.disk_usage(work).free
                for name in ['working_set_bytes','private_bytes','peak_job_commit_bytes']:
                    result['peaks'][name]=max(result['peaks'].get(name,0),sample.get(name,0))
                result.update(samples=result['samples']+1,seconds=elapsed,last=sample)
                samples.write(json.dumps(sample,separators=(',',':'))+'\n');samples.flush()
                if elapsed-last_report>=30:
                    save();print(json.dumps(dict(seconds=round(elapsed),peak_job_commit_bytes=result['peaks']['peak_job_commit_bytes'],database_logical_bytes=disk['logical_bytes'])),flush=True);last_report=elapsed
                if sample['drive_free_bytes']<8*1024**3:result['safety_stop']='Work drive free below8GiB';budget.close();break
                time.sleep(.5)
            process.wait(timeout=30)
            if budget.handle:
                result['peaks']['peak_job_commit_bytes']=max(result['peaks'].get('peak_job_commit_bytes',0),budget.sample()['peak_job_commit_bytes'])
        result.update(exit_code=process.returncode,seconds=time.monotonic()-start,final_disk=directory_size(work))
        if (work/'conversion.json').is_file():result['conversion']=json.loads((work/'conversion.json').read_text(encoding='utf-8'))
        result['complete']=process.returncode==0 and result.get('conversion',{}).get('passed') is True and 'safety_stop' not in result
        save();print(json.dumps(dict(complete=result['complete'],peaks=result['peaks'],seconds=result['seconds'])))
        return 0 if result['complete'] else 1
    except BaseException as exc:result.update(complete=False,error=str(exc),error_type=type(exc).__name__);save();raise
    finally:
        budget.close()
        if process is not None and process.poll() is None:process.wait(timeout=30)
        if process is not None:process.close()


if __name__=='__main__':raise SystemExit(main())
