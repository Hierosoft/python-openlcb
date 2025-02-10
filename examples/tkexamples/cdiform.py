"""
CDI Frame

This file is part of the python-openlcb project
(<https://github.com/bobjacobsen/python-openlcb>).

Contributors: Poikilos, Bob Jacobsen (code from example_cdi_access)

Purpose: Provide a reusable widget for editing LCC node settings
as described by the node's Configuration Description Information (CDI).
"""
import json
import os
import platform
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from collections import OrderedDict

import xml.etree.ElementTree as ET

from xml.etree.ElementTree import Element
from logging import getLogger

logger = getLogger(__name__)

TKEXAMPLES_DIR = os.path.dirname(os.path.realpath(__file__))
EXAMPLES_DIR = os.path.dirname(TKEXAMPLES_DIR)
REPO_DIR = os.path.dirname(EXAMPLES_DIR)
if os.path.isfile(os.path.join(REPO_DIR, "openlcb", "__init__.py")):
    sys.path.insert(0, REPO_DIR)
else:
    logger.warning(
        "Reverting to installed copy if present (or imports will fail),"
        " since test running from repo but could not find openlcb in {}."
        .format(repr(REPO_DIR)))
try:
    from openlcb.canbus.tcpsocket import TcpSocket
except ImportError as ex:
    print("{}: {}".format(type(ex).__name__, ex), file=sys.stderr)
    print("* You must run this from a venv that has openlcb installed"
          " or adds it to sys.path like examples_settings does.",
          file=sys.stderr)
    raise  # sys.exit(1)


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


import xml.sax  # noqa: E402


class CDIForm(ttk.Frame, xml.sax.handler.ContentHandler):
    def __init__(self, *args, **kwargs):
        self.parent = None
        if args:
          self.parent = args[0]
        self.realtime = True

        ttk.Frame.__init__(self, *args, **kwargs)
        xml.sax.handler.ContentHandler.__init__(self)
        # region ContentHandler
        # self._chunks = []
        self._tag_stack = []
        # endregion ContentHandler
        self.container = self  # where to put visible widgets
        self.treeview = None
        self.gui(self.container)

    def callback_msg(self, msg):
        if self.callback:
            print("CDIForm callback_msg({})".format(repr(msg)))
            self.callback({
                'message': msg,
            })
        else:
            logger.warning("No callback, but set status: {}".format(msg))

    def gui(self, container):
        self.treeview = ttk.Treeview(container)
        self.grid(sticky=tk.NSEW)

    def connect(self, host, port, localNodeID, callback=None):
        self.callback = callback
        self.callback_msg("connecting to {}...".format(host))
        self.sock = TcpSocket()
        # s.settimeout(30)
        self.sock.connect(host, port)
        self.callback_msg("CanPhysicalLayerGridConnect...")
        self.canPhysicalLayerGridConnect = CanPhysicalLayerGridConnect(self.sendToSocket)
        self.canPhysicalLayerGridConnect.registerFrameReceivedListener(self.printFrame)


        self.callback_msg("CanLink...")
        self.canLink = CanLink(NodeID(localNodeID))
        self.callback_msg("CanLink...linkPhysicalLayer...")
        self.canLink.linkPhysicalLayer(self.canPhysicalLayerGridConnect)
        self.callback_msg("CanLink...linkPhysicalLayer...registerMessageReceivedListener...")
        self.canLink.registerMessageReceivedListener(self.printMessage)

        self.callback_msg("DatagramService...")
        self.datagramService = DatagramService(self.canLink)
        self.canLink.registerMessageReceivedListener(self.datagramService.process)

        self.datagramService.registerDatagramReceivedListener(self.printDatagram)

        self.callback_msg("MemoryService...")
        self.memoryService = MemoryService(self.datagramService)

        # accumulate the CDI information
        self.resultingCDI = bytearray()

    def sendToSocket(self, string):
        # print("      SR: {}".format(string.strip()))
        self.sock.send(string)


    def printFrame(self, frame):
        # print("   RL: {}".format(frame))
        pass


    def printMessage(self, message):
        # print("RM: {} from {}".format(message, message.source))
        pass


    def printDatagram(self, memo):
        """A call-back for when datagrams received

        Args:
            DatagramReadMemo: The datagram object

        Returns:
            bool: Always False (True would mean we sent a reply to the datagram,
                but let the MemoryService do that).
        """
        # print("Datagram receive call back: {}".format(memo.data))
        return False


    def memoryReadSuccess(self, memo):
        """Handle a successful read
        Invoked when the memory read successfully returns,
        this queues a new read until the entire CDI has been
        returned.  At that point, it invokes the XML processing below.

        Args:
            memo (MemoryReadMemo): Successful MemoryReadMemo
        """
        # print("successful memory read: {}".format(memo.data))
        if self.realtime:
            if len(memo.data) == 64 and 0 not in memo.data:
                chunk = memo.data.decode("utf-8")
            else:
                null_i = memo.data.find(b'\0')
                terminate_i = len(memo.data)
                if null_i > -1:
                    terminate_i = min(null_i, terminate_i)
                chunk = memo.data[:terminate_i].decode("utf-8")

            self.feed(chunk)
            # is this done?
        else:
          if len(memo.data) == 64 and 0 not in memo.data:
              # save content
              self.resultingCDI += memo.data
              # update the address
              memo.address = memo.address+64
              # and read again
              self.memoryService.requestMemoryRead(memo)
              # The last packet is not yet reached, so don't parse (However,
              #   parser.feed could be called for realtime processing).
          else :
              # and we're done!
              # save content
              self.resultingCDI += memo.data
              # concert resultingCDI to a string up to 1st zero
              cdiString = ""
              null_i = self.resultingCDI.find(b'\0')
              terminate_i = len(self.resultingCDI)
              if null_i > -1:
                  terminate_i = min(null_i, terminate_i)
              cdiString = self.resultingCDI[:terminate_i].decode("utf-8")
              # print (cdiString)

              # and process that
              self.parse(cdiString)
              self.callback_msg("Done loading CDI.")

              # done


    def memoryReadFail(self, memo):
        print("memory read failed: {}".format(memo.data))


    def startElement(self, name, attrs):
        """See xml.sax.handler.ContentHandler documentation."""
        self._start_name = name
        self._start_attrs = attrs
        tab = "  " * len(self._tag_stack)
        print(tab, "Start: ", name)
        if attrs is not None and attrs :
            print(tab, "  Attributes: ", attrs.getNames())
        el = Element(name, attrs)
        self.callback_msg(
            "loaded: {}{}".format(tab, ET.tostring(el, encoding="unicode")))
        self._tag_stack.append(el)

    def endElement(self, name):
        """See xml.sax.handler.ContentHandler documentation."""
        indent = len(self._tag_stack)
        if indent:
            indent -= 1  # account for closing the tag
        tab = "  " * indent
        # print(tab, name, "content:", self._flushCharBuffer())
        print(tab, "End: ", name)
        if len(self._tag_stack):
            print(tab+"Warning: </{}> before any start tag"
                  .format(name))
            return
        top_el = self._tag_stack[-1]
        if name != top_el.tag:
            print(tab+"Warning: </{}> before </{}>".format(name, top_el.tag))
            return
        del self._tag_stack[-1]

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
    #         raise TypeError("Expected str, got {}".format(type(data).__name__))
    #     self._chunks.append(data)