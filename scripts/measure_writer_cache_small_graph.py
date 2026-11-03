"""Complete real F030 graph encoding A/B; not native scan or large performance."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
r=Path(__file__).resolve().parents[1];sys.path.insert(0,str(r))
parser=argparse.ArgumentParser(description=__doc__)
for name in ['before-engine','after-engine','scan','work']:parser.add_argument('--'+name,type=Path,required=True)
args=parser.parse_args()
from ecra.studio.process_budget import ProcessBudget
from ecra.studio.write_guard import OwnedProcess
from ecra.workspace import studio_data_root,no_links
source=no_links(args.scan);work=studio_data_root(args.work)
if source.stat().st_size>64*1024**2:raise ValueError('This complete SMALL-graph A/B proof refuses source databases above64MiB; use the native large observer, never truncate inputs')
work.mkdir(parents=True,exist_ok=False)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
 return h.hexdigest()
source_sha=sha(source)
code=r'''
import hashlib,json,sqlite3,sys,time
from pathlib import Path
engine,source,folder=map(Path,sys.argv[1:]);sys.path.insert(0,str(engine))
from ecra.scan_store import EvidenceProvider,publish_scan
provider=EvidenceProvider(source);binding=provider.metadata()
facts,report,provenance=[provider.load(name) for name in ['facts','report','provenance']]
statements=[];original_connect=sqlite3.connect
def observed_connect(*args,**kwargs):
 conn=original_connect(*args,**kwargs)
 if str(args[0]).endswith('.pending'):
  conn.set_trace_callback(lambda statement:statements.append(statement) if 'PRAGMA' in statement.upper() and 'CACHE_SIZE' in statement.upper() else None)
 return conn
sqlite3.connect=observed_connect
start=time.monotonic();target=folder/'scan.db'
publish_scan(target,facts,report,scan_id=binding['scan_id'],project_id=binding['project_id'],profile_id=binding['profile_id'],provenance=provenance,validation_state=binding['state'])
seconds=time.monotonic()-start;after=EvidenceProvider(target);after.validate(deep=True)
assert after.metadata()==binding
before_roots={row['name']:row['hash'] for row in provider.roots()};after_roots={row['name']:row['hash'] for row in after.roots()}
assert after_roots==before_roots
result=dict(passed=True,engine=str(engine),scan_store_sha256=hashlib.sha256((engine/'ecra/scan_store.py').read_bytes()).hexdigest(),sqlite_version=sqlite3.sqlite_version,publication_seconds=seconds,actual_cache_pragmas=statements,roots=after_roots,full_typed_graphs_restored=True,scope='Complete approved F030 facts/report/provenance encoding only; no partial facts, no large/native or physical32GB claim')
(folder/'result.json').write_text(json.dumps(result,indent=2)+'\n','utf-8')
'''
(work/'observer.py').write_text(code,'utf-8')
result=dict(passed=False,scope=__doc__,source=str(source),source_sha256_before=source_sha,cases=[])
for name,engine in [('writer8MiB',no_links(args.before_engine)),('writer64MiB',no_links(args.after_engine))]:
 folder=work/name;folder.mkdir();budget=ProcessBudget(2*1024**3);process=None
 try:
  with (folder/'console.log').open('xb') as log:
   command=[sys.executable,'-B','-X','utf8',str(work/'observer.py'),str(engine),str(source),str(folder)]
   process=OwnedProcess(command,cwd=engine,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='0'),log=log)
   budget.assign(process);process.resume();peak=0
   while process.poll() is None:
    sample=budget.sample();peak=max(peak,sample.get('peak_job_commit_bytes',0));time.sleep(.1)
   process.wait(30);sample=budget.sample();peak=max(peak,sample.get('peak_job_commit_bytes',0));assert process.returncode==0
  receipt=json.loads((folder/'result.json').read_text('utf-8'));assert receipt['passed']
  receipt.update(name=name,job_peak_commit_bytes=peak,database_bytes=(folder/'scan.db').stat().st_size,database_sha256=sha(folder/'scan.db'))
  result['cases'].append(receipt)
 finally:
  budget.close()
  if process:process.close()
one,two=result['cases'];assert one['actual_cache_pragmas'][0]=='PRAGMA cache_size=-8192' and two['actual_cache_pragmas'][0]=='PRAGMA cache_size=-65536'
result.update(source_sha256_after=sha(source),complete_database_bytes_identical=one['database_sha256']==two['database_sha256'],all_roots_identical=one['roots']==two['roots'])
result['passed']=result['source_sha256_after']==source_sha and result['complete_database_bytes_identical'] and result['all_roots_identical']
result['performance_claim']='NOT_VERIFIED_LARGE; small complete F030 graph and OS cache/concurrency cannot establish large speedup'
(work/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n','utf-8')
print(json.dumps(result),flush=True);raise SystemExit(0 if result['passed'] else 1)
