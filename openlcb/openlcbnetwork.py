
"""
CDI Frame

A reusable superclass for Configuration Description Information
(CDI) processing and editing.

This file is part of the python-openlcb project
(<https://github.com/bobjacobsen/python-openlcb>).

Contributors: Poikilos, Bob Jacobsen (code from example_cdi_access)
"""
from collections import deque
from enum import Enum
import os
import threading
import time
import sys
from typing import Callable, Union
import xml.sax  # noqa: E402
import xml.etree.ElementTree as ET

from logging import getLogger
import xml.sax.handler
from xml.sax.xmlreader import AttributesImpl
# from xml.sax.xmlreader import AttributesImpl  # for autocomplete only

from openlcb import formatted_ex, precise_sleep

from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.canphysicallayergridconnect import (
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canlink import CanLink
from openlcb.message import Message
from openlcb.mti import MTI
from openlcb.nodeid import NodeID
from openlcb.datagramservice import (
    DatagramReadMemo,
    DatagramService,
)
from openlcb.memoryservice import (
    MemoryReadMemo,
    MemoryService,
)
from openlcb.platformextras import SysDirs, clean_file_name

if __name__ == "__main__":
    logger = getLogger(__file__)
else:
    logger = getLogger(__name__)


def element_to_dict(element):
    element = ET.Element(element)  # for autocomplete only
    return {
        'tag': element.tag,
        'attrib': element.attrib,  # already dict[str,str]
    }


def attrs_to_dict(attrs) -> dict:
    """Convert parser tag attrs.

    Args:
        attrs (AttributesImpl): attrs from xml parser startElement event
            (Not the same as element.attrib which is already dict).
    """
    # attrs = AttributesImpl(attrs)
    # attrs_dict = attrs.__dict__  # may have private members, so:
    return {key: attrs.getValue(key) for key in attrs.getNames()}


# TODO: split OpenLCBNetwork (socket & event handler) from ContentHandler
#   and/or only handle data as XML if request is for CDI/FDI or other XML.
class OpenLCBNetwork(xml.sax.handler.ContentHandler):
    """Manage Configuration Description Information.
    - Send events to downloadCDI caller describing the state and content
      of the document construction.
    - Collect and traverse XML in a CDI-specific way.

    Attributes:
        etree (Element): The XML root element (Does not correspond to an
            XML tag but rather the document itself, and contains all
            actual top-level elements as children).
        _openEl (SubElement): Tracks currently-open tag (no `</...>`
            yet) during parsing, or if no tags are open then equals
            etree.
        _tag_stack (list[SubElement]): Tracks scope during parse since
            self.etree doesn't have awareness of whether end tag is
            finished (and therefore doesn't know which element is the
            parent of a new startElement).
        _onElement (Callable): Called if an XML element is
            received (including either a start or end tag).
            Typically set as `callback` argument to downloadCDI.
        _resultingCDI (str): CDI document being collected from the
            network stream (successful read request memo handler). To
            ensure valid state:
            - Initialize to None at program start, end download, or
              failed download.
            - Assert is None at start of download, then set to
              bytearray().
    """
    class Mode(Enum):
        """Track what data is expected, if any.
        Attributes:
            Idle: No data (memory read request response) is expected.
            CDI: The data expected from the memory read is CDI XML.
        """
        Initializing = 0
        Disconnected = 1
        Idle = 2
        CDI = 3

    def __init__(self, *args, **kwargs):
        caches_dir = SysDirs.Cache
        self._myCacheDir = os.path.join(caches_dir, "python-openlcb")
        self._onElement = None
        self._onConnect = None
        self._mode = OpenLCBNetwork.Mode.Initializing
        # ^ In case some parsing step happens early,
        #   prepare these for _callback_msg.
        super().__init__()  # takes no arguments
        self._stringTerminated = None  # None means no read is occurring.
        self._parser = xml.sax.make_parser()
        self._parser.setContentHandler(self)

        self._realtime = True

        # region ContentHandler
        # self._chunks = []
        self._tag_stack = []
        # endregion ContentHandler

        # region connect
        self._port = None
        self._physicalLayer = None
        self._canLink = None
        self._datagramService = None
        self._memoryService = None
        self._resultingCDI = None
        # endregion connect

        self._connectingStart: float = None

    def _resetTree(self):
        self.etree = ET.Element("root")
        self._openEl = self.etree

    def _fireStatus(self, status, callback=None):
        """Fire status handlers with the given status."""
        if callback is None:
            callback = self._onElement
        if callback is None:
            callback = self._onConnect
        if callback:
            print("CDIForm callback_msg({})".format(repr(status)))
            self._onConnect({
                'status': status,
            })
        else:
            logger.warning("No callback, but set status: {}".format(status))

    def setElementHandler(self, handler: Callable):
        self._onElement = handler

    def setConnectHandler(self, handler: Callable):
        self._onConnect = handler

    def startListening(self, connected_port,
                       localNodeID: Union[NodeID, int, str, bytearray]):
        if self._port is not None:
            logger.warning(
                "[startListening] A previous _port will be discarded.")
        self._port = connected_port
        self._fireStatus("CanPhysicalLayerGridConnect...")
        self._physicalLayer = CanPhysicalLayerGridConnect()

        self._fireStatus("CanLink...")
        self._canLink = CanLink(self._physicalLayer, NodeID(localNodeID))
        # ^ CanLink constructor sets _physicalLayer's onFrameReceived
        #   and onFrameSent to handlers in _canLink.
        self._fireStatus("CanLink...registerMessageReceivedListener...")
        self._canLink.registerMessageReceivedListener(self._handleMessage)
        # NOTE: Incoming data (Memo) is handled by _memoryReadSuccess
        #   and _memoryReadFail.
        #   - These are set when constructing the MemoryReadMemo which
        #     is provided to openlcb's requestMemoryRead method.

        self._fireStatus("DatagramService...")
        self._datagramService = DatagramService(self._canLink)
        self._canLink.registerMessageReceivedListener(
            self._datagramService.process
        )

        self._datagramService.registerDatagramReceivedListener(
            self._printDatagram
        )

        self._fireStatus("MemoryService...")
        self._memoryService = MemoryService(self._datagramService)

        self._fireStatus("listen...")

        self.listen()  # Must listen for alias reservation responses
        #   (sendAliasConnectionSequence will occur for another 200ms
        #   once, then another 200ms on each alias collision if any)
        #   - must also keep doing frame = pollFrame() and sending
        #     if not None.

        self._fireStatus("physicalLayerUp...")
        self._physicalLayer.physicalLayerUp()
        self._fireStatus("Waiting for alias reservation...")
        while self._canLink.pollState() != CanLink.State.Permitted:
            precise_sleep(.02)
        # ^ triggers fireFrameReceived which calls CanLink's default
        #   receiveListener by default since added on CanPhysicalLayer
        #   arg of linkPhysicalLayer.
        #   - Must happen *after* listen thread starts, since
        #     fireFrameReceived (ControlFrame.LinkUp)
        #     calls sendAliasConnectionSequence on this thread!
        self._fireStatus("Alias reservation complete.")

    def listen(self):
        self._listenThread = threading.Thread(
            target=self._listen,
            daemon=True,  # True to terminate on program exit
        )
        print("[listen] Starting port receive loop...")
        self._listenThread.start()

    def _receive(self) -> bytearray:
        """Receive data from the port.
        Override this if serial/other subclass not using TCP
        (or better yet, make all ports including TcpSocket inherit from
        a standard port interface)
        """
        return self._port.receive()

    def _listen(self):
        self._connectingStart = time.perf_counter()
        self._messageStart = None
        self._mode = OpenLCBNetwork.Mode.Idle  # Idle until data type is known
        caught_ex = None
        try:
            # NOTE: self._canLink.state is *definitely not*
            #   CanLink.State.Permitted yet, but that's ok because
            #   CanLink's default receiveHandler has to provide
            #   the alias from each node (collision or not)
            #   to has to get the expected replies to the alias
            #   reservation sequence below.
            precise_sleep(.05)   # Wait for physicalLayerUp non-network Message
            while True:
                # Wait 200 ms for all nodes to announce (and for alias
                #   reservation to complete), as per section 6.2.1 of CAN
                #   Frame Transfer Standard (sendMessage requires )
                logger.debug("[_listen] _receive...")
                try:
                    # Receive mode (switches to write mode on BlockingIOError
                    #   which is expected and used on purpose)
                    # print("Waiting for _receive")
                    received = self._receive()  # requires setblocking(False)
                    print("[_listen] received {} byte(s)"
                          .format(len(received)),
                          file=sys.stderr)
                    # print("      RR: {}".format(received.strip()))
                    # pass to link processor
                    self._physicalLayer.handleData(received)
                    # ^ will trigger self._printFrame if that was added
                    #   via registerFrameReceivedListener during connect.
                    precise_sleep(.01)  # let processor sleep before read
                    if time.perf_counter() - self._connectingStart > .2:
                        if self._canLink._state != CanLink.State.Permitted:
                            delta = time.perf_counter() - self._messageStart
                            if ((self._messageStart is None) or (delta > 1)):
                                logger.warning(
                                    "CanLink is not ready yet."
                                    " There must have been a collision"
                                    "--processCollision increments node alias"
                                    " in this case and tries again.")
                        # else _on_link_state_change will be called
                    # TODO: move *all* send calls to this loop.
                except BlockingIOError:
                    # Nothing to receive right now, so perform all sends
                    #   This *must* occur (require socket.setblocking(False))
                    # sends = self._physicalLayer.popFrames()
                    # while sends:
                    while True:
                        # *Always* do send in the receive thread to
                        #   avoid overlapping calls to socket
                        #   (causes undefined behavior)!
                        frame = self._physicalLayer.pollFrame()
                        if frame is None:
                            break  # allow receive to run!
                        if isinstance(frame, CanFrame):
                            # if self._canLink.isDuplicateAlias(frame.alias):
                            if self._canLink.isBadReservation(frame):
                                logger.warning(
                                    "Discarded frame from a previous"
                                    " alias reservation attempt"
                                    " (duplicate alias={})"
                                    .format(frame.alias))
                                continue
                            logger.debug("[_listen] _sendString...")
                            packet = frame.encodeAsString()
                            assert isinstance(packet, str)
                            print("Sending {}".format(packet))
                            self._port.sendString(packet)
                            self._physicalLayer.onFrameSent(frame)
                        else:
                            raise NotImplementedError(
                                "Event type {} is not handled."
                                .format(type(frame).__name__))
                    #   so that it doesn't block (or occur during) recv
                    #   (overlapping calls would cause undefined behavior)!
                    # delay = random.uniform(.005,.02)
                    # ^ random delay may help if send is on another thread
                    #   (but avoid that for stability and speed)
                    precise_sleep(.01)
            # raise RuntimeError("We should never get here")
        except RuntimeError as ex:
            caught_ex = ex
            # If _port is a TcpSocket:
            #   May be raised by tcplink.tcpsocket.TCPSocket.receive
            #   manually.
            #   - Usually "socket connection broken" due to no more
            #     bytes to read, but ok if "\0" terminator was reached.
            if self._resultingCDI is not None and not self._stringTerminated:
                # This boolean is managed by the memoryReadSuccess
                # callback.
                event_d = {  # same as self._event_listener here
                    'error': formatted_ex(ex),
                    'done': True,  # stop progress in gui/other main thread
                }
                if self._onElement:
                    self._onElement(event_d)
                self._mode = OpenLCBNetwork.Mode.Disconnected
                raise  # re-raise since incomplete (prevent done OK state)
        finally:
            self._canLink.onDisconnect()
        self._listenThread: threading.Thread = None

        self._mode = OpenLCBNetwork.Mode.Disconnected
        # If we got here, the RuntimeError was ok since the
        #   null terminator '\0' was reached (otherwise re-raise occurs above)
        event_d = {
            'error': ("Listen loop stopped (caught_ex={})."
                      .format(formatted_ex(caught_ex))),
            'done': True,
        }
        if not (self._onConnect and self._onConnect(event_d)):
            # The message was not handled, so log it.
            logger.error(event_d['error'])
        return event_d  # return it in case running synchronously (no thread)

    def _memoryRead(self, farNodeID: Union[NodeID, int, str, bytearray],
                    offset: int):
        """Create and send a read datagram.
        This is a read of 20 bytes from the start of CDI space.
        We will fire it on a separate thread to give time for other nodes to
        reply to AME.

        Before calling this, ensure connect returns (or that you
        manually do the 200 ms wait it has built in). That ensures nodes
        announce, otherwise sendMessage (triggered by requestMemoryRead)
        will have a KeyError when trying to use the farNodeID.
        """
        # read 64 bytes from the CDI space starting at address zero
        memMemo = MemoryReadMemo(NodeID(farNodeID), 64, 0xFF, offset,
                                 self._memoryReadFail, self._memoryReadSuccess)
        self._memoryService.requestMemoryRead(memMemo)

    def downloadCDI(self, farNodeID: str, callback=None):
        if not farNodeID or not farNodeID.strip():
            raise ValueError("No farNodeID specified.")
        self._farNodeID = farNodeID
        self._stringTerminated = False
        if callback is None:
            def callback(event_d):
                print("downloadCDI default callback: {}".format(event_d),
                      file=sys.stderr)
        self._onElement = callback
        if not self._port:
            raise RuntimeError(
                "No port connection. Call startListening first.")
        if not self._physicalLayer:
            raise RuntimeError(
                "No physicalLayer. Call startListening first.")
        self._cdi_offset = 0
        self._resetTree()
        self._mode = OpenLCBNetwork.Mode.CDI
        if self._resultingCDI is not None:
            raise ValueError(
                "A previous downloadCDI operation is in progress"
                " or failed (Set _resultingCDI to None first if failed)")
        self._resultingCDI = bytearray()
        self._memoryRead(farNodeID, self._cdi_offset)
        # ^ On a successful memory read, _memoryReadSuccess will trigger
        #   _memoryRead again and again until end/fail.

    # def _sendToPort(self, string: str):
    #     # print("      SR: {}".format(string.strip()))
    #     DeprecationWarning("Use a PhysicalLayer subclass' sendFrameAfter")
    #     self.sendFrameAfter(string)

    # def _printFrame(self, frame: CanFrame):
    #     # print("   RL: {}".format(frame))
    #     pass

    def _handleMessage(self, message: Message):
        """Handle a Message from the LCC network.
        The Message Type Indicator (MTI) is checked in case the
        application should visualize a change in the connection state
        etc.

        Data (Memo) is not handled here (See _memoryReadSuccess and
        _memoryReadFail for that).

        Args:
            message (Message): Any message instance received from the
                LCC network.

        Returns:
            bool: If message was handled (always True in this
                method)
        """
        print("[_handleMessage] RM: {} from {}"
              .format(message, message.source))
        print("[_handleMessage]   message.mti={}".format(message.mti))
        if message.mti == MTI.Link_Layer_Down:
            if self._onConnect:
                self._onConnect({
                    'done': True,
                    'error': "Disconnected",
                    'message': message,
                })
                self._messageStart = None  # so _listen won't discard error
                return True
        elif message.mti == MTI.Link_Layer_Up:
            if self._onConnect:
                self._onConnect({
                    'done': True,  # 'done' without error indicates connected.
                    'message': message,
                })
                return True
        return False

    def _printDatagram(self, memo: DatagramReadMemo):
        """A call-back for when datagrams received

        Args:
            memo (DatagramReadMemo): The datagram object

        Returns:
            bool: Always False (True would mean we sent a reply to the
                datagram, but let the MemoryService do that).
        """
        # print("Datagram receive call back: {}".format(memo.data))
        return False

    def _CDIReadPartial(self, memo: MemoryReadMemo):
        """Handle partial CDI XML (any packet except last)
        The last packet is not yet reached, so don't parse (but
        feed if self._realtime)

        Args:
            memo (MemoryReadMemo): successful read memo containing data.
        """
        self._resultingCDI += memo.data
        partial_str = memo.data.decode("utf-8")
        if self._realtime:
            self._parser.feed(partial_str)  # may call startElement/endElement

    def _CDIReadDone(self, memo: MemoryReadMemo):
        """Handle end of CDI XML (last packet)
        End of data, so parse (or feed if self._realtime)

        Args:
            memo (MemoryReadMemo): successful read memo containing data.
        """
        partial_str = memo.data.decode("utf-8")
        # save content
        self._resultingCDI += memo.data
        # concert resultingCDI to a string up to 1st zero
        # and process that
        cdiString = None
        if self._realtime:
            # If _realtime, last chunk is treated same as another
            #   (since _realtime uses feed) except stop at '\0'.
            null_i = memo.data.find(b'\0')
            terminate_i = len(memo.data)
            if null_i > -1:
                terminate_i = min(null_i, terminate_i)
            partial_str = memo.data[:terminate_i].decode("utf-8")
        else:
            # *not* realtime (but got to end, so parse all at once)
            cdiString = ""
            null_i = self._resultingCDI.find(b'\0')
            terminate_i = len(self._resultingCDI)
            if null_i > -1:
                terminate_i = min(null_i, terminate_i)
            cdiString = self._resultingCDI[:terminate_i].decode("utf-8")
            # print (cdiString)
            self.parse(cdiString)
            # ^ startElement, endElement, etc. all consecutive using parse
            # self._fireStatus("Done loading CDI.")
            if self._onElement:
                self._onElement({
                    'done': True,  # 'done' and not 'error' means got all
                })
        if self._realtime:
            self._parser.feed(partial_str)  # may call startElement/endElement
        # memo = MemoryReadMemo(memo)
        path = self.cache_cdi_path(memo.nodeID)
        with open(path, 'w') as stream:
            if cdiString is None:
                cdiString = self._resultingCDI.rstrip(b'\0').decode("utf-8")
            stream.write(cdiString)
            print('Saved "{}"'.format(path))
        self._resultingCDI = None  # Ensure isn't reused for more than one doc

    def cache_cdi_path(self, item_id: Union[NodeID, str]):
        cdi_cache_dir = os.path.join(self._myCacheDir, "cdi")
        if not os.path.isdir(cdi_cache_dir):
            os.makedirs(cdi_cache_dir)
        # TODO: add hardware name and firmware version and from SNIP to
        #   name file to avoid cache file from a different
        #   device/version.
        item_id = str(item_id)  # Convert NodeID or other
        clean_name = clean_file_name(item_id.replace(":", "."))
        # ^ replace ":" to avoid converting that one to default "_"
        # ^ will raise error if path instead of name
        path = os.path.join(cdi_cache_dir, clean_name)
        if path == clean_name:
            # just to be safe, even though clean_file_name
            #   should prevent. If this occurs, fix clean_file_name.
            raise ValueError("Cannot specify absolute path.")
        return path + ".xml"

    def _memoryReadSuccess(self, memo: MemoryReadMemo):
        """Handle a successful read
        Invoked when the memory read successfully returns,
        this queues a new read until the entire CDI has been
        returned.  At that point, it invokes the XML processing below.

        Args:
            memo (MemoryReadMemo): Successful MemoryReadMemo
        """
        # print("successful memory read: {}".format(memo.data))
        if len(memo.data) == 64 and 0 not in memo.data:  # *not* last chunk
            self._stringTerminated = False
            if self._mode == OpenLCBNetwork.Mode.CDI:
                # save content
                self._CDIReadPartial(memo)
            else:
                logger.error(
                    "Unknown data packet received"
                    " (memory read not triggered by OpenLCBNetwork)")
            # update the address
            memo.address = memo.address + 64
            # and read again (read next)
            self._memoryService.requestMemoryRead(memo)
            # The last packet is not yet reached
        else:  # last chunk
            self._stringTerminated = True
            # and we're done!
            if self._mode == OpenLCBNetwork.Mode.CDI:
                self._CDIReadDone(memo)
            else:
                logger.error(
                    "Unknown last data packet received"
                    " (memory read not triggered by OpenLCBNetwork)")
            self._mode = OpenLCBNetwork.Mode.Idle  # CDI no longer expected
            # done reading

    def _memoryReadFail(self, memo: MemoryReadMemo):
        error = "memory read failed: {}".format(memo.data)
        if self._onElement:
            self._onElement({
                'error': error,
                'done': True,  # stop progress in gui/other main thread
            })
        else:
            logger.error(error)

    def startElement(self, name: str, attrs: AttributesImpl[str]):
        """See xml.sax.handler.ContentHandler documentation."""
        tab = "  " * len(self._tag_stack)
        print(tab, "Start: ", name)
        if attrs is not None and attrs :
            print(tab, "  Attributes: ", attrs.getNames())
        # el = ET.Element(name, attrs)
        attrib = attrs_to_dict(attrs)
        el = ET.SubElement(self._openEl, name, attrib)
        # if self._tag_stack:
        #     parent = self._tag_stack[-1]
        event_d = {'name': name, 'end': False, 'attrs': attrs,
                   'element': el}
        if self._onElement:
            self._onElement(event_d)

        # self._callback_msg(
        #     "loaded: {}{}".format(tab, ET.tostring(el, encoding="unicode")))
        self._tag_stack.append(el)
        self._openEl = el

    def checkDone(self, event_d: dict):
        """Notify the caller if parsing is over.
        Calls _onElement with `'done': True` in the argument if
        'name' is "cdi" (case-insensitive). That notifies the
        downloadCDI caller that parsing is over, so that caller should
        end progress bar/other status tracking for downloadCDI in that
        case.

        Returns:
            dict: Reserved for use without events (doesn't need to be
                processed if self._onElement is set since that
                also gets the dict if 'done'). 'done' is only True if
                'name' is "cdi" (case-insensitive).
        """
        event_d['done'] = False
        name = event_d.get('name')
        if not name or name.lower() != "cdi":
            # Not </cdi>, so not done yet
            return event_d
        event_d['done'] = True  # since "cdi" if avoided conditional return
        if self._onElement:
            self._onElement(event_d)
        return event_d

    def endElement(self, name: str):
        """See xml.sax.handler.ContentHandler documentation."""
        indent = len(self._tag_stack)
        tab = "  " * indent
        top_el = self._tag_stack[-1]
        if name != top_el.tag:
            print(tab+"Warning: </{}> before </{}>".format(name, top_el.tag))
        elif indent:  # top element found and indent not 0
            indent -= 1  # dedent since scope ended
        # print(tab, name, "content:", self._flushCharBuffer())
        print(tab, "End: ", name)
        event_d = {'name': name, 'end': True}
        if not self._tag_stack:
            event_d['error'] = "</{}> before any start tag".format(name)
            print(tab+"Warning: {}".format(event_d['error']))
            self.checkDone(event_d)
            return
        if name != top_el.tag:
            event_d['error'] = (
                "</{}> before top tag <{} ...> closed"
                .format(name, top_el.tag))
            print(tab+"Warning: {}".format(event_d['error']))
            self.checkDone(event_d)
            return
        del self._tag_stack[-1]
        if self._tag_stack:
            self._openEl = self._tag_stack[-1]
        else:
            self._openEl = self.etree
        if self._tag_stack:
            event_d['parent'] = self._tag_stack[-1]
        event_d['element'] = top_el
        result = self.checkDone(event_d)
        if not result.get('done'):
            # Notify downloadCDI's caller since it can potentially add
            #   UI widget(s) for at least one setting/segment/group
            #   using this 'element'.
            self._onElement(event_d)

    # def _flushCharBuffer(self):
    #     """Decode the buffer, clear it, and return all content.
    #     See xml.sax.handler.ContentHandler documentation.

    #     Returns:
    #         str: The content of the bytes buffer decoded as utf-8.
    #     """
    #     s = ''.join(self._chunks)
    #     self._chunks.clear()
    #     return s

    # def characters(self, data: Union[bytearray, bytes, list[int]]):
    #     """Received characters handler.
    #     See xml.sax.handler.ContentHandler documentation.

    #     Args:
    #         data (Union[bytearray, bytes, list[int]]): any
    #           data (any type accepted by bytearray extend).
    #     """
    #     if not isinstance(data, str):
    #         raise TypeError(
    #             "Expected str, got {}".format(type(data).__name__))
    #     self._chunks.append(data)
