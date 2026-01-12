from typing import Union
import unittest

from openlcb import formatted_ex
from openlcb.canbus.canlink import CanLink

from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.canlinklayersimulation import CanLinkLayerSimulation
from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.canbus.canphysicallayersimulation import (
    CanPhysicalLayerSimulation
)
from openlcb.message import Message
from openlcb.mti import MTI
from openlcb.nodeid import NodeID
from openlcb.canbus.controlframe import ControlFrame
from openlcb.portinterface import PortInterface


class PhyMockLayer(CanPhysicalLayer):
    # FIXME: Doesn't work anymore. (Was) used for
    #   testZeroLengthDatagram, testOneFrameDatagram,
    #   testToFrameDataGram, testThreeFrameDatagram,
    #   so use it in those places if fixed.

    def __init__(self):
        # onFrameSent will not work until this instance is passed to the
        #   LinkLayer subclass' constructor (See onFrameSent
        #   docstring in PhysicalLayer)
        self.sentFrames = []
        CanPhysicalLayer.__init__(self)

    def sendDataAfter(self, data, verbose=False):
        # verbose: ignored since used in sendAll when not a Realtime subclass.
        assert isinstance(data, (bytes, bytearray))
        self.sentFrames.append(data)

    def sendAll(self, _, mode="binary", verbose=True) -> int:
        """Simulated sendAll
        The simulation has no real communication, so no device argument
        is necessary. See CanLink for a real implementation.

        Args:
            verbose (bool, optional): If True, print the packet (not
                recommended in the case of numerous sequential memory
                read requests such as when reading CDI/FDI).
        """
        count = 0
        if self.linkLayer:
            self.linkLayer.pollState()  # run first since may enqueue frame(s)
        while True:
            # self.linkLayer must be set by canLink/superclass constructor by
            #   passing a physicalLayer to it.
            frame = self.linkLayer.pollFrame()
            if not frame:
                break
            # ^ If using popleft, break on IndexError (empty) instead.
            if self.linkLayer:
                if self.linkLayer.isCanceled(frame):
                    if verbose:
                        print("- Skipped (probably dup alias CID frame).")
                    continue

            string = frame.encodeAsString()
            # device.sendString(string)  # commented since simulation
            if verbose:
                print("- SENT frame (simulated socket) packet: {}"
                      .format(string.strip()))
            self.onFrameSent(frame)
            count += 1
        return count


class MessageMockLayer:
    '''Mock Message to record messages requested to be sent'''
    def __init__(self):
        self.receivedMessages = []

    def receiveMessage(self, msg):
        self.receivedMessages.append(msg)


class MockPort(PortInterface):
    def send(self, data: Union[bytearray, bytes]):
        pass

    def sendString(self, data: str):
        pass

    def receive(self):
        return None


def getLocalNodeIDStr():
    return "05.01.01.01.03.01"


def getLocalNodeID():
    return NodeID(getLocalNodeIDStr())


