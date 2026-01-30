
from logging import getLogger
from typing import Union

from openlcb.physicallayer import PhysicalLayer
from openlcb.portinterface import PortInterface

logger = getLogger(__name__)


class RealtimePhysicalLayer(PhysicalLayer):
    """A realtime physical layer is only for use when there is an
    absence of a link layer (or link layer doesn't enqueue frames) *and*
    the application is not multi-threaded or uses a lock and avoids
    race conditions.
    Otherwise, overlapping port calls (*undefined behavior* at OS level)
    may occur!
    TODO: Add a lock variable and do reads here so all port usage can
    utilize the lock and prevent overlapping use of the port.
    """
    class State:
        Initial = 0
        Disconnected = 1
        Permitted = 2

    DisconnectedState = State.Disconnected

    def __init__(self, socket):
        PhysicalLayer.__init__(self)
        # sock to distinguish from socket module or socket.socket class!
        self.sock = socket

    def sendDataAfter(self, data: Union[bytearray, bytes], verbose=True):
        """Send data (immediately, since realtime subclass).

        Args:
            data (Union[bytearray, bytes, CanFrame]): data to send.
            verbose (bool, optional): verbose is only for Realtime
                subclass (since data is sent immediately), otherwise set
                verbose on sendAll. Defaults to False.
        """
        # if isinstance(data, list):
        #     raise TypeError(
        #         "Got {}({}) but expected str"
        #         .format(type(data).__name__, data)
        #     )
        assert isinstance(data, (bytes, bytearray))
        if verbose:
            print("- SENT data (realtime): {}".format(data.strip()))
        self.sock.send(data)
        self.onFrameSent(data)

    def sendFrameAfter(self, frame, verbose=False):
        """Send frame (immediately, since realtime subclass).

        Args:
            data (Union[bytearray, bytes, CanFrame]): data to send.
            verbose (bool, optional): verbose is only for Realtime
                subclass (since data is sent immediately), otherwise set
                verbose on sendAll. Defaults to False.
        """
        if hasattr(self, 'encodeFrameAsData'):
            data = self.encodeFrameAsData(frame)
        else:
            assert isinstance(frame, (bytes, bytearray, str)), \
                "Use a FrameEncoder implementation if not using bytes/str"
            if isinstance(frame, str):
                data = frame.encode("utf-8")
            else:
                data = frame
        # if isinstance(data, list):
        #     raise TypeError(
        #         "Got {}({}) but expected str"
        #         .format(type(data).__name__, data)
        #     )
        if verbose:
            print("- SENT frame (realtime): {}".format(frame))
        # send and fireFrameReceived would usually occur after
        #   frame from _send_frames.popleft is sent,
        #   but we do all this here in the Realtime subclass:
        self.sock.send(data)
        self.onFrameSent(data)
        if hasattr(frame, 'afterSendState') and frame.afterSendState:  # type: ignore # noqa: E501
            # Use hasattr since only applicable to subclasses that use
            #   CanFrame.
            self.fireFrameReceived(frame)  # also calls self.onFrameSent(frame)

    def sendAll(self, device: PortInterface, mode="binary",
                verbose=False) -> int:
        """sendAll is only a stub in the case of realtime subclasses.
        Instead of popping frames it performs a check to ensure the
        queue is not used (since queue should only be used for typical
        subclasses which are queued).
        """
        if len(self._send_frames) > 0:
            raise AssertionError("Realtime subclasses should not use a queue!")
        logger.debug("sendAll ran (realtime subclass, so nothing to do)")
        return 0

    def registerFrameReceivedListener(self, listener):
        """Register a new frame received listener
        (optional since LinkLayer subclass constructor sets
        self.onFrameReceived to its handler).

        Args:
            listener (Callable): A method that accepts decoded frame
                objects from the network.
        """
        logger.warning(
            "registerFrameReceivedListener skipped"
            " (That is a link-layer issue, but you are using"
            " a Raw physical layer subclass).")
