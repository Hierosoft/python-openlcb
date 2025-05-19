
from enum import Enum
from logging import getLogger
from typing import Union

from openlcb.physicallayer import PhysicalLayer

logger = getLogger(__name__)


class RealtimePhysicalLayer(PhysicalLayer):

    class State:
        Initial = 0
        Disconnected = 1
        Permitted = 2

    DisconnectedState = State.Disconnected

    def __init__(self, socket):
        # sock to distinguish from socket module or socket.socket class!
        self.sock = socket

    def sendDataAfter(self, data: Union[bytearray, bytes]):
        # if isinstance(data, list):
        #     raise TypeError(
        #         "Got {}({}) but expected str"
        #         .format(type(data).__name__, data)
        #     )
        assert isinstance(data, (bytes, bytearray))
        print("      SR: {}".format(data))
        self.sock.send(data)

    def sendFrameAfter(self, frame):
        # if isinstance(data, list):
        #     raise TypeError(
        #         "Got {}({}) but expected str"
        #         .format(type(data).__name__, data)
        #     )
        print("      SR: {}".format(frame.encode()))
        # send and fireFrameReceived would usually occur after
        #   frame from _send_frames.popleft is sent,
        #   but we do all this here in the Realtime subclass:
        self.sock.send(frame.encode())
        # TODO: finish onFrameSent
        if frame.afterSendState:
            self.fireFrameReceived(frame)  # also calls self.onFrameSent(frame)

    def registerFrameReceivedListener(self, listener):
        """Register a new frame received listener
        (optional since LinkLayer subclass constructor sets
        self.onFrameReceived to its handler).

        Args:
            listener (callable): A method that accepts decoded frame
                objects from the network.
        """
        logger.warning(
            "registerFrameReceivedListener skipped"
            " (That is a link-layer issue, but you are using"
            " a Raw physical layer subclass).")
