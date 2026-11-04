"""Real four-TU extraction on an independent copy of approved F030 sources.

Same logical paths/commands for original vs frozen workers in this new copy.
No claim of original-path golden full scan, formal dirty Diff or new G2 input.
"""
import hashlib,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
repo=Path('H:/global_static_concurrency_design');sys.path.insert(0,str(repo))
from ecra.report_package import sha256
from ecra.config import load_config
from ecra.workspace import formal_workspace
from ecra.git_diff import relocate_paths
from ecra import working_snapshot,working_compiler_view
from ecra.analysis import merge,analyze
from ecra.input_snapshot import InputSnapshot,SOURCE_READS,read_analysis_bytes
from ecra.initialization import constructor_map_directory
from scripts.validate_studio_baseline import strict_difference

w=Path(__file__).parent;work=w/'working-view-approved-f030-v3';work.mkdir(exist_ok=False)
original=w.parent/'baseline/firmware';config_origin=w/'golden-parsed-f030/semantics.yaml'
files=[config_origin,w.parent/'baseline/compile_commands.json',*[p for p in original.rglob('*') if p.is_file()]]
inputs_before={str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in files}
engine={p.relative_to(repo).as_posix():sha256(p) for p in (repo/'ecra').rglob('*.py')}
state=dict(passed=False,scope=__doc__,all_gates_passed=False,units=[],source_engine_hashes=engine,
           original_files=len(inputs_before),controller_sha256=sha256(Path(__file__)),formal_dirty_enabled=False)
