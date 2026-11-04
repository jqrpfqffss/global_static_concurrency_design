"""Measure complete Packet construction on a sealed native authority.

full uses the unchanged builder after ordinary complete reconstruction;
control reconstructs complete original facts and only the chosen finding;
selected uses its complete per-object inputs. No model or source execution.
Both modes preserve original authority bytes. This is not a new native scan.
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


def worker(source,work,mode,write_packet=False,verify_packet=False,*,barrier=None):
    from contextlib import closing,nullcontext
    from unittest.mock import patch
    from ecra.scan_store import EvidenceProvider,connect_readonly
    from ecra.native_review_packet import packet_inputs
    from ecra.review import build_variable_review_packet
    from ecra.report_package import sha256
    before=sha256(source/'scan.db');(work/'before.json').write_text(json.dumps(dict(sha256=before))+'\n','utf-8')
    provider=EvidenceProvider(source/'scan.db')
    with closing(connect_readonly(provider.path)) as conn:
        array=provider.resolve('report',['findings'])
        row=conn.execute("SELECT fid.value,coalesce(a.length,0),member.ordinal FROM edges member "
            "JOIN edges f ON f.parent=member.child AND f.key='finding_id' JOIN nodes fid ON fid.id=f.child "
            "LEFT JOIN edges access ON access.parent=member.child AND access.key='accesses' "
            "LEFT JOIN nodes a ON a.id=access.child WHERE member.parent=? "
            "ORDER BY coalesce(a.length,0) DESC,member.ordinal LIMIT 1",(array,)).fetchone()
    if row is None:raise ValueError('原authority没有候选，不能伪造Packet')
    finding_id=row[0].decode('utf-8');root=Path(json.loads((source/'scan_state.json').read_text('utf-8'))['project_root'])
    options=dict(facts_path=source/'review/facts-navigation.json',shared_path=source/'review/project-evidence.json',report_path=source/'review/report-navigation.json')
    (work/'phase.json').write_text(json.dumps(dict(phase='PACKET_'+mode,finding_id=finding_id,accesses=row[1]))+'\n','utf-8');start=time.monotonic()
    if mode in {'full','control'}:
        facts=provider.load('facts')
        if mode=='full':report=provider.load('report');finding=report['findings'][row[2]]
        else:finding=provider.load('report',['findings',row[2]])
        packet=build_variable_review_packet(root,facts,finding,**options)
    else:
        with (nullcontext() if barrier is not None else patch.object(EvidenceProvider,'load',side_effect=AssertionError('Root reconstruction forbidden'))):
            with packet_inputs(provider.path,finding_id) as (facts,finding):
                packet=build_variable_review_packet(root,facts,finding,**options)
    if barrier is not None:
        (work/'simultaneous-ready.json').write_text(json.dumps(dict(finding_id=finding_id,packet_built=True))+'\n','utf-8')
        barrier.wait(timeout=1200)
    hashed=hashlib.sha256();size=0
    for text in json.JSONEncoder(ensure_ascii=True).iterencode(packet):
        raw=text.encode('utf-8');hashed.update(raw);size+=len(raw)
    from ecra.common import digest as old_digest,write_json
    from ecra.review_hash import digest as streamed_digest
    digest=old_digest if mode in {'full','control'} else streamed_digest
    cache_key=digest(['fixed-fingerprint-for-equivalence',packet,'fixed-prompt',{'model':'not-invoked'},'fixed-implementation'])
    if write_packet:write_json(work/'packet.input.json',packet,indent=1)
    if verify_packet:
        from ecra.review_packet import validation_packet
        from ecra.review_language import technical_identifiers
        from ecra.review_contract import stale_writeback_hints
        from ecra.review import _sha
        with (nullcontext() if barrier is not None else patch.object(Path,'read_bytes',side_effect=AssertionError('Whole Packet byte read forbidden'))):
            projected=validation_packet(work/'packet.input.json',identifiers=True)
            physical_sha256=_sha(work/'packet.input.json')
        if technical_identifiers(projected)!=technical_identifiers(packet):raise ValueError('技术标识符投影不一致')
        if json.dumps(projected.get('nvic_priorities',[]))!=json.dumps(packet.get('nvic_priorities',[])):raise ValueError('NVIC校验投影不一致')
        if json.dumps(stale_writeback_hints(projected))!=json.dumps(stale_writeback_hints(packet)):raise ValueError('写回校验投影不一致')
    seconds=time.monotonic()-start
    result=dict(passed=True,scope=__doc__,mode=mode,finding_id=finding_id,selected_accesses=row[1],
        packet_bytes=size,packet_sha256=hashed.hexdigest(),cache_key=cache_key,physical_packet_written=write_packet,
        seconds=seconds,source_bytes=provider.path.stat().st_size,
        before_sha256=before,after_sha256=sha256(provider.path),all_gates_passed=False)
    if verify_packet:result.update(receipt_projection_verified=True,physical_packet_sha256=physical_sha256)
    if result['before_sha256']!=result['after_sha256']:raise ValueError('原authority字节变化')
    (work/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n','utf-8')
    return result


def concurrent_worker(source,work,copies,write_packet,verify_packet):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from unittest.mock import patch
    from ecra.scan_store import EvidenceProvider
    from ecra.report_package import sha256
    before=sha256(source/'scan.db');(work/'before.json').write_text(json.dumps(dict(sha256=before))+'\n','utf-8')
    barrier=Barrier(copies)
    def one(index):
        folder=work/('copy-'+str(index));folder.mkdir()
        try:return worker(source,folder,'selected',write_packet,verify_packet,barrier=barrier)
        except BaseException:barrier.abort();raise
    with (patch.object(EvidenceProvider,'load',side_effect=AssertionError('Root reconstruction forbidden')),
          patch.object(Path,'read_bytes',side_effect=AssertionError('Whole Packet byte read forbidden'))):
        with ThreadPoolExecutor(max_workers=copies) as pool:
            results=list(pool.map(one,range(copies)))
    for result in results:
        if not result['passed'] or any(result[key]!=results[0][key] for key in ('finding_id','packet_bytes','packet_sha256','cache_key')):
            raise ValueError('并发完整Packet与缓存键不相同')
    after=sha256(source/'scan.db')
    if after!=before:raise ValueError('并发测试原authority变化')
    value=dict(passed=True,copies=copies,same_worst_finding_stress=True,independent_packets_held_at_barrier=True,
        results=results,before_sha256=before,after_sha256=after,all_gates_passed=False,
        scope='Repeated independent complete worst-case Packet in concurrent threads with a barrier, not different findings, full queue, saved_run or live model.')
    (work/'acceptance.json').write_text(json.dumps(value,indent=2)+'\n','utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--mode',choices=['full','control','selected'],default='selected');parser.add_argument('--job-gib',type=float,default=2)
    parser.add_argument('--write-packet',action='store_true')
    parser.add_argument('--verify-packet',action='store_true')
    parser.add_argument('--copies',type=int,default=1,help='1–8 independent simultaneous copies of the actual maximum candidate; selected mode only')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);args=parser.parse_args()
    engine=args.engine.resolve();sys.path.insert(0,str(engine))
    from ecra.workspace import no_links,studio_data_root
    source=no_links(args.source);work=studio_data_root(args.work)
    if source==work or source.is_relative_to(work) or work.is_relative_to(source):raise ValueError('验收输出必须独立于原件')
    if args.verify_packet and not args.write_packet:raise ValueError('验证实际Packet须同时--write-packet')
    if not 1<=args.copies<=8 or args.copies>1 and args.mode!='selected':raise ValueError('并发压力只支持selected模式1–8份')
    if args.worker:
        if args.copies>1:return concurrent_worker(source,work,args.copies,args.write_packet,args.verify_packet)
        return worker(source,work,args.mode,args.write_packet,args.verify_packet)
    if os.name!='nt' or not .25<=args.job_gib<=32:raise ValueError('需要实际Windows Job及0.25–32GiB预算')
    work.mkdir(exist_ok=False,parents=True)
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.write_guard import OwnedProcess
    from ecra.studio.resource_policy import temporary_environment
    from ecra.scan_diagnostics import memory
    from ecra.report_package import sha256
    state=dict(passed=False,status='RUNNING',scope=__doc__,source=str(source),engine=str(engine),mode=args.mode,
        copies=args.copies,job_limit_bytes=int(args.job_gib*1024**3),peaks={},all_gates_passed=False)
    def save():(work/'execution.json').write_text(json.dumps(state,indent=2)+'\n','utf-8')
    save();budget=ProcessBudget(state['job_limit_bytes']);process=None;started=time.monotonic()
    try:
        with (work/'console.log').open('xb') as log,(work/'resources.jsonl').open('x',encoding='utf-8') as samples:
            command=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--worker','--engine',str(engine),'--source',str(source),'--work',str(work),'--mode',args.mode]
            if args.write_packet:command.append('--write-packet')
            if args.verify_packet:command.append('--verify-packet')
            command+=['--copies',str(args.copies)]
            process=OwnedProcess(command,cwd=engine,env=temporary_environment(work,dict(os.environ,PYTHONPATH=str(engine),PYTHONHASHSEED='0',PYTHONDONTWRITEBYTECODE='1')),log=log);budget.assign(process);process.resume();state.update(pid=process.pid,command=command);save()
            while process.poll() is None:
                if (work/'stop').is_file():raise KeyboardInterrupt('观察器收到停止请求；仅关闭本次自有Job，保留原件')
                sample=budget.sample()
                for key in ('working_set_bytes','private_bytes','peak_job_commit_bytes'):state['peaks'][key]=max(state['peaks'].get(key,0),sample.get(key,0))
                samples.write(json.dumps(sample)+'\n');samples.flush();state['seconds']=time.monotonic()-started;save()
                metrics=memory();available=metrics.get('system_physical_available_bytes');limit=metrics.get('system_commit_limit_bytes');used=metrics.get('system_commit_bytes')
                if (available is not None and available<8*1024**3) or (limit is not None and used is not None and limit-used<8*1024**3):raise MemoryError('观察器主机余量不足8GiB，安全停止本次自有Job，原件保留')
                if shutil.disk_usage(work).free<1024**3:raise OSError('工作盘空闲不足1GiB')
                time.sleep(1)
            process.wait(timeout=30);state['exit_code']=process.returncode
            sample=budget.sample()
            for key in ('working_set_bytes','private_bytes','peak_job_commit_bytes'):
                state['peaks'][key]=max(state['peaks'].get(key,0),sample.get(key,0))
            samples.write(json.dumps(dict(sample,final_job_sample=True))+'\n');samples.flush()
            state.update(final_job_sampled=True,rss_measurement='Maximum sampled aggregate working set; sub-second RSS spikes may be missed')
            if process.returncode:raise RuntimeError('Worker失败；保留日志，不声明Packet通过')
        result=json.loads((work/'acceptance.json').read_text('utf-8'))
        manifest=engine.with_name(engine.name+'.sha256.json')
        if manifest.is_file():
            frozen=json.loads(manifest.read_text('utf-8'));differences=[row['file'] for row in frozen['files'] if sha256(engine/row['file'])!=row['sha256']]
            if differences:raise ValueError('冻结源码变化：'+str(differences))
            state.update(manifest_sha256=sha256(manifest),engine_differences=differences)
        state.update(passed=result['passed'],result=result,status='PASS_SCOPED',seconds=time.monotonic()-started);save()
    except BaseException:
        state.update(status='FAIL',error=traceback.format_exc(),seconds=time.monotonic()-started);save();raise
    finally:
        budget.close()
        if process is not None:process.close()
        before=work/'before.json'
        if before.is_file():
            state['original_source_postflight_sha256']=sha256(source/'scan.db')
            state['original_source_unchanged']=state['original_source_postflight_sha256']==json.loads(before.read_text('utf-8'))['sha256']
            if not state['original_source_unchanged']:
                state.update(passed=False,status='FAIL',postflight_error='原authority在观察器结束时变化')
                save();raise ValueError(state['postflight_error'])
            save()
    print(json.dumps(dict(passed=state['passed'],seconds=state['seconds'],peaks=state['peaks'])),flush=True)


if __name__=='__main__':main()
