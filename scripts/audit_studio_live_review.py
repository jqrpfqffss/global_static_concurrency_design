"""Read-only acceptance of an actual Studio/OpenCode round, never a model stub.

Use on a small, authorized real project; the complete report/ledger is audited.
Raw responses may contain proprietary source. Only compact hashes and outcomes
are written to the requested receipt, not source, provider credentials or tokens.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecra.config import read_yaml
from ecra.review import verify_receipt
from ecra.review_integrity import review_targets
from ecra.review_context import review_context_section
from ecra.scan_persistence import runtime
from ecra.scan_store import EvidenceProvider


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(data,scan_id,task_id,context_marker,firmware_before,static_before):
    data=Path(data);out=data/'scans'/scan_id;folder=out/'review'
    task_folder=data/'work/tasks'/task_id
    task=json.loads((task_folder/'task.json').read_text('utf-8'))
    assert task['mode']=='review' and task['scan_id']==scan_id and task['state']=='COMPLETE', 'Task has not completed'
    # Original workflow exit=1 can mean findings, and exit=2 can mean LIKELY
    # or incomplete static coverage. Require every receipt DONE below; never
    # change those original risk/coverage states just to obtain exit=0.
    assert task['exit_code'] in {0,1,2},'Review process did not complete normally'
    cfg=read_yaml(task_folder/'semantics.yaml');root=Path(task['project_root'])
    current=runtime(out)
    rows=current['reviews'];targets=review_targets(EvidenceProvider(out/'scan.db').load('report'))
    assert rows and {r['finding_id'] for r in rows}=={f['finding_id'] for f in targets},'Full target coverage mismatch'
    assert all(r['state']=='DONE' for r in rows),'Technical failure or unfinished target'
    manifest=json.loads((task_folder/'review-materials.json').read_text('utf-8'))
    materials=manifest['documents']
    for name,entry in materials.items():assert sha(task_folder/name)==entry['sha256'],'Frozen document changed'
    case_sha=materials['concurrency_cases.md']['sha256']
    snapshot=folder/'case-library'/(case_sha+'.md')
    assert sha(snapshot)==case_sha,'Case body differs from configured material'
    background=review_context_section(task_folder/'review_context.md')
    if not background:assert (task_folder/'review_context.md').read_bytes()==b'', 'Empty-background acceptance expects an empty frozen file'
    receipts=[]
    for row in rows:
        verify_receipt(root,folder,row)
        assert not row.get('analysis_cached'),'Live acceptance must not reuse an earlier model answer'
        calls=[a for a in row['attempts'] if a['stage']=='ANALYZE']
        assert calls,'No real analysis invocation'
        successful=[]
        for attempt in calls:
            prompt=(folder/attempt['prompt_file']).read_text('utf-8')
            if background:
                assert background in prompt,'Frozen engineering background did not reach original prompt'
                if context_marker:assert context_marker in prompt,'Expected background marker missing'
            else:assert '提供的当前工程背景（待源码和运行配置核实）' not in prompt,'Empty background was replaced by another source'
            assert case_sha in prompt and 'CASE-0001' in prompt,'Configured case index missing'
            assert attempt['model']==cfg['review']['model'],'Model differs from UI-saved profile'
            events=[json.loads(line) for line in (folder/attempt['stdout_file']).read_text('utf-8').splitlines() if line.strip()]
            for event in events:
                part=event.get('part',{});state=part.get('state',{});params=state.get('input',{})
                if event.get('type')!='tool_use' or part.get('tool')!='read' or state.get('status')!='completed':continue
                requested=Path(params.get('filePath',''))
                if not requested.is_absolute():requested=root/requested
                if requested.resolve()!=snapshot.resolve():continue
                text=state.get('output','')
                assert len(text)>200 and ('CASE-' in text or '误判' in text or '排除' in text),'No case body content in tool response'
                successful.append(dict(offset=params.get('offset'),limit=params.get('limit'),output_chars=len(text),output_sha256=hashlib.sha256(text.encode()).hexdigest()))
        assert successful,'No successful case body read for '+row['finding_id']
        receipts.append(dict(finding_id=row['finding_id'],status=row['status'],case_body_reads=successful,
                             analyze_calls=len(calls),attempt_count=row['attempt_count'],source_citations=len(row['source_evidence']),
                             summary_validation=row['summary_validation']['state']))
    before=json.loads(Path(firmware_before).read_text('utf-8'))
    after=[dict(file=p.relative_to(root).as_posix(),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns,sha256=sha(p)) for p in sorted(root.rglob('*')) if p.is_file()]
    assert before==after,'Firmware files changed or new products appeared'
    assert sha(out/'scan.db')==static_before,'Static authority changed during review'
    return dict(passed=True,status='PASS_REAL_FULL_ROUND_WITH_CASE_BODY_READS',scan_id=scan_id,task_id=task_id,
                target_count=len(rows),states=dict(Counter(r['state'] for r in rows)),verdicts=dict(Counter(r['status'] for r in rows)),
                model=cfg['review']['model'],workers=cfg['review']['workers'],timeout_seconds=cfg['review']['timeout_seconds'],
                process_exit_code=task['exit_code'],overall_run_status=current.get('report',{}).get('run_status'),
                materials=materials,background_input_empty=not bool(background),frozen_background_checked_in_every_analyze_prompt=True,
                context_marker_in_every_analyze_prompt=True if context_marker else None,firmware_unchanged_files=len(after),
                static_database_sha256=static_before,receipts=receipts,
                limitations=['Automated real model/software acceptance, not human UAT or hardware execution'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('data-root','scan-id','task-id','firmware-before','static-before','output'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--context-marker',default='',help='Optional known text for nonempty project background; empty background is audited directly')
    args=parser.parse_args()
    result=audit(args.data_root,args.scan_id,args.task_id,args.context_marker,args.firmware_before,args.static_before)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({k:result[k] for k in ('passed','target_count','states','verdicts')},ensure_ascii=False))


if __name__=='__main__':main()
