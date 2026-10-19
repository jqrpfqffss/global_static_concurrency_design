"""Keep full cited files when an opt-in live test deletes its temporary project."""
import hashlib
import shutil
from pathlib import Path

from ecra.common import write_json


def archive_sources(root, target, row):
    root, target = Path(root).resolve(), Path(target).resolve()
    sources = {root/'app.c', root/'fixture.h'}
    sources.update((root/item['file']).resolve() for item in row.get('source_evidence', []))
    manifest = []
    for source in sorted(sources):
        source = source.resolve()
        if not source.is_relative_to(root):
            raise ValueError('真实测试归档证据不属于临时工程：' + str(source))
        relative = source.relative_to(root)
        destination = target/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest.append(dict(original_path=str(source), archived_file=relative.as_posix(),
                             sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
    write_json(target/'source-manifest.json', manifest)
