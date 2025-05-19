from typing import Callable
import unittest

from openlcb import emit_cast
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
        # ^ Sets onQueuedFrame on None, so set it afterward:
        self.onQueuedFrame = self.captureString

    def captureString(self, frame):
        # formerly was in CanPhysicalLayerGridConnectTest
        #   but there isn't a send callback anymore
        #   (to avoid port contention in issue #62)
        #   just a physical layer.
        assert isinstance(frame, CanFrame), \
            "CanFrame expected, got {}".format(emit_cast(frame))
        self.capturedFrame = frame
        self.capturedFrame.encoder = self
        self.capturedString = frame.encodeAsString()

    def onFrameSent(self, frame):
        pass
        # NOTE: not patching this method to be canLink.handleFrameSent
        #   since testing only physical layer not link layer.

    def onFrameReceived(self, frame):
        pass
        # NOTE: not patching
        #   self.onFrameReceived = canLink.handleFrameReceived
        #   since testing only physical layer not link layer.


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
        self.gc = PhysicalLayerMock()
        frame = CanFrame(4, NodeID(0x010203040506), 0xABC)
        # self.linklayer.sendFrameAfter(frame)
        # ^ It will use physical layer to encode and enqueue it
        #   (or send if using Realtime subclass of PhysicalLayer)
        #   but we are testing physical layer, so:
        self.gc.sendFrameAfter(frame)
        assert self.gc.onQueuedFrame is not None
        # self.assertEqual(self.capturedString, ":X14506ABCN;\n")
        self.assertEqual(self.gc.capturedString,
                         ":X14506ABCN;\n")

    def testVerifyNodeSent(self):
        self.gc = PhysicalLayerMock()
        frame = CanFrame(0x19170, 0x365,
                         bytearray([0x02, 0x01, 0x12, 0xFE, 0x05, 0x6C]))
        frame.encoder = self.gc
        assert self.gc.onQueuedFrame is not None
        self.gc.sendFrameAfter(frame)
        # self.assertEqual(self.capturedString, ":X19170365N020112FE056C;\n")
        self.assertEqual(self.gc.capturedString,
                         ":X19170365N020112FE056C;\n")

    def testOneFrameReceivedExactlyHeaderOnly(self):
        self.gc = PhysicalLayerMock()
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
        self.gc = PhysicalLayerMock()
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
        self.gc = PhysicalLayerMock()
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
        self.gc = PhysicalLayerMock()
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
        self.gc = PhysicalLayerMock()
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
        self.gc = PhysicalLayerMock()
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
