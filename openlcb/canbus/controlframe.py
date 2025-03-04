"""
An Enum representing the various kinds of CAN control frames.
These are link-layer concepts, so are here instead of CanFrame.
"""

from enum import Enum


class ControlFrame(Enum):
    """Link-layer control frame values for OpenLCB/LCC.

    These values represent control frames used in the Layout Command
    Control (LCC) and OpenLCB link layer. They define specific types of
    link-layer interactions, including address management, error
    indications, and internal signaling.

    Attributes:
        RID (int): Reserve ID (RID) frame, used for alias reservation.
        AMD (int): Alias Map Definition (AMD) frame, used to define a
            mapping between an alias and a full Node ID.
        AME (int): Alias Mapping Enquiry (AME) frame, used to request
            alias information from other nodes.
        AMR (int): Alias Map Reset (AMR) frame, used to reset alias
            mappings.
        EIR0 (int): Error Information Report 0, emitted when a node
            transitions from the "Error Active" state to the "Error
            Passive" state.
        EIR1 (int): Error Information Report 1, emitted when a node
            transitions from the "Bus Off" state to the "Error Passive"
            state.
        EIR2 (int): Error Information Report 2, emitted when a node
            transitions from the "Error Passive" state to the "Error
            Active" state.
        EIR3 (int): Error Information Report 3, emitted when a node
            transitions from the "Bus Off" state to the "Error Active"
            state.

        CID (int): Check ID (CID) frame, used to verify Node ID
            uniqueness. Only the upper bits are specified; additional
            arguments are encoded in the lower bits.
            See CAN Frame Transfer - Standard for details.
        Data (int): Data frame. Only the upper bits are specified;
            additional arguments are encoded in the lower bits.

        LinkUp (int): Internal signal indicating that the link has been
            established. Non-OpenLCB value.
        LinkRestarted (int): Internal signal indicating that the link has been
            restarted. Non-OpenLCB value.
        LinkCollision (int): Internal signal indicating that a link collision
            has been detected. Non-OpenLCB value.
        LinkError (int): Internal signal indicating that a link error has
            occurred. Non-OpenLCB value.
        LinkDown (int): Internal signal indicating that the link has gone down.
            Non-OpenLCB value.
        UnknownFormat (int): Internal signal indicating that an unknown frame
            format has been received. Non-OpenLCB value.
    """
    RID = 0x0700
    AMD = 0x0701
    AME = 0x0702
    AMR = 0x0703
    EIR0 = 0x00710
    EIR1 = 0x00711
    EIR2 = 0x00712
    EIR3 = 0x00713

    # note these two don't code the entire control field value (i.e. there are
    # arguments in the lower bits)
    CID  =  0x4000
    Data = 0x18000

    # these are non-openlcb values used for internal signaling
    # their values have a bit set above what can come from a CAN Frame
    LinkUp         = 0x20000
    LinkRestarted  = 0x20001
    LinkCollision  = 0x20002
    LinkError      = 0x20003
    LinkDown       = 0x20004
    UnknownFormat  = 0x21000
