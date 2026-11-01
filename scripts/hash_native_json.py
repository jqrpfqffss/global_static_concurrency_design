"""Read-only full ordered/typed JSON hashes; no full graph or evidence restore.

Normalization is exactly compare_native_graphs.NormalizedGraph's contract.
Raw JSON remains the complete envelope evidence. A hash mismatch is FAIL; this
tool does not locate the first differing path. It is not a production codec.
"""
import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import time

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.json_rows import RowReader
from ecra.scan_store import _scalar, _hash_start
from ecra.shared_json import encoded_stream
from scripts.compare_native_graphs import REVIEW_FIELDS, READ_TIMINGS, STATUS_HASH
from ecra.scan_persistence import RUNTIME_KEYS

SCOPES = ('opaque', 'report', 'findings', 'finding', 'workspace', 'coverage', 'input-map', 'input-row')
KINDS = ('object', 'list', 'null', 'bool', 'int', 'float', 'str')
REQUIRED = {1: 'object', 2: 'list', 3: 'object', 4: 'object', 5: 'object', 6: 'object'}
OMIT = {1: frozenset(RUNTIME_KEYS) | {'generated_at', 'fingerprint'},
        3: REVIEW_FIELDS, 4: {'results_root'}, 7: READ_TIMINGS}
U64 = struct.Struct('>Q')


class Token:
    __slots__ = ('kind', 'hashes', 'integer')
    def __init__(self, kind, hashes, integer=None):
        self.kind, self.hashes, self.integer = kind, tuple(hashes), integer

    def pack(self, scopes=range(len(SCOPES))):
        mask = sum(1 << i for i in scopes if self.hashes[i] is not None)
        return bytes((KINDS.index(self.kind), mask)) + b''.join(self.hashes[i] or bytes(32) for i in scopes)

    @classmethod
    def unpack(cls, raw, scopes=range(len(SCOPES))):
        if len(raw) != 2+32*len(scopes): raise ValueError('Truncated comparison pool metadata')
        hashes = [None] * len(SCOPES)
        for offset, scope in enumerate(scopes):
            if raw[1] & (1 << scope): hashes[scope] = raw[2+32*offset:2+32*(offset+1)]
        return cls(KINDS[raw[0]], hashes)


class Keys:
    """Duplicate detection spills only unusually wide objects, without a key cap."""
    def __init__(self, owner, frame):
        self.owner, self.frame, self.local, self.size = owner, frame, set(), 0

    def add(self, key):
        if self.local is not None:
            if key in self.local: raise ValueError('Repeated JSON object key')
            self.local.add(key); self.size += len(key)
            if len(self.local) <= self.owner.key_budget and self.size <= 1024**2: return
            if self.owner.keys is None:
                self.owner.keys = sqlite3.connect(self.owner.work/'keys.db')
                self.owner.keys.execute('PRAGMA cache_size=-2048')
                self.owner.keys.execute('PRAGMA journal_mode=OFF')
                self.owner.keys.execute('CREATE TABLE keys(frame INTEGER, name BLOB, PRIMARY KEY(frame,name)) WITHOUT ROWID')
            self.owner.keys.executemany('INSERT INTO keys VALUES (?,?)',
                                       ((self.frame, value) for value in self.local))
            self.local = None
        else:
            try: self.owner.keys.execute('INSERT INTO keys VALUES (?,?)', (self.frame, key))
            except sqlite3.IntegrityError as exc: raise ValueError('Repeated JSON object key') from exc

    def close(self):
        if self.local is None: self.owner.keys.execute('DELETE FROM keys WHERE frame=?', (self.frame,))


