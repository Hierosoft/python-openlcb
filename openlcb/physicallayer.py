'''
Generalize access to the physical layer;.

Parent of `CanPhysicalLayer`

To change implementation of popFrames or other methods without
NotImplementedError, call super() normally, as such methods are used
similarly to how a template or generic class would be used in a strictly
OOP language. However, re-implementation is typically not necessary
since Python allows any type to be used for the elements of _send_frames.

We implement logic here not only because it is convenient but also
because _send_frames (and the subclass being a state machine with states
specific to the physical layer type) is a the paradigm used by this
openlcb stack (Python module) as a whole (connection and flow determined
by application's port code, state determined by the openlcb stack). This
allows single-threaded use or thread-safe multi-threaded use like the C
version of openlcb in OpenMRN. Issue #62 comments discuss this paradigm
(among other necessary structure beyond that) as central to stability
and predictable use in applications.
-Poikilos
'''

from collections import deque
from logging import getLogger
from typing import Union

logger = getLogger(__name__)


class PhysicalLayer:
    """Generalize access to the physical layer;.

    Parent of `CanPhysicalLayer`

    The PhysicalLayer class enforces restrictions on how many node
    instances can be created on a single machine.

    If you need more than one node (such as to create virtual nodes),
    call:
    ```
    PhysicalLayer.moreThanOneNodeOnMyMachine(count)
    ```
    with `count` higher than 1.

    If you did that and this warning still appears, set:
    ```
    PhysicalLayer.allowDynamicNodes(true)
    ```
    ONLY if you are really sure you require the number of nodes *on this
    machine* (*not* including remote network nodes) to be more or less
    at different times (and stack memory allocations don't need to be
    manually optimized on the target platform).
    """

    def __init__(self):
        self._send_frames = deque()

    # def sendDataAfter(self, data):
    #     assert isinstance(data, (bytes, bytearray))
    #     self._send_frames.append(data)

    def pollFrame(self):
        """Check if there is another frame queued and get it.
        Subclass should call PhysicalLayer.pollFrame (or
        super().pollFrame) then enforce type, only if not None, before
        returning the return of this superclass method.

        Returns:
            Any: next frame in FIFO buffer (_send_frames). In a
                CanPhysicalLayer or subclass of that, type is CanFrame.
                In a raw implementation it is either bytes or bytearray.
        """
        try:
            data = self._send_frames.popleft()
            return data
        except IndexError:  # "popleft from an empty deque"
            pass
        return None

    def sendFrameAfter(self, frame):
        """In subclass, enforce type and set frame.encoder to self
        (which should inherit from both PhysicalLayer and FrameEncoder)
        before calling this.

        This only adds to a queue, so use pollFrame() in your socket
        code so application manages flow, physicalLayer manages data,
        and link manages state.
        """
        self._send_frames.append(frame)  # append: queue-like if using popleft

    def onSentFrame(self, frame):
        raise NotImplementedError(
            "onSentFrame must be set (monkeypatched)"
            " to use the LinkLayer subclass' one"
            " so state can be updated if necessary.")

    def registerFrameReceivedListener(self, listener):
        """abstract method"""
        # raise NotImplementedError("Each subclass must implement this.")
        logger.warning(
            "{} abstract registerFrameReceivedListener called"
            " (expected implementation)"
            .format(type(self).__name__))

    def physicalLayerUp(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def physicalLayerRestart(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def physicalLayerDown(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def encodeFrameAsString(self, frame) -> str:
        raise NotImplementedError("Each subclass must implement this.")
