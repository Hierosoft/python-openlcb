import os
import struct
import sys
import unittest

from openlcb import emit_cast
from openlcb.cdivar import SIGNED_INT_MINIMUMS, CDIVar
from openlcb.storagepool import MemoryManager


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


class TestMemoryManager(unittest.TestCase):

    def testGetNothing(self):
        memory = MemoryManager()
        value_bytes = memory.getSlice(4, 40, 4, force=True)
        self.assertEqual(len(value_bytes), 4)
        value = struct.unpack(">I", value_bytes)[0]
        assert isinstance(value, int)
        # i or I: int32
        # capital letter: unsigned
        self.assertEqual(value, 0)

    def test_get_raises_keyerror(self):
        memory = MemoryManager()
        with self.assertRaises(KeyError):
            # KeyError is necessary because space 4 was not defined
            #   (memory.set* is not called above, so no spaces exist).
            memory.getSlice(4, 40, 4)        # adjust arguments as needed

    def testUnsignedIntData(self):
        in_value = 9999999
        value_bytes = struct.pack(">I", in_value)
        self.assertEqual(len(value_bytes), 4)
        assert isinstance(value_bytes, (bytes, bytearray))
        memory = MemoryManager()
        memory.setSlice(1, 10, value_bytes)
        out_bytes = memory.getSlice(1, 10, 4)
        self.assertEqual(len(out_bytes), 4)
        out_value = struct.unpack(">I", out_bytes)[0]
        self.assertEqual(in_value, out_value)

    def testSignedIntData(self):
        in_value = -9999999
        value_bytes = struct.pack(">i", in_value)
        self.assertEqual(len(value_bytes), 4)
        assert isinstance(value_bytes, (bytes, bytearray))
        memory = MemoryManager()
        memory.setSlice(1, 10, value_bytes)
        out_bytes = memory.getSlice(1, 10, 4)
        self.assertEqual(len(out_bytes), 4)
        out_value = struct.unpack(">i", out_bytes)[0]
        self.assertEqual(in_value, out_value)

    def testUnsignedInt(self):
        in_value = 9999999
        memory = MemoryManager()
        size = 4
        signed = False
        memory.setInt(1, 10, in_value, size, signed)
        out_bytes = memory.getSlice(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(">I", out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = memory.getInt(1, 10, size, signed)
        self.assertEqual(in_value, out_value)

    def testSignedInt(self):
        in_value = -9999999
        memory = MemoryManager()
        size = 4
        signed = True
        memory.setInt(1, 10, in_value, size, signed)
        out_bytes = memory.getSlice(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(">i", out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = memory.getInt(1, 10, size, signed)
        self.assertEqual(in_value, out_value)

    def testFloat(self):
        memory = MemoryManager()
        sizeFormats = {
            2: ">e",
            4: ">f",
            8: ">d",
        }
        in_value = -999
        size = 2
        memory.setFloat(1, 10, in_value, size)
        out_bytes = memory.getSlice(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(sizeFormats[size], out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = memory.getFloat(1, 10, size)
        self.assertEqual(in_value, out_value)

        size = 4
        in_value = -9999999  # NOTE: f32 fits -9999999 f16 does not
        memory.setFloat(1, 10, in_value, size)
        out_bytes = memory.getSlice(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(sizeFormats[size], out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = memory.getFloat(1, 10, size)
        self.assertEqual(in_value, out_value)

        size = 8
        memory.setFloat(1, 10, in_value, size)
        out_bytes = memory.getSlice(1, 10, size)
        self.assertEqual(len(out_bytes), size)
        out_value = struct.unpack(sizeFormats[size], out_bytes)[0]
        self.assertEqual(in_value, out_value)
        out_value = memory.getFloat(1, 10, size)
        self.assertEqual(in_value, out_value)

    def testCDIVarUInt(self):
        size = 4
        var = CDIVar("int", _size=size)
        var.space = 1
        var.address = 10
        in_value = 999
        # signed = False
        var.setInt(in_value)
        self.assertEqual(var.getInt(), in_value)
        memory = MemoryManager()
        memory.set(var)
        var = memory.get(var)
        self.assertEqual(var.getInt(), in_value)
        assert var.space is not None
        assert var.address is not None
        assert var.size is not None
        assert var.signed is not None
        out_value = memory.getInt(var.space, var.address, var.size, var.signed)
        self.assertEqual(out_value, in_value)

    def testCDIVarSInt(self):
        size = 4
        in_value = -999
        signed = True if in_value < 0 else False
        # defaultVar = CDIVar("int", _size=size, _no_min=True, _no_max=True,
        #                     signed=signed)
        # defaultVar.setInt(in_value)
        # simplified construction:
        defaultVar = CDIVar.fromInt(in_value, size)
        self.assertTrue(defaultVar.signed)
        self.assertIsNone(defaultVar.min)
        var = CDIVar(
            "int",
            _size=size,
            _default=defaultVar,  # forces signed since negative
        )
        self.assertTrue(var.signed)
        self.assertIsInstance(var.min, CDIVar)
        self.assertIsNotNone(
            var.min,
            msg=f"{emit_cast(var.min)} should be min for {size*8}-bit")
        self.assertEqual(var.min, SIGNED_INT_MINIMUMS[size])
        # ^ == allowed since __eq__ is defined for CDIVar (var.min)
        var.space = 1
        var.address = 10
        # signed = False
        var.setInt(in_value)
        self.assertEqual(var.getInt(), in_value)
        memory = MemoryManager()
        memory.set(var)
        var = memory.get(var)
        self.assertEqual(var.getInt(), in_value)
        assert var.space is not None
        assert var.address is not None
        assert var.size is not None
        assert var.signed is True
        out_value = memory.getInt(var.space, var.address, var.size, var.signed)
        self.assertEqual(out_value, in_value)


if __name__ == "__main__":
    unittest.main()
