'''
Demo of using the memory service to read the CDI from memory, then an
example of parsing

Usage:
python3 example_memory_transfer.py [host|host:port]

Options:
host|host:port            (optional) Set the address (or using a colon,
                          the address and port). Defaults to a hard-coded test
                          address and port.
'''
# region same code as other examples
import copy
# from xml.sax.expatreader import AttributesImpl  # only for IDE autocomplete
from examples_settings import Settings  # do 1st to fix path if no pip install
from openlcb import precise_sleep
from openlcb.tcplink.tcpsocket import TcpSocket
settings = Settings()

if __name__ == "__main__":
    settings.load_cli_args(docstring=__doc__)
# endregion same code as other examples

from openlcb.canbus.canphysicallayergridconnect import (  # noqa:E402
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canlink import CanLink  # noqa:E402
from openlcb.nodeid import NodeID  # noqa:E402
from openlcb.datagramservice import (  # noqa:E402
    DatagramService,
)
from openlcb.memoryservice import (  # noqa:E402
    MemoryReadMemo,
    MemoryService,
)

# specify connection information
# region moved to settings
# host = "192.168.16.212"
# port = 12021
# localNodeID = "05.01.01.01.03.01"
# # farNodeID = "09.00.99.03.00.35"
# farNodeID = "02.01.57.00.04.9C"
# endregion moved to settings

sock = TcpSocket()
# s.settimeout(30)
sock.connect(settings['host'], settings['port'])


# print("RR, SR are raw socket interface receive and send;"
#      " RL, SL are link interface; RM, SM are message interface")


# def sendToSocket(frame: CanFrame):
#     string = frame.encodeAsString()
#     # print("      SR: {}".format(string.strip()))
#     sock.sendString(string)
#     physicalLayer.onFrameSent(frame)


def printFrame(frame):
    # print("   RL: {}".format(frame))
    pass


def printMessage(message):
    # print("RM: {} from {}".format(message, message.source))
    pass


def printDatagram(memo):
    """A call-back for when datagrams received

    Args:
        DatagramReadMemo: The datagram object

    Returns:
        bool: Always False (True would mean we sent a reply to the datagram,
            but let the MemoryService do that).
    """
    # print("Datagram receive call back: {}".format(memo.data))
    return False


physicalLayer = CanPhysicalLayerGridConnect()
physicalLayer.registerFrameReceivedListener(printFrame)

canLink = CanLink(physicalLayer, NodeID(settings['localNodeID']))
canLink.registerMessageReceivedListener(printMessage)

datagramService = DatagramService(canLink)
canLink.registerMessageReceivedListener(datagramService.process)

datagramService.registerDatagramReceivedListener(printDatagram)

memoryService = MemoryService(datagramService)


# accumulate the CDI information
resultingCDI = bytearray()

# callbacks to get results of memory read

complete_data = False
read_failed = False


def memoryReadSuccess(memo):
    """Handle a successful read
    Invoked when the memory read successfully returns,
    this queues a new read until the entire CDI has been
    returned.  At that point, it invokes the XML processing below.

    Args:
        memo (MemoryReadMemo): Successful MemoryReadMemo
    """
    # print("successful memory read: {}".format(memo.data))

    global resultingCDI
    global complete_data

    # is this done?
    if len(memo.data) == 64 and 0 not in memo.data:
        # save content
        resultingCDI += memo.data
        # update the address
        memo.address = memo.address+64
        # and read again
        memoryService.requestMemoryRead(memo)
        # The last packet is not yet reached, so don't parse (However,
        #   parser.feed could be called for realtime processing).
    else :
        # and we're done!
        # save content
        resultingCDI += memo.data
        # concert resultingCDI to a string up to 1st zero
        cdiString = ""
        null_i = resultingCDI.find(b'\0')
        terminate_i = len(resultingCDI)
        if null_i > -1:
            terminate_i = min(null_i, terminate_i)
        cdiString = resultingCDI[:terminate_i].decode("utf-8")
        # print (cdiString)

        # and process that
        processXML(cdiString)
        complete_data = True

        # done


def memoryReadFail(memo):
    global read_failed
    print("memory read failed: {}".format(memo.data))
    read_failed = True


#######################
# The XML parsing section.
#
# This creates a handler object that just prints
# information as it's presented.
#
# Since `characters` can be called multiple times
# in a row, we buffer up the characters until the `endElement`
# call is invoked to indicate the text is complete

import xml.sax  # noqa: E402


class MyHandler(xml.sax.handler.ContentHandler):
    """XML SAX callbacks in a handler object

    Attributes:
        _chunks (list[str]): Collects chunks of data.
            This is implementation-specific, and not
            required if streaming (parser.feed).
    """

    def __init__(self):
        self._chunks = []

    def startElement(self, name: str, attrs):
        """See xml.sax.handler.ContentHandler documentation."""
        print("Start: ", name)
        if attrs is not None and attrs :
            print("  Attributes: ", attrs.getNames())

    def endElement(self, name: str):
        """See xml.sax.handler.ContentHandler documentation."""
        print(name, "content:", self._flushCharBuffer())
        print("End: ", name)
        pass

    def _flushCharBuffer(self):
        """Decode the buffer, clear it, and return all content.
        See xml.sax.handler.ContentHandler documentation.

        Returns:
            str: The content of the bytes buffer decoded as utf-8.
        """
        s = ''.join(self._chunks)
        self._chunks.clear()
        return s

    def characters(self, data: str):
        """Received characters handler.
        See xml.sax.handler.ContentHandler documentation.

        Args:
            data (Union[bytearray, bytes, list[int]]): any
              data (any type accepted by bytearray extend).
        """
        if not isinstance(data, str):
            raise TypeError("Expected str, got {}".format(type(data).__name__))
        self._chunks.append(data)


handler = MyHandler()


def processXML(content: str) :
    """process the XML and invoke callbacks

    Args:
        content (str): Raw XML data
    """
    # NOTE: The data is complete in this example since processXML is
    #   only called when there is a null terminator, which indicates the
    #   last packet was reached for the requested read.
    #   - See memoryReadSuccess comments for details.
    with open("cached-cdi.xml", 'w') as stream:
        # NOTE: Actual caching should key by all SNIP info that could
        #   affect CDI/FDI: manufacturer, model, and version. Without
        #   all 3 being present in SNIP, the cache may be incorrect.
        stream.write(content)
    xml.sax.parseString(content, handler)
    print("\nParser done")


#######################

# have the socket layer report up to bring the link layer up and get an alias
print("      QUEUE frames : link up...")
physicalLayer.physicalLayerUp()
print("      QUEUED frames : link up...waiting...")
while canLink.pollState() != CanLink.State.Permitted:
    # provides incoming data to physicalLayer & sends queued:
    physicalLayer.receiveAll(sock, verbose=True)
    physicalLayer.sendAll(sock)

    if canLink.getState() == CanLink.State.WaitForAliases:
        # physicalLayer.receiveAll(sock, verbose=True)
        physicalLayer.sendAll(sock)
        # ^ prevent assertion error below, proceed to send.
    if canLink.pollState() == CanLink.State.Permitted:
        break
    assert canLink.getWaitForAliasResponseStart() is not None, \
        ("openlcb didn't send the 7,6,5,4 CID frames (state={})"
         .format(canLink.getState()))
    precise_sleep(.02)
print("      SENT frames : link up")


def memoryRead():
    """Create and send a read datagram.
    This is a read of 20 bytes from the start of CDI space.
    We will fire it on a separate thread to give time for other nodes to reply
    to AME
    """
    import time
    time.sleep(.21)
    # ^ 200ms: See section 6.2.1 of CAN Frame Transfer Standard
    #   (CanLink.State.Permitted will only occur after that, but waiting
    #   now will reduce output & delays below in this example).
    while canLink.getState() != CanLink.State.Permitted:
        print("Waiting for connection sequence to complete...")
        # This delay could be .2 (per alias collision), but longer to
        #   reduce console messages:
        time.sleep(.5)
    print("Requesting memory read. Please wait...")
    # read 64 bytes from the CDI space starting at address zero
    memMemo = MemoryReadMemo(NodeID(settings['farNodeID']), 64, 0xFF, 0,
                             memoryReadFail, memoryReadSuccess)
    memoryService.requestMemoryRead(memMemo)


import threading  # noqa E402
thread = threading.Thread(target=memoryRead)
thread.start()
previous_nodes = copy.deepcopy(canLink.nodeIdToAlias)
# process resulting activity
print()
print("This example will exit on failure or complete data.")
while not complete_data and not read_failed:
    # In this example, requests are initiate by the
    #   memoryRead thread, and receiveAll actually
    #   receives the data from the requested memory space (CDI in this
    #   case) and offset (incremental position in the file/data,
    #   incremented by this example's memoryReadSuccess handler).
    count = 0
    count += physicalLayer.receiveAll(sock)
    count += physicalLayer.sendAll(sock)
    if canLink.nodeIdToAlias != previous_nodes:
        print("nodeIdToAlias updated: {}".format(canLink.nodeIdToAlias))
    if count < 1:
        precise_sleep(.01)
    # else skip sleep to avoid latency (port already delayed)
    if canLink.nodeIdToAlias != previous_nodes:
        previous_nodes = copy.deepcopy(canLink.nodeIdToAlias)

physicalLayer.onDisconnect()

if read_failed:
    print("Read complete (FAILED)")
else:
    print("Read complete (OK)")
