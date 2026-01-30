'''
based on LocalNodeProcessor.swift

Created by Bob Jacobsen on 6/1/22.

Process messages destined for a node implemented by this application.
'''

# This is a state-free class.  All the node-specific information is kept
# in a separate Node item that's passed in as part of the process(..) call.
# I.e. you only need to hook up one of these, even if you're implementing
# multiple local nodes.

import logging

from typing import Union

from openlcb.linklayer import LinkLayer
from openlcb.node import Node
from openlcb.mti import MTI
from openlcb.message import Message
from openlcb.processor import Processor
from openlcb.nodeid import NodeID


class LocalNodeProcessor(Processor):

    def __init__(self, linkLayer: LinkLayer, node: Node):
        self.linkLayer = linkLayer
        self.node = node

    def process(self, message: Message, givenNode: Union[Node, None] = None):
        if givenNode is None:
            node = self.node
        else:
            node = givenNode

        if not (self.checkDestID(message, node) or message.isGlobal()):
            return False  # not to us
        # specific message handling
        if message.mti == MTI.Link_Layer_Up:
            self._linkUpMessage(message, node)
        elif message.mti == MTI.Link_Layer_Down:
            self._linkDownMessage(message, node)
        elif message.mti == MTI.Verify_NodeID_Number_Global:
            self._verifyNodeIDNumberGlobal(message, node)
        elif message.mti == MTI.Verify_NodeID_Number_Addressed:
            self._verifyNodeIDNumberAddressed(message, node)
        elif message.mti == MTI.Protocol_Support_Inquiry:
            self._protocolSupportInquiry(message, node)
        elif message.mti in (MTI.Protocol_Support_Reply,
                             MTI.Simple_Node_Ident_Info_Reply):
            # these are not relevant here
            pass
        elif message.mti in (MTI.Traction_Control_Command,
                             MTI.Traction_Control_Reply):
            # these are not relevant here
            pass
        elif message.mti in (MTI.Datagram, MTI.Datagram_Rejected,
                             MTI.Datagram_Received_OK):
            # datagrams and datagram replies are handled in the
            # DatagramService
            pass
        elif message.mti == MTI.Simple_Node_Ident_Info_Request:
            self._simpleNodeIdentInfoRequest(message, node)
        elif message.mti == MTI.Identify_Events_Addressed:
            self._identifyEventsAddressed(message, node)
        elif message.mti in (MTI.Terminate_Due_To_Error,
                             MTI.Optional_Interaction_Rejected):
            self._errorMessageReceived(message, node)
        else:
            self._unrecognizedMTI(message, node)
        return False

    def _linkUpMessage(self, message: Message, node: Node):
        node.state = Node.State.Initialized
        msgIC = Message(MTI.Initialization_Complete, node.id,
                        None, node.id.toArray())
        self.linkLayer.sendMessage(msgIC)
        # ask all nodes to identify themselves
        # msgVN = Message( MTI.Verify_NodeID_Number_Global,  node.id)
        # self.linkLayer.sendMessage(msgVN)

    def _linkDownMessage(self, message: Message, node: Node):
        node.state = Node.State.Uninitialized

    def _verifyNodeIDNumberGlobal(self, message: Message, node: Node):
        if not (len(message.data) == 0 or node.id == NodeID(message.data)):
            return  # not to us
        msg = Message(MTI.Verified_NodeID, node.id, message.source,
                      node.id.toArray())
        self.linkLayer.sendMessage(msg)

    def _verifyNodeIDNumberAddressed(self, message: Message, node: Node):
        msg = Message(MTI.Verified_NodeID,  node.id, message.source,
                      node.id.toArray())
        self.linkLayer.sendMessage(msg)

    def _protocolSupportInquiry(self, message: Message, node: Node):
        pips = 0
        for pip in node.pipSet:
            pips |= pip.value
        part1 = ((pips >> 24) & 0xFF)
        part2 = ((pips >> 16) & 0xFF)
        part3 = ((pips >> 8) & 0xFF)
        retval = bytearray(
            [part1, part2, part3, 0, 0, 0])  # JMRI wants to see 6 bytes

        msg = Message(MTI.Protocol_Support_Reply, node.id,  message.source,
                      retval)
        self.linkLayer.sendMessage(msg)

    def _simpleNodeIdentInfoRequest(self, message: Message, node: Node):
        msg = Message(MTI.Simple_Node_Ident_Info_Reply, node.id,
                      message.source, node.snip.returnStrings())
        self.linkLayer.sendMessage(msg)

    def _identifyEventsAddressed(self, message: Message, node: Node):
        '''EventProtocol in PIP, but no Events here to reply about;
        no reply necessary
        '''
        return

    def _unrecognizedMTI(self, message: Message, node: Node):
        '''Handle a message with an unrecognized MTI
        by returning OptionalInteractionRejected
        '''

        # special case of unknown MTI from lower level
        unknownAddressed = False
        originalMTI = 0xFFFF
        if message.mti == MTI.Unknown :
            if message.originalMTI is not None:
                originalMTI = message.originalMTI
            else :
                logging.error("MTI.Unknown without originalMTI")
            unknownAddressed = (originalMTI & 0x008 ) != 0
        if not (message.mti.addressPresent() or unknownAddressed) :
            return  # unrecognized global messages are ignored

        # addressed messages get an OptionalInteractionRejected
        logging.info("received unexpected {}, send OIR".format(message))
        msg = Message(MTI.Optional_Interaction_Rejected,  node.id,
                      message.source,
                      bytearray([0x10, 0x43, ((originalMTI >> 8) & 0xFF),
                                 (originalMTI & 0xFF)]))  # permanent error
        self.linkLayer.sendMessage(msg)

    def _errorMessageReceived(self, message: Message, node: Node):
        # these are just logged until we have more complex interactions
        logging.info("received unexpected {}".format(message))
