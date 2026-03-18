# -*- coding: utf-8 -*-
import os
import struct
import sys
import unittest

from logging import getLogger

from openlcb.convert import Convert
from openlcb.physicallayer import PhysicalLayer
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

from openlcb.nodeid import NodeID  # noqa: E402
from openlcb.linklayer import LinkLayer  # noqa: E402
from openlcb.mti import MTI  # noqa: E402
from openlcb.message import Message  # noqa: E402
from openlcb.memoryservice import (  # noqa: E402
    MemoryReadMemo,
    MemoryWriteMemo,
    MemoryService,
)
from openlcb.datagramservice import (  # noqa: E402
    # DatagramWriteMemo,
    # DatagramReadMemo,
    DatagramService,
)


class MockPhysicalLayer(PhysicalLayer):
    pass


class LinkMockLayer(LinkLayer):

    class State:
        Initial = 0
        Disconnected = 1
        Permitted = 2

    DisconnectedState = State.Disconnected

    sentMessages = []

    def sendMessage(self, msg, verbose=False):
        LinkMockLayer.sentMessages.append(msg)

    def _onStateChanged(self, oldState, newState):
        print(f"State changed from {oldState} to {newState}"
              " (nothing to clean up since LinkMockLayer).")


class TestMemoryServiceClass(unittest.TestCase):

    def callbackR(self, memo):
        self.returnedMemoryReadMemo.append(memo)

    def callbackW(self, memo):
        self.returnedMemoryWriteMemo.append(memo)

    def setUp(self):
        LinkMockLayer.sentMessages = []
        self.returnedMemoryReadMemo = []
        self.returnedMemoryWriteMemo = []
        self.dService = DatagramService(
            LinkMockLayer(MockPhysicalLayer(), NodeID(12))
        )
        self.mService = MemoryService(self.dService)

    def testSingleRead(self):
        memMemo = MemoryReadMemo(NodeID(123), 64, 0xFD, 0,
                                 self.callbackR, self.callbackR)
        self.mService.requestMemoryRead(memMemo)
        self.assertEqual(len(LinkMockLayer.sentMessages), 1)
        # ^ memory request datagram sent

        # have to reply through DatagramService
        self.dService.process(Message(MTI.Datagram_Received_OK, NodeID(123),
                                      NodeID(12)))
        self.assertEqual(len(LinkMockLayer.sentMessages), 1)
        # ^ memory request datagram sent
        self.assertEqual(LinkMockLayer.sentMessages[0].data,
                         bytearray([0x20, 0x41, 0, 0, 0, 0, 64]))
        self.assertEqual(len(self.returnedMemoryReadMemo), 0)
        # ^ no memory read op returned

        self.dService.process(
            Message(MTI.Datagram, NodeID(123), NodeID(12),
                    bytearray([0x20, 0x51, 0, 0, 0, 0, 1, 2, 3, 4])))
        self.assertEqual(len(LinkMockLayer.sentMessages), 2)
        # read reply datagram reply sent
        self.assertEqual(len(self.returnedMemoryReadMemo), 1)
        # memory read returned

    def testSingleWrite(self):
        memMemo = MemoryWriteMemo(NodeID(123),
                                  self.callbackW, self.callbackW,
                                  64, 0xFD, 0,
                                  bytearray([1, 2, 3]))
        self.mService.requestMemoryWrite(memMemo)
        self.assertEqual(len(LinkMockLayer.sentMessages), 1)
        # ^ memory request datagram sent

        # have to reply through DatagramService
        self.dService.process(Message(MTI.Datagram_Received_OK, NodeID(123),
                                      NodeID(12)))
        self.assertEqual(len(LinkMockLayer.sentMessages), 1)
        # ^ memory request datagram sent
        self.assertEqual(LinkMockLayer.sentMessages[0].data,
                         bytearray([
                             0x20, 0x01,
                             0, 0, 0, 0,
                             1, 2, 3]))
        self.assertEqual(len(self.returnedMemoryWriteMemo), 0)
        # ^ no memory write op returned

        self.dService.process(Message(MTI.Datagram, NodeID(123), NodeID(12),
                                      bytearray([0x20,
                                                 0x11,
                                                 0, 0, 0, 0])))
        self.assertEqual(len(LinkMockLayer.sentMessages), 2)
        # ^ write reply datagram reply sent
        self.assertEqual(len(self.returnedMemoryWriteMemo), 1)
        # ^ memory write returned

    def testMultipleRead(self):

        # make three requests, only one of which should go forward at a time
        memMemo0 = MemoryReadMemo(NodeID(123), 64, 0xFD, 0,
                                  self.callbackR, self.callbackR)
        self.mService.requestMemoryRead(memMemo0)
        memMemo64 = MemoryReadMemo(NodeID(123), 32, 0xFD, 64,
                                   self.callbackR, self.callbackR)
        self.mService.requestMemoryRead(memMemo64)
        memMemo128 = MemoryReadMemo(NodeID(123), 16, 0xFD, 128,
                                    self.callbackR, self.callbackR)
        self.mService.requestMemoryRead(memMemo128)

        self.assertEqual(len(LinkMockLayer.sentMessages), 1)
        # ^ only one memory request datagram sent

        # have to reply through DatagramService
        self.dService.process(Message(MTI.Datagram_Received_OK, NodeID(123),
                                      NodeID(12)))
        self.assertEqual(len(LinkMockLayer.sentMessages), 1)  # memory request datagram sent  # noqa: E501
        self.assertEqual(LinkMockLayer.sentMessages[0].data,
                         bytearray([0x20, 0x41, 0,0,0,0, 64]))  # noqa: E231
        self.assertEqual(len(self.returnedMemoryReadMemo), 0)  # no memory read op returned  # noqa: E501

        self.dService.process(
            Message(MTI.Datagram, NodeID(123), NodeID(12),
                    bytearray([0x20, 0x51, 0,0,0,0, 1,2,3,4])))  # noqa: E231
        self.assertEqual(len(LinkMockLayer.sentMessages), 3)  # read reply datagram reply sent and next datagram sent  # noqa: E501
        self.assertEqual(len(self.returnedMemoryReadMemo), 1)  # memory read returned  # noqa: E501

        # walk through 2nd datagram
        self.dService.process(Message(MTI.Datagram_Received_OK, NodeID(123),
                                      NodeID(12)))
        self.assertEqual(len(LinkMockLayer.sentMessages), 3)  # memory request datagram sent  # noqa: E501
        self.assertEqual(LinkMockLayer.sentMessages[2].data,
                         bytearray([0x20, 0x41, 0,0,0,64, 32]))  # noqa: E231,E501
        self.assertEqual(len(self.returnedMemoryReadMemo), 1)  # no memory read op returned  # noqa: E501

        self.dService.process(
            Message(MTI.Datagram, NodeID(123), NodeID(12),
                    bytearray([0x20, 0x51,
                               0, 0, 0, 64,
                               1, 2, 3, 4])))
        self.assertEqual(len(LinkMockLayer.sentMessages), 5)  # read reply datagram reply sent and next datagram sent  # noqa: E501
        self.assertEqual(len(self.returnedMemoryReadMemo), 2)  # memory read returned  # noqa: E501


if __name__ == '__main__':
    unittest.main()
