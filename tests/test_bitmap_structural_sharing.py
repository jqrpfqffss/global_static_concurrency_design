"""Synthetic allocation regression; does not replace real firmware acceptance."""
import unittest

from ecra.block_bitmap import BLOCK_BITS, BlockBitmap


class BitmapStructuralSharingTests(unittest.TestCase):
    def test_persistent_unions_reuse_unchanged_dense_chunks(self):
        # Solver projections retain successive exact images. One changing
        # block must not duplicate every dense chunk in each retained image.
        count, steps = 160, 240
        dense = (1 << (BLOCK_BITS - 1)) | ((1 << 512) - 1)
        current = BlockBitmap.from_blocks((index, dense) for index in range(count))
        versions = [current]
        expected = int(current)
        for step in range(steps):
            changed = step % count
            bit = 1024 + step // count
            delta = BlockBitmap.from_blocks((index, (1 << bit) if index == changed else 1)
                                           for index in range(count))
            expected |= int(delta)
            current = current | delta
            self.assertEqual(int(current), expected)
            versions.append(current)
        chunks = {id(pair) for value in versions for pair in value.blocks}
        # Every target remains in every image. Only immutable representation
        # nodes are shared; the complete historic images remain accessible.
        self.assertEqual(len(versions), steps + 1)
        self.assertLessEqual(len(chunks), count + steps)
        self.assertEqual(versions[0].bit_count(), count * 513)
        self.assertEqual(versions[-1].bit_count(), count * 513 + steps)

    def test_subset_union_reuses_complete_existing_image(self):
        large = BlockBitmap.from_blocks((i, (1 << 4095) | 7) for i in range(20))
        small = BlockBitmap.from_blocks((i, 3) for i in range(20))
        self.assertEqual(int(small | large), int(large))
        self.assertIs(small | large, large)
        self.assertIs(large | small, large)


if __name__ == '__main__':
    unittest.main()
