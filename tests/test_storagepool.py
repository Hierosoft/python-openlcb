import os
import struct
import sys
import unittest

from openlcb.storagepool import StoragePool


from logging import getLogger
if __name__ == "__main__":
    logger = getLogger(__file__)
else:
    logger = getLogger(__name__)

if __name__ == "__main__":
    # Allow importing repo copy of openlcb if running tests from repo manually.
    TESTS_DIR = os.path.dirname(os.path.realpath(__file__))
    REPO_DIR = os.path.dirname(TESTS_DIR)
    if os.path.isfile(os.path.join(REPO_DIR, "openlcb", "__init__.py")):
        sys.path.insert(0, REPO_DIR)
    else:
        logger.warning(
            "Reverting to installed copy if present (or imports will fail),"
            " since test running from repo but could not find openlcb in {}."
            .format(repr(REPO_DIR)))


class TestStoragePool(unittest.TestCase):

    def testGetNothing(self):
        pool = StoragePool()
        value_bytes = pool.getData(4, 40, 4, force=True)
        self.assertEqual(len(value_bytes), 4)
        value = struct.unpack(">I", value_bytes)[0]
        assert isinstance(value, int)
        # i or I: int32
        # capital letter: unsigned
        self.assertEqual(value, 0)

    def test_get_raises_keyerror(self):
        pool = StoragePool()
        with self.assertRaises(KeyError):
            # KeyError is necessary because space 4 was not defined
            #   (pool.set* is not called above, so no spaces exist).
            pool.getData(4, 40, 4)        # adjust arguments as needed

    def testUnsignedIntData(self):
        in_value = 9999999
        value_bytes = struct.pack(">I", in_value)
        self.assertEqual(len(value_bytes), 4)
        assert isinstance(value_bytes, (bytes, bytearray))
        pool = StoragePool()
        pool.setData(1, 10, value_bytes)
        out_bytes = pool.getData(1, 10, 4)
        self.assertEqual(len(out_bytes), 4)
        out_value = struct.unpack(">I", out_bytes)[0]
        self.assertEqual(in_value, out_value)

    def testSignedIntData(self):
        in_value = -9999999
        value_bytes = struct.pack(">i", in_value)
        self.assertEqual(len(value_bytes), 4)
        assert isinstance(value_bytes, (bytes, bytearray))
        pool = StoragePool()
        pool.setData(1, 10, value_bytes)
        out_bytes = pool.getData(1, 10, 4)
        self.assertEqual(len(out_bytes), 4)
        out_value = struct.unpack(">i", out_bytes)[0]
        self.assertEqual(in_value, out_value)

    def testUnsignedInt(self):
        in_value = 9999999
        pool = StoragePool()
        size = 4
        signed = False
        pool.setInt(1, 10, in_value, size, signed)
        out_bytes = pool.getData(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(">I", out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = pool.getInt(1, 10, size, signed)
        self.assertEqual(in_value, out_value)

    def testSignedInt(self):
        in_value = -9999999
        pool = StoragePool()
        size = 4
        signed = True
        pool.setInt(1, 10, in_value, size, signed)
        out_bytes = pool.getData(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(">i", out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = pool.getInt(1, 10, size, signed)
        self.assertEqual(in_value, out_value)

    def testFloat(self):
        pool = StoragePool()
        sizeFormats = {
            2: ">e",
            4: ">f",
            8: ">d",
        }
        in_value = -999
        size = 2
        pool.setFloat(1, 10, in_value, size)
        out_bytes = pool.getData(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(sizeFormats[size], out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = pool.getFloat(1, 10, size)
        self.assertEqual(in_value, out_value)

        size = 4
        in_value = -9999999  # NOTE: f32 fits -9999999 f16 does not
        pool.setFloat(1, 10, in_value, size)
        out_bytes = pool.getData(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(sizeFormats[size], out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = pool.getFloat(1, 10, size)
        self.assertEqual(in_value, out_value)

        size = 8
        pool.setFloat(1, 10, in_value, size)
        out_bytes = pool.getData(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(sizeFormats[size], out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = pool.getFloat(1, 10, size)
        self.assertEqual(in_value, out_value)


if __name__ == "__main__":
    unittest.main()
