from collections import OrderedDict
import os
import xml.sax  # noqa: E402
import xml.sax.handler
import xml.etree.ElementTree as ET

from logging import getLogger
from typing import Callable, List, Union
# from xml.sax.xmlreader import AttributesImpl  # for type hints, for autocomplete only in this case
import xml.sax.xmlreader  # for type hints, for autocomplete only in this case

from openlcb import emit_cast
from openlcb.canbus.canlink import CanLink
from openlcb.cdimemo import CDIMemo
from openlcb.dataprocessor import DataFormat, DataProcessor
from openlcb.nodeid import NodeID
from openlcb.platformextras import (
    SysDirs,
    clean_file_name,
)
from openlcb.memoryservice import (
    MemoryReadMemo,
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


def attrs_to_ordered(attrs: xml.sax.xmlreader.AttributesImpl):
    od = OrderedDict()
    for name in attrs.getNames():
        od['name'] = attrs[name]
    return od


def format_of_space(space):
    assert isinstance(space, MemorySpace)
    if space == MemorySpace.CDI:
        return DataFormat.XML
    elif space == MemorySpace.FDI:
        return DataFormat.XML
    raise NotImplementedError(emit_cast(space))


class XMLDataProcessor(xml.sax.handler.ContentHandler, DataProcessor):
    """Collect & process consecutive XML data from each incoming MemoryReadMemo
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
        _data (str): CDI document being collected from the
            network stream (successful read request memo handler). To
            ensure valid state:
            - Initialize to None at program start, end download, or
              failed download.
            - Assert is None at start of download, then set to
              bytearray().
        _space (int): Space containing the CDI itself (not data
            described by CDI).
        _tmp_space (int|None): What space we are currently on
            (of data described by Element(s), not of XML data itself)
        _tmp_address (int|None): Where we are in the memory space
            (starting at origin, and calculated using offset and/or size
            of start tags).
    """
    XML_TOP_TAGS = ("cdi", "fdi")

    def __init__(self, linkLayer: CanLink, space: MemorySpace):
        self.canLink: CanLink = linkLayer
        caches_dir = SysDirs.Cache
        self._space: Union[MemorySpace, None] = None
        self._openEl: Union[ET.Element, None] = None
        self._top_tag = "cdi"  # cdi or fdi (detected in startElement)
        self._myCacheDir = os.path.join(caches_dir, "python-openlcb")
        self._tmp_space = None  # type: int|None
        self._tmp_address = None  # type: int|None
        assert isinstance(space, MemorySpace)
        self.setSpace(space)  # also sets _format
        # ^ Idle until DataFormat is known
        # ^ In case some parsing step happens early,
        #   prepare these for _callback_msg.
        xml.sax.ContentHandler.__init__(self)
        DataProcessor.__init__(self)
        self._stringTerminated = None  # type: Union[bool, None]
        # ^ None means no read is occurring.
        if self._format != DataFormat.XML:
            raise NotImplementedError(
                "This class only handles XML. Make a separate subclass for {}"
                .format(self._format))
        self._parser = xml.sax.make_parser()  # type: xml.sax.xmlreader.XMLReader  # noqa: E501
        self._parser.setContentHandler(self)
        self._data: Union[bytearray, None] = None

        self._realtime = True

        # region ContentHandler
        self._chunks = []
        self._tag_stack = []  # type: List[CDIMemo]
        # endregion ContentHandler
        self.acdi = False

    def setSpace(self, space: MemorySpace):
        self._space = space
        self._format = format_of_space(space)

    @property
    def format(self) -> DataFormat:
        assert isinstance(self._format, DataFormat), \
            "expected DataFormat, got {}".format(emit_cast(self._format))
        return self._format

    @property
    def space(self) -> MemorySpace:
        """The memory space of the XML itself. See also
        `space` in event dict in startElement, and _tmp_space."""
        assert isinstance(self._space, MemorySpace)
        return self._space

    def onStatusMemo(self, cm: CDIMemo) -> bool:
        """Handle memo with status that doesn't affect tag stack/scope.
        (Implement in subclass)
        Returns:
            bool: True if handled.
        """
        return False

    def onPushScope(self, cm: CDIMemo) -> bool:
        """Handle memo being added to _tag_stack
        which may already be pushed if a thread is being used
        for download but the UI is on the main thread.
        (Implement in subclass)
        Returns:
            bool: True if handled.
        """
        return False

    def onPopScope(self, cm: CDIMemo) -> bool:
        """Handle memo being popped from _tag_stack
        which may already be popped if a thread is being used
        for download but the UI is on the main thread.
        (Implement in subclass)
        Returns:
            bool: True if handled.
        """
        return False

    def onStart(self):
        # self._cdi_offset = 0  # Instead see memo.address (which is
        #   incremented on _memoryReadSuccess or custom memory read
        #   handler).
        if self._data is not None:
            raise ValueError(
                "A previous downloadCDI operation is in progress"
                " or failed (Set _data to None first if failed)")
        self._data = bytearray()

    def onStop(self):
        self._format = DataFormat.EOF  # no data expected

    def _resetTree(self):
        self.etree = ET.Element("root")
        self._openEl = self.etree

    def _fireStatus(self, status,
                    callback: Union[Callable[[CDIMemo], bool], None] = None):
        """Fire status handlers with the given status."""
        if callback is None:
            callback = self.onStatusMemo
        if callback:
            print("OpenLCBNetwork callback_msg({})".format(repr(status)))
            callback(CDIMemo(status=status))
        else:
            logger.warning("No callback, but set status: {}".format(status))

    def _feedNext(self, memo: MemoryReadMemo):
        """Handle partial CDI XML (any packet except last)
        The last packet is not yet reached, so don't parse (but
        feed if self._realtime, which may trigger a
        callback)

        Args:
            memo (MemoryReadMemo): successful read memo containing data.
        """
        assert self._data is not None
        self._data += memo.data
        partial_str = memo.data.decode("utf-8")
        if self._realtime:
            self._parser.feed(partial_str)  # may call startElement/endElement

    def _feedLast(self, memo: MemoryReadMemo):
        """Handle end of CDI XML (last packet)
        End of data, so parse (or feed if self._realtime)

        Args:
            memo (MemoryReadMemo): successful read memo containing data.
        """
        partial_str = memo.data.decode("utf-8")
        # save content
        assert self._data is not None
        self._data += memo.data
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
            null_i = self._data.find(b'\0')
            terminate_i = len(self._data)
            if null_i > -1:
                terminate_i = min(null_i, terminate_i)
            cdiString = self._data[:terminate_i].decode("utf-8")
            # print (cdiString)
            # self.parse(cdiString)  # no such method
            # self._parser.parse(cdiString)  # urllib.error.URLError
            # ^ startElement, endElement, etc. all consecutive using parse
            # ^ urllib.error.URLError: <urlopen error unknown url type:
            #   ?xml version="1.0" encoding="utf-8"?>
            xml.sax.parseString(cdiString, self)
            # self._fireStatus("Done loading CDI.")
            cm = CDIMemo()
            cm.done = True  # 'done' and not 'error' means got all
            self.onStatusMemo(cm)
        if self._realtime:
            self._parser.feed(partial_str)  # may call startElement/endElement
        # memo = MemoryReadMemo(memo)
        path = self.cache_cdi_path(memo.nodeID)
        with open(path, 'w') as stream:
            if cdiString is None:
                cdiString = self._data.rstrip(b'\0').decode("utf-8")
            stream.write(cdiString)
            print('Saved {}'.format(repr(path)))
        self._data = None  # Ensure isn't reused for more than one doc

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

    def startElement(self, name: str,
                     attrs: xml.sax.xmlreader.AttributesImpl):
        """See xml.sax.handler.ContentHandler documentation."""
        tab = "  " * len(self._tag_stack)
        if name is not None:
            if name.lower() in ("cdi", "fdi"):
                self._top_tag = name.lower()
            elif name.lower() == "acdi":
                self.acdi = True
        attrib = attrs_to_dict(attrs)
        origin = attrib.get('origin')
        offset = attrib.get('offset')
        parts = [tab, "Start: ", name]
        if origin is not None:
            parts.append(f"origin={origin}")
        if offset is not None:
            parts.append(f"offset={offset}")
        logger.debug(*parts)
        if attrs is not None and attrs :
            logger.debug(tab, "  Attributes: ", attrs.getNames())
        # el = ET.Element(name, attrs)

        # NOTE: self._openEl is root if this is the first tag.
        assert self._openEl is not None, "_openEl wasn't even set to etree yet"

        el = ET.SubElement(self._openEl, name, attrib)
        parent_cm = None
        if self._tag_stack:
            parent_cm = self._tag_stack[-1]
        cm = CDIMemo(tag=name, element=el, parent=parent_cm)
        if name == "segment":
            self._tmp_space = attrib.get('space')
            self._tmp_address = int(attrib.get('origin', 0))
            if self._tmp_space is None:
                raise AttributeError("Node didn't specify space for segment")
            else:
                self._tmp_space = int(self._tmp_space)
        else:
            offset = attrib.get('offset')
            if offset is not None:
                offset = int(offset)
                if self._tmp_address is None:
                    raise AttributeError(
                        f"Node specifies {name} offset before segment origin")
                self._tmp_address += offset
        cm.address = self._tmp_address  # May be None if after /segment

        self.onPushScope(cm)

        # self._callback_msg(
        #     "loaded: {}{}".format(tab, ET.tostring(el, encoding="unicode")))
        self._tag_stack.append(cm)
        self._openEl = el
        size = attrib.get('size')
        if size is not None:
            if name == "segment":
                logger.warning("Node segment should not specify size.")
            if self._tmp_address is None:
                raise AttributeError(
                    f"Node has {name} variable before segment origin")
            self._tmp_address += int(size)

    def checkDone(self, cm: CDIMemo):
        """Notify the caller if parsing is over.
        Calls self.onStatusMemo with `'done': True` in the argument if
        'name' is "cdi" or the detected self._top_tag
        (case-insensitive). That notifies the downloadCDI caller that
        parsing is over, so that caller should end progress bar/other
        status tracking for downloadCDI in that case.

        Returns:
            CDIMemo: Reserved for synchronous use.
        """
        cm.done = False
        if not cm.tag or cm.tag.lower() != self._top_tag:
            # Not </cdi> nor other detected self._top_tag, so not done
            return cm
        cm.done = True  # done: past conditional return above
        self.onStatusMemo(cm)
        return cm

    def endElement(self, name: str):
        """See xml.sax.handler.ContentHandler documentation.
        Called on end tag or after startElement on self-closing tag.
        """
        indent = len(self._tag_stack)
        tab = "  " * indent
        # top_cm = self._tag_stack.pop()  # raises index error if empty
        top_cm = self._tag_stack[-1] if len(self._tag_stack) else None
        top_el = top_cm.element if top_cm is not None else None
        if top_el is None:
            pass  # see warning case further down
        elif name != top_el.tag:
            pass  # see warning case further down
        elif indent > 0:  # top element found and indent not 0
            indent -= 1  # dedent since scope ended
        # print(tab, name, "content:", self._flushCharBuffer())
        logger.debug(tab, "End: ", name)
        if name == "segment":
            self._tmp_space = None
            self._tmp_address = None
        cm = None
        if top_cm is not None:
            top_cm.tag = name
            cm = top_cm
        else:
            cm = CDIMemo(tag=name)
            cm.stray = True
        cm.end = True

        if not self._tag_stack:
            cm.error = "</{}> before any start tag".format(name)
            print(tab+"Warning: {}".format(cm.error))
            self.checkDone(cm)
            return
        if (top_el is None):
            cm.error = "stray </{}> before top element".format(name)
            print(tab+"Warning: {}".format(cm.error))
            self.checkDone(cm)
            return
        elif name != top_el.tag:
            cm.error = (
                "</{}> before top tag <{} ...> closed"
                .format(name, top_el.tag if top_el else None))
            print(tab+"Warning: {}".format(cm.error))
            self.checkDone(cm)
            return
        del self._tag_stack[-1]
        if self._tag_stack:
            self._openEl = self._tag_stack[-1].element
        else:
            self._openEl = self.etree
        if len(self._tag_stack) and cm.stray:
            cm.parent = self._tag_stack[-1]
            cm.element = top_el
        # else parent & element should already have been set in startElement
        _ = self.checkDone(cm)
        cm.content = self._flushCharBuffer()
        self.onPopScope(cm)

    def _flushCharBuffer(self):
        """Decode the buffer, clear it, and return all content.
        See xml.sax.handler.ContentHandler documentation.
        - Use this in endElement so that the callback gets all content.

        Returns:
            str: The content of the bytes buffer decoded as utf-8.
        """
        s = ''.join(self._chunks)
        self._chunks.clear()
        return s

    def characters(self, content: str):
        """Received characters handler.
        See xml.sax.handler.ContentHandler documentation.

        Args:
            content (str): any content (between tags)
        """
        # Union[bytearray, bytes, List[int]]
        if not isinstance(content, str):
            raise TypeError(
                "Expected str, got {}".format(type(content).__name__))
        self._chunks.append(content)
