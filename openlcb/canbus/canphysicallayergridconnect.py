'''
based on CanPhysicalLayerGridConnect.swift

Created by Bob Jacobsen on 6/14/22.

Provide a CanPhysicalLayer for GridConnect format strings.

Works with frames like
- :X19490365N;
- :X19170365N020112FE056C;
'''


import struct
import sys

from logging import getLogger
from typing import Tuple, Union

from openlcb import from_hex_bytes, only_hex_pairs
from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.canbus.canframe import CanFrame
from openlcb.frameencoder import FrameEncoder
from openlcb.portinterface import PortInterface

logger = getLogger(__name__)


GC_START_BYTE = 0x3a  # :
GC_END_BYTE = 0x3b  # ;


class CanPhysicalLayerGridConnect(CanPhysicalLayer, FrameEncoder):
    """CAN physical layer subclass for GridConnect

    This acts as frame.encoder for canLink, and manages the packet
    _send_frames queue (deque is used for speed; defined & managed in base
    class: PhysicalLayer)

    Attributes:
        assertValidData (bool): Raise assertion error if characters
            other than 0-F are in a GirdConnect packet (not including
            non-data tokens).
    """
    # deprecated:
    # Args:
    #     callback (Callable): A string send method for the platform and
    #         hardware being used. It must be associated with an active
    #         connection before used as the arg, and must raise exception
    #         on failure so that sendAliasAllocationSequence is
    #         interrupted in order to prevent canlink.state from
    #         proceeding to CanLink.State.Permitted)
    def __init__(self):
        # ^ A CanLink requires a physical layer to operate,
        #   so CanLink now requires a PhysicalLayer instance
        #   such as this in its constructor.
        CanPhysicalLayer.__init__(self)  # creates self._send_frames
        self.assertValidData = False
        # region moved to CanLink constructor
        # from canLink.linkPhysicalLayer(self)  # self.setCallBack(callback):
        # canLink.physicalLayer = self
        # self.registerFrameReceivedListener(canLink.handleFrameReceived)
        # endregion moved to CanLink constructor

        self.inboundBuffer = bytearray()

    # def setCallBack(self, callback):
    #     assert callable(callback)
    #     self.canSendCallback = callback

    def encodeFrameAsString(self, frame: CanFrame) -> str:
        '''Encode frame to string.'''
        output = ":X{:08X}N".format(frame.header)  # at least 8 chars, hex
        for byte in frame.data:
            output += "{:02X}".format(byte)  # at least 2 chars, hex
        output += ";\n"
        return output

    def encodeFrameAsData(self, frame: CanFrame) -> Union[bytearray, bytes]:
        # TODO: Consider doing this manually (in Python 3,
        #   bytes/bytearray has no attribute 'format')
        return self.encodeFrameAsString(frame).encode("utf-8")

    def receiveAll(self, device: PortInterface, verbose=False) -> int:
        """Receive all data on the given device.
        Args:
            device (PortInterface): Device which *must* be in
                non-blocking mode (otherwise necessary two-way
                communication such as alias reservation cannot occur).
            verbose (bool, optional): If True, print each full packet.

        Returns:
            int: number of bytes received
        """
        count = 0
        try:
            data = device.receive()  # If timeout, set non-blocking
            if data is None:
                return count
            _ = self.handleData(data, verbose=verbose)
            count += len(data)
        except BlockingIOError:
            # raised by receive if no data (non-blocking is
            #   what we want, so fall through).
            pass
        return count

    def sendAll(self, device: PortInterface, mode="binary",
                verbose=False) -> int:
        """Send all queued frames using the given device.

        Args:
            device (PortInterface): A Serial or Socket device
                implementation of PortInterface so as to provide a send
                method (Since usually Socket has send & sendString but
                Serial has write).
            mode (str, optional): "binary" (use device.send) or "text"
                (use device.sendString). Defaults to "binary".
            verbose (bool, optional): Print each packet sent (not
                recommend for numerous read requests such as CDI/FDI).
                Defaults to False.

        Returns:
            int: The count of frames sent. If 0, None were queued by
                sendFrameAfter (or internal python-openlcb methods which
                call it) since the queue was created or since the last
                time all frames were polled.
        """
        assert mode in ("binary", "text")
        if self.linkLayer:
            self.linkLayer.pollState()  # Advance delayed state(s) if necessary
            #  (done first since may enqueue frames).
        count = 0
        try:
            while True:
                frame: CanFrame = self._send_frames.popleft()
                # ^ exits loop with IndexError when done.
                # (otherwise use pollFrame() and break if None)
                if self.linkLayer:
                    blockedMsg = self.linkLayer.blockedReason(frame)
                    if blockedMsg:
                        print("Skipping sending frame: {}".format(blockedMsg))
                if mode == "binary":
                    data = self.encodeFrameAsData(frame)
                    device.send(data)
                else:
                    data = self.encodeFrameAsString(frame)
                    device.sendString(data)
                self.onFrameSent(frame)  # Calls setState if necessary
                #   (if frame.afterSendState is not None).
                if verbose:
                    print("- SENT: {}".format(data))
                count += 1
        except IndexError:
            # nothing more to do (queue is empty)
            pass
        return count

    def handleDataString(self, string: str) -> int:
        '''Provide string from the outside link to be parsed

        Args:
            string (str): A new UTF-8 string from outside link

        Returns:
            int: The number of frames completed by inboundBuffer+string.
        '''
        # formerly pushString formerly receiveString
        return self.handleData(string.encode("utf-8"))

    @classmethod
    def nextPacketRange(cls, data: Union[bytes, bytearray],
                        start: int = 0) -> Union[Tuple[int, int],
                                                 Tuple[None, None]]:
        """Get the packet slice if any.
        Returns:
            tuple(int, int): Position of ':' and position *after* ';' or
                ';\n' otherwise (None,None).
        """
        firstI = data.find(GC_START_BYTE, start)
        if firstI < 0:
            return None, None
        lastI = data.find(GC_END_BYTE, firstI+1)
        if lastI < 0:
            return None, None
        if (len(data) > lastI + 1) and (data[lastI+1] == 0x0a):
            # Collect the newline as well
            lastI += 1
        return (firstI, lastI+1)

    @classmethod
    def nextPacket(cls, data: Union[bytes, bytearray]) -> Union[bytearray,
                                                                bytes, None]:
        """Get the packet including ':' and ';'."""
        start, end = cls.nextPacketRange(data)
        if start is None:
            return None
        return data[start:end]

    @staticmethod
    def readInt32(data, start):
        # chunk = data[start:start+8]
        # return (int.from_bytes(chunk, 'big') - 0x30303030 +
        #         ((chunk & 0x40404040) >> 6) * 9)
        """Fast hex bytearray → 32-bit int (8 hex chars, ASCII)"""
        # branchless conversion for uppercase/lowercase or digits:
        # - (data[i] & 15): Gives the low 4 bits (0-9 for digits
        #   '0'-'9', or 1-6 for 'A'-'F'/'a'-'f').
        # - ((data[i] >> 6) & 1): Detects letters—0 for digits (ASCII
        #   48-57), 1 for uppercase/lowercase letters (ASCII 65-70 or
        #   97-102).
        # - * 9: Adds an extra 9 only for letters (e.g., 'A' low bits=1
        #     → 1+9=10; 'F'=6 → 6+9=15). This avoids if/else branches
        #     for better performance in tight loops.
        v = 0
        for i in range(start, start+8):
            v = (v << 4) + (data[i] & 15) + ((data[i] >> 6) & 1) * 9
        return v

    def handleDataOptimized(self, data: Union[bytes, bytearray],
                            test_output=None, verbose=False) -> int:
        """Provide characters from the outside link to be parsed

        Args:
            data (Union[bytes,bytearray]): new data from outside link
            test_output (list, optional): List-like object to hold
                resulting frames--for testing only (In normal operation,
                this method only uses self.fireFrameReceived(cf) to
                queue frames).
            verbose (bool, optional): If True, print each frame
                detected.

        Returns:
            int: The number of frames completed by inboundBuffer+data.
        """
        # This is the old version of the handleData method without
        #   specific integrity checks & messages.
        frameCount = 0
        self.inboundBuffer += data
        lastByte = 0  # last index is at ';'

        if GC_END_BYTE in self.inboundBuffer:
            #  ^ ';' ends message so we have at least one (CR/LF not required)
            # found end, now find start of that same message, earlier in buffer
            for index in range(0, len(self.inboundBuffer)):
                outData = bytearray()
                if GC_END_BYTE not in self.inboundBuffer[index:]:
                    break
                if self.inboundBuffer[index] == 0x3A:  # ':' starts message
                    # now start to accumulate data from entire message
                    header = 0
                    for offset in range(2, 9+1):  # skip first 2 bytes (":X")
                        nextChar = (self.inboundBuffer[index+offset])
                        nextByte = (nextChar & 0xF)+9 if nextChar > 0x39 else nextChar & 0xF  # noqa: E501
                        header = (header << 4)+nextByte
                    # offset 10 is N
                    # offset 11 might be data, might be ;
                    lastByte = index+11
                    for dataItem in range(0, 8):
                        if self.inboundBuffer[index+11+2*dataItem] == GC_END_BYTE:  # noqa: E501
                            break
                        # two characters are data
                        byte1 = self.inboundBuffer[index+11+2*dataItem]
                        # Convert from UTF-8 to ordinal (0x39 is
                        #   "9", so assume UTF-8 code higher than 39 is
                        #   "A"-"F" [NOTE: "a"="f" would also work due
                        #   to `& 0xF` but are N/A in GridConnect]):
                        #   - 0x30-0x39 & 0xF yields 0-9
                        #   - 0x41-0x46 or 0x61-0x66 & 0xF + 9 yields 10-15
                        part1 = (byte1 & 0xF)+9 if byte1 > 0x39 else byte1 & 0xF  # noqa: E501
                        byte2 = self.inboundBuffer[index+11+2*dataItem+1]
                        part2 = (byte2 & 0xF)+9 if byte2 > 0x39 else byte2 & 0xF  # noqa: E501
                        high_nibble = part1 << 4
                        # if part1 > 0xF:  # can't fit > 0b1111 in nibble
                        #     # possible overflow caused by +9 above
                        #     #   (but should only happen on bad packet)?
                        #     #   Commented since not sure if ok
                        #     raise ValueError(
                        #         "Got {} for high nibble (part1 << 4 == {})."
                        #         .format(part1, high_nibble))
                        outData += bytearray([high_nibble | part2])
                        lastByte += 2
                    # lastByte is index of ; in this message

                    cf = CanFrame(header, outData)
                    if test_output is not None:
                        test_output.add(cf)
                    frameCount += 1
                    self.fireFrameReceived(cf)
                    if verbose:
                        print("- RECV {}".format(
                            self.inboundBuffer[index:lastByte+1].strip()))

            # shorten buffer by removing the processed message
            self.inboundBuffer = self.inboundBuffer[lastByte:]
        return frameCount

    def handleData(self, data: Union[bytes, bytearray],
                   test_output=None, verbose=False) -> int:
        """Provide characters from the outside link to be parsed

        Args:
            data (Union[bytes,bytearray]): new data from outside link
            test_output (list, optional): List-like object to hold
                resulting frames--for testing only (In normal operation,
                this method only uses self.fireFrameReceived(cf) to
                queue frames).
            verbose (bool, optional): If True, print each frame
                detected.

        Returns:
            int: The number of frames completed by inboundBuffer+data.
        """
        # same as the original handleData (renamed to
        #   handleDataOptimized, but more explicit with messages and error
        #   checking (effectively noise rejection).
        cls = type(self)
        frameCount = 0
        self.inboundBuffer += data
        # lastByte = 0  # last index is at ';'
        start = 0
        while True:
            first, end = cls.nextPacketRange(self.inboundBuffer, start=start)
            if first is None:
                break
            # else last is not None guaranteed
            semi = (end - 2) if (self.inboundBuffer[end-1] == 0x0a) else (end - 1)  # noqa: E501
            if semi - first < 11:  # len(":X") + 8 data + len("N")
                logger.warning(
                    "[handleData] Skipped malformed {} "
                    " (< 8 pairs in range {},{}) in packet {}"
                    .format(repr(self.inboundBuffer[first+1:semi]),
                            first+1, end,
                            repr(self.inboundBuffer[first:end])))
                start = end
                continue
            if self.inboundBuffer[first+1] != ord(b'X'):  # 0x58 (88)
                logger.warning(
                    "[handleData] Skipped malformed packet"
                    " (No 'X' in {})"
                    .format(repr(self.inboundBuffer[first:end])))
                start = end
                continue
            headerI = first + 2  # skip 2 chars: ":X"
            headerEnd = headerI + 8
            if (self.inboundBuffer[headerEnd] != ord(b'N')):  # 0x58 (88)
                logger.warning(
                    "[handleData] Skipped malformed packet"
                    " (header {} does not end with 'N' {} but {} in {})"
                    .format(repr(self.inboundBuffer[first:end]),
                            ord(b'N'), self.inboundBuffer[headerEnd],
                            self.inboundBuffer[first:end]))
                start = end
                continue
            dataI = headerEnd + 1  # header (8) + 1 (skip "N")
            dataEnd = semi
            if self.assertValidData and (dataEnd - dataI > 0):
                assert only_hex_pairs(self.inboundBuffer[headerI:headerEnd]), \
                    self.inboundBuffer[headerI:headerEnd]  # show non-hex data
                assert only_hex_pairs(self.inboundBuffer[dataI:dataEnd]), \
                    self.inboundBuffer[dataI:dataEnd]  # show the non-hex data
            header_bytes = from_hex_bytes(self.inboundBuffer, headerI,
                                          headerEnd,
                                          assertValid=self.assertValidData)
            if dataEnd - dataI > 0:
                if (dataEnd - dataI) % 2 > 0:
                    logger.warning(
                        "[handleData] Skipped malformed packet"
                        " (Incomplete pair in {} (range {},{}) in {})"
                        .format(repr(self.inboundBuffer[dataI:dataEnd]), dataI,
                                dataEnd, repr(self.inboundBuffer[first:end])))
                    start = end
                    continue
                outData = from_hex_bytes(self.inboundBuffer, dataI, dataEnd,
                                         assertValid=self.assertValidData)
            else:
                outData = bytearray()

            # Convert 4-byte big-endian header to 29-bit integer
            header = struct.unpack('>I', header_bytes)[0]

            cf = CanFrame(header, outData)
            if test_output is not None:
                test_output.add(cf)
            frameCount += 1
            self.fireFrameReceived(cf)
            if verbose:
                print("- RECV {}".format(
                    self.inboundBuffer[first:end].strip()))

            start = end  # proceed to next packet (keep going until no : or ;)

        # if lastByte > 0:
        #     del self.inboundBuffer[0:lastByte+1]
        if start > 0:
            del self.inboundBuffer[0:start]

        return frameCount
