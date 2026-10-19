"""Audit saved real artifacts, source receipts and Chinese reports without a model.

Run after the configured project's review completes:
  py -3.10 scripts/audit_nvic_acceptance.py
"""
from pathlib import Path
import collections
import json
import re
import sqlite3
import sys
from html.parser import HTMLParser

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.common import read_json,write_json
from ecra.config import load_config,configured_project_root
from ecra.review import verify_receipt
from ecra.review_contract import validate_nvic_missing_facts
from ecra.review_language import language_issues,is_english_prose
from ecra.workflow import checked_scan,output_path


class VisibleProse(HTMLParser):
    def __init__(self):
        super().__init__();self.depth=0;self.skip=[];self.failures=[]
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','pre','code'}:self.skip.append(tag)
    def handle_endtag(self,tag):
        if self.skip and self.skip[-1]==tag:self.skip.pop()
    def handle_data(self,data):
        if not self.skip and len(re.findall(r'\b[A-Za-z]+\b',data))>=5 and is_english_prose(data):
            self.failures.append(data.strip())


def main():
    root=configured_project_root().resolve()
    cfg,config=load_config(root)
    out=output_path(root,cfg)
    facts,static,state=checked_scan(root,out,cfg,config)
    report=read_json(out/'reports/global_static_concurrency.json')
    rows=read_json(out/'review/queue.json')
    assert len(rows)==len(report['findings'])
    assert all(r['state']=='DONE' for r in rows),collections.Counter(r['state'] for r in rows)
    assert report['review_integrity']['all_done'],report['review_integrity']
    for row in rows:
        assert row['scan_fingerprint']==state['fingerprint']
        answer=verify_receipt(root,out/'review',row)
        assert not language_issues(answer)
        packet=read_json(out/'review'/row['packet_file'])
        assert packet['nvic_priorities']==facts['nvic_priorities']
        validate_nvic_missing_facts(answer,packet)
    for name in ('index.html','opencode_review.html'):
        text=(out/name).read_text('utf-8')
        parser=VisibleProse();parser.feed(text)
        assert not parser.failures,(name,parser.failures)
        assert '中断优先级、分组及配置调用链' in text
    markdown_files=sorted((out/'reports').glob('*.md'))+sorted((out/'inventory').glob('*.md'))
    for path in markdown_files:
        text=re.sub(r'```[\s\S]*?```','',path.read_text('utf-8'))
        failures=[line for line in text.splitlines() if len(re.findall(r'\b[A-Za-z]+\b',line))>=5 and is_english_prose(line)]
        assert not failures,(path.name,failures[:5])
    priorities={name:row for row in facts['nvic_priorities'] for name in row['irqn']}
    assert priorities['USART2_IRQn']['configured_preemption']==0
    assert priorities['SysTick_IRQn']['configured_preemption']==15
    assert priorities['USART2_IRQn']['source_groupings']==[3]
    assert facts['nvic_recovery']['priority_bits']==4
    with sqlite3.connect(out/'facts.db') as db:
        count=db.execute('select count(*) from nvic_priorities').fetchone()[0]
        assert count==len(facts['nvic_priorities'])
    baseline_path=out/'snapshots/20261019-150008-858553/facts.json'
    baseline=read_json(baseline_path)
    before={v['symbol_id']:v.get('static_classification') for v in baseline['variables']}
    after={v['symbol_id']:v.get('static_classification') for v in facts['variables']}
    assert before==after
    fixture=read_json(TOOL/'validation/nvic_acceptance/acceptance.json')
    assert fixture['mode']=='live' and fixture['compiled'] and fixture['fresh_scan']
    summary=dict(project=str(root),fingerprint=state['fingerprint'],engine_digest=state['engine_digest'],
        translation_units=len(facts['translation_units']),inventory_rows=len(facts['variables']),
        static_classification=report['coverage']['static_classification'],
        static_baseline_unchanged=True,review_targets=len(rows),review_states=dict(collections.Counter(r['state'] for r in rows)),
        review_verdicts=dict(collections.Counter(r['status'] for r in rows)),
        chinese_answers=True,receipts_verified=True,html_checked=True,markdown_checked=True,sqlite_checked=True,
        recovered_priorities={name:dict(preemption=priorities[name]['configured_preemption'],subpriority=priorities[name]['configured_subpriority'],
            groupings=priorities[name]['source_groupings']) for name in ('USART2_IRQn','SysTick_IRQn')},
        fixture=fixture)
    destination=TOOL/'validation/nvic_final_audit.json'
    write_json(destination,summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('验收记录：',destination)


if __name__=='__main__':main()
