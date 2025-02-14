
"""
CDI Frame

A reusable superclass for Configuration Description Information
(CDI) processing and editing.

This file is part of the python-openlcb project
(<https://github.com/bobjacobsen/python-openlcb>).

Contributors: Poikilos, Bob Jacobsen (code from example_cdi_access)
"""
import json
import platform
import subprocess
from collections import OrderedDict
import sys
import xml.sax  # noqa: E402
import xml.etree.ElementTree as ET

from logging import getLogger

from openlcb.canbus.tcpsocket import TcpSocket

from openlcb.canbus.canphysicallayergridconnect import (
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canlink import CanLink
from openlcb.nodeid import NodeID
from openlcb.datagramservice import (
    DatagramService,
)
from openlcb.memoryservice import (
    MemoryReadMemo,
    MemoryService,
)

logger = getLogger(__name__)


class CDIHandler(xml.sax.handler.ContentHandler):
    """Manage Configuration Description Information.
    - Send events to downloadCDI caller describing the state and content
      of the document construction.
    - Collect and traverse XML in a CDI-specific way.

    Attributes:
        etree (Element): The XML root element (Does not correspond to an
            XML tag but rather the document itself, and contains all
            actual top-level elements as children).
        _open_el (SubElement): Tracks currently-open tag (no `</...>`
            yet) during parsing, or if no tags are open then equals
            etree.
        _tag_stack(list[SubElement]): Tracks scope during parse since
            self.etree doesn't have awareness of whether end tag is
            finished (and therefore doesn't know which element is the
            parent of a new startElement).
    """
    def __init__(self, *args, **kwargs):
        self._download_callback = None
        self._connect_callback = None
        # ^ In case some parsing step happens early,
        #   prepare these for _callback_msg.
        super().__init__()  # takes no arguments

        self._realtime = True

        # region ContentHandler
        # self._chunks = []
        self._tag_stack = []
        # endregion ContentHandler

        # region connect
        self._sock = None
        self._canPhysicalLayerGridConnect = None
        self._canLink = None
        self._datagramService = None
        self._memoryService = None
        self._resultingCDI = None
        # endregion connect

    def _reset_tree(self):
        self.etree = ET.Element("root")
        self._open_el = self.etree

    def _callback_msg(self, msg, callback=None):
        if callback is None:
            callback = self._download_callback
        if callback is None:
            callback = self._connect_callback
        if callback:
            print("CDIForm callback_msg({})".format(repr(msg)))
            self._connect_callback({
                'message': msg,
            })
        else:
            logger.warning("No callback, but set status: {}".format(msg))

    def connect(self, host, port, localNodeID, callback=None):
        self._connect_callback = callback
        self._callback_msg("connecting to {}...".format(host))
        self._sock = TcpSocket()
        # s.settimeout(30)
        self._sock.connect(host, port)
        self._callback_msg("CanPhysicalLayerGridConnect...")
        self._canPhysicalLayerGridConnect = \
            CanPhysicalLayerGridConnect(self._sendToSocket)
        self._canPhysicalLayerGridConnect.registerFrameReceivedListener(
            self._printFrame
        )

        self._callback_msg("CanLink...")
        self._canLink = CanLink(NodeID(localNodeID))
        self._callback_msg("CanLink...linkPhysicalLayer...")
        self._canLink.linkPhysicalLayer(self._canPhysicalLayerGridConnect)
        self._callback_msg("CanLink...linkPhysicalLayer"
                           "...registerMessageReceivedListener...")
        self._canLink.registerMessageReceivedListener(self._printMessage)

        self._callback_msg("DatagramService...")
        self._datagramService = DatagramService(self._canLink)
        self._canLink.registerMessageReceivedListener(
            self._datagramService.process
        )

        self._datagramService.registerDatagramReceivedListener(
            self._printDatagram
        )

        self._callback_msg("MemoryService...")
        self._memoryService = MemoryService(self._datagramService)

        self._callback_msg("physicalLayerUp...")
        self._canPhysicalLayerGridConnect.physicalLayerUp()

        # accumulate the CDI information
        self._resultingCDI = bytearray()  # only used if not self.realtime
        event_d = {
            'message': "Ready to receive.",
            'done': True,
        }
        if callback:
            callback(event_d)

        return event_d  # return it in case running synchronously (no thread)


    def _memoryRead(self, farNodeID, offset):
        """Create and send a read datagram.
        This is a read of 20 bytes from the start of CDI space.
        We will fire it on a separate thread to give time for other nodes to
        reply to AME
        """
        # time.sleep(1)

        # read 64 bytes from the CDI space starting at address zero
        memMemo = MemoryReadMemo(NodeID(farNodeID), 64, 0xFF, offset,
                                 self._memoryReadFail, self._memoryReadSuccess)
        self._memoryService.requestMemoryRead(memMemo)

    def downloadCDI(self, farNodeID, callback=None):
        if not farNodeID or not farNodeID.strip():
            raise ValueError("No farNodeID specified.")
        self._farNodeID = farNodeID
        self._string_terminated = False
        if callback is None:
            def callback(event_d):
                print("downloadCDI default callback: {}".format(event_d),
                      file=sys.stderr)
        self._download_callback = callback
        if not self._sock:
            raise RuntimeError("No TCPSocket. Call connect first.")
        if not self._canPhysicalLayerGridConnect:
            raise RuntimeError(
                "No canPhysicalLayerGridConnect. Call connect first.")
        self._cdi_offset = 0
        self._reset_tree()
        self._memoryRead(farNodeID, self._cdi_offset)
        while True:
            try:
                received = self._sock.receive()
                # print("      RR: {}".format(received.strip()))
                # pass to link processor
                self._canPhysicalLayerGridConnect.receiveString(received)
                # ^ will trigger self._printFrame since that was added
                #   via registerFrameReceivedListener during connect.
            except RuntimeError as ex:
                # May be raised by canbus.tcpsocket.TCPSocket.receive
                # manually. Usually "socket connection broken" due to
                # no more bytes to read, but ok if "\0" terminator
                # was reached.
                if not self._string_terminated:
                    # This boolean is managed by the memoryReadSuccess
                    # callback.
                    callback({  # same as self._download_callback here
                        'error': "{}: {}".format(type(ex).__name__, ex),
                        'done': True,  # stop progress in gui/other main thread
                    })
                    raise # re-raise since incomplete (prevent done OK state)
                break
        # If we got here, the RuntimeError was ok since the
        #   null terminator '\0' was reached (otherwise re-raise occurs above)
        event_d = {
            'message': "Done reading CDI.",
            # 'done': True,  # NOTE: not really done until endElement("cdi")
        }
        return event_d  # return it in case running synchronously (no thread)

    def _sendToSocket(self, string):
        # print("      SR: {}".format(string.strip()))
        self._sock.send(string)

    def _printFrame(self, frame):
        # print("   RL: {}".format(frame))
        pass

    def _printMessage(self, message):
        # print("RM: {} from {}".format(message, message.source))
        pass

    def _printDatagram(self, memo):
        """A call-back for when datagrams received

        Args:
            DatagramReadMemo: The datagram object

        Returns:
            bool: Always False (True would mean we sent a reply to the datagram,
                but let the MemoryService do that).
        """
        # print("Datagram receive call back: {}".format(memo.data))
        return False

    def _memoryReadSuccess(self, memo):
        """Handle a successful read
        Invoked when the memory read successfully returns,
        this queues a new read until the entire CDI has been
        returned.  At that point, it invokes the XML processing below.

        Args:
            memo (MemoryReadMemo): Successful MemoryReadMemo
        """
        # print("successful memory read: {}".format(memo.data))
        if len(memo.data) == 64 and 0 not in memo.data:  # *not* last chunk
            self._string_terminated = False
            chunk_str = memo.data.decode("utf-8")
            # save content
            self._resultingCDI += memo.data
            # update the address
            memo.address = memo.address + 64
            # and read again (read next)
            self._memoryService.requestMemoryRead(memo)
            # The last packet is not yet reached, so don't parse (but
            #   feed if self._realtime)
        else:  # last chunk
            self._string_terminated = True
            # and we're done!
            # save content
            self._resultingCDI += memo.data
            # concert resultingCDI to a string up to 1st zero
            # and process that
            if self._realtime:
                # If _realtime, last chunk is treated same as another
                #   (since _realtime uses feed) except stop at '\0'.
                null_i = memo.data.find(b'\0')
                terminate_i = len(memo.data)
                if null_i > -1:
                    terminate_i = min(null_i, terminate_i)
                chunk_str = memo.data[:terminate_i].decode("utf-8")
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
                self._callback_msg("Done loading CDI.")
            # done reading
        if self._realtime:
            self.feed(chunk_str)  # startElement, endElement etc. are automatic

    def _memoryReadFail(self, memo):
        error = "memory read failed: {}".format(memo.data)
        if self._download_callback:
            self._download_callback({
                'error': error,
                'done': True,  # stop progress in gui/other main thread
            })
        else:
            logger.error(error)

    def startElement(self, name, attrs):
        """See xml.sax.handler.ContentHandler documentation."""
        tab = "  " * len(self._tag_stack)
        print(tab, "Start: ", name)
        if attrs is not None and attrs :
            print(tab, "  Attributes: ", attrs.getNames())
        # el = ET.Element(name, attrs)
        el = ET.SubElement(self._open_el, "element1")
        # if self._tag_stack:
        #     parent = self._tag_stack[-1]
        self._callback_msg(
            "loaded: {}{}".format(tab, ET.tostring(el, encoding="unicode")))
        self._tag_stack.append(el)
        self._open_el = el

    def checkDone(self, event_d):
        """Notify the caller if parsing is over.
        Calls _download_callback with `'done': True` in the argument if
        'name' is "cdi" (case-insensitive). That notifies the
        downloadCDI caller that parsing is over, so that caller should
        end progress bar/other status tracking for downloadCDI in that
        case.

        Returns:
            dict: Reserved for use without events (doesn't need to be
                processed if self._download_callback is set since that
                also gets the dict if 'done'). 'done' is only True if
                'name' is "cdi" (case-insensitive).
        """
        event_d['done'] = False
        name = event_d.get('name')
        if not name or name.lower() != "cdi":
            # Not </cdi>, so not done yet
            return event_d
        event_d['done'] = True  # since "cdi" if avoided conditional return
        if self._download_callback:
            self._download_callback(event_d)
        return event_d

    def endElement(self, name):
        """See xml.sax.handler.ContentHandler documentation."""
        indent = len(self._tag_stack)
        top_el = self._tag_stack[-1]
        if name != top_el.tag:
            print(tab+"Warning: </{}> before </{}>".format(name, top_el.tag))
        elif indent:  # top element found and indent not 0
            indent -= 1  # dedent since scope ended
        tab = "  " * indent
        # print(tab, name, "content:", self._flushCharBuffer())
        print(tab, "End: ", name)
        event_d = {'name': name}
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
            self._open_el = self._tag_stack[-1]
        else:
            self._open_el = self.etree
        if self._tag_stack:
            event_d['parent'] = self._tag_stack[-1]
        event_d['element'] = top_el
        result = self.checkDone(event_d)
        if not result.get('done'):
            # Notify downloadCDI's caller since it can potentially add
            #   UI widget(s) for at least one setting/segment/group
            #   using this 'element'.
            self._download_callback(event_d)

    # def _flushCharBuffer(self):
    #     """Decode the buffer, clear it, and return all content.
    #     See xml.sax.handler.ContentHandler documentation.

    #     Returns:
    #         str: The content of the bytes buffer decoded as utf-8.
    #     """
    #     s = ''.join(self._chunks)
    #     self._chunks.clear()
    #     return s

    # def characters(self, data):
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