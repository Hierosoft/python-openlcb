'''
based on Message.swift
Created by Bob Jacobsen on 6/1/22.
'''


from openlcb import emit_cast
from openlcb.mti import MTI
from openlcb.node import Node
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

    def __init__(self, mti, source: NodeID, destination: NodeID, data=None):
        # For args, see class docstring.
        if data is None:
            data = bytearray()
        self.mti = mti
        self.source = source
        self.destination = destination
        self.assertTypes()
        if not isinstance(data, bytearray):
            raise TypeError("Expected bytearray, got {}"
                            .format(type(data).__name__))
        self.data = data

    def assertTypes(self):
        assert isinstance(self.mti, MTI)
        assert isinstance(self.source, NodeID), \
            "expected NodeID, got {}".format(emit_cast(self.source))
        if self.destination is not None:
            assert isinstance(self.destination, NodeID), \
                "expected NodeID, got {}".format(emit_cast(self.destination))
        # allowed to be None. See linkUp in tcplink.py
        # TODO: Only allow in certain conditions?

    def isGlobal(self):
        return self.mti.value & 0x0008 == 0

    def isAddressed(self):
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
