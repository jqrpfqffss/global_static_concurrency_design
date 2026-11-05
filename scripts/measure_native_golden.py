"""Measure a real native CLI run without restoring complete facts in the observer.

Windows Job accounting includes every descendant. The explicit safety memory cap
is recorded; hitting it is a controlled failure, never labelled a natural OOM.
This harness does not establish semantic equivalence, a physical 32GB test, or
the complete G4 disk gate. File allocation is a sampled lower bound excluding
directory/MFT metadata and alternate data streams. Paging rates are host-wide.
"""
import argparse
from contextlib import ExitStack
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
from ecra.common import write_json
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
    parser.add_argument('--mode',choices=['legacy','canonical','canonical-published'],required=True)
    parser.add_argument('--limit-gib',type=int,required=True)
    parser.add_argument('--scan-id',default='native-golden',help='Explicit canonical output identity; original default unchanged')
    parser.add_argument('--profile-id',default='same-golden-input')
    parser.add_argument('--reuse-tu-cache-from',type=Path,help='Explicit failed same-engine native attempt; replay preprocessing and verify every TU cache, not fresh extraction timing')
    parser.add_argument('--resume-published-from',type=Path,help='Exited incomplete public attempt on the same engine/config/data root; publish a NEW scan ID, revalidate the shared formal TU cache')
    parser.add_argument('--inject-stop-before-merge',action='store_true',help='Explicit diagnostic fault after real extraction; never a successful native benchmark')
    parser.add_argument('--classification-diagnostics',action='store_true',help='Observe classification cache sizes without changing engine inputs or results; diagnostic run, not an uninstrumented benchmark')
    args=parser.parse_args()
    from ecra.report_package import IDENTITY
    if not IDENTITY.fullmatch(args.scan_id) or not IDENTITY.fullmatch(args.profile_id):parser.error('Scan/profile identity is invalid')
    if os.name!='nt':parser.error('This measurement requires real Windows Job accounting')
    if not 2<=args.limit_gib<=32:parser.error('Choose an explicit safety cap between 2 and 32GiB')
    if args.inject_stop_before_merge and args.mode not in {'canonical','canonical-published'}:parser.error('Fault injection is canonical diagnostic only')
    if args.resume_published_from and (args.mode!='canonical-published' or args.reuse_tu_cache_from):parser.error('Published recovery requires canonical-published and cannot mix legacy cache copying')
    if args.classification_diagnostics and args.mode=='canonical-published':parser.error('Published pipeline measurement must not instrument classification')
    work=args.work.resolve()
    data=args.data_root.resolve();engine=args.engine.resolve();config=args.config.resolve()
    recovery=None
    if args.resume_published_from:
        from ecra.workspace import no_links
        import psutil
        no_links(args.data_root);no_links(args.engine);no_links(args.config)
        previous_path=no_links(args.resume_published_from);previous_file=previous_path/'execution.json'
        previous=json.loads(previous_file.read_text('utf-8'))
        if (previous.get('mode')!='canonical-published' or previous.get('complete') is not False
                or Path(previous.get('engine','')).resolve()!=engine or Path(previous.get('data_root','')).resolve()!=data
                or previous.get('config_sha256')!=sha256(config) or not data.is_dir()):
            raise ValueError('Published recovery requires identical engine/config/data root and an incomplete previous attempt')
        pid=previous.get('pid')
        if type(pid) is not int or pid<=0 or psutil.pid_exists(pid):raise ValueError('Previous worker is alive or cannot be proven exited; do not take over')
        descriptor=no_links(previous_path/'output.json');old_out=no_links(json.loads(descriptor.read_text('utf-8'))['output'])
        if old_out.parent!=data/'scans' or not (old_out/'storage.json').is_file():raise ValueError('Previous canonical output identity is missing or outside the data root')
        if (old_out/'manifest.json').exists():raise ValueError('Previous scan is already published; do not classify it as interrupted')
        if old_out.name==args.scan_id:raise ValueError('Recovery must publish a new scan ID; preserve the interrupted output')
        if (data/'scans'/args.scan_id).exists():raise FileExistsError('Recovery output already exists; preserve it and choose another scan ID')
        recovery=dict(previous_attempt=str(previous_path),previous_execution_sha256=sha256(previous_file),
            previous_descriptor_sha256=sha256(descriptor),previous_output=str(old_out),worker_proven_exited=pid,
            scope='Same-root formal cache revalidated by original preprocessing/content/engine/environment gates; restart global analysis, not arbitrary solver continuation; not cold extraction timing')
    elif data.exists():raise FileExistsError('Use a fresh data root; never mix another scan into the measurement')
    if data==engine or data.is_relative_to(engine):raise ValueError('Measurement data cannot enter the engine installation')
    from ecra.config import configured_project_root
    source=configured_project_root(config)
    if data==source or data.is_relative_to(source) or source.is_relative_to(data):
        raise ValueError('Measurement data cannot overlap the firmware input')
    if work==source or work.is_relative_to(source) or work.is_relative_to(engine):
        raise ValueError('Observer evidence cannot enter firmware or the engine installation')
    work.mkdir(parents=True,exist_ok=False)
    observer_source=Path(__file__).read_bytes();(work/'observer.py').write_bytes(observer_source)
    data.mkdir(parents=True,exist_ok=bool(recovery))
    cache_reuse=None
    if args.reuse_tu_cache_from:
        if args.mode!='canonical':raise ValueError('Cache recovery diagnostic is canonical only')
        previous_path=args.reuse_tu_cache_from.resolve();previous=json.loads((previous_path/'execution.json').read_text(encoding='utf-8'))
        if previous.get('complete') is not False or Path(previous['engine']).resolve()!=engine or previous['config_sha256']!=sha256(config):
            raise ValueError('Recovery requires a failed native attempt on exactly the same engine and config')
        from ecra.config import load_config
        from ecra.workspace import WorkspaceResolver,no_links
        from scripts.freeze_native_baseline import hash_file
        cfg,_=load_config(source,config)
        old_ws=WorkspaceResolver.resolve(source,dict(cfg['analysis'],output=dict(location='custom',custom_dir=previous['data_root'])))
        new_ws=WorkspaceResolver.resolve(source,dict(cfg['analysis'],output=dict(location='custom',custom_dir=str(data)))).initialize()
        old_cache=no_links(Path(old_ws.cache_root)/'tu-v1');new_cache=no_links(Path(new_ws.cache_root)/'tu-v1');new_cache.mkdir(parents=True)
        if not old_cache.is_dir():raise ValueError('Failed native attempt has no preserved TU cache')
        buffer=bytearray(1024**2);view=memoryview(buffer);count=total=0;started_copy=time.monotonic()
        for original in old_cache.iterdir():
            no_links(original)
            if not original.is_file() or original.suffix not in {'.facts','.json'}:raise ValueError('Unknown failed TU cache entry; retain it and investigate')
            target=new_cache/original.name
            with original.open('rb',buffering=0) as reader,target.open('xb',buffering=0) as writer:
                while size:=reader.readinto(buffer):
                    part=view[:size];written=0
                    while written<size:
                        actual=writer.write(part[written:])
                        if not actual:raise OSError('Cache copy made no progress')
                        written+=actual
                writer.flush();os.fsync(writer.fileno())
            if hash_file(original,buffer)!=hash_file(target,buffer):raise ValueError('Independent failed-TU cache copy mismatch')
            shutil.copystat(original,target);count+=1;total+=original.stat().st_size
        cache_reuse=dict(previous_attempt=str(previous_path),previous_execution_sha256=sha256(previous_path/'execution.json'),files=count,
            bytes=total,copy_seconds=time.monotonic()-started_copy,independent_copy=True,
            scope='Recovery from real native TU cache; preprocessing/input/engine/hash gates are rerun; elapsed is not cold full-extraction timing')
    # No engine imports before ownership: children wait at this gate before the
    # actual public legacy CLI or production canonical worker body is entered.
    code=r'''import sys,time,runpy,json
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
elif mode=='canonical-published':
 if Path(WorkspaceResolver.resolve(root,cfg['analysis']).workspace_root)!=data:
  raise ValueError('Published canonical config must explicitly select the measured data root')
 out=data/'scans'/sys.argv[7]
else:
 from dataclasses import replace
 from ecra.common import write_json
 ws=WorkspaceResolver.resolve(root,dict(cfg['analysis'],output=dict(location='custom',custom_dir=str(data)))).initialize()
 out=data/'scans'/sys.argv[7];out.mkdir(parents=True)
 ws=replace(ws,results_root=str(out),snapshots_root=str(out/'snapshots'))
 write_json(out/'storage.json',dict(version=1,scan_id=sys.argv[7],project_id=ws.project_id,profile_id=sys.argv[8]))
gate.with_name('output.json').write_text(json.dumps(dict(output=str(out))),encoding='utf-8')
if mode=='legacy':
 sys.argv=[str(engine/'run_ecra.py'),'--config',str(config),'--scan-mode','full','--no-review']
 runpy.run_path(str(engine/'run_ecra.py'),run_name='__main__')
elif mode=='canonical-published':
 if sys.argv[6]=='True':
  import ecra.cli as cli
  def interrupted_merge(*args,**kwargs):raise RuntimeError('EXPLICIT_DIAGNOSTIC_STOP_BEFORE_MERGE')
  cli.merge=interrupted_merge
 from ecra.scan_persistence import run_canonical
 raise SystemExit(run_canonical(root,config,no_review=True,scan_mode='full',
  scan_id=sys.argv[7],profile_id=sys.argv[8],_budget_owned=True))
else:
 import ecra.cli as cli
 if sys.argv[9]=='True':
  from ecra.evidence import EvidenceIndex
  from ecra.scan_diagnostics import memory
  original_build=EvidenceIndex.build
  classification_rows=0
  shallow_totals={}
  def observed_build(self,variable,*args,**kwargs):
   global classification_rows
   classification_rows+=1
   if classification_rows%64==1:
    value=dict(variable_ordinal=classification_rows,symbol_id=variable['symbol_id'],memory=memory(),
      issue_identity_cache=len(self.issue_identity_cache),gap_row_cache=len(self.gap_row_cache),
      issue_cache_container_bytes=sys.getsizeof(self.issue_identity_cache),gap_cache_container_bytes=sys.getsizeof(self.gap_row_cache),
      ancestor_cache_members=self.ancestor_cache_members,
      completed_evidence_shallow_bytes=dict(shallow_totals),
      scope='Diagnostic pre-build samples; shallow totals may count shared containers repeatedly and exclude nested rows/scalars, not retained-heap attribution')
    with (out/'diagnostics/classification-observations.jsonl').open('a',encoding='utf-8') as stream:
     stream.write(json.dumps(value,ensure_ascii=True)+'\n')
   result=original_build(self,variable,*args,**kwargs)
   for key,item in vars(result).items():
    shallow_totals[key]=shallow_totals.get(key,0)+sys.getsizeof(item)
   return result
  EvidenceIndex.build=observed_build
 if sys.argv[6]=='True':
  def interrupted_merge(*args,**kwargs):raise RuntimeError('EXPLICIT_DIAGNOSTIC_STOP_BEFORE_MERGE')
  cli.merge=interrupted_merge
 raise SystemExit(cli.run(root,config,no_review=True,scan_mode='full',_workspace=ws,_cache_enabled=True))
'''
    compile(code, '<owned-native-worker>', 'exec')
    result=dict(complete=False,scope=__doc__,mode=args.mode,engine=str(engine),config=str(config),
        config_sha256=sha256(config),data_root=str(data),safety_job_commit_limit_bytes=args.limit_gib*1024**3,
        controlled_limit_experiment=True,physical_32GB='NOT_VERIFIED',
        physical_disk_peak='SAMPLED_FILE_ALLOCATION_LOWER_BOUND_EXCLUDES_METADATA_ADS',
        system_paging_rate='PDH_HOST_WIDE_NOT_ATTRIBUTABLE_TO_ECRA',paging_samples_valid=0,
        canonical_scope=('Public run_canonical including final publication' if args.mode=='canonical-published' else
                         'Production CLI body, not TaskManager publication wrapper'),
        logical_disk_peak_is_sampled_lower_bound=True,recovery=recovery,cold_extraction=not bool(recovery or cache_reuse),
        started=datetime.now(timezone.utc).isoformat(),peaks={},samples=0,cache_reuse=cache_reuse,
        diagnostic_fault='STOP_BEFORE_MERGE' if args.inject_stop_before_merge else None,
        classification_diagnostics=args.classification_diagnostics)
    result['observer_script_sha256']=sha256(work/'observer.py')
    receipt=work/'execution.json'
    def save():receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    save();process=None;paging=None;budget=ProcessBudget(result['safety_job_commit_limit_bytes']);activities=ExitStack();started=time.monotonic()
    try:
        if args.mode=='canonical-published':
            from ecra.storage_activity import DataActivity
            activities.enter_context(DataActivity(data))
            activities.enter_context(DataActivity(data,exclusive=True,purpose='scan-budget'))
            if recovery:
                previous=Path(recovery['previous_attempt'])
                if (sha256(previous/'execution.json')!=recovery['previous_execution_sha256'] or
                        sha256(previous/'output.json')!=recovery['previous_descriptor_sha256']):
                    raise ValueError('Previous recovery evidence changed while acquiring scan ownership')
        import psutil
        try:paging=PagingRates()
        except OSError as exc:result.update(system_paging_rate='NOT_MEASURED',paging_error=str(exc))
        env=dict(os.environ,PYTHONIOENCODING='utf-8',GIT_OPTIONAL_LOCKS='0',ECRA_JOB_STOP_FILE=str(work/'stop'))
        if args.mode in {'canonical','canonical-published'}:
            from ecra.studio.resource_policy import temporary_environment
            owned=data/'work/native-observer'/args.scan_id;owned.mkdir(parents=True)
            env=temporary_environment(owned,env)
            result['worker_temporary_root']=env['TEMP']
        if args.mode=='canonical-published':
            env['ECRA_RESOURCE_PRESSURE_FILE']=str(work/'resource-pressure.json')
        result['output_volume_free_at_start']=shutil.disk_usage(data).free
        save()
        with (work/'console.log').open('wb') as log,(work/'resources.jsonl').open('w',encoding='utf-8') as samples:
            from ecra.studio.write_guard import OwnedProcess
            process=OwnedProcess([sys.executable,'-X','utf8','-B','-c',code,str(engine),str(work/'start'),str(config),str(data),args.mode,str(args.inject_stop_before_merge),args.scan_id,args.profile_id,str(args.classification_diagnostics)],cwd=engine,env=env,log=log)
            budget.assign(process);process.resume();result['pid']=process.pid;save();(work/'start').write_text('OWNED',encoding='ascii')
            last_disk=last_report=0;disk={}
            while process.poll() is None:
                elapsed=time.monotonic()-started;sample=dict(seconds=elapsed,**budget.sample())
                system=memory();sample.update({k:v for k,v in system.items() if k.startswith('system_')})
                commit_headroom=system.get('system_commit_limit_bytes',2**63)-system.get('system_commit_bytes',0)
                sample['system_commit_headroom_bytes']=commit_headroom
                if args.mode=='canonical-published':
                    limit=result['safety_job_commit_limit_bytes']
                    write_json(work/'resource-pressure.json',dict(parallel_limit=1 if sample.get('private_bytes',0)>=limit*.75 else 8))
                    available=system.get('system_physical_available_bytes',2**63)
                    if sample.get('private_bytes',0)>=limit*.90 or available<4*1024**3:
                        (work/'stop').write_text('OWNED_RESOURCE_PRESSURE',encoding='ascii');result['resource_stop_requested']=True
                    if available<2*1024**3:
                        result['safety_stop']='Host physical RAM below2GiB; owned Job stopped';budget.close();break
                if commit_headroom<4*1024**3:
                    (work/'stop').write_text('HOST_COMMIT_PRESSURE',encoding='ascii')
                    result['host_commit_stop_requested']=True
                if commit_headroom<2*1024**3:
                    result['safety_stop']='Host commit headroom below2GiB; not a scan Job limit result';budget.close();break
                if paging is not None:
                    sample['host_paging']=paging.sample()
                    if sample['host_paging']['available']:result['paging_samples_valid']+=1
                sample['disk_free_bytes']=shutil.disk_usage(data).free
                sample['whole_volume_used_change_bytes']=result['output_volume_free_at_start']-sample['disk_free_bytes']
                sample['volume_change_scope']='WHOLE_VOLUME_INCLUDES_UNLINKED_OPEN_TEMP_FILES_AND_OTHER_WRITERS'
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
        if args.mode=='canonical-published':
            published=out/'manifest.json' if (work/'output.json').is_file() else work/'missing-manifest.json'
            value=json.loads(published.read_text('utf-8')) if published.is_file() else {}
            result['publication']=dict(manifest_sha256=sha256(published) if published.is_file() else None,
                format=value.get('format'),state=value.get('state'),scan_id=value.get('scan_id'))
            result['complete']=result['complete'] and value.get('format')=='ECRA_LOCAL_SCAN' and value.get('state')=='STATIC_VALIDATED' and value.get('scan_id')==args.scan_id
            if (work/'output.json').is_file() and (out/'diagnostics/tu_cache.json').is_file():result['tu_cache']=json.loads((out/'diagnostics/tu_cache.json').read_text('utf-8'))
        if sha256(config)!=result['config_sha256']:raise ValueError('Frozen configuration changed during measurement')
        save();print(json.dumps(dict(complete=result['complete'],exit_code=process.returncode,seconds=result['seconds'],peaks=result['peaks'])),flush=True)
        return 0 if result['complete'] else 1
    except BaseException as exc:
        result.update(complete=False,error=str(exc),error_type=type(exc).__name__,seconds=time.monotonic()-started);save();raise
    finally:
        try:
            if paging is not None:paging.close()
            budget.close()
            if process is not None and process.poll() is None:process.wait(timeout=30)
            if process is not None:process.close()
        finally:activities.close()


if __name__=='__main__':raise SystemExit(main())
