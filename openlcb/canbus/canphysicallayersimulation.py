'''
Simulated CanPhysicalLayer to record frames requested to be sent.
'''

from openlcb.canbus.canphysicallayer import CanPhysicalLayer


class CanPhysicalLayerSimulation(CanPhysicalLayer):

    def __init__(self):
        self.receivedPackets = []
        CanPhysicalLayer.__init__(self)
        self.onQueuedFrame = self._onQueuedFrame

    def _onQueuedFrame(self, frame):
        raise AttributeError(
            "This should not be used for simulation"
            "--Make sendFrameAfter realtime instead.")

    def captureFrame(self, frame):
        self.receivedPackets.append(frame)
        return "CanPhysicalLayerSimulation"

    def sendFrameAfter(self, frame):
        return self.captureFrame(frame)  # pretend it was sent
        #   (normally only onQueuedFrame would be called here,
        #   and would be encoded to packet str/bytes/bytearray
        #   and sent to socket later by the application's socket code,
        #   which would then call onSentFrame which is set
        #   to the LinkLayer subclass' handleSentFrame)
