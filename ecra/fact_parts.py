"""Replayable on-disk TU facts; the parent retains metadata, never all AST facts."""
from pathlib import Path
from functools import lru_cache
import json
import hashlib
import re

from .json_rows import RecordDicts, rows


def _worker_scratch(scan, relative):
    from .workspace import no_links
    parts = Path(relative).parts
    # Only private extractor slots. Build inputs, TU cache and profile data
    # are outside this namespace even if named by a damaged retry marker.
    if (not parts or any(p in {'.','..'} or ':' in p for p in parts)
            or Path(relative).is_absolute()):
        raise ValueError('工作文件路径无效')
    if parts[0] == 'workers':
        allowed = re.fullmatch(r'(?:TU-[a-zA-Z0-9_-]+|[0-9a-f]{24})(?:\.dependencies)?\.(?:request|response)\.json(?:\.metadata\.json)?', parts[-1])
    else:
        allowed = (parts[0] == 'diagnostics' and len(parts) > 2 and parts[1] in {'workers','dependencies','supplemental'}
                   and parts[-1] in {'scan_progress.json','scan_stages.json','memory_profile.json'})
    if not allowed:
        raise ValueError('工作文件不属于可释放的提取器产物')
    return no_links(scan.joinpath(*parts))


def _defer_worker(path):
    from .report_package import sha256
    from .review_archive import write_receipt
    from .workspace import no_links
    scan = next((parent for parent in path.parents if parent.parent.name == 'scans'), None)
    if scan is None:
        return
    relative = path.relative_to(scan).as_posix()
    path = _worker_scratch(scan, relative)
    info = path.stat()
    record = dict(scan_id=scan.name, path=relative, identity=[info.st_dev, info.st_ino],
                  size=info.st_size, mtime_ns=info.st_mtime_ns, sha256=sha256(path))
    folder = no_links(scan/'diagnostics/worker-cleanup')
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
    write_receipt(folder/(name+'.json'), record)


def retry_worker_cleanup(scan):
    from .report_package import sha256
    from .scan_diagnostics import diagnostic_log
    from .workspace import no_links
    folder = no_links(scan/'diagnostics/worker-cleanup')
    if not folder.is_dir() or not (scan/'scan.db').is_file():
        return
    for marker in folder.glob('*.json'):
        try:
            record = json.loads(no_links(marker).read_bytes())
            if (hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest() != marker.stem
                    or record['scan_id'] != scan.name):
                continue
            path = _worker_scratch(scan, record['path'])
            if path.exists():
                info = path.stat()
                if ([info.st_dev, info.st_ino] != record['identity'] or info.st_size != record['size']
                        or info.st_mtime_ns != record['mtime_ns'] or sha256(path) != record['sha256']):
                    continue
                path.unlink()
            marker.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            diagnostic_log(f'提取器缓存保留待清理 {marker.name}：{exc}')


def discard_worker_files(*paths):
    from .scan_diagnostics import diagnostic_log
    from .workspace import no_links
    released = True
    for path in paths:
        try:
            no_links(path).unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            released = False
            diagnostic_log(f'工作文件保留待清理 {path}：{exc}')
            try:
                _defer_worker(Path(path))
            except (OSError, ValueError) as failure:
                diagnostic_log(f'无法登记工作文件身份 {path}：{failure}')
    return released


class FactParts:
    def __init__(self):
        self.paths = []
        self.work_files = set()
        self.strong_functions = set()
        self.counts = {}
        self.metadata = {}
        # Header paths, USRs, source lines and schema keys recur in millions of
        # rows. Share equal immutable strings without an unbounded cache.
        self._string = lru_cache(maxsize=131072)(lambda text: text)
        self._layout = lru_cache(maxsize=4096)(self._make_layout)
        self._records = RecordDicts()

    def append(self, path, part):
        self.append_metadata(path, dict(parse_status=part.get('parse_status'), diagnostics=part.get('diagnostics', []),
             weak_functions=[f['function_id'] for f in part.get('functions', []) if f.get('is_weak')],
             strong_functions=[f['function_id'] for f in part.get('functions', [])
                                                        if not f.get('is_weak')],
             counts={key: len(value) for key, value in part.items() if isinstance(value, list)}))

    def append_metadata(self, path, metadata):
        self.paths.append(Path(path))
        self.metadata[Path(path)] = {key: metadata.get(key) for key in ('parse_status', 'diagnostics', 'weak_functions')}
        self.strong_functions.update(metadata.get('strong_functions', []))
        for key, count in metadata.get('counts', {}).items():
            self.counts[key] = self.counts.get(key, 0) + count

    def __iter__(self):
        for path in self.paths:
            with path.open(encoding='utf-8-sig') as stream:
                yield json.load(stream, object_hook=self._object)

    def iter_linked_parts(self, strong):
        from .analysis import TABLES
        from .points_to import WEAK_BODY_OWNERS
        # Only the caller may mark a response as scratch. A path can appear
        # more than once; its last complete merge read releases the file.
        last_read = {p: i for i, p in enumerate(self.paths) if p in self.work_files}
        for index, path in enumerate(self.paths):
            metadata = self.metadata[path]
            weak = metadata.get('weak_functions')
            if weak is None:
                # Compatibility with previously persisted worker metadata.
                # Read one function row at a time, never the whole TU.
                weak, seen = [], False
                for table, row, array in rows(path):
                    if table == 'functions' and array:
                        seen = True
                        if row.get('is_weak'):
                            weak.append(row['function_id'])
                    elif seen:
                        break
            overridden = set(weak) & strong
            for table, row, array in rows(path, self._object):
                if not array or table not in TABLES:
                    continue
                owner = WEAK_BODY_OWNERS.get(table)
                if owner is not None and row.get(owner) in overridden:
                    continue
                yield dict(_table=table, parse_status=metadata.get('parse_status'),
                           diagnostics=metadata.get('diagnostics') or [], **{table: [row]})
            if last_read.get(path) == index and discard_worker_files(path):
                self.work_files.remove(path)

    def _value(self, value):
        if isinstance(value, str):
            return self._string(value) if len(value) <= 1024 else value
        if isinstance(value, list):
            return [self._value(item) for item in value]
        return value

    def _object(self, value):
        keys = tuple(self._string(key) for key in value)
        result = self._records(keys)
        for key, item in zip(keys, value.values()):
            result[key] = self._value(item)
        # These schema fields describe type layouts. Solvers read them and
        # construct their own sets; none is a mutable solution/target set.
        # Sharing equal lists preserves every path and every callsite's field.
        for key in ('paths', 'argument_pointee_paths', 'argument_pointee_sizes',
                    'argument_aggregate_paths', 'return_aggregate_paths'):
            if isinstance(result.get(key), list):
                try:
                    shape = self._layout_key(result[key])
                    result[key] = self._layout(shape)
                except (TypeError, ValueError):
                    pass
        return result

    @classmethod
    def _layout_key(cls, value):
        if len(value) > 1024:
            raise ValueError('large layout remains unshared')
        result = []
        for item in value:
            if isinstance(item, list):
                result.append(cls._layout_key(item))
            elif isinstance(item, (str, int, float, bool)) or item is None:
                result.append(item)
            else:
                raise TypeError('not a scalar type layout')
        return tuple(result)

    @staticmethod
    def _make_layout(shape):
        return [FactParts._make_layout(item) if isinstance(item, tuple) else item for item in shape]

    def clear(self):
        discard_worker_files(*self.work_files)
        self.work_files.clear()
        self.paths.clear()
        self.strong_functions.clear()
        self.metadata.clear()
        self._string.cache_clear()
        self._layout.cache_clear()
