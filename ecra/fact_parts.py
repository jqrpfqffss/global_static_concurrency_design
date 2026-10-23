"""Replayable on-disk TU facts; the parent retains metadata, never all AST facts."""
from pathlib import Path
from functools import lru_cache
import json

from .json_rows import RecordDicts, rows


class FactParts:
    def __init__(self):
        self.paths = []
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
        for path in self.paths:
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
        self.paths.clear()
        self.strong_functions.clear()
        self.metadata.clear()
        self._string.cache_clear()
        self._layout.cache_clear()
