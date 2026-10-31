"""Real frozen legacy conversion and a separately labelled storage capacity test.

The golden is an existing native ARM result, not a fresh native scan. The
capacity input is synthetic JSON and cannot qualify G2/G3/G4.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))


def worker(facts,report,database):
    from ecra.scan_store import publish_json_scan,EvidenceProvider
    import psutil
    started=time.monotonic()
    publish_json_scan(database,facts,report,scan_id='capacity-json',project_id='SYNTHETIC_STORAGE_ONLY')
    process=psutil.Process(); memory=process.memory_info()
    result=dict(scope='Synthetic streamed JSON storage only, not native analysis or G3/G4',
        seconds=time.monotonic()-started,sqlite_bytes=database.stat().st_size,
        peak_working_set_bytes=getattr(memory,'peak_wset',memory.rss),
        peak_commit_bytes=getattr(memory,'peak_pagefile',memory.vms),
        variables=EvidenceProvider(database).symbols(limit=1)['total'],
        roots={row['name']:row['hash'] for row in EvidenceProvider(database).roots()})
    print(json.dumps(result));return


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--work',type=Path)
    parser.add_argument('--receipt',type=Path)
    parser.add_argument('--capacity-rows',type=int,default=50000)
    parser.add_argument('--worker',nargs=3,type=Path)
    args=parser.parse_args()
    if args.worker:return worker(*args.worker)
    if not args.baseline or not args.work or not args.receipt:parser.error('baseline, work and receipt required')
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    from ecra.report_package import sha256,export_report,import_report
    from ecra.scan_store import EvidenceProvider
    from ecra.legacy_import import convert
    from ecra.workflow import read_saved_json
    from scripts.validate_studio_baseline import strict_difference
    baseline=args.baseline.resolve()
    from shutil import copyfile
    old_receipt=json.loads((TOOL/'docs/rearchitecture/evidence/golden-roundtrip.json').read_text(encoding='utf-8'))
    source=Path(old_receipt['original']).resolve()
    if not source.is_relative_to(baseline):raise ValueError('golden source is outside the selected frozen baseline')
    before={str(p.relative_to(source)):sha256(p) for p in source.rglob('*') if p.is_file()}
    isolated_check=work/'original-check-copy';isolated_check.mkdir()
    for relative in before:
        destination=isolated_check/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        copyfile(source/relative,destination)
    checker='''from pathlib import Path
import os,sys,json
baseline=Path(sys.argv[3]).resolve()
def readonly(event,args):
    write=(event=='open' and isinstance(args[2],int) and args[2]&(os.O_WRONLY|os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_TRUNC))
    if write or event in {'os.remove','os.rename','os.mkdir','os.rmdir','os.chmod','os.utime'}:
        for item in args[:2] if event=='os.rename' else args[:1]:
            if isinstance(item,(str,bytes,os.PathLike)) and Path(os.fsdecode(item)).resolve().is_relative_to(baseline):
                raise RuntimeError('validation attempted a write to the frozen baseline: '+str(item))
sys.addaudithook(readonly)
from ecra.config import load_config,configured_project_root
from ecra.workflow import checked_scan
config=Path(sys.argv[1]);root=configured_project_root(config);cfg,_=load_config(root,config);out=Path(sys.argv[2])
_,_,state=checked_scan(root,out,cfg,config,with_facts=False)
print(json.dumps(dict(output=str(out),root=str(root),fingerprint=state['fingerprint'])))
'''
    original=subprocess.run([sys.executable,'-X','utf8','-B','-c',checker,str(baseline/'semantics.yaml'),str(isolated_check),str(baseline)],
        cwd=baseline/'engine',capture_output=True,text=True,encoding='utf-8',
        env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    (work/'original-check.log').write_text(original.stdout+'\n'+original.stderr,encoding='utf-8')
    original.check_returncode()
    original=json.loads(original.stdout.splitlines()[-1]);original['frozen_output']=str(source)
    started=time.monotonic();result=convert(source,original['root'],work/'data')
    target=work/'data/scans'/result['scan_id']; provider=EvidenceProvider(target/'scan.db')
    differences={name:strict_difference(read_saved_json(source/path),provider.load(name))
        for name,path in [('facts','facts.json'),('report','reports/global_static_concurrency.json')]}
    assert all(value is None for value in differences.values()),differences
    preserved=before=={str(p.relative_to(source)):sha256(p) for p in source.rglob('*') if p.is_file()}
    assert preserved
    package=work/'converted.ecra-report';export_report(target,package)
    imported=import_report(package,work/'viewer')
    assert EvidenceProvider(work/'viewer/scans'/imported['scan_id']/'scan.db').roots()==provider.roots()
    native_conversion=dict(passed=True,scope='Existing independent native 4-TU ARM legacy output; conversion only',
        original_engine_approved=True,original=original,original_preserved=preserved,files=len(before),
        differences=differences,seconds=time.monotonic()-started,scan_id=result['scan_id'],
        sqlite_bytes=(target/'scan.db').stat().st_size,package_bytes=package.stat().st_size,
        source_reverification=False,fresh_native_scan=False)
    # Write rows individually; neither the producer nor importer builds a
    # Python variable array or shared-node pool for this capacity measurement.
    facts=work/'capacity-facts.json';report=work/'capacity-report.json';shared=work/'capacity-shared.json'
    with facts.open('w',encoding='utf-8') as stream, shared.open('w',encoding='utf-8') as pool:
        stream.write('{"variables":[')
        pool.write('{"_ecra_shared_json":1,"reference_key":"@","pool":[')
        for index in range(args.capacity_rows):
            if index:stream.write(',');pool.write(',')
            raw=json.dumps(dict(symbol_id='CAPACITY-'+str(index),name='capacity_'+str(index),
                static_classification='UNKNOWN',definition_file='CAPACITY_ONLY.c',definition_line=index+1,
                contexts=['main','irq'],original_flags=[True,1,-0.0]),ensure_ascii=False)
            stream.write(raw);pool.write(raw)
        stream.write('],"accesses":[]}')
        pool.write('],"value":{"variables":[')
        for index in range(args.capacity_rows):
            if index:pool.write(',')
            pool.write('{"@":'+str(index)+'}')
        pool.write('],"accesses":[]}}')
    report.write_text('{"findings":[]}',encoding='utf-8')
    child=subprocess.run([sys.executable,'-B',str(Path(__file__)), '--worker',str(facts),str(report),str(work/'capacity.db')],
        cwd=TOOL,capture_output=True,text=True,encoding='utf-8',check=True)
    capacity=json.loads(child.stdout.splitlines()[-1]);assert capacity['variables']==args.capacity_rows
    capacity['input_bytes']=facts.stat().st_size+report.stat().st_size
    other=subprocess.run([sys.executable,'-B',str(Path(__file__)), '--worker',str(shared),str(report),str(work/'capacity-shared.db')],
        cwd=TOOL,capture_output=True,text=True,encoding='utf-8',check=True)
    shared_capacity=json.loads(other.stdout.splitlines()[-1]);assert shared_capacity['variables']==args.capacity_rows
    shared_capacity['input_bytes']=shared.stat().st_size+report.stat().st_size
    assert capacity['roots']==shared_capacity['roots'],'shared codec must preserve complete typed ordered evidence'
    receipt=dict(passed=True,native_legacy_conversion=native_conversion,synthetic_capacity=capacity,
        synthetic_shared_pool=shared_capacity,capacity_complete_roots_equal=True,
        protected_algorithms_modified=False,G1_large='NOT_VERIFIED',G3_32GB='NOT_VERIFIED',G4_reduction='NOT_VERIFIED')
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
