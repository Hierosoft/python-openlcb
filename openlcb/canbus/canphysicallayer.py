'''
Generalize a CAN physical layer, real or simulated.

This is a class because it represents a single physical connection to a layout
and is subclassed.
'''
from logging import getLogger
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
        self.listeners = []

    def onReceivedFrame(self):
        raise NotImplementedError(
            "Your LinkLayer/subclass must set this manually (monkeypatch)"
            " to the CanLink instance's receiveListener method.")

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
        PhysicalLayer.sendFrameAfter(self, frame)

    def pollFrame(self) -> CanFrame:
        frame = super().pollFrame()
        if frame is None:
            return None
        assert isinstance(frame, CanFrame)
        return frame

    def encode(self, frame) -> str:
        '''abstract interface (encode frame to string)'''
        raise NotImplementedError("Each subclass must implement this.")

    def registerFrameReceivedListener(self, listener):
        assert listener is not None
        warnings.warn(
            "You don't really need to listen to packets."
            " Use pollFrame instead, which will collect and decode"
            " packets into frames (this layer communicates to upper layers"
            " using self.onReceivedFrame set in LinkLayer/subclass"
            " constructor).")
        self.listeners.append(listener)

    def fireListeners(self, frame):
        """At least the LinkLayer (CanLink in this case)
        should register one listener."""

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
