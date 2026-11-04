"""Original e69 combiner vs GUI-produced pinned input result; approved F030 aliases only."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
w=Path(__file__).parent;repo=Path('H:/global_static_concurrency_design');baseline=w.parent/'baseline/engine';sys.path.insert(0,str(repo))
from ecra.scan_store import EvidenceProvider,publish_json_scan
from ecra.workspace import WorkspaceResolver
from ecra.config import load_config
from ecra.report_package import sha256
from ecra.common import write_json
from scripts.compare_native_graphs import compare
work=w/'multicore-workflow-equivalence-v1';work.mkdir(exist_ok=False)
case=json.loads((w/'multicore-native-gui-v1/acceptance.json').read_text('utf-8'));gui=json.loads((w/'multicore-workflow-ui-v1-evidence/acceptance.json').read_text('utf-8'));assert case['passed'] and gui['passed']
source=Path(case['data_root'])/'scans'/gui['scan_id'];provider=EvidenceProvider(source/'scan.db');components=provider.load('provenance')['components'];root=Path(case['project_root'])
inputs=[];elfs={};source_files=[];proof=[]
for item in components:
 variant=item['variant'];raw=Path(item['config']['path']).read_bytes();cfg=json.loads(raw);original=json.loads(raw)
 cfg['analysis']['output']=dict(location='custom',custom_dir=str(work/('reference-'+variant)))
 before_cfg=json.loads(raw);before_cfg['analysis'].pop('output',None);after_cfg=json.loads(json.dumps(cfg));after_cfg['analysis'].pop('output',None)
 assert json.dumps(before_cfg,sort_keys=True,separators=(',',':'))==json.dumps(after_cfg,sort_keys=True,separators=(',',':'))
 config=work/(variant+'.yaml');write_json(config,cfg);effective,_=load_config(root,config);workspace=WorkspaceResolver.resolve(root,effective['analysis']).initialize()
 folder=Path(workspace.results_root);facts=EvidenceProvider(Path(case['data_root'])/'scans'/item['binding']['scan_id']/'scan.db').load('facts');write_json(folder/'facts.json',facts)
 inputs.append((variant,str(config)));elfs[variant]=item['elf']['path'];source_files.extend([Path(item['facts']['path']),Path(item['config']['path']),Path(item['elf']['path'])])
 proof.append(dict(variant=variant,original_config_sha256=hashlib.sha256(raw).hexdigest(),reference_config_sha256=sha256(config),only_change='analysis.output: reference-only external legacy facts folder',unchanged_effective_semantic_config_sha256=hashlib.sha256(json.dumps(before_cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest()))
spec=dict(root=str(root),inputs=inputs,regions=[[0x20000000,0x10000]],elfs=elfs,out=str(work/'old-combination'));write_json(work/'spec.json',spec)
source_files.append(source/'scan.db');before={str(p):sha256(p) for p in source_files};old_module=sha256(baseline/'ecra/multicore.py');candidate=sha256(repo/'ecra/multicore.py')
old_code="""import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);from ecra.multicore import combine
x=json.loads(Path(sys.argv[2]).read_text('utf-8'));combine(Path(x['root']),x['inputs'],x['regions'],Path(x['out']),x['elfs'])
"""
start=time.monotonic()
with (work/'old-console.log').open('xb') as log:code=subprocess.call([sys.executable,'-B','-X','utf8','-c',old_code,str(baseline),str(work/'spec.json')],cwd=baseline,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='0'),stdout=log,stderr=subprocess.STDOUT)
assert code==0,'Original combiner failed; private output retained'
publish_json_scan(work/'original.db',work/'old-combination/facts.json',work/'old-combination/reports/global_static_concurrency.json',scan_id='old-combined',project_id='reference-only')
result=compare(work/'original.db',source/'scan.db',envelope=work/'execution-envelope.jsonl');assert result['passed'],result
assert before=={str(p):sha256(p) for p in source_files}
assert sha256(baseline/'ecra/multicore.py')==old_module and sha256(repo/'ecra/multicore.py')==candidate
import ast
old=ast.parse((w/'frozen-engine-studio-v36/ecra/multicore.py').read_text('utf-8'));new=ast.parse((repo/'ecra/multicore.py').read_text('utf-8'))
algorithm_hashes={}
for name in ['_assemble','elf_objects']:
 a=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==name)
 left=ast.dump(a,include_attributes=False);right=ast.dump(b,include_attributes=False);assert left==right,name
 algorithm_hashes[name]=hashlib.sha256(right.encode()).hexdigest()
receipt=dict(passed=True,scope=__doc__,comparison=result,seconds=time.monotonic()-start,baseline_head='e69a10bbcb870dfc19a7d69cf2267774d08b3342',baseline_module_sha256=old_module,candidate_module_sha256=candidate,algorithm_AST_unchanged_from_v36=algorithm_hashes,input_config_execution_only_changes=proof,source_files_unchanged=True,gui_receipt_sha256=sha256(w/'multicore-workflow-ui-v1-evidence/acceptance.json'),all_gates_passed=False,G2='NOT_AN_INDEPENDENT_DUALCORE_INPUT')
write_json(work/'acceptance.json',receipt);print(json.dumps(dict(passed=True,seconds=receipt['seconds'],hashes=result['hashes'])),flush=True)
