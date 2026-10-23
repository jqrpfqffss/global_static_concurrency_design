"""Content-based consistency of the actual compiler input closure.

Discovery uses the same libclang arguments as extraction, before any facts
are accepted. Extraction reports hashes of Clang's buffers, not just later
disk reads. A final discovery verifies include-resolution/set changes (for
example a newly created header shadowing an earlier search directory).
"""
import ctypes
import hashlib
from pathlib import Path
import time
from contextvars import ContextVar

from .common import relative, write_json
from .common import read_json

SOURCE_READS = ContextVar('ecra_verified_parent_source_reads',default=None)


def read_analysis_bytes(path):
    snapshot = SOURCE_READS.get()
    return snapshot.read_bytes(path) if snapshot is not None else Path(path).read_bytes()


def read_analysis_text(path, *, encoding='utf-8', errors='strict'):
    snapshot = SOURCE_READS.get()
    if snapshot is not None:
        return snapshot.read_text(path,encoding=encoding,errors=errors)
    return Path(path).read_text(encoding=encoding,errors=errors)


def iter_analysis_lines(path, *, encoding='utf-8', errors='strict'):
    if SOURCE_READS.get() is None:
        with Path(path).open(encoding=encoding,errors=errors) as stream:
            yield from stream
        return
    text = read_analysis_text(path,encoding=encoding,errors=errors)
    position = 0
    while position < len(text):
        end = text.find('\n',position)
        if end < 0:
            yield text[position:]
            break
        yield text[position:end+1]
        position = end+1


def select_analysis_files(directory,pattern):
    snapshot = SOURCE_READS.get()
    return snapshot.select_files(directory,pattern) if snapshot is not None else list(Path(directory).glob(pattern))


def assert_active_source_inputs():
    snapshot = SOURCE_READS.get()
    if snapshot is not None:
        snapshot.assert_valid()
from .common import digest


def file_record(path):
    path = Path(path)
    try:
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            before = path.stat()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(block)
            after = path.stat()
        unstable = False
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            # A touch during hashing is not a content change. Re-read only
            # this raced file and reject differing bytes, not differing times.
            check = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    check.update(block)
            unstable = sha.digest() != check.digest()
        return dict(status='OK', sha256=sha.hexdigest(), size=after.st_size,
                    mtime_ns=after.st_mtime_ns,
                    unstable=unstable)
    except FileNotFoundError:
        return dict(status='MISSING', sha256=None)
    except OSError as exc:
        return dict(status='UNREADABLE', sha256=None, error=f'{type(exc).__name__}: {exc}')


def content_key(record):
    return record.get('status'), record.get('sha256')


def read_consumed_text(path, records, *, errors='strict'):
    """Bind parsed configuration to the exact bytes read, before discovery.

    Hashing the path later cannot prove which flags were actually consumed.
    Re-reading one response file with different bytes also invalidates the
    scan even if its final disk content matches one of those observations.
    """
    path = Path(path).resolve()
    data = path.read_bytes()
    record = dict(status='OK', sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                  read_completed_ns=time.time_ns())
    key = str(path)
    if key in records:
        previous = records[key]
        if content_key(previous) != content_key(record):
            previous['unstable'] = True
            previous.setdefault('observed_sha256', [previous['sha256']])
            if record['sha256'] not in previous['observed_sha256']:
                previous['observed_sha256'].append(record['sha256'])
    else:
        records[key] = record
    return data.decode('utf-8-sig',errors=errors)


def clang_file_contents(tu, path):
    from clang import cindex as ci
    get_contents = ci.conf.lib.clang_getFileContents
    get_contents.argtypes = [ci.TranslationUnit, ci.File, ctypes.POINTER(ctypes.c_size_t)]
    get_contents.restype = ctypes.c_void_p
    size = ctypes.c_size_t()
    pointer = get_contents(tu, tu.get_file(str(path)), ctypes.byref(size))
    if not pointer:
        return None
    return ctypes.string_at(pointer, size.value)


def clang_inputs(tu, source):
    """Hash bytes retained in the parsed TU, including forced/system headers."""
    from clang import cindex as ci
    get_contents = ci.conf.lib.clang_getFileContents
    get_contents.argtypes = [ci.TranslationUnit, ci.File, ctypes.POINTER(ctypes.c_size_t)]
    get_contents.restype = ctypes.c_void_p
    paths = {str(Path(source).resolve()), *(str(Path(i.include.name).resolve()) for i in tu.get_includes())}
    result = {}
    for path in sorted(paths):
        file = tu.get_file(path)
        size = ctypes.c_size_t()
        pointer = get_contents(tu, file, ctypes.byref(size))
        if not pointer:
            # Empty buffers are valid. Missing/unavailable buffers fail closed.
            record = file_record(path)
            if record.get('size') == 0:
                result[path] = dict(status='OK', sha256=hashlib.sha256(b'').hexdigest(), size=0)
            else:
                result[path] = dict(status='BUFFER_UNAVAILABLE', sha256=None)
            continue
        sha = hashlib.sha256()
        for offset in range(0, size.value, 1024 * 1024):
            sha.update(ctypes.string_at(pointer + offset, min(1024 * 1024, size.value-offset)))
        result[path] = dict(status='OK', sha256=sha.hexdigest(), size=size.value)
    return result


