"""Resume reviews only against a verified, unchanged static scan."""
import copy
import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import digest, read_json, relative, write_json
from .config import load_config
from .html_report import REVIEW_PAGE, category, review_records, write_html
from .report import generate
from .review import review_all, parse_answer, verify_receipt


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def engine_digest():
    return digest({name: file_digest(Path(__file__).with_name(name+'.py')) for name in
                   ('analysis', 'cli', 'compilation', 'config', 'extract', 'pointer_extract', 'points_to', 'scope', 'common', 'supplemental')})


def analysis_config(cfg):
    return {k: v for k, v in cfg.items() if k != 'review'}


def clean_report(report):
    result = copy.deepcopy(report)
    for key in ('run_status', 'review_summary', 'matrix_review_summary', 'risk_summary', 'final_conclusion'):
        result.pop(key, None)
    for f in result['findings']:
        f.pop('review', None)
        f.pop('review_state', None)
        f['status'] = 'NEED_OPENCODE_REVIEW'
    return result


def save_scan(root, out, cfg, config_file, report):
    write_json(out/'review/queue.json', [dict(finding_id=f['finding_id'],state='PENDING',status='NEED_MORE_CONTEXT')
                                      for f in report['findings']])
    write_json(out/'scan_state.json', dict(schema=1, project_root=str(root),
        config_file=relative(config_file, root), config_digest=digest(analysis_config(cfg)),
        engine_digest=engine_digest(), facts_sha256=file_digest(out/'facts.json'),
        manifest_sha256=file_digest(out/'input_manifest.json'),
        report_digest=digest(clean_report(report)), fingerprint=report['fingerprint']))


def checked_scan(root, out, cfg, config_file):
    from .cli import file_hashes
    if not (out/'scan_state.json').is_file():
        raise ValueError('没有可恢复的扫描检查点；请先运行 run（旧版报告需要重新扫描一次）')
    state = read_json(out/'scan_state.json')
    required=('project_root','config_file','config_digest','engine_digest','facts_sha256','manifest_sha256','report_digest','fingerprint')
    if not isinstance(state,dict) or any(not isinstance(state.get(k),str) for k in required):
        raise ValueError('扫描检查点损坏；请重新运行 run')
    if state.get('schema') != 1 or state.get('project_root') != str(root):
        raise ValueError('扫描检查点不属于当前工程；请重新运行 run')
    if state['engine_digest'] != engine_digest() or state['config_digest'] != digest(analysis_config(cfg)):
        raise ValueError('分析实现或分析配置已变化；请重新运行 run，不能复用旧调用链')
    if (state['facts_sha256'] != file_digest(out/'facts.json') or
            state['manifest_sha256'] != file_digest(out/'input_manifest.json')):
        raise ValueError('扫描事实或输入清单已变化/损坏；请重新运行 run')
    report = read_json(out/'reports/global_static_concurrency.json')
    if not isinstance(report,dict) or not isinstance(report.get('findings'),list):
        raise ValueError('静态报告格式损坏；请重新运行 run')
    if digest(clean_report(report)) != state['report_digest']:
        raise ValueError('静态报告已变化/损坏；请重新运行 run')
    manifest = read_json(out/'input_manifest.json')
    from .scope import AuditScope
    current = file_hashes(root, out, [config_file, *(root/p for p in manifest)], AuditScope(root, cfg['analysis']).includes)
    # Model/time/retry settings can change without re-parsing the firmware.
    ignored = {state['config_file'], relative(config_file, root)}
    changed = sorted(p for p in set(current) | set(manifest)
                     if p not in ignored and current.get(p) != manifest.get(p))
    if changed:
        raise ValueError('源码/头文件/编译数据库已变化，需重新扫描：' + ', '.join(changed[:8]))
    return read_json(out/'facts.json'), clean_report(report), state


def output_path(root, cfg):
    out = (root/cfg['analysis'].get('output_dir', '.ecra')).resolve()
    if out == root or not out.is_relative_to(root):
        raise ValueError('analysis.output_dir 必须是工程根目录下的独立子目录')
    return out


def checked_reviews(root, out, reviews, fingerprint):
    import json
    verified=[]
    for original in reviews:
        r=copy.deepcopy(original)
        if r.get('state')=='DONE':
            try:
                cached=read_json(out/'review'/(r['finding_id']+'.result.json'))
                if (r.get('scan_fingerprint')!=fingerprint or cached.get('cache_key')!=r.get('cache_key')
                        or cached.get('answer')!=r.get('answer')):
                    raise ValueError('复核收据与当前扫描/缓存不匹配')
                answer=verify_receipt(root, out/'review', r)
                if answer['status']!=r.get('status'):
                    raise ValueError('复核状态与答案不一致')
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                r.update(state='STALE',status='NEED_MORE_CONTEXT',error=str(exc))
                r.pop('answer',None)
        verified.append(r)
    return verified


