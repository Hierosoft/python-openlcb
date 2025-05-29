'''
Generalize a CAN physical layer, real or simulated.

This is a class because it represents a single physical connection to a layout
and is subclassed.
'''
from logging import getLogger
from typing import Callable
import warnings

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
        self._frameReceivedListeners: list[Callable[[CanFrame], None]] = []

    def sendFrameAfter(self, frame: CanFrame):
        """Enqueue: *IMPORTANT* Main/other thread may have
        called this. Any other thread sending other than the _listen
        thread is bad, since overlapping calls to socket cause undefined
        behavior, so this just adds to a deque (double ended queue, used
        as FIFO).
        - CanPhysicalLayerGridConnect formerly had canSendCallback
          but now it uses its own frame deque, and the socket code pops
          and sends the frames.
          (formerly canSendCallback was set to a sendToPort function
          which was formerly a direct call to a port which was not
          thread-safe and could be called from anywhere in the
          openlcb stack)
          - Add a generalized LocalEvent queue avoid deep callstack?
            - See issue #62 comment about a local event queue.
              For now, CanFrame is used (improved since issue #62
              was solved by adding more states to CanLink so it
              can have incremental states instead of requiring two-way
              communication [race condition] during a single
              blocking call to defineAndReserveAlias)
        """
        assert isinstance(frame, CanFrame)
        frame.encoder = self
        PhysicalLayer.sendFrameAfter(self, frame)  # calls onQueuedFrame if set

    def pollFrame(self) -> CanFrame:
        frame = super().pollFrame()
        if frame is None:
            return None
        assert isinstance(frame, CanFrame)
        return frame

    def registerFrameReceivedListener(self,
                                      listener: Callable[[CanFrame], None]):
        # ^ 2nd arg to Callable type is the return type.
        assert listener is not None
        warnings.warn(
            "[registerFrameReceivedListener]"
            " You don't really need to listen to packets."
            " Use pollFrame instead, which will collect and decode"
            " packets into frames (this layer communicates to upper layers"
            " using physicalLayer.onFrameReceived set by LinkLayer/subclass"
            " constructor).")
        self._frameReceivedListeners.append(listener)

    def fireFrameReceived(self, frame: CanFrame):
        """Fire *CanFrame received* listeners.
        Monitor each frame that is constructed
        as the application provides handleData raw data from the port.
        - LinkLayer (CanLink in this case) must set onFrameReceived,
          so registerFrameReceivedListener is now optional, and
          a Message handler should usually be used instead.
        """
        # (onFrameReceived was implemented to make it clear by way of
        #   constructor code that the handler is required in order for
        #   the openlcb network stack (This Python module) to
        #   operate--See
        #   <https://github.com/bobjacobsen/python-openlcb/issues/62#issuecomment-2775668681>
        self.onFrameReceived(frame)  # canLink.handleFrameReceived reference
        for listener in self._frameReceivedListeners:
            listener(frame)

    def physicalLayerUp(self):
        '''Invoked when the physical link implementation has initially come up
        '''
        # notify link layer
        cf = CanFrame(ControlFrame.LinkUp.value, 0)
        self.fireFrameReceived(cf)

    def physicalLayerRestart(self):
        '''Invoked from OpenlcbNetwork when the physical link implementation
        has come up 2nd or later times
        '''
        # notify link layer
        cf = CanFrame(ControlFrame.LinkRestarted.value, 0)
        self.fireFrameReceived(cf)

    def physicalLayerDown(self):
        '''Invoked from OpenlcbNetwork when the physical link implementation
        has gone down
        '''
        # notify link layer
        cf = CanFrame(ControlFrame.LinkDown.value, 0)
        self.fireFrameReceived(cf)
