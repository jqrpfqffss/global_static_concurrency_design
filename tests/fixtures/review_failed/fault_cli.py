"""External-process transport fixture, never a production review provider.

Faults happen in real child processes. In live mode successful calls go to the
real OpenCode executable; fixture answers test mechanics, not AI correctness.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--fault-plan', required=True)
    parser.add_argument('--journal', required=True)
    args, upstream_args = parser.parse_known_args()
    incoming = sys.stdin.read()
    plan = json.loads(Path(args.fault_plan).read_text(encoding='utf-8'))
    if '--file' in upstream_args:
        packet = json.loads(Path(upstream_args[upstream_args.index('--file') + 1]).read_text(encoding='utf-8'))
        fid = packet['finding_id']
        stage = 'ANALYZE'
    else:
        match = re.search(r'GS-[0-9a-f]{16}', incoming or upstream_args[-1])
        if not match:
            raise ValueError('Missing finding identity in auxiliary request')
        fid, stage = match[0], 'AUXILIARY'
    name = plan['names'][fid]
    action = plan.get('faults', {}).get(name, 'pass')
    entry = dict(time=datetime.now(timezone.utc).isoformat(), step=plan['step'],
                 finding_id=fid, variable=name, stage=stage, action=action, backend=plan['backend'])
    with Path(args.journal).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry) + '\n')
    if action == 'exit':
        print('Injected nonzero process exit (17).', file=sys.stderr, flush=True)
        return 17
    if action == 'timeout':
        print(json.dumps(dict(type='step_start', injected=True)), flush=True)
        print('Injected timeout; this partial stderr must be retained.', file=sys.stderr, flush=True)
        time.sleep(30)
        return 18  # ECRA must terminate the process before reaching here.
    if action == 'provider':
        print(json.dumps(dict(type='error', error=dict(name='InjectedProviderError',
            data=dict(message='Injected provider unavailable; not a semantic verdict.')))), flush=True)
        return 0
    if action == 'bad-json':
        print('Injected unrecoverable response: no final JSON.', flush=True)
        return 0
    if plan['backend'] == 'live':
        proc = subprocess.run(plan['upstream'] + upstream_args, input=incoming,
                              text=True, encoding='utf-8', errors='replace')
        return proc.returncode
    status = plan['statuses'][name]
    labels = dict(CONFIRMED='已确认并发风险', LIKELY='疑似并发风险',
                  REVIEWED_SAFE='已验证当前条件下安全', FALSE_POSITIVE='已确认静态误报',
                  NEED_MORE_CONTEXT='证据不足，暂无法判断')
    answer = dict(finding_id=fid, status=status,
        summary=labels[status] + '：' + name + ' 的模拟访问关系已核对，仅用于复核协议测试。',
        reason='确定性的子进程协议测试响应，仅验证传输机制，未进行模型分析。',
        interleaving='模拟夹具中的访问顺序，仅用于协议验证。',
        protection='模拟保护说明，不用于评估真实固件的安全性。',
        impact='仅验证结果归档，不对生产工程作出判断。',
        evidence=[dict(file='Core/Src/probes.c', line=1, claim='协议测试的源码文件存在。')],
        fix='本次传输测试不提供生产修复建议。', verification='核对命令行调用日志与故障计划。',
        missing_context=['该最小协议夹具未包含实际中断启用条件。']
            if status in {'LIKELY', 'NEED_MORE_CONTEXT'} else [])
    print(json.dumps(dict(type='text', part=dict(text=json.dumps(answer)))), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
