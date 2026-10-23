"""Exhaust a real extraction worker's Windows quota and verify CLI invalidation.

Disposable source only. The worker first completes actual Clang extraction,
then exhausts allocations inside Extractor.run; no mock MemoryError is raised.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def worker(args):
    sys.path.insert(0,str(args.engine))
    from ecra.extract import Extractor,main
    from ecra.scan_diagnostics import memory
    from probe_diagnostic_memory import exhaust_allocators
    original=Extractor.run
    def exhausted(self):
        facts=original(self)
        dump(args.evidence/'worker-ready.json',dict(pid=os.getpid(),memory=memory(),
             actual_clang_extraction_completed=True,counts={k:len(v) for k,v in facts.items() if isinstance(v,list)}))
        start=time.monotonic()
        while not (args.evidence/'limit.json').is_file():
            if time.monotonic()-start>30:raise RuntimeError('Worker quota setup timed out')
            time.sleep(0.05)
        exhaust_allocators()
        raise AssertionError('Quota exhaustion did not raise')
    sys.argv=['worker-memory-probe',str(args.worker_request),str(args.worker_output)]
    with patch.object(Extractor,'run',exhausted):main()


def cli(args):
    sys.path.insert(0,str(args.engine))
    from ecra import cli as commands
    root=args.evidence/'fixture'
    root.mkdir()
    (root/'app.c').write_text('int shared;void IRQ(void){shared++;}int main(void){shared++;return 0;}\n',encoding='utf-8')
    dump(root/'compile_commands.json',[dict(directory=str(root),file='app.c',
        arguments=['arm-none-eabi-gcc','-mcpu=cortex-m4','-mthumb','-c','app.c'])])
    config=root/'semantics.yaml'
    dump(config,dict(version=1,analysis=dict(compile_database='compile_commands.json'),
        contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['IRQ'])],
        review=dict(enabled=False,prepare_packets=False)))
    with (args.evidence/'baseline.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        prior=commands.run(root,config,no_review=True)
    assert prior==2,prior
    execute=commands.execute
    def actual_worker(argv,**kw):
        if 'ecra.extract' in argv and '.dependencies.' not in str(argv[-1]):
            argv=[str(args.python),'-u',str(Path(__file__).resolve()),'--engine',str(args.engine),
                '--python',str(args.python),'--evidence',str(args.evidence),'--inside-worker',
                '--worker-request',str(argv[-2]),'--worker-output',str(argv[-1])]
        return execute(argv,**kw)
    with patch.object(commands,'execute',actual_worker), \
            (args.evidence/'injected.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        code=commands.run(root,config,no_review=True)
    out=root/'.ecra'
    worker_dir=next((out/'diagnostics/workers').glob('TU-*'))
    info=json.loads((worker_dir/'exception.json').read_text(encoding='utf-8'))
    response=json.loads(next((out/'workers').glob('TU-*.response.json.metadata.json')).read_text(encoding='utf-8'))
    validity=json.loads((out/'result_validity.json').read_text(encoding='utf-8'))
    ready=json.loads((args.evidence/'worker-ready.json').read_text(encoding='utf-8'))
    result=dict(controlled_fault_injection=True,full_scan_acceptance=False,actual_worker_entry=True,
        actual_clang_extraction_completed=ready['actual_clang_extraction_completed'],
        real_allocator_exhaustion=True,experimental_extra_reserve=False,baseline_cli_exit=prior,
        failed_cli_exit=code,worker_pid=info['pid'],parent_pid=os.getpid(),worker_origin=info['origin'],
        worker_exception=response.get('worker_exception'),worker_parse_status=response['parse_status'],
        analysis_valid=validity['analysis_valid'],checkpoint_removed=not (out/'scan_state.json').exists(),
        lock_removed=not (out/'scan.lock').exists(),interpreter=sys.version,
        worker_peak_memory=info.get('peak_memory'),worker_memory=info.get('memory'))
    result['passed']=(code==3 and info['origin']=='WORKER' and info['pid']!=os.getpid() and
        info['exception_type']=='MemoryError' and response.get('worker_exception',{}).get('type')=='MemoryError' and
        validity['analysis_valid'] is False and result['checkpoint_removed'] and result['lock_removed'])
    dump(args.evidence/'result.json',result)
    return 0 if result['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','python','evidence'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--limit-mib',type=int,default=192)
    parser.add_argument('--inside-cli',action='store_true')
    parser.add_argument('--inside-worker',action='store_true')
    parser.add_argument('--worker-request',type=Path)
    parser.add_argument('--worker-output',type=Path)
    args=parser.parse_args()
    for name in ('engine','python','evidence'):setattr(args,name,getattr(args,name).resolve())
    if args.inside_worker:return worker(args)
    if args.inside_cli:return cli(args)
    if os.name!='nt':parser.error('Windows Job Object required')
    args.evidence.mkdir(parents=True,exist_ok=False)
    command=[str(args.python),'-u',str(Path(__file__).resolve()),*sys.argv[1:],'--inside-cli']
    begin=time.monotonic()
    with (args.evidence/'console.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        while not (args.evidence/'worker-ready.json').is_file():
            if process.poll() is not None:raise RuntimeError('Probe failed before worker quota; inspect console.log')
            if time.monotonic()-begin>60:
                process.terminate();raise RuntimeError('Worker setup timed out')
            time.sleep(0.05)
        ready=json.loads((args.evidence/'worker-ready.json').read_text(encoding='utf-8'))
        controller=subprocess.Popen([sys.executable,str(Path(__file__).with_name('windows_memory_limit.py')),
            '--pid',str(ready['pid']),'--gib',str(args.limit_mib/1024),'--evidence',str(args.evidence/'limit.json')],
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        code=process.wait()
        controller.wait(timeout=10)
    dump(args.evidence/'execution.json',dict(exit_code=code,seconds=time.monotonic()-begin,command=command,
        controlled_fault_injection=True,full_scan_acceptance=False))
    return code


if __name__=='__main__':raise SystemExit(main())
