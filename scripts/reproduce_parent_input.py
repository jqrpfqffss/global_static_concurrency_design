"""Inject changed-and-restored assembly bytes in a disposable real Clang scan."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.engine.resolve()))
    from ecra import cli
    from ecra.common import read_json,write_json
    root=args.evidence.resolve()
    root.mkdir(parents=True,exist_ok=False)
    (root/'app.c').write_text('int shared;void IRQ(void){shared++;}int main(void){shared++;return 0;}\n',encoding='utf-8')
    assembly=root/'startup.S'
    assembly.write_text('.section .isr_vector,"a"\ng_pfnVectors:\n.word _estack\n.word main\n.word IRQ\n',encoding='utf-8')
    write_json(root/'compile_commands.json',[dict(directory=str(root),file=name,
        arguments=['arm-none-eabi-gcc','-mcpu=cortex-m4','-mthumb','-c',name]) for name in ('app.c','startup.S')])
    config=root/'semantics.yaml'
    write_json(config,dict(version=1,analysis=dict(compile_database='compile_commands.json'),
        contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['IRQ'])],
        review=dict(enabled=False,prepare_packets=False)))
    with (root/'baseline.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        baseline=cli.run(root,config,no_review=True)
    if baseline!=2:raise RuntimeError(f'Disposable baseline failed: {baseline}')
    original=assembly.read_bytes()
    consumed=original+b'/* different bytes actually consumed, then restored */\n'
    changed=[]
    analyze=cli.analyze
    def intercept(method):
        def read(path,*a,**kw):
            if path.resolve()==assembly and not changed:
                changed.append(True)
                assembly.write_bytes(consumed)
                try:return method(path,*a,**kw)
                finally:assembly.write_bytes(original)
            return method(path,*a,**kw)
        return read
    def analyzed(*a,**kw):
        with patch.object(Path,'read_text',intercept(Path.read_text)),patch.object(Path,'read_bytes',intercept(Path.read_bytes)):
            return analyze(*a,**kw)
    with patch.object(cli,'analyze',side_effect=analyzed), \
            (root/'injected.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        code=cli.run(root,config,no_review=True)
    out=root/'.ecra'
    validity=read_json(out/'result_validity.json')
    result=dict(controlled_fault_injection=True,full_scan_acceptance=False,baseline_exit_code=baseline,
        exit_code=code,expected_exit_code=3,different_assembly_content_really_read=bool(changed),
        disk_restored=assembly.read_bytes()==original,analysis_valid=validity.get('analysis_valid'),
        checkpoint_exists=(out/'scan_state.json').exists(),interpreter=sys.version)
    result['passed']=(code==3 and changed and result['disk_restored'] and
                      validity.get('analysis_valid') is False and not result['checkpoint_exists']) is True
    write_json(root/'result.json',result)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
