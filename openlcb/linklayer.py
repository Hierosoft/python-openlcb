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

from openlcb.physicallayer import PhysicalLayer

logger = getLogger(__name__)


class LinkLayer:
    """Abstract Link Layer interface

    Attributes:
        listeners (list[Callback]): local list of listener callbacks.
            See subclass for default listener and more specific
            callbacks called from there.
        _state: The state (a.k.a. "runlevel" in linux terms)
            of the network link. This may be moved to an overall
            stack handler such as Dispatcher.
        State (class(Enum)): values for _state. Implement in subclass.
            This may be moved to an overall stack handler such as
            Dispatcher.
    """

    class State(Enum):
        Undefined = 1  # subclass constructor did not run (implement states)

    def __init__(self, physicalLayer: PhysicalLayer, localNodeID):
        assert isinstance(physicalLayer, PhysicalLayer)  # allows any subclass
        # subclass should check type of localNodeID technically
        self.localNodeID = localNodeID
        self.listeners = []
        self._state = LinkLayer.State.Undefined
        # region moved from CanLink linkPhysicalLayer
        self.physicalLayer = physicalLayer  # formerly self.link = cpl
        # if physicalLayer is not None:
        physicalLayer.registerFrameReceivedListener(self.receiveListener)
        # else:
        #     print("Using {} without"
        #           " registerFrameReceivedListener(self.receiveListener)"
        #           " on physicalLayer, since no physicalLayer specified."
        #           .format())
        # endregion moved from CanLink linkPhysicalLayer

    def receiveListener(self, frame):
        logger.warning(
            "{} abstract receiveListener called (expected implementation)"
            .format(type(self).__name__))

    def onDisconnect(self):
        """Run this whenever the socket connection is lost
        and override _onStateChanged to handle the change.
        * If you override this, you *must* call
        `LinkLayer.onDisconnect(self)` to trigger _onStateChanged
        if the implementation utilizes getState.
        """
        self._setState(LinkLayer.State.Undefined)

    def getState(self):
        return self._state

    def setState(self, state):
        oldState = self._state
        newState = state  # keep a copy for _onStateChanged, for thread safety
        #   (ensure value doesn't change between two lines below)
        self._state = newState
        self._onStateChanged(oldState, newState)

    def _onStateChanged(self, oldState, newState):
        raise NotImplementedError(
            "[LinkLayer] abstract _onStateChanged not implemented")

    def sendMessage(self, msg):
        '''This is the basic abstract interface
        '''

    def registerMessageReceivedListener(self, listener):
        self.listeners.append(listener)

    def fireListeners(self, msg):
        for listener in self.listeners:
            listener(msg)
