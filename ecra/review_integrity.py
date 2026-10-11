"""Single source of truth for review coverage and state invariants."""
from collections import Counter
import re
from .common import read_json, write_json

STATES = {'PENDING', 'RUNNING', 'DONE', 'FAILED', 'STALE'}
VERDICTS = {'CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT'}


def review_targets(report):
    return list(report.get('findings', ())) + list(report.get('review_safe_samples', ()))


def review_integrity(report, records, *, require_terminal=False):
    """Validate the ledger without hiding duplicate or missing IDs in a dict."""
    targets = [f['finding_id'] for f in review_targets(report)]
    archived = [r['finding_id'] for r in records]
    tc, ac = Counter(targets), Counter(archived)
    missing = sorted(tc.keys() - ac.keys())
    extra = sorted(ac.keys() - tc.keys())
    duplicates = sorted(set(k for k, n in tc.items() if n != 1) |
                        set(k for k, n in ac.items() if n != 1))
    errors = []
    for fid in targets + archived:
        if not isinstance(fid, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', fid) or '..' in fid:
            errors.append(f'非法 finding_id: {fid!r}')
    for row in records:
        fid, state = row['finding_id'], row.get('state')
        if state not in STATES:
            errors.append(f'{fid}: 非法复核状态 {state!r}')
        elif state == 'DONE':
            answer = row.get('answer')
            if not isinstance(answer, dict) or answer.get('status') not in VERDICTS or row.get('status') != answer.get('status'):
                errors.append(f'{fid}: DONE 缺少合法且一致的 answer')
        elif state == 'FAILED' and not row.get('error'):
            errors.append(f'{fid}: FAILED 缺少 error')
        elif state in {'PENDING', 'RUNNING', 'STALE'} and row.get('answer'):
            errors.append(f'{fid}: {state} 不得携带当前有效 answer')
        if state != 'DONE' and row.get('status') is not None:
            errors.append(f'{fid}: {state} 不得携带当前有效 status')
        if require_terminal and state not in {'DONE', 'FAILED', 'STALE'}:
            errors.append(f'{fid}: 尚未形成终态记录')
    errors += [f'遗漏 finding_id: {missing}' for _ in [0] if missing]
    errors += [f'多余 finding_id: {extra}' for _ in [0] if extra]
    errors += [f'重复 finding_id: {duplicates}' for _ in [0] if duplicates]
    states = Counter(r.get('state') for r in records)
    summary = dict(targets=len(targets), archived=len(archived), done=states['DONE'],
                   failed=states['FAILED'], pending=states['PENDING'] + states['RUNNING'],
                   stale=states['STALE'], missing=len(missing), duplicate=len(duplicates),
                   errors=errors, complete=not errors,
                   all_done=not errors and states['DONE'] == len(targets))
    return summary


def assert_review_integrity(report, records, *, require_terminal=False):
    summary = review_integrity(report, records, require_terminal=require_terminal)
    if summary['errors']:
        raise ValueError('复核结果不完整：' + '; '.join(summary['errors'][:12]))
    return summary


def assert_review_archive(report, records, folder, *, require_terminal=True):
    """Check queue, per-item receipts and returned records at the commit point."""
    assert_review_integrity(report, records, require_terminal=require_terminal)
    queue = read_json(folder / 'queue.json')
    assert_review_integrity(report, queue, require_terminal=require_terminal)
    expected = {r['finding_id']: r for r in records}
    errors = []
    for row in queue:
        fid = row['finding_id']
        current = expected[fid]
        for key in ('state', 'status', 'error', 'answer'):
            if row.get(key) != current.get(key):
                errors.append(f'{fid}: queue 与本轮结果的 {key} 不一致')
        if require_terminal:
            try:
                receipt = read_json(folder / (fid + '.result.json'))
            except (OSError, ValueError) as exc:
                errors.append(f'{fid}: 结果收据缺失或损坏：{exc}')
                continue
            for key in ('state', 'status', 'error', 'answer'):
                if receipt.get(key) != row.get(key):
                    errors.append(f'{fid}: result 与 queue 的 {key} 不一致')
    fingerprint = next((r.get('scan_fingerprint') for r in records if r.get('scan_fingerprint')), None)
    if fingerprint:
        for path in folder.glob('*.result.json'):
            fid = path.name[:-len('.result.json')]
            if fid in expected:
                continue
            try:
                extra = read_json(path)
            except (OSError, ValueError):
                continue
            if extra.get('scan_fingerprint') == fingerprint:
                errors.append(f'{fid}: result 有记录但当前报告无目标')
    if errors:
        raise ValueError('复核结果不完整：' + '; '.join(errors[:12]))
    return review_integrity(report, records, require_terminal=require_terminal)


def mark_review_stale(folder, row, reason):
    """Invalidate a verdict in every durable view while retaining its history."""
    if row.get('answer'):
        previous = dict(state=row.get('state'), status=row.get('status'),
                        answer=row['answer'], execution=row.get('execution') or {},
                        source_evidence=row.get('source_evidence'))
        row['previous_reviews'] = list(row.get('previous_reviews', [])) + [previous]
    row.update(state='STALE', status=None, error=str(reason),
               error_type='StaleReview', failure_stage='source_or_receipt_validation')
    row.pop('answer', None)
    write_json(folder/(row['finding_id']+'.result.json'), row)
    return row
