from logging import getLogger

from openlcb.canbus.canlink import CanLink


logger = getLogger(__name__)


class CanLinkLayerSimulation(CanLink):

    def sendAll(self, _, mode="binary", verbose=True):
        """Simulated sendAll
        The simulation has no real communication, so no device argument
        is necessary. See CanLink for a real implementation.

        Args:
            verbose (bool, optional): If True, print the packet (not
                recommended in the case of numerous sequential memory
                read requests such as when reading CDI/FDI).
        """

        self.pollState()  # run first since may enqueue frame(s)
        while True:
            # self.physicalLayer must be set by canLink constructor by
            #   passing a physicalLayer to it.
            frame = self.physicalLayer.pollFrame()
            if not frame:
                break
            string = frame.encodeAsString()
            # device.sendString(string)  # commented since simulation
            if verbose:
                print("      SENT (simulated socket) packet: "+string.strip())
            self.physicalLayer.onFrameSent(frame)
