"""Bounded physical reuse of immutable evidence; logical rows stay complete."""
from collections import OrderedDict

from .json_rows import RecordDicts


class ReadOnlyEvidence:
    def __init__(self, cache_size=4096):
        self.cache_size = cache_size
        self.records = OrderedDict()
        self.integer_lists = OrderedDict()
        self.layouts = RecordDicts(maxsize=8)

    def _remember(self, cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > self.cache_size:
            cache.popitem(last=False)
        return value

    def record(self, values, *, share=False):
        # Include types and insertion order: bool/int equality cannot merge
        # distinct logical JSON facts. Unknown/mutable values stay independent.
        reusable = share and all(type(k) is str and type(v) in {type(None), bool, int, str}
                                 for k, v in values.items())
        key = tuple((k, type(v), v) for k, v in values.items()) if reusable else None
        if reusable and key in self.records:
            self.records.move_to_end(key)
            return self.records[key]
        result = self.layouts(tuple(values))
        for k, v in values.items():
            result[k] = v
        return self._remember(self.records, key, result) if reusable else result

    def integer_list(self, values):
        # CFG node IDs are exact ints. Bypass other types rather than normalize
        # True/1, floats or arbitrary caller objects into the same evidence.
        if type(values) is not list or any(type(v) is not int for v in values):
            return values
        key = len(values), hash(tuple(values))
        previous = self.integer_lists.get(key)
        if previous is not None and previous == values:
            self.integer_lists.move_to_end(key)
            return previous
        return self._remember(self.integer_lists, key, values)