def save():(work/'acceptance.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n','utf-8')
save();started=time.monotonic()
try:
 root=work/'firmware';shutil.copytree(original,root)
 def git(*args):
  result=subprocess.run(['git','-c','core.autocrlf=false','-C',str(root),*args],capture_output=True,timeout=120)
  assert result.returncode==0,result.stderr;return result.stdout
 git('init','-q');git('config','user.name','ECRA automated private copy validation');git('config','user.email','validation@example.invalid')
 git('config','core.autocrlf','false');git('add','.');git('commit','-qm','Independent approved source copy; no original repository changes')
 # Deliberately dirty only the new private repository, without altering any
 # compiled source: staged and unstaged bytes differ, plus an ignored input.
 marker=root/'working-capture-validation.txt';marker.write_text('staged input audit\n','utf-8');git('add',marker.name)
 marker.write_text('actual working input audit\n','utf-8')
 cfg=json.loads(config_origin.read_text('utf-8'));cfg['project']['root']=str(root)
 cfg['analysis']['output']=dict(location='custom',custom_dir=str(work/'data'))
 config=work/'semantics.json';config.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n','utf-8')
 cfg,_=load_config(root,config);ws=formal_workspace(root,cfg['analysis']).initialize();ws.bind(cfg['analysis'])
 source_case=w/'multicore-native-gui-v1/data/scans/native-f030-1/workers'
 units=[];external=[]
 for p in sorted(source_case.glob('TU-*.request.json')):
  if '.dependencies.' in p.name or '.verification.' in p.name:continue
  record=json.loads(p.read_text('utf-8'));unit=relocate_paths(record['unit'],original,root)
  assert unit['source_file'] in ['startup.c','main.c','utils.c','peripheral.c']
  units.append(unit)
  for value in [unit['directory'],*unit.get('system_include_dirs',[])]:
   if value not in external:external.append(value)
 assert len(units)==4
 private_before={str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
 external_before={str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for directory in external for p in Path(directory).rglob('*') if p.is_file()}
 state['external_directories']=external;state['external_files']=len(external_before);save()
 captured=working_snapshot.capture(root,cfg)
 descriptor=working_compiler_view.create(captured,root,cfg,external_directories=[Path(p) for p in external],external_files=[config,Path(cfg['analysis']['compile_database'])])
 state['descriptor']=descriptor;save()
 results={'original':[],'frozen':[]}
 for index,unit in enumerate(units):
  row=dict(tu_id=unit['tu_id'],source=unit['source_file'])
  for mode in ['original','frozen']:
   request=work/(str(index)+'-'+mode+'-request.json');response=work/(str(index)+'-'+mode+'-response.json')
   payload=dict(root=str(root),config=cfg,unit=unit,verify_inputs=True)
   if mode=='frozen':payload['compiler_view']=descriptor
   request.write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
   tick=time.monotonic()
   with (work/(str(index)+'-'+mode+'.log')).open('xb') as log:
    code=subprocess.call([sys.executable,'-B','-X','utf8','-m','ecra.extract',str(request),str(response)],cwd=repo,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
   result=json.loads(response.read_text('utf-8'));assert code==0 and not result.get('worker_exception'),result.get('worker_exception')
   results[mode].append(result);row[mode]=dict(parse_status=result['parse_status'],seconds=time.monotonic()-tick,request_sha256=sha256(request),response_sha256=sha256(response))
  difference=strict_difference(results['original'][-1],results['frozen'][-1]);assert difference is None,difference
  row['full_typed_ordered_difference']=difference;state['units'].append(row);save()
 left=merge(results['original']);right=merge(results['frozen']);assert strict_difference(left,right) is None
 statuses=[row['original']['parse_status'] for row in state['units']]
 assert statuses.count('PARSED')==2 and statuses.count('PARTIAL')==2,statuses
 coverage=dict(translation_units_total=4,translation_units_failed=0,translation_units_partial=2,translation_units_parsed=2)
 before_report=analyze(left,cfg,coverage)
 with working_compiler_view.ParentFiles(descriptor,root,cfg) as parent_files:
  explicit=[config,Path(cfg['analysis']['compile_database']),*[Path(unit['source']) for unit in units]]
  parent=InputSnapshot(root,work/'frozen-parent-diagnostics',explicit,file_view=parent_files)
  for unit,payload in zip(units,results['frozen']):parent.discover(unit,payload['input_snapshot'],payload['preprocessor_signature'])
  parent.register_selection(constructor_map_directory(root,cfg),'*.map')
  parent.seal();token=SOURCE_READS.set(parent)
  try:
   for path in explicit:assert read_analysis_bytes(path)==path.read_bytes()
   after_report=analyze(right,cfg,coverage)
  finally:SOURCE_READS.reset(token)
  parent.verify_disk();parent.assert_valid();parent.finalize_parent_inputs();parent.save()
  state['frozen_parent']=dict(input_closure_sha256=sha256(work/'input_closure.json'),parent_reads=parent.parent_reads,
    source_changes_sha256=sha256(work/'frozen-parent-diagnostics/source_changes.json'),status=parent.status,
    formal_dirty_enabled=False,original_final_reverification_required=True)
 assert strict_difference(before_report,after_report) is None
 def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
 state['complete_merged_facts']=dict(before=digest(left),after=digest(right),difference=None)
 state['complete_analysis_report']=dict(before=digest(before_report),after=digest(after_report),difference=None)
 state['view_validation']=working_compiler_view.validate(descriptor,root,cfg)
 for name,before in [('approved_original',inputs_before),('private_dirty_git_copy',private_before),('external_build_and_SDK',external_before)]:
  differences=[p for p,value in before.items() if (sha256(Path(p)),Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=value]
  assert not differences,(name,differences);state[name+'_differences']=differences
 assert engine=={p.relative_to(repo).as_posix():sha256(p) for p in (repo/'ecra').rglob('*.py')}
 assert sha256(Path(__file__))==state['controller_sha256']
 state.update(passed=True,seconds=time.monotonic()-started,actual_worker_processes=8,engine_differences=[],G2='SAME_APPROVED_SOURCE_COPY_NOT_NEW_INPUT')
 save();print(json.dumps(dict(passed=True,units=len(units),processes=8,seconds=state['seconds'],facts_difference=0,report_difference=0)),flush=True)
except BaseException:
 state.update(error=traceback.format_exc(),seconds=time.monotonic()-started);save();raise
