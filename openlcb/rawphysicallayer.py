
from logging import getLogger

from openlcb.physicallayer import PhysicalLayer

logger = getLogger(__name__)


class RealtimeRawPhysicalLayer(PhysicalLayer):

    def __init__(self, socket):
        # sock to distinguish from socket module or socket.socket class!
        self.sock = socket

    def sendFrameAfter(self, data):
        # if isinstance(data, list):
        #     raise TypeError(
        #         "Got {}({}) but expected str"
        #         .format(type(data).__name__, data)
        #     )
        print("      SR: {}".format(data))
        self.sock.send(data)

    def registerFrameReceivedListener(self, listener):
        """_summary_

        Args:
            listener (callable): A method that accepts decoded frame
                objects from the network.
        """
        logger.warning("registerFrameReceivedListener skipped (That is a link-layer issue, but you are using a Raw physical layer subclass).")
