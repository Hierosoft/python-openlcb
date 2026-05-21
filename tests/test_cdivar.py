import math
import unittest
from openlcb.cdivar import (
    FLOAT_MAXIMUMS, SIGNED_INT_MAXIMUMS, SIGNED_INT_MINIMUMS,
    UNSIGNED_INT_MAXIMUMS, CDIVar, SUBTYPE_FORMATS)


class TestCDIVar(unittest.TestCase):

    def test_initialization_valid(self):
        size = 4
        cdivar_int = CDIVar(className='int', _min=CDIVar.fromInt(0, size),
                            _max=CDIVar.fromInt(100, size),
                            _size=size,
                            _default_data=bytearray(b'\x00\x00\x00\x00'))
        self.assertEqual(cdivar_int.className, 'int')
        self.assertEqual(cdivar_int.min, CDIVar.fromInt(0, size),
                         f"got {cdivar_int.min}")
        self.assertEqual(cdivar_int.max, CDIVar.fromInt(100, size))
        self.assertEqual(cdivar_int.size, CDIVar.fromInt(4, size))

        size = 4
        cdivar_float = CDIVar(className='float',
                              _min=CDIVar.fromFloat(0.0, size),
                              _max=CDIVar.fromFloat(100.0, size),
                              _size=size)
        self.assertEqual(cdivar_float.className, 'float')
        self.assertEqual(cdivar_float.min, 0.0)
        self.assertEqual(cdivar_float.max, 100.0)
        self.assertEqual(cdivar_float.size, 4)

        maxSize = 100
        cdivar_string = CDIVar(className='string',
                               _default_data=bytearray(b'Hello\0'),
                               _size=maxSize)
        self.assertEqual(cdivar_string.className, 'string')
        assert cdivar_string.default is not None
        self.assertEqual(cdivar_string.default.data, bytearray(b'Hello\0'),
                         f"got {cdivar_string.default}")
        assert cdivar_string.default is not None
        # self.assertEqual(cdivar_string.size, len(cdivar_string.default))
        self.assertEqual(cdivar_string.size, maxSize)

    def test_initialization_invalid_classname(self):
        with self.assertRaises(AssertionError):
            CDIVar(className='invalid_class')

    def test_subtype(self):
        size = 4
        cdivar_signed_int = CDIVar(className='int', _size=size,
                                   _min=CDIVar.fromInt(-100, size),
                                   _max=CDIVar.fromInt(100, size))
        self.assertEqual(cdivar_signed_int.subtype(), 'int32')
        cdivar_unsigned_int = CDIVar(className='int', _size=size)
        self.assertEqual(cdivar_unsigned_int.subtype(), 'uint32')
        cdivar_signed_float = CDIVar(className='float', _size=size)
        self.assertEqual(cdivar_signed_float.subtype(), 'float32')

    def test_pack_format(self):
        size = 4
        cdivar_int = CDIVar(className='int', _size=size)
        self.assertEqual(cdivar_int.packFormat(),
                         SUBTYPE_FORMATS[cdivar_int.subtype()])

        cdivar_float = CDIVar(className='float', _size=size)
        self.assertEqual(cdivar_float.packFormat(),
                         SUBTYPE_FORMATS[cdivar_float.subtype()])

    def test_set_get_int(self):
        size = 4
        cdivar_int = CDIVar(className='int', _size=size)
        cdivar_int.setInt(42)
        self.assertEqual(cdivar_int.getInt(), 42)

    def test_set_get_float(self):
        size = 4
        cdivar_float = CDIVar(className='float', _size=size)
        cdivar_float.setFloat(3.14)
        got = cdivar_float.getFloat()
        assert got is not None
        self.assertAlmostEqual(got, 3.14, places=6)

    def test_set_get_string(self):
        size = 100
        cdivar_string = CDIVar(className='string', _size=size)
        cdivar_string.setString("Hello")
        self.assertEqual(cdivar_string.getString(), "Hello")

    def test_invalid_set_int(self):
        size = 4
        cdivar_int = CDIVar(className='int', _size=size)
        with self.assertRaises(AssertionError):
            cdivar_int.setInt("not an int")  # type:ignore (assertRaises)

    def test_invalid_set_float(self):
        size = 4
        cdivar_float = CDIVar(className='float', _size=size)
        with self.assertRaises(AssertionError):
            cdivar_float.setFloat("not a float")  # type:ignore (assertRaises)

    def test_invalid_set_string(self):
        size = 100
        cdivar_string = CDIVar(className='string', _size=size)
        with self.assertRaises(AttributeError):  # int, no attribute 'encode'
            cdivar_string.setString(12345)  # type:ignore (assertRaises)

    def test_ranges(self):
        # See learn.microsoft.com/en-us/cpp/cpp/data-type-ranges?view=msvc-170
        # size 1 byte is 8-bit
        self.assertEqual(SIGNED_INT_MINIMUMS[1], -128)
        self.assertEqual(SIGNED_INT_MAXIMUMS[1], 127)
        # size 2 bytes is 16-bit
        self.assertEqual(SIGNED_INT_MINIMUMS[2], -32768)
        self.assertEqual(SIGNED_INT_MAXIMUMS[2], 32767)
        # size 1 byte is 8-bit
        self.assertEqual(UNSIGNED_INT_MAXIMUMS[1], 255)
        # size 2 byte is 16-bit
        self.assertEqual(UNSIGNED_INT_MAXIMUMS[2], 65535)
        # size 4 bytes is 32-bit
        self.assertEqual(UNSIGNED_INT_MAXIMUMS[4], 4_294_967_295)
        # size 8 bytes is 64-bit
        self.assertEqual(UNSIGNED_INT_MAXIMUMS[8], 18_446_744_073_709_551_615)
        # size 4 bytes is 32-bit
        self.assertEqual(SIGNED_INT_MINIMUMS[4], -2_147_483_648)
        self.assertEqual(SIGNED_INT_MAXIMUMS[4], 2_147_483_647)
        # size 8 bytes is 64-bit
        self.assertEqual(SIGNED_INT_MINIMUMS[8], -9_223_372_036_854_775_808)
        self.assertEqual(SIGNED_INT_MAXIMUMS[8], 9_223_372_036_854_775_807)
        # size 2 bytes is 16-bit
        self.assertEqual(SIGNED_INT_MAXIMUMS[2], (1 << 15) - 1)

    def test_compare_float(self):
        size = 4
        left = CDIVar("float", _size=size)
        left.setFloat(0.5)  # 0.5 can be stored precisely in IEEE float format
        rightG = CDIVar("float", _size=size)
        rightG.setFloat(0.6)
        rightGE = CDIVar("float", _size=size)
        # NOTE: almost equal due to float imprecision
        #   (3.3999999521443642e+38 != 3.4e+38)
        assert rightGE.max is not None
        assert rightGE.max.className == "float"
        assert rightGE.size == size
        assert left.getFloat() == 0.5
        assert isinstance(FLOAT_MAXIMUMS[4], float)
        rightGE_max_value = rightGE.max.getFloat()
        assert rightGE_max_value is not None
        # self.assertAlmostEqual(rightGE.max, FLOAT_MAXIMUMS[4],
        #                        places=5,
        #                        msg=f"got {rightGE.max}")
        # ^ "AssertionError: 3.3999999521443642e+38 != 3.4e+38" so:
        self.assertTrue(math.isclose(rightGE_max_value, FLOAT_MAXIMUMS[4],
                                     rel_tol=1e-6),
                        msg=f"got {rightGE.max}")
        rightGE = CDIVar("float", _size=2)
        self.assertEqual(rightGE.max, FLOAT_MAXIMUMS[2],
                         msg=f"got {rightGE.max}")
        rightGE.setFloat(0.5)
        self.assertTrue(left < rightG)
        self.assertTrue(left == rightGE)
        self.assertTrue(rightGE >= left)
        self.assertTrue(left <= rightGE)
        self.assertTrue(rightG > left)
        self.assertFalse(rightG < left)
        self.assertFalse(left == rightG)
        self.assertFalse(left > rightG)

    def test_compare_int(self):
        size = 4
        left = CDIVar("int", _size=size)
        left.setInt(5)  # 0.5 can be stored precisely in IEEE float format
        rightG = CDIVar("int", _size=size)
        rightG.setInt(6)
        rightGE = CDIVar("int", _size=size)
        self.assertEqual(rightGE.max, UNSIGNED_INT_MAXIMUMS[4],
                         msg=f"got {rightGE.max}")
        rightGE.setInt(5)
        self.assertTrue(left < rightG)
        self.assertTrue(left == rightGE)
        self.assertTrue(rightGE >= left)
        self.assertTrue(left <= rightGE)
        self.assertTrue(rightG > left)
        self.assertFalse(rightG < left)
        self.assertFalse(left == rightG)
        self.assertFalse(left > rightG)


if __name__ == '__main__':
    unittest.main()
