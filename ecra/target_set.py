"""Exact interned sets for large inclusion-based pointer solutions.

Every string keeps its identity. Bitmaps change representation only: no target
budget, widening, truncation or classification decision is made here.
"""
from collections.abc import MutableSet

_BYTE_INDICES = tuple(tuple(i for i in range(8) if byte & (1 << i)) for byte in range(256))


class TargetPool:
    def __init__(self):
        self.indices = {}
        self.values = []
        self.unknown_mask = 0
        self.function_mask = 0

    def bit(self, value):
        index = self.indices.get(value)
        if index is None:
            index = len(self.values)
            self.indices[value] = index
            self.values.append(value)
            if value.startswith('unknown:'):
                self.unknown_mask |= 1 << index
            if value.startswith('fn:'):
                self.function_mask |= 1 << index
        return 1 << index

    def make(self, values=()):
        result = TargetSet(self)
        result.update(values)
        return result


def bitmap_values(bits, values):
    if bits.bit_count() > 128:
        # Dense sets must not allocate a full-width big integer for every
        # extracted bit. Byte lookup makes iteration linear in encoded bytes
        # plus targets, while keeping exactly the same indices.
        for offset, byte in enumerate(bits.to_bytes((bits.bit_length() + 7) // 8, 'little')):
            for shift in _BYTE_INDICES[byte]:
                yield values[(offset << 3) + shift]
        return
    while bits:
        low = bits & -bits
        yield values[low.bit_length() - 1]
        bits ^= low


class TargetSet(MutableSet):
    __slots__ = ('pool', 'bits')

    def __init__(self, pool, bits=0):
        self.pool, self.bits = pool, bits

    def __len__(self):
        return self.bits.bit_count()

    def __bool__(self):
        return bool(self.bits)

    def __iter__(self):
        return bitmap_values(self.bits, self.pool.values)

    def __contains__(self, value):
        index = self.pool.indices.get(value)
        return index is not None and bool(self.bits & (1 << index))

    def add(self, value):
        self.bits |= self.pool.bit(value)

    def discard(self, value):
        index = self.pool.indices.get(value)
        if index is not None:
            self.bits &= ~(1 << index)

    def update(self, values):
        if isinstance(values, TargetSet) and values.pool is self.pool:
            self.bits |= values.bits
        else:
            for value in values:
                self.add(value)

    def copy(self):
        return TargetSet(self.pool, self.bits)

    def _existing_mask(self, values):
        if isinstance(values, TargetSet) and values.pool is self.pool:
            return values.bits
        bits = 0
        for value in values:
            index = self.pool.indices.get(value)
            if index is not None:
                bits |= 1 << index
        return bits

    def __sub__(self, other):
        return TargetSet(self.pool, self.bits & ~self._existing_mask(other))

    def __and__(self, other):
        return TargetSet(self.pool, self.bits & self._existing_mask(other))

    __rand__ = __and__

    def __or__(self, other):
        result = self.copy()
        result.update(other)
        return result

    __ror__ = __or__

    def __eq__(self, other):
        if isinstance(other, TargetSet) and other.pool is self.pool:
            return self.bits == other.bits
        if isinstance(other, (set, frozenset, TargetSet)):
            return len(self) == len(other) and all(value in other for value in self)
        return NotImplemented


def point_targets(facts, row):
    """Decode either the original small-set schema or the exact bitmap schema."""
    if 'targets' in row:
        return iter(row['targets'])
    bits = int(facts['pointer_target_sets'][row['target_set_id']], 16)
    return bitmap_values(bits, facts['pointer_target_atoms'])
