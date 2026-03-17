import openlcb

from collections import OrderedDict
from logging import getLogger
from typing import Any, Union

from openlcb import (
    emit_cast,
    list_type_names,
)
from openlcb.canbus.controlframe import ControlFrame
from openlcb.nodeid import NodeID

logger = getLogger(__name__)


class NoEncoder:
    def encodeFrameAsString(self, _) -> str:
        raise AssertionError(
            "You must set encoder on frame to a PhysicalLayer instance"
            " or class that has an encodeFrameAsString method that accepts"
            " a single CanFrame argument (Example in canFrameSend"
            " method of CanPhysicalLayerGridConnect:"
            " frame.encoder = self).")


class CanFrame:
    """OpenLCB-CAN frame
    Use CAN extended format (29-bit header)
    - However, operate error-free when network carries standard-format
      (11-bit header) frames.
    - Bit 28 of header is always sent as 1 and ignored upon receipt
       NOTE: 0x10_00_00_00 is bit 28 in hex.
    - See the "OpenLCB-CAN Frame Transfer" standard on openlcb.org for
      more details.

    Constructor arguments are manually overloaded as follows:
    - N_cid, nodeID, alias: If 2nd arg is NodeID.
    - header, data: If 2nd arg is list.
    - control, alias, data: If 2nd arg is int.

    Attributes:
        encoder (object): A required (in non-test scenarios) encoder
            object (set to a PhysicalLayer subclass, since that layer
            determines the encoding). Must implement FrameEncoder.

    Args:
        N_cid (int, optional): Frame sequence number (becomes first
            3 bits of 15-bit Check ID (CID) frame). 4 to 7 inclusive
            (for non-OpenLCB protocols, down to 1). See
            "OpenLCB-CAN Frame Transfer" standard or comments under
            "nodeCode" for how this affects nodeID bit field size.
        nodeID (NodeID, optional): (becomes last 12 bits at right
            side of Check ID (CID) frame, but which bits are used
            depends upon N_cid).
        alias (int, optional): Source NID Alias. A 12-bit version of the
            nodeID shortened using bitwise overlays, used as a local key
            for the device. See calls to createAlias12.
        header (int, optional): The entire 29-bit header already
            assembled (or received).
        data (list[int], optional): Payload
        control (int, optional): Frame type (1: OpenLCB = 0x0800_000,
            0: CAN Control Frame) | Content Field (3 bits, 3 nibbles,
            mask = 0x07FF_F000).
        afterSendState (CanLink.State, optional): The frame incurs
            a new state in the CanLink instance *after* socket send is
            *complete*, at which time the PortInterface should call
            setState(frame.afterSendState).
        reservation (int): The reservation sequence attempt (incremented
            on each attempt) to allow clearReservation to work (cancel
            previous reservation without race condition related to
            _send_frames).
    """

    ARG_LISTS = [
        OrderedDict(N_cid=int, nodeID=NodeID, alias=int),
        OrderedDict(header=int, data=bytearray),
        OrderedDict(control=int, alias=int, data=bytearray),
    ]

    @staticmethod
    def constructor_help():
        result = ""
        for d in CanFrame.ARG_LISTS:
            result += "("
            for k, v in d.items():
                result += "{}: {}, ".format(k, v.__name__)
            result = result[:-2]  # remove last ", " from this ctor
            result += "), "
        return result[:-2]  # -1 to remove last ", " from list

    @staticmethod
    def decodeControlFrameFormat(frame) -> ControlFrame:
        # type: (CanFrame) -> ControlFrame
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

    def __str__(self):
        return "CanFrame header: 0x{:08X} {}".format(
            self.header,
            list(self.data),  # cast to list to format bytearray(b'') as []
        )

    def encodeAsString(self) -> str:
        return self.encoder.encodeFrameAsString(self)

    def encodeAsBytes(self) -> bytes:
        return self.encodeAsString().encode("utf-8")

    @property
    def alias(self) -> int:
        return self._alias

    def __init__(self, *args, afterSendState=None, reservation=None,
                 minimumState=None):
        self.afterSendState = afterSendState
        self.encoder = NoEncoder()  # type: Any
        self.reservation = reservation
        self.minimumState = minimumState
        arg1 = None
        arg2 = None
        arg3 = None
        self._alias = None  # type: Union[int, None]  # TODO: type: int ?
        if len(args) > 0:
            arg1 = args[0]
        if len(args) > 1:
            arg2 = args[1]
        if len(args) > 2:
            arg3 = args[2]
        else:
            arg3 = bytearray()
        # There are three ctor forms.
        # - See "Args" in class for docstring.
        self.header = 0  # type: int
        self.direction = None  # See deque for usage
        self.data = bytearray()
        # three arguments as N_cid, nodeID, alias
        args_error = None
        alias_warning_case = None
        if isinstance(arg2, NodeID):
            # Other args' types will be enforced by doing math on them
            #   (duck typing) in this case.
            if len(args) < 3:
                args_error = "Expected alias after NodeID"
            assert isinstance(arg3, int), \
                ("Expected int alias after NodeID, got"
                 f" {emit_cast(arg3)}")
            # cid must be 4 to 7 inclusive (100 to 111 binary)
            # precondition(4 <= cid && cid <= 7)
            nodeID = arg2
            self._alias = arg3
            if not isinstance(arg1, int):
                args_error = \
                    ("Expected CID 4 to 7 if arg2 is NodeID,"
                     f" got {emit_cast(arg1)}")
            else:
                cid = arg1

                nodeCode = ((nodeID.value >> ((cid-4)*12)) & 0xFFF)
                # ^ cid-4 results in 0 to 3. *12 results in 0 to 36 bit shift (nodeID size)  # noqa: E501
                self.header = ((cid << 12) | nodeCode) << 12 | (self._alias & 0xFFF) | 0x10_00_00_00  # noqa: E501
                # self.data = bytearray()

        # two arguments as header, data
        elif isinstance(arg2, bytearray):
            # TODO: decode (header?) if self._alias is necessary in this case,
            #   otherwise is remains None!
            if not isinstance(arg1, int):
                args_error = \
                    "Expected int(header) since 2nd argument is bytearray."
            # Types of both args are enforced by this point.
            self.header = arg1  # type: ignore
            self._alias = arg1 & 0xFFF  # type: ignore
            if self._alias == 0:
                logger.warning("Alias is {}".format(self._alias))
            self.data = arg2
            if len(args) > 2:
                args_error = "2nd argument is data, but got extra argument(s)"
            alias_warning_case = "bytearray overload of constructor"

        # two arguments as header, data
        elif isinstance(arg2, list):
            args_error = ("Expected bytearray (formerly list[int])"
                          " if data 2nd argument")
            # self.header = arg1
            # self.data = bytearray(arg2)

        # three arguments as control, alias, data
        elif isinstance(arg2, int):
            # Types of all 3 are enforced by usage (duck typing) in this case.
            control = arg1  # type: int # type: ignore
            self._alias = arg2
            self.header = \
                (control << 12) | (self._alias & 0xFFF) | 0x10_00_00_00
            if not isinstance(arg3, bytearray):
                args_error = ("Expected bytearray (formerly list[int])"
                              " 2nd if 1st argument is header int")
            self.data = arg3
        else:
            args_error = "could not decode CanFrame arguments"

        if args_error:
            raise TypeError(
                "{}. Valid constructors: {}. Got: {}".format(
                    args_error.rstrip("."),
                    CanFrame.constructor_help(),
                    list_type_names(args)))
        if self._alias is not None:
            if self._alias & 0xFFF != self._alias:
                raise ValueError(
                    "Alias overflow: {} > 0xFFF".format(self._alias))
        else:
            if not alias_warning_case:
                alias_warning_case = "untracked constructor case"
            logger.info(
                "[CanFrame] Alias set/decode is not implemented in {}"
                .format(alias_warning_case))

    def __eq__(self, other):
        if other is None:
            return False

        if self.header != other.header:
            return False
        if self.data != other.data:
            return False
        return True

    def difference(self, other):
        if other is None:
            return "other is None"
        if self.header != other.header:
            return "header {} != {}".format(self.header, other.header)
        if self.data != other.data:
            return "data {} != {}".format(self.data, other.data)
        return None