class TestCanLinkClass(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        self.device = MockPort()
        super(TestCanLinkClass, self).__init__(*args, **kwargs)

    def assertFrameEqual(self, frame: CanFrame, other: CanFrame):
        self.assertEqual(frame, other, msg=frame.difference(other))

    # MARK: - Alias calculations
    def testIncrementAlias48(self):
        physicalLayer = PhyMockLayer()
        canLink = CanLinkLayerSimulation(physicalLayer, getLocalNodeID())

        # check precision of calculation
        self.assertEqual(canLink.incrementAlias48(0), 0x1B0C_A37A_4BA9,
                         "0 initial value")

        # test shift and multiplication operations
        next = canLink.incrementAlias48(0x0000_0000_0001)
        self.assertEqual(next, 0x1B0C_A37A_4DAA)
        physicalLayer.physicalLayerDown()

    def testIncrementAliasSequence(self):
        physicalLayer = PhyMockLayer()
        canLink = CanLinkLayerSimulation(physicalLayer, getLocalNodeID())

        # sequence from TN
        next = canLink.incrementAlias48(0)
        self.assertEqual(next, 0x1B0C_A37A_4BA9, "0 initial value")

        next = canLink.incrementAlias48(next)
        self.assertEqual(next, 0x4F_60_3B_8B_E9_52)

        next = canLink.incrementAlias48(next)
        self.assertEqual(next, 0x2A_E3_F6_D8_D8_FB)

        next = canLink.incrementAlias48(next)
        self.assertEqual(next, 0x0D_DE_4C_05_1A_A4)

        next = canLink.incrementAlias48(next)
        self.assertEqual(next, 0xE5_82_F9_B4_AE_4D)
        physicalLayer.physicalLayerDown()

    def testCreateAlias12(self):
        physicalLayer = PhyMockLayer()
        canLink = CanLinkLayerSimulation(physicalLayer, getLocalNodeID())

        # check precision of calculation
        self.assertEqual(canLink.createAlias12(0x001), 0x001, "0x001 input")
        self.assertEqual(canLink.createAlias12(0x1_000), 0x001, "0x1000 input")
        self.assertEqual(canLink.createAlias12(0x1_000_000), 0x001,
                         "0x1000000 input")

        self.assertEqual(canLink.createAlias12(0x4_002_001), 0x007)

        self.assertEqual(canLink.createAlias12(0x1001), 0x002,
                         "0x1001 random input checks against zero")

        self.assertEqual(canLink.createAlias12(0x0000), 0xAEF,
                         "zero input check")
        physicalLayer.physicalLayerDown()

    # MARK: - Test PHY Up
    def testLinkUpSequence(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(
            canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)

        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        self.assertEqual(len(canPhysicalLayer.sentFrames), 7)
        self.assertEqual(canLink._state, CanLink.State.Permitted)

        self.assertEqual(len(messageLayer.receivedMessages), 1)
        canPhysicalLayer.physicalLayerDown()

    # MARK: - Test PHY Down, Up, Error Information
    def testLinkDownSequence(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)
        canLink._state = CanLink.State.Permitted

        canPhysicalLayer.physicalLayerDown()

        self.assertEqual(canLink._state, CanLink.State.Inhibited)
        self.assertEqual(len(messageLayer.receivedMessages), 1)
        canPhysicalLayer.physicalLayerDown()

    def testEIR2NoData(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        canLink._state = CanLink.State.Permitted

        canPhysicalLayer.fireFrameReceived(
            CanFrame(ControlFrame.EIR2.value, 0))
        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        canPhysicalLayer.physicalLayerDown()

    # MARK: - Test AME (Local Node)
    def testAMENoData(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        ourAlias = canLink._localAlias  # 576 with NodeID(0x05_01_01_01_03_01)
        canLink._state = CanLink.State.Permitted

        canPhysicalLayer.fireFrameReceived(CanFrame(ControlFrame.AME.value, 0))
        canPhysicalLayer.sendAll(None)  # add response to sentFrames
        self.assertEqual(len(canPhysicalLayer.sentFrames), 1)
        self.assertFrameEqual(
            canPhysicalLayer.sentFrames[0],
            CanFrame(ControlFrame.AMD.value, ourAlias,
                     canLink.localNodeID.toArray())
        )
        canPhysicalLayer.physicalLayerDown()

    def testAMEnoDataInhibited(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        canLink._state = CanLink.State.Inhibited

        canPhysicalLayer.fireFrameReceived(CanFrame(ControlFrame.AME.value, 0))
        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        canPhysicalLayer.physicalLayerDown()

    def testAMEMatchEvent(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        ourAlias = canLink._localAlias  # 576 with NodeID(0x05_01_01_01_03_01)
        canLink._state = CanLink.State.Permitted

        frame = CanFrame(ControlFrame.AME.value, 0)
        frame.data = bytearray([5, 1, 1, 1, 3, 1])
        canPhysicalLayer.fireFrameReceived(frame)
        canPhysicalLayer.sendAll(None)  # add response to sentFrames
        self.assertEqual(len(canPhysicalLayer.sentFrames), 1)
        self.assertFrameEqual(
            canPhysicalLayer.sentFrames[0],
            CanFrame(ControlFrame.AMD.value, ourAlias,
                     canLink.localNodeID.toArray()))
        canPhysicalLayer.physicalLayerDown()

    def testAMENotMatchEvent(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        canLink._state = CanLink.State.Permitted

        frame = CanFrame(ControlFrame.AME.value, 0)
        frame.data = bytearray([0, 0, 0, 0, 0, 0])
        canPhysicalLayer.fireFrameReceived(frame)
        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        canPhysicalLayer.physicalLayerDown()

    # MARK: - Test Alias Collisions (Local Node)
    def testCIDreceivedMatch(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        ourAlias = canLink._localAlias  # 576 with NodeID(0x05_01_01_01_03_01)
        canLink._state = CanLink.State.Permitted

        canPhysicalLayer.fireFrameReceived(
            CanFrame(7, canLink.localNodeID, ourAlias))
        canPhysicalLayer.sendAll(None)  # add response to sentFrames
        self.assertEqual(len(canPhysicalLayer.sentFrames), 1)
        self.assertFrameEqual(canPhysicalLayer.sentFrames[0],
                              CanFrame(ControlFrame.RID.value, ourAlias))
        canPhysicalLayer.physicalLayerDown()

    def testRIDreceivedMatch(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        ourAlias = canLink._localAlias  # 576 with NodeID(0x05_01_01_01_03_01)
        canLink._state = CanLink.State.Permitted

        canPhysicalLayer.fireFrameReceived(
            CanFrame(ControlFrame.RID.value, ourAlias))
        # ^ collision
        canLink.waitForReady(self.device)
        self.assertEqual(len(canPhysicalLayer.sentFrames), 8)
        # ^ includes recovery of new alias 4 CID, RID, AMR, AME
        self.assertFrameEqual(
            canPhysicalLayer.sentFrames[0],
            CanFrame(ControlFrame.AMR.value, ourAlias,
                     bytearray([5, 1, 1, 1, 3, 1])))
        self.assertEqual(
            canPhysicalLayer.sentFrames[6],
            CanFrame(ControlFrame.AMD.value, 0x539,
                     bytearray([5, 1, 1, 1, 3, 1])))  # new alias
        self.assertEqual(canLink._state, CanLink.State.Permitted)
        canPhysicalLayer.physicalLayerDown()

    def testCheckMTIMapping(self):

        physicalLayer = PhyMockLayer()
        canLink = CanLinkLayerSimulation(physicalLayer, getLocalNodeID())
        self.assertEqual(
            canLink.canHeaderToFullFormat(
                CanFrame(0x19490247, bytearray())),
            MTI.Verify_NodeID_Number_Global
        )

    def testControlFrameDecode(self):
        physicalLayer = PhyMockLayer()
        canLink = CanLinkLayerSimulation(physicalLayer, getLocalNodeID())
        frame = CanFrame(0x1000, 0x000)  # invalid control frame content
        self.assertEqual(canLink.decodeControlFrameFormat(frame),
                         ControlFrame.UnknownFormat)
        physicalLayer.physicalLayerDown()

    def testControlFrameIsInternal(self):
        self.assertFalse(ControlFrame.isInternal(ControlFrame.AMD))
        self.assertFalse(ControlFrame.isInternal(ControlFrame.CID))
        self.assertFalse(ControlFrame.isInternal(ControlFrame.Data))

        # These are non-openlcb values used for internal signaling
        #   their values have a bit set above what can come from a CAN Frame.
        self.assertTrue(ControlFrame.isInternal(ControlFrame.LinkUp))
        self.assertTrue(ControlFrame.isInternal(ControlFrame.LinkRestarted))
        self.assertTrue(ControlFrame.isInternal(ControlFrame.LinkCollision))
        self.assertTrue(ControlFrame.isInternal(ControlFrame.LinkError))
        self.assertTrue(ControlFrame.isInternal(ControlFrame.LinkDown))
        self.assertTrue(ControlFrame.isInternal(ControlFrame.UnknownFormat))

        # Test bad ControlFrame.*.value (only possible if *not*
        #   ControlFrame type, so assertRaises is not necessary above).
        self.assertRaises(
            ValueError,
            lambda x=0x21001: ControlFrame.isInternal(x),
        )

        # If it is not ControlFrame nor int, it is "not in" values:
        self.assertRaises(
            ValueError,
            lambda x="21000": ControlFrame.isInternal(x),
        )
        self.assertRaises(
            ValueError,
            lambda x=21000.0: ControlFrame.isInternal(x),
        )

        # Allow int if not ControlFrame but is a ControlFrame.*.value
        self.assertTrue(ControlFrame.isInternal(0x20000))
        self.assertTrue(ControlFrame.isInternal(0x21000))

    def testSimpleGlobalData(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)
        canLink._state = CanLink.State.Permitted

        # map an alias we'll use
        amd = CanFrame(0x0701, 0x247)
        amd.data = bytearray([1, 2, 3, 4, 5, 6])
        canPhysicalLayer.fireFrameReceived(amd)

        canPhysicalLayer.fireFrameReceived(CanFrame(0x19490, 0x247))
        # ^ from previously seen alias

        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        # ^ nothing back down to CAN
        self.assertEqual(len(messageLayer.receivedMessages), 1)
        # ^ one message forwarded
        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[0].mti,
                         MTI.Verify_NodeID_Number_Global)
        self.assertEqual(messageLayer.receivedMessages[0].source,
                         NodeID(0x010203040506))
        canPhysicalLayer.physicalLayerDown()

    def testVerifiedNodeInDestAliasMap(self):
        # JMRI doesn't send AMD, so gets assigned 00.00.00.00.00.00
        # This tests that a VerifiedNode will update that.

        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)
        canLink._state = CanLink.State.Permitted  # normally set via pollState

        # Don't map an alias with an AMD for this test

        canPhysicalLayer.fireFrameReceived(
            CanFrame(0x19170, 0x247, bytearray([8, 7, 6, 5, 4, 3])))
        # ^ VerifiedNodeID from unique alias

        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        # ^ nothing back down to CAN
        self.assertEqual(len(messageLayer.receivedMessages), 1)
        # ^ one message forwarded
        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[0].mti,
                         MTI.Verified_NodeID)
        self.assertEqual(messageLayer.receivedMessages[0].source,
                         NodeID(0x080706050403))
        canPhysicalLayer.physicalLayerDown()

    def testNoDestInAliasMap(self):
        '''Tests handling of a message with a destination alias not in map
        (should not happen, but...)
        '''

        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)
        canLink._state = CanLink.State.Permitted

        # Don't map an alias with an AMD for this test

        canPhysicalLayer.fireFrameReceived(
            CanFrame(0x19968, 0x247, bytearray([8, 7, 6, 5, 4, 3])))
        # ^ Identify Events Addressed from unique alias

        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        # ^ nothing back down to CAN
        self.assertEqual(len(messageLayer.receivedMessages), 1)
        # ^ one message forwarded
        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[0].mti,
                         MTI.Identify_Events_Addressed)
        self.assertEqual(messageLayer.receivedMessages[0].source,
                         NodeID(0x000000000001))
        canPhysicalLayer.physicalLayerDown()

    def testSimpleAddressedData(self):  # Test start=yes, end=yes frame
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(
            canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)

        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        # map an alias we'll use
        amd = CanFrame(0x0701, 0x247)
        amd.data = bytearray([1, 2, 3, 4, 5, 6])
        canPhysicalLayer.fireFrameReceived(amd)

        ourAlias = canLink.getLocalAlias()
        # ^ 576 with NodeID(0x05_01_01_01_03_01)
        frame = CanFrame(0x19488, 0x247)  # Verify Node ID Addressed
        frame.data = bytearray([((ourAlias & 0x700) >> 8), (ourAlias & 0xFF),
                                12, 13])
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias

        self.assertEqual(len(messageLayer.receivedMessages), 2)
        # ^ startup plus one message forwarded
        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[1].mti,
                         MTI.Verify_NodeID_Number_Addressed)
        self.assertEqual(messageLayer.receivedMessages[1].source,
                         NodeID(0x01_02_03_04_05_06))
        self.assertEqual(messageLayer.receivedMessages[1].destination,
                         NodeID(0x05_01_01_01_03_01))
        self.assertEqual(len(messageLayer.receivedMessages[1].data), 2)
        self.assertEqual(messageLayer.receivedMessages[1].data[0], 12)
        self.assertEqual(messageLayer.receivedMessages[1].data[1], 13)
        canPhysicalLayer.physicalLayerDown()

    def testSimpleAddressedDataNoAliasYet(self):
        '''Test start=yes, end=yes frame with no alias match'''
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(
            canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)

        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        # don't map alias with AMD

        # send Verify Node ID Addressed from unknown alias
        ourAlias = canLink._localAlias  # 576 with NodeID(0x05_01_01_01_03_01)
        frame = CanFrame(0x19488, 0x247)  # Verify Node ID Addressed
        frame.data = bytearray(
            [((ourAlias & 0x700) >> 8), (ourAlias & 0xFF), 12, 13]
        )
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias

        self.assertEqual(len(messageLayer.receivedMessages), 2)
        # ^ startup plus one message forwarded

        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[1].mti,
                         MTI.Verify_NodeID_Number_Addressed)
        self.assertEqual(messageLayer.receivedMessages[1].source,
                         NodeID(0x00_00_00_00_00_01))
        self.assertEqual(messageLayer.receivedMessages[1].destination,
                         NodeID(0x05_01_01_01_03_01))
        self.assertEqual(len(messageLayer.receivedMessages[1].data), 2)
        self.assertEqual(messageLayer.receivedMessages[1].data[0], 12)
        self.assertEqual(messageLayer.receivedMessages[1].data[1], 13)
        canPhysicalLayer.physicalLayerDown()

    def testMultiFrameAddressedData(self):
        '''multi-frame addressed messages - SNIP reply
        Test message in 3 frames
        '''
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(
            canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)

        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        # map an alias we'll use
        amd = CanFrame(0x0701, 0x247)
        amd.data = bytearray([1, 2, 3, 4, 5, 6])
        canPhysicalLayer.fireFrameReceived(amd)

        ourAlias = canLink._localAlias  # 576 with NodeID(0x05_01_01_01_03_01)
        frame = CanFrame(0x19488, 0x247)  # Verify Node ID Addressed
        frame.data = bytearray([(((ourAlias & 0x700) >> 8) | 0x10),
                                (ourAlias & 0xFF), 1, 2])
        # ^ start not end
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias

        self.assertEqual(len(messageLayer.receivedMessages), 1)
        # ^ startup only, no message forwarded yet

        frame = CanFrame(0x19488, 0x247)  # Verify Node ID Addressed
        frame.data = bytearray([(((ourAlias & 0x700) >> 8) | 0x20),
                                (ourAlias & 0xFF), 3, 4])
        # ^ end, not start
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias

        self.assertEqual(len(messageLayer.receivedMessages), 2)
        # ^ startup plus one message forwarded

        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[1].mti,
                         MTI.Verify_NodeID_Number_Addressed)
        self.assertEqual(messageLayer.receivedMessages[1].source,
                         NodeID(0x01_02_03_04_05_06))
        self.assertEqual(messageLayer.receivedMessages[1].destination,
                         NodeID(0x05_01_01_01_03_01))
        canPhysicalLayer.physicalLayerDown()

    def testSimpleDatagram(self):  # Test start=yes, end=yes frame
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(
            canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)

        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        # map two aliases we'll use
        amd = CanFrame(0x0701, 0x247)
        amd.data = bytearray([1, 2, 3, 4, 5, 6])
        canPhysicalLayer.fireFrameReceived(amd)
        amd = CanFrame(0x0701, 0x123)
        amd.data = bytearray([6, 5, 4, 3, 2, 1])
        canPhysicalLayer.fireFrameReceived(amd)

        frame = CanFrame(0x1A123, 0x247)  # single frame datagram
        frame.data = bytearray([10, 11, 12, 13])
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias

        self.assertEqual(len(messageLayer.receivedMessages), 2)
        # ^ startup plus one message forwarded
        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[1].mti,
                         MTI.Datagram)
        self.assertEqual(messageLayer.receivedMessages[1].source,
                         NodeID(0x01_02_03_04_05_06))
        self.assertEqual(messageLayer.receivedMessages[1].destination,
                         NodeID(0x06_05_04_03_02_01))
        self.assertEqual(len(messageLayer.receivedMessages[1].data), 4)
        self.assertEqual(messageLayer.receivedMessages[1].data[0], 10)
        self.assertEqual(messageLayer.receivedMessages[1].data[1], 11)
        self.assertEqual(messageLayer.receivedMessages[1].data[2], 12)
        self.assertEqual(messageLayer.receivedMessages[1].data[3], 13)
        canPhysicalLayer.physicalLayerDown()

    def testMultiFrameDatagram(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(
            canPhysicalLayer, getLocalNodeID())
        messageLayer = MessageMockLayer()
        canLink.registerMessageReceivedListener(messageLayer.receiveMessage)
        print("[testMultiFrameDatagram] state={}"
              .format(canLink.getState()))
        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        # map two aliases we'll use
        amd = CanFrame(0x0701, 0x247)
        amd.data = bytearray([1, 2, 3, 4, 5, 6])
        canPhysicalLayer.fireFrameReceived(amd)
        amd = CanFrame(0x0701, 0x123)
        amd.data = bytearray([6, 5, 4, 3, 2, 1])
        canPhysicalLayer.fireFrameReceived(amd)

        frame = CanFrame(0x1B123, 0x247)  # single frame datagram
        frame.data = bytearray([10, 11, 12, 13])
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias
        frame = CanFrame(0x1C123, 0x247)  # single frame datagram
        frame.data = bytearray([20, 21, 22, 23])
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias
        frame = CanFrame(0x1D123, 0x247)  # single frame datagram
        frame.data = bytearray([30, 31, 32, 33])
        canPhysicalLayer.fireFrameReceived(frame)  # from previously seen alias

        while True:
            frame = canPhysicalLayer.pollFrame()
            if frame is None:
                break
            # FIXME: Pretending sent is not effective if dest is mock node
            #   (if its state will be checked in the test!) but if we are
            #   using pure CAN (not packed with LCC alias) it is P2P.
            canPhysicalLayer.onFrameSent(frame)

        self.assertEqual(len(messageLayer.receivedMessages), 2)
        # ^ startup plus one message forwarded
        # check for proper global MTI
        self.assertEqual(messageLayer.receivedMessages[1].mti,
                         MTI.Datagram)
        self.assertEqual(messageLayer.receivedMessages[1].source,
                         NodeID(0x01_02_03_04_05_06))
        self.assertEqual(messageLayer.receivedMessages[1].destination,
                         NodeID(0x06_05_04_03_02_01))
        self.assertEqual(len(messageLayer.receivedMessages[1].data), 12)
        self.assertEqual(messageLayer.receivedMessages[1].data[0], 10)
        self.assertEqual(messageLayer.receivedMessages[1].data[1], 11)
        self.assertEqual(messageLayer.receivedMessages[1].data[2], 12)
        self.assertEqual(messageLayer.receivedMessages[1].data[3], 13)
        self.assertEqual(messageLayer.receivedMessages[1].data[4], 20)
        self.assertEqual(messageLayer.receivedMessages[1].data[5], 21)
        self.assertEqual(messageLayer.receivedMessages[1].data[6], 22)
        self.assertEqual(messageLayer.receivedMessages[1].data[7], 23)
        self.assertEqual(messageLayer.receivedMessages[1].data[8], 30)
        self.assertEqual(messageLayer.receivedMessages[1].data[9], 31)
        self.assertEqual(messageLayer.receivedMessages[1].data[10], 32)
        self.assertEqual(messageLayer.receivedMessages[1].data[11], 33)
        canPhysicalLayer.physicalLayerDown()

    def testZeroLengthDatagram(self):
        # TODO: ?? canPhysicalLayer = PhyMockLayer()
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        message = Message(MTI.Datagram, getLocalNodeID(),
                          getLocalNodeID())

        canLink.sendMessage(message)

        self.assertEqual(len(canPhysicalLayer._send_frames), 1)
        self.assertEqual(str(canPhysicalLayer._send_frames[0]),
                         "CanFrame header: 0x1A000000 []")
        canPhysicalLayer.physicalLayerDown()

    def testOneFrameDatagram(self):
        # TODO: ? canPhysicalLayer = PhyMockLayer()
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)
        # tries = 0
        # state = None
        # while True:
        #     frame = canPhysicalLayer.pollFrame()
        #     canPhysicalLayer.sendAll(None)
        #     state = canLink.pollState()
        #     if state == CanLink.State.Permitted:
        #         break
        #     tries += 1
        #     if tries > 1000:
        #         raise NotImplementedError(
        #             "CanLink couldn't raise network using mock physical layer."
        #             " State is {}".format(state))

        message = Message(MTI.Datagram, getLocalNodeID(),
                          getLocalNodeID(),
                          bytearray([1, 2, 3, 4, 5, 6, 7, 8]))

        canLink.sendMessage(message)

        self.assertEqual(len(canPhysicalLayer._send_frames), 1)
        self.assertEqual(
            str(canPhysicalLayer._send_frames[0]),
            "CanFrame header: 0x1A000000 [1, 2, 3, 4, 5, 6, 7, 8]"
        )
        canPhysicalLayer.physicalLayerDown()

    def testTwoFrameDatagram(self):
        # TODO: ? canPhysicalLayer = PhyMockLayer()
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        message = Message(MTI.Datagram, getLocalNodeID(),
                          getLocalNodeID(),
                          bytearray([1, 2, 3, 4, 5, 6, 7, 8,
                                     9, 10, 11, 12, 13, 14, 15, 16]))

        canLink.sendMessage(message)

        self.assertEqual(len(canPhysicalLayer._send_frames), 2)
        self.assertEqual(
            str(canPhysicalLayer._send_frames[0]),
            "CanFrame header: 0x1B000000 [1, 2, 3, 4, 5, 6, 7, 8]"
        )
        self.assertEqual(
            str(canPhysicalLayer._send_frames[1]),
            "CanFrame header: 0x1D000000 [9, 10, 11, 12, 13, 14, 15, 16]"
        )
        canPhysicalLayer.physicalLayerDown()

    def testThreeFrameDatagram(self):
        # FIXME: Why was testThreeFrameDatagram named same? What should it be?
        # TODO: ? canPhysicalLayer = PhyMockLayer()
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        canPhysicalLayer.physicalLayerUp()
        canLink.waitForReady(self.device)

        message = Message(MTI.Datagram, getLocalNodeID(),
                          getLocalNodeID(),
                          bytearray([1, 2, 3, 4, 5, 6, 7, 8,
                                     9, 10, 11, 12, 13, 14, 15, 16,
                                     17, 18, 19]))

        canLink.sendMessage(message)

        self.assertEqual(len(canPhysicalLayer._send_frames), 3)
        self.assertEqual(
            str(canPhysicalLayer._send_frames[0]),
            "CanFrame header: 0x1B000000 [1, 2, 3, 4, 5, 6, 7, 8]"
        )
        self.assertEqual(
            str(canPhysicalLayer._send_frames[1]),
            "CanFrame header: 0x1C000000 [9, 10, 11, 12, 13, 14, 15, 16]"
        )
        self.assertEqual(str(canPhysicalLayer._send_frames[2]),
                         "CanFrame header: 0x1D000000 [17, 18, 19]")
        canPhysicalLayer.physicalLayerDown()

    # MARK: - Test Remote Node Alias Tracking
    def testAmdAmrSequence(self):
        canPhysicalLayer = CanPhysicalLayerSimulation()
        canLink = CanLinkLayerSimulation(canPhysicalLayer, getLocalNodeID())
        ourAlias = canLink._localAlias  # 576 with NodeID(0x05_01_01_01_03_01)

        canPhysicalLayer.fireFrameReceived(CanFrame(0x0701, ourAlias+1))
        # ^ AMD from some other alias

        self.assertEqual(len(canLink.aliasToNodeID), 1)
        self.assertEqual(len(canLink.nodeIdToAlias), 1)

        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        # ^ nothing back down to CAN

        canPhysicalLayer.fireFrameReceived(CanFrame(0x0703, ourAlias+1))
        # ^ AMR from some other alias

        self.assertEqual(len(canLink.aliasToNodeID), 0)
        self.assertEqual(len(canLink.nodeIdToAlias), 0)

        self.assertEqual(len(canPhysicalLayer.sentFrames), 0)
        # ^ nothing back down to CAN
        canPhysicalLayer.physicalLayerDown()

    # MARK: - Data size handling
    def testSegmentAddressedDataArray(self):
        physicalLayer = PhyMockLayer()
        canLink = CanLinkLayerSimulation(physicalLayer, getLocalNodeID())

        # no data
        self.assertEqual(
            canLink.segmentAddressedDataArray((0x123), bytearray()),
            [bytearray([0x1,0x23])])  # noqa: E231

        # short data
        self.assertEqual(
            canLink.segmentAddressedDataArray((0x123), bytearray([0x1, 0x2])),
            [bytearray([0x1,0x23, 0x01, 0x02])])  # noqa: E231

        # full first frame
        self.assertEqual(
            canLink.segmentAddressedDataArray(
                (0x123),
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6])),
            [bytearray([0x1,0x23, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6])])  # noqa: E231,E501

        # two frames needed
        self.assertEqual(
            canLink.segmentAddressedDataArray(
                (0x123),
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7])),
            [bytearray([0x11,0x23, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6]),  # noqa:E231
             bytearray([0x21,0x23, 0x7])])  # noqa:E231,E501

        # two full frames needed
        self.assertEqual(
            canLink.segmentAddressedDataArray(
                (0x123),
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC])),  # noqa: E501
            [bytearray([0x11,0x23, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6]),  # noqa:E231
             bytearray([0x21,0x23, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC])])  # noqa: E231,E501

        # three frames needed
        self.assertEqual(
            canLink.segmentAddressedDataArray(
                (0x123),
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE])),  # noqa: E501
            [bytearray([0x11,0x23, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6]),  # noqa:E231
             bytearray([0x31,0x23, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC]),  # noqa:E231
             bytearray([0x21, 0x23, 0xD, 0xE])])  # noqa: E231
        physicalLayer.physicalLayerDown()

    def testSegmentDatagramDataArray(self):
        physicalLayer = PhyMockLayer()
        canLink = CanLinkLayerSimulation(physicalLayer, getLocalNodeID())

        # no data
        self.assertEqual(
            canLink.segmentDatagramDataArray(bytearray()),
            [bytearray()])

        # short data
        self.assertEqual(
            canLink.segmentDatagramDataArray(bytearray([0x1, 0x2])),
            [bytearray([0x01, 0x02])])  # noqa: E501

        # partially full first frame
        self.assertEqual(
            canLink.segmentDatagramDataArray(
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6])),
            [bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6])])  # noqa: E501

        # one full frame needed
        self.assertEqual(
            canLink.segmentDatagramDataArray(
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8])),
            [bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8])])  # noqa: E501

        # two frames needed
        self.assertEqual(
            canLink.segmentDatagramDataArray(
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9])),
            [bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8]),
             bytearray([0x9])])  # noqa: E501

        # two full frames needed
        self.assertEqual(
            canLink.segmentDatagramDataArray(
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF, 0x10])),  # noqa: E501
            [bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8]),
             bytearray([0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF, 0x10])])  # noqa: E501

        # three frames needed
        self.assertEqual(
            canLink.segmentDatagramDataArray(
                bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF, 0x10, 0x11])),  # noqa: E501
            [bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8]),
             bytearray([0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF, 0x10]),
             bytearray([0x11])])  # noqa: E501
        physicalLayer.physicalLayerDown()

    def testEnum(self):
        usedValues = set()
        # ensure values are unique:
        for entry in CanLink.State:
            self.assertNotIn(entry.value, usedValues)
            usedValues.add(entry.value)
            # print('{} = {}'.format(entry.name, entry.value))
            self.assertIsInstance(entry.value, int)


if __name__ == '__main__':
    unittest.main()
    # For debugging a test that was hanging:
    # testCase = TestCanLinkClass()
    # count = 0
    # failedCount = 0
    # exceptions = []
    # errors = []
    # for name in dir(testCase):
    #     if name.startswith("test"):
    #         fn = getattr(testCase, name)
    #         try:
    #             fn()  # Look at def test_* below if tracebacks start here
    #             count += 1
    #         except AssertionError as ex:
    #             # raise ex
    #             error = name + ": " + formatted_ex(ex)
    #             # print(error)
    #             failedCount += 1
    #             exceptions.append(ex)
    #             errors.append(error)
    # # for ex in exceptions:
    # #     print(formatted_ex(ex))
    # for error in errors:
    #     print(error)
    # print("{} test(s) passed.".format(count))
    # if errors:
    #     print("{} test(s) failed.".format(len(errors)))
