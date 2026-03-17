import unittest

from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.canbus.canframe import CanFrame


class TestCanPhysicalLayerClass(unittest.TestCase):

    # test function marks that the listeners were fired
    received = False

    def __init__(self, *args):
        unittest.TestCase.__init__(self, *args)
        self.layer = None
        self._sentFramesCount = 0

    def receiveListener(self, frame: CanFrame):
        self.received = True

    def handleFrameReceived(self, frame: CanFrame):
        pass

    def handleFrameSent(self, frame: CanFrame):
        self._sentFramesCount += 1
        if self.layer:
            self.layer._sentFramesCount += 1

    def testReceipt(self):
        self.received = False
        frame = CanFrame(0x000, bytearray())
        receiver = self.receiveListener
        layer = CanPhysicalLayer()
        self.layer = layer
        layer.onFrameReceived = self.handleFrameReceived
        layer.onFrameSent = self.handleFrameSent
        layer.registerFrameReceivedListener(receiver)

        layer.fireFrameReceived(frame)

        self.assertTrue(self.received)


if __name__ == '__main__':
    unittest.main()
