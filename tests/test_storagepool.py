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
        value_bytes = pool.get(4, 40, 4, force=True)
        self.assertEqual(len(value_bytes), 4)
        value = struct.unpack(">I", value_bytes)[0]
        assert isinstance(value, int)
        # i or I: int32
        # capital letter: unsigned
        self.assertEqual(value, 0)

    def test_get_raises_keyerror(self):
        pool = StoragePool()
        with self.assertRaises(KeyError):
            pool.get(4, 40, 4)        # adjust arguments as needed

    def testUnsignedInt(self):
        in_value = 9999999
        value_bytes = struct.pack(">I", in_value)
        self.assertEqual(len(value_bytes), 4)
        assert isinstance(value_bytes, (bytes, bytearray))
        pool = StoragePool()
        pool.set(1, 10, value_bytes)
        out_bytes = pool.get(1, 10, 4)
        self.assertEqual(len(out_bytes), 4)
        out_value = struct.unpack(">I", out_bytes)[0]
        self.assertEqual(in_value, out_value)

    def testSignedInt(self):
        in_value = -9999999
        value_bytes = struct.pack(">i", in_value)
        self.assertEqual(len(value_bytes), 4)
        assert isinstance(value_bytes, (bytes, bytearray))
        pool = StoragePool()
        pool.set(1, 10, value_bytes)
        out_bytes = pool.get(1, 10, 4)
        self.assertEqual(len(out_bytes), 4)
        out_value = struct.unpack(">i", out_bytes)[0]
        self.assertEqual(in_value, out_value)


if __name__ == "__main__":
    unittest.main()
