'''
based on MemoryService.swift

Created by Bob Jacobsen on 6/1/22.

TODO: Read requests are serialized, but write requests are not yet

Datagram retry handles the link being quiesced/restarted, so it's not
explicitly handled here.

Does memory read and write requests.

Reads and writes are limited to 64 bytes at a time.

To do memory write:
- Create a ``MemoryWriteMemo`` and submit via ``requestMemoryWrite(_:)``
- Wait for either okReply or rejectedReply call back.

To do memory read:
- Create a ``MemoryReadMemo`` and submit via ``requestMemoryRead(_:)``
- Wait for either dataReply or rejectedReply call back.
'''

from enum import Enum
from logging import getLogger
from typing import (
    Callable,
    List,  # in case list doesn't support `[` in this Python version
    Union,  # in case `|` doesn't support 'type' in this Python version
)

from openlcb.datagramservice import (
    # DatagramReadMemo,
    DatagramReadMemo,
    DatagramWriteMemo,
    DatagramService,
)
from openlcb.convert import Convert

logger = getLogger(__name__)


class MemorySpace(Enum):
    """The memory space to read.
    In practice, XMLDataProcessor (or a non-XML parser if necessary)
    uses this to track what data type and format is to be assumed in a
    received Message. It is assumed to have the same space as the
    request (MemoryReadMemo).
    - A datagram's `space` attribute's type should be `int` not
      MemorySpace, because CDI specifies variables' space arbitrarily.

    Attributes:
        Uninitialized: No data (memory read request response) is expected.
        CDI: The data expected from the memory read is CDI XML.
        FDI: The data expected from the memory read is FDI XML.
        All: All memory of the device, where all is defined by its designer
            (See OpenLCB Memory Configuration Standard 4.2).
        Configuration: A writeable basic configuration space, with
            the structure of the 32-bit space defined by the designer
            (See OpenLCB Memory Configuration Standard 4.2).
    """
    Uninitialized = -1
    CDI = 0xFF  # decodes to 0x03
    FDI = 0xFA
    All = 0xFE
    Configuration = 0xFD

    @classmethod
    def fromNumber(cls, num: int):
        """Return the MemorySpace member with the given numeric value,
        or None if no match is found.
        """
        assert isinstance(num, int)
        for member in cls:
            if member.value == num:
                return member
        return None


class MemoryReadMemo:
    """Memo carries request and reply.

    Args:
        nodeID (NodeID): Remote node id (where to read).
        size (int): Size of the data to be read, typically in bytes.
        space (int): Encoded memory space identifier, where values:
            - 0xFF to 0xFD are special spaces, and only the least significant
              2 bits are relevant.
              - 0xFF is CDI (decodes to 0x03)
            - 0x00 to 0xFC represent standard memory spaces directly.
              - 0xFA is FDI
        address (int): The address in memory where the read operation
            should be performed.
        rejectedReply (Callable[MemoryReadMemo]): Callback function to handle
            rejected read responses.
            The callback will receive this MemoryReadMemo instance.
        dataReply (Callable[MemoryReadMemo]): Callback function to
            handle successful read responses (called after okReply which
            is handled by MemoryService). The callback will receive the
            data read from memory. This is passed as a MemoryReadMemo
            object with the data member set.

    Attributes:
        data(bytearray): The data that was read.
    """
    def __init__(self, nodeID, size, space, address, rejectedReply, dataReply):
        # For args see class docstring.
        self.nodeID = nodeID
        self.size = size
        self.space = space
        self.address = address
        self.rejectedReply = rejectedReply
        self.dataReply = dataReply
        # for convenience, data can be added or updated after creation of the
        # memo
        self.data = bytearray()


class MemoryWriteMemo:
    """A memory write request within an OpenLCB network.
    Args:
        nodeID (NodeID): Remote node id (where to write).
        okReply (Callable): Callback function to handle successful write
            responses. The callback receives this MemoryWriteMemo instance.
        rejectedReply (Callable): Callback function to handle rejected
            write responses. The callback receives this MemoryWriteMemo
            instance.
        size (int): Size of the data to be written in bytes.
        space (int): Encoded memory space identifier, where values:
            - 0xFF to 0xFD are special spaces, and only the least significant
              2 bits are relevant.
            - 0x00 to 0xFC represent standard memory spaces directly.
        address (int): The address in memory where the data should be
            written.
        data (bytes): The actual data to be written to the specified
            memory address.
    """

    def __init__(self, nodeID, okReply, rejectedReply, size, space, address,
                 data):
        # For args see class docstring.
        self.nodeID = nodeID
        self.okReply = okReply
        self.rejectedReply = rejectedReply
        self.size = size  # max 64 bytes
        self.space = space
        self.address = address
        self.data = data