def read_queue(out):
    try:
        rows=read_json(out/'review/queue.json')
        if not isinstance(rows,list):
            return []
        return [r for r in rows if isinstance(r,dict) and isinstance(r.get('finding_id'),str)]
    except (OSError,ValueError):
        # Per-item caches can still be recovered by review_all. A broken queue
        # never means that the corresponding findings have been reviewed.
        return []


def status(root, config_path=None):
    cfg, config_file = load_config(root, config_path)
    out = output_path(root, cfg)
    info = dict(project=str(root), output=str(out), scan_lock=(out/'scan.lock').exists())
    if not (out/'reports/global_static_concurrency.json').exists():
        info.update(state='NOT_SCANNED', next_action='运行 run，生成变量清单和复核队列')
    else:
        report = read_json(out/'reports/global_static_concurrency.json')
        queue = read_queue(out)
        records = review_records(report, queue)
        info.update(state=report.get('run_status', 'SCANNED'), analysis_status=report['analysis_status'],
                    variables=report['coverage'].get('variables_total'), findings=len(records),
                    unresolved=sum(category(r)=='unresolved' for r in records),
                    inventory_html=str(out/'index.html'), review_html=str(out/REVIEW_PAGE))
        if info['scan_lock']:
            info.update(resumable=False, next_action='存在运行锁：等待扫描/复核结束；若进程已退出，确认后移除过期 scan.lock。当前数量来自已保存的结果。')
            return info
        try:
            checked_scan(root, out, cfg, config_file)
            disabled = not cfg.get('review', {}).get('enabled', True)
            info.update(resumable=True, review_enabled=not disabled,
                next_action=('当前未启用模型：可按 HTML 人工排查；运行原命令重新扫描；运行 report 仅刷新结果。'
                             if disabled else '运行 review 继续模型复核；运行 report 仅刷新结果'))
        except (OSError, ValueError, KeyError) as exc:
            info.update(resumable=False, next_action=str(exc))
    return info


def saved_run(root, config_path=None, render_only=False):
    cfg, config_file = load_config(root, config_path)
    out = output_path(root, cfg)
    if not out.is_dir():
        raise ValueError('还没有扫描结果；请先运行 run')
    lock = out/'scan.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f'已有扫描锁 {lock}；请先确认当前运行状态') from exc
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        facts, report, state = checked_scan(root, out, cfg, config_file)
        queue_file = out/'review/queue.json'
        reviews = read_queue(out)
        reviews = checked_reviews(root, out, reviews, state['fingerprint'])
        if not render_only:
            cfg['review']['enabled'] = True
            last = time.monotonic()

            def checkpoint(current):
                nonlocal last
                if time.monotonic()-last >= 30:
                    report['run_status']='REVIEW_RUNNING'
                    write_html(out, facts, report, current)
                    last=time.monotonic()

            try:
                reviews = review_all(root, out, cfg, facts, report, state['fingerprint'], on_result=checkpoint)
            except KeyboardInterrupt:
                reviews = read_queue(out)
                report['run_status']='INTERRUPTED'
                generate(out, facts, report, reviews)
                print('复核已中断，队列已保留；运行 review 继续。', flush=True)
                return 130
        try:
            checked_scan(root, out, cfg, config_file)
        except (OSError, ValueError, KeyError):
            for r in reviews:
                r['state']='STALE'
            report['analysis_status']='INCOMPLETE'
            report['limitations'].append('恢复期间输入发生变化；请重新扫描。')
        records = review_records(report, reviews)
        report['run_status'] = 'INCOMPLETE' if report['analysis_status']=='INCOMPLETE' or any(category(r) in {'unresolved', 'likely'} for r in records) else 'REVIEW_COMPLETE'
        mapping={r['finding_id']:r for r in records}
        for f in report['findings']:
            r=mapping[f['finding_id']]
            f['review_state']=r['state']
            if r['state']=='DONE':
                f['status']=r['status']; f['review']=r['answer']
        generate(out, facts, report, reviews)
        write_json(queue_file, reviews)
        code=2 if report['run_status']=='INCOMPLETE' else (1 if report['findings'] else 0)
        write_json(out/'resume.json', dict(command='report' if render_only else 'review', state=report['run_status'],
                                         finished=datetime.now(timezone.utc).isoformat(), exit_code=code))
        print(f"{report['run_status']}：{out/'index.html'}\nOpenCode：{out/REVIEW_PAGE}", flush=True)
        return code
    finally:
        lock.unlink(missing_ok=True)
