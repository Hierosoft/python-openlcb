'''
Generalize a CAN physical layer, real or simulated.

This is a class because it represents a single physical connection to a layout
and is subclassed.
'''
import sys
from logging import getLogger

from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.controlframe import ControlFrame
from openlcb.physicallayer import PhysicalLayer

logger = getLogger(__name__)


class CanPhysicalLayer(PhysicalLayer):
    """Can implementation of PhysicalLayer, still partly abstract
    (No encodeFrameAsString, since this binary layer may be wrapped by
    the higher layer such as the text-based CanPhysicalLayerGridConnect)
    """

    def __init__(self,):
        PhysicalLayer.__init__(self)
        self.listeners = []

    def sendFrameAfter(self, frame: CanFrame):
        """See sendFrameAfter documentation in PhysicalLayer.
        This implementation behaves the same except requires
        a specific type (CanFrame).
        """
        # formerly sendCan Frame, but now behavior is defined by superclass
        #   (regardless of frame type, it is just added to self._sends)
        assert isinstance(frame, CanFrame)
        PhysicalLayer.sendFrameAfter(self, frame)

    def pollFrame(self) -> CanFrame:  # overloaded for type hinting.
        """Check if there is another frame queued and get it.
        Returns:
            CanFrame: next frame in FIFO buffer (_sends).
        """
        return PhysicalLayer.pollFrame(self)

    def encode(self, frame) -> str:
        '''abstract interface (encode frame to string)'''
        raise NotImplementedError("Each subclass must implement this.")

    def registerFrameReceivedListener(self, listener):
        self.listeners.append(listener)

    def fireListeners(self, frame):
        if not self.listeners:
            logger.warning(
                "No listeners for frame received."
                " CanLink (see LinkLayer superclass constructor)"
                " should at least register its receiveFrame method"
                " with a physical layer implementation.")
        for listener in self.listeners:
            listener(frame)

    def physicalLayerUp(self):
        '''Invoked when the physical link implementation has initially come up
        '''
        # notify link layer
        cf = CanFrame(ControlFrame.LinkUp.value, 0)
        self.fireListeners(cf)

    def physicalLayerRestart(self):
        '''Invoked from OpenlcbNetwork when the physical link implementation
        has come up 2nd or later times
        '''
        # notify link layer
        cf = CanFrame(ControlFrame.LinkRestarted.value, 0)
        self.fireListeners(cf)

    def physicalLayerDown(self):
        '''Invoked from OpenlcbNetwork when the physical link implementation
        has gone down
        '''
        # notify link layer
        cf = CanFrame(ControlFrame.LinkDown.value, 0)
        self.fireListeners(cf)