def preprocessor_signature(tu):
    """Include negative __has_include probes through active branch identity."""
    from clang import cindex as ci
    class Ranges(ctypes.Structure):
        _fields_ = [('count', ctypes.c_uint), ('ranges', ctypes.POINTER(ci.SourceRange))]
    get_ranges = ci.conf.lib.clang_getAllSkippedRanges
    get_ranges.argtypes = [ci.TranslationUnit]
    get_ranges.restype = ctypes.POINTER(Ranges)
    dispose = ci.conf.lib.clang_disposeSourceRangeList
    dispose.argtypes = [ctypes.POINTER(Ranges)]
    pointer = get_ranges(tu)
    if not pointer:
        return digest([])
    try:
        rows = []
        for index in range(pointer.contents.count):
            extent = pointer.contents.ranges[index]
            start, end = extent.start, extent.end
            rows.append((str(Path(start.file.name).resolve()) if start.file else '', start.offset, end.offset))
        return digest(sorted(rows))
    finally:
        dispose(pointer)


class InputSnapshot:
    def __init__(self, root, diagnostics, explicit, consumed=None):
        self.root, self.diagnostics = Path(root), Path(diagnostics)
        self.before = {relative(p, root): file_record(p) for p in explicit}
        self.dependencies = {}
        self.preprocessor = {}
        self.units = {}
        self.changes = []
        self.parent_reads = {}
        self.parent_selections = {}
        self.used_selections = set()
        self.optional_before = {}
        self.status = 'DISCOVERING'
        for path, record in (consumed or {}).items():
            key = relative(path, root)
            disk = self.before.get(key) or file_record(path)
            self.before[key] = record
            self.compare(key, record, disk, 'CONFIGURATION_CHANGED_AFTER_READ')
        if self.changes:
            self.status = 'INVALID'

    def record_change(self, path, reason, before, after, **evidence):
        self.changes.append(dict(file=path, reason=reason, before=before, after=after, **evidence))

    def discover(self, unit, inputs, signature=None):
        self.units[unit['tu_id']] = unit
        paths = sorted(relative(path, self.root) for path in inputs)
        self.dependencies[unit['tu_id']] = paths
        self.preprocessor[unit['tu_id']] = signature
        for path, consumed in inputs.items():
            key = relative(path, self.root)
            disk = file_record(path)
            if key not in self.before:
                self.before[key] = disk
            self.compare(key, self.before[key], consumed, 'DEPENDENCY_CONTENT_CHANGED', unit=unit['tu_id'])
            self.compare(key, consumed, disk, 'DEPENDENCY_DISCOVERY_RACE', unit=unit['tu_id'])

    def compare(self, path, before, after, reason, **evidence):
        if (content_key(before) != content_key(after) or before.get('status') != 'OK'
                or after.get('status') != 'OK' or before.get('unstable') or after.get('unstable')):
            self.record_change(path, reason, before, after, **evidence)

    def read_bytes(self,path):
        """Verify bytes actually used by non-Clang analysis, before decoding.

        A disk check after analysis misses a different version read and then
        restored. Keep only hashes/counts, never another copy of source text.
        """
        path = Path(path).resolve()
        key = relative(path, self.root)
        self.assert_valid()
        if key not in self.before and key in self.optional_before:
            self.before[key] = self.optional_before[key]
        expected = self.before.get(key)
        try:
            data = path.read_bytes()
        except OSError as exc:
            consumed = dict(status='MISSING' if isinstance(exc, FileNotFoundError) else 'UNREADABLE',
                            sha256=None, error=f'{type(exc).__name__}: {exc}')
            self.record_change(key, 'CONSUMED_INPUT_UNREADABLE', expected, consumed, phase='PARENT_READ')
        else:
            consumed = dict(status='OK',sha256=hashlib.sha256(data).hexdigest(),size=len(data))
            if expected is None:
                self.record_change(key, 'UNDECLARED_CONSUMED_INPUT', None, consumed, phase='PARENT_READ')
            else:
                self.compare(key, expected, consumed, 'CONSUMED_CONTENT_CHANGED', phase='PARENT_READ')
        previous = self.parent_reads.get(key, {})
        self.parent_reads[key] = dict(consumed, reads=previous.get('reads',0)+1,
                                      read_completed_ns=time.time_ns())
        if self.changes:
            self.status = 'INVALID'
            from .scan_diagnostics import ACTIVE
            diagnostics = ACTIVE.get()
            if diagnostics is not None:
                diagnostics.snapshot_status = self.status
            self.save()
            self.assert_valid()
        return data

    def read_text(self,path,*,encoding='utf-8',errors='strict'):
        data = self.read_bytes(path)
        # Match Path.read_text's universal-newline behavior exactly.
        return data.decode(encoding,errors=errors).replace('\r\n','\n').replace('\r','\n')

    def register_selection(self,directory,pattern):
        directory = Path(directory).resolve()
        files = sorted(relative(path,self.root) for path in directory.glob(pattern))
        key = str(directory),pattern
        self.parent_selections[key] = dict(directory=str(directory),pattern=pattern,files=files)
        # The constructor proof reads a map only when it is unique. Unused
        # candidates do not become strict inputs or cause unrelated failures.
        if len(files)==1 and files[0] not in self.before:
            self.optional_before[files[0]] = file_record(self.root/files[0])

    def _verify_selection(self,key,phase):
        record = self.parent_selections[key]
        current = sorted(relative(path,self.root) for path in Path(record['directory']).glob(record['pattern']))
        if current != record['files']:
            self.record_change(relative(record['directory'],self.root)+'/'+record['pattern'],
                'PARENT_INPUT_SET_CHANGED',dict(files=record['files']),dict(files=current),phase=phase)
        return current

    def select_files(self,directory,pattern):
        key = str(Path(directory).resolve()),pattern
        if key not in self.parent_selections:
            self.record_change(str(directory)+'/'+pattern,'UNDECLARED_INPUT_SELECTION',None,None,phase='PARENT_READ')
        else:
            self.used_selections.add(key)
            self._verify_selection(key,'PARENT_READ')
        if self.changes:
            self.status = 'INVALID'
            self.save()
            self.assert_valid()
        return [self.root/path for path in self.parent_selections[key]['files']]

    def consumed_selections(self):
        return [self.parent_selections[key] for key in sorted(self.used_selections)]

    def finalize_parent_inputs(self):
        # Finalize before the first checkpoint binds this capsule. Preserve
        # the original command records: live TU dicts now carry extraction data.
        path = self.diagnostics.parent/'input_closure.json'
        capsule = read_json(path)
        capsule['parent_selections'] = self.consumed_selections()
        write_json(path,capsule,indent=None)

    def seal(self):
        self.status = 'CAPTURED'
        self.verify_disk()
        self.save()
        self.assert_valid()
        # Immutable replay data is separate from the evolving diagnostic file.
        # Resume must rediscover resolution/negative include probes, rather than
        # merely hash the files which happened to exist at scan time.
        write_json(self.diagnostics.parent / 'input_closure.json', dict(schema=1,
                   units=list(self.units.values()), dependency_sets=self.dependencies,
                   preprocessor_signatures=self.preprocessor), indent=None)

    def observe(self, unit, inputs, phase='EXTRACTION', signature=None):
        expected_signature = self.preprocessor.get(unit['tu_id'])
        if expected_signature is not None and signature != expected_signature:
            self.record_change(unit['source_file'], 'PREPROCESSOR_STATE_CHANGED',
                               dict(sha256=expected_signature), dict(sha256=signature), phase=phase)
        expected = set(self.dependencies.get(unit['tu_id'], []))
        current = {relative(path, self.root): record for path, record in inputs.items()}
        for key in sorted(expected | current.keys()):
            if key not in expected or key not in current:
                self.record_change(key, 'DEPENDENCY_SET_CHANGED', self.before.get(key), current.get(key),
                                   unit=unit['tu_id'], phase=phase)
            else:
                self.compare(key, self.before[key], current[key], 'CONSUMED_CONTENT_CHANGED',
                             unit=unit['tu_id'], phase=phase)

    def verify_disk(self):
        after = {p: file_record(self.root / p) for p in self.before}
        for path, before in self.before.items():
            self.compare(path, before, after[path], 'INPUT_CONTENT_CHANGED')
        for key in sorted(self.used_selections):
            self._verify_selection(key,'VERIFY_DISK')
        self.after = after
        self.status = 'INVALID' if self.changes else 'VERIFIED'
        return {p: r['sha256'] for p, r in after.items() if r['status'] == 'OK'}

    def save(self):
        write_json(self.diagnostics / 'source_changes.json', dict(schema=1, status=self.status,
                   changes=self.changes, inputs_before=self.before, inputs_after=getattr(self, 'after', {}),
                   dependency_sets=self.dependencies, preprocessor_signatures=self.preprocessor,
                   parent_reads=self.parent_reads,parent_selections=self.consumed_selections()))

    def assert_valid(self):
        if self.changes:
            paths = ', '.join(dict.fromkeys(c['file'] for c in self.changes))
            raise ValueError('源码在扫描期间发生变化或无法验证真实输入；无法对不一致快照作安全证明：'
                             + paths[:1500] + '；详见 diagnostics/source_changes.json')
