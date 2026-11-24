"""Measure logical scan-directory bytes with a deterministic OpenCode transport.

Run from the repository with python -m scripts.benchmark_review_storage.
Each size uses a private scan, SQLite publication, Packet builder and receipt verifier.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import statistics
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ecra import review_archive
from ecra.common import read_json
from ecra.review import review_all
from ecra.scan_store import publish_scan
from ecra.workspace import managed_root
from tests.review_fixtures import mock_runtime
from tests.test_review_contract import answer_for


def size(folder, *, allocation=False):
    total = 0
    seen = set()
    if allocation and os.name == 'nt':
        from ecra.windows_storage import WindowsFiles
        windows = WindowsFiles()
    for base, _, names in os.walk(folder):
        for name in names:
            path = Path(base)/name
            try:
                if allocation and os.name == 'nt':
                    info = windows.allocation(path)
                    identity = tuple(info['identity'])
                    amount = info['allocated_bytes']
                elif allocation:
                    stat = path.stat()
                    identity = (stat.st_dev, stat.st_ino)
                    amount = stat.st_blocks * 512
                else:
                    total += path.stat().st_size
                    continue
                if identity not in seen:
                    seen.add(identity)
                    total += amount
            except FileNotFoundError:
                continue
    return total


def measure(root, count, workers):
    out = root/'scans'/f'bench-{count}'
    source = 'int shared;\nvoid IRQ(void){shared++;}\n'
    facts = dict(variables=[], contexts=[], functions=[], calls=[])
    report = dict(findings=[dict(finding_id=f'F{i:05}', variable_name='shared',
                  static_classification='SUSPECT', accesses=[]) for i in range(count)],
                  coverage={}, limitations=[])
    publish_scan(out/'scan.db', facts, report, scan_id=out.name, project_id='bench',
                 provenance=dict(archived_sources=[dict(file='app.c', text=source,
                                 sha256=hashlib.sha256(source.encode()).hexdigest())]))
    cfg = dict(review=dict(enabled=True, retries=0, workers=workers), analysis={})
    folder = out/'review'
    original = review_archive.archive_receipt
    temporary, leftovers, peaks, allocations = [], [], [], []

    def item_bytes(fid):
        total = 0
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith(fid+'.'):
                    try:
                        total += entry.stat().st_size
                    except FileNotFoundError:
                        continue
        return total

    def archive(directory, path, row):
        original(directory, path, row)
        temporary.append(item_bytes(row['finding_id']))
        if len(temporary) in {1, count} or len(temporary) % 25 == 0:
            peaks.append(size(out))
        if len(temporary) in {1, count}:
            allocations.append(size(out, allocation=True))

    def completed(rows):
        leftovers.append(item_bytes(rows[-1]['finding_id']))

    def model(argv, **options):
        packet = read_json(argv[argv.index('--file')+1])
        value = answer_for(fid=packet['finding_id'])
        value['reason'] *= 128
        return CompletedProcess(argv, 0, json.dumps(value, ensure_ascii=False), '')

    with ExitStack() as scope:
        scope.enter_context(mock_runtime(['synthetic-storage-benchmark']))
        scope.enter_context(patch('ecra.review.execute', side_effect=model))
        scope.enter_context(patch.object(review_archive, 'archive_receipt', side_effect=archive))
        scope.enter_context(patch.dict(os.environ, XDG_CONFIG_HOME=str(root/'config'),
                                      XDG_DATA_HOME=str(root/'data'), OPENCODE_DB=''))
        rows = review_all(root, out, cfg, facts, report, 'fixed', progress=lambda _: None, on_result=completed)
    assert len(rows) == len(temporary) == len(leftovers) == count
    assert all(row['state'] == 'DONE' for row in rows), rows[0].get('error')
    assert all(row['static_classification'] == 'SUSPECT' and row['answer']['status'] == 'CONFIRMED'
               for row in rows)
    from ecra.scan_persistence import archive_audit
    archive_audit(out)
    final = size(out)
    evidence = size(out/'evidence')
    allocated = size(out, allocation=True)
    return dict(count=count, workers=workers, mean_item_before_commit=round(statistics.mean(temporary)),
                max_item_after_commit=max(leftovers), sum_item_after_commit=sum(leftovers),
                sampled_peak=max(final, *peaks), final=final, review=size(folder),
                sampled_allocated_peak=max(allocated, *allocations), final_allocated=allocated,
                evidence=evidence, databases=sum((out/name).stat().st_size for name in ('scan.db','reviews.db')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counts', nargs='+', type=int, default=[10, 100, 1000])
    parser.add_argument('--workers', type=int, default=1)
    args = parser.parse_args()
    destination = managed_root()
    destination.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=destination, prefix='review-bench-') as temp:
        for count in args.counts:
            print(json.dumps(measure(Path(temp), count, args.workers)), flush=True)
