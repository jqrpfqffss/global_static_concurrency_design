"""Verify and export the completed STM32 validation review ledger."""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecra.review_integrity import assert_review_archive


def checked_digest(folder, name, expected):
    if not name or not expected:
        raise ValueError(f"Missing receipt filename or digest: {name!r}")
    actual = hashlib.sha256((folder / name).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Receipt digest mismatch: {name}")


def main(root, target):
    root, target = Path(root).resolve(), Path(target).resolve()
    from ecra.config import load_config
    from ecra.workflow import output_path
    out = output_path(root, load_config(root)[0])
    report = json.loads((out / 'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
    folder = out / 'review'
    queue = json.loads((folder / 'queue.json').read_text(encoding='utf-8'))
    integrity = assert_review_archive(report, queue, folder)
    if not integrity['all_done'] or report.get('review_summary', {}).get('unresolved') != 0:
        raise ValueError(f"Review is not complete: {integrity}, {report.get('review_summary')}")
    findings = {item['finding_id']: item for item in report['findings']}
    rows = []
    for review in queue:
        if review.get('scan_fingerprint') != report['fingerprint']:
            raise ValueError(f"Stale scan fingerprint: {review['finding_id']}")
        if review['status'] in {'LIKELY', 'NEED_MORE_CONTEXT'}:
            raise ValueError(f"Unresolved verdict: {review['finding_id']}")
        checked_digest(folder, review.get('packet_file'), review.get('packet_sha256'))
        checked_digest(folder, review.get('prompt_file'), review.get('prompt_sha256'))
        execution = review.get('execution') or {}
        for suffix in ('prompt', 'stdout', 'stderr'):
            checked_digest(folder, execution.get(suffix + '_file'),
                           execution.get(suffix + '_sha256'))
        finding = findings[review['finding_id']]
        rows.append(dict(finding_id=review['finding_id'],
                         variable_name=finding['variable_name'],
                         static_classification=finding['static_classification'],
                         review_status=review['status'],
                         summary=review['answer']['explanation']['summary'],
                         receipt=str(out/'review'/(review['finding_id']+'.result.json'))))
    payload = dict(upstream='https://github.com/ViniBR01/stm32-bare-metal',
                   upstream_commit='065875948326eab4d82cdaca59dd8bbd96d3516e',
                   firmware_target='cli_simple_standalone',
                   scan_fingerprint=report['fingerprint'],
                   analysis_status=report['analysis_status'],
                   run_status=report['run_status'],
                   review_integrity=integrity,
                   verdict_counts=dict(sorted(Counter(row['review_status'] for row in rows).items())),
                   findings=rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{len(rows)} verified review receipts -> {target}")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
