import unittest

from openlcb.linklayer import LinkLayer

from openlcb.mti import MTI
from openlcb.message import Message
from openlcb.nodeid import NodeID
from openlcb.physicallayer import PhysicalLayer


class MockPhysicalLayer(PhysicalLayer):
    pass


class TestLinkLayerClass(unittest.TestCase):

    # test function marks that the listeners were fired
    received = False

    def receiveListener(self, msg):
        self.received = True

    def testReceipt(self):
        self.received = False
        msg = Message(MTI.Initialization_Complete, NodeID(12), NodeID(21))
        receiver = self.receiveListener
        layer = LinkLayer(
            MockPhysicalLayer(),
            NodeID(100)
        )
        layer.registerMessageReceivedListener(receiver)

        layer.fireMessageReceived(msg)

        self.assertTrue(self.received)

    def testEnum(self):
        usedValues = set()
        # ensure values are unique:
        for entry in LinkLayer.State:
            self.assertNotIn(entry.value, usedValues)
            usedValues.add(entry.value)
            # print('{} = {}'.format(entry.name, entry.value))


if __name__ == '__main__':
    unittest.main()
