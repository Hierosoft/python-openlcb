import unittest

from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.canbus.canframe import CanFrame


class TestCanPhysicalLayerClass(unittest.TestCase):

    # test function marks that the listeners were fired
    received = False

    def receiveListener(self, frame: CanFrame):
        self.received = True

    def handleReceivedFrame(self, frame: CanFrame):
        pass

    def handleSentFrame(self, frame: CanFrame):
        pass

    def testReceipt(self):
        self.received = False
        frame = CanFrame(0x000, bytearray())
        receiver = self.receiveListener
        layer = CanPhysicalLayer()
        layer.onReceivedFrame = self.handleReceivedFrame
        layer.onSentFrame = self.handleSentFrame
        layer.registerFrameReceivedListener(receiver)

        layer.fireFrameReceived(frame)

        self.assertTrue(self.received)


if __name__ == '__main__':
    unittest.main()
