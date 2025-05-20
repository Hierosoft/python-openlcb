'''
Simulated CanPhysicalLayer to record frames requested to be sent.
'''

from typing import List
from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.frameencoder import FrameEncoder


class CanPhysicalLayerSimulation(CanPhysicalLayer, FrameEncoder):

    def __init__(self):
        self.receivedFrames: List[CanFrame] = []
        CanPhysicalLayer.__init__(self)
        self.onQueuedFrame = self._onQueuedFrame

    def _onQueuedFrame(self, frame: CanFrame):
        raise AttributeError("Not implemented for simulation")

    def captureFrame(self, frame: CanFrame):
        self.receivedFrames.append(frame)

    def encodeFrameAsString(self, frame: CanFrame):
        return "(no encoding, only simulating CanPhysicalLayer superclass)"

    def encodeFrameAsData(self, frame: CanFrame):
        return self.encodeFrameAsString(frame).encode("utf-8")

    def sendFrameAfter(self, frame: CanFrame):
        frame.encoder = self
        self.captureFrame(frame)
        # NOTE: Can't actually do afterSendState here, because
        #   _enqueueCIDSequence sets state to
        #   CanLink.State.WaitingForSendCIDSequence
        #   *after* calling this (so we must use afterSendState
        #   later!)
        self._send_frames.append(frame)