class MemoryService:
    """Manage memory read and write requests
    (64 bytes at a time).

    Args:
        service (DatagramService): See DatagramService.
    """

    def __init__(self, service: DatagramService):
        self.service: DatagramService = service
        self.readMemos: List[MemoryReadMemo] = []
        self.writeMemos: List[MemoryWriteMemo] = []
        self.spaceLengthCallback: Union[Callable[[int], None], None] = None

        # register to DatagramService to hear arriving datagrams
        self.service.registerDatagramReceivedListener(
            self.datagramReceivedListener
        )

    def requestMemoryRead(self, memo):
        # type: (MemoryReadMemo) -> None
        '''Request a read operation start.

        - If okReply in the memo is triggered, it will be followed by a
          dataReply.

        - A rejectedReply will not be followed by a dataReply.

        Args:
            memo (MemoryReadMemo): Request to enqueue.
        '''
        # preserve the request
        self.readMemos.append(memo)

        if len(self.readMemos) == 1:
            self.requestMemoryReadNext(memo)

    def requestMemoryReadNext(self, memo):
        # type: (MemoryReadMemo) -> None
        """send the read request

        Args:
            memo (MemoryReadMemo): Request to send.
        """
        byte6 = False
        flag = 0
        (byte6, flag) = Convert.spaceDecode(memo.space)
        spaceFlag = 0x40 if byte6 else (flag | 0x40)
        addr2 = ((memo.address >> 24) & 0xFF)
        addr3 = ((memo.address >> 16) & 0xFF)
        addr4 = ((memo.address >> 8) & 0xFF)
        addr5 = (memo.address & 0xFF)
        data = bytearray([
            DatagramService.ProtocolID.MemoryOperation.value, spaceFlag,
            addr2, addr3, addr4, addr5])
        # NOTE: list[int] is ok for bytearray extend (`+` requires cast)
        if byte6:
            data.extend([(memo.space & 0xFF)])
        data.extend([memo.size])
        logger.debug(
            "[requestMemoryReadNext] creating DatagramWriteMemo"
            f" to destID={memo.nodeID} with data={list(data)}")
        dgWriteMemo = DatagramWriteMemo(memo.nodeID, data,
                                        self.receivedOkReplyToWrite)
        self.service.sendDatagram(dgWriteMemo)

    def receivedOkReplyToWrite(self, memo: Union[DatagramWriteMemo, None]):
        '''Wait for following response to be returned via listener.
        This is normal.
        '''
        pass

    def datagramReceivedListener(self, dmemo: DatagramReadMemo) -> bool:
        '''Process a datagram.

        Sends the positive reply and returns true if this is from our service.
        '''
        # node received a datagram, is it our service?
        if self.service.datagramType(dmemo.data) \
                != DatagramService.ProtocolID.MemoryOperation :
            return False

        # datagram must has a command value
        if len(dmemo.data) < 2:
            logger.error("Memory service datagram too short: {}"
                         .format(dmemo.data.count))
            # TODO: ^ more necessary to show same output as Swift? Formerly:
            #   " \(dmemo.data.count, privacy: .public)")
            self.service.negativeReplyToDatagram(dmemo, 0x1041)
            return True  # error, but for our service; sent negative reply
        # Acknowledge the datagram
        self.service.positiveReplyToDatagram(dmemo, 0x0000)

        # decode if read, write or some other reply
        if dmemo.data[1] in (0x50, 0x51, 0x52, 0x53, 0x58, 0x59, 0x5A, 0x5B):
            # read or read-error reply

            # return data to requestor: first find matching memory read
            # memo, then reply
            for index in range(0, len(self.readMemos)):
                if self.readMemos[index].nodeID == dmemo.srcID:
                    tMemoryMemo = self.readMemos[index]  # type: MemoryReadMemo
                    del self.readMemos[index]
                    # decode type of operation, hence offset for start of
                    # data
                    offset = 6
                    if dmemo.data[1] == 0x50 or dmemo.data[1] == 0x58:
                        offset = 7

                    # are there any additional requests queued to send?
                    if len(self.readMemos) > 0:
                        self.requestMemoryReadNext(self.readMemos[0])

                    # fill data for call-back to requestor
                    if len(dmemo.data) > offset:
                        tMemoryMemo.data = dmemo.data[offset:]
                        logger.debug(
                            f"[datagramReceivedListener] got read reply"
                            f" data={list(tMemoryMemo.data)} offset={offset}"
                            f", requested @{tMemoryMemo.address}")

                    # check for read or read error reply
                    if (dmemo.data[1] & 0x08 == 0):
                        tMemoryMemo.dataReply(tMemoryMemo)
                    else:
                        tMemoryMemo.rejectedReply(tMemoryMemo)
                    break
        elif dmemo.data[1] in (0x10, 0x11, 0x12, 0x13, 0x18, 0x19, 0x1A, 0x1B):
            # write reply good, bad

            # return data to requestor: first find matching memory write
            # memo, then reply
            for index in range(0, len(self.writeMemos)):
                if self.writeMemos[index].nodeID == dmemo.srcID:
                    writeMemo = self.writeMemos[index]  # type: MemoryWriteMemo
                    del self.writeMemos[index]
                    if dmemo.data[1] & 0x08 == 0 :
                        writeMemo.okReply(writeMemo)
                    else:
                        writeMemo.rejectedReply(writeMemo)
                    break
        elif dmemo.data[1] in (0x86, 0x87):  # Address Space Information Reply
            if self.spaceLengthCallback is None:
                logger.error("Address Space Information Reply"
                             " received with no callback")
                return True
            if dmemo.data[1] == 0x86:
                # not present
                self.spaceLengthCallback(-1)
                self.spaceLengthCallback = None
                return True
            # normal reply
            address = ((int(dmemo.data[3]) << 24)
                       + (int(dmemo.data[4]) << 16)
                       + (int(dmemo.data[5]) << 8)
                       + int(dmemo.data[6]))
            self.spaceLengthCallback(address)
            self.spaceLengthCallback = None
        else:
            logger.error("Did not expect reply of type 0x{:02X}"
                         .format(dmemo.data[1]))

        return True

    def requestMemoryWrite(self, memo: MemoryWriteMemo):
        """Request memory write.

        Args:
            memo (MemoryWriteMemo): information to send
        """
        # preserve the request
        self.writeMemos.append(memo)
        # create & send a write datagram
        byte6 = False
        flag = 0
        (byte6, flag) = Convert.spaceDecode(memo.space)
        spaceFlag = 0x00 if byte6 else (flag | 0x00)
        addr2 = ((memo.address >> 24) & 0xFF)
        addr3 = ((memo.address >> 16) & 0xFF)
        addr4 = ((memo.address >> 8) & 0xFF)
        addr5 = (memo.address & 0xFF)
        data = bytearray([
            DatagramService.ProtocolID.MemoryOperation.value, spaceFlag,
            addr2, addr3, addr4, addr5
        ])
        if byte6:
            data.extend([(memo.space & 0xFF)])
        data.extend(memo.data)
        dgWriteMemo = DatagramWriteMemo(memo.nodeID, data)
        self.service.sendDatagram(dgWriteMemo)

    def requestSpaceLength(self, space: int, nodeID: NodeID,
                           callback: Callable[[int], None]):
        '''Request the length of a specific memory space from a remote node.

        Args:
            space (int): Encoded memory space identifier. This can be a
                value within a specific range, as defined in the
                `spaceDecode` method.
            nodeID (NodeID): ID of remote node from which the memory
                space length is requested.
            callback (Callable): Callback function that will receive the
                response. The callback will receive an integer address
                as a parameter, representing the address of the
                requested memory space or -1 if not present.

        Returns:
            None
        '''
        if self.spaceLengthCallback is not None:
            logger.error("Overlapping calls to requestSpaceLength")
            return
        self.spaceLengthCallback = callback
        # send request
        dgReqMemo = DatagramWriteMemo(
            nodeID,
            bytearray([
                DatagramService.ProtocolID.MemoryOperation.value,
                0x84,
                space
            ])
        )
        self.service.sendDatagram(dgReqMemo)
