"""Reuse complete identical read-only CFG bodies; never merge graph identities."""
from collections import OrderedDict
import hashlib
import json
import math


_SCALARS = (type(None), bool, int, str)


def _compatible(value):
    kind = type(value)
    if kind in _SCALARS:
        return True
    if kind is float:
        return math.isfinite(value)
    if kind is list:
        return all(_compatible(item) for item in value)
    if kind is dict:
        return all(type(key) is str and _compatible(item) for key, item in value.items())
    return False


def _encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def _fingerprint(encoded):
    return hashlib.sha256(encoded.encode('ascii')).digest()


class ReadOnlyGraphPool:
    def __init__(self, cache_size=4096):
        self.cache_size = cache_size
        self.cache = OrderedDict()

    def share(self, value):
        try:
            if not _compatible(value):
                return value
            encoded = _encode(value)
            key = _fingerprint(encoded)
            previous = self.cache.get(key)
            if key in self.cache and _compatible(previous) and _encode(previous) == encoded:
                self.cache.move_to_end(key)
                return previous
        except (TypeError, ValueError, OverflowError, RecursionError):
            # This optimization cannot normalize an unsupported future fact or
            # replace the original merge/publication failure semantics.
            return value
        self.cache[key] = value
        self.cache.move_to_end(key)
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return value
