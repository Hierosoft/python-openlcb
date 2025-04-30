import unittest

from openlcb.canbus.canphysicallayergridconnect import (
    GC_END_BYTE,
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canframe import CanFrame
from openlcb.nodeid import NodeID

class PhysicalLayerMock(CanPhysicalLayerGridConnect):
    # PHY side
    # def frameSocketSendDummy(self, frame):
    def __init__(self):
        CanPhysicalLayerGridConnect.__init__(self)
        self.registerFrameQueuedListener(self.captureString)

    def captureString(self, packet):
        # formerly was in CanPhysicalLayerGridConnectTest
        # but there isn't a send callback anymore
        # (to avoid port contention in issue #62)
        # just a physical layer.
        self. capturedFrame = packet
        self. capturedFrame.encoder = self.gc

        if frame.afterSendState:
            pass
            # NOTE: skipping canLink.setState since testing only
            # physical layer not link layer.
            #     canLink.setState(frame.afterSendState)

class CanPhysicalLayerGridConnectTest(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        super(CanPhysicalLayerGridConnectTest, self).__init__(*args, **kwargs)
        # self.capturedString = ""
        self.physicalLayer = PhysicalLayerMock()
        self.physicalLayer.capturedFrame = None
        self.receivedFrames = []

    # PHY side
    # def captureString(self, string):
    #     self.capturedString = string


    # Link Layer side
    def receiveListener(self, frame):
        self.receivedFrames += [frame]

    def testCID4Sent(self):
        self.gc = CanPhysicalLayerGridConnect()
        frame = CanFrame(4, NodeID(0x010203040506), 0xABC)
        # self.linklayer.sendFrameAfter(frame)
        # ^ It will use physical layer to encode and enqueue it
        #   (or send if using Realtime subclass of PhysicalLayer)
        #   but we are testing physical layer, so:
        self.gc.sendFrameAfter(frame)

        # self.assertEqual(self.capturedString, ":X14506ABCN;\n")
        self.assertEqual(self.physicalLayer.capturedFrame.encodeAsString(),
                         ":X14506ABCN;\n")

    def testVerifyNodeSent(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        frame = CanFrame(0x19170, 0x365,
                         bytearray([0x02, 0x01, 0x12, 0xFE, 0x05, 0x6C]))
        self.gc.sendFrameAfter(
            self.gc.encode(frame)
        )
        # self.assertEqual(self.capturedString, ":X19170365N020112FE056C;\n")
        self.assertEqual(self.physicalLayer.capturedFrame,
                         ":X19170365N020112FE056C;\n")

    def testOneFrameReceivedExactlyHeaderOnly(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x34, 0x39, 0x30, 0x33, 0x36, 0x35,
            0x4e, GC_END_BYTE, 0x0a])  # :X19490365N;\n

        self.gc.handleData(bytes)

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

        self.gc.handleData(bytes)

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

        self.gc.handleData(bytes+bytes)

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
        self.gc.handleData(bytes)

        self.assertEqual(self.receivedFrames[0],
                         CanFrame(0x19490365, bytearray()))

        bytes = bytearray([
            0x31, 0x39, 0x34, 0x39, 0x30, 0x33,
            0x36, 0x35, 0x4e, GC_END_BYTE, 0x0a])
        self.gc.handleData(bytes)

        self.assertEqual(self.receivedFrames[1],
                         CanFrame(0x19490365, bytearray()))

    def testOneFrameReceivedInTwoChunks(self):
        self.gc = CanPhysicalLayerGridConnect(self.frameSocketSendDummy)
        self.gc.registerFrameReceivedListener(self.receiveListener)
        bytes1 = bytearray([
            0x3a, 0x58, 0x31, 0x39, 0x31, 0x37, 0x30, 0x33, 0x36, 0x35,
            0x4e, 0x30])
        # :X19170365N020112FE056C;

        self.gc.handleData(bytes1)

        bytes2 = bytearray([
            0x32, 0x30, 0x31, 0x31, 0x32, 0x46, 0x45, 0x30, 0x35, 0x36,
            0x43, GC_END_BYTE])
        self.gc.handleData(bytes2)

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

        self.gc.handleData(bytes)

        self.assertEqual(len(self.receivedFrames), 1)
        self.assertEqual(self.receivedFrames[0],
                         CanFrame(0x19490365, bytearray()))
        self.receivedFrames = []

        self.gc.handleData(bytes)
        self.assertEqual(len(self.receivedFrames), 1)
        self.assertEqual(self.receivedFrames[0],
                         CanFrame(0x19490365, bytearray()))


if __name__ == '__main__':
    unittest.main()
