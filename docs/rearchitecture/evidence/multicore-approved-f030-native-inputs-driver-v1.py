"""Two actual approved F030 scans, explicit same-firmware aliases, not dual-core G2."""
import contextlib,hashlib,json,sys,time
from pathlib import Path
w=Path(__file__).parent;repo=Path('H:/global_static_concurrency_design');sys.path.insert(0,str(repo))
from ecra.config import configured_project_root
from ecra.scan_persistence import run_canonical
from ecra.scan_store import EvidenceProvider
from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256
base=w/'multicore-native-gui-v1';base.mkdir(exist_ok=False)
original_config=w/'golden-parsed-f030/semantics.yaml';cfg=json.loads(original_config.read_text('utf-8'));root=configured_project_root(original_config)
elf=w.parent/'baseline/native-build/main.elf';database=Path(cfg['analysis']['compile_database'])
files=[original_config,database,elf,*[p for p in root.rglob('*') if p.is_file()]]
before={str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in files}
engine={str(p):sha256(p) for p in (repo/'ecra').rglob('*.py')}
state=dict(passed=False,scope=__doc__,source_engine=str(repo),data_root=str(base/'data'),project_root=str(root),elf=str(elf),regions=[dict(start='0x20000000',size='0x10000')],inputs=[],all_gates_passed=False,G2='NOT_A_NEW_REAL_DUAL_CORE_INPUT')
def save():(base/'acceptance.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n','utf-8')
save();started=time.monotonic()
for index,variant in enumerate(['F030_A','F030_B']):
 candidate=json.loads(json.dumps(cfg));candidate['project']['name']='获准F030同源操作验收别名 '+variant+'（不是双核工程）';candidate['project']['root']=str(root)
 candidate['analysis']['output']=dict(location='custom',custom_dir=str(base/'data'))
 config=base/(variant+'.yaml');config.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n','utf-8')
 scan_id='native-f030-'+str(index+1);profile='native-profile-'+str(index+1)
 with (base/(variant+'-native.log')).open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):code=run_canonical(root,config,no_review=True,scan_id=scan_id,profile_id=profile)
 assert code in {0,1,2},code
 out=base/'data/scans'/scan_id;provider=EvidenceProvider(out/'scan.db');binding=provider.validate(deep=True)
 assert binding['profile_id']==profile and json.loads((out/'result_validity.json').read_text('utf-8'))['analysis_valid']
 statuses=[r['summary']['parse_status'] for r in provider.records('translation_units',limit=200)['items']]
 assert len(statuses)==4 and statuses.count('PARSED')==2 and statuses.count('PARTIAL')==2,statuses
 sid=provider.symbols()['items'][0]['symbol_id'];ReviewStore(out/'reviews.db',binding).append(sid,provider.fingerprint(sid),reviewer='多核输入保留自动化验收声明',decision='NEED_MORE_EVIDENCE',comment='仅验证输入归档和人工事件保持，不作工程安全结论')
 state['inputs'].append(dict(variant=variant,scan_id=scan_id,profile_id=profile,config=str(config),binding=binding,actual_native_exit_code=code,parse_statuses=statuses,static_sha256=sha256(out/'scan.db'),reviews_sha256=sha256(out/'reviews.db')));save()
state['original_differences']=[p for p,v in before.items() if (sha256(Path(p)),Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=v]
state['engine_differences']=[p for p,h in engine.items() if sha256(Path(p))!=h]
assert not state['original_differences'] and not state['engine_differences']
state.update(passed=True,seconds=time.monotonic()-started,engine_files=len(engine),original_files=len(before),original_elf_sha256=before[str(elf)][0],engine_hashes=engine);save()
print(json.dumps(dict(passed=True,seconds=state['seconds'],inputs=2,actual_TUs=8,source_firmware_unchanged=True,not_dualcore_G2=True)),flush=True)
