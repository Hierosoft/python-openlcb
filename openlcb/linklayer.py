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
from typing import Any, Callable, Dict, List, Set, Union

from openlcb import emit_cast
from openlcb.message import Message
from openlcb.nodeid import NodeID
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
        assert isinstance(physicalLayer, PhysicalLayer), \
            f"Expected PhysicalLayer/subclass, got a(n) {type(physicalLayer)}"
        # ^ allows any subclass
        # subclass should check type of localNodeID technically
        self.localNodeID = localNodeID
        self._messageReceivedListeners = []  # type: List[Callable[[Message], None]]  # noqa: E501
        self._messageSentListeners = []  # type: List[Callable[[Message], None]]  # noqa: E501
        self._nodeMappedListeners = []  # type: List[Callable[[NodeID], None]]
        self._unmappedNodeQueues = {}  # type: Dict[NodeID, List[Message]]
        self._state = None  # LinkLayer.State.Undefined
        self._generatedNodeIDs = {}
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
        self.registerNodeMappedListener(self._onNodeMapped)

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

    def blockedReason(self, frame) -> Union[str, None]:
        return None

    def handleFrameReceived(self, frame: Any):
        logger.warning(
            "{} abstract handleFrameReceived called (expected implementation)"
            .format(type(self).__name__))

    def pollState(self) -> Any:
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

    def getState(self) -> Any:
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

    def isGeneratedNodeID(self, nodeID: NodeID):
        assert isinstance(nodeID, NodeID)
        if nodeID == NodeID(0):
            return True
        return nodeID in self._generatedNodeIDs

    def _generateNodeID(self, alias: int) -> NodeID:
        """Generate a sequential alias for internal use only
        (such as sending messages that don't require a destination).
        Use generate_node_id instead for real NodeID for local node(s).
        """
        assert isinstance(alias, int)
        nodeID = NodeID(self.nextInternallyAssignedNodeID)
        # NOTE: Not a real NodeID, so don't use releaseDelayedIDs!
        self.nextInternallyAssignedNodeID += 1
        self._markPairAsGenerated(nodeID, alias)
        return nodeID

    def _markPairAsGenerated(self, nodeID: NodeID, alias: int):
        assert isinstance(nodeID, NodeID)
        assert isinstance(alias, int)
        self._generatedNodeIDs[nodeID] = alias

    def _onStateChanged(self, oldState, newState):
        raise NotImplementedError(
            "[LinkLayer] abstract _onStateChanged not implemented")

    def _unmarkGeneratedID(self, sourceID: NodeID):
        assert isinstance(sourceID, NodeID)
        try:
            self._generatedNodeIDs.pop(sourceID)
        except KeyError:
            pass  # ok, nothing to unmark

    def _unmarkGeneratedIDOfAlias(self, alias: int):
        assert isinstance(alias, int)
        keys = set()
        for k, v in self._generatedNodeIDs.items():
            if v == alias:
                keys.add(k)
        for k in keys:
            self._unmarkGeneratedID(k)

    def sendMessage(self, msg: Message, verbose=False) -> bool:
        '''This is the basic abstract interface
        '''
        return False

    def _onNodeMapped(self, nodeID: NodeID):
        self._releaseMessages(nodeID)

    def _releaseMessages(self, nodeID: NodeID):
        messages = None
        try:
            # Use pop to avoid concurrent mutation:
            messages = self._unmappedNodeQueues.pop(nodeID)
        except KeyError:
            pass  # Ignore: No delayed messages for this nodeID
        if messages:
            for message in messages:
                if not self.sendMessage(message):
                    logger.warning(f"Node mapped, then unmapped: {nodeID}")

    def _releaseMessagesIfMapped(self):
        """Implement in subclass"""
        pass

    def hasDelayedMessage(self, message: Message):
        destination = message.destination
        if destination is None:
            return False
        if destination not in self._unmappedNodeQueues:
            return False
        for tryMessage in self._unmappedNodeQueues[destination]:
            if tryMessage.mti == message.mti:
                return True
        return False

    def delayMessage(self, message: Message):
        destination = message.destination
        assert destination is not None, \
            "python-openlcb should not delay a global message"
        if destination not in self._unmappedNodeQueues:
            self._unmappedNodeQueues[destination] = []
        # if message in self._unmappedNodeQueues[destination]:
        if self.hasDelayedMessage(message):
            logger.warning(
                f"Already waiting for {destination} for {message.mti}")
            return
        self._unmappedNodeQueues[destination].append(message)

    def _fireNodesMapped(self, ids: Union[Set[NodeID], List[NodeID]]):
        # Disabled for now: since feature code (application) should use
        #   fewer assumptions (register CanLink first so it can map
        #   aliases before feature code tries to reply) instead.
        if isinstance(ids, list):
            ids = set(ids)  # Make unique.
        assert isinstance(ids, set)
        for releaseID in ids:
            assert isinstance(releaseID, NodeID)
            # Send *after* mapped, in case using a realtime PhysicalLayer
            self.fireNodeMapped(releaseID)

    def registerMessageReceivedListener(self, listener):
        if listener in self._messageReceivedListeners:
            logger.warning("Method already registered--lowering its priority.")
            self._messageReceivedListeners.remove(listener)
        self._messageReceivedListeners.append(listener)

    def registerMessageSentListener(self, listener):
        self._messageSentListeners.append(listener)

    def registerNodeMappedListener(self, listener):
        self._nodeMappedListeners.append(listener)

    def fireMessageReceived(self, msg: Message):
        """Fire *Message received* listeners."""
        for listener in self._messageReceivedListeners:
            listener(msg)

    def fireMessageSent(self, msg: Message):
        """Fire *Message received* listeners."""
        for listener in self._messageSentListeners:
            listener(msg)

    def fireNodeMapped(self, nodeID: NodeID):
        """Fire *Message received* listeners.
        Should *only* be fired when receiving an
        *addressed* message:
        - A *message*, since This should also not be called until
          we have the other node mapped,
          otherwise listeners cannot send messages
          to it.
        - An *addressed* message since otherwise typically the other
          node does not have *this* node mapped (such as when it is
          sending a global message, typically when it is sending
          Verify_NodeID_Number_Global).
        """
        print(f"[LinkLayer] fireNodeMapped({nodeID})")
        for listener in self._nodeMappedListeners:
            # Always calls at least self._onNodeMapped
            listener(nodeID)
