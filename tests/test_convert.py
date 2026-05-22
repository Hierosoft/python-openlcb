
import struct
import unittest

from openlcb.convert import Convert
from openlcb.memoryconfigurationheader import MemoryConfigurationHeader, MemorySpaceIndex


class TestConvertClass(unittest.TestCase):

    def testReturnCyrillicStrings(self):
        # See also testReturnCyrillicStrings in test_snip
        # If you have characters specific to UTF-8 (either in code or comment)
        #   add the following as the 1st or 2nd line of the py file:
        # -*- coding: utf-8 -*-
        data = bytearray([0xd0, 0x94, 0xd0, 0xbc, 0xd0, 0xb8, 0xd1, 0x82, 0xd1, 0x80, 0xd0, 0xb8, 0xd0, 0xb9])   # Cyrillic spelling of the name Dmitry (7 characters becomes 14 bytes)  # noqa: E501
        self.assertEqual(Convert.arrayToString(data, len(data)), "Дмитрий")  # Cyrillic spelling of the name Dmitry. This string should appear as 7 Cyrillic characters like Cyrillic-demo-Dmitry.png in doc (14 bytes in a hex editor), otherwise your editor does not support utf-8 and editing this file with it could break it.  # noqa:E501
        # TODO: Russian version is Дми́трий according to <https://en.wikipedia.org/wiki/Dmitry>. See Cyrillic-demo-Dmitry-Russian.png in doc.  # noqa:E501

    def testArrayToString(self):
        sut = Convert.arrayToString(bytearray([0x41, 0x42, 0x43, 0x44]), 4)  # noqa:E501
        self.assertEqual(sut, "ABCD")

        sut = Convert.arrayToString(bytearray([0x41, 0x42, 0, 0x44]), 4)
        self.assertEqual(sut, "AB")

        sut = Convert.arrayToString(bytearray([0x41, 0x42, 0x43, 0x44]), 2)  # noqa:E501
        self.assertEqual(sut, "AB")

        sut = Convert.arrayToString(bytearray([0x41, 0x42, 0x43, 0]), 4)
        self.assertEqual(sut, "ABC")

        sut = Convert.arrayToString(bytearray([0x41, 0x42, 0x31, 0x32]), 8)  # noqa:E501
        self.assertEqual(sut, "AB12")

    def testStringToArray(self):
        aut = Convert.stringToArray("ABCD", 4)
        self.assertEqual(aut, bytearray([0x41, 0x42, 0x43, 0x44]))

        aut = Convert.stringToArray("ABCD", 2)
        self.assertEqual(aut, bytearray([0x41, 0x42]))

        aut = Convert.stringToArray("ABCD", 6)
        self.assertEqual(aut, bytearray([0x41, 0x42, 0x43, 0x44, 0x00, 0x00]))

    def testIntToArray(self):
        test_metas = [
            {
                'value': 65536,  # not a short (1 over max)
                'length': 8,
                # good_bytes: b'\x00\x00\x00\x00\x00\x01\x00\x00'
            },
            {
                'value': 65536,
                'length': 4,
                # good_bytes: b'\x00\x01\x00\x00',
            },
            {
                'value': 281470681743360,  # 65535 << 32
                'length': 8,
                # 'good_bytes': b'\x00\x00\xff\xff\x00\x00\x00\x00',
            }
        ]
        for test_meta in test_metas:
            value = test_meta['value']
            length = test_meta['length']
            good_bytes = struct.pack(">{}s".format(length),
                                     value.to_bytes(length, 'big'))
            self.assertEqual(Convert.intToArray(value, length),
                             good_bytes)

    def testIntToArrayFail(self):
        test_metas = [
            {
                'value': 65536,  # not a short (1 over max)
                'length': 2,
                # good_bytes: b'\x00\x00\x00\x00\x00\x01\x00\x00'
            },
            {
                'value': 281470681743360,  # 65535 << 32
                'length': 4,
                # 'good_bytes': b'\x00\x00\xff\xff\x00\x00\x00\x00',
            }
        ]
        for test_meta in test_metas:
            value = test_meta['value']
            length = test_meta['length']
            with self.assertRaises(ValueError):
                Convert.intToArray(value, length)

    def testSerializeSpace(self):
        # byte6 = False
        # space = 0x00

        mcHeader = MemoryConfigurationHeader(0xF8)
        self.assertEqual(mcHeader.customSpace, 0xF8)
        self.assertEqual(mcHeader.spaceIndex, MemorySpaceIndex.Custom)

        mcHeader = MemoryConfigurationHeader(0xFF)
        self.assertIs(mcHeader.spaceIndex, MemorySpaceIndex.CDI)
        self.assertEqual(mcHeader.spaceIndex.value, 0x03)
        self.assertIsNone(mcHeader.customSpace)

        mcHeader = MemoryConfigurationHeader(0xFD)
        self.assertIs(mcHeader.spaceIndex, MemorySpaceIndex.Configuration)
        self.assertEqual(mcHeader.spaceIndex.value, 0x01)
        self.assertIsNone(mcHeader.customSpace)
