from typing import Union
from openlcb.rawphysicallayer import RawPhysicalLayer
from openlcb.realtimephysicallayer import RealtimePhysicalLayer


class RealtimeRawPhysicalLayer(RealtimePhysicalLayer, RawPhysicalLayer):
    """A realtime physical layer is only for use when there is an
    absence of a link layer (or link layer doesn't enqueue frames) *and*
    the application is not multi-threaded or uses a lock and avoids
    race conditions.
    Otherwise, overlapping port calls (*undefined behavior* at OS level)
    may occur!
    See RealtimePhysicalLayer for more information.
    """
    def sendFrameAfter(self, frame, verbose=False):
        self._sendDataAfter(frame, verbose=verbose)
        self.onFrameSent(frame)

    def sendDataAfter(self, data: Union[bytearray, bytes], verbose=False):
        self._sendDataAfter(data, verbose=verbose)
        self.onFrameSent(data)

    def _sendDataAfter(self, data: Union[bytearray, bytes], verbose=False):
        # ^ data for sendDataAfter,
        #   For frame see sendFrameAfter.
        # verbose is only for Realtime subclass (since data is sent
        # immediately), otherwise set verbose on sendAll.
        # if isinstance(data, list):
        #     raise TypeError(
        #         "Got {}({}) but expected str"
        #         .format(type(data).__name__, data)
        #     )
        if isinstance(data, str):
            data = data.encode("utf-8")
        assert isinstance(data, (bytes, bytearray))
        if verbose:
            print("- SENT data (realtime raw): {}".format(data.strip()))
        self.sock.send(data)