class JsonHashes:
    def __init__(self, work, *, cache_size=16384, key_budget=4096, normalize=True):
        self.work = Path(work); self.work.mkdir(parents=True, exist_ok=False)
        self.spool = (self.work/'edges.bin').open('w+b', buffering=1024**2)
        self.pool = (self.work/'pool.bin').open('w+b', buffering=1024**2)
        self.cache_size, self.key_budget = cache_size, key_budget
        self.scopes = range(len(SCOPES)) if normalize else (0,)
        self.record_size = 2+32*len(self.scopes)
        self.cache = OrderedDict(); self.pool_count = 0; self.marker = None
        self.keys = None; self.frame = 0; self.tokens = 0

    def __enter__(self): return self
    def __exit__(self, *args):
        self.spool.close(); self.pool.close()
        if self.keys is not None: self.keys.close()

    def remember(self, ordinal, token):
        self.cache[ordinal] = token; self.cache.move_to_end(ordinal)
        while len(self.cache) > self.cache_size: self.cache.popitem(last=False)

    def reference(self, ordinal):
        if type(ordinal) is not int or not 0 <= ordinal < self.pool_count:
            raise ValueError('Invalid or forward shared JSON reference')
        if ordinal in self.cache:
            self.cache.move_to_end(ordinal); return self.cache[ordinal]
        self.pool.seek(ordinal * self.record_size)
        token = Token.unpack(self.pool.read(self.record_size),self.scopes); self.remember(ordinal, token)
        return token

    def container(self, reader):
        self.tokens += 1
        first = reader.peek()
        if first not in {'{', '['}:
            value = reader.value(); kind, payload = _scalar(value)
            hashed = _hash_start(kind, len(payload)); hashed.update(payload); digest = hashed.digest()
            return Token(kind, [digest if i not in REQUIRED else None for i in range(len(SCOPES))],
                         value if type(value) is int else None)
        kind, end = ('object', '}') if first == '{' else ('list', ']')
        reader.take(first); start = self.spool.tell(); self.frame += 1
        keys = Keys(self, self.frame); counts = [0] * len(SCOPES)
        count = 0; reference = None; has_reference = status_found = findings_found = False
        while reader.peek() != end:
            key = None; raw = b''
            if kind == 'object':
                key = reader.value()
                if not isinstance(key, str): raise ValueError('JSON object key must be a string')
                raw = key.encode('utf-8', errors='surrogatepass'); keys.add(raw); reader.take(':')
                status_found |= key == 'status'; findings_found |= key == 'findings'
            child = self.container(reader)
            if self.marker is not None and key == self.marker:
                has_reference = True; reference = child
            self.spool.write(U64.pack(len(raw))); self.spool.write(raw); self.spool.write(child.pack(self.scopes))
            for i in self.scopes: counts[i] += key not in OMIT.get(i, ())
            count += 1
            if reader.peek() == end: break
            reader.take(',')
            if reader.peek() == end: raise ValueError('Trailing JSON comma')
        reader.take(end); keys.close()
        if has_reference:
            if count != 1 or reference.kind != 'int': raise ValueError('Invalid shared JSON reference object')
            self.spool.seek(start); return self.reference(reference.integer)
        if kind == 'object' and not status_found: counts[3] += 1
        hashers = [_hash_start(kind, counts[i]) if i in self.scopes and REQUIRED.get(i, kind) == kind else None
                   for i in range(len(SCOPES))]
        if not findings_found: hashers[1] = None
        self.spool.seek(start)
        for _ in range(count):
            size = U64.unpack(self.spool.read(U64.size))[0]; raw = self.spool.read(size)
            key = raw.decode('utf-8', errors='surrogatepass') if kind == 'object' else None
            child = Token.unpack(self.spool.read(self.record_size),self.scopes)
            for i in self.scopes:
                hasher = hashers[i]
                if hasher is None or key in OMIT.get(i, ()): continue
                scope = ({'findings':2, 'workspace':4, 'coverage':5}.get(key, 0) if i == 1 else
                         3 if i == 2 else 6 if i == 5 and key == 'consumed_inputs' else 7 if i == 6 else 0)
                digest = bytes.fromhex(STATUS_HASH) if i == 3 and key == 'status' else child.hashes[scope]
                if digest is None: hashers[i] = None; continue
                hasher.update(U64.pack(len(raw))); hasher.update(raw); hasher.update(digest)
        if kind == 'object' and not status_found and hashers[3] is not None:
            hashers[3].update(U64.pack(6)); hashers[3].update(b'status'); hashers[3].update(bytes.fromhex(STATUS_HASH))
        self.spool.seek(start)
        return Token(kind, [hasher.digest() if hasher is not None else None for hasher in hashers])

    def read(self, stream):
        shared = encoded_stream(stream); reader = RowReader(stream)
        if shared:
            reader.take('{')
            for n, key in enumerate(['_ecra_shared_json', 'reference_key']):
                if n: reader.take(',')
                if reader.value() != key: raise ValueError('Missing shared JSON header')
                reader.take(':'); value = reader.value()
                if n == 0:
                    if type(value) is not int or value != 1: raise ValueError('Unsupported shared JSON version')
                else:
                    if not isinstance(value, str) or not value: raise ValueError('Invalid shared JSON marker')
                    self.marker = value
            reader.take(',')
            if reader.value() != 'pool': raise ValueError('Missing shared JSON pool')
            reader.take(':'); reader.take('[')
            while reader.peek() != ']':
                token = self.container(reader)
                if token.kind not in {'list', 'object'}: raise ValueError('Shared pool node must be a container')
                self.pool.seek(self.pool_count * self.record_size); self.pool.write(token.pack(self.scopes))
                self.remember(self.pool_count, token); self.pool_count += 1
                if reader.peek() == ']': break
                reader.take(',')
                if reader.peek() == ']': raise ValueError('Trailing shared pool comma')
            reader.take(']'); reader.take(',')
            if reader.value() != 'value': raise ValueError('Missing shared JSON complete value')
            reader.take(':')
        token = self.container(reader)
        if shared: reader.take('}')
        if reader.peek(): raise ValueError('Trailing JSON content')
        return token


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024**2): h.update(block)
    return h.hexdigest()


