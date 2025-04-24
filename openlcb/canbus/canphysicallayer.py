'''
Generalize a CAN physical layer, real or simulated.

This is a class because it represents a single physical connection to a layout
and is subclassed.
'''
import sys
from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.controlframe import ControlFrame
from openlcb.physicallayer import PhysicalLayer


class CanPhysicalLayer(PhysicalLayer):
    """Can implementation of PhysicalLayer, still partly abstract
    (No encodeFrameAsString, since this binary layer may be wrapped by
    the higher layer such as the text-based CanPhysicalLayerGridConnect)

    Args:
        waitForSendCallback (callable): This *must* be a thread-blocking
            callback so that the caller knows the timeline for when to
            expect a response.
    """

    def __init__(self, waitForSendCallback):
        self.listeners = []
        if not waitForSendCallback:
            raise ValueError("Provide a blocking waitForSend function")
        sys.stderr.write("Validating waitForSendCallback...")
        sys.stderr.flush()
        waitForSendCallback()  # asserts that the callback works.
        #  If it raises an error or halts the program, the value is bad
        #    (The application code is incorrect, so prevent startup).
        print("OK", file=sys.stderr)
        self.waitForSend = waitForSendCallback

    def sendCanFrame(self, frame: CanFrame):
        '''basic abstract interface'''
        raise NotImplementedError(
            "Each subclass must implement this, and set"
            "  frame.encoder = self")

    def encode(self, frame) -> str:
        '''abstract interface (encode frame to string)'''
        raise NotImplementedError("Each subclass must implement this.")

    def registerFrameReceivedListener(self, listener):
        self.listeners.append(listener)

    def fireListeners(self, frame):
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
