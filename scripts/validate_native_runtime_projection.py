"""Measure existing-authority runtime summaries in a real Windows Job.

Reads the original authority without changing it; writes only an independent
runtime scratch DB. This is not saved_run input replay, a new native scan,
whole review/Packet/Diff recovery, physical 32GB acceptance or UAT.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from unittest.mock import patch


def worker(source,work):
    from ecra.native_consumers import runtime_inputs
    from ecra.report import prepare
    from ecra.report_package import sha256
    from ecra.scan_persistence import runtime,append_runtime
    from ecra.scan_store import EvidenceProvider
    from scripts.validate_studio_baseline import strict_difference
    def phase(value):
        (work/'phase.json').write_text(json.dumps(dict(phase=value,observed=time.time()))+'\n','utf-8')
        print(value,flush=True)
    phase('ORIGINAL_COMPLETE_DATABASE_AND_RECEIPTS_SHA256')
    files=[source/name for name in ('scan.db','reviews.db','scan_state.json','manifest.json') if (source/name).is_file()]
    before={str(path):sha256(path) for path in files}
    manifest=json.loads((source/'manifest.json').read_text('utf-8'))
    expected=manifest.get('scan_sha256') or manifest.get('files',{}).get('scan.db',{}).get('sha256')
    if before[str(source/'scan.db')]!=expected:raise ValueError('原authority SHA与manifest不符')
    phase('METADATA_ONLY_ORIGINAL_SUMMARIES_AND_RUNTIME_PERSISTENCE')
    started=time.monotonic()
    with patch.object(EvidenceProvider,'load',side_effect=AssertionError('Complete authority reconstruction forbidden')):
        expected=runtime(source)
        facts,report=runtime_inputs(source)
        report['run_status']=expected['report']['run_status']
        prepare(facts,report,expected['reviews'],_runtime_only=True)
        target=work/'runtime-scratch';target.mkdir()
        append_runtime(target,report,expected['reviews'])
        actual=runtime(target)
    difference=strict_difference(expected['report'],actual['report'])
    if difference is not None:raise ValueError('完整原运行时投影不一致：'+str(difference))
    if strict_difference(expected['reviews'],actual['reviews']) is not None:raise ValueError('原AI事件投影不一致')
    seconds=time.monotonic()-started
    phase('ORIGINAL_COMPLETE_DATABASE_AND_RECEIPTS_POSTFLIGHT_SHA256')
    differences=[path for path,sha in before.items() if sha256(path)!=sha]
    if differences:raise ValueError('原authority/收据变化：'+str(differences))
    result=dict(passed=True,scope=__doc__,seconds=seconds,source_database_bytes=(source/'scan.db').stat().st_size,
        source_sha256=before,source_differences=differences,variables=len(facts['variables']),findings=len(report['findings']),
        complete_runtime_difference=difference,ai_events=len(expected['reviews']),full_reconstruction_calls=0,
        all_gates_passed=False)
    (work/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n','utf-8');phase('COMPLETE_SCOPED_RUNTIME_PROJECTION')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--job-gib',type=float,default=2)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();engine=args.engine.resolve();sys.path.insert(0,str(engine))
    from ecra.workspace import no_links,studio_data_root
    source=no_links(args.source);work=studio_data_root(args.work)
    if work==source or work.is_relative_to(source) or source.is_relative_to(work):raise ValueError('原件与验收输出必须独立')
    if args.worker:return worker(source,work)
    if not .25<=args.job_gib<=64:raise ValueError('Job预算须为0.25–64GiB')
    if os.name!='nt':raise ValueError('本控制器要求实际Windows Job，不能把其他平台称为Job实测')
    if any(path.is_file() and path.stat().st_size for path in source.glob('*-wal')):
        raise ValueError('原扫描仍有WAL，请先封存原写入者，不能在此观察器中改写原库')
    work.mkdir(parents=True,exist_ok=False)
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.write_guard import OwnedProcess
    from ecra.studio.resource_policy import temporary_environment
    from ecra.report_package import sha256
    manifest=engine.with_name(engine.name+'.sha256.json')
    state=dict(passed=False,status='RUNNING',scope=__doc__,engine=str(engine),source=str(source),
        job_limit_bytes=int(args.job_gib*1024**3),peaks={},controller_sha256=sha256(Path(__file__)),all_gates_passed=False)
    def save():(work/'execution.json').write_text(json.dumps(state,indent=2)+'\n','utf-8')
    save();budget=ProcessBudget(state['job_limit_bytes']);process=None;started=time.monotonic()
    try:
        with (work/'console.log').open('xb') as log,(work/'resources.jsonl').open('x',encoding='utf-8') as samples:
            command=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--worker','--engine',str(engine),'--source',str(source),'--work',str(work)]
            env=temporary_environment(work,dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='0',PYTHONPATH=str(engine)))
            process=OwnedProcess(command,cwd=engine,env=env,log=log);budget.assign(process);process.resume()
            state.update(pid=process.pid,command=command);save()
            while process.poll() is None:
                sample=budget.sample()
                for key in ('working_set_bytes','private_bytes','peak_job_commit_bytes'):
                    state['peaks'][key]=max(state['peaks'].get(key,0),sample.get(key,0))
                state['seconds']=time.monotonic()-started;save();samples.write(json.dumps(sample)+'\n');samples.flush()
                if shutil.disk_usage(work).free<1024**3:raise OSError('验收工作盘空闲不足1GiB；保留原件和本次失败证据')
                time.sleep(1)
            process.wait(timeout=30)
            state['exit_code']=process.returncode
            if process.returncode!=0:raise RuntimeError('Worker失败，请查console.log；未声明通过')
        result=json.loads((work/'acceptance.json').read_text('utf-8'))
        if manifest.is_file():
            frozen=json.loads(manifest.read_text('utf-8'));differences=[row['file'] for row in frozen['files'] if sha256(engine/row['file'])!=row['sha256']]
            if differences:raise ValueError('冻结源码变化：'+str(differences))
            state.update(manifest_sha256=sha256(manifest),engine_differences=differences)
        if sha256(Path(__file__))!=state['controller_sha256']:raise ValueError('观察器在执行期间变化')
        state.update(passed=result['passed'],status='PASS_SCOPED',result=result,seconds=time.monotonic()-started);save()
    except BaseException:
        state.update(status='FAIL',error=traceback.format_exc(),seconds=time.monotonic()-started);save();raise
    finally:
        budget.close()
        if process is not None:process.close()
    print(json.dumps(dict(passed=state['passed'],peaks=state['peaks'],seconds=state['seconds'])),flush=True)


if __name__=='__main__':main()
