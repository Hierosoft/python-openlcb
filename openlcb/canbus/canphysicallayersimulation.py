'''
Simulated CanPhysicalLayer to record frames requested to be sent.
'''

from typing import List, Union
from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.frameencoder import FrameEncoder


class CanPhysicalLayerSimulation(CanPhysicalLayer, FrameEncoder):

    """Simulation CanPhysicalLayer and FrameEncoder implementation
    Attributes:
        received_chunks (list[bytearray]): Reserved for future use.
    """
    def __init__(self):
        self.sentFrames: List[CanFrame] = []
        # ^ formerly receivedFrames but was appended in self.sendCanFrame!

        CanPhysicalLayer.__init__(self)
        self.onQueuedFrame = self._onQueuedFrame
        self.received_chunks = []

    def _onQueuedFrame(self, frame: CanFrame):
        raise AttributeError("Not implemented for simulation")

    def handleData(self, data: Union[bytes, bytearray], verbose=False) -> int:
        # Do not parse, since simulation. Just collect for later analysis
        self.received_chunks.append(data)
        frameCount = 1  # assumed for simulation
        return frameCount

    def encodeFrameAsString(self, frame: CanFrame):
        return "(no encoding, only simulating CanPhysicalLayer superclass)"

    def encodeFrameAsData(self, frame: CanFrame):
        return self.encodeFrameAsString(frame).encode("utf-8")

    def sendFrameAfter(self, frame: CanFrame):
        frame.encoder = self
        # NOTE: Can't actually do afterSendState here, because
        #   _enqueueCIDSequence sets state to
        #   CanLink.State.WaitingForSendCIDSequence
        #   *after* calling this (so we must use afterSendState
        #   later!)
        self._send_frames.append(frame)

    def sendAll(self, device, mode="binary", verbose=False) -> int:
        if self.linkLayer:
            self.linkLayer.pollState()  # Advance delayed state(s) if necessary
            #  (done first since may enqueue frames).
        count = 0
        try:
            while True:
                frame = self._send_frames.popleft()
                # ^ exits loop with IndexError when done.
                # (otherwise use pollFrame() and break if None)
                if self.linkLayer:
                    if self.linkLayer.isCanceled(frame):
                        if verbose:
                            print("- Skipped (probably dup alias CID frame).")
                        continue
                # data = self.encodeFrameAsData(frame)
                # device.send(data)  # commented since simulation
                self.onFrameSent(frame)
                self.sentFrames.append(frame)
                count += 1
        except IndexError:
            # no more frames (no problem)
            pass
        return count
