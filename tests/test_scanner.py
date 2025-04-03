import unittest

from openlcb.canbus.canphysicallayergridconnect import GC_END_BYTE
from openlcb.canbus.gridconnectobserver import GridConnectObserver
from openlcb.scanner import Scanner


class TestScanner(unittest.TestCase) :
    def test_scanner(self):
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x34, 0x39, 0x30, 0x33, 0x36, 0x35,
            0x4e, GC_END_BYTE, 0x0a])  # :X19490365N;\n
        scanner = Scanner()
        self.assertFalse(scanner.hasNext())
        self.assertFalse(scanner.hasNextByte())
        scanner.push(bytes[0])
        self.assertTrue(scanner.hasNext())  # True since default is EOF
        self.assertTrue(scanner.hasNextByte())
        self.assertTrue(scanner.hasNextByte())  # make sure not mutated
        # test_gridconnectobserver covers more details
        #   of Scanner since Scanner is the superclass
        #   and defines all behaviors other than _delimiter for now.

    def test_gridconnectobserver(self):
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x34, 0x39, 0x30, 0x33, 0x36, 0x35,
            0x4e, GC_END_BYTE, 0x0a])  # :X19490365N;\n
        gc_end_byte_idx = bytes.index(GC_END_BYTE)
        scanner = GridConnectObserver()
        self.assertFalse(scanner.hasNext())
        self.assertFalse(scanner.hasNextByte())
        scanner.push(bytes[0])
        self.assertFalse(scanner.hasNext())  # False since default is
        # GC_END_BYTE in GridConnectObserver and we haven't added
        # GC_END_BYTE yet (see below)
        self.assertTrue(scanner.hasNextByte())
        self.assertTrue(scanner.hasNextByte())  # make sure not mutated
        scanner.push(bytes[1:-2])  # all except ;\n
        self.assertFalse(scanner.hasNext())
        self.assertTrue(scanner.hasNextByte())  # make sure not mutated
        assert gc_end_byte_idx < len(len(bytes))-1, "test is flawed"
        scanner.push(bytes[gc_end_byte_idx:gc_end_byte_idx+1])  # GC_END_BYTE
        self.assertTrue(scanner.hasNext())
        data = scanner.nextBytes()
        self.assertEqual(data, bytes[:gc_end_byte_idx+1])  # make sure got
        #  everything up to and including GC_END_BYTE
        self.assertFalse(scanner.hasNext())  # make sure *was* mutated by next
        self.assertEqual(len(scanner._buffer), 1)
        self.assertEqual(scanner._buffer[0], bytes[-1])  # last byte is after
        #  delimiter, so it should remain.


