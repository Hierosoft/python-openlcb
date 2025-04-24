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

from openlcb import emit_cast, formatted_ex, precise_sleep
from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.controlframe import ControlFrame

from openlcb.linklayer import LinkLayer
from openlcb.message import Message
from openlcb.mti import MTI
from openlcb.nodeid import NodeID

logger = getLogger(__name__)


class CanLink(LinkLayer):
    """CAN link layer (manage stack's link state).

    Attributes:
        ALIASES_RECEIVED_TIMEOUT (float): (seconds) CAN Frame Transfer -
            Standard says to wait 200 ms for collisions, and if there
            are no replies, the alias is good, otherwise increment and
            restart alias reservation.
            - However, in this implementation, require_remote_nodes
              is True by default (See require_remote_nodes).

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
        require_remote_nodes (bool): If True, getting no external frames
            (See isInternal) within ALIASES_RECEIVED_TIMEOUT (seconds)
            causes an exception in pollState. Defaults to True, which is
            non-standard:
            - CAN Frame Transfer - Standard specifies that after 200ms
              the node should assume _localAlias is ok (even if there
              are 0 responses, in which case assume no other LCC nodes
              are connected).
            - In this implementation we at least expect an LCC hub
              (otherwise there is no hardware connection, or an issue
              with socket timing, call order, or another hard-coded
              problem in the stack or application).
    """

    ALIAS_RESPONSE_DELAY = .2  # See docstring.

    def __init__(self, localNodeID, require_remote_nodes=True):  # a NodeID
        # See class docstring for args
        self.require_remote_nodes = require_remote_nodes
        self._waitingForAliasStart = None
        self._localAliasSeed = localNodeID.value
        self._localAlias = self.createAlias12(self._localAliasSeed)
        self.localNodeID = localNodeID
        self._state = CanLink.State.Initial
        self.link = None
        self._frameCount = 0
        self._reserveAliasCollisions = 0
        self._errorCount = 0
        self.aliasToNodeID = {}
        self.nodeIdToAlias = {}
        self.accumulator = {}
        self.duplicateAliases = []
        self.nextInternallyAssignedNodeID = 1
        LinkLayer.__init__(self, localNodeID)

    # This method may never actually be necessary, as
    # sendMessage uses nodeIdToAlias (which has localNodeID
    # *only after* a successful reservation)
    def getLocalAlias(self):
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
        if self._state != CanLink.State.Permitted:
            raise InterruptedError(
                "The alias reservation is not complete (state={})."
                " Make sure defineAliasReservation (linkLayerUp) isn't"
                " called in a way that blocks the socket receive thread,"
                " and that your application has a Message received listener"
                " registered via registerMessageReceivedListener that"
                " checks for MTI.Link_Layer_Up and MTI.Link_Layer_Down"
                " and inhibits the usage of the openlcb stack if not up"
                " unless you poll for"
                " canlink.getState() == CanLink.State.Permitted in a"
                " non-blocking manner."
                .format(self._state)
            )
        return self._localAlias

    def ready(self):
        """Check if state == CanLink.State.Permitted
        To find out if ready right away, check for
        MTI.Link_Layer_Up and MTI.Link_Layer_Down and use them
        to track the state in the application code.
        """
        assert isinstance(self._state, CanLink.State)
        return self._state == CanLink.State.Permitted

    def isDuplicateAlias(self, alias):
        if not isinstance(alias, int):
            raise NotImplementedError(
                "Can't check for duplicate due to alias not stored as int."
                " bytearray parsing must be implemented in CanFrame"
                " constructor if this markDuplicateAlias scenario is valid"
                " (alias={})."
                .format(emit_cast(alias)))
        return alias in self.duplicateAliases

    def linkPhysicalLayer(self, cpl):
        """Set the physical layer to use.
        Also registers self.receiveListener as a listener on the given
        physical layer. Before using sendMessage, wait for the
        connection phase to finish, as the phase receives aliases
        (populating nodeIdToAlias) and reserves a unique alias as per
        section 6.2.1 of CAN Frame Transfer Standard:
        https://openlcb.org/wp-content/uploads/2021/08/S-9.7.2.1-CanFrameTransfer-2021-04-25.pdf

        Args:
            cpl (CanPhysicalLayer): The physical layer to use.
        """
        self.link = cpl
        cpl.registerFrameReceivedListener(self.receiveListener)

    class State(Enum):
        """This now behaves as a linux-like "runlevel"
        so that defineAndReserveAlias is non-blocking.

        Attributes:
            AllocatingAlias (State): Waiting for send of the last
                reservation packet (after collision detection fully
                done) to be success (wait for socket to notify us,
                sendAfter is not enough)
        """
        Initial = LinkLayer.State.Undefined.value  # special case of .Inhibited
        #   where init hasn't started.
        Inhibited = 2
        EnqueueAliasAllocationRequest = 3
        # enqueueCIDSequence sets:
        BusyLocalCIDSequence = 4
        WaitingForSendCIDSequence = 5
        WaitForAliases = 6  # queued via last frame it sends
        EnqueueAliasReservation = 7  # called by pollState if got aliases
        #  (or after fixed delay if require_remote_nodes is False)
        # enqueueReserveID sets:
        BusyLocalReserveID = 8
        WaitingForSendReserveID = 9

        NotifyAliasReservation = 14

        BusyLocalNotifyReservation = 11
        WaitingForLocalNotifyReservation = 12
        RecordAliasReservation = 13


        BusyLocalMappingAlias = 18
        Permitted = 20  # formerly 3

    def _onStateChanged(self, _, newState):
        # return super()._onStateChanged(oldState, newState)
        assert isinstance(newState, CanLink.State)
        if newState == CanLink.State.EnqueueAliasAllocationRequest:
            self.enqueueCIDSequence()
            # - sets state to BusyLocalCIDSequence
            # - then at the end to WaitingForSendCIDSequence
            # - then a packet sent sets state to WaitForAliases
            # - then if wait is over,
            #   pollState sets state to EnqueueAliasReservation
        elif newState == CanLink.State.EnqueueAliasReservation:
            self.enqueueReserveID()  # sets _state to
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

        self.linkStateChange(newState)  # Notify upper layers

    def receiveListener(self, frame):
        """Call the correct handler if any for a received frame.
        Typically this is called by CanPhysicalLayer since the
        linkPhysicalLayer method in this class registers this method as
        a listener in the given CanPhysicalLayer instance.

        Args:
            frame (CanFrame): Any CanFrame, OpenLCB/LCC or not (if
                not then ignored).
        """
        control_frame = self.decodeControlFrameFormat(frame)
        if not ControlFrame.isInternal(control_frame):
            self._frameCount += 1
        else:
            print("[CanLink receiveListener] control_frame={}"
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
        elif control_frame == ControlFrame.Data:
            # NOTE: We may process other bits of frame.header
            #   that were stripped from control_frame
            self.handleReceivedData(frame)
        elif (control_frame == ControlFrame.UnknownFormat):
            logger.warning(
                "Unexpected CAN header 0x{:08X}"
                .format(frame.header))
        else:
            # This should never happen due to how
            #   decodeControlFrameFormat works, but this is a "not
            #   implemented" output for ensuring completeness (If this
            #   case occurs, some code is missing above).
            logger.warning(
                "Invalid control frame format 0x{:08X}"
                .format(control_frame))

    def handleReceivedLinkUp(self, frame):
        """Link started, update state, start process to create alias.
        LinkUp message will be sent when alias process completes.

        Args:
            frame (CanFrame): A LinkUp frame.
        """
        # start the alias allocation in Inhibited state
        self._state = CanLink.State.Inhibited
        if self.defineAndReserveAlias():
            print("[CanLink] Notifying upper layers of LinkUp.")
        else:
            logger.warning(
                "[CanLink] Not notifying upper layers of LinkUp"
                " since reserve alias failed (will retry).")

    def handleReceivedLinkRestarted(self, frame):
        """Send a LinkRestarted message upstream.

        Args:
            frame (CanFrame): A LinkRestarted frame.
        """
        msg = Message(MTI.Link_Layer_Restarted, NodeID(0), None,
                      bytearray())
        self.fireListeners(msg)

    def defineAndReserveAlias(self):
        self.setState(CanLink.State.EnqueueAliasAllocationRequest)
    #
    # Use self.enqueueCIDSequence() instead,
    # but actually trigger it in _onStateChanged
    # via setState(CanLink.State.EnqueueAliasAllocationRequest)
    # self.sendAliasAllocationSequence()
    #
    # Split up to the following (which was its docstring):
    """
    This *must not block* the frame receive thread, since we must
    wait 200ms and start sendAliasAllocationSequence over if
    transmission error occurs, or an announcement with a Node ID
    same as ours is received.
    - In either case this method must *not* complete (*not* sending
        RID is implied).
    - In the latter case, our ID must be incremented before
        sendAliasAllocationSequence starts over, and repeat this until
        it is unique (no packets with senders matching it are
        received)
    - See section 6.2.1 of LCC "CAN Frame Transfer" Standard

    Returns:
        bool: True if succeeded, False if collision.
    """

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
        self.link.sendCanFrame(
            CanFrame(ControlFrame.AMD.value, self._localAlias,
                     self.localNodeID.toArray(),
                     afterSendState=CanLink.State.RecordAliasReservation)
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
        #    send AME with no NodeID to get full alias map
        self.link.sendCanFrame(
            CanFrame(ControlFrame.AME.value, self._localAlias,
                     afterSendState=CanLink.State.Permitted)
        )

    #    TODO: (restart) Should this set inhibited every time? LinkUp not
    #    called on restart
    #    TODO: (restart) This is not called; there's no callback for it in
    #    Telnet library
    def handleReceivedLinkDown(self, frame):
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

    def linkStateChange(self, state):
        """invoked when the link layer comes up and down

        Args:
            state (CanLink.State): See CanLink.
        """
        if state == CanLink.State.Permitted:
            print("[linkStateChange] Link_Layer_Up")
            msg = Message(MTI.Link_Layer_Up, NodeID(0), None, bytearray())
        else:
            msg = Message(MTI.Link_Layer_Down, NodeID(0), None, bytearray())
        self.fireListeners(msg)

    def handleReceivedCID(self, frame):  # CanFrame
        """Handle a Check ID (CID) frame only if addressed to us
        (used to verify node uniqueness). Additional arguments may be
        encoded in lower bits of frame.header (below ControlFrame.CID).
        """
        #    Does this carry our alias?
        if (frame.header & 0xFFF) != self._localAlias:
            return  # no match
        #    send an RID in response
        self.link.sendCanFrame(CanFrame(ControlFrame.RID.value,
                                        self._localAlias))

    def handleReceivedRID(self, frame):  # CanFrame
        """Handle a Reserve ID (RID) frame
        (used for alias reservation)."""
        if self.checkAndHandleAliasCollision(frame):
            return

    def handleReceivedAMD(self, frame):  # CanFrame
        """Handle an Alias Map Definition (AMD) frame
        (Defines a mapping between an alias and a full Node ID).
        """
        if self.checkAndHandleAliasCollision(frame):
            return
        # check for matching node ID, which is a collision
        nodeID = NodeID(frame.data)
        if nodeID == self.localNodeID :
            print("collide")
            # collision, restart
            self.processCollision(frame)
            return
        #    This defines an alias, so store it
        alias = frame.header & 0xFFF
        self.aliasToNodeID[alias] = nodeID
        logger.info(
            "handleReceivedAMD setting nodeIdToAlias[{}]"
            .format(nodeID))
        self.nodeIdToAlias[nodeID] = alias

    def handleReceivedAME(self, frame):  # CanFrame
        """Handle an Alias Mapping Enquiry (AME) frame
        (a node requested alias information from other nodes).
        """
        if self.checkAndHandleAliasCollision(frame):
            return
        if self._state != CanLink.State.Permitted:
            return
        #    check node ID
        matchNodeID = self.localNodeID
        if len(frame.data) >= 6 :
            matchNodeID = NodeID(frame.data)

        if self.localNodeID == matchNodeID :
            #    matched, send RID
            returnFrame = CanFrame(ControlFrame.AMD.value, self._localAlias,
                                   self.localNodeID.toArray())
            self.link.sendCanFrame(returnFrame)

    def handleReceivedAMR(self, frame):  # CanFrame
        """Handle an Alias Map Reset (AMR) frame
        (A node is asking to remove an alias from mappings).
        """
        if (self.checkAndHandleAliasCollision(frame)):
            return
        #    Alias Map Reset - drop from maps
        nodeID = NodeID(frame.data)
        alias = frame.header & 0xFFF
        try:
            del self.aliasToNodeID[alias]
            del self.nodeIdToAlias[nodeID]
        except KeyboardInterrupt:
            raise
        except:
            pass

    def handleReceivedData(self, frame):  # CanFrame
        """Handle a data frame.
        Additional arguments may be encoded in lower bits (below
        ControlFrame.Data) in frame.header.
        """
        if self.checkAndHandleAliasCollision(frame):
            return
        # ^ may affect _reserveAliasCollisions (not _frameCount)
        #    get proper MTI
        mti = self.canHeaderToFullFormat(frame)
        sourceID = NodeID(0)
        try:
            mapped = self.aliasToNodeID[frame.header & 0xFFF]
            sourceID = mapped
        except KeyboardInterrupt:
            raise
        except:
            #    special case for JMRI before 5.1.5 which sends
            #    VerifiedNodeID but not AMD
            if mti == MTI.Verified_NodeID:
                sourceID = NodeID(frame.data)
                logger.info(
                    "Verified_NodeID from unknown source alias: {},"
                    " continue with observed ID {}"
                    .format(frame, sourceID))
            else:
                sourceID = NodeID(self.nextInternallyAssignedNodeID)
                self.nextInternallyAssignedNodeID += 1
                logger.warning(
                    "message from unknown source alias: {},"
                    " continue with created ID {}"
                    .format(frame, sourceID))

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
                    self.fireListeners(msg)

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
                if (frame.data[0] & 0x20 == 0):
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

                if frame.data[0] & 0x10 == 0:
                    # is end, ship and remove accumulation
                    msg = Message(mti, sourceID, destID, self.accumulator[key])
                    # This includes the special case of MTI.Unknown,
                    #   which needs to carry its original MTI value
                    if mti is MTI.Unknown :
                        msg.originalMTI = ((frame.header >> 12) & 0xFFF)
                    self.fireListeners(msg)

                    # remove accumulation
                    self.accumulator[key] = None

            # end addressed message case

        else:
            # forward global message
            msg = Message(mti, sourceID, destID, frame.data)
            # This includes the special case of MTI.Unknown, which needs
            # to carry its original MTI value
            if mti is MTI.Unknown :
                msg.originalMTI = ((frame.header >> 12) & 0xFFF)
            self.fireListeners(msg)

    def sendMessage(self, msg):
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
            except:
                logger.warning(
                    "Did not know source = {} on datagram send"
                    "".format(msg.source)
                )

            try:
                dddAlias = self.nodeIdToAlias[msg.destination]
                header |= ((dddAlias) & 0xFFF) << 12
            except KeyboardInterrupt:
                raise
            except Exception as ex:
                logger.error(
                    "Did not know destination = {} on datagram send ({})"
                    " self.nodeIdToAlias={}. Ensure recv loop"
                    " (such as Dispatcher's _listen thread) is running"
                    " before and during alias reservation sequence delay."
                    " Check previous log messages for an exception"
                    " that may have ended the recv loop."
                    .format(msg.destination, formatted_ex(ex),
                            self.nodeIdToAlias)
                )

            if len(msg.data) <= 8:
                #    single frame
                header |= 0x0A_000_000
                frame = CanFrame(header, msg.data)
                self.link.sendCanFrame(frame)
            else:
                #    multi-frame datagram
                dataSegments = self.segmentDatagramDataArray(msg.data)
                #    send the first one
                frame = CanFrame(header | 0x0B_00_00_00, dataSegments[0])
                self.link.sendCanFrame(frame)
                #    send middles
                if len(dataSegments) >= 3:
                    for index in range(1, len(dataSegments) - 2 + 1):
                        # upper limit leaves one
                        frame = CanFrame(header | 0x0C_00_00_00,
                                         dataSegments[index])
                        self.link.sendCanFrame(frame)

                # send last one
                frame = CanFrame(
                    header | 0x0D_00_00_00,
                    dataSegments[len(dataSegments) - 1]
                )
                self.link.sendCanFrame(frame)
        else:
            #    all non-datagram cases
            #    Remap the mti
            header = 0x19_00_00_00 | ((msg.mti.value & 0xFFF) << 12)

            alias = self.nodeIdToAlias.get(msg.source)
            if alias is not None:  # might not know it if error
                header |= (alias & 0xFFF)
            else:
                logger.warning(
                    "Did not know source = {} on message send"
                    .format(msg.source))

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
                        self.link.sendCanFrame(frame)
                else:
                    logger.warning(
                        "Don't know alias for destination = {}"
                        .format(msg.destination or NodeID(0)))
            else:
                #    global still can hold data; assume length is correct by
                #    protocol send the resulting frame
                frame = CanFrame(header, msg.data)
                self.link.sendCanFrame(frame)

    def segmentDatagramDataArray(self, data):
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

    def segmentAddressedDataArray(self, alias, data):
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
    def checkAndHandleAliasCollision(self, frame):
        if self._state != CanLink.State.Permitted:
            return False
        receivedAlias = frame.header & 0x0_00_0F_FF
        abort = (receivedAlias == self._localAlias)
        if abort:
            self.processCollision(frame)
        return abort

    def markDuplicateAlias(self, alias):
        if not isinstance(alias, int):
            raise NotImplementedError(
                "Can't mark collision due to alias not stored as int."
                " bytearray parsing must be implemented in CanFrame"
                " constructor if this markDuplicateAlias scenario is valid"
                " (alias={})."
                .format(emit_cast(alias)))
        self.duplicateAliases.append(alias)

    def processCollision(self, frame) :
        ''' Collision! '''
        self._reserveAliasCollisions += 1
        logger.warning(
            "alias collision in {}, we restart with AMR"
            " and attempt to get new alias".format(frame))
        self.markDuplicateAlias(frame.alias)
        self.link.sendCanFrame(CanFrame(ControlFrame.AMR.value,
                                        self._localAlias,
                                        self.localNodeID.toArray()))
        #    Standard 6.2.5
        self._state = CanLink.State.Inhibited
        #    attempt to get a new alias and go back to .Permitted
        self._localAliasSeed = self.incrementAlias48(self._localAliasSeed)
        self._localAlias = self.createAlias12(self._localAliasSeed)
        self.defineAndReserveAlias()

    # def sendAliasAllocationSequence(self):
    #     # actually, call self.enqueueCIDSequence()  # sets _state and sends data
    #     raise DeprecationWarning("Use setState to BusyLocalCIDSequence instead.")

    def pollState(self):
        """You must keep polling state after every time
        a state change frame is sent, and after
        every call to pushString or pushChars
        for the stack to keep operating.
        - calling this automatically *must not* be
          implemented there, because this exists to
          untether the processing from the socket
          to make those calls non-blocking
          (were blocking since sendAliasAllocationSequence
          could be called in the case of processCollision)
          - This being separate has the added benefit of the
            stack being able to work in the same thread
            as the application's (or Dispatcher's)
            socket calls.
        """
        assert isinstance(self._state, CanLink.State)
        if self._state == CanLink.State.WaitForAliases:
            if self._waitingForAliasStart is None:
                self._waitingForAliasStart = default_timer()
            else:
                if ((default_timer() - self._waitingForAliasStart)
                        > CanLink.ALIAS_RESPONSE_DELAY):
                    if self.require_remote_nodes:
                        # keep the current state, in case
                        # application wants to try again.
                        raise ConnectionError(
                            "At least an LCC node was expected within 200ms."
                            " See require_remote_nodes documentation and"
                            " only set to True for Standard"
                            " (permissive) behavior")
                    # finish the sends for the alias reservation:
                    self.setState(CanLink.State.EnqueueAliasReservation)
        elif self._state == CanLink.State.RecordAliasReservation:
            self.finalizeAlias()

        return self.getState()

    def enqueueCIDSequence(self):
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
        self.link.sendCanFrame(CanFrame(7, self.localNodeID, self._localAlias))
        self.link.sendCanFrame(CanFrame(6, self.localNodeID, self._localAlias))
        self.link.sendCanFrame(CanFrame(5, self.localNodeID, self._localAlias))
        self.link.sendCanFrame(
            CanFrame(4, self.localNodeID, self._localAlias,
                     afterSendState=CanLink.State.WaitForAliases)
        )
        self._previousCollisions = self._reserveAliasCollisions
        self._previousFrameCount = self._frameCount
        self._previousLocalAliasSeed = self._localAliasSeed
        self.setState(CanLink.State.WaitingForSendCIDSequence)

    def enqueueReserveID(self):
        """Send Reserve ID (RID)
        If no collision after `CanLink.ALIAS_RESPONSE_DELAY`,
        but this will not be called in no-response case if
        `require_remote_nodes` is `True`.
        """
        self._waitingForAliasStart = None  # done waiting for reply to 7,6,5,4
        self.setState(CanLink.State.BusyLocalReserveID)
        # precise_sleep(.2)  # Waiting 200ms as per section 6.2.1
        #  is now done by pollState (application must keep polling after
        #  sending and receiving data) based on _waitingForAliasStart.

        #  See ("Reserving a Node ID Alias") of
        #  LCC "CAN Frame Transfer" Standard
        responseCount = self._frameCount - self._previousFrameCount
        if responseCount < 1:
            logger.warning(
                "sendAliasAllocationSequence may be blocking the receive"
                " thread or the network is taking too long to respond"
                " (200ms is LCC standard time for all nodes to respond to"
                " reservation request. If there any other nodes, this is"
                " an error and this method should *not* continue sending"
                " Reserve ID (RID) frame)...")
        if self._reserveAliasCollisions > self._previousCollisions:
            # processCollision will increment the non-unique alias try
            #   defineAndReserveAlias again (so stop before completing
            #   the sequence as per Standard)
            logger.warning(
                "Cancelled reservation of duplicate local alias seed {}"
                " (processCollision increments ID to avoid,"
                " & restarts sequence)."
                .format(self._previousLocalAliasSeed))
            return False
        if responseCount < 1:
            logger.warning(
                "Continuing to send Reservation (RID) anyway"
                "--no response, so assuming alias seed {} is unique"
                " (If there are any other nodes on the network then"
                " a thread, the call order, or network connection failed!)."
                .format(self._localAliasSeed))
            # precise_sleep(.2)  # wait for another collision wait term
            # responseCount = self._frameCount - previousFrameCount
            # NOTE: If we were to loop here, then we would have to
            #   trigger defineAndReserveAlias again, since
            #   processCollision usually does that, but collision didn't
            #   occur. However, stopping here would not be valid anyway
            #   since we can't know for sure we aren't the only node,
            #   and if we are the only node no responses are expected.
        self.link.sendCanFrame(
            CanFrame(ControlFrame.RID.value, self._localAlias,
                     afterSendState=CanLink.State.NotifyAliasReservation)
        )
        self.setState(CanLink.State.WaitingForSendReserveID)

    def incrementAlias48(self, oldAlias):
        '''
        Implements the OpenLCB preferred alias
        generation mechanism:  a 48-bit computation
        of x(i+1) = (2^9+1) x(i) + c
        where c = 29,741,096,258,473 or 0x1B0CA37A4BA9
        '''

        newProduct = (oldAlias << 9) + oldAlias + (0x1B_0C_A3_7A_4B_A9)
        maskedProduct = newProduct & 0xFFFF_FFFF_FFFF
        return maskedProduct

    def createAlias12(self, rnd):
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

    def decodeControlFrameFormat(self, frame):
        if (frame.header & 0x0800_0000) == 0x0800_0000:
            # data case; not checking leading 1 bit
            # NOTE: handleReceivedData can get all header bits via frame
            return ControlFrame.Data
        if (frame.header & 0x4_000_000) != 0:  # CID case
            # NOTE: handleReceivedCID can get all header bits via frame
            return ControlFrame.CID

        try:
            retval = ControlFrame((frame.header >> 12) & 0x2_FF_FF)
            return retval  # top 1 bit for out-of-band messages
        except KeyboardInterrupt:
            raise
        except:
            logger.warning(
                "Could not decode header 0x{:08X}"
                .format(frame.header))
            return ControlFrame.UnknownFormat

    def canHeaderToFullFormat(self, frame):
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
