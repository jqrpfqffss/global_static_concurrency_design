"""Content-bound raw TU cache; preprocessing is always rediscovered first."""
from pathlib import Path
import shutil
from .common import digest, read_json, write_json, replace_file
from .workflow import engine_digest, file_digest


class TUCache:
    def __init__(self, folder, cfg, snapshot):
        self.folder = Path(folder)
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
                                search_path=os.environ.get('PATH'), include=os.environ.get('CPATH'),
                                c_include=os.environ.get('C_INCLUDE_PATH'), cpp_include=os.environ.get('CPLUS_INCLUDE_PATH'))
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
            shutil.copyfile(raw, response)
            write_json(metadata, meta)
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
        temp = raw.with_suffix('.pending')
        shutil.copyfile(response, temp)
        replace_file(temp, raw)
        write_json(self.folder/(key + '.json'), dict(schema=1, sha256=file_digest(raw),
                                                   metadata=meta, metadata_sha256=digest(meta)))

    def stats(self):
        return dict(hits=self.hits, extracted=self.misses, corrupt=self.corrupt,
                    total=self.hits+self.misses)
