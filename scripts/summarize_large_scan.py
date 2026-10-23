"""Summarize actual stage/process metrics without loading analysis facts.

Private Bytes, working set and system commit are deliberately separate.
Per-worker OS peaks are retained by PID/creation time and by self diagnostics.
"""
import argparse
import json
from pathlib import Path


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else default


def summarize(evidence, output):
    execution = read(evidence/'execution.json', {})
    start = read(evidence/'execution-start.json', {})
    pid = start.get('pid', execution.get('pid'))
    peaks = [dict(value, pid=value.get('pid', int(key.split('@')[0])))
             for key, value in execution.get('peaks', {}).items()]
    parent = next((p for p in peaks if p['pid'] == pid), {})
    result = dict(evidence=str(evidence), output=str(output), exit_code=execution.get('exit_code'),
                  seconds=execution.get('seconds'), main_pid=pid, main_memory=parent.get('memory', {}),
                  process_peaks=peaks, validity=read(output/'result_validity.json'),
                  completion=read(output/'diagnostics/completion.json'),
                  stages=read(output/'diagnostics/scan_stages.json', []),
                  exit_status_unknown=execution.get('exit_status_unknown',False),
                  measurement_gap=execution.get('measurement_gap',False),
                  last_observed_seconds=execution.get('last_observed_seconds'))
    scheduling = read(evidence/'analysis-resource-wait.json', {})
    waited = (scheduling.get('seconds') if scheduling.get('status') == 'COMPLETE' or scheduling.get('complete') is True
              else None if scheduling else 0)
    elapsed = result['seconds']
    valid_wait = (isinstance(waited, (int, float)) and waited >= 0 and
                  isinstance(elapsed, (int, float)) and elapsed >= waited)
    result.update(resource_wait=scheduling, resource_wait_seconds=waited,
                  resource_wait_accounting_valid=valid_wait,
                  wall_seconds_excluding_resource_wait=elapsed-waited if valid_wait else None)
    for stage in result['stages']:
        seconds = stage.get('seconds')
        if stage.get('stage') == '跨翻译单元事实归并':
            stage['resource_wait_seconds'] = waited
            stage['seconds_excluding_resource_wait'] = (seconds-waited if valid_wait and
                isinstance(seconds, (int, float)) and seconds >= waited else None)
        first = stage.get('memory_start', {}).get('private_bytes')
        last = stage.get('memory_end', {}).get('private_bytes')
        if first is not None and last is not None:
            stage['private_bytes_delta'] = last-first
    commit, physical, observations = {}, {}, 0
    memory_files=[path for path in (evidence/'memory.jsonl',evidence/'memory-recovered.jsonl') if path.is_file()]
    result['memory_files']=list(map(str,memory_files))
    for memory_file in memory_files:
        with memory_file.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                observations += 1
                current = row.get('system_commit_bytes', {})
                if current.get('CommitTotal', 0) > commit.get('CommitTotal', 0):
                    commit = dict(current, seconds=row['seconds'])
                system = row.get('system', {})
                if system.get('used', 0) > physical.get('used', 0):
                    physical = dict(system, seconds=row['seconds'])
    result['os_observations'] = observations
    result['system_commit_at_max_observed_total'] = commit
    result['physical_memory_at_max_observed_used'] = physical
    result['worker_self_diagnostics'] = []
    for profile in sorted((output/'diagnostics/workers').glob('*/memory_profile.json')):
        data = read(profile)
        result['worker_self_diagnostics'].append(dict(tu=profile.parent.name, pid=data['pid'],
                                                      current=data['current'], peaks=data['peaks']))
    result['artifacts'] = {name: (output/name).stat().st_size for name in
        ('facts.json', 'facts.db', 'index.html', 'reports/global_static_concurrency.json') if (output/name).is_file()}
    manifest = read(output/'html_details/manifest.json')
    if manifest:
        result['html_sidecars'] = dict(complete=manifest['complete'], files=len(manifest.get('files', {})),
                                      bytes=sum(r['bytes'] for r in manifest.get('files', {}).values()),
                                      max_detail_chars=manifest.get('max_detail_chars'))
    result['measurement_boundary'] = ('OS peaks are historical peaks within each observed process; '
        'system peak uses the maximum sampled CommitTotal, not the OS lifetime CommitPeak. '
        'Stage deltas are endpoint Private Bytes changes. Worker self diagnostics refer to the supplied output snapshot.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--json', dest='json_file', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args()
    result = summarize(args.evidence, args.output_dir)
    args.json_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.markdown:
        memory = result['main_memory']
        lines = ['# 实测扫描指标', '', f"证据：`{args.evidence}`；输出：`{args.output_dir}`。", '',
                 '| 指标 | 实测值 |', '|---|---:|', f"| 退出码 | {result['exit_code']} |",
                 f"| 总耗时（秒） | {result['seconds']} |",
                 f"| 显式资源排队（秒） | {result['resource_wait_seconds']} |",
                 f"| 扣除资源排队的墙钟时间（秒，非 CPU 时间） | {result['wall_seconds_excluding_resource_wait']} |",
                 f"| 主进程提交峰值（B） | {memory.get('peak_pagefile')} |",
                 f"| 主进程工作集峰值（B） | {memory.get('peak_wset')} |",
                 f"| 本轮采样系统提交峰值（B） | {result['system_commit_at_max_observed_total'].get('CommitTotal')} |",
                 f"| 提取 Worker 自诊断数 | {len(result['worker_self_diagnostics'])} |", '',
                 '| 阶段 | 状态 | 墙钟秒（含排队） | 扣除显式排队的墙钟秒 | Private Bytes 开始 / 结束 |', '|---|---|---:|---:|---:|']
        for stage in result['stages']:
            lines.append(f"| {stage['stage']} | {stage['status']} | {stage.get('seconds')} | "
                         f"{stage.get('seconds_excluding_resource_wait', stage.get('seconds'))} | "
                         f"{stage.get('memory_start', {}).get('private_bytes')} / {stage.get('memory_end', {}).get('private_bytes')} |")
        lines += ['', '系统提交含其他进程；排队扣除后仍含 I/O 和操作系统调度，不是 CPU 使用时间。完整进程及 Worker 数据见配套 JSON。', '']
        args.markdown.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(output=str(args.json_file), main_pid=result['main_pid'], exit_code=result['exit_code'])))


if __name__ == '__main__':
    main()