def hash_file(path, work, scope='opaque'):
    path = Path(path); stat = path.stat(); before = sha(path); start = time.monotonic()
    with JsonHashes(work,normalize=scope!='opaque') as hasher, path.open(encoding='utf-8-sig') as stream:
        token = hasher.read(stream); result = token.hashes[SCOPES.index(scope)]
        if result is None: raise ValueError('Malformed complete JSON for scope '+scope)
        counts = dict(pool_nodes=hasher.pool_count,parsed_tokens=hasher.tokens)
    after = path.stat()
    if (stat.st_size,stat.st_mtime_ns,before) != (after.st_size,after.st_mtime_ns,sha(path)):
        raise ValueError('Input JSON changed during full comparison')
    return dict(path=str(path.resolve()),raw_sha256=before,bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,
                ordered_hash=token.hashes[0].hex(),normalized_hash=result.hex(),scope=scope,
                seconds=time.monotonic()-start,inputs_unchanged=True,**counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts',type=Path,required=True); parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True); parser.add_argument('--receipt',type=Path,required=True)
    args = parser.parse_args()
    from ecra.workspace import studio_data_root, no_links
    args.work = studio_data_root(args.work)
    args.receipt = no_links(args.receipt)
    studio_data_root(args.receipt.parent)
    for source in (args.facts.resolve(),args.report.resolve()):
        for target in (args.work,args.receipt):
            if target == source.parent or target.is_relative_to(source.parent) or source.is_relative_to(target):
                raise ValueError('Comparison outputs must stay outside original input trees')
    if args.receipt.exists() or args.work.exists(): raise FileExistsError('Preserve prior evidence; use fresh paths')
    args.work.mkdir(parents=True)
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    result = dict(passed=False,format='ECRA_NATIVE_JSON_HASHES_V1',scope=__doc__,script_sha256=sha(__file__),
                  limit='Hash certificate only; original JSON retains all envelope values. No first-difference path, G2/G3/G4 or input-closure claim.')
    try:
        result['facts'] = hash_file(args.facts,args.work/'facts')
        result['report'] = hash_file(args.report,args.work/'report','report')
        result['passed'] = True
    except Exception as exc: result.update(error=str(exc),error_type=type(exc).__name__)
    with args.receipt.open('x',encoding='utf-8') as stream: json.dump(result,stream,indent=2)
    print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
