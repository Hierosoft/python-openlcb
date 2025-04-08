import unittest

from openlcb.canbus.canphysicallayergridconnect import (
    GC_END_BYTE,
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canframe import CanFrame
from openlcb.nodeid import NodeID


class CanPhysicalLayerGridConnectTest(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        super(CanPhysicalLayerGridConnectTest, self).__init__(*args, **kwargs)
        # self.capturedString = ""
        self.capturedFrame = None
        self.receivedFrames = []

    # PHY side
    # def captureString(self, string):
    #     self.capturedString = string

    # PHY side
    def frameSocketSendDummy(self, frame):
        # formerly captureString(self, string)
        self.capturedFrame = frame
        self.capturedFrame.encoder = self.gc

    # Link Layer side
    def receiveListener(self, frame):
        self.receivedFrames += [frame]

    def testCID4Sent(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)

        self.gc.sendCanFrame(CanFrame(4, NodeID(0x010203040506), 0xABC))
        # self.assertEqual(self.capturedString, ":X14506ABCN;\n")
        self.assertEqual(self.capturedFrame.encodeAsString(), ":X14506ABCN;\n")

    def testVerifyNodeSent(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)

        self.gc.sendCanFrame(
            CanFrame(0x19170, 0x365, bytearray([
                0x02, 0x01, 0x12, 0xFE,
                0x05, 0x6C])))
        # self.assertEqual(self.capturedString, ":X19170365N020112FE056C;\n")
        self.assertEqual(self.capturedFrame.encodeAsString(),
                         ":X19170365N020112FE056C;\n")

    def testOneFrameReceivedExactlyHeaderOnly(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x34, 0x39, 0x30, 0x33, 0x36, 0x35,
            0x4e, GC_END_BYTE, 0x0a])  # :X19490365N;\n

        self.gc.pushChars(bytes)

        self.assertEqual(
            self.receivedFrames[0],
            CanFrame(0x19490365, bytearray())
        )

    def testOneFrameReceivedExactlyWithData(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x31, 0x42, 0x30, 0x33, 0x36, 0x35,
            0x4e, 0x30,
            0x32, 0x30, 0x31, 0x31, 0x32, 0x46, 0x45, 0x30, 0x35, 0x36,
            0x43, GC_END_BYTE])
        # :X19170365N020112FE056C;

        self.gc.pushChars(bytes)

        self.assertEqual(
            self.receivedFrames[0],
            CanFrame(0x191B0365,
                     bytearray([0x02, 0x01, 0x12, 0xFE, 0x05, 0x6C]))
        )

    def testOneFrameReceivedHeaderOnlyTwice(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x34, 0x39, 0x30, 0x33, 0x36, 0x35,
            0x4e, GC_END_BYTE, 0x0a])  # :X19490365N;\n

        self.gc.pushChars(bytes+bytes)

        self.assertEqual(self.receivedFrames[0],
                         CanFrame(0x19490365, bytearray()))
        self.assertEqual(self.receivedFrames[1],
                         CanFrame(0x19490365, bytearray()))

    def testOneFrameReceivedHeaderOnlyPlusPartOfAnother(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x34, 0x39, 0x30, 0x33, 0x36,
            0x35, 0x4e, GC_END_BYTE, 0x0a,  # :X19490365N;\n
            0x3a, 0x58])
        self.gc.pushChars(bytes)

        self.assertEqual(self.receivedFrames[0],
                         CanFrame(0x19490365, bytearray()))

        bytes = bytearray([
            0x31, 0x39, 0x34, 0x39, 0x30, 0x33,
            0x36, 0x35, 0x4e, GC_END_BYTE, 0x0a])
        self.gc.pushChars(bytes)

        self.assertEqual(self.receivedFrames[1],
                         CanFrame(0x19490365, bytearray()))

    def testOneFrameReceivedInTwoChunks(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes1 = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x31, 0x37, 0x30, 0x33, 0x36, 0x35,
            0x4e, 0x30])
        # :X19170365N020112FE056C;

        self.gc.pushChars(bytes1)

        bytes2 = bytearray([
            0x32, 0x30, 0x31, 0x31, 0x32, 0x46, 0x45, 0x30, 0x35, 0x36,
            0x43, GC_END_BYTE])
        self.gc.pushChars(bytes2)

        self.assertEqual(
            self.receivedFrames[0],
            CanFrame(0x19170365,
                     bytearray([0x02, 0x01, 0x12, 0xFE, 0x05, 0x6C]))
        )

    def testSequence(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x34, 0x39, 0x30, 0x33,
            0x36, 0x35, 0x4e, GC_END_BYTE, 0x0a])
        # :X19490365N;\n

        self.gc.pushChars(bytes)

        self.assertEqual(len(self.receivedFrames), 1)
        self.assertEqual(self.receivedFrames[0],
                         CanFrame(0x19490365, bytearray()))
        self.receivedFrames = []

        self.gc.pushChars(bytes)
        self.assertEqual(len(self.receivedFrames), 1)
        self.assertEqual(self.receivedFrames[0],
                         CanFrame(0x19490365, bytearray()))


if __name__ == '__main__':
    unittest.main()
