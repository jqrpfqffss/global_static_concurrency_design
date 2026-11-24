"""Content-bound raw TU cache; preprocessing is always rediscovered first."""
import os
import shutil
import uuid
from .common import digest, read_json, write_json
from .path_io import filesystem_path
from .workflow import engine_digest, file_digest


class TUCache:
    def __init__(self, folder, cfg, snapshot):
        self.folder = filesystem_path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.snapshot = snapshot
        from .workflow import analysis_config
        self.cfg = analysis_config(cfg)
        self.engine = engine_digest()
        self.keys = {}
        import os
        import sys
        from clang import cindex
        self.environment = dict(python=sys.version, libclang=file_digest(cindex.conf.lib._name),
                                python_hash_seed=os.environ.get('PYTHONHASHSEED') or '0',
                                source_date_epoch=os.environ.get('SOURCE_DATE_EPOCH'),
                                search_path=os.environ.get('PATH'), include=os.environ.get('CPATH'),
                                c_include=os.environ.get('C_INCLUDE_PATH'), cpp_include=os.environ.get('CPLUS_INCLUDE_PATH'))
        # An explicit random seed does not identify reproducible worker
        # ordering. Keep this run's entries, but never reuse another run's.
        if self.environment['python_hash_seed'] == 'random':
            import uuid
            self.environment['random_seed_session'] = uuid.uuid4().hex
        self.hits = self.misses = self.corrupt = 0

    def key(self, unit):
        sid = unit['tu_id']
        if sid in self.keys:
            return self.keys[sid]
        # Fresh libclang preprocessing captures include resolution, negative
        # __has_include probes, generated inputs and response-file semantics.
        from .input_snapshot import content_key
        from .portable import resolved_executable
        compiler = resolved_executable(unit['original_arguments'][0], unit['directory'])
        key = digest(dict(schema=1, engine=self.engine, environment=self.environment,
            compiler_sha256=file_digest(compiler) if compiler.is_file() else None, config=self.cfg, unit=unit,
            signature=self.snapshot.preprocessor[sid],
            inputs={p: content_key(self.snapshot.before[p]) for p in self.snapshot.dependencies[sid]}))
        self.keys[sid] = key
        return key

    def restore(self, unit, response, metadata):
        key = self.key(unit)
        try:
            manifest = read_json(self.folder/(key + '.json'))
            raw = self.folder/(key + '.facts')
            if (manifest['schema'] != 1 or file_digest(raw) != manifest['sha256']
                    or digest(manifest['metadata']) != manifest['metadata_sha256']):
                raise ValueError('缓存校验失败')
            meta = manifest['metadata']
            if meta.get('parse_status') != 'PARSED' or not isinstance(meta.get('input_snapshot'), dict):
                raise ValueError('缓存事实不完整')
            response = filesystem_path(response)
            if response == raw:
                raise ValueError('缓存原件不能作为可写工作槽')
            response.unlink(missing_ok=True)
            # Publish metadata before exposing a link to the read-only cache.
            # A miss lets the extractor write into the same working slot.
            write_json(filesystem_path(metadata), meta)
            try:
                os.link(raw, response)
            except FileExistsError:
                raise
            except OSError:
                try:
                    shutil.copyfile(raw, response)
                    if file_digest(response) != manifest['sha256']:
                        raise ValueError('恢复的 TU 事实摘要不一致')
                except (OSError, ValueError):
                    response.unlink(missing_ok=True)
                    raise
        except FileNotFoundError:
            self.misses += 1
            return False
        except (ValueError, KeyError, TypeError, OSError):
            self.corrupt += 1
            self.misses += 1
            return False
        self.hits += 1
        return True

    def store(self, unit, response, meta):
        if meta.get('parse_status') != 'PARSED' or not isinstance(meta.get('input_snapshot'), dict):
            return
        # Called only after extraction buffers match the sealed snapshot.
        self.snapshot.assert_valid()
        key = self.key(unit)
        raw = self.folder/(key + '.facts')
        if raw.exists() and raw.samefile(response):
            return raw  # A verified restore. The worker link is now disposable.
        from .review_archive import durable_replace, write_receipt
        temp = raw.with_name(key+'.'+uuid.uuid4().hex+'.pending')
        try:
            response = filesystem_path(response)
            expected = None
            try:
                os.link(response, temp)
            except OSError:
                expected = file_digest(response)
                shutil.copyfile(response, temp)
            with temp.open('r+b') as stream:
                os.fsync(stream.fileno())
            hashed = file_digest(temp)
            if expected is not None and hashed != expected:
                raise ValueError('TU 工作响应与缓存副本摘要不一致')
            durable_replace(temp, raw)
            write_receipt(self.folder/(key+'.json'),
                          dict(schema=1, sha256=hashed, metadata=meta, metadata_sha256=digest(meta)), compact=True)
        finally:
            temp.unlink(missing_ok=True)
        return raw

    def stats(self):
        return dict(hits=self.hits, extracted=self.misses, corrupt=self.corrupt,
                    total=self.hits+self.misses)
