"""Exact finite bitmaps without padding every small set to the largest ID.

Sorted nonzero 4096-bit blocks preserve integer set operations and index order.
Immutable values are safe solver cache keys. No target budget or widening is
applied; absent blocks contain zero bits, rather than omitted target evidence.
"""
from bisect import bisect_left
from functools import lru_cache
import hashlib
import sys

BLOCK_BITS = 4096
BLOCK_MASK = (1 << BLOCK_BITS) - 1
_BYTE_INDICES = tuple(tuple(i for i in range(8) if value & (1 << i)) for value in range(256))


@lru_cache(maxsize=4096)
def _hash_factor(index):
    # Positive Python integer hashes are residues modulo this interpreter's
    # modulus. Keep equal hashes without constructing the full-width integer.
    return pow(2, BLOCK_BITS*index, sys.hash_info.modulus)


class _Complement:
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value

    def __invert__(self):
        return self.value


class BlockBitmap:
    __slots__ = ('_blocks', '_hash', '_count')

    def __init__(self, blocks=()):
        self._blocks = blocks
        self._hash = self._count = None

    @property
    def blocks(self):
        return self._blocks

    @classmethod
    def from_int(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, int) or value < 0:
            raise ValueError('A finite target bitmap requires a nonnegative integer')
        blocks = []
        index = 0
        while value:
            chunk = value & BLOCK_MASK
            if chunk:
                blocks.append((index, chunk))
            value >>= BLOCK_BITS
            index += 1
        return cls(tuple(blocks))

    @classmethod
    def from_blocks(cls, blocks):
        values = {}
        for index, value in blocks:
            if type(index) is not int or index < 0 or type(value) is not int or not 0 <= value <= BLOCK_MASK:
                raise ValueError('Invalid finite bitmap block')
            if value:
                values[index] = values.get(index, 0) | value
        return cls(tuple(sorted(values.items())))

    @classmethod
    def bit(cls, index):
        if type(index) is not int or index < 0:
            raise ValueError('Invalid target index')
        return cls(((index//BLOCK_BITS, 1 << (index % BLOCK_BITS)),))

    def __bool__(self):
        return bool(self._blocks)

    def bit_length(self):
        return self._blocks[-1][0]*BLOCK_BITS+self._blocks[-1][1].bit_length() if self._blocks else 0

    def bit_count(self):
        if self._count is None:
            self._count = sum(value.bit_count() for _, value in self._blocks)
        return self._count

    def __hash__(self):
        if self._hash is None:
            self._hash=sum((value % sys.hash_info.modulus)*_hash_factor(index)
                           for index,value in self._blocks) % sys.hash_info.modulus
        return self._hash

    def __eq__(self, other):
        if isinstance(other, BlockBitmap):
            return self._blocks == other._blocks
        if isinstance(other, int):
            return other >= 0 and self == self.from_int(other)
        return NotImplemented

    def __int__(self):
        value = 0
        for index, chunk in self._blocks:
            value |= chunk << (index*BLOCK_BITS)
        return value
    __index__ = __int__

    def __format__(self, spec):
        return format(int(self), spec)

    def __repr__(self):
        return f'BlockBitmap(blocks={len(self._blocks)}, targets={self.bit_count()}, width={self.bit_length()})'

    def _finish(self, blocks, other=None):
        blocks = tuple(blocks)
        if blocks == self._blocks:
            return self
        if other is not None and blocks == other._blocks:
            return other
        return BlockBitmap(blocks)

    def __or__(self, other):
        if self is other:
            return self
        if not isinstance(other, BlockBitmap):
            if not isinstance(other, int) or other < 0:
                return NotImplemented
            other = self.from_int(other)
        if not other:
            return self
        if not self:
            return other
        if len(other._blocks) == 1:
            index, value = other._blocks[0]
            pos = bisect_left(self._blocks, (index,))
            if pos < len(self._blocks) and self._blocks[pos][0] == index:
                previous = self._blocks[pos][1]
                combined = previous | value
                if combined == previous:
                    return self
                if len(self._blocks) == 1 and combined == value:
                    return other
                blocks = self._blocks[:pos]+((index, combined),)+self._blocks[pos+1:]
            else:
                blocks = self._blocks[:pos]+other._blocks+self._blocks[pos:]
            return BlockBitmap(blocks)
        first, second = self._blocks, other._blocks
        result = []
        i = j = 0
        while i < len(first) and j < len(second):
            ai, av = first[i]
            bi, bv = second[j]
            if ai < bi:
                result.append(first[i])
                i += 1
            elif bi < ai:
                result.append(second[j])
                j += 1
            else:
                combined = av | bv
                # Retained monotone projections share unchanged immutable
                # chunks. Rebuilding every dense chunk on one changed block
                # copied the whole image into each cache version.
                result.append(first[i] if combined == av else
                              second[j] if combined == bv else (ai, combined))
                i += 1
                j += 1
        result.extend(first[i:])
        result.extend(second[j:])
        return self._finish(result, other)
    __ror__ = __or__

    def __and__(self, other):
        if self is other:
            return self
        if isinstance(other, _Complement):
            return self._difference(other.value)
        if isinstance(other, int):
            return self._finish((index,chunk) for index,value in self._blocks
                for chunk in (value & (other >> (index*BLOCK_BITS)),) if chunk)
        if not isinstance(other, BlockBitmap):
            return NotImplemented
        first, second = self._blocks, other._blocks
        if len(first) > len(second):
            first, second = second, first
        result = []
        for index, value in first:
            pos = bisect_left(second, (index,))
            if pos < len(second) and second[pos][0] == index:
                chunk = value & second[pos][1]
                if chunk:
                    result.append((index, chunk))
        return self._finish(result)
    __rand__ = __and__

    def _difference(self, other):
        if not isinstance(other, BlockBitmap):
            other = self.from_int(other)
        result = []
        for index, value in self._blocks:
            pos = bisect_left(other._blocks, (index,))
            if pos < len(other._blocks) and other._blocks[pos][0] == index:
                value &= ~other._blocks[pos][1]
            if value:
                result.append((index, value))
        return self._finish(result)

    def __xor__(self, other):
        if not isinstance(other, BlockBitmap):
            if not isinstance(other, int) or other < 0:
                return NotImplemented
            other = self.from_int(other)
        return (self._difference(other)) | other._difference(self)
    __rxor__ = __xor__
    def __invert__(self):
        return _Complement(self)

    def contains_index(self, index):
        block = index//BLOCK_BITS
        pos = bisect_left(self._blocks, (block,))
        return (pos < len(self._blocks) and self._blocks[pos][0] == block
                and bool(self._blocks[pos][1] & (1 << (index % BLOCK_BITS))))

    def indices(self):
        for index, value in self._blocks:
            base = index*BLOCK_BITS
            if value.bit_count() > 128:
                for offset, byte in enumerate(value.to_bytes((value.bit_length()+7)//8, 'little')):
                    for shift in _BYTE_INDICES[byte]:
                        yield base+(offset << 3)+shift
            else:
                while value:
                    low = value & -value
                    yield base+low.bit_length()-1
                    value ^= low

    def referenced_storage_bytes(self):
        return sys.getsizeof(self)+sys.getsizeof(self._blocks)+sum(
            sys.getsizeof(pair)+sys.getsizeof(pair[0])+sys.getsizeof(pair[1]) for pair in self._blocks)

    def hexadecimal_fragments(self):
        """Legacy integer hexadecimal bytes with bounded zero padding."""
        if not self._blocks:
            yield '0'
            return
        width = BLOCK_BITS//4
        previous = None
        for index, value in reversed(self._blocks):
            if previous is None:
                yield format(value, 'x')
            else:
                missing = previous-index-1
                while missing:
                    count = min(missing, 64)
                    yield '0'*(count*width)
                    missing -= count
                yield format(value, f'0{width}x')
            previous = index
        while previous:
            count = min(previous, 64)
            yield '0'*(count*width)
            previous -= count

    def evidence_identifier(self):
        # common.digest(format(old_integer, 'x')) hashes a JSON string. Keep
        # those exact IDs without allocating a potentially enormous string.
        sha = hashlib.sha256(b'"')
        for fragment in self.hexadecimal_fragments():
            sha.update(fragment.encode('ascii'))
        sha.update(b'"')
        return 'PTS-'+sha.hexdigest()[:20]
