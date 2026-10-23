"""Read top-level JSON array rows without loading the entire document.

Worker output is an object of fact arrays and small metadata values. Each row
uses the standard JSON decoder, preserving ordinary JSON types and hooks. The
buffer grows geometrically only when one individual value needs more data.
"""
import json
import re
from functools import lru_cache

_SPACE = re.compile(r'[ \t\r\n]*')


class RecordDicts:
    """Ordinary independent dicts with shared schema keys on CPython.

    JSON facts contain millions of small records with identical ordered keys.
    Instance dictionaries share those keys without sharing any record values.
    Returning the actual dict preserves JSON encoding and all dict operations;
    other interpreters can use the same code without relying on the saving.
    Only schema constructors are cached, never records or analysis evidence.
    """
    def __init__(self, maxsize=512):
        self._classes = lru_cache(maxsize=maxsize)(self._make_class)

    @staticmethod
    def _make_class(keys):
        if any(not isinstance(key, str) or key in {'__dict__', '__class__', '__weakref__'} for key in keys):
            return None
        record_class = type('_FactRecord', (), {})
        seed = record_class()
        # Attribute insertion updates the class's cached shared-key table.
        # Direct dict insertion alone cannot grow that table past its initial
        # capacity, so medium schemas silently became ordinary combined dicts.
        for key in keys:
            setattr(seed, key, None)
        return record_class

    def __call__(self, keys):
        # Bound schema construction; every fallback is still a normal dict.
        # Other interpreters need not provide the CPython memory reduction.
        if not keys or len(keys) > 128:
            return {}
        record_class = self._classes(keys)
        return record_class().__dict__ if record_class is not None else {}

    def cache_info(self):
        return self._classes.cache_info()


class RowReader:
    def __init__(self, stream, object_hook=None, chunk_size=65536):
        self.stream = stream
        self.decoder = json.JSONDecoder(object_hook=object_hook)
        self.chunk_size = chunk_size
        self.buffer, self.position, self.eof = '', 0, False

    def fill(self, size=None):
        self.buffer = self.buffer[self.position:]
        self.position = 0
        data = self.stream.read(size or self.chunk_size)
        self.buffer += data
        if not data:
            self.eof = True

    def peek(self):
        while True:
            self.position = _SPACE.match(self.buffer, self.position).end()
            if self.position < len(self.buffer):
                return self.buffer[self.position]
            if self.eof:
                return ''
            self.fill()

    def take(self, expected):
        if self.peek() != expected:
            raise ValueError(f'Invalid worker JSON: expected {expected!r}')
        self.position += 1

    def value(self):
        self.peek()
        amount = self.chunk_size
        while True:
            try:
                result, end = self.decoder.raw_decode(self.buffer, self.position)
                # A scalar number can end at a chunk boundary (1 + e3). Read
                # ahead before accepting a token whose boundary is unknown.
                boundary = end < len(self.buffer) and self.buffer[end] in ' \t\r\n,]}:'
                if self.eof or boundary:
                    self.position = end
                    return result
                del result
            except json.JSONDecodeError:
                if self.eof:
                    raise
            self.fill(amount)
            amount *= 2

    def rows(self):
        self.take('{')
        seen = set()
        if self.peek() != '}':
            while True:
                key = self.value()
                if not isinstance(key, str) or key in seen:
                    raise ValueError('Invalid or repeated worker JSON table')
                seen.add(key)
                self.take(':')
                if self.peek() == '[':
                    self.take('[')
                    if self.peek() != ']':
                        while True:
                            yield key, self.value(), True
                            if self.peek() == ']':
                                break
                            self.take(',')
                    self.take(']')
                else:
                    yield key, self.value(), False
                if self.peek() == '}':
                    break
                self.take(',')
        self.take('}')
        if self.peek():
            raise ValueError('Trailing data in worker JSON')


def rows(path, object_hook=None, chunk_size=65536):
    with open(path, encoding='utf-8-sig') as stream:
        yield from RowReader(stream, object_hook, chunk_size).rows()
