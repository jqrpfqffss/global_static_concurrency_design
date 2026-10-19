"""Reproducible fresh AST/packet/review/HTML acceptance; optional live OpenCode.

Run from the repository root: py -3.10 scripts/validate_nvic_fix.py [--live]
The modeled IRQ layout is deliberately synthetic. It is not a real MCU claim.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.cli import run
from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.report import generate
from ecra.review import review_all, verify_receipt
from ecra.review_language import language_issues


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    options=parser.parse_args()
    root=TOOL/'validation/nvic_acceptance'
    root.mkdir(parents=True,exist_ok=True)
    for path in (TOOL/'tests/fixtures/nvic_recovery').iterdir():
        shutil.copy2(path,root/path.name)
    compiler=shutil.which('arm-none-eabi-gcc')
    if not compiler:
        raise RuntimeError('未找到 Arm GCC，不能宣称最小工程已编译')
    commands=[]
    for source in sorted(root.glob('*.c')):
        args=[compiler,'-mcpu=cortex-m4','-mthumb','-std=c11','-I',str(root),'-c',str(source),'-o',str(root/(source.stem+'.o'))]
        subprocess.run(args,cwd=root,check=True,capture_output=True,text=True)
        commands.append(dict(directory=str(root),file=source.name,arguments=args))
    write_json(root/'compile_commands.json',commands)
    config=root/'semantics.yaml'
    write_json(config,dict(version=1,project=dict(root=str(root)),
        analysis=dict(compile_database='compile_commands.json',output_dir='.ecra',open_report=False),
        contexts=[dict(id='main',kind='MAIN',functions=['main'])],
        review=dict(enabled=False,prepare_packets=True,retries=0,workers=1)))
    code=run(root,str(config),no_review=True)
    assert code in (0,2),code
    out=root/'.ecra'
    facts=read_json(out/'facts.json')
    report=read_json(out/'reports/global_static_concurrency.json')
    expected={'TIM3_IRQn':(3,0),'TIM4_IRQn':(2,1),'TIM8_UP_TIM13_IRQn':(1,2),'TIM1_UP_TIM16_IRQn':(0,3)}
    values={r['irqn'][0]:r for r in facts['nvic_priorities']}
    for irq,(pre,sub) in expected.items():
        row=values[irq]
        assert (row['preemption_priority'],row['subpriority'])==(pre,sub),row
        assert row['effective_validity']=='CONFIRMED',row
        assert row['mapping_validity']=='VECTOR_TABLE',row
        assert row['source_configurations'][0]['call_chain'][0]['function']=='main'
        assert len(row['source_configurations'][0]['call_chain'])==5,row
        assert any('Business_Update' in p['functions'] for p in row['execution_paths']),row
    finding=next(f for f in report['findings'] if f.get('variable_name')=='shared')
    packet=read_json(out/'review'/(finding['finding_id']+'.input.json'))
    assert len(packet['nvic_priorities'])==4
    cfg,_=load_config(root,str(config))
    cfg['review']['enabled']=True
    focused=copy.deepcopy(report)
    focused['findings']=[finding]
    def respond(argv,**kwargs):
        body=dict(finding_id=finding['finding_id'],status='LIKELY',reason='已核对源码优先级配置，多个 IRQ 与前台均存在读改写访问。',
            interleaving='前台读取旧值后，已使能并触发的 IRQ 可介入更新，前台随后写回旧值。',
            protection='未发现覆盖完整读改写窗口的中断屏蔽证据。',impact='计数更新可能丢失。',
            fix='保存并恢复原有屏蔽状态，保护完整读改写窗口。',verification='在实际硬件上核对定时中断的触发窗口。',
            missing_context=['仍需核实实际硬件触发时序。'],evidence=[dict(file='msp.c',line=5,claim='此处按参数配置抢占优先级和子优先级。')])
        return subprocess.CompletedProcess(argv,0,json.dumps(body,ensure_ascii=False),'')
    review_out=out/'acceptance_review'
    review_out.mkdir(exist_ok=True)
    if options.live:
        reviews=review_all(root,review_out,cfg,facts,focused,report['fingerprint'],mode='review')
    else:
        with patch('ecra.review.resolve_command',return_value=['synthetic-review']),patch('ecra.review.execute',side_effect=respond):
            reviews=review_all(root,review_out,cfg,facts,focused,report['fingerprint'],mode='review')
    for row in reviews:
        assert row['state']=='DONE',row
        assert not language_issues(row['answer'])
        verify_receipt(root,review_out/'review',row)
    generate(review_out,facts,focused,reviews)
    for name in ('index.html','opencode_review.html'):
        text=(review_out/name).read_text(encoding='utf-8')
        assert '中断优先级、分组及配置调用链' in text
        assert 'TIM8_UP_TIM13_IRQn' in text
    write_json(root/'acceptance.json',dict(compiled=True,fresh_scan=True,mode='live' if options.live else 'protocol-simulation',
        priorities={k:[v['preemption_priority'],v['subpriority']] for k,v in values.items()},
        facts=str(out/'facts.json'),packet=str(out/'review'/(finding['finding_id']+'.input.json')),
        review=str(review_out/'review/queue.json'),html=str(review_out/'index.html')))
    print('验收通过：',root/'acceptance.json')


if __name__=='__main__':
    main()
