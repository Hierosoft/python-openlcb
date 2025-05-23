'''
based on CanPhysicalLayerGridConnect.swift

Created by Bob Jacobsen on 6/14/22.

Provide a CanPhysicalLayer for GridConnect format strings.

Works with frames like
- :X19490365N;
- :X19170365N020112FE056C;
'''


from typing import Union
from openlcb.canbus.canphysicallayer import CanPhysicalLayer
from openlcb.canbus.canframe import CanFrame
from openlcb.frameencoder import FrameEncoder
from openlcb.portinterface import PortInterface

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

    def sendAll(self, device: PortInterface, mode="binary", verbose=False) -> int:
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
                    if self.linkLayer.isCanceled(frame):
                        if verbose:
                            print("- Skipped (probably dup alias CID frame).")
                        continue
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

    def handleData(self, data: Union[bytes, bytearray], verbose=False) -> int:
        """Provide characters from the outside link to be parsed

        Args:
            data (Union[bytes,bytearray]): new data from outside link
            verbose (bool, optional): If True, print each frame
                detected.

        Returns:
            int: The number of frames completed by inboundBuffer+data.
        """
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
                    for offset in range(2, 9+1):
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
                    frameCount += 1
                    self.fireFrameReceived(cf)
                    if verbose:
                        print("- RECV {}".format(
                            self.inboundBuffer[index:lastByte+1].strip()))

            # shorten buffer by removing the processed message
            self.inboundBuffer = self.inboundBuffer[lastByte:]
        return frameCount
