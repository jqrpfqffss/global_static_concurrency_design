"""Single source of truth for review coverage and state invariants."""
from collections import Counter
import re
from .common import read_json, write_json
from .review_summary import validate_summary, summary_settings

STATES = {'PENDING', 'DONE', 'TECH_FAILED'}
VERDICTS = {'CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT'}


def validate_archived_summary(row):
    """New receipts carry their policy; historical receipts stay readable."""
    check = row.get('summary_validation')
    if check is not None:
        if check.get('state') not in {'PASSED', 'DISABLED'}:
            raise ValueError('摘要尚未通过质量校验')
        settings = summary_settings(dict(summary=check['settings']))
        if check['state'] != ('PASSED' if settings['enabled'] else 'DISABLED'):
            raise ValueError('摘要策略与校验状态不一致')
        validate_summary(row['answer'], settings, check.get('variable_name', ''))


def set_review_state(row, state, status=None):
    row.update(state=state, review_state=state, status=status, review_status=status)
    return row


def normalize_review_record(row):
    """Read old ledgers without retaining their obsolete runtime states."""
    row = dict(row)
    state = row.get('state', row.get('review_state', 'PENDING'))
    state = {'FAILED': 'TECH_FAILED', 'STALE': 'TECH_FAILED', 'RUNNING': 'PENDING'}.get(state, state)
    if state not in STATES:
        state = 'PENDING'
    if state == 'DONE':
        answer = row.get('answer')
        if (not isinstance(answer, dict) or answer.get('status') not in VERDICTS
                or row.get('status') != answer.get('status')):
            state = 'TECH_FAILED'
            row.update(error='复核收据缺少一致的合法答案；请重新复核', error_type='InvalidReceipt')
        if state == 'DONE':
            try:
                validate_archived_summary(row)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                state = 'TECH_FAILED'
                row.update(error='复核摘要收据无效：' + str(exc), error_type='InvalidSummaryReceipt')
    if state != 'DONE' and row.get('answer'):
        row['previous_reviews'] = list(row.get('previous_reviews', [])) + [
            {k: row[k] for k in ('answer', 'status', 'execution', 'source_evidence') if k in row}]
        row.pop('answer', None)
    set_review_state(row, state, row.get('status') if state == 'DONE' else None)
    if state == 'TECH_FAILED':
        row.setdefault('error', '旧复核未正常完成；可通过 review-failed 再次复核')
        row.setdefault('last_error', dict(type=row.get('error_type', 'ReviewError'), message=row['error']))
    return row


def review_targets(report):
    from .git_diff import selected_findings
    ids = set(report['git_diff']['selected_symbol_ids']) if report.get('git_diff') else None
    return selected_findings(report) + [f for f in report.get('review_safe_samples', ())
                                       if ids is None or f.get('symbol_id') in ids]


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
    static_by_id = {f['finding_id']: f.get('static_classification') for f in review_targets(report)}
    for fid in targets + archived:
        if not isinstance(fid, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', fid) or '..' in fid:
            errors.append(f'非法 finding_id: {fid!r}')
    for row in records:
        fid, state = row['finding_id'], row.get('state')
        if (row.get('static_classification') is not None and static_by_id.get(fid) is not None
                and row['static_classification'] != static_by_id[fid]):
            errors.append(f'{fid}: 复核记录与静态分类不一致')
        if state not in STATES:
            errors.append(f'{fid}: 非法复核状态 {state!r}')
        elif state == 'DONE':
            answer = row.get('answer')
            if not isinstance(answer, dict) or answer.get('status') not in VERDICTS or row.get('status') != answer.get('status'):
                errors.append(f'{fid}: DONE 缺少合法且一致的 answer')
            else:
                try:
                    validate_archived_summary(row)
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    errors.append(f'{fid}: 摘要校验失败：{exc}')
        elif state == 'TECH_FAILED' and not row.get('error'):
            errors.append(f'{fid}: TECH_FAILED 缺少 error')
        elif state == 'PENDING' and row.get('answer'):
            errors.append(f'{fid}: {state} 不得携带当前有效 answer')
        if state != 'DONE' and row.get('status') is not None:
            errors.append(f'{fid}: {state} 不得携带当前有效 status')
        if state == 'TECH_FAILED' and row.get('answer'):
            errors.append(f'{fid}: TECH_FAILED 不得携带当前有效 answer')
        if 'review_state' in row and row['review_state'] != state:
            errors.append(f'{fid}: review_state 与 state 不一致')
        if 'review_status' in row and row['review_status'] != row.get('status'):
            errors.append(f'{fid}: review_status 与 status 不一致')
        if require_terminal and state not in {'DONE', 'TECH_FAILED'}:
            errors.append(f'{fid}: 尚未形成终态记录')
    errors += [f'遗漏 finding_id: {missing}' for _ in [0] if missing]
    errors += [f'多余 finding_id: {extra}' for _ in [0] if extra]
    errors += [f'重复 finding_id: {duplicates}' for _ in [0] if duplicates]
    states = Counter(r.get('state') for r in records)
    summary = dict(targets=len(targets), archived=len(archived), done=states['DONE'],
                   failed=states['TECH_FAILED'], tech_failed=states['TECH_FAILED'], pending=states['PENDING'],
                   stale=0, missing=len(missing), duplicate=len(duplicates),
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
        for key in ('state', 'status', 'error', 'answer', 'static_classification'):
            if row.get(key) != current.get(key):
                errors.append(f'{fid}: queue 与本轮结果的 {key} 不一致')
        if require_terminal or row.get('state') in {'DONE', 'TECH_FAILED'}:
            try:
                receipt = read_json(folder / (fid + '.result.json'))
            except (OSError, ValueError) as exc:
                errors.append(f'{fid}: 结果收据缺失或损坏：{exc}')
                continue
            for key in ('state', 'status', 'error', 'answer', 'static_classification'):
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
    set_review_state(row, 'TECH_FAILED')
    row.update(error=str(reason), last_error=dict(type='StaleReview', message=str(reason)),
               error_type='StaleReview', failure_stage='source_or_receipt_validation')
    row.pop('answer', None)
    write_json(folder/(row['finding_id']+'.result.json'), row)
    return row
