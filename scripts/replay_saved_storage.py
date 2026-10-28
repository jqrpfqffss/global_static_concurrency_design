"""对已完整校验的事实执行存储回放；不提取 AST、不重新分析、不运行模型。"""
import argparse
from contextlib import contextmanager
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def inside(args):
    sys.path.insert(0,str(args.engine))
    for stream in (sys.stdout,sys.stderr):
        stream.reconfigure(encoding='utf-8',errors='replace')
    from ecra.common import read_json
    from ecra.workflow import read_saved_json,clean_report,file_digest,engine_digest
    from ecra.shared_json import logical_digest
    from scripts.verify_replayed_report import verify_artifacts
    result=dict(complete=False,kind='SAVED_FACTS_STORAGE_ONLY',native_acceptance=False,
        safety_report_valid=False,analysis_reexecuted=False,ast_reextracted=False,
        review_executed=False,source=str(args.source),engine_digest=engine_digest(),stages=[],
        index_mode='SEPARATE' if args.independent_plans else 'REUSED')
    receipt=args.evidence/'storage-result.json'
    dump(receipt,result)
    reserve=bytearray(8*1024*1024)
    facts=report=reviews=plan=None
    @contextmanager
    def stage(name):
        start=time.monotonic();print('阶段开始：'+name,flush=True)
        try:
            yield
        finally:
            result['stages'].append(dict(name=name,seconds=time.monotonic()-start))
            dump(receipt,result)
    try:
        source_proof=read_json(args.source/'render-proof.json')
        verified=read_json(args.source/'render-verification.json')
        if (not verified.get('complete') or verified.get('native_acceptance') is not False
                or not source_proof.get('complete')):
            raise ValueError('来源必须是已完成独立校验的受控报告，不能使用未完成事实')
        folder=args.source/'rendered'
        with stage('校验来源文件摘要'):
            if file_digest(folder/'facts.json')!=verified['facts_sha256']:
                raise ValueError('来源事实已变化，禁止复用')
            result['source_facts_sha256']=verified['facts_sha256']
            result['source_report_sha256']=file_digest(folder/'reports/global_static_concurrency.json')
        with stage('读取完整事实及静态报告'):
            facts=read_saved_json(folder/'facts.json',canonical_accesses=True)
            report=read_saved_json(folder/'reports/global_static_concurrency.json')
        codec=module('ecra._storage_candidate_codec',args.evidence/'candidate-codec.py')
        database=module('ecra._storage_candidate_report',args.evidence/'candidate-report.py')
        rendered=args.evidence/'rendered';(rendered/'inventory').mkdir(parents=True)
        (rendered/'reports').mkdir()
        dump(rendered/'result_validity.json',dict(analysis_valid=False,state='CONTROLLED_STORAGE_ONLY',
                                                native_acceptance=False,safety_report_valid=False))
        samples=report.get('review_safe_samples',[])
        if not args.independent_plans:
            with stage('建立一次完整共享索引'):
                plan=codec.Plan(dict(facts=facts,report=report,samples=samples),
                    size_roots=(facts,facts['variables'],report,report['findings'],samples))
        for name,value,path in [('完整事实',facts,rendered/'facts.json'),
                ('变量清单',facts['variables'],rendered/'inventory/global_static_inventory.json'),
                ('完整静态报告',report,rendered/'reports/global_static_concurrency.json')]:
            with stage('写入'+name):
                codec.write(path,value,plan=plan)
        with stage('写入完整 SQLite'):
            if args.independent_plans:
                database.write_database(rendered/'facts.db',facts,report)
            else:
                database.write_database(rendered/'facts.db',facts,report,shared_plan=plan)
        plan=None;gc.collect()
        with stage('核对输入事实及静态分类未变'):
            if logical_digest(facts)!=source_proof['facts_logical_digest']:
                raise ValueError('存储回放改变了完整输入事实')
            if logical_digest(clean_report(report))!=source_proof['static_report_logical_digest']:
                raise ValueError('存储回放改变了静态报告')
        facts=report=reviews=samples=value=None;gc.collect()
        with stage('独立读取输出并核对所有值及数据库'):
            validation=verify_artifacts(rendered,source_proof)
            validation.update(analysis_reexecuted=False,ast_reextracted=False,review_executed=False,
                              kind='SAVED_FACTS_STORAGE_ONLY')
            dump(args.evidence/'storage-verification.json',validation)
        result.update(complete=True,source_analysis_complete=True,
            files={p.relative_to(rendered).as_posix():p.stat().st_size for p in rendered.rglob('*') if p.is_file()})
        dump(receipt,result)
        return 0
    except BaseException as exc:
        reserve=None;facts=report=reviews=plan=None;gc.collect()
        result['error']=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        dump(receipt,result)
        traceback.print_exc()
        return 3


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','source','evidence','codec','report'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    parser.add_argument('--limit-gib',type=float,default=48)
    parser.add_argument('--independent-plans',action='store_true',help='仅用于对照：各产物独立建立索引，仍执行完整值校验')
    parser.add_argument('--inside',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    for name in ('engine','source','evidence','codec','report','python'):
        setattr(args,name,getattr(args,name).resolve())
    if args.inside:
        return inside(args)
    if args.evidence.is_relative_to(args.source) or args.source.is_relative_to(args.evidence):
        parser.error('来源与输出目录不能重叠')
    if not 0<args.limit_gib<1024:
        parser.error('诊断内存限制必须为正数且小于 1024 GiB')
    args.evidence.mkdir(parents=True,exist_ok=False)
    script=Path(__file__).resolve()
    for source,name in [(script,'harness.py'),(args.codec,'candidate-codec.py'),(args.report,'candidate-report.py')]:
        shutil.copyfile(source,args.evidence/name)
    dump(args.evidence/'input-code.json',{name:hashlib.sha256((args.evidence/name).read_bytes()).hexdigest()
        for name in ('harness.py','candidate-codec.py','candidate-report.py')})
    import psutil
    from large_stm32_scan import monitor_sample
    command=[str(args.python),'-u',str(args.evidence/'harness.py'),*sys.argv[1:],'--inside']
    peaks={};start=time.monotonic()
    with (args.evidence/'console.log').open('w',encoding='utf-8') as log, \
            (args.evidence/'memory.jsonl').open('w',encoding='utf-8') as memory:
        proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        root=psutil.Process(proc.pid)
        subprocess.Popen([sys.executable,str(script.with_name('windows_memory_limit.py')),
            '--pid',str(proc.pid),'--gib',str(args.limit_gib),'--evidence',str(args.evidence/'limit.json')],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        dump(args.evidence/'execution-start.json',dict(pid=proc.pid,created_unix=root.create_time(),command=command))
        reserve=[bytearray(256*1024)]
        while proc.poll() is None:
            monitor_sample(root,start,peaks,memory,psutil,args.evidence/'monitor-errors.log',reserve=reserve)
            time.sleep(.5)
    dump(args.evidence/'execution.json',dict(kind='SAVED_FACTS_STORAGE_ONLY',native_acceptance=False,
        pid=proc.pid,exit_code=proc.returncode,seconds=time.monotonic()-start,peaks=peaks))
    return proc.returncode


if __name__=='__main__':raise SystemExit(main())
