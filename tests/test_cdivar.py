import unittest
from openlcb.cdivar import CDIVar, SUBTYPE_FORMATS


class TestCDIVar(unittest.TestCase):

    def test_initialization_valid(self):
        cdivar_int = CDIVar(className='int', _min=0, _max=100, _size=4,
                            _default=bytearray(b'\x00\x00\x00\x00'))
        self.assertEqual(cdivar_int.className, 'int')
        self.assertEqual(cdivar_int.min, 0)
        self.assertEqual(cdivar_int.max, 100)
        self.assertEqual(cdivar_int.size, 4)

        cdivar_float = CDIVar(className='float', _min=0.0, _max=100.0, _size=4)
        self.assertEqual(cdivar_float.className, 'float')
        self.assertEqual(cdivar_float.min, 0.0)
        self.assertEqual(cdivar_float.max, 100.0)
        self.assertEqual(cdivar_float.size, 4)

        maxSize = 100
        cdivar_string = CDIVar(className='string',
                               _default=bytearray(b'Hello'),
                               _size=maxSize)
        self.assertEqual(cdivar_string.className, 'string')
        self.assertEqual(cdivar_string.default, bytearray(b'Hello'))
        assert cdivar_string.default is not None
        # self.assertEqual(cdivar_string.size, len(cdivar_string.default))
        self.assertEqual(cdivar_string.size, maxSize)

    def test_initialization_invalid_classname(self):
        with self.assertRaises(AssertionError):
            CDIVar(className='invalid_class')

    def test_subtype(self):
        cdivar_signed_int = CDIVar(className='int', _size=4, _min=-100,
                                   _max=100)
        self.assertEqual(cdivar_signed_int.subtype(), 'int32')
        cdivar_unsigned_int = CDIVar(className='int', _size=4)
        self.assertEqual(cdivar_unsigned_int.subtype(), 'uint32')
        cdivar_signed_float = CDIVar(className='float', _size=4)
        self.assertEqual(cdivar_signed_float.subtype(), 'float32')

    def test_pack_format(self):
        cdivar_int = CDIVar(className='int', _size=4)
        self.assertEqual(cdivar_int.packFormat(),
                         SUBTYPE_FORMATS[cdivar_int.subtype()])

        cdivar_float = CDIVar(className='float', _size=4)
        self.assertEqual(cdivar_float.packFormat(),
                         SUBTYPE_FORMATS[cdivar_float.subtype()])

    def test_set_get_int(self):
        cdivar_int = CDIVar(className='int', _size=4)
        cdivar_int.setInt(42)
        self.assertEqual(cdivar_int.getInt(), 42)

    def test_set_get_float(self):
        cdivar_float = CDIVar(className='float', _size=4)
        cdivar_float.setFloat(3.14)
        got = cdivar_float.getFloat()
        assert got is not None
        self.assertAlmostEqual(got, 3.14, places=6)

    def test_set_get_string(self):
        cdivar_string = CDIVar(className='string', _size=100)
        cdivar_string.setString("Hello")
        self.assertEqual(cdivar_string.getString(), "Hello")

    def test_invalid_set_int(self):
        cdivar_int = CDIVar(className='int', _size=4)
        with self.assertRaises(AssertionError):
            cdivar_int.setInt("not an int")  # type:ignore (assertRaises)

    def test_invalid_set_float(self):
        cdivar_float = CDIVar(className='float', _size=4)
        with self.assertRaises(AssertionError):
            cdivar_float.setFloat("not a float")  # type:ignore (assertRaises)

    def test_invalid_set_string(self):
        cdivar_string = CDIVar(className='string', _size=100)
        with self.assertRaises(AttributeError):  # number has no attribute 'encode'
            cdivar_string.setString(12345)  # type:ignore (assertRaises)


if __name__ == '__main__':
    unittest.main()
