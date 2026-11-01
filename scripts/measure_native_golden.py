"""Measure a real native CLI run without restoring complete facts in the observer.

Windows Job accounting includes every descendant. The explicit safety memory cap
is recorded; hitting it is a controlled failure, never labelled a natural OOM.
This harness does not establish semantic equivalence, a physical 32GB test, or
the complete G4 disk gate. File allocation is a sampled lower bound excluding
directory/MFT metadata and alternate data streams. Paging rates are host-wide.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.studio.process_budget import ProcessBudget
from ecra.scan_diagnostics import memory
from ecra.report_package import sha256
from scripts.native_metrics import directory_size,PagingRates


def logical_size(folder):
    # Preserve the previous helper name for existing benchmark callers.
    return directory_size(folder)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--mode',choices=['legacy','canonical'],required=True)
    parser.add_argument('--limit-gib',type=int,required=True)
    args=parser.parse_args()
    if os.name!='nt':parser.error('This measurement requires real Windows Job accounting')
    if not 2<=args.limit_gib<=32:parser.error('Choose an explicit safety cap between 2 and 32GiB')
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    data=args.data_root.resolve();engine=args.engine.resolve();config=args.config.resolve()
    if data.exists():raise FileExistsError('Use a fresh data root; never mix another scan into the measurement')
    if data==engine or data.is_relative_to(engine):raise ValueError('Measurement data cannot enter the engine installation')
    from ecra.config import configured_project_root
    source=configured_project_root(config)
    if data==source or data.is_relative_to(source) or source.is_relative_to(data):
        raise ValueError('Measurement data cannot overlap the firmware input')
    if work==source or work.is_relative_to(source) or work.is_relative_to(engine):
        raise ValueError('Observer evidence cannot enter firmware or the engine installation')
    data.mkdir(parents=True)
    # No engine imports before ownership: children wait at this gate before the
    # actual public legacy CLI or production canonical worker body is entered.
    code='''import sys,time,runpy,json
from pathlib import Path
engine,gate,config,data,mode=map(Path,sys.argv[1:6])
mode=str(mode)
while not gate.is_file():time.sleep(.02)
sys.path.insert(0,str(engine))
from ecra.config import load_config,configured_project_root
from ecra.workspace import WorkspaceResolver
root=configured_project_root(config);cfg,_=load_config(root,config)
if mode=='legacy':
 ws=WorkspaceResolver.resolve(root,cfg['analysis'])
 if Path(ws.workspace_root)!=data:raise ValueError('Legacy configuration data root does not match measurement')
 out=Path(ws.results_root)
else:
 from dataclasses import replace
 from ecra.common import write_json
 ws=WorkspaceResolver.resolve(root,dict(cfg['analysis'],output=dict(location='custom',custom_dir=str(data)))).initialize()
 out=data/'scans/native-golden';out.mkdir(parents=True)
 ws=replace(ws,results_root=str(out),snapshots_root=str(out/'snapshots'))
 write_json(out/'storage.json',dict(version=1,scan_id='native-golden',project_id=ws.project_id,profile_id='same-golden-input'))
gate.with_name('output.json').write_text(json.dumps(dict(output=str(out))),encoding='utf-8')
if mode=='legacy':
 sys.argv=[str(engine/'run_ecra.py'),'--config',str(config),'--scan-mode','full','--no-review']
 runpy.run_path(str(engine/'run_ecra.py'),run_name='__main__')
else:
 from ecra.cli import run
 raise SystemExit(run(root,config,no_review=True,scan_mode='full',_workspace=ws,_cache_enabled=True))
'''
    result=dict(complete=False,scope=__doc__,mode=args.mode,engine=str(engine),config=str(config),
        config_sha256=sha256(config),data_root=str(data),safety_job_commit_limit_bytes=args.limit_gib*1024**3,
        controlled_limit_experiment=True,physical_32GB='NOT_VERIFIED',
        physical_disk_peak='SAMPLED_FILE_ALLOCATION_LOWER_BOUND_EXCLUDES_METADATA_ADS',
        system_paging_rate='PDH_HOST_WIDE_NOT_ATTRIBUTABLE_TO_ECRA',paging_samples_valid=0,
        canonical_scope='Production CLI body, not TaskManager publication wrapper',
        logical_disk_peak_is_sampled_lower_bound=True,
        started=datetime.now(timezone.utc).isoformat(),peaks={},samples=0)
    receipt=work/'execution.json'
    def save():receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    save();process=None;paging=None;budget=ProcessBudget(result['safety_job_commit_limit_bytes']);started=time.monotonic()
    try:
        import psutil
        try:paging=PagingRates()
        except OSError as exc:result.update(system_paging_rate='NOT_MEASURED',paging_error=str(exc))
        env=dict(os.environ,PYTHONIOENCODING='utf-8',GIT_OPTIONAL_LOCKS='0')
        with (work/'console.log').open('wb') as log,(work/'resources.jsonl').open('w',encoding='utf-8') as samples:
            process=subprocess.Popen([sys.executable,'-X','utf8','-B','-c',code,str(engine),str(work/'start'),str(config),str(data),args.mode],
                cwd=engine,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            budget.assign(process);result['pid']=process.pid;save();(work/'start').write_text('OWNED',encoding='ascii')
            last_disk=last_report=0;disk={}
            while process.poll() is None:
                elapsed=time.monotonic()-started;sample=dict(seconds=elapsed,**budget.sample())
                system=memory();sample.update({k:v for k,v in system.items() if k.startswith('system_')})
                if paging is not None:
                    sample['host_paging']=paging.sample()
                    if sample['host_paging']['available']:result['paging_samples_valid']+=1
                sample['disk_free_bytes']=shutil.disk_usage(data).free
                try:sample['main_process_memory']=psutil.Process(process.pid).memory_info()._asdict()
                except psutil.NoSuchProcess:pass
                if elapsed-last_disk>=15 or not disk:
                    disk=logical_size(data);last_disk=elapsed
                sample['output_disk']=disk
                sample['output_disk_observed_seconds']=last_disk
                for key in ['working_set_bytes','private_bytes','peak_job_commit_bytes']:
                    result['peaks'][key]=max(result['peaks'].get(key,0),sample.get(key,0))
                result['peaks']['sampled_output_logical_bytes']=max(result['peaks'].get('sampled_output_logical_bytes',0),disk['logical_bytes'])
                result['peaks']['sampled_output_allocated_bytes']=max(result['peaks'].get('sampled_output_allocated_bytes',0),disk['allocated_bytes'])
                result['samples']+=1;samples.write(json.dumps(sample,separators=(',',':'))+'\n');samples.flush()
                result.update(seconds=elapsed,last=sample)
                if elapsed-last_report>=30:
                    save();last_report=elapsed;print(json.dumps(dict(seconds=round(elapsed),processes=sample['processes'],
                        tree_private_bytes=sample['private_bytes'],peak_job_commit_bytes=sample['peak_job_commit_bytes'],output_logical_bytes=disk['logical_bytes'])),flush=True)
                if sample.get('system_physical_available_bytes',2**63)<4*1024**3 or sample['disk_free_bytes']<8*1024**3:
                    result['safety_stop']='Host available RAM below 4GiB or output drive free below 8GiB';budget.close();break
                time.sleep(.5)
            process.wait(timeout=30)
            final=budget.sample() if budget.handle else {}
            result['peaks']['peak_job_commit_bytes']=max(result['peaks'].get('peak_job_commit_bytes',0),final.get('peak_job_commit_bytes',0))
            result.update(exit_code=process.returncode,seconds=time.monotonic()-started,final_output_disk=logical_size(data))
            result['peaks']['sampled_output_logical_bytes']=max(result['peaks'].get('sampled_output_logical_bytes',0),result['final_output_disk']['logical_bytes'])
            result['peaks']['sampled_output_allocated_bytes']=max(result['peaks'].get('sampled_output_allocated_bytes',0),result['final_output_disk']['allocated_bytes'])
        if (work/'output.json').is_file():
            out=Path(json.loads((work/'output.json').read_text())['output']);result['output']=str(out)
            if (out/'result_validity.json').is_file():result['validity']=json.loads((out/'result_validity.json').read_text(encoding='utf-8'))
        result['complete']=process.returncode in {0,1,2} and result.get('validity',{}).get('analysis_valid') is True and 'safety_stop' not in result
        if sha256(config)!=result['config_sha256']:raise ValueError('Frozen configuration changed during measurement')
        save();print(json.dumps(dict(complete=result['complete'],exit_code=process.returncode,seconds=result['seconds'],peaks=result['peaks'])),flush=True)
        return 0 if result['complete'] else 1
    except BaseException as exc:
        result.update(complete=False,error=str(exc),seconds=time.monotonic()-started);save();raise
    finally:
        if paging is not None:paging.close()
        budget.close()
        if process is not None and process.poll() is None:process.wait(timeout=30)


if __name__=='__main__':raise SystemExit(main())
