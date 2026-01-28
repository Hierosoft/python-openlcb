'''
based on LinkLayer.swift

Created by Bob Jacobsen on 6/1/22.

Handles link-layer formatting and unformatting for a particular kind of
communications link.

Nodes are handled in one of two ways:
- "Own Node" - this is a node resident within the program
- "Remote Node" - this is a node outside the program

This is a class, not a struct, because an instance corresponds to an external
object (the actual link implementation), so there's no semantic meaning to
making multiple copies of a single object.
'''


from enum import Enum
from logging import getLogger

from openlcb import emit_cast
from openlcb.message import Message
from openlcb.physicallayer import PhysicalLayer

logger = getLogger(__name__)


class LinkLayer:
    """Abstract Link Layer interface

    Attributes:
        _messageReceivedListeners (list[Callback]): local list of
            listener callbacks. See subclass for default listener and
            more specific callbacks called from there.
        _state: The state (a.k.a. "runlevel" in linux terms)
            of the network link. This may be moved to an overall
            stack handler such as OpenLCBNetwork.
        State (class(Enum)): values for _state. Implement all necessary
            states in subclass to handle connection phases etc.
    """

    class State(Enum):
        Undefined = 0  # subclass constructor didn't run--Implement State there

    DisconnectedState = State.Undefined  # change in subclass! Only for tests!
    #   (enforced using type(self).__name__ != "LinkLayer" checks in methods)

    def __init__(self, physicalLayer: PhysicalLayer, localNodeID):
        assert isinstance(physicalLayer, PhysicalLayer)  # allows any subclass
        # subclass should check type of localNodeID technically
        self.localNodeID = localNodeID
        self._messageReceivedListeners = []
        self._state = None  # LinkLayer.State.Undefined
        # region moved from CanLink linkPhysicalLayer
        self.physicalLayer = physicalLayer  # formerly self.link = cpl
        # if physicalLayer is not None:
        # listener = self.handleFrameReceived  # try to prevent
        # "new bound method" Python behavior in subclass from making "is"
        #   operator not work as expected in registerFrameReceivedListener.
        physicalLayer.onFrameReceived = self.handleFrameReceived
        physicalLayer.onFrameSent = self.handleFrameSent
        physicalLayer.linkLayer = self
        # # ^ enforce queue paradigm (See use in PhysicalLayer subclass)
        # physicalLayer.registerFrameReceivedListener(listener)
        # ^ Doesn't work with "is" operator still! So just use
        #   physicalLayer.onFrameReceived in fireFrameReceived in PhysicalLayer
        # else:
        #     print("Using {} without"
        #           " registerFrameReceivedListener(self.handleFrameReceived)"
        #           " on physicalLayer, since no physicalLayer specified."
        #           .format())
        # endregion moved from CanLink linkPhysicalLayer
        if type(self).__name__ != "LinkLayer":
            # ^ Use name, since isinstance returns True for any subclass.
            if isinstance(type(self).DisconnectedState, LinkLayer.State):
                raise NotImplementedError(
                    " LinkLayer.State and LinkLayer.DisconnectedState"
                    " are only for testing. Redefine them in each subclass"
                    " (got LinkLayer.State({}) for {}.DisconnectedState)"
                    .format(emit_cast(type(self).DisconnectedState),
                            type(self).__name__))

    def isCanceled(self, frame) -> bool:
        """Subclass should implement this
        if there is a cancelling mechanism (In the case of CanLink,
        cancel frames from a previous LCC alias allocation where an
        alias collision reply was received).
        """
        return False

    def isAllowed(self, frame) -> bool:
        """Subclass should implement this
        if there is a cancelling mechanism (In the case of CanLink,
        cancel frames from a previous LCC alias allocation where an
        alias collision reply was received).
        """
        if self.isCanceled(frame):
            return False
        return True

    def blockedReason(self, frame) -> str:
        return None

    def handleFrameReceived(self, frame):
        logger.warning(
            "{} abstract handleFrameReceived called (expected implementation)"
            .format(type(self).__name__))

    def pollState(self):
        print("Abstract pollState ran (implement in subclass)."
              "  Continuing anyway (assuming non-CAN or test subclass).")

    def handleFrameSent(self, frame):
        """Update state based on the frame having been sent."""
        if self.physicalLayer:
            self.physicalLayer._sentFramesCount += 1
        if (hasattr(frame, 'afterSendState')
                and (frame.afterSendState is not None)):
            self.setState(frame.afterSendState)  # may change again
            #   since setState calls pollState via _onStateChanged.

    def getState(self):
        return self._state

    def setState(self, state):
        """Reusable LinkLayer setState
        (enforce type of state in _onStateChanged implementation in subclass)
        """
        # Run _onStateChange *even if state is same* as old state, to
        #   processes state as soon as possible (Let it catch up in case
        #   _state was set manually etc).
        oldState = self._state

        newState = state  # keep a copy for _onStateChanged, for thread safety
        #   (ensure value doesn't change between two lines below)
        self._state = newState
        if type(self).__name__ != "LinkLayer":
            # ^ Use name, since isinstance returns True for any subclass.
            if isinstance(state, LinkLayer.State):
                raise NotImplementedError(
                    " LinkLayer.State and LinkLayer.DisconnectedState"
                    " are only for testing. Redefine them in each subclass.")

        self._onStateChanged(oldState, newState)  # enforce type in subclass

    def _onStateChanged(self, oldState, newState):
        raise NotImplementedError(
            "[LinkLayer] abstract _onStateChanged not implemented")

    def sendMessage(self, msg: Message, verbose=False):
        '''This is the basic abstract interface
        '''

    def registerMessageReceivedListener(self, listener):
        self._messageReceivedListeners.append(listener)

    def fireMessageReceived(self, msg: Message):
        """Fire *Message received* listeners."""
        for listener in self._messageReceivedListeners:
            listener(msg)
