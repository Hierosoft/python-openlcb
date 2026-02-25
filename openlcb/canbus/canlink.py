'''
based on CanLink.swift

Created by Bob Jacobsen on 6/1/22.


Handles link-layer formatting and unformatting for CAN-frame links.

Uses a ``CanPhysicalLayer`` implementation at the CanFrame layer.

This implementation handles one static Local Node and a variable number of
Remote Nodes.

- An alias is allocated for the Local Node when the link comes up.

- Aliases are tracked for the Remote Nodes, but not allocated here

Multi-frame addressed messages are accumulated in parallel
'''

from enum import Enum
from logging import getLogger
from timeit import default_timer
from typing import (
    # Iterable,
    List,  # in case list doesn't support `[` in this Python version
    Union,  # in case `|` doesn't support 'type' in this Python version
)

from openlcb import (
    precise_sleep,
    emit_cast,
    formatted_ex,
)
from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.canbus.controlframe import ControlFrame
from openlcb.linklayer import LinkLayer
from openlcb.message import Message
from openlcb.mti import MTI
from openlcb.nodeid import NodeID
from openlcb.physicallayer import PhysicalLayer
from openlcb.portinterface import PortInterface

logger = getLogger(__name__)


class CanLink(LinkLayer):
    """CAN link layer (manage stack's link state).

    Attributes:
        ALIASES_RECEIVED_TIMEOUT (float): (seconds) Section 6.2.1 of CAN
            Frame Transfer - Standard says to wait 200 ms for
            collisions, and if there are no replies, the alias is good
            (nodes are only required to reply if they collide, as per
            section 6.2.5 of CAN Frame Transfer - Standard). If a reply
            has the same alias as self during this time, processCollision
            increments alias and restarts reservation (sets lower state).

    Args:
        localNodeID (NodeID): The node ID of the device itself
            (localhost) running python-openlcb, or a virtual node
            controlled by it. A node ID should be universally unique
            (serialized by device), but each NodeID is mapped to an
            alias that CanLink generates and guarantees is unique within
            the network.
            - Therefore, technically any valid NodeID can be used by
              this openlcb stack as long as it is the same one used to
              construct the CanLink (See getLocalAlias for details), but
              use a unique one within a valid range at:
              <https://registry.openlcb.org/uniqueidranges> or discuss
              reserving your own range there with OpenLCB if your
              application/hardware does not apply to one of those
              ranges.
        physicalLayer (PhysicalLayer): The PhysicalLayer/subclass to
          use for sending frames (enqueue them via sendFrameAfter).
    """

    # MIN_STATE_VALUE & MAX_STATE_VALUE are set statically below the
    #   State class declaration:
    STANDARD_ALIAS_RESPONSE_DELAY = .2
    ALIAS_RESPONSE_DELAY = STANDARD_ALIAS_RESPONSE_DELAY  # See docstring.

    class State(Enum):
        """Used as a linux-like "runlevel"

        Attributes:
            EnqueueAliasAllocationRequest (State): This state triggers
                the first phase of the alias reservation process.
                Normally set by calling defineAndReserveAlias. If
                a collision occurs, processCollision increments the
                alias before calling defineAndReserveAlias.

            WaitingForSendCIDSequence (State): Waiting for send of the last
                CID sequence packet (first phase of reserving an alias).
                - The last frame sets state to WaitForAliases *after*
                  sent by socket (wait for socket code in application or
                  OpenLCBNetwork to notify us, as sendFrameAfter is too
                  soon to be sure our 200ms delay starts after send).
            EnqueueAliasReservation (State): After collision detection fully
                determined to be success, this state triggers
                _enqueueReserveID.
        """
        Initial = 1  # special case of .Inhibited
        #   where init hasn't started.
        Inhibited = 2
        EnqueueAliasAllocationRequest = 3
        # _enqueueCIDSequence sets:
        BusyLocalCIDSequence = 4
        WaitingForSendCIDSequence = 5
        WaitForAliases = 6  # queued via frame
        EnqueueAliasReservation = 7  # called by pollState (see comments there)
        # _enqueueReserveID sets:
        BusyLocalReserveID = 8
        WaitingForSendReserveID = 9
        NotifyAliasReservation = 14  # queued via frame
        # _notifyReservation sets:
        BusyLocalNotifyReservation = 11
        WaitingForLocalNotifyReservation = 12
        RecordAliasReservation = 13  # queued via frame
        # _recordReservation sets:
        BusyLocalMappingAlias = 18
        Permitted = 20  # formerly 3. queued via frame
        # (formerly set at end of _notifyReservation code)

    InitialState = State.Initial
    DisconnectedState = State.Inhibited

    MIN_STATE_VALUE = min(entry.value for entry in State)
    MAX_STATE_VALUE = max(entry.value for entry in State)

    def __init__(self, physicalLayer: PhysicalLayer, localNodeID: NodeID):
        # See class docstring for args
        self.physicalLayer: CanPhysicalLayer = None  # set by super() below
        # ^ typically CanPhysicalLayerGridConnect
        LinkLayer.__init__(self, physicalLayer, localNodeID)
        self._previousLocalAliasSeed = None
        self._waitingForAliasStart = None
        self._localAliasSeed = localNodeID.value
        self._localAlias = self.createAlias12(self._localAliasSeed)
        self.localNodeID = localNodeID
        self._state = CanLink.State.Initial
        self._frameCount = 0
        self._aliasCollisionCount = 0
        self._errorCount = 0
        self._previousFrameCount = None
        self.aliasToNodeID = {}
        self.nodeIdToAlias = {}
        self.accumulator = {}
        self.duplicateAliases = []
        self.nextInternallyAssignedNodeID = 1
        self._state = CanLink.State.Initial
        self._reservation = -1  # incremented on use.

    # This method may never actually be necessary, as
    # sendMessage uses nodeIdToAlias (which has localNodeID
    # *only after* a successful reservation)
    def getLocalAlias(self, minimumState=State.Permitted) -> int:
        """Get the local alias, since it may differ from original
        localNodeID given at construction: It may have been
        reassigned (via incrementAlias48 and createAlias12 in
        processCollision), therefore don't call this until state ==
        State.Permitted that indicates the alias is reserved (after
        definedAndReserveAlias is successful). Before that, the
        stack has no validated alias for sending a Message.

        Raises:
            InterruptedError: When the state is not Permitted that
                indicates that the alias reservation is not complete
                (alias is not reserved, and may not be unique).

        Returns:
            int: The local alias.
        """
        if self._state.value < minimumState.value:
            raise InterruptedError(
                "The alias reservation is not complete (state={}<{})."
                " Make sure defineAliasReservation (physicalLayerUp) isn't"
                " called in a way that blocks the socket receive thread,"
                " and that your application has a Message received listener"
                " registered via registerMessageReceivedListener that"
                " checks for MTI.Link_Layer_Up and MTI.Link_Layer_Down"
                " and inhibits the usage of the openlcb stack if not up"
                " unless you poll for"
                " canlink.getState() == CanLink.State.Permitted in a"
                " non-blocking manner."
                .format(self._state, minimumState)
            )
        return self._localAlias

    # Use pollState instead, which keeps the state machine moving
    # def ready(self):
    #     """Check if state == CanLink.State.Permitted
    #     To find out if ready right away, check for
    #     MTI.Link_Layer_Up and MTI.Link_Layer_Down and use them
    #     to track the state in the application code.
    #     """
    #     assert isinstance(self._state, CanLink.State)
    #     return self._state == CanLink.State.Permitted

    def isCanceled(self, frame: CanFrame) -> bool:
        if frame.reservation is None:
            return False
        return frame.reservation < self._reservation

    def isAllowed(self, frame: CanFrame) -> bool:
        if self.isCanceled(frame):
            return False
        return self.blockedFrameType(frame) is None

    def blockedFrameType(self, frame: CanFrame) -> Union[ControlFrame, None]:
        if self._state == CanLink.State.Permitted:
            # All frame types are allowed in this state.
            return None
        control_frame = CanFrame.decodeControlFrameFormat(frame)
        if frame.minimumState is not None:
            assert control_frame == ControlFrame.AMR
            # ^ assert since otherwise python-openlcb code itself has an error.
            #   - only AMR is allowed to be sent while transitioning to
            #     Inhibited state (and in this implementation, prior
            #     states occur before sending CID)
            state = self.getState()
            if state is None:
                return control_frame
            if state.value >= frame.minimumState.value:
                return None
        if control_frame == ControlFrame.CID:
            return None
        if control_frame == ControlFrame.RID:
            return None
        if control_frame == ControlFrame.AMD:
            return None
        return control_frame

    def isDuplicateAlias(self, alias):
        if not isinstance(alias, int):
            raise NotImplementedError(
                "Can't check for duplicate due to alias not stored as int."
                " bytearray parsing must be implemented in CanFrame"
                " constructor if this markDuplicateAlias scenario is valid"
                " (alias={})."
                .format(emit_cast(alias)))
        return alias in self.duplicateAliases
    # ^ was Commented since isCanceled handles both collision and error,
    #   but this can occur if a reservation was successful but the
    #   link layer later switched to an Inhibited state and had to
    #   generate a new alias

    def blockedReason(self, frame: CanFrame) -> Union[str, None]:
        if self.isCanceled(frame):
            return "The frame is using an alias from a previous reservation"
        blocked_type = self.blockedFrameType(frame)
        if blocked_type is not None:  # if not self.isAllowed(frame):
            return ("Only CID/RID/AMD can be sent while Inhibited ({}), not {}"
                    .format(self.getState(), blocked_type))
        if self.isDuplicateAlias(frame.alias):
            control_frame = CanFrame.decodeControlFrameFormat(frame)
            if control_frame != ControlFrame.AMR:
                return "can't send from an alias reserved by another node."
            # else allow deleting our own alias (Ok since our NodeID is
            #   required by the Standard to be unique).
        return None

    # Commented since instead, socket code should call linkLayerUp and
    #   linkLayerDown. Constructors should construct the openlcb stack:
    #   github.com/bobjacobsen/python-openlcb/issues/62#issuecomment-2775668681
    # def linkPhysicalLayer(self, cpl):
    #     """Set the physical layer to use.
    #     Also registers self.handleFrameReceived as a listener on the given
    #     physical layer. Before using sendMessage, wait for the
    #     connection phase to finish, as the phase receives aliases
    #     (populating nodeIdToAlias) and reserves a unique alias as per
    #     section 6.2.1 of CAN Frame Transfer Standard:
    #     https://openlcb.org/wp-content/uploads/2021/08/S-9.7.2.1-CanFrameTransfer-2021-04-25.pdf

    #     Args:
    #         cpl (CanPhysicalLayer): The physical layer to use.
    #     """
    #     self.physicalLayer = cpl  # self.link = cpl
    #     cpl.registerFrameReceivedListener(self.handleFrameReceived)
    #     # ^ Commented since it makes more sense for its
    #     #   constructor to do this, since it needs a PhysicalLayer
    #     #   in order to do anything

    def _onStateChanged(self, oldState: State, newState: State):
        # return super()._onStateChanged(oldState, newState)
        assert isinstance(newState, CanLink.State), \
            "expected a CanLink.State, got {}".format(emit_cast(newState))
        if newState == CanLink.State.EnqueueAliasAllocationRequest:
            self._enqueueCIDSequence()
            # - sets state to BusyLocalCIDSequence
            # - then at the end to WaitingForSendCIDSequence
            # - then a packet sent sets state to WaitForAliases
            # - then if wait is over,
            #   pollState sets state to EnqueueAliasReservation
        elif newState == CanLink.State.EnqueueAliasReservation:
            self._enqueueReserveID()  # sets _state to
            # - BusyLocalReserveID
            # - WaitingForSendReserveID
            # - NotifyAliasReservation (queued for after frame is sent)
        elif newState == CanLink.State.NotifyAliasReservation:
            self._notifyReservation()  # sets _state to
            # BusyLocalNotifyReservation
            # then WaitingForLocalNotifyReservation
            # then frame sent sets state to RecordAliasReservation
        elif newState == CanLink.State.RecordAliasReservation:
            # formerly _recordReservation was part of _notifyReservation
            self._recordReservation()
            # - BusyLocalMappingAlias
            #   (then adds our alias to the map)
            # - sets _state to Permitted (queued for after frame is sent)
            #   - (state was formerly set to Permitted at end of the
            #     _notifyReservation code, before _recordReservation
            #     code)
        if ((oldState != CanLink.State.Permitted)
                and (newState == CanLink.State.Permitted)):
            self.linkStateChange(newState)  # Notify upper layers
            # - formerly done at end of _recordReservation code.
        # TODO: Make sure upper layers handle any states
        #   necessary (formerly only states other than Initial were
        #   Inhibited & Permitted).
        self.pollState()  # May enqueue frame(s) via eventual recursion
        #  back to here, and/or change state. Calling it here may speed
        #  up certain state changes (prevent useless pollState loop
        #  iterations), but will not cause infinite recursion since
        #  pollState only should call this (via setState) when state
        #  actually changed.

    def handleFrameReceived(self, frame: CanFrame):
        """Call the correct handler if any for a received frame.
        Typically this is called by CanPhysicalLayer since the
        linkPhysicalLayer method in this class registers this method as
        a listener in the given CanPhysicalLayer instance.

        Args:
            frame (CanFrame): Any CanFrame, OpenLCB/LCC or not (if
                not then ignored).
        """
        handled = True  # True if state may change, otherwise set False
        control_frame = CanFrame.decodeControlFrameFormat(frame)
        if not ControlFrame.isInternal(control_frame):
            self._frameCount += 1
        else:
            print("[CanLink handleFrameReceived] control_frame={}"
                  .format(control_frame))

        if control_frame == ControlFrame.LinkUp:
            self.handleReceivedLinkUp(frame)
        elif control_frame == ControlFrame.LinkRestarted:  # noqa: E501
            self.handleReceivedLinkRestarted(frame)
        elif control_frame in (ControlFrame.LinkCollision,  # noqa: E501
                               ControlFrame.LinkError):
            logger.warning(
                "Unexpected error report {:08X}"
                .format(frame.header))
            self._errorCount += 1
            if self.isRunningAliasReservation():
                print("Restarting alias reservation due to error ({})."
                      .format(control_frame))
                # Restart alias reservation process if an
                #   error occurs during it, as per section
                #   6.2.1 of CAN Frame Transfer - Standard.
                self.defineAndReserveAlias()
        elif control_frame == ControlFrame.LinkDown:
            self.handleReceivedLinkDown(frame)
        elif control_frame == ControlFrame.CID:
            # NOTE: We may process other bits of frame.header
            #   that were stripped from control_frame
            self.handleReceivedCID(frame)
        elif control_frame == ControlFrame.RID:
            self.handleReceivedRID(frame)
        elif control_frame == ControlFrame.AMD:
            self.handleReceivedAMD(frame)
        elif control_frame == ControlFrame.AME:
            self.handleReceivedAME(frame)
        elif control_frame == ControlFrame.AMR:
            self.handleReceivedAMR(frame)
        elif control_frame in (ControlFrame.EIR0,
                               ControlFrame.EIR1,
                               ControlFrame.EIR2,
                               ControlFrame.EIR3):
            self._errorCount += 1
            if self.isRunningAliasReservation():
                print("Restarting alias reservation due to error ({})."
                      .format(control_frame))
                # Restart alias reservation process if an
                #   error occurs during it, as per section
                #   6.2.1 of CAN Frame Transfer - Standard.
                self.defineAndReserveAlias()
        elif control_frame == ControlFrame.Data:
            # NOTE: We may process other bits of frame.header
            #   that were stripped from control_frame
            self.handleReceivedData(frame)
        elif (control_frame == ControlFrame.UnknownFormat):
            logger.warning(
                "Unexpected CAN header 0x{:08X}"
                .format(frame.header))
            handled = False
        else:
            handled = False
            # This should never happen due to how
            #   decodeControlFrameFormat works, but this is a "not
            #   implemented" output for ensuring completeness (If this
            #   case occurs, some code is missing above).
            logger.warning(
                "Invalid control frame format 0x{:08X}"
                .format(control_frame))
        if handled:
            self.pollState()  # May enqueue frame(s) and/or change state.

    def isRunningAliasReservation(self) -> bool:
        return self._state in (
            CanLink.State.EnqueueAliasAllocationRequest,
            CanLink.State.BusyLocalCIDSequence,
            CanLink.State.WaitingForSendCIDSequence,
            CanLink.State.WaitForAliases,
            CanLink.State.EnqueueAliasReservation,
            CanLink.State.BusyLocalReserveID,
            CanLink.State.WaitingForSendReserveID
        )

    def handleReceivedLinkUp(self, frame: CanFrame):
        """Link started, update state, start process to create alias.
        LinkUp message will be sent when alias process completes.

        Args:
            frame (CanFrame): A LinkUp frame.
        """
        # start the alias allocation in Inhibited state
        self._state = CanLink.State.Inhibited
        self.defineAndReserveAlias()
        print("[CanLink] done calling defineAndReserveAlias.")

    def handleReceivedLinkRestarted(self, frame: CanFrame):
        """Send a LinkRestarted message upstream.

        Args:
            frame (CanFrame): A LinkRestarted frame.
        """
        msg = Message(MTI.Link_Layer_Restarted, NodeID(0), None,
                      bytearray())
        self.fireMessageReceived(msg)

    def _notifyReservation(self):
        """Send Alias Map Definition (AMD)
        Triggered by last frame sent that was enqueued by
        _recordReservation (NotifyAliasReservation)
        """
        # formerly ran in defineAndReserveAlias since
        # sendAliasAllocationSequence used to run all steps
        # in a blocking manner before this code
        # (and prevented this code on return False)
        self.setState(CanLink.State.BusyLocalNotifyReservation)
        # send AMD frame, go to Permitted state
        self.physicalLayer.sendFrameAfter(
            CanFrame(ControlFrame.AMD.value, self._localAlias,
                     self.localNodeID.toArray(),
                     afterSendState=CanLink.State.RecordAliasReservation,
                     reservation=self._reservation)
        )
        self.setState(CanLink.State.WaitingForLocalNotifyReservation)
        # self._state = CanLink.State.Permitted  # not really ready
        # (commented since network hasn't been notified yet)!
        # and now WaitingForLocalNotifyReservation allows local packets
        # (formerly Permitted was required even for )
        # wait for RecordAliasReservation state to call _recordReservation

    def _recordReservation(self):
        """Triggered by RecordAliasReservation

        Formerly ran directly after code in _notifyReservation
        but now we wait for the network to be aware of the node.
        - Call from _notifyReservation instead if alias needs to be
          mapped sooner.
        """
        self.setState(CanLink.State.BusyLocalMappingAlias)
        # add to map
        self.aliasToNodeID[self._localAlias] = self.localNodeID
        logger.info(
            "defineAndReserveAlias setting nodeIdToAlias[{}]"
            " from a datagram from an unknown source"
            .format(self.localNodeID))
        self.nodeIdToAlias[self.localNodeID] = self._localAlias

        # We already sent RID, so reservation is done
        # (Also AME is not allowed unless state is Permitted!)
        self.setState(CanLink.State.Permitted)

        #    send AME with no NodeID to get full alias map
        self.physicalLayer.sendFrameAfter(
            CanFrame(ControlFrame.AME.value, self._localAlias)
            # afterSendState=CanLink.State.Permitted)
        )

    #    TODO: (restart) Should this set inhibited every time? LinkUp not
    #    called on restart
    #    TODO: (restart) This is not called; there's no callback for it in
    #    Telnet library
    def handleReceivedLinkDown(self, frame: CanFrame):
        """return to Inhibited state until link back up

        Args:
            frame (CanFrame): an link down frame.
        """
        # NOTE: since no working link, not sending the AMR frame
        self._state = CanLink.State.Inhibited

        # print("***** received link down")
        # import traceback
        # traceback.print_stack()

        #    notify upper levels
        self.linkStateChange(self._state)

    def linkStateChange(self, state: State):
        """invoked when the link layer comes up and down

        Args:
            state (CanLink.State): See CanLink.
        """
        assert isinstance(state, CanLink.State)
        if state == CanLink.State.Permitted:
            print("[linkStateChange] Link_Layer_Up")
            msg = Message(MTI.Link_Layer_Up, NodeID(0), None, bytearray())
        elif state.value <= CanLink.State.Inhibited.value:
            msg = Message(MTI.Link_Layer_Down, NodeID(0), None, bytearray())
        else:
            raise TypeError(
                "The other layers don't need to know the intermediate steps.")
        self.fireMessageReceived(msg)

    def handleReceivedCID(self, frame: CanFrame):
        """Handle a Check ID (CID) frame (verifies node uniqueness).
        If source alias is same as ours, send a RID to cause the sender
        to try a different alias.
        - Additional arguments may be encoded in higher bits of
          frame.header (above FFF).
        """
        #    Does this carry our alias?
        if (frame.header & 0xFFF) != self._localAlias:
            return  # no match
        #    send an RID in response
        self.physicalLayer.sendFrameAfter(CanFrame(ControlFrame.RID.value,
                                          self._localAlias))

    def handleReceivedRID(self, frame: CanFrame):
        """Handle a Reserve ID (RID) frame
        (used for alias reservation)."""
        if self.checkAndHandleAliasCollision(frame):
            return

    def handleReceivedAMD(self, frame: CanFrame):
        """Handle an Alias Map Definition (AMD) frame
        (Defines a mapping between an alias and a full Node ID).
        """
        if self.checkAndHandleAliasCollision(frame):
            return
        # check for matching node ID, which is a collision
        nodeID = NodeID(frame.data)
        if nodeID == self.localNodeID :
            # collision, restart
            print("Alias collision occurred. Restarting alias reservation...")
            self.processCollision(frame)
            return
        #    This defines an alias, so store it
        alias = frame.header & 0xFFF
        self.aliasToNodeID[alias] = nodeID
        logger.info(
            "handleReceivedAMD setting nodeIdToAlias[{}]"
            .format(nodeID))
        self.nodeIdToAlias[nodeID] = alias

    def handleGlobalAME(self, frame: CanFrame):
        """If no data, clear all except self from maps
        even if not in Permitted state
        (CAN Frame Transfer Standard, 6.2.3
        Alias Map Enquiry).
        """
        if frame.data:  # not global
            return
        for otherNodeID in list(self.nodeIdToAlias.keys()):
            if otherNodeID == self.localNodeID:
                continue
            del self.nodeIdToAlias[otherNodeID]
            # except KeyError:
            #     pass  # concurrent modification
        for alias in list(self.aliasToNodeID.keys()):
            otherNodeID = self.aliasToNodeID[alias]
            # except KeyError:
            #     pass  # concurrent modification
            if otherNodeID == self.localNodeID:
                continue
            try:
                del self.nodeIdToAlias[otherNodeID]
            except KeyError:
                pass  # concurrent modification?
            # TODO: clear matching _send_frames??

    def handleReceivedAME(self, frame: CanFrame):
        """Handle an Alias Mapping Enquiry (AME) frame
        (a node requested alias information from other nodes).
        """
        if self.checkAndHandleAliasCollision(frame):
            return
        if self._state != CanLink.State.Permitted:
            self.handleGlobalAME(frame)
            return
        #    check node ID
        destNodeID = None
        if len(frame.data) == 6 :
            destNodeID = NodeID(frame.data)

        if (self.localNodeID == destNodeID) or (destNodeID is None):
            #    matched/global (and Permitted if got this far), so send AMD
            returnFrame = CanFrame(ControlFrame.AMD.value, self._localAlias,
                                   self.localNodeID.toArray())
            self.physicalLayer.sendFrameAfter(returnFrame)
        self.handleGlobalAME(frame)

    def handleReceivedAMR(self, frame: CanFrame):
        """Handle an Alias Map Reset (AMR) frame
        (A node is asking to remove an alias from mappings).
        """
        alias = frame.header & 0xFFF
        if (self.checkAndHandleAliasCollision(frame)):
            pass  # return
            logger.warning(
                f"Accepting AMR after collision (alias={alias:02X})")
        #    Alias Map Reset - drop from maps
        if not frame.data:
            logger.warning(f"Bad AMR (no data, so no NodeID) from {alias:02X}")
            return
        if len(frame.data) < 6:
            logger.warning("Bad AMR (data {} truncated--no NodeID) from {:02X}"
                           .format(frame.data, alias))
            return
        nodeID = NodeID(frame.data)
        # CAN Frame Transfer Standard 6.2.4 just says stop using the
        #   alias to refer to that node, so delete only on that
        #   condition to save steps and not lose any good mapping.
        storedID = self.aliasToNodeID.get(alias)
        localAlias = self.getLocalAlias(minimumState=CanLink.State.Initial)
        # ^ Standard doesn't say we have to be Permitted to process AMR
        if storedID == nodeID:
            if ((alias == localAlias) and (storedID == self.localNodeID)):
                logger.warning("AMR reset local nodeID {} (for alias [{}])"
                               .format(storedID, alias))
            try:
                logger.warning(f"AMR alias={alias:02X}")
                del self.aliasToNodeID[alias]
            except KeyError:
                pass  # deleted by a concurrent process
        else:
            logger.warning(
                f"AMR ignored: Node {nodeID} can't delete node"
                f" {storedID}'s alias {alias} which is the same")

        storedAlias = self.nodeIdToAlias.get(nodeID)
        if storedAlias == alias:
            if ((storedAlias == localAlias) and (nodeID == self.localNodeID)):
                logger.warning("AMR reset local alias {} (for NodeID [{}])"
                               .format(localAlias, nodeID))
            try:
                logger.warning(f"AMR nodeID={nodeID}")
                del self.nodeIdToAlias[nodeID]
            except KeyError:
                pass  # deleted by a concurrent process
        else:
            logger.warning(
                f"AMR ignored: Alias {alias} can't delete alias"
                f" {storedAlias}'s NodeID {nodeID} which is the same")
        try:
            self.duplicateAliases.remove(alias)
        except ValueError:
            pass  # not present
        return

    def handleReceivedData(self, frame: CanFrame):
        """Handle a data frame.
        Additional arguments may be encoded in lower bits (below
        ControlFrame.Data) in frame.header.
        """
        if self.checkAndHandleAliasCollision(frame):
            return
        # ^ may affect _aliasCollisionCount (not _frameCount)
        #    get proper MTI
        mti = self.canHeaderToFullFormat(frame)
        sourceID = NodeID(0)
        try:
            mapped = self.aliasToNodeID[frame.header & 0xFFF]
            sourceID = mapped
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            unmapped = frame.header & 0xFFF
            logger.warning("[CanLink]" + formatted_ex(ex))
            #    special case for JMRI before 5.1.5 which sends
            #    VerifiedNodeID but not AMD
            if mti == MTI.Verified_NodeID:
                sourceID = NodeID(frame.data)
                logger.info(
                    "Verified_NodeID frame {} from unknown source alias: {},"
                    " continue with observed ID {}"
                    .format(frame, unmapped, sourceID))
            else:
                sourceID = NodeID(self.nextInternallyAssignedNodeID)
                self.nextInternallyAssignedNodeID += 1
                logger.warning(
                    "message frame {} from unknown source alias: {},"
                    " continue with created ID {}"
                    .format(frame, unmapped, sourceID))

            #    register that internally-generated nodeID-alias association
            self.aliasToNodeID[frame.header & 0xFFF] = sourceID
            logger.info(
                "handleReceivedData setting nodeIdToAlias[{}]"
                " from a datagram from an unknown source"
                .format(sourceID))
            self.nodeIdToAlias[sourceID] = frame.header & 0xFFF

        destID = NodeID(0)
        #    handle destination for addressed messages
        dgCode = frame.header & 0x0_0F_00_00_00
        if frame.header & 0x00_80_00 != 0 \
                or (dgCode >= 0x0_0A_00_00_00 and dgCode <= 0x0_0F_00_00_00) :
            #    Addressed bit is active 1
            #    decoder regular addressed message from Datagram
            if (dgCode >= 0x0_0A_00_00_00 and dgCode <= 0x0_0F_00_00_00):
                #    datagram case

                destAlias = (frame.header & 0x00_FF_F0_00) >> 12

                if destAlias in self.aliasToNodeID  :
                    destID = self.aliasToNodeID[destAlias]
                else:
                    destID = NodeID(self.nextInternallyAssignedNodeID)
                    self.nextInternallyAssignedNodeID += 1
                    logger.warning(
                        "message from unknown dest alias: {},"
                        " continue with {}"
                        .format(str(frame), str(destID)))
                    #    register that internally-generated nodeID-alias
                    #    association
                    self.aliasToNodeID[destAlias] = destID
                    logger.info(
                        "handleReceivedData setting nodeIdToAlias[{}]"
                        " from a datagram from an unknown node"
                        .format(destID))
                    self.nodeIdToAlias[destID] = destAlias

                #    check for start and end bits
                key = CanLink.AccumKey(mti, sourceID, destID)
                if dgCode == 0x0_0A_00_00_00 or dgCode == 0x0_0B_00_00_00:
                    #    start of message, create the entry in the accumulator
                    self.accumulator[key] = bytearray()
                else:
                    # not start frame
                    # check for never properly started, this is an error
                    if key not in self.accumulator:
                        #    have not-start frame, but never started
                        logger.warning(
                            "Dropping non-start datagram frame"
                            " without accumulation started:"
                            " {}".format(frame)
                            # TODO: ^ more necessary to show same output
                            #   as Swift? Formerly:
                            #   " \(frame, privacy: .public)"
                        )
                        return  # early return to stop processing of this frame

                # add this data
                if len(frame.data) > 0:
                    self.accumulator[key].extend(frame.data)

                if dgCode == 0x0_0A_00_00_00 or dgCode == 0x0_0D_00_00_00:
                    #    is end, ship and remove accumulation
                    msg = Message(mti, sourceID, destID, self.accumulator[key])
                    self.fireMessageReceived(msg)

                    #    remove accumulation
                    self.accumulator[key] = None
            else:
                #    addressed message case
                destAlias = 0
                if (len(frame.data) > 0):
                    destAlias |= (frame.data[0] & 0x0F) << 8  # rm f bits
                    # TODO: Is this ok when len(frame.data) <= 1? Still << 8?
                if (len(frame.data) > 1):
                    destAlias |= (frame.data[1] & 0xFF)
                try:
                    mapped = self.aliasToNodeID[destAlias]
                    destID = mapped
                except KeyboardInterrupt:
                    raise
                except:
                    destID = NodeID(self.nextInternallyAssignedNodeID)
                    self.nextInternallyAssignedNodeID += 1
                    logger.warning(
                        "message from unknown dest alias:"
                        " 0x{:04X}, continue with 0x{}"
                        .format(destAlias, destID))
                    #    register that internally-generated nodeID-alias
                    #    association
                    self.aliasToNodeID[destAlias] = destID
                    logger.info(
                        "handleReceivedData setting nodeIdToAlias[{}]"
                        " to destID due to message from unknown dest."
                        .format(destID))
                    self.nodeIdToAlias[destID] = destAlias

                # check for start and end bits
                key = CanLink.AccumKey(mti, sourceID, destID)
                if frame.data and (frame.data[0] & 0x20 == 0):
                    #    is start, create the entry in the accumulator
                    self.accumulator[key] = bytearray()
                else:
                    # not start frame
                    # check for first bit set never seen
                    if key not in self.accumulator:
                        #    have not-start frame, but never started
                        logger.warning(
                            "Dropping non-start frame without"
                            " accumulation started: {}"
                            .format(frame))
                        return  # early return to stop processing of this gram

                #    add this data
                if len(frame.data) > 2:
                    for byte in frame.data[2:]:  # through end of array
                        self.accumulator[key].append(byte)

                if frame.data and (frame.data[0] & 0x10 == 0):
                    # is end, ship and remove accumulation
                    msg = Message(mti, sourceID, destID, self.accumulator[key])
                    # This includes the special case of MTI.Unknown,
                    #   which needs to carry its original MTI value
                    if mti is MTI.Unknown :
                        msg.originalMTI = ((frame.header >> 12) & 0xFFF)
                    self.fireMessageReceived(msg)

                    # remove accumulation
                    del self.accumulator[key]

            # end addressed message case

        else:
            # forward global message
            msg = Message(mti, sourceID, destID, frame.data)
            # This includes the special case of MTI.Unknown, which needs
            # to carry its original MTI value
            if mti is MTI.Unknown :
                msg.originalMTI = ((frame.header >> 12) & 0xFFF)
            self.fireMessageReceived(msg)

    def sendMessage(self, msg: Message, verbose=False):
        """Send a message using the physicalLayer.

        Args:
            msg (Message): Any message.
            verbose (bool, optional): (Reserved argument). Defaults to
                False.

        Raises:
            IndexError: If the source or destination address in the
                Message is invalid. The sender and receiver must be on
                the network. If not (not in nodeIdToAlias), the node
                didn't announce itself properly (as per OpenLCB
                standards), the node became disconnected, or a NodeID
                was entered incorrectly such as in a GUI.
        """
        error = None
        #    special case for datagram
        if msg.mti == MTI.Datagram:
            header = 0x10_00_00_00
            #    datagram headers are
            #             1Adddsss - one frame
            #             1Bdddsss - first frame
            #             1Cdddsss - middle frame
            #             1Ddddsss - last frame
            try:
                sssAlias = self.nodeIdToAlias[msg.source]
                header |= ((sssAlias) & 0xFFF)
            except KeyboardInterrupt:
                raise
            except KeyError:
                error = (
                    "Did not know source = {} on datagram send"
                    "".format(msg.source)
                )
                logger.error(error)
                raise

            try:
                dddAlias = self.nodeIdToAlias[msg.destination]
                header |= ((dddAlias) & 0xFFF) << 12
            except KeyboardInterrupt:
                raise
            except KeyError:
                error = (
                    "Did not know destination = {} on datagram send"
                    " self.nodeIdToAlias={}. Ensure recv loop"
                    " (such as OpenLCBNetwork's _listen thread) is running"
                    " before and during alias reservation sequence delay."
                    " Check previous log messages for an exception"
                    " that may have ended the recv loop."
                    .format(msg.destination,
                            self.nodeIdToAlias)
                )
                logger.error(error)
                raise

            if len(msg.data) <= 8:
                #    single frame
                header |= 0x0A_000_000
                frame = CanFrame(header, msg.data)
                self.physicalLayer.sendFrameAfter(frame)
            else:
                #    multi-frame datagram
                dataSegments = self.segmentDatagramDataArray(msg.data)
                #    send the first one
                frame = CanFrame(header | 0x0B_00_00_00, dataSegments[0])
                self.physicalLayer.sendFrameAfter(frame)
                #    send middles
                if len(dataSegments) >= 3:
                    for index in range(1, len(dataSegments) - 2 + 1):
                        # upper limit leaves one
                        frame = CanFrame(header | 0x0C_00_00_00,
                                         dataSegments[index])
                        self.physicalLayer.sendFrameAfter(frame)

                # send last one
                frame = CanFrame(
                    header | 0x0D_00_00_00,
                    dataSegments[len(dataSegments) - 1]
                )
                self.physicalLayer.sendFrameAfter(frame)
        else:
            #    all non-datagram cases
            #    Remap the mti
            header = 0x19_00_00_00 | ((msg.mti.value & 0xFFF) << 12)

            alias = self.nodeIdToAlias.get(msg.source)
            if alias is not None:  # might not know it if error
                header |= (alias & 0xFFF)
            else:
                error = (
                    "Did not know source = {} on message send"
                    .format(msg.source))
                logger.error(error)

            # Is a destination address needed? Could be long message
            if msg.isAddressed():
                dest = msg.destination
                if dest is None:
                    dest = NodeID(0)
                alias = self.nodeIdToAlias.get(dest)
                if alias is not None:  # might not know it?
                    #    address and have alias, break up data
                    dataSegments = self.segmentAddressedDataArray(alias,
                                                                  msg.data)
                    for content in dataSegments:
                        #    send the resulting frame
                        frame = CanFrame(header, content)
                        self.physicalLayer.sendFrameAfter(frame)
                else:
                    error = (
                        "Don't know alias for destination = {}"
                        .format(msg.destination or NodeID(0)))
                    logger.error(error)
            else:
                #    global still can hold data; assume length is correct by
                #    protocol send the resulting frame
                frame = CanFrame(header, msg.data)
                self.physicalLayer.sendFrameAfter(frame)

    def segmentDatagramDataArray(self, data: bytearray) -> List[bytearray]:
        """Segment data into zero or more arrays
        of no more than 8 bytes for datagram.

        Args:
            data (list): The input data to be segmented.

        Returns:
            list[bytearray]:  A list of one or more data segments.
                Each contains exactly 8 bytes except possibly the last.
        """
        nSegments = (len(data)+7) // 8
        # ^ the +7 is since integer division takes the floor value
        if nSegments == 0:
            return [bytearray()]

        if nSegments == 1:
            return [data]

        #    multiple frames
        segments = []
        for i in range(0, nSegments-2+1):  # first entry of 2 has full data
            nextEntry = data[i*8:i*8+7+1]
            segments.append(nextEntry)

        #    add the last
        lastEntry = data[8*(nSegments-1):]
        segments.append(lastEntry)

        return segments

    def segmentAddressedDataArray(self, alias: int,
                                  data: bytearray) -> List[bytearray]:
        '''Segment data into zero or more arrays
        of no more than 8 bytes, with the alias at the start of each,
        for addressed non-datagram messages.

        Args:
            alias (int): A 12-bit alias to be included at the start of
                each segment.
            data (list): The input data to be segmented.

        Returns:
            list[bytearray]: A list of one or more data segments.
                Each list begins with the alias (split into
                two parts) followed by segmented data.
        '''
        part0 = (alias >> 8) & 0xF
        part1 = alias & 0xFF
        nSegments = (len(data)+5) // 6  # the +5 is since integer division
        #   takes the floor value
        if nSegments == 0:
            return [bytearray([part0, part1])]
        if nSegments == 1:
            return [bytearray([part0, part1])+data]

        #    multiple frames
        segments = []
        for i in range(0, nSegments-2+1):  # first entry of 2 has full data
            nextEntry = bytearray([part0 | 0x30, part1]) + data[i*6:i*6+5+1]
            segments.append(nextEntry)

        #    add the last
        lastEntry = bytearray([part0 | 0x20, part1]) + data[6*(nSegments-1):]
        segments.append(lastEntry)
        #    mark first (last already done above)
        segments[0][0] &= ~0x20

        return segments

    #    MARK: common code
    def checkAndHandleAliasCollision(self, frame: CanFrame):
        if self._state != CanLink.State.Permitted:
            return False
        receivedAlias = frame.header & 0x0_00_0F_FF
        abort = (receivedAlias == self._localAlias)
        if abort:
            self.processCollision(frame)
        return abort

    def markDuplicateAlias(self, alias: int):
        if not isinstance(alias, int):
            raise NotImplementedError(
                "Can't mark collision due to alias not stored as int."
                " bytearray parsing must be implemented in CanFrame"
                " constructor if this markDuplicateAlias scenario is valid"
                " (alias={})."
                .format(emit_cast(alias)))
        self.duplicateAliases.append(alias)

    def processCollision(self, frame: CanFrame):
        ''' Collision! '''
        self._aliasCollisionCount += 1
        logger.warning(
            "alias collision in {}, we restart with AMR"
            " and attempt to get new alias".format(frame))
        self.markDuplicateAlias(frame.alias)
        if self._state == CanLink.State.Permitted:
            # Only tell nodes to stop using it if it was already in use
            #   (See Can Frame Transfer Standard
            #   section 6.2.5 Node ID Alias Collision Handling)
            #   - should only happen while already Permitted!
            # self.physicalLayer.clearSendQueue()  # probably not necessary using blockedReason later (should be isCanceled in this case)  # noqa: E501
            # Send AMR before inhibited (section 6.2.4):
            self.physicalLayer.sendFrameAfter(CanFrame(
                ControlFrame.AMR.value,
                self._localAlias,
                self.localNodeID.toArray(),
                minimumState=CanLink.State.WaitingForSendCIDSequence,
                afterSendState=CanLink.State.Inhibited))
            # ^ Allowed since defineAndReserveAlias below
            #   sets EnqueueAliasAllocationRequest, which
            #   triggers _enqueueCIDSequence which
            #   sets WaitingForSendCIDSequence before
            #   anything is sent (all happens via pollState).
        else:
            #    section 6.2.5 (restart alias reservation)
            self._state = CanLink.State.Inhibited
            #    attempt to get a new alias and go back to .Permitted
        self._localAliasSeed = self.incrementAlias48(self._localAliasSeed)
        self._localAlias = self.createAlias12(self._localAliasSeed)
        self.defineAndReserveAlias()

    # def sendAliasAllocationSequence(self):
    #     # actually, call self._enqueueCIDSequence()  # set _state&send data
    #     raise DeprecationWarning("Use setState to BusyLocalCIDSequence")
    def getWaitForAliasResponseStart(self):
        return self._waitingForAliasStart

    def pollState(self) -> State:
        """You must keep polling state after every time
        a state change frame is sent, and after
        every call to handleDataString or handleData
        for the stack to keep operating.
        - calling this automatically *must not* be
          implemented there, because this exists to
          untether the processing from the socket
          to make those calls non-blocking
          (were blocking since sendAliasAllocationSequence
          could be called in the case of processCollision)
          - This being separate has the added benefit of the
            stack being able to work in the same thread
            as the application's (or OpenLCBNetwork's)
            socket calls.
        """
        assert isinstance(self._state, CanLink.State), \
            "Expected a CanLink.State, got {}".format(emit_cast(self._state))
        if self._state in (CanLink.State.Inhibited, CanLink.State.Initial):
            # Do nothing. OpenLCBNetwork or application must first call
            # physicalLayerUp
            # - which triggers handleReceivedLinkUp
            #   - which calls defineAndReserveAlias
            pass
        elif self._state == CanLink.State.WaitForAliases:
            if self._waitingForAliasStart is None:
                self._waitingForAliasStart = default_timer()
            else:
                if ((default_timer() - self._waitingForAliasStart)
                        > CanLink.ALIAS_RESPONSE_DELAY):
                    # There were no alias collisions (any nodes with the
                    #   same alias are required to respond within this
                    #   time as per Section 6.2.5 of CAN Frame Transfer
                    #   Standard) so finish the sends for the alias
                    #   reservation:
                    self._waitingForAliasStart = None
                    self.setState(CanLink.State.EnqueueAliasReservation)
        # NOTE: *All* other state processing is done in _onStateChange
        #   which is always called by setState, so avoid infinite
        #   recursion by only calling setState from here if state is
        #   sure to have changed, and won't change to a state this
        #   handles since it calls this (and do all non-delayed state
        #   changes in _onStateChange not here).

        return self.getState()

    # May use self._enqueueCIDSequence() instead,
    # but actually trigger it in _onStateChanged
    # via setState(CanLink.State.EnqueueAliasAllocationRequest)
    # self.sendAliasAllocationSequence()
    def defineAndReserveAlias(self):
        """Enqueue EnqueueAliasAllocationRequest frames.
        See section 6.2.1 of LCC "CAN Frame Transfer" Standard

        Implementation details: The application must call popFrames()
        and send them as usual in its socket streaming loop, as well as
        continue calling pollState() and check its return against
        CanLink.State.Permitted before trying to send a CanFrame or
        Message instance. The application manages flow and the
        openlcb stack (this Python module) manages state.
        """
        if self._reservation > -1:
            # If any reservation occurred before, clear it
            #   (prevent race condition, don't require pollFrame loop
            #   to check isDuplicateAlias)
            self.physicalLayer.clearReservation(self._reservation)
        self._reservation += 1
        self.setState(CanLink.State.EnqueueAliasAllocationRequest)

    def _enqueueCIDSequence(self):
        """Enqueue the four alias reservation step1 frames
        (N_cid values 7, 6, 5, 4 respectively)
        It is the responsibility of the application code
        (socket/PortInterface thread) to set the next state using
        frame.afterSendState. See afterSendState in CanFrame
        documentation.

        Triggered by EnqueueAliasReservation
        """
        self._previousLocalAliasSeed = self._localAliasSeed
        self.setState(CanLink.State.BusyLocalCIDSequence)
        # sending 7, 6, 5, 4 tells the LCC network we are a node, and other LCC
        #   nodes will respond with their NodeIDs and aliases (populates
        #   NodeIdToAlias, permitting openlcb to send to those
        #   destinations)
        self.physicalLayer.sendFrameAfter(CanFrame(7, self.localNodeID,
                                          self._localAlias,
                                          reservation=self._reservation))
        self.physicalLayer.sendFrameAfter(CanFrame(6, self.localNodeID,
                                          self._localAlias,
                                          reservation=self._reservation))
        self.physicalLayer.sendFrameAfter(CanFrame(5, self.localNodeID,
                                          self._localAlias,
                                          reservation=self._reservation))
        self.physicalLayer.sendFrameAfter(
            CanFrame(4, self.localNodeID, self._localAlias,
                     afterSendState=CanLink.State.WaitForAliases,
                     reservation=self._reservation)
        )
        self._previousErrorCount = self._errorCount
        self._previousFrameCount = self._frameCount
        self._previousLocalAliasSeed = self._localAliasSeed
        self.setState(CanLink.State.WaitingForSendCIDSequence)

    def _enqueueReserveID(self):
        """Send Reserve ID (RID)

        Triggered by CanLink.State.EnqueueAliasReservation
        - If no collision during `CanLink.ALIAS_RESPONSE_DELAY`.
        """
        self._waitingForAliasStart = None  # done waiting for reply to 7,6,5,4
        self.setState(CanLink.State.BusyLocalReserveID)
        # Waiting 200ms as per section 6.2.1 of CAN Frame Transfer -
        #   Standard is now done by pollState (application must keep
        #   polling after sending and receiving data)
        #   - But based on _waitingForAliasStart, so pollState is not a
        #     blocking call.

        # The frame below must be cancelled by the application/other
        #   pollFrame loop if there was a collision in the meantime
        #   (simply don't send the result of pollFrame if
        #   isDuplicateAlias)
        # TODO: ^ Test that.
        # NOTE: Below may cause a race condition, but more than
        #   one thread *must not* be handling send, so this is the
        #   solution for now:
        thisErrorCount = self._errorCount - self._previousErrorCount
        if thisErrorCount > 1:
            # Restart reservation on error as per section 6.2.1 of
            # CAN Frame Transfer - Standard.
            # - This is not a collision, so don't increment alias.
            print("Error occurred, restarting alias reservation...")
            self.defineAndReserveAlias()

        self.physicalLayer.sendFrameAfter(
            CanFrame(ControlFrame.RID.value, self._localAlias,
                     afterSendState=CanLink.State.NotifyAliasReservation,
                     reservation=self._reservation)
        )
        self.setState(CanLink.State.WaitingForSendReserveID)

    def incrementAlias48(self, oldAlias: int) -> int:
        '''
        Implements the OpenLCB preferred alias
        generation mechanism:  a 48-bit computation
        of x(i+1) = (2^9+1) x(i) + c
        where c = 29,741,096,258,473 or 0x1B0CA37A4BA9
        '''

        newProduct = (oldAlias << 9) + oldAlias + (0x1B_0C_A3_7A_4B_A9)
        maskedProduct = newProduct & 0xFFFF_FFFF_FFFF
        return maskedProduct

    def createAlias12(self, rnd: int) -> int:
        '''Form 12 bit alias from 48-bit random number'''

        part1 = (rnd >> 36) & 0x0FFF
        part2 = (rnd >> 24) & 0x0FFF
        part3 = (rnd >> 12) & 0x0FFF
        part4 = (rnd) & 0x0FFF

        if (part1 ^ part2 ^ part3 ^ part4) != 0:
            return (part1 ^ part2 ^ part3 ^ part4)

        #    zero is not a valid alias, so provide a non-zero value
        if ((part1+part2+part3+part4) & 0xFF) != 0:
            return ((part1+part2+part3+part4) & 0xFF)
        return 0xAEF  # Why'd you say Burma?

    def canHeaderToFullFormat(self, frame: CanFrame) -> MTI:
        '''Returns a full 16-bit MTI from the full 29 bits of a CAN header'''
        frameType = (frame.header >> 24) & 0x7
        canMTI = ((frame.header >> 12) & 0xFFF)

        if frameType == 1:
            try :
                okMTI = MTI(canMTI)
            except ValueError:
                logger.warning(
                    "unhandled canMTI: {}, marked Unknown"
                    .format(frame))
                return MTI.Unknown
            return okMTI

        if (frameType >= 2 and 5 >= frameType):
            #    datagram type - we don't address the subtypes here
            return MTI.Datagram

        #    not handling reserver and stream type except to log
        logger.warning(
            "unhandled canMTI: {}, marked Unknown"
            .format(frame))
        return MTI.Unknown

    def waitForReady(self, device: PortInterface, mode="binary",
                     run_physical_link_up_test=False, verbose=True):
        """Send and receive frames until.
        Other thread(s) *must not* use the device during this
        (overlapping read or write would cause "undefined behavior" at
        OS level).

        Args:
            device (PortInterface): *Must* be in non-blocking
                mode (or send & receive dialog will fail and time out):
                A Serial or Socket wrapped in the PortInterface to
                provide send and sendString (since Serial itself has
                write not send).
            mode (str, optional): "binary" to use device.send, or "text"
                to attempt device.sendString.
            run_physical_link_up_test (bool, optional): Set to True only
                if the last command that ran was "physicalLayerUp".
            verbose (bool, optional): If True, print status to
                console. Defaults to False.
        Raises:
            AssertionError: run_physical_link_up_test is True
                but the state is not initially WaitingForSendCIDSequence
                or successive states were not triggered by pollState
                and onFrameSent.
        """
        assert device is not None
        prefix = "[{}] ".format(type(self).__name__)  # show subclass on print
        first = True
        state = self.pollState()
        if verbose:
            print(prefix+"waitForReady...state={}...".format(state))
        first_state = state
        if run_physical_link_up_test:
            assert state == CanLink.State.WaitingForSendCIDSequence
        debug_count = 0
        second_state = None
        while True:
            # NOTE: Must call handleData each read regardless of pollState().
            debug_count += 1
            # if verbose:
            #     print("{}. state: {}".format(debug_count, state))
            if state == CanLink.State.Permitted:
                # This could be the while condition, but
                #   is here so we can monitor it for testing.
                break
            if first is True:
                first = False
            if verbose and debug_count < 3:
                print("  * sendAll")
            self.physicalLayer.sendAll(device, mode=mode, verbose=verbose)
            if verbose and debug_count < 3:
                print("  * state: {}".format(state))
            state = self.getState()
            if first_state == CanLink.State.WaitingForSendCIDSequence:
                # State should be set by onFrameSent (called by
                # sendAll, or in non-simulation cases, the socket loop
                #   after dequeued and sent, as the next state is )
                if second_state is None:
                    assert state == CanLink.State.WaitForAliases, \
                        ("expected onFrameSent (if properly set to"
                         " handleFrameSent or overridden for simulation) sent"
                         " frame's EnqueueAliasAllocationRequest state (CID"
                         " 4's afterSendState), but state is {}"
                         .format(state))
                    second_state = state
                # If sendAll blocks for at least 200ms after send
                #   then receives, responses may have already been sent
                #   to handleFrameReceived, in which case we may be in a
                #   later state. That isn't recommended except for
                #   realtime applications (or testing). However, if that
                #   is programmed, add
                #   `or state == CanLink.State.EnqueueAliasAllocationRequest`
                #   to the assertion.
            if state == CanLink.State.WaitForAliases:
                if verbose and debug_count < 3:
                    print("    * sendAll")
                state = self.pollState()  # set _waitingForAliasStart if None
                # (prevent getWaitForAliasResponseStart() None in assert below)
                if device is not None:
                    # self.physicalLayer.receiveAll(device)
                    try:
                        data = device.receive()  # If timeout, set non-blocking
                        self.physicalLayer.handleData(data)
                    except BlockingIOError:
                        # raised by receive if no data (non-blocking is
                        #   what we want, so fall through).
                        pass
            state = self.pollState()
            if state == CanLink.State.Permitted:
                if verbose:
                    print("    * state: {}".format(state))
                break
            # if verbose:
            #     print("  * state: {}".format(state))
            responseStart = self.getWaitForAliasResponseStart()
            assert responseStart is not None, \
                "openlcb didn't send 7,6,5,4 CIDs (state={})".format(state)
            if ((default_timer() - responseStart)
                    > CanLink.ALIAS_RESPONSE_DELAY):
                # 200ms = standard wait time for responses
                pass  # no collisions (fail collision test if doing that)
            precise_sleep(.02)  # must be *less than* 200ms (.2) to process
            #   collisions (via handleData) if any during
            #   CanLink.State.WaitForAliases.
            state = self.pollState()
        if verbose:
            print(prefix+"waitForReady...done")

    class AccumKey:
        '''Class that holds the ID for accumulating a multi-part message:

        - MTI

        - Source

        - Destination

        Together these uniquely identify a stream of frames that need to
        be assembled into a message
        '''
        def __init__(self, mti, source, dest):
            self.mti = mti
            self.source = source
            self.dest = dest

        def __hash__(self):
            return hash(self.mti)+hash(self.source)+hash(self.dest)

        def __eq__(self, other):
            if self.mti != other.mti:
                return False
            if self.source != other.source:
                return False
            if self.dest != other.dest:
                return False
            return True
