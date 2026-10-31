"""Real allocated-cache cleanup; never a native large-scan G4 performance claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra import garbage_collection as gc
from ecra.common import write_json
from ecra.human_reviews import ReviewStore
from ecra.report_package import import_report,sha256
from ecra.scan_store import EvidenceProvider
from ecra.scan_diagnostics import memory
from ecra.workspace import WorkspaceResolver,no_links,studio_data_root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',type=Path,required=True)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--gib',type=int,default=50)
    parser.add_argument('--reuse-cache',action='store_true',help='保留失败日志，复用本脚本已生成且归属/容量匹配的真实缓存')
    args=parser.parse_args()
    if not 1<=args.gib<=100:raise ValueError('容量夹具要求1–100 GiB；每次独立新目录')
    case=no_links(args.case);case.mkdir(parents=True,exist_ok=args.reuse_cache)
    data=studio_data_root(case/'data')
    size=args.gib*1024**3
    if not args.reuse_cache and shutil.disk_usage(case).free<size+8*1024**3:raise ValueError('实际写入缓存及校验所需可用空间不足')
    original=sha256(args.package)
    if args.reuse_cache:
        scans=list((data/'scans').glob('*/manifest.json'))
        if len(scans)!=1 or json.loads(scans[0].read_text(encoding='utf-8')).get('import_origin')!=original:
            raise ValueError('既有容量夹具归档来源不匹配，拒绝接管')
        scan=scans[0].parent
    else:
        result=import_report(args.package,data);scan=data/'scans'/result['scan_id']
    provider=EvidenceProvider(scan/'scan.db')
    static_before=sha256(scan/'scan.db')
    store=ReviewStore(scan/'reviews.db',provider.metadata())
    history_before=store.history()
    root=case/'synthetic-cache-owner';root.mkdir(exist_ok=args.reuse_cache)
    workspace=WorkspaceResolver.resolve(root,dict(output=dict(location='custom',custom_dir=str(data)))).initialize()
    cache=no_links(Path(workspace.cache_root)/'tu-v1');cache.mkdir(parents=True,exist_ok=args.reuse_cache)
    key=hashlib.sha256(b'explicitly unused capacity-test TU cache').hexdigest()
    path=no_links(cache/(key+'.facts'))
    if not path.is_relative_to(data):raise ValueError('容量夹具路径越界')
    chunk=os.urandom(1024*1024)  # real writes; no sparse file/truncate shortcut
    hashed=hashlib.sha256();started=time.perf_counter()
    free_before=None if args.reuse_cache else shutil.disk_usage(case).free
    if args.reuse_cache:
        gc._role(data,path,'TU_CACHE')
        if path.stat().st_size!=size:raise ValueError('既有真实缓存容量不匹配')
    else:
        with path.open('xb') as stream:
            for index in range(args.gib*1024):
                stream.write(chunk);hashed.update(chunk)
                if (index+1)%1024==0:print(json.dumps(dict(written_gib=(index+1)//1024,seconds=time.perf_counter()-started)),flush=True)
            stream.flush();os.fsync(stream.fileno())
    free_written=shutil.disk_usage(case).free
    print('Collecting complete reference closure and preview',flush=True)
    proposal=gc.preview(data)
    if proposal['logical_bytes']<size:raise AssertionError('capacity fixture was not proposed')
    gc.quarantine(data,proposal['id'])
    free_quarantined=shutil.disk_usage(case).free
    print('Purging the explicitly quarantined disposable cache',flush=True)
    gc.purge(data,proposal['id'])
    free_after=shutil.disk_usage(case).free
    provider.validate(deep=True)
    preserved=(sha256(scan/'scan.db')==static_before and store.history()==history_before and sha256(args.package)==original)
    receipt=dict(passed=preserved and not path.exists() and free_after-free_quarantined>=size-512*1024**2,
        scope='Real standard F030 archive unchanged; synthetic unused TU-cache capacity fixture only. Not a native G3/G4 result.',
        allocated_logical_bytes=size,physical_free_before=free_before,physical_free_after_write=free_written,
        physical_free_after_quarantine=free_quarantined,physical_free_after_purge=free_after,
        observed_freed_bytes=free_after-free_quarantined,source_archive_unchanged=preserved,
        scan_sha256=static_before,cache_sha256=next(row['sha256'] for row in proposal['items'] if row['relative']==path.relative_to(data).as_posix()),seconds=time.perf_counter()-started,
        preview_id=proposal['id'],memory=memory())
    write_json(case/'acceptance.json',receipt)
    print(json.dumps(receipt),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
