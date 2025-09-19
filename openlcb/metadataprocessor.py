import os
import threading
import sys
import xml.sax  # noqa: E402
import xml.sax.handler
import xml.etree.ElementTree as ET

from enum import Enum
from logging import getLogger
from typing import Callable, Union
# from xml.sax.xmlreader import AttributesImpl  # for autocomplete only

from openlcb.canbus.canlink import CanLink
from openlcb.nodeid import NodeID
from openlcb.platformextras import (
    SysDirs,
    clean_file_name,
)
from openlcb.datagramservice import (
    DatagramReadMemo,
    DatagramService,
)
from openlcb.memoryservice import (
    MemoryReadMemo,
    MemoryService,
    MemorySpace,
)
# from openlcb.remotenodeprocessor import RemoteNodeProcessor


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
    # AttributesImpl[str] type hint fails on Python 3.8. For autocomplete:
    # attrs = AttributesImpl(attrs)
    # attrs_dict = attrs.__dict__  # may have private members, so:
    return {key: attrs.getValue(key) for key in attrs.getNames()}


class MetadataProcessor(xml.sax.handler.ContentHandler):
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

    def __init__(self, linkLayer: CanLink, mode: MemorySpace):
        self.canLink: CanLink = linkLayer
        caches_dir = SysDirs.Cache
        self._top_tag = "cdi"  # cdi or fdi (detected in startElement)
        self._myCacheDir = os.path.join(caches_dir, "python-openlcb")
        self._onElement = None
        self._mode = mode
        # self._mode = MemorySpace.Uninitialized  # Idle until datatype known
        # ^ In case some parsing step happens early,
        #   prepare these for _callback_msg.
        xml.sax.ContentHandler.__init__(self)
        self._stringTerminated = None  # None means no read is occurring.
        self._parser = xml.sax.make_parser()
        self._parser.setContentHandler(self)
        self._resultingCDI: bytearray = None

        self._realtime = True

        # region ContentHandler
        # self._chunks = []
        self._tag_stack = []
        # endregion ContentHandler

    @property
    def space(self) -> int:
        assert isinstance(self._mode, MemorySpace)
        return self._mode.value

    def onStart(self):
        self._cdi_offset = 0
        if self._resultingCDI is not None:
            raise ValueError(
                "A previous downloadCDI operation is in progress"
                " or failed (Set _resultingCDI to None first if failed)")
        self._resultingCDI = bytearray()

    def onStop(self):
        self._mode = MemorySpace.Uninitialized  # CDI no longer expected

    def _resetTree(self):
        self.etree = ET.Element("root")
        self._openEl = self.etree

    def _fireStatus(self, status, callback=None):
        """Fire status handlers with the given status."""
        if callback is None:
            callback = self._onElement
        if callback:
            print("OpenLCBNetwork callback_msg({})".format(repr(status)))
            callback({
                'status': status,
            })
        else:
            logger.warning("No callback, but set status: {}".format(status))

    def setElementHandler(self, handler: Callable):
        self._onElement = handler

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

    def startElement(self, name: str, attrs):
        """See xml.sax.handler.ContentHandler documentation."""
        # AttributesImpl[str] type hint fails on Python 3.8. For autocomplete:
        # attrs = AttributesImpl(attrs)
        tab = "  " * len(self._tag_stack)
        if name is not None:
            if name.lower() in ("cdi", "fdi"):
                self._top_tag = name.lower()
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
        'name' is "cdi" or the detected self._top_tag
        (case-insensitive). That notifies the downloadCDI caller that
        parsing is over, so that caller should end progress bar/other
        status tracking for downloadCDI in that case.

        Returns:
            dict: Reserved for use without events (doesn't need to be
                processed if self._onElement is set since that
                also gets the dict if 'done'). 'done' is only True if
                'name' is "cdi" or self._top_tag (case-insensitive).
        """
        event_d['done'] = False
        name = event_d.get('name')
        if not name or name.lower() != self._top_tag:
            # Not </cdi> nor other detected self._top_tag, so not done
            return event_d
        event_d['done'] = True  # done: past conditional return above
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

    # def characters(self, data: Union[bytearray, bytes, List[int]]):
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
