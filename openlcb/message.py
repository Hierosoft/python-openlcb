'''
based on Message.swift
Created by Bob Jacobsen on 6/1/22.
'''
import copy
from typing import Union

from openlcb import emit_cast
from openlcb.mti import MTI
from openlcb.nodeid import NodeID


class Message:
    """basic message, with an MTI, source, destination? and data content

    Args:
        mti (MTI): Message Type Indicator.
        source (NodeID): Message source.
        destination (NodeID): Set to None for global.
        data (bytearray, optional): Data being transmitted. Defaults to
            empty bytearray().
    """

    def __init__(self, mti, source: NodeID,
                 destination: Union[NodeID, None], data=None):
        # For args, see class docstring.
        if data is None:
            data = bytearray()
        self.mti = mti
        assert isinstance(mti, MTI)
        if self.mti in (MTI.Verified_NodeID, MTI.Initialization_Complete):
            # Requires node.id in data for these MTIs (See
            #   7.3.3.1 and 7.3.3.3 in Message Network Standard)
            assert data is not None, \
                f"Expected node.id.toArray() for data of {mti}, got {data}"
        self.source = source
        self.destination = destination  # Union[NodeID, None]
        self.originalMTI = None  # type: Union[int, None]
        self.assertTypes()
        if not isinstance(data, bytearray):
            raise TypeError("Expected bytearray, got {}"
                            .format(type(data).__name__))
        self.data = data

    def copy(self) -> 'Message':
        source = None
        if self.source is not None:
            source = NodeID(self.source.value)
        destination = None
        if self.destination is not None:
            destination = NodeID(self.destination.value)
        assert source is not None
        return Message(
            self.mti,  # Enums are assigned by value not reference
            source,
            destination=destination,
            data=copy.deepcopy(self.data),  # returns copy or None
        )

    def assertTypes(self):
        assert isinstance(self.mti, MTI)
        assert isinstance(self.source, NodeID), \
            "expected NodeID, got {}".format(emit_cast(self.source))
        if self.destination is not None:
            assert isinstance(self.destination, NodeID), \
                "expected NodeID, got {}".format(emit_cast(self.destination))
        # allowed to be None. See linkUp in tcplink.py
        # TODO: Only allow in certain conditions?

    def isGlobal(self) -> bool:
        return self.mti.value & 0x0008 == 0

    def isAddressed(self) -> bool:
        return self.mti.value & 0x0008 != 0

    def __str__(self):
        return "Message ("+self.mti.name+")"

    def __eq__(lhs, rhs):
        if rhs is None:
            return False
        lhs.assertTypes()
        rhs.assertTypes()
        if rhs.mti != lhs.mti:
            return False
        if rhs.source != lhs.source:
            return False
        if rhs.destination != lhs.destination:
            return False
        if not isinstance(rhs.data, type(lhs.data)):
            raise TypeError(
                "Tried to compare a {} to a {}"
                " (expected bytearray for Message().data)"
                .format(type(lhs.data).__name__, type(rhs.data).__name__))
        if rhs.data != lhs.data:
            return False
        return True

    def __hash__(self) :
        return self.mti.__hash__() + self.source.__hash__()
