'''
based on CanPhysicalLayerGridConnect.swift

Created by Bob Jacobsen on 6/14/22.

Provide a CanPhysicalLayer for GridConnect format strings.

Works with frames like
- :X19490365N;
- :X19170365N020112FE056C;
'''

from collections import deque
from typing import Union
from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.canbus.canframe import CanFrame
from openlcb.frameencoder import FrameEncoder

GC_START_BYTE = 0x3a  # :
GC_END_BYTE = 0x3b  # ;


class CanPhysicalLayerGridConnect(CanPhysicalLayer, FrameEncoder):
    """CAN physical layer subclass for GridConnect

    This acts as frame.encoder for canLink, and manages the packet
    _send_frames queue (deque is used for speed; defined & managed in base
    class: PhysicalLayer)

    Args:
        callback (Callable): A string send method for the platform and
            hardware being used. It must be associated with an active
            connection before used as the arg, and must raise exception
            on failure so that sendAliasAllocationSequence is
            interrupted in order to prevent canlink.state from
            proceeding to CanLink.State.Permitted)
    """
    def __init__(self):
        # ^ A CanLink requires a physical layer to operate,
        #   so CanLink now requires a PhysicalLayer instance
        #   such as this in its constructor.
        CanPhysicalLayer.__init__(self)  # creates self._send_frames

        # region moved to CanLink constructor
        # from canLink.linkPhysicalLayer(self)  # self.setCallBack(callback):
        # canLink.physicalLayer = self
        # self.registerFrameReceivedListener(canLink.handleFrameReceived)
        # endregion moved to CanLink constructor

        self.inboundBuffer = bytearray()

    # def setCallBack(self, callback):
    #     assert callable(callback)
    #     self.canSendCallback = callback

    def encodeFrameAsString(self, frame) -> str:
        '''Encode frame to string.'''
        output = ":X{:08X}N".format(frame.header)  # at least 8 chars, hex
        for byte in frame.data:
            output += "{:02X}".format(byte)  # at least 2 chars, hex
        output += ";\n"
        return output

    def encodeFrameAsData(self, frame) -> Union[bytearray, bytes]:
        # TODO: Consider doing this manually (in Python 3,
        #   bytes/bytearray has no attribute 'format')
        return self.encodeFrameAsString(frame).encode("utf-8")

    def handleDataString(self, string: str):
        '''Provide string from the outside link to be parsed

        Args:
            string (str): A new UTF-8 string from outside link
        '''
        # formerly pushString formerly receiveString
        self.handleData(string.encode("utf-8"))

    def handleData(self, data: Union[bytes, bytearray]):
        """Provide characters from the outside link to be parsed

        Args:
            data (Union[bytes,bytearray]): new data from outside link
        """
        self.inboundBuffer += data
        processedCount = 0
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
                    for offset in range(2, 9+1):
                        nextChar = (self.inboundBuffer[index+offset])
                        nextByte = (nextChar & 0xF)+9 if nextChar > 0x39 else nextChar & 0xF  # noqa: E501
                        header = (header << 4)+nextByte
                    # offset 10 is N
                    # offset 11 might be data, might be ;
                    processedCount = index+11
                    for dataItem in range(0, 8):
                        if self.inboundBuffer[index+11+2*dataItem] == GC_END_BYTE:  # noqa: E501
                            break
                        # two characters are data
                        byte1 = self.inboundBuffer[index+11+2*dataItem]
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
                        processedCount += 2
                    # lastByte is index of ; in this message

                    cf = CanFrame(header, outData)
                    self.fireFrameReceived(cf)

            # shorten buffer by removing the processed message
            self.inboundBuffer = self.inboundBuffer[processedCount:]
